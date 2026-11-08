#!/usr/bin/env python3
"""
CLI 通道端到端验证 (verify_cli.py)

对 engine.py 的全部子命令做三层验证：
  1. 只读不变量：9 条只读命令不改写状态文件（sha256 前后逐字节一致）
  2. 写通道全覆盖：combat/trade/social/karma/tick 五条 dirty 分支全部落盘，
     且落盘结果可解析、字段有界（rng_counter 恰好 +1、relations 钳位、tick 单调）
  3. 确定性：同种子同行动 → 同结果（三副本 combat 终态哈希一致；
     双副本 12 步混合动作最终状态逐字节相同）

用法:  python scripts/verify_cli.py
退出码: 0 = 全绿；1 = 有失败项
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(ROOT, 'engine.py')
DEMO_STATE = os.path.join(ROOT, 'demo_state.json')

RESULTS = []


def check(name, ok, note=''):
    RESULTS.append(bool(ok))
    print('%s  %-52s %s' % ('PASS' if ok else 'FAIL', name, note))


def sha256(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def fresh_copy(tmp, name):
    """demo_state 的字节级副本（工作区零污染）。"""
    dst = os.path.join(tmp, name)
    shutil.copyfile(DEMO_STATE, dst)
    return dst


def run_cli(state_path, *args):
    """在系统临时目录里跑 CLI（顺带持续验证「任意工作目录可运行」）。"""
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    return subprocess.run([sys.executable, ENGINE, *args, '--state', state_path],
                          capture_output=True, text=True, encoding='utf-8',
                          errors='replace', cwd=tempfile.gettempdir(), env=env)


def _cli_json(stdout):
    """从 CLI stdout 里取出结果 JSON（engine.py 打印的就是纯 JSON）。"""
    try:
        return json.loads(stdout)
    except Exception:
        return {}


def _cli_damage(stdout):
    return _cli_json(stdout).get('damage')


def _cli_total_cost(stdout):
    return _cli_json(stdout).get('total_cost')


# ---------------------------------------------------------------- 1. 只读不变量
READONLY = [
    ('flow', ()), ('identity', ()), ('narrative', ()), ('world_state', ()),
    ('panarchy', ()), ('moral_update', ()),
    ('cognition', ('--entity', 'player')),
    ('merit', ('--aid', '0.5', '--sincerity', '0.5')),
    ('info_weight', ('--probability', '0.5')),
]


def verify_readonly(tmp):
    base_counter = json.load(open(DEMO_STATE, encoding='utf-8')).get('rng_counter', 0)
    # 同一份副本连跑 9 条只读命令：既验单次哈希，也验累计后 rng_counter 未被推进
    p = fresh_copy(tmp, 'ro_all.json')
    hash_before_all = sha256(p)
    for cmd, extra in READONLY:
        before = sha256(p)
        r = run_cli(p, cmd, *extra)
        ok = (r.returncode == 0 and sha256(p) == before)
        check('只读 %s 落盘哈希不变' % cmd, ok,
              '' if ok else 'exit=%s hash_changed=%s' % (r.returncode, sha256(p) != before))
    s = json.load(open(p, encoding='utf-8'))
    check('只读命令不推进 rng_counter（9 条连跑后复核落盘值）',
          s.get('rng_counter') == base_counter,
          'base=%s after=%s' % (base_counter, s.get('rng_counter')))
    check('只读命令累计执行后状态文件逐字节不变',
          sha256(p) == hash_before_all,
          '' if sha256(p) == hash_before_all else 'hash changed')


# ---------------------------------------------------------------- 2. 写通道全覆盖
WRITE = [
    ('combat', ('combat', '--attacker', 'player', '--defender', 'goblin')),
    ('trade', ('trade', '--location', 'bamboo_tea_booth', '--item', 'coarse_tea',
               '--direction', 'buy', '--entity', 'player')),
    ('social', ('social', '--actor', 'player', '--target', 'old_chen', '--event', 'help')),
    ('karma', ('karma', '--actor', 'player', '--karma_type', 'theft', '--victim', 'old_chen')),
    ('tick', ('tick',)),
]


def verify_write(tmp):
    base = json.load(open(DEMO_STATE, encoding='utf-8'))
    base_counter, base_tick = base.get('rng_counter', 0), base.get('tick', 0)
    bp = base['entities']['player']
    for name, args in WRITE:
        p = fresh_copy(tmp, 'w_%s.json' % name)
        r = run_cli(p, *args)
        ok, notes = r.returncode == 0, []
        try:
            s = json.load(open(p, encoding='utf-8'))
            sp = s['entities']['player']
            notes.append('rng_counter %s->%s' % (base_counter, s.get('rng_counter')))
            ok = ok and s.get('rng_counter') == base_counter + 1
            for rel in s.get('relations', {}).values():
                if not (-100 <= rel.get('affinity', 0) <= 100 and -100 <= rel.get('respect', 0) <= 100):
                    ok, notes = False, notes + ['relations 越界']
                    break

            # ── 业务效果：光验 rng_counter 只能证明"落了盘"，证明不了"做了事"。
            #    每条写命令都必须产生自己的可见副作用，否则 resolve_* 整个 no-op 也会全绿。
            if name == 'combat':
                hp0 = base['entities']['goblin']['hp']
                hp1 = s['entities']['goblin']['hp']
                # 精确判据：伤害必须等于 hp 的实际减少量，且事件里报告的数字与之吻合。
                # 只看"hp 变小了"或"有命中字样"会让 damage=0 / 少扣血 这类回归漏网。
                dmg = int(r_damage or 0) if (r_damage := _cli_damage(r.stdout)) is not None else None
                ok = ok and hp1 != hp0
                if hp1 < hp0:
                    ok = ok and dmg is not None and (hp0 - hp1) == dmg
                notes.append('goblin hp %s->%s dmg=%s' % (hp0, hp1, dmg))
            elif name == 'trade':
                item_key = 'coarse_tea'
                qty0 = int((bp.get('items') or {}).get(item_key, 0))
                qty1 = int((sp.get('items') or {}).get(item_key, 0))
                sup0 = int(base['market']['bamboo_tea_booth'][item_key]['supply'])
                sup1 = int(s['market']['bamboo_tea_booth'][item_key]['supply'])
                gold0, gold1 = int(bp.get('gold', 0)), int(sp.get('gold', 0))
                cost = _cli_total_cost(r.stdout)
                # 精确判据：入库恰 1 件、库存恰减 1、扣款恰等于结算总额
                ok = (ok and qty1 == qty0 + 1 and sup0 - sup1 == 1
                      and cost is not None and gold0 - gold1 == cost)
                notes.append('粗茶 %s->%s · 库存 %s->%s · 钱 %s->%s (cost=%s)'
                             % (qty0, qty1, sup0, sup1, gold0, gold1, cost))
            elif name == 'social':
                key = 'old_chen:player'
                r0 = (base.get('relations', {}).get(key) or {})
                r1 = (s.get('relations', {}).get(key) or {})
                a0, a1 = r0.get('affinity', 0), r1.get('affinity', 0)
                p0, p1 = r0.get('respect', 0), r1.get('respect', 0)
                # 精确判据：help 事件的固定增益是 affinity +5、respect +3（rules/social.py:40）
                ok = ok and (a1 - a0) == 5 and (p1 - p0) == 3
                notes.append('%s affinity %s->%s respect %s->%s' % (key, a0, a1, p0, p1))
            elif name == 'karma':
                l0 = len(base.get('karma_ledger') or [])
                l1 = len(s.get('karma_ledger') or [])
                entry = s['karma_ledger'][-1] if l1 > l0 else {}
                # 精确判据：theft 记 15 业，且 from/to/type 都要对
                ok = (ok and l1 == l0 + 1 and entry.get('amount') == 15
                      and entry.get('type') == 'theft' and entry.get('from') == 'player'
                      and entry.get('to') == 'old_chen')
                notes.append('账本 %s->%s %s' % (l0, l1, entry.get('type')))
            elif name == 'tick':
                ok = ok and s.get('tick') == base_tick + 1
                notes.append('tick %s->%s' % (base_tick, s.get('tick')))
            if name != 'tick':
                ok = ok and s.get('tick') == base_tick
        except Exception as e:
            ok, notes = False, notes + ['状态不可解析: %s' % e]
        check('写命令 %s 落盘且业务效果可见' % name, ok,
              ' · '.join(notes) if ok else 'exit=%s %s' % (r.returncode, ' '.join(notes)))


# ---------------------------------------------------------------- 3. 确定性
def verify_determinism(tmp):
    # 3a. 三副本同行动 → 终态逐字节一致
    #     注意：三个副本都失败时也会得到"1 种终态"，那是假通过，必须显式排除。
    hashes, fails = set(), []
    for i in range(3):
        p = fresh_copy(tmp, 'det%d.json' % i)
        r = run_cli(p, 'combat', '--attacker', 'player', '--defender', 'goblin')
        if r.returncode != 0:
            fails.append('副本%d exit=%s' % (i, r.returncode))
            continue
        hashes.add(sha256(p))
    check('三副本同 combat 终态哈希一致', not fails and len(hashes) == 1,
          '%d 种终态' % len(hashes) if not fails else '执行失败: %s' % '; '.join(fails))

    # 3b. 双副本 12 步混合动作（combat/tick 交替）→ 终态逐字节一致
    #     每一步都要验业务结果，不能只看 returncode：否则"每步都成功但什么都没做"
    #     的回归（combat 全 miss、tick 不推进）照样能通过一致性断言。
    finals, last_counter, step_fails = set(), None, []
    hit_counts = {}
    base0 = json.load(open(DEMO_STATE, encoding='utf-8'))
    base_tick0, base_rc0 = base0.get('tick', 0), base0.get('rng_counter', 0)
    for i in range(2):
        p = fresh_copy(tmp, 'mix%d.json' % i)
        for step in range(6):
            rc1 = run_cli(p, 'combat', '--attacker', 'player', '--defender', 'city_guard')
            rc2 = run_cli(p, 'tick')
            if rc1.returncode != 0 or rc2.returncode != 0:
                step_fails.append('副本%d 第%d轮 combat=%s tick=%s'
                                  % (i, step + 1, rc1.returncode, rc2.returncode))
                break
            mid = json.load(open(p, encoding='utf-8'))
            want_tick = base_tick0 + step + 1
            want_rc = base_rc0 + (step + 1) * 2   # 每轮 combat + tick 各推进一次
            if mid.get('tick') != want_tick:
                step_fails.append('副本%d 第%d轮 tick 未推进（%s != %s）'
                                  % (i, step + 1, mid.get('tick'), want_tick))
                break
            if mid.get('rng_counter') != want_rc:
                step_fails.append('副本%d 第%d轮 rng_counter 未按步推进（%s != %s）'
                                  % (i, step + 1, mid.get('rng_counter'), want_rc))
                break
            # 每步 combat 必须真的产生结算：命中则血量下降量必须等于 damage；
            # 只有明确"未命中/闪避"才允许 damage=0。仅判 damage is not None
            # 会让 `damage=0` 或"伤害与扣血不符"的回归静默通过。
            res_step = _cli_json(rc1.stdout) or {}
            dmg_step = res_step.get('damage')
            hit_step = bool(res_step.get('hit'))
            hp_step = mid['entities']['city_guard']['hp']
            hp_max_step = mid['entities']['city_guard'].get('hp_max', 100)
            if dmg_step is None:
                step_fails.append('副本%d 第%d轮 combat 无结算结果' % (i, step + 1))
                break
            if hit_step and int(dmg_step) <= 0:
                step_fails.append('副本%d 第%d轮 命中却零伤害' % (i, step + 1))
                break
            if not hit_step and int(dmg_step) != 0:
                step_fails.append('副本%d 第%d轮 未命中却有伤害 %s' % (i, step + 1, dmg_step))
                break
            if not (0 <= hp_step <= hp_max_step):
                step_fails.append('副本%d 第%d轮 敌方血量越界 %s' % (i, step + 1, hp_step))
                break
            # 已死的目标不能再被打（打尸体是行为错误）
            if mid['entities']['city_guard'].get('_dead_seen') and hit_step:
                step_fails.append('副本%d 第%d轮 对已死目标继续结算' % (i, step + 1))
                break
            if hp_step == 0:
                mid['entities']['city_guard']['_dead_seen'] = True
            if hit_step:
                hit_counts[i] = hit_counts.get(i, 0) + 1
        s = json.load(open(p, encoding='utf-8'))
        last_counter = s.get('rng_counter')
        finals.add(sha256(p))
    min_hits = min(hit_counts.values()) if hit_counts else 0
    check('12 步内每副本至少命中 3 次（防"只在特定条件命中"的实现退化）',
          min_hits >= 3, '最少命中 %d 次（副本 %s）' % (min_hits, hit_counts))
    check('双副本 12 步混合动作终态哈希一致（rng_counter 持久化）',
          not step_fails and len(finals) == 1,
          '%d 种终态' % len(finals) if not step_fails else '中途失败: %s' % '; '.join(step_fails))
    if not step_fails and len(finals) == 1:
        base_counter = json.load(open(DEMO_STATE, encoding='utf-8')).get('rng_counter', 0)
        # CLI 的 tick 必须和 MCP 的 tick 同义：市场 + 世界演化（势力/相位）+ tick+1。
    # 只验 tick+1 会让"CLI 世界永远静止"漏网——那是 INV-E4/E6 的通道分裂（变异 M27 曾存活）。
    wt = fresh_copy(tmp, 'worldtick.json')
    for _ in range(12):
        r = run_cli(wt, 'tick')
    wst = json.load(open(wt, encoding='utf-8'))
    fac = wst.get('factions') or {}
    pan = wst.get('panarchy') or {}
    check('CLI tick 驱动世界演化（势力存量与 Panarchy 相位落盘）',
          r.returncode == 0 and bool(fac) and bool(pan.get('phase'))
          and any(abs(float(v.get('power', 0)) - 32.0) > 0.5 for v in fac.values()),
          'factions=%s phase=%s' % (list(fac)[:3], pan.get('phase')))

    check('混合动作后 rng_counter 累计 +12 并落盘',
              last_counter == base_counter + 12,
              '%s -> %s' % (base_counter, last_counter))


def main():
    tmp = tempfile.mkdtemp(prefix='ww-verify-cli-')
    try:
        verify_readonly(tmp)
        verify_write(tmp)
        verify_determinism(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    n_pass, n_all = sum(RESULTS), len(RESULTS)
    print('\n%d/%d passed' % (n_pass, n_all))
    sys.exit(0 if n_pass == n_all else 1)


if __name__ == '__main__':
    main()
