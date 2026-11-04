#!/usr/bin/env python3
"""
自由玩家压力测试 (stress_freeplay.py)

模拟一个"自由发挥"的玩家连续游玩 2000 回合（回合数可配），全程走**真实 MCP stdio 通道**
（起一个 mcp_server.py 子进程 + ClientSession，和 ZCode / opencode 接到的是同一条路）。

玩家行为分布（可配置，默认贴近真人习惯）：
- 探索：travel 到已知/新地点 + narration_context + 随机 social + karma（善或偷窃，看玩家"心态"）
- 切磋：和某个 NPC 开打，连打到对方倒下；自己血少就买疗伤散 / 回满
- 买卖：看行情买丹、低价囤货、高价抛售（验证价格不会崩）
- 突破：阶段性尝试 advance；失败就 snapshot→restore 回退重刷（玩家惯用的"试到成"心态）
- 死局：血量打空时"复活"（新命续玩，玩家口头禅"我还活着"）
- 记忆：周期性 write_summary / recap / recall；NPC 死绝后 add_npc 让江湖有人气
- 习惯验证：混入少量"错招"（坏 location / 负数数量 / 概率 0）确认引擎报错而不是崩

不变量（每轮全量断言，任何一条破了立即记录）：
- 状态文件可解析、entity 的 hp/gold 不出现负数、market 价格 0<=price<=base*3 且 base 不被砸穿
- 事件归档正常（event_log 不超 keep，archived_events 只增不减）
- 工具错误率（预期只有故意打错的那几条）

用法:  python scripts/stress_freeplay.py [回合数=2000]
退出码: 0 = 全绿；1 = 有不变量破坏或错误率超标；2 = 缺 mcp SDK
"""

import asyncio
import builtins
import json
import os
import random
import sys
import tempfile
import time

try:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
except ImportError:
    print('缺少 mcp SDK。请先安装: pip install -e ".[mcp]"')
    sys.exit(2)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, 'mcp_server.py')
SETTING = os.path.join(ROOT, 'settings', '玄枢界.setting.json')
DEFAULT_TURNS = 2000
REPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'last_stress_report.json')

KNOWN_LOCS = ['临川城', '听霄城', '旧枢台废墟', '南屏药谷', '渡口']
BAD_LOCATIONS = ['不存在的楼', '墟界裂口']


def data(result):
    for attr in ('structuredContent', 'structured_content'):
        sc = getattr(result, attr, None)
        if isinstance(sc, dict):
            return sc.get('result', sc) if set(sc) == {'result'} else sc
    for c in getattr(result, 'content', None) or []:
        if getattr(c, 'type', '') == 'text':
            try:
                return json.loads(c.text)
            except Exception:  # aqg: top-level boundary —— 返回体非 JSON 时回退原文，不中断压测
                return c.text
    return None


def is_err(result):
    return bool(getattr(result, 'isError', False) or getattr(result, 'is_error', False))


class Player:
    """自由发挥的玩家：心态随血量/身家变化，行为有习惯、有随机、偶尔犯傻。"""

    def __init__(self, rng, state):
        self.rng = rng
        self.state = state
        self.phase = 'explore'
        self.phase_left = 3
        self.stage_target = 0          # 期望达到的突破次数
        self.npc_seq = 0

    def _player(self):
        return self.state['entities']['player']

    def _alive_npcs(self):
        return [k for k, e in self.state.get('entities', {}).items()
                if k != 'player' and e.get('hp', 0) > 0]

    def plan(self, tick):
        self.phase_left -= 1
        if self.phase_left <= 0:
            pool = ['explore'] * 3 + ['spar'] * 2 + ['market'] * 2 + ['social'] + ['introspect']
            if tick >= 40 and tick % 40 == 0:
                pool += ['breakthrough'] * 3
            self.phase = self.rng.choice(pool)
            self.phase_left = self.rng.randint(2, 5)

        p = self._player()
        if p.get('hp', 0) < p.get('hp_max', 1) * 0.25:
            self.phase = 'market'      # 血少先买药续命
        if tick == 1 and self.phase != 'explore':
            self.phase = 'explore'

    @property
    def label(self):
        return self.phase


async def run(turns: int, quiet: bool = False):
    rng = random.Random(20261014)
    t0 = time.time()
    calls, errors = {}, {}
    invariant_fail = []

    tmp = tempfile.mkdtemp(prefix='ww-stress-')
    state_path = os.path.join(tmp, 'xuanshu.save.json')

    params = StdioServerParameters(
        command=sys.executable, args=[SERVER], cwd=ROOT,
        env={**os.environ, 'WORLD_GAMES_STATE_ROOT': tempfile.gettempdir()},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(tool, args=None, allow_error=False):
                args = args or {}
                calls[tool] = calls.get(tool, 0) + 1
                try:
                    r = await session.call_tool(tool, args)
                except Exception as e:  # aqg: top-level boundary —— 工具报错计入 errors 统计，继续跑满轮次
                    errors[tool] = errors.get(tool, 0) + 1
                    msg = str(e)
                    # BaseExceptionGroup 是 3.11+ 的内置名；3.10 上直接引用会 NameError，
                    # 把"工具报错"变成"压测崩掉"，掩盖真实错误率。
                    _BEG = getattr(builtins, 'BaseExceptionGroup', None)
                    if _BEG is not None and isinstance(e, _BEG):
                        sub = list(e.exceptions)
                        msg = 'ExceptionGroup(%d): %s' % (len(sub),
                                                          '; '.join(str(x)[:120] for x in sub[:3]))
                    invariant_fail.append({'turn': None, 'tool': tool, 'crash': msg[:200]})
                    return None
                if is_err(r):
                    if allow_error:
                        return {'__expected_error__': True}
                    errors[tool] = errors.get(tool, 0) + 1
                    detail = ''
                    try:
                        detail = str(r.content[0].text)[:200] if r.content else ''
                    except Exception:  # aqg: top-level boundary —— 错误详情取不到就不取，不影响统计
                        pass
                    invariant_fail.append({'tool': tool, 'args': {k: str(v)[:60] for k, v in args.items()},
                                           'error': detail})
                    return None
                return data(r)

            def check(state, note, ok, detail=''):
                if not ok:
                    invariant_fail.append({'note': note, 'detail': str(detail)[:160]})

            # ── 开局：设定包一键载入 ──
            ls = await call('load_setting', {'path': SETTING, 'state_path': state_path, 'seed': 777})
            check(ls, 'load_setting 开局', isinstance(ls, dict) and ls.get('entities') == 9)
            await call('configure', {'event_log_keep': 120, 'recap_budget_chars': 1200,
                                     'milestone_keep': 400})
            await call('narration_context', {'scene_text': '临川城·旧枢台', 'recent': 10})

            player = Player(rng, {})
            snap_saved = None
            new_locs_seen = set()
            recap_hits, summaries, recalls = 0, 0, 0

            for turn in range(1, turns + 1):
                # 状态读法：每 10 回合经 MCP 拉一次全量状态做不变量断言并刷新决策依据；
                # 轮间用各工具自己的返回（它们都带 _tick 与最新数值），省 90% 的传输。
                if turn % 10 == 1:
                    st = await call('read_state', {})
                    check(st, 'read_state', isinstance(st, dict) and 'entities' in st
                          and 'player' in st.get('entities', {})
                          and isinstance(st.get('market'), dict) and bool(st.get('market')),
                          'keys=%s' % (sorted(st)[:6] if isinstance(st, dict) else st))
                    player.state = st or {}
                else:
                    player.state = player.state or {}

                # 不变量（随刷新执行）
                if turn % 10 == 1:
                    p = (player.state.get('entities') or {}).get('player', {})
                    check(player.state, 'hp/gold 非负',
                          p.get('hp', 0) >= 0 and p.get('gold', 0) >= 0
                          and all(e.get('hp', 0) >= 0 and e.get('gold', 0) >= 0
                                  for e in player.state.get('entities', {}).values()))
                    mkts = (player.state.get('market') or {})
                    checked = 0
                    for items in mkts.values():
                        for it in items.values():
                            base, price = int(it.get('base_price', 0)), int(it.get('price', 0))
                            if not (base > 0 and 0 <= price <= base * 3 + 1):
                                checked = -1
                            elif checked >= 0:
                                checked += 1
                    # 市场必须存在且有商品可检——空集合会让"全称命题"恒真
                    check(player.state, '市场价格有界（市场非空 且 0<=price<=3*base）',
                          bool(mkts) and checked > 0,
                          '市场 %d 个 · 合格商品 %d' % (len(mkts), max(checked, 0)))

                p = (player.state.get('entities') or {}).get('player', {})
                player.plan(turn)
                npc_ids = player._alive_npcs()
                loc = p.get('location', '临川城')

                # ── 行动（按玩家心态） ──
                if player.phase == 'explore':
                    known = list((player.state.get('codex') or {}).get('locations', [loc]))
                    target = rng.choice(KNOWN_LOCS + known) if rng.random() < 0.7 else \
                        rng.choice(KNOWN_LOCS)
                    r = await call('travel', {'location': target, 'note': '闲逛'})
                    if r and r.get('location') not in new_locs_seen:
                        new_locs_seen.add(r.get('location'))
                    await call('narration_context', {'scene_text': target, 'recent': 8})
                    if npc_ids and rng.random() < 0.3:
                        await call('social', {'actor': 'player', 'target': rng.choice(npc_ids),
                                              'event': rng.choice(['praise', 'cooperate', 'gift']),
                                              'intensity': 1})
                    if rng.random() < 0.15:
                        # 善心 or 偷心
                        kt = rng.choice(['help_innocent', 'theft'])
                        await call('karma', {'actor': 'player', 'karma_type': kt,
                                              'victim': 'shi_sanniang' if kt == 'theft' else None})
                elif player.phase == 'spar':
                    if not npc_ids:
                        # 江湖不能没人：现场生成新散修（无角色卡也能入局）
                        player.npc_seq += 1
                        r = await call('spawn_npc', {'id': 'npc_new_%d' % player.npc_seq,
                                                     'name': '路过客%d' % player.npc_seq,
                                                     'faction': '散修',
                                                     'attrs': {'str': rng.randint(9, 15),
                                                               'dex': rng.randint(9, 15),
                                                               'int': rng.randint(8, 14),
                                                               'con': rng.randint(8, 14),
                                                               'cha': rng.randint(8, 13)},
                                                     'level': '淬体%d段' % rng.randint(3, 9),
                                                     'hp': 80, 'gold': 50,
                                                     'location': loc,
                                                     'desc': '新来的散修'})
                        check(r, 'spawn_npc 新人物入局',
                              bool(r) and r.get('entity_id') == 'npc_new_%d' % player.npc_seq,
                              (r or {}).get('entity_id'))
                        npc_ids = player._alive_npcs()
                    if npc_ids:
                        target = rng.choice(npc_ids)
                        rounds = 0
                        while rounds < 4:
                            r = await call('combat', {'attacker': 'player', 'defender': target,
                                                      'action_type': rng.choice(['attack', 'heavy'])})
                            rounds += 1
                            if r is None:
                                break
                            # 用引擎返回的 attacker_hp 刷新本地决策副本（轮间不重拉全量状态）
                            if r.get('attacker_hp') is not None:
                                lp = player.state.get('entities', {}).get('player', {})
                                lp['hp'] = r['attacker_hp']
                            if r.get('defender_dead') or r.get('fled') is not None:
                                break
                            if (player.state.get('entities', {}).get(target, {}).get('hp', 0) <= 0):
                                break
                elif player.phase == 'market':
                    mkt = (player.state.get('market') or {}).get(loc) or {}
                    # 血少先买药回血（use_item：引擎结算，花的是钱不是白拿；金数不足/缺货属预期报错）
                    if p.get('hp', 0) < p.get('hp_max', 1) * 0.9:
                        for key, it in mkt.items():
                            if '丹药' in it.get('type', '') or '药' in it.get('type', ''):
                                r = await call('use_item', {'item': key, 'quantity': 1,
                                                           'location': loc}, allow_error=True)
                                if r and not r.get('__expected_error__'):
                                    # 把引擎结算的 hp/gold 同步进本地决策副本
                                    lp = player.state.get('entities', {}).get('player', {})
                                    lp['hp'] = r.get('hp', lp.get('hp', 0))
                                    lp['gold'] = r.get('gold', lp.get('gold', 0))
                                    break
                    # 低价囤 / 高价卖（用行情差做判断——真玩家心态）
                    for key, it in mkt.items():
                        ratio = it['price'] / max(1, it.get('base_price', it['price']))
                        if ratio < 0.85 and p.get('gold', 0) > it['price'] * 3 and rng.random() < 0.5:
                            r = await call('trade', {'location': loc, 'item': key, 'direction': 'buy',
                                                     'quantity': 2})
                            if r and r.get('success'):
                                lp = player.state.get('entities', {}).get('player', {})
                                lp['gold'] = lp.get('gold', 0) - int(r.get('total_cost', 0))
                        elif ratio > 1.15 and rng.random() < 0.4:
                            r = await call('trade', {'location': loc, 'item': key, 'direction': 'sell',
                                                     'quantity': 1})
                            if r and r.get('success'):
                                lp = player.state.get('entities', {}).get('player', {})
                                lp['gold'] = lp.get('gold', 0) + int(r.get('total_cost', 0))
                elif player.phase == 'social':
                    if npc_ids:
                        await call('social', {'actor': 'player', 'target': rng.choice(npc_ids),
                                               'event': rng.choice(['help', 'praise', 'cooperate']), 'intensity': 1})
                elif player.phase == 'introspect':
                    await call('narrative', {})
                    await call('status', {})
                    await call('merit', {'aid': 0.6, 'sincerity': 0.5})
                    if rng.random() < 0.5:
                        rc = await call('recall', {'query': rng.choice(['突破', '杀', '抵达'])})
                        if rc and rc.get('matches'):
                            recalls += 1
                elif player.phase == 'breakthrough':
                    player.stage_target += 1
                    snap_saved = await call('snapshot', {'label': 'before_bk%d' % turn})
                    # stage 缺键即 0（引擎 advance 同样按 get("stage", 0) 起算）
                    st_bk = await call('read_state', {})
                    stage_before = int(((st_bk or {}).get('entities') or {}).get('player', {}).get('stage', 0) or 0)
                    # 按真实等级算下一步（阶梯校验会拒掉"同阶同名/倒退/跳阶"）
                    _cur = (((await call('read_state', {})) or {}).get('entities') or {}).get('player', {})
                    _cur_lvl = str(_cur.get('level') or '淬体七段')
                    _lvl = ['淬体八段', '引元境·初层', '引元境·中层', '引元境·后层',
                            '引元境·圆满', '元府境·初层', '元府境·中层', '元府境·后层',
                            '元府境·圆满', '元丹境·初层', '元丹境·中层', '元丹境·后层',
                            '元丹境·圆满', '化元境·初层', '化元境·中层', '通玄境·初层',
                            '玄台境·初层', '玄婴境·初层', '破妄境·初层', '登枢']
                    _idx = 0
                    for _i, _n in enumerate(_lvl):
                        if _cur_lvl.startswith(_n.split('·')[0]) or _n.split('·')[0] in _cur_lvl:
                            _idx = _i + 1
                    _pick = _lvl[min(_idx, len(_lvl) - 1)]
                    adv = await call('advance', {'next_level': _pick, 'insight': rng.uniform(0.4, 0.95)})
                    if adv and adv.get('success'):
                        st_now = await call('read_state')
                        check(st_now, '突破成功则 stage 恰好 +1',
                              int(st_now['entities']['player'].get('stage', 0) or 0) == stage_before + 1,
                              'stage %s -> %s' % (stage_before, st_now['entities']['player'].get('stage')))
                    elif snap_saved:
                        # 失败：老玩家习惯——回退存档点重来（stage 不应被失败污染）
                        rs = await call('restore', {'snapshot_path': snap_saved['snapshot']})
                        st_rb = await call('read_state', {}) if rs else None
                        stage_after = int(((st_rb or {}).get('entities') or {}).get('player', {}).get('stage', 0) or 0)
                        check(rs, '失败回退后 stage 保持',
                              bool(rs) and stage_after == stage_before,
                              'stage before=%s after=%s' % (stage_before, stage_after))

                # 记忆维护：每 25 回合摘要、每 50 回合回顾
                if turn % 25 == 0:
                    await call('write_summary', {'text': '第%d回合·%s 阶段（阶段累计 %d，当前 %s）'
                                                 % (turn, player.label, player.stage_target, loc)})
                    summaries += 1
                if turn % 50 == 0:
                    rc = await call('recap', {})
                    if rc:
                        recap_hits += 1

                # 每 15 回合混入一条"错招"（验证优雅报错）
                if turn % 15 == 7:
                    bad = rng.random()
                    if bad < 0.4:
                        await call('travel', {'location': rng.choice(BAD_LOCATIONS)}, allow_error=True)
                    elif bad < 0.8:
                        mkt2 = (player.state.get('market') or {}).get(loc) or {}
                        key0 = next(iter(mkt2), 'liaoshang_san')
                        await call('trade', {'location': loc, 'item': key0, 'direction': 'buy',
                                              'quantity': -3}, allow_error=True)
                    else:
                        await call('narrative_weight', {'probability': 0}, allow_error=True)

                # 濒死：引擎保证玩家气血 >= 1 并自动记账（不再靠本地改内存假装复活）
                p = player.state.get('entities', {}).get('player', {})
                if p.get('hp', 0) <= 0:
                    invariant_fail.append({'note': '玩家气血归零（濒死保护失效）', 'turn': turn,
                                           'detail': 'hp=%s' % p.get('hp')})

                r = await call('tick', {})
                if r is None and turn == 1:
                    invariant_fail.append({'note': '第一轮 tick 失败，中止'})
                    break

            # ── 终局断言 ──
            st = await call('read_state', {})
            check(st, '终局状态可解析', isinstance(st, dict) and 'entities' in st
                  and 'player' in st.get('entities', {}),
                  'keys=%s' % (sorted(st)[:6] if isinstance(st, dict) else st))
            if st:
                player.state = st
                arch = int(st.get('archived_events', 0))
                keep = int((st.get('config') or {}).get('event_log_keep', 200))
                check(st, 'event_log 不超保留量', len(st.get('event_log', [])) <= keep,
                      '%d/%d' % (len(st.get('event_log', [])), keep))
                # 归档按世代分文件（回退安全），所以"总归档行数"= 所有世代文件之和，
                # 应与状态里累计的 archived_events 严格相等，且必须真的发生过归档。
                import glob as _glob
                arch_files = ([state_path + '.log.jsonl']
                              + sorted(_glob.glob(state_path + '.log.*.jsonl')))
                lines = 0
                for af in arch_files:
                    if os.path.exists(af):
                        lines += sum(1 for _ in open(af, encoding='utf-8'))
                check(st, 'archived_events 与全部世代归档行数之和严格相等且 > 0',
                      arch > 0 and lines == arch,
                      'archived_events=%d 各世代行数合计=%d 文件数=%d'
                      % (arch, lines, len([f for f in arch_files if os.path.exists(f)])))

            total_calls = sum(calls.values())
            real_errors = sum(errors.values())
            state_size = os.path.getsize(state_path) if os.path.exists(state_path) else 0

            # 内存占用：长局最怕"跑几百轮后 RSS 一路涨"。用 psutil 取本进程 RSS；
            # 没有 psutil 时退化为 None（不阻断压测）。
            try:
                import psutil
                rss_mb = round(psutil.Process(os.getpid()).memory_info().rss / 1048576, 1)
            except Exception:  # aqg: top-level boundary —— 可选依赖缺失不该影响压测结论
                rss_mb = None

            report = {
                'turns_requested': turns,
                'turns_completed': turn,
                'wall_seconds': round(time.time() - t0, 1),
                'tool_calls': total_calls,
                'by_tool': calls,
                'unexpected_errors': real_errors,
                'error_rate': round(real_errors / max(1, total_calls), 5),
                'summaries': summaries, 'recaps': recap_hits, 'recalls': recalls,
                'breakthroughs_attempted': player.stage_target,
                'new_locations': sorted(new_locs_seen),
                'state_file_bytes': state_size,
                'rss_mb': rss_mb,
                'invariant_failures': invariant_fail[:50],
                'invariant_fail_count': len(invariant_fail),
                'tmp': tmp,
            }
            with open(REPORT, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            print(json.dumps({k: v for k, v in report.items() if k != 'invariant_failures'},
                             ensure_ascii=False, indent=2))
            for bad in invariant_fail[:20]:
                print('  VIOLATION: %s' % json.dumps(bad, ensure_ascii=False))
            ok = (not invariant_fail) and (report['turns_completed'] == turns)
            print('\n%d/%d 轮完成 · %d 次工具调用 · 意外错误 %d · 不变量破坏 %d · %.1fs'
                  % (report['turns_completed'], turns, total_calls, real_errors,
                     len(invariant_fail), report['wall_seconds']))
            return 0 if ok else 1


if __name__ == '__main__':
    n = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_TURNS
    quiet = '--quiet' in sys.argv
    sys.exit(asyncio.run(run(n, quiet=quiet)))
