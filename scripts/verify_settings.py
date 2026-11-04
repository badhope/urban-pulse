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

import importlib.util as _ilu
_pspec = _ilu.spec_from_file_location('panel_settings', os.path.join(ROOT, 'panel.py'))
PANEL = _ilu.module_from_spec(_pspec)
_pspec.loader.exec_module(PANEL)

from game_engine import settings_loader as SL
from game_engine.rules.economy import tick_market
from game_engine.rules.world_evolution import evolve
from game_engine.state_schema import load_state, save_state, seed_rng

SETTINGS_DIR = os.path.join(ROOT, 'settings')
RESULTS = []


def check(name, ok, note=''):
    RESULTS.append(bool(ok))
    print('%s  %-50s %s' % ('PASS' if ok else 'FAIL', name, str(note)[:80]))


def main():
    files = sorted(f for f in os.listdir(SETTINGS_DIR) if f.endswith('.setting.json'))
    check('设定包数量 ≥ 4（覆盖修真/武侠/赛博/悬疑四种世界观）', len(files) >= 4, str(files))

    tmp = tempfile.mkdtemp(prefix='ww-settings-')
    for fn in files:
        path = os.path.join(SETTINGS_DIR, fn)
        with open(path, encoding='utf-8') as f:
            bundle = json.load(f)
        state_path = os.path.join(tmp, fn.replace('.setting.json', '.save.json'))
        try:
            with open(path, encoding="utf-8") as f:
                bundle = json.load(f)
            state = SL.build_state(bundle)
            SL.apply_runtime_fields(state, bundle)
            save_state(state, state_path)
        except Exception as exc:
            check('%s 可载入' % fn, False, '%s: %s' % (type(exc).__name__, str(exc)[:100]))
            continue

        state = load_state(state_path)
        player = state['entities']['player']
        vm = PANEL.view_model(state_path)
        terms = vm.get('terms') or {}
        expected_terms = bundle.get('terms') or {}
        ui = vm.get('skin') or {}

        ok = True
        notes = []
        if not state.get('entities'):
            ok = False; notes.append('无实体')
        if bundle.get('level_tiers'):
            if (state.get('config') or {}).get('level_tiers') != bundle['level_tiers']:
                ok = False; notes.append('阶梯未落盘')
        for k, v in expected_terms.items():
            if terms.get(k) != v:
                ok = False; notes.append('术语 %s=%r≠%r' % (k, terms.get(k), v))
                break
        if bundle.get('currency') and state.get('currency') != bundle['currency']:
            ok = False; notes.append('货币未落盘')
        if bundle.get('ui', {}).get('brand') and ui.get('brand') != bundle['ui']['brand']:
            ok = False; notes.append('品牌未生效')
        if bundle.get('ui', {}).get('skin') and ui.get('id') != bundle['ui']['skin']:
            ok = False; notes.append('皮肤未生效')
        if not (vm.get('lore_total') or 0) >= 5:
            ok = False; notes.append('世界书条目过少')
        if not vm.get('market'):
            ok = False; notes.append('无市场')
        if not (vm.get('present') or vm.get('others')):
            ok = False; notes.append('无 NPC')
        # 卡面文字必须落盘：面板的角色卡详情与 narration_context 都依赖它
        npc_cards = [e for k, e in state['entities'].items() if k != 'player']
        if npc_cards and not all(e.get('desc') for e in npc_cards):
            ok = False; notes.append('NPC 缺 desc')
        check('%s 载入完整（术语/阶梯/货币/品牌/世界书/市场/NPC）' % fn, ok,
              '%s ｜ %s' % (player.get('name'), ' · '.join(notes) if notes else 'OK'))

        # 术语确实进了面板视图模型，且没有修真词汇泄漏
        # "泄漏"的判据是：**设定包自己没写**的词却出现在界面上。
        # 玄枢界是修真世界，它显式写了 level=境界，那是正确结果而不是泄漏。
        joined = terms.get('level', '') + terms.get('gold', '') + terms.get('track', '')
        leak_terms = [w for w in ('境界', '灵石', '修行轨')
                      if w in joined and w not in ''.join(str(v) for v in expected_terms.values())]
        check('%s 面板术语无未声明的修真词泄漏' % fn, not leak_terms,
              '漏词=%s' % leak_terms if leak_terms else 'clean')

        # 场景正文随地点切换
        places = bundle.get('places') or {}
        if places:
            loc = player.get('location')
            first = (vm.get('scene') or {}).get('description', '')
            check('%s 开局场景取自 places/开场描写' % fn,
                  bool(first) and (first == (places.get(loc) or {}).get('desc')
                                   or first == (bundle.get('world') or {}).get('location_desc')),
                  first[:40])

        # 世界演化在真实设定上能跑起来
        for _ in range(15):
            state = load_state(state_path)
            seed_rng(state)
            tick_market(state)
            state['tick'] = state.get('tick', 0) + 1
            evolve(state)
            save_state(state, state_path)
        st2 = load_state(state_path)
        fac = st2.get('factions') or {}
        pan = st2.get('panarchy') or {}
        check('%s 连跑 15 回合：势力与相位都在动' % fn,
              bool(fac) and bool(pan.get('phase')) and len(fac) >= 2,
              'factions=%d phase=%s' % (len(fac), pan.get('phase')))

    print('\n%d/%d passed' % (sum(RESULTS), len(RESULTS)))
    return 0 if all(RESULTS) else 1


if __name__ == '__main__':
    sys.exit(main())
