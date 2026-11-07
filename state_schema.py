"""
状态结构定义 (State Schema)

游戏状态是一个 JSON 对象,Agent 通过 read/write 与引擎交换。
引擎本身不持有状态——它每次调用都接收完整状态 JSON，返回更新后的完整状态 JSON。
这样 Agent 只需要在游戏开始时 load_state()，每回合通过 engine 结算后 save_state()。

状态结构:
{
  "tick": 123,                    # 回合数
  "entities": {
    "player": {
      "name": "玩家",
      "faction": "散修",
      "attrs": {"str": 12, "dex": 14, "int": 10, "con": 11, "cha": 9},
      "hp": 80, "hp_max": 80,     # 生命值
      "mp": 30, "mp_max": 30,     # 法力/内力
      "level": "练气三层",
      "gold": 500,
      "location": "bamboo_tea_booth"
    },
    "old_chen": { ... }
  },
  "relations": {
    "player:old_chen": {"affinity": 10, "respect": -5},
    ...
  },
  "market": {
    "bamboo_tea_booth": {
      "回灵丹": {"price": 50, "supply": 20, "base_price": 50},
      ...
    }
  },
  "karma_ledger": [
    {"from": "player", "to": "old_chen", "type": "赊欠", "amount": 50, "tick": 120, "settled": false}
  ],
  "world_flags": ["innkeeper_dead"],   # 触发过的世界事件
  "event_log": [...]                     # 最近 N 条事件
}
"""

import contextlib
import hashlib
import json, math, os, random, sys, time
import threading as _threading
import shutil as _shutil

try:
    from game_engine import input_policy as _input_policy
except ImportError:  # pragma: no cover - direct source-module loading
    import input_policy as _input_policy


def new_game():
    """返回一个初始状态"""
    return {
        "tick": 0,
        "entities": {},
        "relations": {},
        "market": {},
        "karma_ledger": [],
        "world_flags": [],
        "event_log": []
    }

def _require_finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("状态 JSON 不允许 NaN 或 Infinity")
    if isinstance(value, dict):
        for child in value.values():
            _require_finite(child)
    elif isinstance(value, list):
        for child in value:
            _require_finite(child)


def load_state(path):
    """从路径加载状态 JSON；拒绝非有限 JSON 数值。"""
    with state_lock(path):
        _recover_archive(path)
        return _load_state_unlocked(path)


def _load_state_unlocked(path):
    checked = _ensure_no_links(path)
    def reject_constant(value):
        raise ValueError("状态 JSON 不允许 NaN 或 Infinity")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(checked, flags)
    try:
        with os.fdopen(fd, "r", encoding="utf-8") as f:
            fd = None
            state = json.load(f, parse_constant=reject_constant)
    finally:
        if fd is not None:
            os.close(fd)
    _require_finite(state)
    return state

def _archive_file(path, state):
    """按归档世代选择归档文件：`<path>.log.jsonl` 或 `<path>.log.<gen>.jsonl`。

    为什么按世代分文件：快照回退会让状态里的 archived_events 退到旧值，而归档是
    追加写的。若强行把共享文件截断到旧计数，会把"未来分支已经写下、但仍属用户
    历史"的事件物理删除（这是不可接受的数据丢失）。按世代隔离后，回退只需切回
    该世代的文件，任何分支的归档都完整保留。
    """
    gen = int(state.get("archive_generation", 0) or 0)
    return path + ".log.jsonl" if gen == 0 else "%s.log.%d.jsonl" % (path, gen)


_STATE_TLOCK = _threading.RLock()
_STATE_LOCAL = _threading.local()


def _state_tlock():
    return _STATE_TLOCK


def _state_local():
    return _STATE_LOCAL


def _ensure_no_links(path):
    return _input_policy.ensure_no_links(path)


def _state_flock(path, timeout=10.0):
    lock_path = os.path.abspath(os.fspath(path)) + ".lock"
    directory = os.path.dirname(lock_path) or "."
    _ensure_no_links(lock_path)
    os.makedirs(directory, exist_ok=True)
    _ensure_no_links(lock_path)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(lock_path, flags, 0o600)
    handle = os.fdopen(fd, "a+b")
    deadline = time.monotonic() + float(timeout)
    try:
        if os.name == "nt":
            import msvcrt as _msvcrt
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b"0")
                handle.flush()
            while True:
                try:
                    handle.seek(0)
                    _msvcrt.locking(handle.fileno(), _msvcrt.LK_NBLCK, 1)
                    return handle
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("状态文件锁等待超时: %s" % lock_path)
                    time.sleep(0.05)
        else:
            import fcntl as _fcntl
            while True:
                try:
                    _fcntl.flock(handle.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                    return handle
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("状态文件锁等待超时: %s" % lock_path)
                    time.sleep(0.05)
    except Exception:  # aqg: top-level boundary —— 加锁失败必须关闭句柄并传播
        handle.close()
        raise


def _state_funlock(handle):
    try:
        if os.name == "nt":
            import msvcrt as _msvcrt
            handle.seek(0)
            _msvcrt.locking(handle.fileno(), _msvcrt.LK_UNLCK, 1)
        else:
            import fcntl as _fcntl
            _fcntl.flock(handle.fileno(), _fcntl.LOCK_UN)
    except OSError:  # aqg: top-level boundary —— 句柄失效时关闭即可
        pass
    finally:
        handle.close()


def _library_key(path):
    folder = os.path.dirname(os.path.abspath(os.fspath(path)))
    if os.path.normcase(os.path.basename(folder)) == os.path.normcase('.trash'):
        folder = os.path.dirname(folder)
    return os.path.normcase(os.path.join(folder, '.ww-session-library'))


@contextlib.contextmanager
def _key_lock(key, timeout=10.0):
    key = os.path.normcase(os.path.abspath(os.fspath(key)))
    local = _state_local()
    held = getattr(local, "held", None)
    if held is None:
        held = local.held = {}
    if key in held:
        held[key] += 1
        try:
            yield
        finally:
            held[key] -= 1
            if held[key] == 0:
                del held[key]
        return
    with _state_tlock():
        handle = _state_flock(key, timeout)
        held[key] = 1
        try:
            yield
        finally:
            held.pop(key, None)
            _state_funlock(handle)


@contextlib.contextmanager
def state_lock(path, timeout=10.0):
    with _key_lock(_library_key(path), timeout):
        with _key_lock(path, timeout):
            yield


def _restore_state(target, original):
    target.clear()
    target.update(original)


def _atomic_backup(path, backup_path):
    _ensure_no_links(path)
    _ensure_no_links(backup_path)
    import tempfile as _tf
    directory = os.path.dirname(os.path.abspath(backup_path)) or "."
    fd, tmp = _tf.mkstemp(prefix=".ww_backup_", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as dst:
            fd = None
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            src_fd = os.open(path, flags)
            try:
                with os.fdopen(src_fd, "rb") as src:
                    _shutil.copyfileobj(src, dst)
            finally:
                src_fd = None
            dst.flush()
            os.fsync(dst.fileno())
        _ensure_no_links(backup_path)
        os.replace(tmp, backup_path)
        tmp = None
    finally:
        if fd is not None:
            os.close(fd)
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _append_archive(path, entries):
    _ensure_no_links(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            fd = None
            for entry in entries:
                handle.write(json.dumps(entry, ensure_ascii=False, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd is not None:
            os.close(fd)


def _read_bytes(path):
    _ensure_no_links(path)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as handle:
        return handle.read()


def _archive_journal(path):
    return os.fspath(path) + ".archive-pending"


def _recover_archive(path):
    journal = _archive_journal(path)
    folder = os.path.dirname(os.path.abspath(os.fspath(path)))
    if os.path.normcase(os.path.basename(folder)) == os.path.normcase('.trash'):
        folder = os.path.dirname(folder)
    guard = os.path.join(folder, '.ww-session-transaction-pending')
    for candidate in (journal, guard):
        _ensure_no_links(candidate)
        if os.path.lexists(candidate):
            raise RuntimeError("存在未处理的归档记录，需要人工核对: %s" % candidate)


def _publish_archive_journal(path, record):
    import tempfile as _tf
    journal = _archive_journal(path)
    _ensure_no_links(journal)
    fd, tmp = _tf.mkstemp(prefix=".ww_pending_", suffix=".tmp", dir=os.path.dirname(os.path.abspath(journal)))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = None
            json.dump(record, handle)
            handle.flush()
            os.fsync(handle.fileno())
        _ensure_no_links(journal)
        os.link(tmp, journal)
    finally:
        if fd is not None:
            os.close(fd)
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _save_state_unlocked(state, path, archive_entries=None):
    _ensure_no_links(path)
    cfg = state.get("config") or {}
    keep = max(1, int(cfg.get("event_log_keep", 200)))
    log = state.get("event_log") or []
    overflow = log[:-keep] if len(log) > keep else []
    archive_path = None
    archive_existed = False
    journal = None
    entries = list(archive_entries or [])
    if overflow:
        state["event_log"] = log[-keep:]
        if cfg.get("archive", True):
            entries = overflow + entries
    if entries:
        state["archived_events"] = int(state.get("archived_events", 0) or 0) + len(entries)

    directory = os.path.dirname(os.path.abspath(path)) or "."
    import tempfile as _tf
    fd, tmp = _tf.mkstemp(prefix=".ww_state_", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline=None) as handle:
            fd = None
            json.dump(state, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        if entries:
            archive_path = _archive_file(path, state)
            _ensure_no_links(archive_path)
            existed = os.path.exists(archive_path)
            archive_existed = existed
            info = os.stat(archive_path, follow_symlinks=False) if existed else None
            if info is not None and info.st_nlink != 1:
                raise RuntimeError("归档存在多个硬链接")
            offset = info.st_size if info else 0
            appended = "".join(json.dumps(entry, ensure_ascii=False, allow_nan=False) + "\n" for entry in entries)
            appended = appended.replace("\n", os.linesep).encode("utf-8")
            record = {"generation": int(state.get("archive_generation", 0) or 0),
                      "existed": existed, "offset": offset, "length": len(appended),
                      "sha256": hashlib.sha256(appended).hexdigest(),
                      "state_before": hashlib.sha256(_read_bytes(path)).hexdigest() if os.path.exists(path) else None,
                      "state_after": hashlib.sha256(_read_bytes(tmp)).hexdigest()}
            _publish_archive_journal(path, record)
            journal = _archive_journal(path)
            _append_archive(archive_path, entries)
        if os.path.exists(path):
            backup_path = path + ".bak"
            try:
                _atomic_backup(path, backup_path)
            except _input_policy.PolicyError:
                raise
            except OSError:  # aqg: top-level boundary —— 备份失败不阻断主状态替换
                pass
        _ensure_no_links(path)
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                tmp = None
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
    except Exception:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        if journal is not None and not archive_existed and not os.path.lexists(archive_path):
            try:
                _ensure_no_links(journal)
                os.unlink(journal)
            except (OSError, _input_policy.PolicyError):
                pass
        raise
    if journal is not None:
        try:
            _ensure_no_links(journal)
            os.unlink(journal)
        except (OSError, _input_policy.PolicyError):
            pass


def save_state(state, path, allow_create=True):
    """保存状态；失败时恢复调用方对象并保留无法安全回滚的归档证据。"""
    original = json.loads(json.dumps(state, ensure_ascii=False, allow_nan=False))
    try:
        with state_lock(path):
            _recover_archive(path)
            if not allow_create and not os.path.exists(path):
                raise FileNotFoundError("状态文件不存在: %s" % path)
            _save_state_unlocked(state, path)
    except Exception:
        _restore_state(state, original)
        raise


def transact_state(edit, path, timeout=10.0, archive_entries=None, allow_create=False):
    """原子读-改-写：在同一排它锁内完成 load、edit、save。"""
    with state_lock(path, timeout):
        _recover_archive(path)
        if not os.path.exists(path) and not allow_create:
            raise FileNotFoundError("状态文件不存在: %s" % path)
        state = load_state(path) if os.path.exists(path) else new_game()
        original = json.loads(json.dumps(state, ensure_ascii=False, allow_nan=False))
        try:
            edit(state)
            _save_state_unlocked(state, path, archive_entries=archive_entries)
            return state
        except Exception:
            _restore_state(state, original)
            raise

def seed_rng(state) -> None:
    """按状态里的 rng_seed + rng_counter 重置全局随机源（带种子可复现）。

    同一 state、同一计数器、同一行动 → 同一结果；计数器随每次结算递增并落盘，
    保证同一回合内的多次行动不会复用同一段随机序列。CLI（engine.py）与
    MCP（mcp_server.py）共用本函数，两条入口的确定性语义一致。
    装有 numpy 时顺带重置其全局种子（可选，缺失则静默跳过）。
    """
    seed = state.get("rng_seed")
    if seed is None:
        return
    counter = int(state.get("rng_counter", 0)) + 1
    state["rng_counter"] = counter
    mixed = (int(seed) * 1000003 + int(state.get("tick", 0)) * 7919 + counter) % (2 ** 32)
    random.seed(mixed)
    # numpy 只在**已经被导入**时同步种子：
    #   1. 本项目宣称零第三方依赖，工具调用里裸 import numpy 会让首次结算多花数百毫秒，
    #      并在某些 Windows 子进程环境里卡住（实测 MCP stdio 服务里 status/tick 挂死）；
    #   2. 没被导入就说明这一局没有代码在用 numpy 随机源，重置它没有意义。
    np = sys.modules.get("numpy")
    if np is not None:
        np.random.seed(mixed)

def bump(state, key, n=1):
    """累加一个计数器（`state["counters"]`）。模板与成就的 counter_gte 谓词靠它。

    约定键名：
      locations / people / items / lore —— 图鉴首次收录时 +1
      clues     —— context_remember(kind="clue") 时 +1
      checks    —— 每次 roll 判定 +1
      kills     —— 每次击杀 +1
    有界：只保留整数，值封顶 1e9，键数封顶 200（超了丢最旧的）。
    """
    key = str(key or "").strip()
    if not key:
        return 0
    counters = state.setdefault("counters", {})
    if not isinstance(counters, dict):
        counters = {}
        state["counters"] = counters
    try:
        value = int(counters.get(key, 0) or 0) + max(0, int(n))
    except (TypeError, ValueError):
        value = max(0, int(n))
    counters[key] = min(10 ** 9, value)
    if len(counters) > 200:
        for old_key in list(counters)[:len(counters) - 200]:
            counters.pop(old_key, None)
    return counters[key]


def entity_key(a, b):
    """生成关系键——保证对称性，始终按字母顺序"""
    return f"{min(a,b)}:{max(a,b)}"

def get_relation(state, a, b):
    """安全获取关系，不存在返回默认值（返回副本，避免原地修改污染）"""
    key = entity_key(a, b)
    r = state.get("relations", {}).get(key, {"affinity": 0, "respect": 0})
    return dict(r)

def _clamp(value, lo=-100, hi=100):
    """将值限制在 [lo, hi] 范围内"""
    return max(lo, min(hi, value))

def set_relation(state, a, b, affinity_delta=0, respect_delta=0):
    """更新关系值 (affinity/respect clamp 到 -100~100)"""
    key = entity_key(a, b)
    if "relations" not in state:
        state["relations"] = {}
    if key not in state["relations"]:
        state["relations"][key] = {"affinity": 0, "respect": 0}
    state["relations"][key]["affinity"] = _clamp(state["relations"][key]["affinity"] + affinity_delta)
    state["relations"][key]["respect"] = _clamp(state["relations"][key]["respect"] + respect_delta)

def add_karma(state, debtor, creditor, ktype, amount):
    """添加因果债记录"""
    entry = {
        "from": debtor,
        "to": creditor,
        "type": ktype,
        "amount": amount,
        "tick": state["tick"],
        "settled": False
    }
    ledger = state.setdefault("karma_ledger", [])
    ledger.append(entry)
    cap = int((state.get("config") or {}).get("karma_ledger_keep", 500))
    _prune_settled(state, ledger, cap)
    return entry

def _prune_settled(state, ledger, cap):
    """把台账裁到保留量以内，**不丢失任何未结算债务**。

    两级策略：
      1. 先删已结算条目（不再被任何读取器使用，get_unsettled_karma 已过滤）；
      2. 仍然超额 → 把最旧的未结算条目合并成一条汇总条目（`merged` 记录条数），
         总额**逐分不变**，只丢单条明细（明细在归档与大事记里仍可回捞）。

    为什么不能直接截断：用户明确反对「按计数截断会物理删历史」
    （见 ARCHIVE_GENERATION 决策）。合并保留总额，因此业债机制与风险等级不变。
    """
    cap = max(1, int(cap))
    if len(ledger) <= cap:
        return
    settled = [i for i, e in enumerate(ledger) if e.get("settled")]
    for i in sorted(settled, reverse=True):
        if len(ledger) <= cap:
            return
        del ledger[i]
    if len(ledger) <= cap:
        return
    # 仍有超额：把所有未结算条目**按债务人分组**各合并成一条。
    # 不能直接取前 N 条合并——那会把 A/B/C 的债全挂到第一个人的头上
    # （实测 B 的 100 变成 A 的，总额守恒但归属错乱，业债/天劫按错误的人计算）。
    # 分组后条目数 = 债务人种类数，是"不丢归属"前提下的最小上界；
    # 单债务人长局（最常见）就是一条汇总，与旧行为一致。
    buckets = {}
    order = []
    for e in ledger:
        debtor = e.get("from", "")
        if debtor not in buckets:
            buckets[debtor] = []
            order.append(debtor)
        buckets[debtor].append(e)
    merged_rows = []
    for debtor in order:
        rows = buckets[debtor]
        if len(rows) == 1 and rows[0].get("type") != "merged":
            merged_rows.append(rows[0])
            continue
        merged_rows.append({
            "from": debtor,
            "to": rows[-1].get("to", ""),
            "type": "merged",
            "amount": sum(int(e.get("amount", 0) or 0) for e in rows),
            "tick": rows[0].get("tick", 0),
            "settled": False,
            "merged": sum(int(e.get("merged", 1) or 1) for e in rows),
        })
    ledger[:] = merged_rows

def get_unsettled_karma(state, entity):
    """获取某实体未偿还的因果债总额"""
    return sum(
        e["amount"] for e in state["karma_ledger"]
        if e["from"] == entity and not e["settled"]
    )

def log_event(state, etype, desc, **extra):
    """记录事件到日志。

    `extra` 是结构化附加字段（outcome / karma_type / location 等）：
    结算层与展示层读结构化字段，不再靠中文关键词反推语义。
    旧调用点不传 extra 时行为完全不变。
    """
    log = state.get("event_log")
    if not isinstance(log, list):
        log = state["event_log"] = []
    # 单调事件序号：同一 tick 内多条事件的真实先后，单靠 tick 排不出来。
    # 这是事件溯源的最小锚点——归档是按追加顺序写的，seq 让"按序重放"不依赖文件行号。
    seq = int(state.get("event_seq", 0) or 0) + 1
    state["event_seq"] = seq
    entry = {
        "seq": seq,
        "tick": state.get("tick", 0),
        "type": etype,
        "desc": desc
    }
    for k, v in extra.items():
        if v is not None:
            entry[k] = v
    log.append(entry)
    # 只追加；截断与归档统一在 save_state 里做（保证任何写入路径都不会漏归档）
