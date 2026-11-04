#!/usr/bin/env python3
"""
用户视角试玩 (user_playtest.py)

模拟一个"真实玩家"从开局玩到收摊：探索、逛市场、砍价、打架、吃药、交朋友、
背因果、冲境界、写小作文、回退重来……同时故意做几件"聪明玩家"会做的事：
卖自己没有的东西、买 99999 个、拿模型层当计算器（先算价格回归再下单）、
把关系刷到爆表、拿不存在的 NPC 打架。

验证两件事（用户视角，不是不变量压测）：
  1. 每个"该优雅拒绝"的操作都拿到人能读懂的报错，而不是崩会话/写坏状态
  2. 玩完之后状态文件仍然自洽（钱/血/价/关系/账本/事件都有界）

用法:  python scripts/user_playtest.py [seed]
退出码: 0 = 玩家体验全绿；1 = 有"玩家会投诉"的问题；2 = 缺少 mcp SDK
"""

import asyncio
import json
import os
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

CALLS = {'n': 0, 'graceful': 0, 'unexpected': 0}
CHECKS = []      # (name, ok, note) 玩家视角断言
OBSERVED = []    # 只观察不判定的行为（打印给人看）


def ux(name, ok, note=''):
    CHECKS.append((bool(ok), name))
    print('  %s %-44s %s' % ('ok ' if ok else 'XX ', name, note))


def observe(text):
    OBSERVED.append(text)
    print('  .. %s' % text)


# 一局武侠小世界：三个地点、两个市场、四个 NPC（玩家 500 玄晶，够倒腾）
SETTING = {
    'world': {'name': '雾隐山城', 'era': '雾隐历三年',
              'location_desc': '临江城挨着渡口，竹楼酒旗顺着江风一排排摆开。'},
    'player': {'name': '阿吉', 'faction': '散人',
               'attrs': {'str': 13, 'dex': 12, 'int': 12, 'con': 11, 'cha': 12},
               'level': '三流', 'hp': 100, 'hp_max': 100, 'mp': 20, 'mp_max': 20,
               'gold': 500, 'location': '临江城'},
    'entities': [
        {'id': 'laowang', 'name': '老王', 'faction': '市井',
         'attrs': {'str': 7, 'dex': 8, 'int': 12, 'con': 9, 'cha': 13},
         'level': '凡人', 'hp': 35, 'hp_max': 35, 'gold': 150, 'location': '临江城'},
        {'id': 'wolf', 'name': '独眼狼', 'faction': '黑风寨',
         'attrs': {'str': 12, 'dex': 11, 'int': 8, 'con': 10, 'cha': 5},
         'level': '二流', 'hp': 45, 'hp_max': 45, 'gold': 40, 'location': '黑风寨'},
        {'id': 'daoist', 'name': '观星老道', 'faction': '方外',
         'attrs': {'str': 5, 'dex': 6, 'int': 16, 'con': 8, 'cha': 11},
         'level': '一流', 'hp': 40, 'hp_max': 40, 'gold': 5, 'location': '观星台'},
    ],
    'market': [
        {'location': '临江城', 'items': [
            {'key': 'chun_cha', 'name': '春茶', 'price': 20, 'supply': 20, 'base_price': 20,
             'type': '饮品', 'desc': '江边新茶'},
            {'key': 'hui_ling', 'name': '回灵丹', 'price': 50, 'supply': 12, 'base_price': 50,
             'type': '丹药', 'desc': '回气养神'},
            {'key': 'jinchuang', 'name': '金疮药', 'price': 30, 'supply': 10, 'base_price': 30,
             'type': '药品', 'desc': '外伤用药'},
        ]},
        {'location': '观星台', 'items': [
            {'key': 'xiang_zhu', 'name': '香烛', 'price': 15, 'supply': 20, 'base_price': 15,
             'type': '杂物', 'desc': '观星前焚一支'},
        ]},
    ],
    'relations': [{'a': 'player', 'b': 'laowang', 'affinity': 5, 'respect': 2}],
    'world_flags': ['wuxia'],
}


def is_err(result):
    return bool(getattr(result, 'isError', False) or getattr(result, 'is_error', False))


def err_text(result):
    parts = []
    for c in getattr(result, 'content', None) or []:
        if getattr(c, 'type', '') == 'text':
            parts.append(c.text)
    return ' '.join(parts).strip() or '(无报错正文)'


def data(result):
    for attr in ('structuredContent', 'structured_content'):
        sc = getattr(result, attr, None)
        if isinstance(sc, dict):
            return sc.get('result', sc) if set(sc) == {'result'} else sc
    for c in getattr(result, 'content', None) or []:
        if getattr(c, 'type', '') == 'text':
            try:
                return json.loads(c.text)
            except Exception:  # aqg: top-level boundary —— 返回体非 JSON 时回退原文，试玩不断链
                return c.text
    return None


async def call(session, name, args=None, label=''):
    """调一个工具。allow_refuse=True 的场合用 refuse()。"""
    CALLS['n'] += 1
    r = await session.call_tool(name, args or {})
    if is_err(r):
        CALLS['unexpected'] += 1
        print('  !! %s 意外异常: %s' % (name, err_text(r)[:160]))
        return {'__unexpected__': err_text(r)}
    d = data(r)
    return d if isinstance(d, dict) else {'result': d}


async def refuse(session, name, args=None):
    """期待一次"优雅拒绝"（raise → isError + 人能读懂的报错）。返回报错文本。"""
    CALLS['n'] += 1
    r = await session.call_tool(name, args or {})
    if not is_err(r):
        CALLS['unexpected'] += 1
        print('  !! %s 本该拒绝却成功了: %s' % (name, str(data(r))[:160]))
        return None
    CALLS['graceful'] += 1
    return err_text(r)


async def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 777
    tmp = tempfile.mkdtemp(prefix='ww-play-')
    state_path = os.path.join(tmp, 'aji.save.json')

    params = StdioServerParameters(
        command=sys.executable, args=[SERVER], cwd=ROOT,
        env={**os.environ, 'WORLD_GAMES_STATE_ROOT': tempfile.gettempdir()},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print('── 开局 ─────────────────────────────────────')
            init = await call(session, 'world_init', dict(SETTING, state_path=state_path, seed=seed))
            print('  [01] 建局「%s」：%s 实体 / %s 市场' %
                  (init.get('world'), init.get('entities'), len(init.get('market_locations', []))))
            await call(session, 'configure', {'currency': '玄晶'})
            schema = await call(session, 'world_schema', {})
            tools = (schema.get('action_tools') or {})
            ux('world_schema 能查工具目录（含模型层）', 'model' in tools and 'model_list' in tools,
               '%d 个动作' % len(tools))
            st = await call(session, 'read_state', {})
            ux('开局状态自洽', st.get('tick') == 0
               and st['entities']['player']['gold'] == 500
               and len(st.get('market', {})) == 2)

            print('── 逛世界 ───────────────────────────────────')
            ctx = await call(session, 'narration_context',
                             {'scene_text': '阿吉走进临江城，渡口人来人往，老王在茶摊招手。'})
            ux('narration_context 可用', isinstance(ctx, dict) and ctx != {},
               str(list(ctx.keys())[:5]))
            t1 = await call(session, 'travel', {'location': '黑风寨', 'note': '去看独眼狼'})
            ux('首次抵达记图鉴', t1.get('first_time') is True and t1.get('in_setting') is True)
            await call(session, 'travel', {'location': '观星台'})
            t3 = await call(session, 'travel', {'location': '黑风寨'})
            ux('二次抵达不重复记', t3.get('first_time') is False)
            t4 = await call(session, 'travel', {'location': '不存在的地方'})
            observe('去"不存在的地方"：没拦（in_setting=%s）——自由探索设计，允许' % t4.get('in_setting'))
            e = await refuse(session, 'travel', {'location': '   '})
            ux('空地点被拒且报错可读', e is not None and '不能为空' in e, (e or '')[:40])

            print('── 市场：老玩家会先算再买（模型层当计算器）────')
            await call(session, 'travel', {'location': '临江城'})
            # OU 均值回归：多点 + 多步收敛。
            # 只测一个点（40→37）会被 `if price==40: return 37` 这种特例硬编码绕过；
            # 这里用"高于基准 / 低于基准 / 接近基准"三组初值，各连跑 3 步，
            # 每步都按闭式解 x' = x - theta*(x-base) 独立手算后比对。
            import json as _json
            st0 = await call(session, 'read_state', {})
            b0 = int(st0['market']['临江城']['chun_cha']['base_price'])
            theta = 0.15
            # 第三组必须落在死区外（死区实测为 |Δ|<=3，见下方说明），否则等于断言常量
            cases = [b0 * 2, max(1, b0 // 2), b0 + 5]
            for ci, p_init in enumerate(cases):
                st_c = _json.loads(_json.dumps(st0))
                st_c['market']['临江城']['chun_cha']['price'] = p_init
                # 关闭市场扰动：本组验证的是 OU 回归公式能否逐点复算，
                # 叠加随机扰动就无法用手算值比对（扰动是产品特性，用配置关掉）。
                st_c.setdefault('config', {})['market_jitter'] = False
                tmp_c = '%s.ou%d.json' % (state_path, ci)
                with open(tmp_c, 'w', encoding='utf-8') as f:
                    _json.dump(st_c, f, ensure_ascii=False)
                await call(session, 'world_open', {'state_path': tmp_c})
                cur = p_init
                ok_steps, trace = True, [cur]
                for _ in range(3):
                    cur = max(0, int(round(cur - theta * (cur - b0))))
                    await call(session, 'tick', {})
                    got = (await call(session, 'read_state', {}))['market']['临江城']['chun_cha']['price']
                    trace.append(got)
                    if got != cur:
                        ok_steps = False
                        break
                ux('OU 回归多点第%d组（初值 %s）3 步逐步吻合闭式解' % (ci + 1, p_init),
                   ok_steps, '轨迹 %s' % trace)
                # 整数化后当 |price-base| <= 1 时 round() 会卡在边界无法再收敛，
                # 这是实现已知的取整局限（不是回归），故小差值组只要求不远离基准。
                near = abs(p_init - b0) <= 1
                ux('OU 回归第%d组逼近基准（死区外须严格收敛）' % (ci + 1),
                   (abs(trace[-1] - b0) <= 1) if near else (abs(trace[-1] - b0) < abs(p_init - b0)),
                   'init=%s final=%s base=%s' % (p_init, trace[-1], b0))
            await call(session, 'world_open', {'state_path': state_path})
            hag = await call(session, 'model', {'name': 'lerner_price', 'params': {'cogs': 30, 'elasticity': 3}})
            ux('砍价模型出数正确（30×3/2=45）', abs(float(hag.get('value', 0)) - 45.0) < 1e-9)

            # 边界：数量 0 / 负数 / 天量 / 没货
            r0 = await call(session, 'trade', {'location': '临江城', 'item': 'chun_cha',
                                               'direction': 'buy', 'quantity': 0})
            rn = await call(session, 'trade', {'location': '临江城', 'item': 'chun_cha',
                                               'direction': 'buy', 'quantity': -3})
            ux('买 0 个 / 买负数都被拒', r0.get('success') is False and rn.get('success') is False,
               str(r0.get('events', []))[:30])
            rbig = await call(session, 'trade', {'location': '临江城', 'item': 'hui_ling',
                                                 'direction': 'buy', 'quantity': 99999})
            ux('买 99999 个被拒（库存不足）', rbig.get('success') is False,
               str(rbig.get('events', []))[:30])

            # 钻空子①：卖自己从来没有的东西
            rp = await call(session, 'trade', {'location': '观星台', 'item': 'xiang_zhu',
                                               'direction': 'sell', 'quantity': 2})
            observe('空手卖香烛×2：success=%s total=%s（预期待拒）' % (rp.get('success'), rp.get('total_cost')))
            ux('没持有的东西卖不掉', rp.get('success') is False,
               '玩家从没买过香烛；若能卖=金币印刷机' if rp.get('success') else '')

            # 正常循环：买了就该能卖
            rb = await call(session, 'trade', {'location': '临江城', 'item': 'chun_cha',
                                               'direction': 'buy', 'quantity': 5})
            rs = await call(session, 'trade', {'location': '临江城', 'item': 'chun_cha',
                                               'direction': 'sell', 'quantity': 2})
            ux('买 5 卖 2 正常完成', rb.get('success') and rs.get('success'),
               'buy=%s sell=%s' % (rb.get('success'), rs.get('success')))
            rcheat = await call(session, 'trade', {'location': '临江城', 'item': 'chun_cha',
                                                   'direction': 'sell', 'quantity': 9999})
            observe('卖 9999 春茶（手里约 3 个）：success=%s total=%s' % (rcheat.get('success'), rcheat.get('total_cost')))
            ux('卖超持有量被拒', rcheat.get('success') is False,
               '超量卖出=刷钱' if rcheat.get('success') else '')

            rloc = await refuse(session, 'trade', {'location': '月球', 'item': 'chun_cha', 'direction': 'buy'})
            ux('去没市场的地方买东西→报错列出可用地', rloc is not None and '没有市场' in rloc, (rloc or '')[:44])
            ritem = await call(session, 'trade', {'location': '临江城', 'item': '大宝剑',
                                                  'direction': 'buy'})
            ux('买不存在的货被拒', ritem.get('success') is False, str(ritem.get('events', []))[:30])
            rdir = await refuse(session, 'trade', {'location': '临江城', 'item': 'chun_cha', 'direction': '抢'})
            ux('direction 乱填被拒', rdir is not None and 'buy / sell' in rdir)

            print('── 打架（先备药，再上门）─────────────────────')
            await call(session, 'trade', {'location': '临江城', 'item': 'jinchuang',
                                          'direction': 'buy', 'quantity': 2})
            await call(session, 'travel', {'location': '黑风寨'})
            hits, dead, meds = 0, False, 0
            for _ in range(24):
                cr = await call(session, 'combat', {'attacker': 'player', 'defender': 'wolf',
                                                    'action_type': 'attack'})
                hits += 1
                if cr.get('defender_dead'):
                    dead = True
                    break
                if cr.get('__unexpected__'):
                    break
                # 宿主式结算：狼还手（引擎一次只结算一方出手）
                await call(session, 'combat', {'attacker': 'wolf', 'defender': 'player',
                                               'action_type': 'attack'})
                st = await call(session, 'read_state', {})
                if st['entities']['player']['hp'] < 45 and meds < 4:
                    u = await call(session, 'use_item', {'item': 'jinchuang', 'quantity': 1,
                                                         'location': '临江城'})
                    meds += 1
                    if u.get('__unexpected__'):
                        break
            observe('与独眼狼交手 %d 回合（狼会还手）、应急吃药 %d 次：%s'
                     % (hits, meds, '击杀' if dead else '未分胜负'))
            observe('引擎一次 combat 只结算一方出手（单边）；双方对打由宿主各调一次——本局按此演')
            st = await call(session, 'read_state', {})
            ux('真打会掉血且没死', 1 <= st['entities']['player']['hp'] < 100,
               'hp=%s' % st['entities']['player']['hp'])
            if dead:
                corpse = await call(session, 'combat', {'attacker': 'player', 'defender': 'wolf'})
                observe('再打尸体：hit=%s dead=%s（引擎照旧结算，行为待议）'
                         % (corpse.get('hit'), corpse.get('defender_dead')))
            e = await refuse(session, 'combat', {'attacker': 'player', 'defender': '鬼影'})
            ux('打不存在的 NPC→报错可读', e is not None and '不存在' in e, (e or '')[:40])
            e = await refuse(session, 'combat', {'attacker': 'player', 'defender': 'wolf', 'action_type': '跳舞'})
            ux('招式乱填被拒', e is not None and 'attack / heavy / flee' in e)

            print('── 疗伤：现买现用 vs 自备 ────────────────────')
            st = await call(session, 'read_state', {})
            p = st['entities']['player']
            need_heal = p['hp'] < p['hp_max']
            await call(session, 'trade', {'location': '临江城', 'item': 'hui_ling',
                                                'direction': 'buy', 'quantity': 2})
            st = await call(session, 'read_state', {})
            gold_after_buy = st['entities']['player']['gold']
            u = await call(session, 'use_item', {'item': 'hui_ling', 'quantity': 1, 'location': '临江城'})
            ux('用自备的丹药不再扣钱（买时已付）', u.get('gold') == gold_after_buy,
               'buy后=%s 使用后=%s' % (gold_after_buy, u.get('gold')))
            if need_heal:
                ux('丹药确实回血', u.get('hp', 0) > p['hp'], 'hp %s→%s' % (p['hp'], u.get('hp')))
            e = await refuse(session, 'use_item', {'item': '龙涎香', 'location': '临江城'})
            ux('用没有的货被拒', e is not None and '没有' in e, (e or '')[:40])

            print('── 交朋友 & 背因果 ───────────────────────────')
            await call(session, 'social', {'actor': 'player', 'target': 'laowang',
                                           'event': 'gift', 'intensity': 1.0})
            await call(session, 'social', {'actor': 'player', 'target': 'laowang',
                                           'event': 'gift', 'intensity': 999})
            st = await call(session, 'read_state', {})
            rel = (st['relations'].get('laowang:player') or st['relations'].get('player:laowang') or {})
            ux('关系被夹在 ±100 内（刷爆友谊无效）',
               abs(rel.get('affinity', 0)) <= 100 and abs(rel.get('respect', 0)) <= 100,
               'affinity=%s respect=%s' % (rel.get('affinity'), rel.get('respect')))
            e = await refuse(session, 'social', {'actor': 'player', 'target': 'laowang', 'event': '亲'})
            ux('社交动作乱填被拒', e is not None and '只能是' in e)
            for _ in range(5):
                await call(session, 'karma', {'actor': 'player', 'karma_type': 'theft', 'victim': 'laowang'})
            await call(session, 'karma', {'actor': 'player', 'karma_type': 'murder_evil', 'victim': 'wolf'})
            st = await call(session, 'read_state', {})
            observe('因果账本 %d 条（玩家顺手做坏事）' % len(st.get('karma_ledger', [])))

            print('── 冲境界 ───────────────────────────────────')
            st = await call(session, 'read_state', {})
            before_stage = st['entities']['player'].get('stage', 0)
            succ = fail = 0
            for i in range(12):
                ar = await call(session, 'advance', {'next_level': '后天%d' % (i + 1), 'insight': 1.0})
                if ar.get('success'):
                    succ += 1
                else:
                    fail += 1
            st = await call(session, 'read_state', {})
            p = st['entities']['player']
            # 至少要成功一次——否则"成功次数与 stage 增量一致"在 0==0 时恒真，
            # 引擎把 advance 做成永远失败也能全绿。
            ux('12 次高洞察突破至少成功一次（验证成功路径真的可达）', succ > 0,
               '成功%s 失败%s' % (succ, fail))
            ux('突破次数与 stage/心伤对得上',
               p.get('stage', 0) - before_stage == succ and p.get('mind_scars', 0) == fail,
               '成功%s 失败%s stage=%s 心伤=%s' % (succ, fail, p.get('stage'), p.get('mind_scars')))
            ux('连败也不会血崩到 0', p['hp'] >= 1, 'hp=%s' % p['hp'])
            ar = await call(session, 'advance', {'next_level': '渡劫', 'insight': 5.0})
            observe('insight 填 5.0（乱填）：chance=%s（被夹在 0.95 内，没炸）' % ar.get('chance'))

            print('── 新人入局 & 长局工具 ───────────────────────')
            sn = await call(session, 'spawn_npc', {'id': 'ahua', 'name': '阿花', 'faction': '江上渔家',
                                                   'location': '临江城'})
            ux('中途生成新 NPC', sn.get('entity_id') == 'ahua')
            e = await refuse(session, 'spawn_npc', {'id': 'ahua', 'name': '阿花二号'})
            ux('重名 NPC 被拒', e is not None and '已存在' in e)
            await call(session, 'social', {'actor': 'player', 'target': 'ahua', 'event': 'help'})
            await call(session, 'write_summary', {'text': '阿吉在雾隐山城落脚，与老王交好，杀了独眼狼，'
                                                             '在临江、黑风、观星三地都留了脚印。'})
            rc = await call(session, 'recap', {'recent': 8})
            ux('recap 带出摘要与大事记', bool(rc.get('summary')) and len(rc.get('milestones', [])) > 0,
               'milestones=%d' % len(rc.get('milestones', [])))
            rl = await call(session, 'recall', {'query': '独眼狼'})
            observe('recall(独眼狼) 命中 %d 条' % len(rl.get('matches', [])))

            snap = await call(session, 'snapshot', {'label': 'playtest'})
            for _ in range(20):
                await call(session, 'tick', {})
            re1 = await call(session, 'restore', {'snapshot_path': snap['snapshot']})
            st_after = await call(session, 'read_state', {})
            ux('快照回退回到原回合', re1.get('tick') == snap.get('tick')
               and st_after.get('tick') == snap.get('tick'), 'tick=%s' % snap.get('tick'))
            e = await refuse(session, 'restore', {'snapshot_path': snap['snapshot'] + '.不存在'})
            ux('恢复不存在的快照被拒', e is not None and '快照不存在' in e)

            print('── 模型层目录 & 用途演示 ─────────────────────')
            ml = await call(session, 'model_list', {})
            names = {m['name'] for m in ml.get('models', [])}
            ux('模型目录 >=16 且含核心模型', len(names) >= 16
               and {'lerner_price', 'ou_price', 'sir_step', 'lotka_volterra'} <= names,
               '%d 个模型' % len(names))
            sir = await call(session, 'model', {'name': 'sir_step',
                                                'params': {'s': 0.99, 'i': 0.01, 'r': 0.0,
                                                           'beta': 0.6, 'gamma': 0.2}})
            v = sir.get('value', [0, 0, 0])
            ux('SIR 一步归一（s+i+r ≈ 1）', abs(sum(v) - 1.0) < 1e-6, 'sir=%s' % [round(x, 4) for x in v])
            e = await refuse(session, 'model', {'name': '算命模型'})
            ux('未知模型报错给出可用清单', e is not None and '未知模型' in e, (e or '')[:60])

            print('── 收摊核对：状态文件仍自洽 ───────────────────')
            with open(state_path, encoding='utf-8') as f:
                disk = json.load(f)
            p = disk['entities']['player']
            ux('钱 >= 0 且不为小数', p['gold'] >= 0 and float(p['gold']) == int(p['gold']), 'gold=%s' % p['gold'])
            ux('血在 [1, hp_max]', 1 <= p['hp'] <= p['hp_max'], 'hp=%s/%s' % (p['hp'], p['hp_max']))
            bad_prices = [(loc, k, it['price'], it['base_price'])
                          for loc, mk in disk.get('market', {}).items()
                          for k, it in mk.items()
                          if not (0 < it['price'] <= 3 * max(1, it['base_price']))]
            ux('全部价格在 (0, 3×基准]', not bad_prices, str(bad_prices[:2]))
            bad_rel = [k for k, r in disk.get('relations', {}).items()
                       if abs(r.get('affinity', 0)) > 100 or abs(r.get('respect', 0)) > 100]
            ux('全部关系夹在 ±100 内', not bad_rel, str(bad_rel[:2]))
            keep = disk.get('config', {}).get('event_log_keep', 200)
            ux('事件日志不超上限', len(disk.get('event_log', [])) <= keep,
               '%d/%d' % (len(disk.get('event_log', [])), keep))
            ux('因果账本不超上限', len(disk.get('karma_ledger', [])) <= 500,
               '%d 条' % len(disk.get('karma_ledger', [])))
            ux('突破 stage 不超上限', p.get('stage', 0) <= 20, 'stage=%s' % p.get('stage'))

    # 汇总
    fails = [n for ok, n in CHECKS if not ok]
    print('\n── 玩家视角小结 ─────────────────────────────────')
    print('工具调用 %d 次 · 优雅拒绝 %d 次 · 意外异常 %d 次'
          % (CALLS['n'], CALLS['graceful'], CALLS['unexpected']))
    print('检查项 %d 个：通过 %d · 不过 %d' % (len(CHECKS), len(CHECKS) - len(fails), len(fails)))
    if not fails and CALLS['unexpected'] == 0:
        print('玩家体验：全绿。')
        return 0
    print('玩家会投诉的点：')
    for n in fails:
        print('  - %s' % n)
    return 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
