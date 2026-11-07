#!/usr/bin/env python3
"""
MCP 服务器端到端验证 (verify_mcp_stdio.py)

起一个真实的 stdio MCP 服务进程，按「设定 → 建世界 → 打一局」的完整流程调用全部工具，
并验证两件关键性质：
  1. 所有数值结算都由引擎完成、状态落盘可续跑（Agent 无法绕过引擎）
  2. 同种子 + 同行动序列 → 结果完全一致（可复现）

用法:  python scripts/verify_mcp_stdio.py
退出码: 0 = 全绿；1 = 有失败项；2 = 缺少 mcp SDK
"""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile

try:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
except ImportError:
    print('缺少 mcp SDK。请先安装: pip install -e ".[mcp]"')
    sys.exit(2)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, 'mcp_server.py')

EXPECTED_TOOLS = {
    'world_schema', 'world_init', 'world_open', 'read_state', 'combat', 'trade',
    'social', 'karma', 'tick', 'narrative', 'status', 'merit', 'narrative_weight',
    'narration_context', 'character_card_read', 'add_character', 'import_lorebook',
    'snapshot', 'restore', 'travel', 'open_panel', 'load_setting',
    'advance', 'recall', 'write_summary', 'recap', 'configure',
    'use_item', 'spawn_npc', 'model', 'model_list', 'world_state', 'publish_prose',
    'pending_actions', 'playbook_info', 'quest_status', 'quest_advance',
    'lore_lookup', 'failure_tick',
    # v1.2.0 通用游戏层
    'roll', 'game_profile', 'game_adjust', 'game_tag', 'game_sheet',
    'context_remember', 'context_search', 'context_forget', 'context_pack',
    'context_known', 'context_tell', 'combat_preview',
    'session_list', 'session_new', 'session_switch', 'session_snapshot',
    'session_manage', 'session_import', 'close_panel',
    # v1.4.0 体系与模板层
    'system_define', 'system_run', 'system_status', 'system_remove', 'system_schema',
    'templates_list', 'template_info', 'template_apply', 'template_start',
}

RESULTS = []


def check(name, ok, note=''):
    RESULTS.append(bool(ok))
    print('%s  %-46s %s' % ('PASS' if ok else 'FAIL', name, note))


def data(result):
    """兼容 structured 与文本两种返回形态，取出工具返回的 payload。"""
    for attr in ('structuredContent', 'structured_content'):
        sc = getattr(result, attr, None)
        if isinstance(sc, dict):
            return sc.get('result', sc) if set(sc) == {'result'} else sc
    for c in getattr(result, 'content', None) or []:
        if getattr(c, 'type', '') == 'text':
            try:
                return json.loads(c.text)
            except Exception:
                return c.text
    return None


def is_err(result):
    return bool(getattr(result, 'isError', False) or getattr(result, 'is_error', False))


# 一局武侠小世界的「设定」，作为 world_init 的入参
SETTING = {
    'world': {'name': '测试江湖', 'era': '江湖历元年',
              'location_desc': '临江茶棚，竹帘低垂，江水声隐约可闻。'},
    'player': {'name': '试剑人', 'faction': '散人',
               'attrs': {'str': 14, 'dex': 12, 'int': 11, 'con': 10, 'cha': 9},
               'level': '三流', 'hp': 60, 'hp_max': 60, 'mp': 10, 'mp_max': 10,
               'gold': 200, 'location': '临江茶棚'},
    'entities': [
        {'id': 'scout', 'name': '黑衣探子', 'faction': '不明',
         'attrs': {'str': 10, 'dex': 11, 'int': 9, 'con': 8, 'cha': 6},
         'level': '凡人', 'hp': 40, 'hp_max': 40, 'gold': 30, 'location': '临江茶棚'},
        {'id': 'vendor', 'name': '茶棚老板', 'faction': '市井',
         'attrs': {'str': 7, 'dex': 8, 'int': 12, 'con': 9, 'cha': 13},
         'level': '凡人', 'hp': 35, 'hp_max': 35, 'gold': 150, 'location': '临江茶棚',
         'desc': '茶棚老板，眼睛很尖，谁欠他两文钱都记得。',
         'personality': '和气但不吃亏；喜欢听人讲外面的事。',
         'speech': '「茶凉了就换一碗，人走了就不必了。」'},
    ],
    'market': [{'location': '临江茶棚', 'items': [
        {'key': 'chun_cha', 'name': '春茶', 'price': 30, 'supply': 20, 'base_price': 30,
         'type': '饮品', 'desc': '解渴'},
        {'key': 'jinchuang_yao', 'name': '金疮药', 'price': 50, 'supply': 10, 'base_price': 50,
         'type': '药品', 'desc': '外伤用药'},
    ]}],
    'relations': [{'a': 'player', 'b': 'vendor', 'affinity': 5, 'respect': 2}],
    'world_flags': ['jianghu'],
}


async def scenario(session, state_path, seed):
    """标准剧本：建世界 → 战斗/交易/社交/因果 → 回合。返回关键结果。"""
    init = data(await session.call_tool('world_init', dict(SETTING, state_path=state_path, seed=seed)))
    combat = data(await session.call_tool('combat', {'attacker': 'player', 'defender': 'scout',
                                                     'action_type': 'heavy'}))
    trade = data(await session.call_tool('trade', {'location': '临江茶棚', 'item': 'jinchuang_yao',
                                                   'direction': 'buy', 'quantity': 2}))
    social = data(await session.call_tool('social', {'actor': 'player', 'target': 'vendor',
                                                     'event': 'gift'}))
    karma = data(await session.call_tool('karma', {'actor': 'player', 'karma_type': 'theft',
                                                   'victim': 'vendor'}))
    tick = data(await session.call_tool('tick', {}))
    return {'init': init, 'combat': combat, 'trade': trade, 'social': social,
            'karma': karma, 'tick': tick}


async def main():
    tmp = tempfile.mkdtemp(prefix='ww-verify-')
    state_a = os.path.join(tmp, 'a.save.json')

    params = StdioServerParameters(
        command=sys.executable, args=[SERVER], cwd=ROOT,
        env={**os.environ, "WORLD_GAMES_STATE_ROOT": tempfile.gettempdir()},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. 工具清单
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            check('tools/list 覆盖全部 %d 个工具' % len(EXPECTED_TOOLS), names == EXPECTED_TOOLS,
                  '缺少: %s' % (EXPECTED_TOOLS - names) if names != EXPECTED_TOOLS else '')
            check('每个工具都有描述', all((t.description or '').strip() for t in tools.tools))
            wi = next(t for t in tools.tools if t.name == 'world_init')
            # MCP 1.x 的 pydantic 模型字段叫 inputSchema，2.x 改名 input_schema —— 两边都要能读。
            wi_schema = getattr(wi, 'input_schema', None) or getattr(wi, 'inputSchema', None) or {}
            check('world_init 入参带字段级 schema（$defs）', bool(wi_schema.get('$defs')),
                  str(list(wi_schema.get('$defs', {}))[:5]))

            # 1b. prompt：客户端可当斜杠命令用，把「设定 → 开局指令」一键化
            pr = await session.list_prompts()
            check('prompts/list 含 new_game', 'new_game' in {p.name for p in pr.prompts},
                  str(sorted(p.name for p in pr.prompts)))
            got = await session.get_prompt('new_game', {'setting': '世界：测试世界。主角：阿甲。', 'seed': '5'})
            ptext = got.messages[0].content.text
            check('new_game 渲染出设定与 seed', '测试世界' in ptext and 'seed=5' in ptext,
                  '%d 字符' % len(ptext))

            # 2. 未开局时的守卫
            r = await session.call_tool('tick', {})
            check('未 world_init 就结算会报错（不许绕过引擎）', is_err(r), 'isError=True' if is_err(r) else data(r))

            # 3. world_schema
            schema = data(await session.call_tool('world_schema', {}))
            check('world_schema 返回状态结构说明',
                  isinstance(schema, dict) and 'entity_shape' in schema and 'action_tools' in schema)

            # 4. 完整剧本（A 局）
            out = await scenario(session, state_a, seed=42)
            check('world_init 建世界成功', isinstance(out['init'], dict) and out['init'].get('entities') == 3,
                  str(out['init'])[:80])
            # 卡面文字必须穿过 pydantic 保留下来——它是角色卡详情弹窗与叙事层的唯一来源。
            # 曾经的缺陷：EntityIn 没有 desc/personality/speech 字段，设定包人物描述被静默丢弃，
            # 面板点开角色只剩气血一行。
            carded = [e for e in SETTING['entities'] if e.get('desc')]
            if carded:
                saved = json.load(open(state_a, encoding='utf-8'))
                # 挑**带卡面文字的那一个**（fixture 里是茶棚老板），不是随便第一个 NPC
                npc = next(v for k, v in saved['entities'].items()
                           if k != 'player' and v.get('name') == '茶棚老板')
                check('设定包/角色卡文字经 world_init 完整保留',
                      all(npc.get(f) for f in ('desc', 'personality', 'speech')),
                      str({f: bool(npc.get(f)) for f in ('desc', 'personality', 'speech')}))
            check('状态文件已落盘（utf-8 JSON）', os.path.exists(state_a))
            with open(state_a, encoding='utf-8') as f:
                disk = json.load(f)
            check('关系键按字母序生成', 'player:vendor' in disk['relations'])
            check('rng_seed 已写入状态', disk.get('rng_seed') == 42 and disk.get('rng_counter', 0) >= 1)

            # 5. 战斗结算：找一个必然命中的种子，验证伤害真的落到状态里
            hit_seed, hit_path, hit_res = None, None, None
            for s in range(1, 20):
                p = os.path.join(tmp, 'seed%d.save.json' % s)
                await session.call_tool('world_init', dict(SETTING, state_path=p, seed=s))
                cr = data(await session.call_tool('combat', {'attacker': 'player', 'defender': 'scout',
                                                             'action_type': 'attack'}))
                if cr.get('hit'):
                    hit_seed, hit_path, hit_res = s, p, cr
                    break
            check('战斗能命中（20 个种子内至少一次）', hit_seed is not None,
                  'seed=%s damage=%s' % (hit_seed, hit_res.get('damage') if hit_seed else '-'))
            if hit_seed is not None:
                await session.call_tool('world_open', {'state_path': hit_path})
                live = data(await session.call_tool('read_state', {}))
                check('命中伤害写入状态（read_state 与结算一致）',
                      hit_res['damage'] > 0 and hit_res['defender_hp_after'] < 40
                      and live['entities']['scout']['hp'] == hit_res['defender_hp_after'],
                      'damage=%s hp=%s' % (hit_res['damage'], live['entities']['scout']['hp']))
            # 回到 A 局继续后面的检查
            await session.call_tool('world_open', {'state_path': state_a})
            live = data(await session.call_tool('read_state', {}))

            # 6. 交易：扣款 + 入库 + 减库存 三件事都要验（只验扣款会让"物品不入包"漏网）
            check('trade 扣款并减库存',
                  out['trade'].get('success') and live['entities']['player']['gold'] == 200 - out['trade']['total_cost'],
                  'cost=%s gold=%s' % (out['trade'].get('total_cost'), live['entities']['player']['gold']))
            inv = live['entities']['player'].get('items') or {}
            check('trade 买入的物品真的进了背包（2 件金疮药）',
                  int(inv.get('jinchuang_yao', 0)) == 2,
                  'items=%s' % inv)
            sup = live['market']['临江茶棚']['jinchuang_yao']['supply']
            # 初始 10，买 2 → 8；但剧本中途 tick 过一次，tick_market 每回合给 supply<20 的货 +1 → 9
            check('trade 买入后市场库存减少（10→9，含 1 点回合恢复）', sup == 9, 'supply=%s' % sup)
            bad = data(await session.call_tool('trade', {'location': '临江茶棚', 'item': '不存在的货',
                                                         'direction': 'buy'}))
            check('trade 错误商品返回 success=false 而非崩溃', bad.get('success') is False)

            # 7. 社交 → 关系变化（返回值 + 落盘两层都要验，防"只算不写"）
            check('social 提升亲密度（gift +8）',
                  out['social']['affinity_after'] == out['social']['affinity_before'] + 8,
                  '%s -> %s' % (out['social']['affinity_before'], out['social']['affinity_after']))
            live_rel = data(await session.call_tool('read_state', {}))['relations']['player:vendor']
            check('social 的关系变化真的写进状态（read_state 一致）',
                  live_rel['affinity'] == out['social']['affinity_after'],
                  'disk=%s 返回=%s' % (live_rel['affinity'], out['social']['affinity_after']))

            # 8. 因果债
            live = data(await session.call_tool('read_state', {}))
            ledger = live.get('karma_ledger', [])
            check('karma 记入账本（theft +15）',
                  len(ledger) == 1 and ledger[0]['amount'] == 15 and ledger[0]['from'] == 'player',
                  str(ledger[:1]))

            # 8b. 死目标不再刷编年史：长局里"已经没有还手之力"曾连续 ×12 占满时间线。
            #     先打死 scout，再对尸体攻击两次，断言事件条数不增。
            # 打到真的倒下为止（命中是概率的，固定 6 次可能还没死——那会让下面的断言测错对象）
            for _ in range(30):
                await session.call_tool('combat', {'attacker': 'player', 'defender': 'scout',
                                                   'action_type': 'heavy'})
                probe = data(await session.call_tool('read_state', {}))
                if int(probe['entities']['scout']['hp']) <= 0:
                    break
            dead = data(await session.call_tool('read_state', {}))
            dead_ok = int(dead['entities']['scout']['hp']) <= 0
            log_before = len(dead.get('event_log') or [])
            for _ in range(2):
                again_hit = data(await session.call_tool('combat', {
                    'attacker': 'player', 'defender': 'scout', 'action_type': 'attack'}))
            dead_after = data(await session.call_tool('read_state', {}))
            tail = [e.get('desc', '') for e in (dead_after.get('event_log') or [])[log_before:]]
            check('对已倒下目标再次攻击：返回提示但不写编年史',
                  dead_ok and again_hit.get('target_already_dead') is True
                  and len(tail) == 0, '新增 %d 条：%s' % (len(tail), tail[:2]))

            # 9. 回合
            check('tick 推进回合', out['tick'].get('_tick') == 1)

            # 10. 涌现叙事 / 状态聚合
            nar = data(await session.call_tool('narrative', {}))
            check('narrative 返回涌现事件与相位',
                  isinstance(nar, dict) and 'emergent_events' in nar and 'panarchy_phase' in nar)
            st = data(await session.call_tool('status', {}))
            check('status 聚合心流/身份/道德/认知',
                  isinstance(st, dict) and {'flow', 'identity', 'moral_vector', 'cognition'} <= set(st))

            # 11. 纯函数：按闭式公式断言精确值，不只看"有没有数"
            merit = data(await session.call_tool('merit', {'aid': 0.9, 'sincerity': 1.0}))
            weight = data(await session.call_tool('narrative_weight', {'probability': 0.01}))
            # merit = aid × (0.4 + 0.6 × sincerity) = 0.9 × 1.0 = 0.9
            check('merit 按闭式公式出数（0.9×1.0=0.9）',
                  abs(float(merit.get('merit_value', -1)) - 0.9) < 1e-9,
                  'merit=%s 期望 0.9' % merit.get('merit_value'))
            # 信息量 = -log2(p)：p=0.01 → 6.6439 bit
            check('narrative_weight 按 -log2(p) 出数（p=0.01 → 6.6439）',
                  abs(float(weight.get('info_weight', 0)) - 6.6439) < 1e-3,
                  'info=%s 期望 6.6439' % round(weight.get('info_weight', 0), 4))

            # 11a. 只读工具必须零副作用：连续查询不得推进 rng_counter 或改写状态
            before_read = json.load(open(state_a, encoding="utf-8"))
            snap_hash = hashlib.sha256(open(state_a, "rb").read()).hexdigest()
            # mtime 是"有没有落盘"的直接证据：内容相同的 save_state 会让哈希不变，
            # 但一定会刷新 mtime（原子替换）。只看哈希会把"偷偷重写"判成只读（变异 M26 曾存活）。
            snap_mtime = os.stat(state_a).st_mtime_ns
            for _ in range(3):
                await session.call_tool('status', {})
                await session.call_tool('world_state', {})
                await session.call_tool('read_state', {})
            after_read = json.load(open(state_a, encoding="utf-8"))
            check('只读工具（status/world_state/read_state）不推进 rng_counter',
                  after_read.get("rng_counter") == before_read.get("rng_counter"),
                  "%s -> %s" % (before_read.get("rng_counter"), after_read.get("rng_counter")))
            check('只读工具不落盘（字节不变且 mtime 不变）',
                  hashlib.sha256(open(state_a, "rb").read()).hexdigest() == snap_hash
                  and os.stat(state_a).st_mtime_ns == snap_mtime,
                  'mtime %s -> %s' % (snap_mtime, os.stat(state_a).st_mtime_ns))

            # 11b. 模型层：命名闭式公式直接算效果
            mlist = data(await session.call_tool('model_list', {}))
            names = {m['name'] for m in mlist.get('models', [])}
            lerner = data(await session.call_tool('model', {'name': 'lerner_price',
                                                            'params': {'cogs': 60, 'elasticity': 2.5}}))
            ou = data(await session.call_tool('model', {'name': 'ou_price',
                                                        'params': {'price': 37, 'base': 30, 'theta': 0.15}}))
            check('model_list 列出命名模型（含 economics/population）',
                  {'lerner_price', 'ou_price', 'lotka_volterra', 'sir_step',
                   'logistic_sigmoid'} <= names, '%d 个模型' % len(names))
            # Lerner: P = 60 * 2.5/1.5 = 100
            check('model(lerner_price) 按公式出数', abs(lerner.get('value', 0) - 100.0) < 1e-6,
                  'value=%s formula=%s' % (lerner.get('value'), lerner.get('formula')))
            # OU: 37 + (-0.15*(37-30)) = 37 - 1.05 = 35.95
            check('model(ou_price) 均值回归一步', abs(ou.get('value', 0) - 35.95) < 1e-6,
                  'value=%s' % ou.get('value'))

            # 12. world_open 续跑
            reopened = data(await session.call_tool('world_open', {'state_path': state_a}))
            check('world_open 可续跑已存对局', reopened.get('tick') == 1 and 'scout' in reopened.get('entities', []))

            # 13. 确定性：同种子 + 同行动 → 完全一致；不同种子 → 结果有差异
            det_a, det_b = os.path.join(tmp, 'det_a.save.json'), os.path.join(tmp, 'det_b.save.json')
            await session.call_tool('world_init', dict(SETTING, state_path=det_a, seed=hit_seed or 1))
            r1 = data(await session.call_tool('combat', {'attacker': 'player', 'defender': 'scout',
                                                         'action_type': 'attack'}))
            await session.call_tool('world_init', dict(SETTING, state_path=det_b, seed=hit_seed or 1))
            r2 = data(await session.call_tool('combat', {'attacker': 'player', 'defender': 'scout',
                                                         'action_type': 'attack'}))
            check('确定性：同种子同行动结果完全一致', r1 == r2 and r1.get('hit'),
                  'damage=%s' % r1.get('damage'))
            outs = set()
            for s in range(1, 9):
                p = os.path.join(tmp, 'rand%d.save.json' % s)
                await session.call_tool('world_init', dict(SETTING, state_path=p, seed=s))
                cr = data(await session.call_tool('combat', {'attacker': 'player', 'defender': 'scout',
                                                             'action_type': 'attack'}))
                outs.add((cr.get('hit'), cr.get('damage'), cr.get('crit')))
            check('不同种子给出不同战斗结果（随机数确实生效）', len(outs) >= 2, '%d 种结果' % len(outs))

    # 14. 酒馆生态兼容：PNG 嵌卡 → NPC、world-info 世界书、叙事上下文
    import base64, struct, zlib

    def png_chunk(ctype, payload):
        return (struct.pack('>I', len(payload)) + ctype + payload
                + struct.pack('>I', zlib.crc32(ctype + payload) & 0xffffffff))

    card = {
        'spec': 'chara_card_v2', 'spec_version': '2.0',
        'data': {
            'name': '白露',
            'description': '白发药师的学徒，随身带着一只旧药箱。',
            'personality': '话少、谨慎、心软。',
            'first_mes': '「……你受伤了。」她放下药箱。',
            'mes_example': '「别动。」/「药苦，忍着。」',
            'tags': ['药师', '寡言'], 'creator': 'verify-script',
            'character_book': {'entries': [
                {'keys': ['药箱', '药'], 'content': '白露的旧药箱是师父遗物，夹层里藏着一封没写完的信。',
                 'insertion_order': 10, 'enabled': True, 'comment': '药箱'},
                {'keys': ['渡口'], 'secondary_keys': ['雨'], 'selective': True,
                 'content': '渡口的雨夜里，船夫们会在茶棚后烤火。', 'insertion_order': 20,
                 'enabled': True, 'comment': '雨夜渡口'},
                {'keys': ['不会被触发'], 'content': '这条不该出现。', 'enabled': True, 'comment': '干扰项'},
                {'keys': ['节奏'], 'content': '常驻：秋雨、慢节奏、旧账。', 'constant': True,
                 'enabled': True, 'comment': '基调'},
            ]},
        },
    }
    card_png = os.path.join(tmp, 'bailu.png')
    with open(card_png, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n')
        f.write(png_chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0)))
        f.write(png_chunk(b'IDAT', zlib.compress(b'\x00\x00\x00\x00\x00')))
        f.write(png_chunk(b'tEXt', b'chara\x00'
                          + base64.b64encode(json.dumps(card, ensure_ascii=False).encode('utf-8'))))
        f.write(png_chunk(b'IEND', b''))

    wi = {'entries': {
        '0': {'uid': 0, 'key': ['镖局'], 'keysecondary': [], 'comment': '镖局',
              'content': '临江渡口归「镇远镖局」管，总镖头姓沈。', 'disable': False, 'order': 50},
        '1': {'uid': 1, 'key': ['规矩'], 'comment': '规矩',
              'content': '渡口规矩：先付钱后上船。', 'disable': True, 'order': 60},
    }}
    wi_path = os.path.join(tmp, 'worldinfo.json')
    with open(wi_path, 'w', encoding='utf-8') as f:
        json.dump(wi, f, ensure_ascii=False)

    eco_state = os.path.join(tmp, 'ecosys.save.json')

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await session.call_tool('world_init', dict(SETTING, state_path=eco_state, seed=11))
            cr = data(await session.call_tool('character_card_read', {'path': card_png}))
            check('角色卡读取（PNG 内嵌 V2 卡）',
                  cr.get('name') == '白露' and cr.get('book_entries') == 4, str(cr.get('spec')))
            ac = data(await session.call_tool('add_character', {'path': card_png,
                                                               'entity_id': 'bailu',
                                                               'location': '临江茶棚'}))
            check('角色卡入局为 NPC 并并入卡内世界书', ac.get('lore_added') == 4, str(ac))
            st = data(await session.call_tool('read_state', {}))
            check('卡面文字进入叙事层（desc/personality/speech）',
                  '药箱' in st['entities']['bailu'].get('desc', '')
                  and bool(st['entities']['bailu'].get('personality')))
            il = data(await session.call_tool('import_lorebook', {'path': wi_path}))
            check('导入 SillyTavern world-info（含 disable 字段）',
                  il.get('imported') == 2 and il.get('total') == 6, str(il))

            nc1 = data(await session.call_tool('narration_context', {'scene_text': '她打开药箱取药'}))
            blob1 = ' '.join(x['comment'] + x['content'] for x in nc1['triggered_lore'])
            check('关键词触发：命中主键 + 常驻，排除无关条目',
                  '药箱' in blob1 and '基调' in blob1 and '干扰项' not in blob1,
                  '%d 条触发' % len(nc1['triggered_lore']))
            nc2 = data(await session.call_tool('narration_context', {'scene_text': '渡口的雨很大'}))
            nc3 = data(await session.call_tool('narration_context', {'scene_text': '渡口很干'}))
            has = lambda nc, s: any(s in x['content'] for x in nc['triggered_lore'])
            check('selective 语义：需主键+副键同中', has(nc2, '烤火') and not has(nc3, '烤火'))
            nc4 = data(await session.call_tool('narration_context', {'scene_text': '镖局的规矩'}))
            check('disable 条目不触发；ST 键名（key/keysecondary）生效',
                  has(nc4, '镇远镖局') and not has(nc4, '先付钱后上船'))
            check('叙事包带在场角色卡面与编年史',
                  bool(nc4['present_cast']) and bool(nc4['chronicle']),
                  'cast=%d chronicle=%d' % (len(nc4['present_cast']), len(nc4['chronicle'])))

            # 15. 快照 / 回退（确定性）
            snap = data(await session.call_tool('snapshot', {'label': 'before'}))
            await session.call_tool('tick', {})
            after = data(await session.call_tool('read_state', {}))['tick']
            rs = data(await session.call_tool('restore', {'snapshot_path': snap['snapshot']}))
            check('快照/回退：状态回到存档点',
                  after == rs['tick'] + 1 and 'bailu' in rs.get('entities', []),                  'tick %s -> %s' % (rs['tick'], after))

            # 16. 确定性显式契约：同一快照点重放同一行动 → 结果逐字段相等
            #     （覆盖 rng_counter 随快照回退后的确定性语义，此前仅有 world_init 级覆盖）
            c_first = data(await session.call_tool('combat', {'attacker': 'player',
                                                              'defender': 'scout', 'action_type': 'attack'}))
            await session.call_tool('restore', {'snapshot_path': snap['snapshot']})
            c_replay = data(await session.call_tool('combat', {'attacker': 'player',
                                                               'defender': 'scout', 'action_type': 'attack'}))
            check('确定性契约：快照点重放同行动结果逐字段相等',
                  c_first == c_replay and c_first.get('hit'),
                  'damage %s vs %s' % (c_first.get('damage'), c_replay.get('damage')))

            # 17. 设定包一键开局（仓库自带的玄枢界）
            sp = os.path.join(ROOT, 'settings', '玄枢界.setting.json')
            await session.call_tool('load_setting', {'path': sp,
                                                     'state_path': os.path.join(tmp, 'xs.save.json'),
                                                     'seed': 5})
            st = data(await session.call_tool('read_state', {}))
            check('设定包一键开局：世界/人物/世界书全部落地',
                  st['world_info']['name'] == '玄枢界' and len(st['entities']) == 9
                  and len(st.get('lore', [])) == 21,
                  '%s · 实体 %d · 词条 %d' % (st['world_info']['name'], len(st['entities']),
                                             len(st.get('lore', []))))
            nc = data(await session.call_tool('narration_context',
                                              {'scene_text': '旧枢台夜里透出光，试炼名额被人买断'}))
            blob = ' '.join(x['comment'] for x in nc['triggered_lore'])
            check('设定包世界书按关键词触发（含常驻基调与事件范式）',
                  '基调' in blob and '事件范式 · 入学试炼与大比' in blob,
                  '触发 %d 条' % len(nc['triggered_lore']))
            check('世界书递归默认关闭（防止整本书被拉进上下文）',
                  nc.get('lore_by_depth', {}).keys() == {'0'}, str(nc.get('lore_by_depth')))

            # 18. 长局：归档/召回/摘要/回顾/突破/配置
            await session.call_tool('configure', {'event_log_keep': 5})
            for i in range(9):   # 用 travel 造事件（一定成功），验证溢出归档
                await session.call_tool('travel', {'location': '听霄城' if i % 2 else '临川城',
                                                   'note': '巡视%d' % i})
            st = data(await session.call_tool('read_state', {}))
            check('长局：事件溢出自动归档，状态文件不膨胀',
                  len(st['event_log']) <= 5 and st.get('archived_events', 0) > 0,
                  '保留 %d / 归档 %d' % (len(st['event_log']), st.get('archived_events', 0)))
            rc = data(await session.call_tool('recall', {'query': '巡视'}))
            check('长局：可按关键词回捞归档事件', len(rc.get('matches', [])) > 0,
                  '命中 %d 条' % len(rc.get('matches', [])))

            # 18b. 回退不得删除归档（曾经为修正计数漂移而截断归档文件，导致历史被物理删除）
            arch_before = data(await session.call_tool('read_state', {})).get('archived_events', 0)
            rc_first = data(await session.call_tool('recall', {'query': '巡视0'}))
            snap_arch = data(await session.call_tool('snapshot', {'label': 'arch'}))
            for i in range(4):
                await session.call_tool('travel', {'location': '听霄城' if i % 2 else '临川城',
                                                   'note': '溢出%d' % i})
            await session.call_tool('restore', {'snapshot_path': snap_arch['snapshot']})
            st_after_rb = data(await session.call_tool('read_state', {}))
            rc_after = data(await session.call_tool('recall', {'query': '巡视0'}))
            # 硬判据：回退前能召回的那批归档事件，回退后必须一条不少地还能召回
            # （只看 archived_events 数值会被"快照里本来就够大"掩盖，故直接比对召回集合）
            set_before = {m.get('desc') for m in rc_first.get('matches', [])}
            set_after = {m.get('desc') for m in rc_after.get('matches', [])}
            missing = set_before - set_after
            check('长局：回退后旧归档仍可逐条召回（不丢历史）',
                  bool(set_before) and not missing,
                  '回退前 %d 条 · 回退后 %d 条 · 丢失 %d 条 %s'
                  % (len(set_before), len(set_after), len(missing), sorted(missing)[:2]))
            # 硬判据：回退后计数必须等于**所有世代归档文件的实际行数**
            # （只判"不回退"会漏掉"计数不变但文件行数更多"的漂移）
            import glob as _g
            _cur = os.path.join(tmp, 'xs.save.json')
            _arch_files = ([_cur + '.log.jsonl'] + sorted(_g.glob(_cur + '.log.*.jsonl')))
            _lines = 0
            for _af in _arch_files:
                if os.path.exists(_af):
                    _lines += sum(1 for _ in open(_af, encoding='utf-8'))
            check('长局：回退后 archived_events 与归档文件行数严格相等',
                  st_after_rb.get('archived_events', 0) == _lines,
                  'counter=%s file_lines=%s' % (st_after_rb.get('archived_events'), _lines))
            check('长局：回退后 archived_events 不回退（归档只增不减）',
                  st_after_rb.get('archived_events', 0) >= arch_before,
                  'arch %s→%s' % (arch_before, st_after_rb.get('archived_events')))
            await session.call_tool('write_summary', {'text': '本段：买丹、结交、动身听霄城。'})
            rp = data(await session.call_tool('recap', {'budget_chars': 400}))
            check('长局：回顾包带摘要且遵守字符预算',
                  '听霄城' in (rp.get('summary') or '') and rp.get('used_chars', 0) <= 400,
                  '用量 %d/%d' % (rp.get('used_chars'), rp.get('budget_chars')))
            before = data(await session.call_tool('read_state', {}))['entities']['player']
            adv = data(await session.call_tool('advance', {'next_level': '淬体八段', 'insight': 0.8}))
            after = data(await session.call_tool('read_state', {}))['entities']['player']
            ok_shape = (after['level'] == '淬体八段' and after['hp_max'] >= before['hp_max']) if adv['success']                 else (after['hp'] < before['hp'] and after.get('mind_scars', 0) == before.get('mind_scars', 0) + 1)
            mil = data(await session.call_tool('read_state', {})).get('milestones', [])
            check('长局：突破由引擎判定并落数值与大事记',
                  ok_shape and any('突破' in m.get('desc', '') for m in mil),
                  'success=%s chance=%s 大事记 %d 条' % (adv['success'], adv['chance'], len(mil)))
            nc = data(await session.call_tool('narration_context', {'scene_text': '听霄城'}))
            check('长局：叙事包带最新摘要与大事记',
                  bool(nc.get('latest_summary')) and len(nc.get('milestones', [])) > 0)

            # 16. 移动 + 探索图鉴 + 实况面板
            panel_state = os.path.join(tmp, 'panel.save.json')
            await session.call_tool('world_init', dict(SETTING, state_path=panel_state, seed=3))
            t1 = data(await session.call_tool('travel', {'location': '后山古道', 'note': '雨里上山'}))
            t2 = data(await session.call_tool('travel', {'location': '临江茶棚'}))
            t3 = data(await session.call_tool('travel', {'location': '后山古道'}))
            check('travel 改位置；首次到达才算"初次探索"（开局地点已在图鉴）',
                  t1.get('first_time') is True and t2.get('first_time') is False
                  and t3.get('first_time') is False and t1.get('location') == '后山古道', str(t1))
            await session.call_tool('trade', {'location': '临江茶棚', 'item': 'chun_cha',
                                              'direction': 'buy'})
            await session.call_tool('social', {'actor': 'player', 'target': 'vendor',
                                               'event': 'praise'})
            await session.call_tool('import_lorebook', {'path': wi_path})
            await session.call_tool('narration_context', {'scene_text': '镖局的规矩'})
            st = data(await session.call_tool('read_state', {}))
            cx = st.get('codex', {})
            check('探索图鉴：地点/人物/物品/词条都已记录',
                  {'临江茶棚', '后山古道'} <= set(cx.get('locations', []))
                  and '茶棚老板' in cx.get('people', [])
                  and '春茶' in cx.get('items', [])
                  and '镖局' in cx.get('lore', []),
                  'loc=%d people=%d items=%d lore=%d' % (
                      len(cx.get('locations', [])), len(cx.get('people', [])),
                      len(cx.get('items', [])), len(cx.get('lore', []))))

            # 面板「行动队列」：只写侧写文件，状态由宿主经引擎结算
            inbox_hash_before = hashlib.sha256(open(panel_state, "rb").read()).hexdigest()
            import importlib.util as _ilu2
            _pspec = _ilu2.spec_from_file_location('ww_panel_x', os.path.join(ROOT, 'panel.py'))
            _panelmod = _ilu2.module_from_spec(_pspec)
            _pspec.loader.exec_module(_panelmod)
            _panelmod.inbox_append(panel_state, '去城里打听学宫名额')
            _panelmod.inbox_append(panel_state, '找裴无咎喝一杯')
            queued = data(await session.call_tool('pending_actions', {'mark_done': True}))
            check('pending_actions 取走面板排的行动并标记已处理',
                  queued.get('count') == 2 and queued.get('marked_done') == 2
                  and [q['text'] for q in queued['pending']] == ['去城里打听学宫名额', '找裴无咎喝一杯'],
                  str(queued.get('count')))
            again = data(await session.call_tool('pending_actions', {}))
            check('pending_actions 标记后不再重复返回', again.get('count') == 0,
                  str(again.get('count')))
            check('行动队列不改写状态文件（字节不变）',
                  hashlib.sha256(open(panel_state, "rb").read()).hexdigest() == inbox_hash_before)

            pv = data(await session.call_tool('open_panel', {'port': 8791}))
            import urllib.request
            html = urllib.request.urlopen(pv['url'], timeout=8).read().decode('utf-8')
            vm = json.loads(urllib.request.urlopen(pv['url'].rstrip('/') + '/state',
                                                   timeout=8).read().decode('utf-8'))
            check('实况面板：页面与数据就绪且反映最新状态',
                  '实况' in html and vm['player']['location'] == '后山古道'
                  and '后山古道' in vm['codex']['locations'],
                  pv['url'] + ' | 编年史 %d 条' % len(vm['chronicle']))
            check('面板视图含引擎推导（心流/相位/图鉴/市场）',
                  'flow' in vm['insights'] and 'phase' in vm['insights']
                  and {'locations', 'people', 'items', 'lore'} <= set(vm['codex'])
                  and bool(vm['market']))

    # 14. CLI 冒烟（验证导入别名让任意目录名都能跑）
    cli = subprocess.run([sys.executable, os.path.join(ROOT, 'engine.py'),
                          'world_state', '--state', state_a],
                         capture_output=True, text=True, encoding='utf-8', cwd=tempfile.gettempdir())
    ok_cli = cli.returncode == 0 and '"tick"' in (cli.stdout or '')
    check('CLI 从任意工作目录可运行（导入别名生效）', ok_cli,
          (cli.stdout or cli.stderr or '').strip().splitlines()[:1][0] if not ok_cli else '')

    # 15. streamable-http 传输：远程 agent 连 HTTP 端点拿到同一套工具（v1.10.0）
    #     判据：initialize 握手成功、serverInfo 报出正确版本、tools/list 工具数与 stdio 一致。
    import socket
    import time as _time
    import urllib.error
    import urllib.request

    def _free_port():
        s = socket.socket()
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
        s.close()
        return port

    def _http_post(url, payload, sid=None):
        headers = {'Content-Type': 'application/json',
                   'Accept': 'application/json, text/event-stream',
                   'MCP-Protocol-Version': '2025-06-18'}
        if sid:
            headers['Mcp-Session-Id'] = sid
        req = urllib.request.Request(url, method='POST',
                                     data=json.dumps(payload).encode('utf-8'),
                                     headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode('utf-8', 'replace')
            out_sid = resp.headers.get('mcp-session-id') or sid
            # streamable-http 可能回 SSE 帧（data: {...}）或普通 JSON，两种都要能解
            msgs = []
            for line in body.splitlines():
                line = line.strip()
                if line.startswith('data:'):
                    try:
                        msgs.append(json.loads(line[5:].strip()))
                    except Exception:
                        pass
            if not msgs and body.strip():
                try:
                    msgs.append(json.loads(body))
                except Exception:
                    pass
            return resp.status, out_sid, msgs

    http_port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, SERVER, '--http', '--host', '127.0.0.1', '--port', str(http_port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env={**os.environ, 'WORLD_GAMES_STATE_ROOT': tempfile.gettempdir()})
    try:
        base = 'http://127.0.0.1:%d/mcp' % http_port
        sid, init_msg = None, None
        for _ in range(60):  # 服务监听就绪前轮询（最多 ~12s）
            if proc.poll() is not None:
                break  # 进程提前退出：SDK 不支持 --http，下面按失败报告
            try:
                status, sid, msgs = _http_post(base, {
                    'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                    'params': {'protocolVersion': '2025-06-18', 'capabilities': {},
                               'clientInfo': {'name': 'wg-verify-http', 'version': '0'}}})
                if status == 200 and msgs:
                    init_msg = next((m for m in msgs if m.get('id') == 1), None)
                    break
            except urllib.error.URLError:
                _time.sleep(0.2)
        http_tools = []
        if init_msg is not None:
            # notifications/initialized 之后 tools/list 才是合法会话
            _http_post(base, {'jsonrpc': '2.0', 'method': 'notifications/initialized'}, sid)
            _, _, msgs = _http_post(base, {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}, sid)
            tl = next((m for m in msgs if m.get('id') == 2), None)
            http_tools = [t.get('name') for t in ((tl or {}).get('result') or {}).get('tools', [])]
        _init_info = ((init_msg or {}).get('result') or {}).get('serverInfo') or {}
        check('HTTP 传输：initialize 握手返回 world-games 服务器信息',
              _init_info.get('name') == 'world-games',
              str((init_msg or {}).get('error', {}).get('message') or _init_info.get('name')))
        from game_engine import __version__ as _wg_ver
        check('HTTP 传输：serverInfo 报出世界引擎版本',
              _init_info.get('version') == _wg_ver,
              '%s 期望 %s' % (_init_info.get('version'), _wg_ver))
        check('HTTP 传输：tools/list 与 stdio 同一套 %d 个工具' % len(EXPECTED_TOOLS),
              sorted(http_tools) == sorted(EXPECTED_TOOLS),
              '%d 个工具' % len(http_tools))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    passed = sum(RESULTS)
    print('\n%d/%d passed' % (passed, len(RESULTS)))
    return 0 if passed == len(RESULTS) else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
