#!/usr/bin/env python3
"""
濒死保护验证 (verify_near_death.py)

锁定一条设计决策：玩家永不真正死亡（气血保底 1），但气血归零必须付出
真实且落盘的代价——掉钱 30%、心伤 +1、事件与大事记留痕。

为什么需要这个文件：此前玩家 hp 落 0 后既不死也不罚，可继续以 0 血战斗；
stress_freeplay 靠直接改内存 p['hp']=hp_max 假装复活，状态文件从未变化。

三条契约（详见 .aqg/code-construction/player-near-death.md）：
  R1 玩家气血不得归零：任意结算后 hp >= 1，结果带 near_death=true
  R2 濒死代价必须落盘：gold 扣 30%、mind_scars +1、事件日志含「濒死」
  R3 NPC 死亡语义不变：NPC 气血归零仍是 defender_dead=true

用法:  python scripts/verify_near_death.py
退出码: 0 = 全绿；1 = 有失败项
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

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

from game_engine.rules.combat import resolve_combat        # noqa: E402
from game_engine.state_schema import load_state, save_state  # noqa: E402

RESULTS = []


def check(name, ok, note=''):
    RESULTS.append(bool(ok))
    print('%s  %-52s %s' % ('PASS' if ok else 'FAIL', name, note))


def base_state(player_hp=1, gold=100, npc_hp=1):
    return {
        'tick': 5,
        'rng_seed': 1,
        'rng_counter': 0,
        'entities': {
            'player': {'name': '阿吉', 'hp': player_hp, 'hp_max': 100, 'gold': gold,
                       'mp': 10, 'mp_max': 10, 'attrs': {'str': 10, 'dex': 10, 'con': 10}},
            'brute': {'name': '恶汉', 'hp': npc_hp, 'hp_max': 50, 'gold': 5,
                      'attrs': {'str': 30, 'dex': 20, 'con': 5}},
        },
        'relations': {}, 'market': {}, 'karma_ledger': [], 'world_flags': [],
        'event_log': [], 'milestones': [], 'config': {},
    }


def force_hit(state, attacker, defender):
    """用必中且高伤的参数结算（恶汉 str30 打 1 血玩家必倒）。"""
    import random
    random.seed(7)
    out = None
    for _ in range(200):
        out = resolve_combat(state, attacker, defender, 'heavy')
        if out.get('hit'):
            return out
    return out


def r1_player_never_zero():
    st = base_state(player_hp=1)
    out = force_hit(st, 'brute', 'player')
    hp_after = st['entities']['player']['hp']
    check('R1 玩家气血不归零（hp >= 1）', out.get('hit') and hp_after >= 1,
          'hit=%s hp=%s' % (out.get('hit'), hp_after))
    check('R1 濒死结算带 near_death 标记', out.get('near_death') is True,
          'near_death=%s' % out.get('near_death'))
    return st, out


def r2_cost_persisted(st, out):
    cost = out.get('near_death_cost') or {}
    check('R2 药费/掉钱写入结算结果（gold -30%）', cost.get('gold_lost') == 30,
          'cost=%s gold=%s' % (cost, st['entities']['player']['gold']))
    check('R2 心伤 +1', st['entities']['player'].get('mind_scars') == 1,
          'mind_scars=%s' % st['entities']['player'].get('mind_scars'))
    # 落盘后重读，证明不是只改内存
    tmp = tempfile.mkdtemp(prefix='ww-neardeath-')
    path = os.path.join(tmp, 'nd.save.json')
    save_state(st, path)
    disk = load_state(path)
    check('R2 重读状态文件后代价仍在（真实落盘）',
          disk['entities']['player']['gold'] == 70
          and disk['entities']['player'].get('mind_scars') == 1,
          'gold=%s scars=%s' % (disk['entities']['player']['gold'],
                                disk['entities']['player'].get('mind_scars')))
    return tmp


def r3_npc_dies():
    st = base_state()
    force_hit(st, 'brute', 'player')
    st2 = base_state()
    out2 = force_hit(st2, 'player', 'brute')
    check('R3 NPC 气血归零仍判死亡', out2.get('defender_dead') is True
          and st2['entities']['brute']['hp'] == 0,
          'dead=%s hp=%s' % (out2.get('defender_dead'), st2['entities']['brute']['hp']))
    check('R3 NPC 死亡不触发 near_death', out2.get('near_death') in (None, False),
          'near_death=%s' % out2.get('near_death'))


def main():
    st, out = r1_player_never_zero()
    r2_cost_persisted(st, out)
    r3_npc_dies()
    passed = sum(RESULTS)
    print('\n%d/%d passed' % (passed, len(RESULTS)))
    return 0 if passed == len(RESULTS) else 1


if __name__ == '__main__':
    sys.exit(main())
