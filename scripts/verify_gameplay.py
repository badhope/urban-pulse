#!/usr/bin/env python3
"""
玩法层自检 (verify_gameplay.py)

为什么需要：项目新增了「玩法剧本 / 事业线 / 世界书引擎」三层，它们共同决定
"这一局到底怎么玩"。这三层最容易犯的错不是崩，而是**静默不生效**：
剧本字段写错被回退、任务永远停在第一幕、世界书递归把整本书塞进上下文。

本脚本把三类语义钉成可执行断言：
  G1  playbook：四种循环可配、进度轴取值正确、失败钟只在 clock 模式推进、节拍按 tick 循环
  G2  questline：DAG 校验（环/幽灵 next 必须报错）、可见性、exit_if 推进、奖励只发一次、失败优先
  G3  lorebook：selectiveLogic 四值、sticky 不续期、cooldown 生效、同组互斥、概率确定性、递归可关
  G4  集成：load_setting 后 playbook/questlines 真的落盘；tick 推进事业线并写编年史
  G5  回退一致性：同状态 + 同 tick 触发同一批条目（不消耗 rng_counter）

用法:  python scripts/verify_gameplay.py
退出码: 0 = 全绿；1 = 有失败项
"""

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if 'game_engine' not in sys.modules:
    import importlib.util
    _spec = importlib.util.spec_from_file_location(
        'game_engine', os.path.join(ROOT, '__init__.py'),
        submodule_search_locations=[ROOT])
    _pkg = importlib.util.module_from_spec(_spec)
    _pkg.__path__ = [ROOT]
    sys.modules['game_engine'] = _pkg
    _spec.loader.exec_module(_pkg)

from game_engine import settings_loader as SL              # noqa: E402
from game_engine.state_schema import load_state, save_state, seed_rng  # noqa: E402
from game_engine.rules import lorebook as LB              # noqa: E402
from game_engine.rules import playbook as PB              # noqa: E402
from game_engine.rules import questline as QL             # noqa: E402
from game_engine.rules import questline as quest_rules   # noqa: E402
from game_engine.rules.economy import tick_market          # noqa: E402
from game_engine.rules.world_evolution import evolve       # noqa: E402

RESULTS = []


def check(name, ok, note=''):
    RESULTS.append(bool(ok))
    print('%s  %-56s %s' % ('PASS' if ok else 'FAIL', name, str(note)[:70]))


def state_of(**extra):
    st = {'tick': 0, 'rng_seed': 42, 'config': {},
          'entities': {'player': {'name': '甲', 'hp': 10, 'hp_max': 10,
                                  'mp': 5, 'mp_max': 10, 'gold': 50, 'stage': 2,
                                  'attrs': {'int': 12}}},
          'relations': {}, 'codex': {}, 'world_flags': [], 'event_log': [],
          'karma_ledger': [], 'quests': {}}
    st.update(extra)
    return st


# ── G1 玩法剧本 ────────────────────────────────────────────
def g1_playbook():
    for loop in PB.LOOPS:
        pb, notes = PB.normalize({'loop': loop})
        check('G1 循环类型 %s 可配置且无回退提示' % loop,
              pb['loop'] == loop and not notes, str(notes))
    pb, notes = PB.normalize({'loop': 'nonexistent'})
    check('G1 未知循环回退 freeform 并记录原因',
          pb['loop'] == 'freeform' and bool(notes), str(notes))

    pb, _ = PB.normalize({'progress': {'axis': 'knowledge', 'max': 10}})
    st = state_of()
    st['codex'] = {'locations': ['a', 'b'], 'people': ['x'], 'items': [], 'lore': ['l1']}
    prog = PB.progress_of(st, pb)
    check('G1 进度轴 knowledge = 图鉴条目总数（2+1+0+1=4）',
          prog['value'] == 4 and prog['ratio'] == 0.4, str(prog))

    pb, _ = PB.normalize({'progress': {'axis': 'reputation', 'max': 100}})
    st = state_of(relations={'a:player': {'affinity': 5, 'respect': 20},
                             'player:b': {'affinity': -5, 'respect': 10}})
    check('G1 进度轴 reputation = 与玩家有关的 respect 之和（30）',
          PB.progress_of(st, pb)['value'] == 30, str(PB.progress_of(st, pb)))

    pb, _ = PB.normalize({'failure': {'mode': 'clock', 'max': 4}})
    st = state_of()
    PB.tick_failure(st, pb, 2, '受伤')
    PB.tick_failure(st, pb, 2, '受伤')      # 同 tick 同 reason：幂等
    fs = PB.failure_state(st, pb)
    check('G1 失败钟只在 clock 模式推进且同 tick 同原因幂等',
          fs['value'] == 2 and fs['max'] == 4 and not fs['failed'], str(fs))
    PB.tick_failure(st, pb, 3, '再拖')
    check('G1 失败钟填满即 failed', PB.failure_state(st, pb)['failed'] is True,
          str(PB.failure_state(st, pb)))

    pb_hp, _ = PB.normalize({'failure': {'mode': 'hp'}})
    st2 = state_of()
    PB.tick_failure(st2, pb_hp, 5, '不该生效')
    check('G1 非 clock 模式下 failure_tick 不写状态',
          not st2.get('failure_clock'), str(st2.get('failure_clock')))

    pb, _ = PB.normalize({'beat': {'pattern': ['a', 'b', 'c'], 'every': 4}})
    beats = [PB.beat_at(pb, t)['name'] for t in (0, 4, 8, 12)]
    check('G1 节拍按 tick 循环（4 回合 / 3 拍）', beats == ['a', 'b', 'c', 'a'], str(beats))
    check('G1 空状态下不误报失败', PB.failure_state({'tick': 0}, {})['failed'] is False)

    catalogue = PB.configurable_axes()
    check('G1 配置枚举齐全（循环/输入/失败模式）',
          set(catalogue['loops']) == set(PB.LOOPS)
          and set(catalogue['failure_modes']) == set(PB.FAILURE_MODES), str(len(catalogue['guides'])))


# ── G2 事业线 ──────────────────────────────────────────────
def q(raw):
    return QL.normalize(raw)


def g2_questline():
    # 环检测
    try:
        QL.normalize({'id': 'cyclic', 'stages': [
            {'id': 'a', 'next': ['b']}, {'id': 'b', 'next': ['a']}]})
        cyclic_ok = False
    except ValueError as exc:
        cyclic_ok = '环' in str(exc)
    check('G2 stage 图有环必须报错', cyclic_ok)

    try:
        QL.normalize({'id': 'ghost', 'stages': [{'id': 'a', 'next': ['nope']}]})
        ghost_ok = False
    except ValueError as exc:
        ghost_ok = 'next' in str(exc)
    check('G2 next 指向不存在的 stage 必须报错', ghost_ok)

    quest = q({'id': 'main', 'title': '主线', 'visibility': {'flag': '开'}, 'reward': {'gold': 50},
               'stages': [
                   {'id': 's1', 'title': '一', 'exit_if': {'gold_gte': 60}, 'next': ['s2']},
                   {'id': 's2', 'title': '二', 'exit_if': {'flag': '完成'}, 'next': []}]})
    st = state_of()
    changes = QL.advance(st, [quest])
    check('G2 未满足 visibility 时保持 dormant（且不出现在面板列表）',
          changes == [] and st['quests']['main']['status'] == 'dormant'
          and QL.status(st, [quest]) == [], str(st['quests']['main']['status']))
    st['world_flags'].append('开')
    ch1 = QL.advance(st, [quest])
    check('G2 满足 visibility 后浮现并进入第一幕',
          st['quests']['main']['status'] == 'active' and st['quests']['main']['stage'] == 's1'
          and any(c['change'] == 'revealed' for c in ch1), str(ch1))
    check('G2 exit_if 未满足时停在原幕（不自动往前跑）',
          QL.advance(st, [quest]) == [], str(st['quests']['main']['stage']))
    st['entities']['player']['gold'] = 100
    ch2 = QL.advance(st, [quest])
    check('G2 exit_if 满足后推进到下一幕',
          st['quests']['main']['stage'] == 's2'
          and any(c['change'] == 'stage' for c in ch2), str(ch2))
    st['world_flags'].append('完成')
    QL.advance(st, [quest])
    gold_after = st['entities']['player']['gold']
    QL.advance(st, [quest])
    check('G2 整条完成后发一次奖励且不重复发',
          st['quests']['main']['status'] == 'done' and gold_after == 150
          and st['entities']['player']['gold'] == 150, '%s' % st['entities']['player']['gold'])

    # 失败优先
    quest_fail = q({'id': 'f', 'visibility': None, 'deadline_tick': 5,
                    'stages': [{'id': 'a', 'exit_if': {'flag': 'never'}, 'next': []}]})
    st2 = state_of(tick=6)
    QL.advance(st2, [quest_fail])
    check('G2 超过 deadline 判失败（优先于推进）',
          st2['quests']['f']['status'] == 'failed', str(st2['quests']['f']))

    # 手动完成
    quest_manual = q({'id': 'm', 'stages': [{'id': 'a', 'next': ['b']},
                                            {'id': 'b', 'next': []}]})
    st3 = state_of()
    QL.advance(st3, [quest_manual])
    QL.complete_stage(st3, [quest_manual], 'm', 'a')
    check('G2 手动完成一幕会进入下一幕',
          st3['quests']['m']['stage'] == 'b', str(st3['quests']['m']))
    QL.complete_stage(st3, [quest_manual], 'm', 'b')
    check('G2 手动完成最后一幕即整条完成',
          st3['quests']['m']['status'] == 'done', str(st3['quests']['m']['status']))

    # 可见性过滤：dormant 不出现在面板
    st4 = state_of()
    QL.advance(st4, [quest])
    hidden = QL.status(st4, [quest])
    check('G2 dormant 任务不出现在状态列表', hidden == [], str(hidden))

    # 谓词
    st5 = state_of(world_flags=['x'])
    st5['entities']['player']['items'] = {'key1': 3}
    st5['counters'] = {'kills': 4}
    st5['relations'] = {'abc:player': {'affinity': 30, 'respect': 5}}
    st5['codex'] = {'locations': ['港口']}
    st5['milestones'] = [{'kind': '击杀', 'desc': '击败了 守卫'}]
    st5['quests'] = {'doneq': {'status': 'done', 'done_stages': ['s1']}}
    st5['config'] = {'level_tiers': ['一阶', '二阶', '三阶']}
    st5['entities']['player']['level'] = '二阶'
    preds = [
        ({'flag': 'x'}, True), ({'flag': 'y'}, False),
        ({'all': [{'flag': 'x'}, {'gold_gte': 10}]}, True),
        ({'any': [{'flag': 'y'}, {'gold_gte': 10}]}, True),
        ({'not': {'flag': 'y'}}, True),
        ({'item_gte': {'key': 'key1', 'n': 3}}, True),
        ({'counter_gte': {'key': 'kills', 'n': 5}}, False),
        ({'bogus_key': 1}, False),
        ({'visited': '港口'}, True),
        ({'visited': '沙漠'}, False),
        ({'killed': '守卫'}, True),
        ({'killed': '路人'}, False),
        ({'relation_gte': {'with': 'abc', 'affinity': 30}}, True),
        ({'relation_gte': {'with': 'abc', 'affinity': 31}}, False),
        ({'relation_gte': {'with': 'abc', 'respect': 5}}, True),
        ({'stage_done': {'quest': 'doneq', 'stage': 's1'}}, True),
        ({'stage_done': {'quest': 'doneq', 'stage': 's9'}}, False),
        ({'quest_done': 'doneq'}, True),
        ({'quest_done': 'noq'}, False),
        ({'tier_gte': 1}, True),
        ({'karma_gte': 1}, False),
        ({'tick_gte': 1}, False),
    ]
    ok = all(QL.evaluate(st5, pred) is want for pred, want in preds)
    check('G2 谓词求值（all/any/not/flag/item/counter/未知键 fail-closed）', ok)


# ── G3 世界书 ──────────────────────────────────────────────
def g3_lorebook():
    def entry(**kw):
        base = {'keys': ['灯'], 'content': '灯的内容', 'comment': kw.pop('comment', 'e'),
                'order': 10, 'enabled': True}
        base.update(kw)
        return base

    # selectiveLogic 四值
    def fires(logic, text):
        e = entry(keys=['雨'], secondary_keys=['夜', '风'], selective=True,
                  selective_logic=logic, comment='x')
        return [x['comment'] for x in
                LB.trigger({'tick': 0, 'rng_seed': 1, 'config': {}, 'lore_runtime': {}},
                           [e], [text], tick=0, apply_runtime=False)['entries']]

    check('G3 selectiveLogic=AND_ANY 需任一副键',
          fires('AND_ANY', '雨夜') == ['x'] and fires('AND_ANY', '雨') == [])
    check('G3 selectiveLogic=AND_ALL 需全部副键',
          fires('AND_ALL', '雨夜风') == ['x'] and fires('AND_ALL', '雨夜') == [])
    check('G3 selectiveLogic=NOT_ANY 需无副键命中',
          fires('NOT_ANY', '雨雪') == ['x'] and fires('NOT_ANY', '雨夜') == [])
    check('G3 selectiveLogic=NOT_ALL 需非全部副键命中',
          fires('NOT_ALL', '雨夜') == ['x'] and fires('NOT_ALL', '雨夜风') == [])

    # sticky 不续期
    st_sticky = {'tick': 0, 'rng_seed': 3, 'config': {}, 'lore_runtime': {}}
    sticky = entry(comment='s', sticky=2)
    seen = []
    for t in range(1, 7):
        st_sticky['tick'] = t
        hit = LB.trigger(st_sticky, [sticky], ['灯'], tick=t)
        seen.append((t, bool(hit['entries']), hit['entries'][0]['_reason'] if hit['entries'] else ''))
    reasons = [r for _, on, r in seen if on]
    # sticky=2 的语义：触发当回合 + 之后 2 回合都以 sticky 保持，之后回到正常关键词触发。
    # 关键不是"总共只出现 3 次"，而是 **sticky 不会无限续期**（reason 必须回到 keyword）。
    check('G3 sticky 保持 2 回合后回到正常触发（不无限续期）',
          reasons[:4] == ['keyword', 'sticky', 'sticky', 'keyword'],
          str(reasons))

    # cooldown
    st_cd = {'tick': 0, 'rng_seed': 3, 'config': {}, 'lore_runtime': {}}
    cd = entry(comment='c', cooldown=3)
    fired = []
    for t in range(1, 7):
        st_cd['tick'] = t
        fired.append(bool(LB.trigger(st_cd, [cd], ['灯'], tick=t)['entries']))
    # cooldown=3 起算于触发回合：t1 触发 → t2/t3 冷却 → t4 可再次触发（周期 3）
    check('G3 cooldown 期间不重复触发（t1 触发，t2/t3 冷却，t4 恢复）',
          fired == [True, False, False, True, False, False], str(fired))

    # 同组互斥
    st_g = {'tick': 1, 'rng_seed': 9, 'config': {}, 'lore_runtime': {}}
    g = [entry(comment='g1', group='grp'), entry(comment='g2', group='grp')]
    winners = set()
    for seed in range(1, 12):
        st_g['rng_seed'] = seed
        st_g['lore_runtime'] = {}
        got = LB.trigger(st_g, g, ['灯'], tick=1)['entries']
        winners.add(tuple(sorted(x['comment'] for x in got)))
    check('G3 同组只出一条（且不同种子会换人）',
          all(len(w) == 1 for w in winners) and len(winners) > 1, str(winners))

    # 概率确定性
    st_p = {'tick': 5, 'rng_seed': 77, 'config': {}, 'lore_runtime': {}}
    prob = entry(comment='p', probability=50)
    first = [x['comment'] for x in LB.trigger(st_p, [prob], ['灯'], tick=5,
                                              apply_runtime=False)['entries']]
    second = [x['comment'] for x in LB.trigger(st_p, [prob], ['灯'], tick=5,
                                               apply_runtime=False)['entries']]
    check('G3 概率触发在同状态同 tick 下结果一致（确定性）', first == second, str(first))

    # 递归默认关闭
    st_r = {'tick': 1, 'rng_seed': 1, 'config': {}, 'lore_runtime': {}}
    chain = [entry(comment='a', keys=['甲'], content='乙'), entry(comment='b', keys=['乙'], content='丙')]
    off = LB.trigger(st_r, chain, ['甲'], tick=1, apply_runtime=False)
    st_r['config'] = {'lore_recursion': 2}
    st_r['lore_runtime'] = {}
    on = LB.trigger(st_r, chain, ['甲'], tick=1, apply_runtime=False)
    check('G3 递归默认关闭，显式开启后才扫第二层',
          len(off['entries']) == 1 and len(on['entries']) == 2, '%d vs %d' % (
              len(off['entries']), len(on['entries'])))

    # 概率/时间闸不会消耗 rng_counter
    st_c = {'tick': 3, 'rng_seed': 5, 'config': {}, 'lore_runtime': {}, 'rng_counter': 0}
    LB.trigger(st_c, [entry(comment='z', probability=30)], ['灯'], tick=3)
    check('G3 世界书触发不消耗 rng_counter（INV-E7）', st_c['rng_counter'] == 0,
          str(st_c['rng_counter']))

    # delay：前 N 回合不触发
    st_d = {'tick': 1, 'rng_seed': 1, 'config': {}, 'lore_runtime': {}}
    delayed = entry(comment='d', delay=3)
    hits = []
    for t in (1, 2, 3, 4):
        st_d['tick'] = t
        hits.append(bool(LB.trigger(st_d, [delayed], ['灯'], tick=t)['entries']))
    check('G3 delay 前 N 回合不触发，第 N 回合起恢复',
          hits == [False, False, True, True], str(hits))

    # match_whole_words：只对拉丁文有"词边界"概念；中文没有词边界，
    # 因此实现上只把 ASCII 字母数字当词内字符（这样 "cat" 不会命中 "concatenate"，
    # 而「灯」仍然能命中「灯塔」——这是中文的固有语义，不是缺陷）。
    st_w = {'tick': 1, 'rng_seed': 1, 'config': {}, 'lore_runtime': {}}
    whole = entry(comment='w', keys=['cat'], match_whole_words=True)
    check('G3 match_whole_words：拉丁词不误命中同缀长词',
          not LB.trigger(st_w, [whole], ['concatenate'], tick=1)['entries']
          and bool(LB.trigger(st_w, [whole], ['a cat here'], tick=1)['entries']))

    # group_override
    st_o = {'tick': 1, 'rng_seed': 5, 'config': {}, 'lore_runtime': {}}
    ov = [entry(comment='o1', group='go'), entry(comment='o2', group='go', group_override=True)]
    check('G3 group_override 直接指定组内赢家',
          [x['comment'] for x in LB.trigger(st_o, ov, ['灯'], tick=1)['entries']] == ['o2'])

    # group scoring（SillyTavern filterGroupsByScoring 同义）：
    # 同组两条都命中时，选命中键更多的；不给 use_group_scoring 时仍按权重抽签。
    st_gs = {'tick': 1, 'rng_seed': 5, 'config': {}, 'lore_runtime': {}}
    gs = [entry(comment='loose', keys=['灯'], group='g2'),
          entry(comment='exact', keys=['灯', '塔'], group='g2', use_group_scoring=True)]
    picked = set()
    for seed in range(1, 12):
        st_gs['rng_seed'] = seed
        st_gs['lore_runtime'] = {}
        picked.add(tuple(x['comment'] for x in LB.trigger(st_gs, gs, ['灯塔'], tick=1)['entries']))
    check('G3 group scoring 恒选命中键最多的条目', picked == {('exact',)}, str(picked))
    st_gs2 = {'tick': 1, 'rng_seed': 5, 'config': {}, 'lore_runtime': {}}
    gs2 = [entry(comment='loose', keys=['灯'], group='g3'),
           entry(comment='exact', keys=['灯', '塔'], group='g3')]
    winners2 = set()
    for seed in range(1, 20):
        st_gs2['rng_seed'] = seed
        st_gs2['lore_runtime'] = {}
        winners2.add(tuple(x['comment'] for x in
                           LB.trigger(st_gs2, gs2, ['灯塔'], tick=1)['entries']))
    check('G3 未开 group scoring 时组内仍抽签', len(winners2) > 1, str(winners2))

    # exclude_recursion
    st_x = {'tick': 1, 'rng_seed': 1, 'config': {'lore_recursion': 2}, 'lore_runtime': {}}
    chain_x = [entry(comment='a', keys=['甲'], content='乙'),
               entry(comment='b', keys=['乙'], content='丙', exclude_recursion=True)]
    check('G3 exclude_recursion 的条目不被递归拉入',
          len(LB.trigger(st_x, chain_x, ['甲'], tick=1,
                         apply_runtime=False)['entries']) == 1)

    # 未知 selective_logic 回退 AND_ANY
    st_u = {'tick': 1, 'rng_seed': 1, 'config': {}, 'lore_runtime': {}}
    weird = entry(comment='u', keys=['雨'], secondary_keys=['夜'], selective=True,
                  selective_logic='TOTALLY_BOGUS')
    check('G3 未知 selective_logic 回退 AND_ANY',
          [x['comment'] for x in LB.trigger(st_u, [weird], ['雨夜'], tick=1)['entries']] == ['u'])

    # once / max_fires（借 ink once-only choice：关键剧情不重复注入）
    st_once = {'tick': 1, 'rng_seed': 1, 'config': {}, 'lore_runtime': {}}
    one = entry(comment='one', once=True)
    seen_once = []
    for t in (1, 2, 3):
        st_once['tick'] = t
        seen_once.append(bool(LB.trigger(st_once, [one], ['灯'], tick=t)['entries']))
    check('G3 once 条目只触发一次', seen_once == [True, False, False], str(seen_once))
    st_cap = {'tick': 1, 'rng_seed': 1, 'config': {}, 'lore_runtime': {}}
    capped = entry(comment='cap', max_fires=2)
    seen_cap = []
    for t in (1, 2, 3, 4):
        st_cap['tick'] = t
        seen_cap.append(bool(LB.trigger(st_cap, [capped], ['灯'], tick=t)['entries']))
    check('G3 max_fires 达上限后不再触发', seen_cap == [True, True, False, False], str(seen_cap))
    skipped_reason = LB.trigger({'tick': 5, 'rng_seed': 1, 'config': {}, 'lore_runtime': {
        'fired_count': {'cap': 2}, 'last_fired': {}, 'sticky_until': {},
        'cooldown_until': {}, 'delayed_until': {}}}, [capped], ['灯'], tick=5)['skipped']
    check('G3 闸门原因写进 skipped 供面板解释', [x['why'] for x in skipped_reason] == ['max_fires'],
          str(skipped_reason))

    # runtime_summary
    st_s = {'tick': 10, 'rng_seed': 1, 'config': {}, 'lore_runtime': {}}
    e = entry(comment='sum')
    LB.trigger(st_s, [e], ['灯'], tick=10)
    rows = LB.runtime_summary(st_s, [e])
    check('G3 runtime_summary 报触发次数与剩余时间',
          rows[0]['fired'] == 1 and rows[0]['last_tick'] == 10, str(rows[0]))


# ── G4 集成：设定包 + tick（零依赖路径）───────────────────
def _load_bundle(name, path):
    """用 settings_loader 起一局（不 import mcp —— CI 的 core 作业没装 mcp SDK）。"""
    with open(os.path.join(ROOT, 'settings', '%s.setting.json' % name), encoding='utf-8') as f:
        bundle = json.load(f)
    st = SL.build_state(bundle)
    SL.apply_runtime_fields(st, bundle)
    save_state(st, path)
    return st


def _tick_once(path):
    """与 MCP tick 同义的一步：市场 + 世界演化 + 事业线 + tick+1。"""
    st = load_state(path)
    seed_rng(st)
    tick_market(st)
    st['tick'] = int(st.get('tick', 0) or 0) + 1
    evolve(st)
    quest_rules.advance(st, st.get('questlines') or [], tick=int(st['tick']))
    save_state(st, path)
    return st


def g4_integration():
    tmp = tempfile.mkdtemp(prefix='ww-gameplay-')
    for name in ('玄枢界', '折剑行', '霓虹深渊', '雾港'):
        sp = os.path.join(tmp, name + '.json')
        st = _load_bundle(name, sp)
        check('G4 %s 的 playbook 落盘' % name,
              bool(st.get('playbook')) and st['playbook']['loop'] in PB.LOOPS,
              st.get('playbook', {}).get('loop'))
        check('G4 %s 的 questlines 落盘（≥2 条）' % name,
              len(st.get('questlines') or []) >= 2, str(len(st.get('questlines') or [])))
        for _ in range(3):
            _tick_once(sp)
        st2 = load_state(sp)
        active = {k: v for k, v in (st2.get('quests') or {}).items()
                  if v.get('status') == 'active'}
        check('G4 %s tick 后至少有事业线进入 active' % name, len(active) >= 1, str(len(active)))
        check('G4 %s tick 后 playbook 仍在状态里' % name,
              bool(st2.get('playbook')), str(st2.get('playbook', {}).get('loop')))


# ── G5 回退一致性 ─────────────────────────────────────────
def g5_determinism():
    tmp = tempfile.mkdtemp(prefix='ww-gameplay-det-')
    a = os.path.join(tmp, 'a.json')
    b = os.path.join(tmp, 'b.json')
    sa0 = _load_bundle('雾港', a)
    sb0 = _load_bundle('雾港', b)

    diff_keys = [k for k in set(sa0) | set(sb0) if sa0.get(k) != sb0.get(k)]
    check('G5 两次载入的初始状态逐字段一致', diff_keys == [],
          '差异字段=%s' % (diff_keys[:3] or '无'))

    # 同一 tick 同一文本 → 同一命中集合（世界书确定性）
    ra = LB.trigger(sa0, sa0.get('lore') or [], ['灯塔 名册 沉船湾'], tick=0, apply_runtime=False)
    rb = LB.trigger(sb0, sb0.get('lore') or [], ['灯塔 名册 沉船湾'], tick=0, apply_runtime=False)
    check('G5 同种子同回合的世界书命中完全一致',
          [x['comment'] for x in ra['entries']] == [x['comment'] for x in rb['entries']],
          '%d 条' % len(ra['entries']))

    # 连续 tick 两步后两个副本逐字节一致（排除 event_log 的时间顺序无关性）
    for _ in range(3):
        _tick_once(a)
        _tick_once(b)
    fa = open(a, 'rb').read()
    fb = open(b, 'rb').read()
    check('G5 两个副本连跑 3 回合后逐字节一致', fa == fb, '%d vs %d 字节' % (len(fa), len(fb)))


def main():
    g1_playbook()
    g2_questline()
    g3_lorebook()
    g4_integration()
    g5_determinism()
    passed = sum(RESULTS)
    print('\n%d/%d passed' % (passed, len(RESULTS)))
    return 0 if passed == len(RESULTS) else 1


if __name__ == '__main__':
    sys.exit(main())
