"""
长局态势采样 (viz_series)

把"每一回合的态势"记进一份**侧写文件** `<状态文件>.viz.jsonl`，供面板画长局曲线：
气血/内力/钱财、未清业债、人情均值、物价指数、图鉴规模、所在地。

与状态文件的关系（重要）：
- 本模块**从不写状态文件**，只读写侧写文件；面板仍严格只读（ARCHITECTURE INV-V1）。
- 引擎在每次结算落盘后记一条（mcp_server._finish），面板打开时也会兜底补记（panel.view_model）——
  两边都以 tick 去重：同 tick 覆盖、旧 tick 丢弃，所以重复调用是幂等的，
  且玩家不开面板的回合历史也不会断档（长局可视化的前提）。
"""

import json
import os
import tempfile

try:
    from game_engine import input_policy
except ImportError:  # pragma: no cover - direct source-module loading
    import input_policy

SERIES_CAP = 600
MAX_SERIES_BYTES = 4 * 1024 * 1024


def series_path(state_path):
    return state_path + ".viz.jsonl"


def _sidecar_safe(path):
    try:
        absolute = input_policy.ensure_no_links(path)
    except (OSError, ValueError):
        return False
    try:
        return os.path.getsize(absolute) <= MAX_SERIES_BYTES
    except FileNotFoundError:
        return True
    except OSError:
        return False


def _series_lock(path):
    try:
        from game_engine.state_schema import state_lock
    except ImportError:  # pragma: no cover - direct source-module loading
        from state_schema import state_lock
    return state_lock(path)


def sample_of(state):
    """从状态抽一条态势样本（纯读取；字段固定，前端图表只消费这些 key）。"""
    ents = state.get("entities") or {}
    p = ents.get("player") or {}
    market = state.get("market") or {}
    ratios = []
    for mk in market.values():
        if not isinstance(mk, dict):
            continue
        for it in mk.values():
            if not isinstance(it, dict):
                continue
            base = it.get("base_price") or it.get("price") or 0
            if base:
                ratios.append(float(it.get("price", 0)) / float(base))
    rels = state.get("relations") or {}
    affs = [float(v.get("affinity", 0)) for k, v in rels.items()
            if isinstance(v, dict) and "player" in str(k)]
    codex = state.get("codex") or {}
    codex_total = sum(len(codex.get(k) or []) for k in ("locations", "people", "items", "lore"))
    karma = sum(float(e.get("amount", 0)) for e in (state.get("karma_ledger") or [])
                if e.get("from") == "player" and not e.get("settled"))
    return {
        "tick": int(state.get("tick", 0) or 0),
        "hp": int(p.get("hp", 0) or 0),
        "hp_max": int(p.get("hp_max", 1) or 1),
        "mp": int(p.get("mp", 0) or 0),
        "mp_max": int(p.get("mp_max", 0) or 0),
        "gold": int(p.get("gold", 0) or 0),
        "karma": int(karma),
        "price_index": round(sum(ratios) / len(ratios), 4) if ratios else 1.0,
        "affinity_avg": round(sum(affs) / len(affs), 2) if affs else 0.0,
        "codex_total": int(codex_total),
        "location": str(p.get("location", "") or ""),
        # 世界侧脉搏：长局里"世界自己会动"的可视证据（相位/存量/连接度/烈度）。
        # 旧存档没有 panarchy 时给中性值，图表自动降级。
        "phase": str(((state.get("panarchy") or {}).get("phase") or "")),
        "capital": round(float(((state.get("panarchy") or {}).get("capital") or 0.0)), 4),
        "connectedness": round(float(((state.get("panarchy") or {}).get("connectedness") or 0.0)), 4),
        "intensity": round(float((state.get("panarchy") or {}).get("intensity") or 1.0), 3),
    }


def _atomic_write(path, payload):
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(prefix=".ww_viz_", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            fd = None
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if not _sidecar_safe(path):
            return False
        os.replace(tmp, path)
        tmp = None
        return True
    finally:
        if fd is not None:
            os.close(fd)
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def record_sample(state_path, state):
    """追加（或同 tick 覆盖）一条态势样本；回退/恢复到旧 tick 时丢弃，保持 tick 升序唯一。"""
    if not state_path:
        return
    try:
        s = sample_of(state)
    except Exception:  # aqg: top-level boundary —— 侧写是观测数据，异常绝不影响对局结算
        return
    path = series_path(state_path)
    try:
        from game_engine.state_schema import _recover_archive
        with _series_lock(state_path):
            _recover_archive(state_path)
            _recover_archive(path)
            if not os.path.isfile(state_path):
                return
            if not _sidecar_safe(path):
                return
            lines = []
            last = None
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        lines = f.read().splitlines()
                except UnicodeError:
                    return
                except OSError:
                    lines = []
                while lines:
                    try:
                        cand = json.loads(lines[-1])
                    except Exception:  # nosec B112; aqg: top-level boundary —— 半行/坏行丢弃，保留更早的样本
                        lines.pop()
                        continue
                    if isinstance(cand, dict):
                        last = cand
                    break
            last_tick = None
            if isinstance(last, dict):
                try:
                    last_tick = int(last.get("tick", -1))
                except (TypeError, ValueError):
                    last_tick = None
                    lines.pop() if lines else None
            if last_tick == s["tick"]:
                if last == s:
                    return
                lines[-1] = json.dumps(s, ensure_ascii=False)
            elif last_tick is not None and last_tick > s["tick"]:
                return
            else:
                lines.append(json.dumps(s, ensure_ascii=False))
            if len(lines) > SERIES_CAP:
                lines = lines[-SERIES_CAP:]
            payload = "\n".join(lines) + "\n"
            try:
                if len(payload.encode("utf-8")) > MAX_SERIES_BYTES:
                    return
            except UnicodeError:
                return
            _atomic_write(path, payload)
    except (OSError, UnicodeError, ValueError):
        return


def load_series(state_path):
    """读回样本（tick 升序、封顶 SERIES_CAP）；坏行跳过，永不抛。"""
    from game_engine.state_schema import _recover_archive
    with _series_lock(state_path):
        _recover_archive(state_path)
        _recover_archive(series_path(state_path))
        return _load_series_locked(state_path)


def _load_series_locked(state_path):
    path = series_path(state_path)
    out = []
    if state_path and os.path.exists(path) and _sidecar_safe(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        s = json.loads(line)
                    except (UnicodeError, ValueError):
                        continue
                    if isinstance(s, dict) and "tick" in s:
                        out.append(s)
        except (OSError, UnicodeError):
            pass
    out.sort(key=lambda x: int(x.get("tick", 0)))
    return out[-SERIES_CAP:]
