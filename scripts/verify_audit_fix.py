#!/usr/bin/env python3
"""
审计修复回归 (verify_audit_fix.py)

锁定 2026-10-30 审计抓出的七组缺陷的修复（详见 .aqg/code-construction/audit-fix-20261030.md）：

  R1  快照 label 不许路径穿越：`snapshot(label="..\\x")` 不得在状态目录外落文件
  R2  状态读-改-写并发安全：同进程多线程 / 跨进程并发 save_state 不丢更新
  R3  游戏档案数值必须可序列化：NaN/Infinity 不得经 game_adjust 落进状态文件
      （浏览器 JSON.parse 遇 `Infinity` 直接抛错，面板会整页挂掉）
  R4  事业线奖励：浮点 gold 不许静默丢失；flags 只收非空字符串
  R5  战斗边界：尸体（hp<=0）不能攻击；skill.power 非有限正数按缺省处理不崩溃
  R6  突破校验：同阶内不许倒退（淬体七段 -> 淬体一段 拒绝）
  R7  上下文台账 fact id 不回绕碰撞：seq>9999 后 id 仍唯一

用法:  python scripts/verify_audit_fix.py
退出码: 0 = 全绿；1 = 有失败项
"""

import json
import os
import random
import subprocess
import sys
import tempfile
import threading
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('WORLD_GAMES_STATE_ROOT', ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from _tmpdir import workspace_tmpdir  # noqa: E402

# 仓库根即 game_engine 包（与 engine.py 同样的包别名引导，任意目录名可跑）
if 'game_engine' not in sys.modules:
    import importlib.util
    _spec = importlib.util.spec_from_file_location(
        'game_engine', os.path.join(ROOT, '__init__.py'),
        submodule_search_locations=[ROOT])
    _pkg = importlib.util.module_from_spec(_spec)
    _pkg.__path__ = [ROOT]
    sys.modules['game_engine'] = _pkg
    # 真正执行 __init__.py：包级元数据（__version__ 等）在里面；只建对象不执行会拿不到。
    _spec.loader.exec_module(_pkg)

RESULTS = []


def check(name, ok, note=''):
    RESULTS.append(bool(ok))
    print('%s  %-56s %s' % ('PASS' if ok else 'FAIL', name, str(note)[:60]))


def fresh_state():
    return {'tick': 1, 'rng_seed': 20261014, 'entities': {
        'player': {'name': 'P', 'hp': 100, 'hp_max': 100, 'mp': 50, 'mp_max': 50,
                   'gold': 100, 'attrs': {'str': 12, 'dex': 12, 'con': 12}},
        'npc': {'name': 'N', 'hp': 50, 'hp_max': 50, 'gold': 10,
                'attrs': {'str': 8, 'dex': 8, 'con': 8}},
    }, 'relations': {}, 'market': {}, 'karma_ledger': [], 'world_flags': [],
        'event_log': [], 'checks': [], 'config': {}}


# ── R1 快照 label 路径穿越 ────────────────────────────────
def r1_snapshot_label_traversal():
    mcp = _load_mcp_for_audit()
    d = workspace_tmpdir()
    sp = os.path.join(d, 'a.json')
    mcp.world_init(state_path=sp, world=mcp.WorldInfo(name='W'),
                   player=mcp.EntityIn(name='P'))
    outside = os.path.abspath(os.path.join(d, 'OUTSIDE.txt'))
    if os.path.exists(outside):
        os.remove(outside)
    try:
        r = mcp.snapshot(label=os.sep.join(['..'] * 4 + ['OUTSIDE.txt']))
        dst = os.path.normpath(r['snapshot'])
        check('R1 快照 label 带穿越段也不落目录外', not os.path.exists(outside)
              and dst.startswith(os.path.normpath(os.path.abspath(d))), dst)
    except ValueError as exc:
        check('R1 快照 label 带穿越段也不落目录外', True, 'rejected: %s' % str(exc)[:40])
    finally:
        mcp._active['path'] = None


# ── R2 状态读-改-写并发安全 ───────────────────────────────
def _worker(state_path, tag, err_box):
    from game_engine.state_schema import transact_state
    try:
        def edit(state):
            state['tick'] = int(state.get('tick', 0)) + 1
            state['event_log'].append({'tick': state['tick'], 'type': 'w', 'desc': tag})
        transact_state(edit, state_path)
    except Exception as exc:  # aqg: top-level boundary —— 探针线程把失败带回主线程
        err_box.append('%s: %s' % (tag, exc))


def r2_concurrent_rmw():
    from game_engine.state_schema import load_state, save_state
    d = workspace_tmpdir()
    p = os.path.join(d, 'race.json')
    save_state(fresh_state(), p)
    err_box = []
    threads = [threading.Thread(target=_worker, args=(p, 't%d' % i, err_box))
               for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    final = load_state(p)
    # fresh_state 基线 tick=1：10 个 worker 各 +1 → 11；事件各 1 条 → 10
    check('R2 10 线程读-改-写不丢更新', final['tick'] == 11 and len(final['event_log']) == 10,
          'tick=%d events=%d' % (final['tick'], len(final['event_log'])))

    child = os.path.join(workspace_tmpdir(),
                         '_xproc_child.py')
    with open(child, 'w', encoding='utf-8') as f:
        f.write(
            "import sys, os, importlib.util\n"
            "ROOT = r'%s'\n"
            "spec = importlib.util.spec_from_file_location('game_engine',\n"
            "    os.path.join(ROOT, '__init__.py'), submodule_search_locations=[ROOT])\n"
            "pkg = importlib.util.module_from_spec(spec); pkg.__path__ = [ROOT]\n"
            "sys.modules['game_engine'] = pkg; spec.loader.exec_module(pkg)\n"
            "from game_engine.state_schema import transact_state\n"
            "p, tag = sys.argv[1], sys.argv[2]\n"
            "def edit(state):\n"
            "    state['tick'] = int(state.get('tick', 0)) + 1\n"
            "    state['event_log'].append({'tick': state['tick'], 'type': 'w', 'desc': tag})\n"
            "transact_state(edit, p)\n" % ROOT)
    procs = [subprocess.Popen([sys.executable, child, p, 'w%d' % i],
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
             for i in range(6)]
    fails = [pr.communicate()[1].decode('utf-8', 'ignore') for pr in procs]
    for pr in procs:
        if pr.returncode != 0:
            err_box.append(fails[procs.index(pr)][:120])
    final2 = load_state(p)
    # 线程轮终态（tick=11/events=10）之上再 6 进程各 +1 → 17 / 16
    check('R2 6 进程读-改-写不丢更新',
          final2['tick'] == 17 and len(final2['event_log']) == 16 and not err_box,
          'tick=%d events=%d errs=%s' % (final2['tick'], len(final2['event_log']),
                                         err_box[:1]))


# ── R3 档案数值可序列化（NaN/Infinity 拒绝）────────────────
def r3_gamesystem_finite():
    from game_engine.rules import gamesystem as G
    g = {'game': G.normalize({'resources': [{'key': 'sanity', 'min': 0, 'max': 10, 'value': 5}]})}
    r = G.adjust(g, 'sanity', value=float('inf'))
    check('R3 adjust(+inf) 回退原值不落盘 inf', r['after'] == 5, r['after'])
    g2 = {'game': G.normalize({'resources': [{'key': 'sanity', 'min': 0, 'max': 10, 'value': 5}]})}
    r2 = G.adjust(g2, 'sanity', value=float('nan'))
    check('R3 adjust(nan) 回退原值不落盘 nan', r2['after'] == 5, r2['after'])
    g3 = {'game': G.normalize({'resources': [{'key': 'sanity', 'min': 0, 'max': 0, 'value': 50}]})}
    r3 = G.adjust(g3, 'sanity', delta=float('inf'))
    check('R3 无界条目 adjust(inf) 回退原值', r3['after'] == 50, r3['after'])
    ok = True
    try:
        json.dumps(g3['game'], allow_nan=False)
    except ValueError:
        ok = False
    check('R3 档案可被严格 JSON 序列化', ok)


# ── R4 事业线奖励 ────────────────────────────────────────
def r4_questline_reward():
    from game_engine.rules import questline as Q
    q = Q.normalize({'id': 'q', 'stages': [{'id': 'a', 'next': []}],
                     'reward': {'gold': 200.5, 'flags': ['真相']}})
    st = {'tick': 0, 'entities': {'player': {'gold': 0}}, 'quests': {}}
    Q.complete_stage(st, [q], 'q', 'a', tick=1)
    check('R4 浮点 gold 奖励不静默丢失', st['entities']['player']['gold'] == 200,
          st['entities']['player']['gold'])
    check('R4 字符串 flags 整体入旗不拆字', st.get('world_flags') == ['真相'],
          st.get('world_flags'))
    q3 = Q.normalize({'id': 'q3', 'stages': [{'id': 'a', 'next': []}],
                      'reward': {'flags': [{'x': 1}]}})
    st3 = {'tick': 0, 'entities': {'player': {'gold': 0}}, 'quests': {}}
    Q.complete_stage(st3, [q3], 'q3', 'a', tick=1)
    check('R4 非字符串 flags 被拒不入旗', not (st3.get('world_flags') or []),
          st3.get('world_flags'))


# ── R5 战斗边界 ─────────────────────────────────────────
def r5_combat_boundary():
    from game_engine.rules.combat import resolve_combat
    st = fresh_state()
    st['entities']['npc']['hp'] = 0
    random.seed(1)
    r = resolve_combat(st, 'npc', 'player', 'attack')
    check('R5 尸体不能攻击（hit=False 不掉血）', r['hit'] is False
          and st['entities']['player']['hp'] == 100, r.get('events', [])[:1])
    st2 = fresh_state()
    random.seed(4)
    r2 = resolve_combat(st2, 'player', 'npc', 'attack',
                        {'name': 'X', 'power': float('inf')})
    check('R5 skill.power=inf 不崩溃且不炸伤害', isinstance(r2.get('damage'), int)
          and r2['damage'] >= 0, r2.get('events', [])[:1])
    st3 = fresh_state()
    random.seed(31)
    r3 = resolve_combat(st3, 'player', 'player', 'attack')
    check('R5 自攻击 outcome=draw 不掉血', r3.get('outcome') == 'draw'
          and st3['entities']['player']['hp'] == 100,
          '%s hp=%s' % (r3.get('outcome'), st3['entities']['player']['hp']))


# ── R6 突破校验：同阶不许倒退 ─────────────────────────────
def r6_progression_no_downgrade():
    from game_engine.rules.progression import validate_next_level
    tiers = ['淬体', '引元', '元府']
    st = {'config': {'level_tiers': tiers}}
    try:
        validate_next_level(st, '淬体一段', '淬体七段')
        check('R6 同阶倒退被拒绝', False, '淬体七段 -> 淬体一段 未拒绝')
    except ValueError as exc:
        check('R6 同阶倒退被拒绝', '倒退' in str(exc), str(exc)[:50])
    st2 = {'config': {'level_tiers': tiers}}
    out = validate_next_level(st2, '淬体九段', '淬体七段')
    check('R6 同阶内正常递进仍放行', out == '淬体九段', out)


# ── R7 fact id 不回绕碰撞 ────────────────────────────────
def r7_context_id_unique():
    from game_engine.rules import context as CX
    st = {'tick': 5, 'context': {'seq': 9999, 'facts': []}}
    seen = set()
    dup = False
    for i in range(6):
        r = CX.remember(st, 'fact-%d' % i, 'fact')
        if r['fact']['id'] in seen:
            dup = True
        seen.add(r['fact']['id'])
    check('R7 seq>9999 后 fact id 仍唯一', not dup and len(seen) == 6,
          sorted(seen)[:3])


def _install_mcp_stubs():
    if 'mcp' in sys.modules and 'pydantic' in sys.modules:
        return
    class _Server:
        def __init__(self, *args, **kwargs):
            self.tools = {}
        def tool(self, *args, **kwargs):
            def decorate(fn):
                self.tools[fn.__name__] = fn
                return fn
            return decorate
        def prompt(self, *args, **kwargs):
            return lambda fn: fn
        def run(self, *args, **kwargs):
            raise RuntimeError('MCP stub cannot run a server')
    class _Model:
        def __init_subclass__(cls, **kwargs):
            return super().__init_subclass__()
        def __init__(self, **values):
            hints = getattr(self.__class__, '__annotations__', {})
            for key, value in hints.items():
                if key in values:
                    setattr(self, key, values[key])
                elif hasattr(self.__class__, key):
                    default = getattr(self.__class__, key)
                    setattr(self, key, default() if callable(default) else default)
                else:
                    setattr(self, key, None)
        def model_dump(self, exclude_none=False):
            out = dict(self.__dict__)
            return {k: v for k, v in out.items() if v is not None} if exclude_none else out
    def _field(default=None, default_factory=None, **kwargs):
        if default_factory is not None:
            return default_factory
        return default
    mcp = types.ModuleType('mcp')
    server = types.ModuleType('mcp.server')
    fast = types.ModuleType('mcp.server.fastmcp')
    fast.FastMCP = _Server
    exc = types.ModuleType('mcp.server.fastmcp.exceptions')
    exc.ToolError = RuntimeError
    fast.exceptions = exc
    server.fastmcp = fast
    mcp.server = server
    sys.modules.update({'mcp': mcp, 'mcp.server': server,
                        'mcp.server.fastmcp': fast,
                        'mcp.server.fastmcp.exceptions': exc})
    pyd = types.ModuleType('pydantic')
    pyd.BaseModel = _Model
    pyd.Field = _field
    sys.modules['pydantic'] = pyd


def _load_mcp_for_audit():
    _install_mcp_stubs()
    import importlib
    sys.modules.pop('game_engine.mcp_server', None)
    return importlib.import_module('game_engine.mcp_server')


# ── R8 restore uses current disk state and snapshot atomically ───────────────
def r8_restore_transaction():
    mcp = _load_mcp_for_audit()
    d = workspace_tmpdir()
    current_path = os.path.join(d, 'current.json')
    snapshot_path = current_path + '.snap.before'
    baseline = fresh_state()
    baseline['tick'] = 2
    baseline['archive_generation'] = 4
    baseline['event_log'] = [{'tick': 2, 'type': 'x', 'desc': 'before'}]
    mutated = json.loads(json.dumps(baseline))
    mutated['tick'] = 9
    mutated['entities']['npc']['name'] = 'after'
    from game_engine.state_schema import save_state, load_state
    save_state(baseline, snapshot_path)
    save_state(mutated, current_path)
    mcp._active['path'] = current_path
    restored = mcp.restore(snapshot_path)
    disk = load_state(current_path)
    check('R8 restore 将快照状态原子写回当前磁盘状态',
          disk['tick'] == 2 and disk['entities']['npc']['name'] == 'N'
          and restored['tick'] == 2 and restored['archive_generation'] > 4,
          'tick=%s gen=%s' % (disk.get('tick'), disk.get('archive_generation')))
    mcp._active['path'] = None


# ── R9 rejected input leaves active path and state unchanged ─────────────────
def r9_input_rejection_isolated():
    mcp = _load_mcp_for_audit()
    d = workspace_tmpdir()
    state_path = os.path.join(d, 'current.json')
    from game_engine.state_schema import save_state, load_state
    before = fresh_state()
    save_state(before, state_path)
    mcp._active['path'] = state_path
    old_path = mcp._active['path']
    try:
        mcp.character_card_read(os.path.join(d, '..', 'escape.json'))
    except Exception:
        pass
    after = load_state(state_path)
    check('R9 拒绝路径输入不改变 active path/原状态',
          mcp._active['path'] == old_path and after == before,
          mcp._active['path'])
    mcp._active['path'] = None


# ── R10 state mutation uses transaction and persists behavior ────────────────
def r10_mutation_transaction():
    mcp = _load_mcp_for_audit()
    d = workspace_tmpdir()
    state_path = os.path.join(d, 'current.json')
    from game_engine.state_schema import save_state, load_state
    save_state(fresh_state(), state_path)
    mcp._active['path'] = state_path
    result = mcp.travel('new-place', note='transaction')
    disk = load_state(state_path)
    check('R10 mutating tool 事务后行为落盘',
          result.get('location') == 'new-place'
          and disk['entities']['player']['location'] == 'new-place'
          and disk['event_log'][-1]['type'] == 'travel',
          str(result))
    mcp._active['path'] = None


# ── R11 backup exists after replacement ─────────────────────────────────────
def r11_backup_behavior():
    from game_engine.state_schema import save_state, load_state
    d = workspace_tmpdir()
    path = os.path.join(d, 'backup.json')
    first = fresh_state()
    save_state(first, path)
    second = json.loads(json.dumps(first))
    second['tick'] = 7
    save_state(second, path)
    backup = path + '.bak'
    check('R11 状态替换保留上一版 backup',
          os.path.exists(backup) and load_state(backup)['tick'] == first['tick']
          and load_state(path)['tick'] == 7,
          'current=%s backup=%s' % (load_state(path)['tick'], load_state(backup)['tick']))


# ── R12 failed transaction restores in-memory state and disk ─────────────────
def r12_transaction_rollback():
    from game_engine.state_schema import load_state, save_state, transact_state
    d = workspace_tmpdir()
    path = os.path.join(d, 'rollback.json')
    original = fresh_state()
    save_state(original, path)
    box = []
    def edit(state):
        state['tick'] = 999
        state['event_log'].append({'tick': 999, 'type': 'bad', 'desc': 'must rollback'})
        box.append(state)
        raise ValueError('forced transaction failure')
    try:
        transact_state(edit, path)
    except ValueError:
        pass
    disk = load_state(path)
    check('R12 事务失败回滚磁盘与内存状态且不留坏事件',
          disk == original and box and box[0]['tick'] == original['tick']
          and not box[0]['event_log'],
          'tick=%s events=%s' % (disk['tick'], len(disk['event_log'])))


def r13_read_only_tools_do_not_save():
    mcp = _load_mcp_for_audit()
    d = workspace_tmpdir()
    path = os.path.join(d, 'readonly.json')
    from game_engine.state_schema import save_state
    state = fresh_state()
    state['systems'] = {'defs': {}, 'rt': {}}
    save_state(state, path)
    mcp._active['path'] = path
    try:
        mcp.system_define({'id': 'clock', 'kind': 'time', 'config': {}})
        mcp.system_define({'id': 'loot', 'kind': 'loot', 'config': {'tables': {}}})
        with open(path, 'rb') as handle:
            before_bytes = handle.read()
        before_mtime = os.stat(path).st_mtime_ns
        for _ in range(3):
            mcp.game_profile()
            mcp.game_profile(profile=None)
            mcp.system_run('clock')
            mcp.system_run('clock', action='status')
            mcp.system_run('clock', action='')
            mcp.system_run('loot', action='list')
        with open(path, 'rb') as handle:
            after_bytes = handle.read()
        after_mtime = os.stat(path).st_mtime_ns
        check('R13 只读 game_profile/system_run 连续调用不落盘',
              after_bytes == before_bytes and after_mtime == before_mtime,
              'bytes=%s mtime=%s' % (after_bytes == before_bytes,
                                     after_mtime == before_mtime))
    finally:
        mcp._active['path'] = None


def main():

    r1_snapshot_label_traversal()
    r2_concurrent_rmw()
    r3_gamesystem_finite()
    r4_questline_reward()
    r5_combat_boundary()
    r6_progression_no_downgrade()
    r7_context_id_unique()
    r8_restore_transaction()
    r9_input_rejection_isolated()
    r10_mutation_transaction()
    r11_backup_behavior()
    r12_transaction_rollback()
    r13_read_only_tools_do_not_save()
    failed = RESULTS.count(False)
    print('\n%d/%d 通过' % (len(RESULTS) - failed, len(RESULTS)))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
