#!/usr/bin/env python3
"""
通用游戏层自检 (verify_generic.py)

为什么需要：World Games 的新定位是"通用于所有游戏"。支撑它的三层是
`rules/checks.py`（任意判定）、`rules/gamesystem.py`（自定义档案）、
`rules/context.py`（上下文台账），加上 `sessions.py`（存档库）与面板的新区块。
这些能力最容易犯的错是**静默不生效**：判定永远成功、资源不夹紧、上下文超出预算、
存档互相覆盖。本脚本把它们钉成可执行断言。

覆盖：
  N1 判定：四种模式、自然极值、对抗、属性修正、记录有界、确定性
  N2 游戏档案：旧存档回退推导、自定义资源 clamp、标签、自由表格、条目上限
  N3 上下文：事实增删查、结案/过期、预算打包、去重
  N4 存档库：新建/列表/快照/回收站/还原/导入，路径安全
  N5 集成：MCP 工具端到端 + 面板视图模型字段
  N6 品牌：World Games 默认值与可覆盖性

用法:  python scripts/verify_generic.py
退出码: 0 = 全绿；1 = 有失败
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

from game_engine.rules import checks as CK          # noqa: E402
from game_engine.rules import context as CTX       # noqa: E402
from game_engine.rules import gamesystem as GS     # noqa: E402
from game_engine.state_schema import save_state, seed_rng  # noqa: E402
from game_engine import sessions as SS            # noqa: E402

RESULTS = []
STRICT_FAILURES = []


def check(name, got, want, tol=1e-9):
    ok = False
    try:
        if isinstance(want, (int, float)) and isinstance(got, (int, float)) \
                and not isinstance(want, bool) and not isinstance(got, bool):
            ok = abs(float(got) - float(want)) <= tol * max(1.0, abs(float(want)))
        else:
            ok = got == want
    except Exception:
        ok = False
    RESULTS.append(bool(ok))
    print('%s  %-54s got=%s want=%s' % ('PASS' if ok else 'FAIL', name, got, want))


def check_true(name, cond, note=''):
    RESULTS.append(bool(cond))
    print('%s  %-54s %s' % ('PASS' if cond else 'FAIL', name, str(note)[:70]))


def check_raises(name, fn, exc=ValueError):
    try:
        fn()
    except exc:
        RESULTS.append(True)
        print('PASS  %-54s raises %s' % (name, exc.__name__))
        return
    except Exception as e:
        RESULTS.append(False)
        print('FAIL  %-54s raised %s（期望 %s）' % (name, type(e).__name__, exc.__name__))
        return
    RESULTS.append(False)
    print('FAIL  %-54s 未抛异常' % name)


def base_state(**extra):
    st = {
        'tick': 4, 'rng_seed': 42, 'rng_counter': 0, 'config': {},
        'entities': {
            'player': {'name': '甲', 'hp': 30, 'hp_max': 50, 'mp': 4, 'mp_max': 10,
                       'gold': 20, 'level': '两级', 'location': 'L',
                       'attrs': {'str': 12, 'dex': 8, 'int': 14, 'con': 10, 'cha': 9}},
            'npc': {'name': '乙', 'hp': 40, 'hp_max': 40, 'mp': 0, 'mp_max': 0,
                    'gold': 0, 'location': 'L', 'attrs': {'str': 10, 'int': 16}},
        },
        'relations': {}, 'event_log': [], 'karma_ledger': [], 'world_flags': [],
        'market': {}, 'playbook': {'loop': 'ttrpg',
                                   'progress': {'axis': 'level', 'label': '进度', 'max': 10}},
        'world_info': {'name': '测试世界'},
    }
    st.update(extra)
    return st


# ── N1 判定 ────────────────────────────────────────────────
def n1_checks():
    st = base_state()
    seed_rng(st)
    r = CK.resolve_check(st, 'player', attribute='str', difficulty=0, dice='d20', mode='add')
    check('N1 属性修正直接加到总值', r['total'] - r['raw'], 12)
    check('N1 判定写入 checks 台账', len(st['checks']), 1)

    # 自然 20 / 自然 1：用 d1 边界不行，改为直接构造 bands + 大量抽样找极值
    found_max = found_min = False
    for i in range(200):
        st['rng_counter'] = i
        seed_rng(st)
        out = CK.resolve_check(st, 'player', difficulty=15, dice='d20', record=False)
        found_max = found_max or out['natural_max']
        found_min = found_min or out['natural_min']
    check('N1 d20 自然 1/20 都能被识别', (found_max, found_min), (True, True))

    # 四种模式都能出结果
    for mode, dice in (('add', '2d6'), ('roll_under', 'd100'), ('pool', 'pool'), ('fate', '4dF')):
        st['rng_counter'] = 7
        seed_rng(st)
        out = CK.resolve_check(st, 'player', difficulty=10, dice=dice, mode=mode,
                              pool_size=5, record=False)
        check_true('N1 模式 %s 返回成功等级' % mode,
                   out.get('level') in ('critical_success', 'success', 'partial', 'failure'),
                   str(out.get('level')))

    # 游戏档案里定义的自定义属性必须能直接用于判定（否则只是面板装饰）
    stp = base_state()
    GS.set_profile(stp, {'attributes': [{'key': 'per', 'label': '感知', 'value': 13}]})
    stp['rng_counter'] = 5
    seed_rng(stp)
    rp = CK.resolve_check(stp, 'player', 'per', difficulty=0, dice='2d6', record=False)
    check('N1 档案自定义属性参与判定（按 key）', rp['attr_mod'], 13)
    stp['rng_counter'] = 6
    seed_rng(stp)
    rl = CK.resolve_check(stp, 'player', '感知', difficulty=0, dice='2d6', record=False)
    check('N1 档案自定义属性参与判定（按 label）', rl['attr_mod'], 13)

    # 对抗判定：margin = 我 - 对方
    st['rng_counter'] = 3
    seed_rng(st)
    opp = CK.resolve_check(st, 'player', attribute='str', difficulty=10, dice='d20',
                           opposed_by='npc', record=False)
    check('N1 对抗判定的 difficulty 等于对方总值', opp['difficulty'], opp['opposed']['total'])
    check('N1 对抗判定 margin = 我 - 对方', opp['margin'], opp['total'] - opp['opposed']['total'])

    # 修正值：dict / 纯数字都能用
    st['rng_counter'] = 11
    seed_rng(st)
    mod = CK.resolve_check(st, 'player', difficulty=0, dice='d20',
                           modifiers=[{'value': 3, 'label': '装备'}, 2], record=False)
    check('N1 修正值合计', mod['mod_total'], 5)

    # 台账有界
    st = base_state(config={'checks_keep': 10})
    for i in range(40):
        st['rng_counter'] = i
        seed_rng(st)
        CK.resolve_check(st, 'player', difficulty=10)
    check('N1 判定台账有界（checks_keep）', len(st['checks']), 10)

    # 确定性：同 state 同 counter 同参数 → 同结果
    a, b = base_state(), base_state()
    seed_rng(a)
    ra = CK.resolve_check(a, 'player', difficulty=12, dice='2d6', record=False)
    seed_rng(b)
    rb = CK.resolve_check(b, 'player', difficulty=12, dice='2d6', record=False)
    check('N1 同种子同参数判定的骰面', ra['rolls'], rb['rolls'])

    # 错误输入
    check_raises('N1 未知骰型被拒绝', lambda: CK.parse_dice('2x6'))
    check_raises('N1 骰子数量越界被拒绝', lambda: CK.parse_dice('0d6'))
    check_raises('N1 不存在的实体被拒绝',
                 lambda: CK.resolve_check(base_state(), 'ghost', difficulty=10))

    rate = CK.win_rate({'checks': [{'level': 'success'}, {'level': 'failure'}]})
    check('N1 成功率统计', rate['rate'], 0.5)


# ── N2 游戏档案 ────────────────────────────────────────────
def n2_gamesystem():
    st = base_state()
    prof = GS.profile_of(st)
    check('N2 旧存档回退：资源来自 hp/mp/gold',
          [r['key'] for r in prof['resources']], ['hp', 'mp', 'gold'])
    check('N2 旧存档回退：属性来自 attrs', len(prof['attributes']), 5)
    check('N2 旧存档回退：kind 默认 rpg', prof['kind'], 'rpg')

    custom = {
        'title': '雾港调查', 'kind': 'investigation',
        'resources': [{'key': 'sanity', 'label': '理智', 'value': 8, 'min': 0, 'max': 10}],
        'attributes': [{'key': 'per', 'label': '感知', 'value': 13}],
        'meters': [{'key': 'clue', 'label': '线索', 'value': 2, 'min': 0, 'max': 10}],
        'tags': ['戒严', '雨季'],
        'sheet': {'职业': '记者'},
    }
    saved = GS.set_profile(st, custom)
    check('N2 自定义档案落盘', saved['kind'], 'investigation')
    check('N2 标签保留', saved['tags'], ['戒严', '雨季'])
    check('N2 自由表格保留', saved['sheet']['职业'], '记者')

    up = GS.adjust(st, 'sanity', delta=-20)
    check('N2 资源下限夹紧', up['after'], 0)
    check('N2 触底标记', up['at_min'], True)
    up2 = GS.adjust(st, 'sanity', value=99)
    check('N2 资源上限夹紧', up2['after'], 10)
    up3 = GS.adjust(st, 'per', kind='attributes', delta=2)
    check('N2 属性可调整', up3['after'], 15)
    auto = GS.adjust(st, 'clue', delta=1)
    check('N2 不传 kind 时自动定位到 meters', (auto['kind'], auto['after']), ('meters', 3))
    check_raises('N2 不存在的资源被拒绝', lambda: GS.adjust(st, 'mana', delta=1))

    tag = GS.add_tag(st, '空袭')
    check('N2 标签可追加', tag['tags'], ['戒严', '雨季', '空袭'])
    GS.add_tag(st, '空袭', remove=True)
    check('N2 标签可移除', GS.add_tag(st, '空袭')['tags'], ['戒严', '雨季', '空袭'])

    # 条目上限
    many = {'resources': [{'key': 'r%d' % i, 'value': i} for i in range(50)]}
    check('N2 条目数封顶 MAX_ENTRIES', len(GS.normalize(many)['resources']), GS.MAX_ENTRIES)

    # 坏条目跳过而不是整局失败
    bad = {'resources': [{'key': 'ok'}, {'nokey': 1}]}
    check_raises('N2 缺 key 的条目报错（不静默丢）', lambda: GS.normalize(bad))

    # kind 非法回退 custom
    check('N2 未知 kind 回退 custom', GS.normalize({'kind': 'shooter'})['kind'], 'custom')


# ── N3 上下文台账 ─────────────────────────────────────────
def n3_context():
    st = base_state()
    a = CTX.remember(st, '沈伯说灯塔三年前就熄了', kind='clue', keys=['灯塔', '沈伯'])
    check('N3 事实写入并分配 id', a['fact']['id'], 'f1')
    dup = CTX.remember(st, '沈伯说灯塔三年前就熄了', kind='clue', keys=['灯塔'])
    check('N3 重复正文刷新而非重复追加', dup['created'], False)
    check('N3 重复后总数仍为 1', dup['total'], 1)

    CTX.remember(st, '答应替林小姐送信', kind='promise', keys=['林小姐'])
    check('N3 按关键词检索', len(CTX.search(st, keys=['灯塔'])), 1)
    check('N3 全文检索', len(CTX.search(st, query='送信')), 1)
    check('N3 按类型过滤', len(CTX.search(st, kind='promise')), 1)
    check('N3 无匹配返回空', len(CTX.search(st, query='不存在的事')), 0)

    st['tick'] += 3
    CTX.remember(st, '临时线索：雨停了', kind='clue', keys=['雨'], ttl=1)
    st['tick'] += 3
    got = CTX.search(st, keys=['雨'])
    check('N3 ttl 过期后默认不可见', got, [])

    fact_id = a['fact']['id']
    closed = CTX.set_status(st, fact_id, 'done')
    check('N3 结案状态落盘', closed['status'], 'done')
    check('N3 结案后默认检索不含它', len(CTX.search(st, keys=['灯塔'])), 0)
    check('N3 status="" 可以查全部', len(CTX.search(st, keys=['灯塔'], status='')), 1)

    removed = CTX.forget(st, kind='promise')
    check('N3 按类型删除', removed['count'], 1)
    check_raises('N3 无条件的 forget 被拒绝', lambda: CTX.forget(st))

    packed = CTX.pack(st, scene_text='灯塔', budget_chars=400)
    check_true('N3 预算打包不超预算', packed['used_chars'] <= 400, str(packed['used_chars']))
    check_true('N3 打包至少一节', len(packed['sections']) >= 1,
               str([s['title'] for s in packed['sections']]))
    tiny = CTX.pack(st, scene_text='灯塔', budget_chars=200)
    check_true('N3 极小预算会截断而不是报错',
               tiny['used_chars'] <= 200, str(tiny.get('truncated')[:1]))

    summary = CTX.summary(st)
    check('N3 汇总统计总数', summary['total'], len(st['context']['facts']))

    # GA 三分量检索：相关比新旧更重要（0.5/3/2 权重），且分值可复算
    # 故意拉开新旧差距：老事实 recency=0、相关度=1.0；新事实 recency=1、相关度=0.5。
    # 只有 relevance 权重足够大（3.0）时老事实才会赢——这条断言专杀"权重写反/清零"。
    st_rank = base_state(tick=1)
    CTX.remember(st_rank, '北塔的钥匙埋在井里', kind='fact', keys=['北塔'], importance=0.5)
    st_rank['tick'] = 100
    CTX.remember(st_rank, '北塔今日风平浪静', kind='fact', keys=['北塔'], importance=0.5)
    ranked = CTX.search(st_rank, query='北塔 钥匙', status='open', limit=10, ranked=True)
    check('N3 GA 检索：高相关旧事实排在低相关新事实之前',
          [f['text'] for f in ranked][0], '北塔的钥匙埋在井里')
    exact = (CTX.SCORE_WEIGHTS['recency'] * ranked[0]['score_detail']['recency']
             + CTX.SCORE_WEIGHTS['relevance'] * ranked[0]['score_detail']['relevance']
             + CTX.SCORE_WEIGHTS['importance'] * ranked[0]['score_detail']['importance'])
    check('N3 检索总分等于三分量加权和', round(ranked[0]['score'], 2), round(exact, 2))
    same_seed = CTX.search(st_rank, query='北塔 钥匙', status='open', limit=10, ranked=True)
    check('N3 同状态检索完全可复现', [f['id'] for f in same_seed], [f['id'] for f in ranked])
    legacy = CTX.search(st_rank, query='北塔', status='open', limit=10)
    check('N3 ranked=False 走置信度排序分支', len(legacy), 2)

    # mem0 式写入期冲突消解：同 subject 的旧事实留档而不是删除
    st_sup = base_state(tick=7)
    first = CTX.remember(st_sup, '灯塔守夜人是老周', kind='npc', subject='灯塔守夜人')
    replaced = CTX.remember(st_sup, '灯塔守夜人换成了小满', kind='npc', subject='灯塔守夜人',
                            supersede=True)
    check('N3 supersede 标记旧事实并指向新事实', replaced['superseded'], [first['fact']['id']])
    check('N3 supersede 后默认检索只剩新事实',
          [f['text'] for f in CTX.search(st_sup, kind='npc')], ['灯塔守夜人换成了小满'])
    closed_rows = CTX.search(st_sup, kind='npc', status='superseded')
    check('N3 superseded 事实仍可按全状态审计查回', len(closed_rows), 1)
    check('N3 审计链记录 superseded_by',
          (closed_rows[0].get('superseded_by') if closed_rows else None),
          replaced['fact']['id'])
    CTX.remember(st_sup, '酒馆老板换人了', kind='npc', subject='酒馆老板', supersede=True)
    check('N3 supersede 只影响同 subject',
          len(CTX.search(st_sup, kind='npc', status='open')), 2)

    # 排序稳定性：新增一条低分事实不应打乱已有高分事实的相对顺序（提示词前缀缓存）
    st_stable = base_state(tick=50)
    for i in range(5):
        CTX.remember(st_stable, '线索%d：灯塔的机关' % i, kind='clue', keys=['灯塔'],
                     importance=0.8)
    before = [f['id'] for f in CTX.search(st_stable, query='灯塔', ranked=True, limit=10)]
    CTX.remember(st_stable, '无关备注', kind='note')
    after = [f['id'] for f in CTX.search(st_stable, query='灯塔', ranked=True, limit=10)]
    check('N3 新增无关事实不改变已有排序', after, [i for i in before if i in after])

    # 编年史检索：recall 旧实现只取最近的匹配，久远的突破永远回不来；
    # 三分量打分后"类型重要 + 文本相关"能压过"刚发生但无关"的噪声。
    st_ev = base_state(tick=500)
    events = [{'tick': 100, 'type': 'breakthrough', 'desc': '突破至筑基'},
              {'tick': 498, 'type': 'combat', 'desc': '攻击被闪避'},
              {'tick': 499, 'type': 'combat', 'desc': '攻击被闪避'},
              {'tick': 300, 'type': 'travel', 'desc': '抵达雾港'}]
    ranked_ev = CTX.rank_events(events, st_ev, '突破', limit=2)
    check('N3 编年史检索把久远突破排在近期噪声之前', ranked_ev[0]['desc'], '突破至筑基')
    check('N3 编年史检索返回三元打分明细',
          sorted((ranked_ev[0].get('score_detail') or {}).keys()),
          ['importance', 'recency', 'relevance'])
    check('N3 编年史检索遵守 limit', len(ranked_ev), 2)

    # GA 反思阈值：累计 importance 过线才 due，write_summary 落点后归零
    st_ref = base_state(tick=30)
    st_ref['config'] = {'context_reflect_threshold': 2.0}
    CTX.remember(st_ref, '第一条', kind='clue', importance=1.0)
    check('N3 反思未达阈值不触发', CTX.reflection_due(st_ref)['due'], False)
    CTX.remember(st_ref, '第二条', kind='clue', importance=1.0)
    due = CTX.reflection_due(st_ref)
    check('N3 反思累计 importance 过阈值触发', (due['due'], due['fresh_facts']), (True, 2))
    CTX.mark_reflected(st_ref)
    after = CTX.reflection_due(st_ref)
    check('N3 mark_reflected 后不重复触发', (after['due'], after['accumulated']), (False, 0.0))
    packed_ref = CTX.pack(st_ref, budget_chars=400)
    check_true('N3 pack 输出反思建议块且已反思后不重复要',
               'reflection' in packed_ref and packed_ref['reflection']['due'] is False,
               str(packed_ref.get('reflection')))

    # 台账有界：超量后仍保留开放事实的数量级
    st2 = base_state()
    for i in range(CTX.MAX_FACTS + 30):
        CTX.remember(st2, '第%d条' % i, kind='note', confidence=0.1)
    check_true('N3 事实台账有界', len(st2['context']['facts']) <= CTX.MAX_FACTS,
               str(len(st2['context']['facts'])))


# ── N4 存档库 ─────────────────────────────────────────────
def n4_sessions():
    tmp = tempfile.mkdtemp(prefix='ww-sessions-')
    old = os.environ.get('WORLD_GAMES_SAVES')
    os.environ['WORLD_GAMES_SAVES'] = os.path.join(tmp, 'saves')
    try:
        root = SS.saves_root(tmp)
        st = base_state()
        p1 = SS.save_path(root, '雾港 调查/第一局', create_dir=True)
        check('N4 局名被安全化（无空格与斜杠）', os.path.basename(p1), '雾港_调查_第一局.save.json')
        save_state(st, p1)
        rows = SS.list_saves(root)
        check('N4 列表能读到世界与回合', (rows[0]['world'], rows[0]['tick']), ('测试世界', 4))
        check('N4 损坏存档被标记而不是崩溃', _broken_entry(root)['broken'], True)

        snap = SS.snapshot(p1, '测试')
        check('N4 快照记录了 tick', snap['tick'], 4)
        check_true('N4 快照文件存在', os.path.exists(snap['snapshot']), snap['snapshot'])
        check('N4 快照可列出', len(SS.list_snapshots(p1)), 1)

        arc = SS.archive(root, p1)
        check_true('N4 归档后原文件消失', not os.path.exists(p1), arc['archived'])
        check('N4 回收站可列出', len(SS.list_trash(root)), 1)
        back = SS.restore_from_trash(root, '雾港_调查_第一局')
        check_true('N4 从回收站还原', os.path.exists(back['restored']), back['restored'])
        check_raises('N4 同名还原被拒绝', lambda: _double_restore(root))
        trash_before = len(SS.list_trash(root))
        purged = SS.purge_trash(root)
        check('N4 purge 删除条数等于回收站原有条数', purged['count'], trash_before)
        check('N4 清空回收站后回收站为空', SS.list_trash(root), [])

        check_raises('N4 空局名被拒绝', lambda: SS.safe_name('   '))
        check('N4 中文局名保留', SS.safe_name('折剑行'), '折剑行')
        check('N4 局名长度封顶', len(SS.safe_name('x' * 100)), SS.MAX_NAME)
    finally:
        if old is None:
            os.environ.pop('WORLD_GAMES_SAVES', None)
        else:
            os.environ['WORLD_GAMES_SAVES'] = old


def _broken_entry(root):
    path = os.path.join(root, 'broken.save.json')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('{not json')
    rows = SS.list_saves(root)
    return next((r for r in rows if r['name'] == 'broken'), {'broken': False})


def _double_restore(root):
    # 回收站里有同名、存档库里也有同名时，restore 必须拒绝覆盖
    trash = os.path.join(root, SS.TRASH_DIR)
    os.makedirs(trash, exist_ok=True)
    for path in (os.path.join(trash, 'dup.save.json'),
                 os.path.join(root, 'dup.save.json')):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'entities': {}, 'tick': 0}, f)
    SS.restore_from_trash(root, 'dup')


# ── N5 集成：MCP 工具 + 面板视图模型 ───────────────────
def n5_integration():
    try:
        import game_engine.mcp_server as MS
    except Exception as exc:  # aqg: top-level boundary —— 可选 MCP 依赖在 core 路径允许缺失
        message = 'N5 需要 mcp SDK：%s' % str(exc)[:60]
        if os.environ.get('WORLD_GAMES_STRICT') == '1':
            RESULTS.append(False)
            STRICT_FAILURES.append(message)
            print('FAIL  %s' % message)
        else:
            print('SKIP  %s' % message)
        return
    import game_engine.panel as PANEL

    tmp = tempfile.mkdtemp(prefix='ww-generic-int-')
    old = os.environ.get('WORLD_GAMES_SAVES')
    os.environ['WORLD_GAMES_SAVES'] = os.path.join(tmp, 'saves')
    old_path = MS._active.get('path')
    try:
        created = MS.session_new('集成测试', setting_path=os.path.join(ROOT, 'settings', '雾港.setting.json'))
        check('N5 session_new 返回存档路径', created['name'], '集成测试')
        check('N5 session_new 设置当前对局', os.path.basename(MS._state_path()), '集成测试.save.json')

        rolled = MS.roll(attribute='int', difficulty=8, dice='2d6', reason='查档案')
        check_true('N5 roll 返回成功等级', 'level' in rolled, rolled.get('level'))

        prof = MS.game_profile({
            'title': '雾港调查', 'kind': 'investigation',
            'resources': [{'key': 'sanity', 'label': '理智', 'value': 8, 'min': 0, 'max': 10}],
            'meters': [{'key': 'clue', 'label': '线索', 'value': 2, 'min': 0, 'max': 10}],
        })
        check('N5 game_profile 设置生效', prof['game']['kind'], 'investigation')
        adj = MS.game_adjust('sanity', delta=-3)
        check('N5 game_adjust 生效', adj['after'], 5)
        check('N5 game_tag 生效', MS.game_tag('戒严')['tags'], ['戒严'])
        check('N5 game_sheet 生效', MS.game_sheet({'职业': '记者'})['count'], 1)

        fact = MS.context_remember('灯塔三年前熄了', kind='clue', keys=['灯塔'])
        check('N5 context_remember 生效', fact['created'], True)
        check('N5 context_search 生效', MS.context_search(query='灯塔')['count'], 1)
        packed = MS.context_pack(scene_text='灯塔', budget_chars=500)
        check_true('N5 context_pack 带 content_policy', bool(packed.get('content_policy')),
                   str(packed.get('content_policy'))[:40])

        vm = PANEL.view_model(MS._state_path())
        check('N5 视图模型带 game 区块', sorted(vm['game'].keys()),
              ['check_rate', 'checks', 'context', 'profile'])
        check('N5 视图模型带 sessions 区块', 'saves' in vm['sessions'], True)
        check('N5 面板能读到自定义资源', [r['key'] for r in vm['game']['profile']['resources']],
              ['sanity'])
        check('N5 面板能读到判定记录', len(vm['game']['checks']), 1)

        snaps = MS.session_snapshot('集成')
        check_true('N5 session_snapshot 生成快照', os.path.exists(snaps['snapshot']), snaps['snapshot'])
        check('N5 session_snapshot list_only', len(MS.session_snapshot(list_only=True)['snapshots']), 1)
    finally:
        MS._active['path'] = old_path
        if old is None:
            os.environ.pop('WORLD_GAMES_SAVES', None)
        else:
            os.environ['WORLD_GAMES_SAVES'] = old


# ── N6 品牌 ───────────────────────────────────────────────
def n6_brand():
    import game_engine.panel as PANEL
    st = base_state(ui={})
    skin = PANEL.skin_for_world(st)
    check('N6 默认品牌是 World Games', skin['brand'], 'World Games')
    check('N6 默认标语', skin['tagline'], '万物皆可为一局 · 规则为证')
    st2 = base_state(ui={'brand': '折剑行', 'tagline': '一柄断剑'})
    skin2 = PANEL.skin_for_world(st2)
    check('N6 设定包可覆盖品牌', (skin2['brand'], skin2['tagline']), ('折剑行', '一柄断剑'))


def main():
    print('── N1 通用判定 ──')
    n1_checks()
    print('\n── N2 游戏档案 ──')
    n2_gamesystem()
    print('\n── N3 上下文台账 ──')
    n3_context()
    print('\n── N4 存档库 ──')
    n4_sessions()
    print('\n── N5 MCP + 面板集成 ──')
    n5_integration()
    print('\n── N6 品牌 ──')
    n6_brand()

    passed = sum(RESULTS)
    print('\n%d/%d passed' % (passed, len(RESULTS)))
    return 0 if passed == len(RESULTS) and not STRICT_FAILURES else 1


if __name__ == '__main__':
    sys.exit(main())
