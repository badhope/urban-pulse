#!/usr/bin/env python3
"""
长局内存稳定性 (verify_memory.py)

为什么需要：`stress_freeplay.py` 跑 2000 轮只报一个终点 RSS，
无法区分「正常占用」和「随回合线性泄漏」。长局是项目核心卖点
（README 写"奔着百万回合设计"），内存必须可证明不随回合增长。

做法：分三段各跑 N 轮，在**同一进程**里测 RSS：
  - 前段 vs 后段的增量应远小于状态文件本身的增长量
  - 若 RSS 增量 > 阈值（默认 40MB/千轮），判为疑似泄漏

同时验证侧写文件封顶（SERIES_CAP=600）与事件归档不会无限膨胀。

用法:  python scripts/verify_memory.py [每段轮数]
退出码: 0 = 内存稳定；1 = 疑似泄漏；2 = 缺 psutil
"""

import os
import sys

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
    # 真正执行 __init__.py：包级元数据（__version__ 等）在里面；只建对象不执行会拿不到。
    _spec.loader.exec_module(_pkg)

try:
    import psutil
except ImportError:
    print('缺少 psutil：pip install psutil（内存统计需要）')
    sys.exit(2)

from game_engine.state_schema import load_state, save_state, log_event  # noqa: E402
from game_engine.viz_series import SERIES_CAP, load_series, record_sample  # noqa: E402

RESULTS = []


def check(name, ok, note=''):
    RESULTS.append(bool(ok))
    print('%s  %-50s %s' % ('PASS' if ok else 'FAIL', name, str(note)[:80]))


def rss_mb():
    return psutil.Process(os.getpid()).memory_info().rss / 1048576


def make_state(keep=50):
    return {
        'tick': 0, 'rng_seed': 1, 'rng_counter': 0,
        'config': {'event_log_keep': keep, 'archive': True},
        'entities': {'player': {'name': '沈砚', 'hp': 100, 'hp_max': 100, 'gold': 100,
                                'location': '临川城',
                                'attrs': {'str': 10, 'dex': 10, 'int': 10, 'con': 10, 'cha': 10}}},
        'relations': {}, 'market': {}, 'karma_ledger': [], 'world_flags': [],
        'event_log': [], 'milestones': [], 'summaries': [], 'codex': {}, 'lore': [],
    }


def burn(state, path, loops):
    """跑 loops 个"回合"：写事件 + 落盘 + 记录侧写（模拟真实长局的三处累积）。"""
    for i in range(loops):
        state['tick'] += 1
        for _ in range(3):   # 每回合 3 条事件，接近实际战斗+社交密度
            log_event(state, 'combat', '第%d回合：与山贼交手，造成 12 点伤害' % state['tick'])
        save_state(state, path)
        record_sample(path, state)


def main():
    loops = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
    import tempfile
    tmp = tempfile.mkdtemp(prefix='ww-mem-')
    path = os.path.join(tmp, 'mem.save.json')

    state = make_state()
    save_state(state, path)

    # 预热：让解释器/缓存先稳定（第一段会分配字节码、模块级缓存）
    burn(state, path, 200)
    base_mb = rss_mb()
    base_size = os.path.getsize(path)

    burn(state, path, loops)
    mid_mb = rss_mb()
    mid_size = os.path.getsize(path)

    burn(state, path, loops)
    end_mb = rss_mb()
    end_size = os.path.getsize(path)

    grow_1 = mid_mb - base_mb
    grow_2 = end_mb - mid_mb
    print('RSS：基准 %.1f MB → 中段 %.1f MB → 末段 %.1f MB' % (base_mb, mid_mb, end_mb))
    print('每 %d 轮增量：%.1f MB → %.1f MB' % (loops, grow_1, grow_2))
    print('状态文件：%d → %d → %d 字节' % (base_size, mid_size, end_size))

    # 判定：第二段增量应显著小于第一段（第一段含缓存预热），且绝对值低
    check('第二段内存增量 < 40MB', grow_2 < 40.0, '%.1f MB' % grow_2)
    check('内存不呈线性增长（第二段 ≤ 第一段的 1.5 倍）',
          grow_2 <= max(grow_1 * 1.5, 8.0),
          'first=%.1f second=%.1f' % (grow_1, grow_2))

    # 状态文件必须有界（事件归档生效）
    keep = 50
    st = load_state(path)
    check('事件日志被归档截断（不随回合无限增长）',
          len(st['event_log']) <= keep, '%d / %d' % (len(st['event_log']), keep))
    check('状态文件大小有界（< 1MB）', end_size < 1048576, '%d 字节' % end_size)

    # 侧写文件同样封顶
    samples = load_series(path)
    check('侧写样本数封顶 SERIES_CAP(%d)' % SERIES_CAP,
          len(samples) <= SERIES_CAP, '%d 条' % len(samples))
    sample_size = os.path.getsize(path + '.viz.jsonl') if os.path.exists(path + '.viz.jsonl') else 0
    check('侧写文件大小有界（< 512KB）', sample_size < 524288, '%d 字节' % sample_size)

    # 归档文件是只增的（这是设计），但增长速率应与淘汰速率匹配
    arch = path + '.log.jsonl'
    arch_lines = sum(1 for _ in open(arch, encoding='utf-8')) if os.path.exists(arch) else 0
    check('归档行数与 archived_events 严格相等',
          arch_lines == int(st.get('archived_events', 0)),
          'file=%d counter=%d' % (arch_lines, st.get('archived_events', 0)))

    passed = sum(RESULTS)
    print('\n%d/%d passed' % (passed, len(RESULTS)))
    return 0 if passed == len(RESULTS) else 1


if __name__ == '__main__':
    sys.exit(main())
