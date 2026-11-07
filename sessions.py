"""
存档会话 (Sessions) —— 多局管理、快照与可持续游玩

为什么需要：原内核一次只有一个"当前对局"，切换靠 `world_open` 记路径。玩家真正需要的是
一个**游戏库**：这局跑团、那局调查、第三局经营——各自的存档、快照、进度互不干扰。

设计：
  · 所有存档集中在一个目录（默认 `<状态文件所在目录>/saves/`，可用 `WORLD_GAMES_SAVES` 覆盖）；
  · 每个存档一个 `.save.json`，索引由目录实时扫描得出（不维护易漂移的索引文件）；
  · 快照 = `<name>.<tick>.snap.json`，与存档同目录；归档/回收站 = `.trash` 子目录；
  · 删除是"移入回收站"而不是物理删除（可回滚），清空回收站才是真删；
  · 本模块只碰文件系统，不写状态内容；状态写入仍由 MCP 的 save_state 单点负责。
"""

import contextlib
import json
import os
import re
import shutil
import tempfile
import time

SAFE_NAME = re.compile(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+")
MAX_NAME = 48
KEEP_SNAPSHOTS = 20
TRASH_DIR = ".trash"


@contextlib.contextmanager
def locked_states(*paths):
    from game_engine.state_schema import state_lock, _recover_archive, _key_lock, _library_key
    with contextlib.ExitStack() as stack:
        for key in sorted({_library_key(p) for p in paths}):
            stack.enter_context(_key_lock(key))
        for path in sorted({os.path.normcase(os.path.abspath(os.fspath(p))) for p in paths}):
            stack.enter_context(state_lock(path))
        for path in paths:
            _recover_archive(path)
        yield


def saves_root(base_dir: str = "") -> str:
    """存档库根目录：环境变量优先，其次 <base_dir>/saves，最后 ./saves。"""
    env = os.environ.get("WORLD_GAMES_SAVES", "").strip()
    if env:
        return os.path.abspath(env)
    base = os.path.abspath(base_dir or os.getcwd())
    return os.path.join(base, "saves")


def safe_name(name: str) -> str:
    """把用户给的局名变成安全文件名：保留中英文数字与 -_，其余折叠为 _。"""
    text = str(name or "").strip()
    if not text:
        raise ValueError("局名不能为空")
    text = SAFE_NAME.sub("_", text).strip("._-")
    if not text:
        raise ValueError("局名里至少要有字母、数字或中文")
    return text[:MAX_NAME]


def save_path(root: str, name: str, create_dir: bool = False) -> str:
    if create_dir:
        os.makedirs(root, exist_ok=True)
    return os.path.join(root, safe_name(name) + ".save.json")


def list_saves(root: str) -> list:
    """列出存档（只读扫描，不修改任何文件）。按最后写入时间倒序。"""
    from game_engine.state_schema import _key_lock, _library_key
    if not os.path.isdir(root):
        return []
    with _key_lock(_library_key(os.path.join(root, '.ww-list'))):
        return _list_saves_locked(root)


def _list_saves_locked(root):
    if not os.path.isdir(root):
        return []
    rows = []
    for fname in os.listdir(root):
        if not fname.endswith(".save.json"):
            continue
        path = os.path.join(root, fname)
        try:
            with locked_states(path):
                st = os.stat(path)
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
        except RuntimeError:
            rows.append({"name": fname[:-len(".save.json")], "path": path,
                         "pending_review": True, "broken": False, "bytes": 0, "mtime": 0})
            continue
        except (OSError, ValueError):
            rows.append({"name": fname[:-len(".save.json")], "path": path,
                         "broken": True, "bytes": 0, "mtime": 0})
            continue
        player = (data.get("entities") or {}).get("player") or {}
        rows.append({
            "name": fname[:-len(".save.json")],
            "path": path,
            "world": str((data.get("world_info") or {}).get("name") or ""),
            "tick": int(data.get("tick", 0) or 0),
            "player": str(player.get("name") or ""),
            "kind": str((data.get("game") or {}).get("kind") or ""),
            "bytes": st.st_size,
            "mtime": int(st.st_mtime),
            "updated": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
            "broken": False,
        })
    if not rows and os.path.lexists(os.path.join(root, '.ww-session-transaction-pending')):
        rows.append({'name': '', 'path': root, 'pending_review': True,
                     'broken': False, 'bytes': 0, 'mtime': 0})
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    return rows


def snapshot(state_path: str, label: str = "") -> dict:
    """给当前存档拍快照（同 tick 只保留一份；最多 KEEP_SNAPSHOTS 份）。"""
    base = state_path[:-len(".save.json")] if state_path.endswith(".save.json") else state_path
    tag = "".join(ch for ch in str(label or "") if ch.isalnum() or ch in "-_")[:24]
    with locked_states(state_path):
        if not os.path.exists(state_path):
            raise ValueError("存档不存在: %s" % state_path)
        with open(state_path, encoding="utf-8") as f:
            tick = int(json.load(f).get("tick", 0) or 0)
        dst = "%s.%06d%s.snap.json" % (base, tick, ("-" + tag) if tag else "")
        snaps = sorted(set(_glob_snapshots(base) + [dst]))
        related = sorted({item for snap in snaps for item in _snapshot_related(snap)})
    with locked_states(state_path, *snaps, *related):
        with open(state_path, encoding="utf-8") as f:
            current_tick = int(json.load(f).get("tick", 0) or 0)
        if (current_tick != tick or sorted(set(_glob_snapshots(base) + [dst])) != snaps
                or sorted({item for snap in snaps for item in _snapshot_related(snap)}) != related):
            raise RuntimeError("快照期间存档或快照列表发生变化，请重试")
        _copy_snapshot_atomic(state_path, dst)
        for old in snaps[:-KEEP_SNAPSHOTS]:
            try:
                os.remove(old)
            except OSError:
                pass
    return {"snapshot": dst, "tick": tick, "kept": min(len(snaps), KEEP_SNAPSHOTS)}


def _copy_snapshot_atomic(src, dst):
    from game_engine.state_schema import _ensure_no_links
    _ensure_no_links(src)
    _ensure_no_links(dst)
    fd, tmp = tempfile.mkstemp(prefix='.ww_snapshot_', suffix='.tmp',
                               dir=os.path.dirname(os.path.abspath(dst)))
    try:
        os.close(fd)
        shutil.copyfile(src, tmp)
        with open(tmp, 'r+b') as handle:
            os.fsync(handle.fileno())
        _ensure_no_links(dst)
        os.replace(tmp, dst)
        tmp = None
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _glob_snapshots(base: str) -> list:
    folder = os.path.dirname(base) or "."
    prefix = os.path.basename(base) + "."
    if not os.path.isdir(folder):
        return []
    return [os.path.join(folder, f) for f in os.listdir(folder)
            if f.startswith(prefix) and f.endswith(".snap.json")]


def _snapshot_related(path):
    folder = os.path.dirname(os.path.abspath(path))
    prefix = os.path.normcase(os.path.basename(path)) + '.'
    if not os.path.isdir(folder):
        return []
    result = []
    for name in os.listdir(folder):
        normalized = os.path.normcase(name)
        if normalized.startswith(prefix) and normalized.endswith('.archive-pending'):
            result.append(os.path.join(folder, name[:-len('.archive-pending')]))
    return sorted(set(result + _associated(path)[1:]))


def list_snapshots(state_path: str) -> list:
    from game_engine.state_schema import _key_lock, _library_key
    with _key_lock(_library_key(state_path)):
        return _list_snapshots_locked(state_path)


def _list_snapshots_locked(state_path):
    base = state_path[:-len(".save.json")] if state_path.endswith(".save.json") else state_path
    rows = []
    for path in _glob_snapshots(base):
        try:
            with locked_states(state_path, path):
                st = os.stat(path)
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                tick = int(data.get("tick", 0) or 0)
        except RuntimeError:
            rows.append({"path": path, "name": os.path.basename(path), "pending_review": True,
                         "tick": 0, "updated": ""})
            continue
        except (OSError, ValueError):
            continue
        rows.append({"path": path, "name": os.path.basename(path), "tick": tick,
                     "bytes": st.st_size, "updated": time.strftime("%Y-%m-%d %H:%M",
                                                                   time.localtime(st.st_mtime))})
    if not rows:
        try:
            with locked_states(state_path):
                pass
        except RuntimeError:
            rows.append({'path': state_path, 'name': '', 'pending_review': True,
                         'tick': 0, 'updated': ''})
    rows.sort(key=lambda r: (r["tick"], r["updated"]), reverse=True)
    return rows


def _associated(path):
    folder = os.path.dirname(os.path.abspath(path))
    name = os.path.basename(path)
    stem = name[:-len('.save.json')] if name.endswith('.save.json') else name
    result = [path]
    if not os.path.isdir(folder):
        return result
    names = os.listdir(folder)
    for item in names:
        normalized = os.path.normcase(item)
        key = os.path.normcase(name)
        base = os.path.normcase(stem)
        suffix = normalized[len(key):] if normalized.startswith(key) else ''
        snap = normalized[len(base):] if normalized.startswith(base) else ''
        if (suffix in ('.bak', '.viz.jsonl', '.inbox.jsonl', '.log.jsonl')
                or re.fullmatch(r'\.log\.\d+\.jsonl', suffix)
                or re.fullmatch(r'\.snap(?:\.[\w-]+)?', suffix)
                or re.fullmatch(r'\.\d{6,}(?:-[\w-]+)?\.snap\.json', snap)):
            result.append(os.path.join(folder, item))
    snapshots = [os.path.basename(item) for item in result[1:]
                 if '.snap' in os.path.basename(item).lower()]
    for item in names:
        key = os.path.normcase(item)
        for snapshot in snapshots:
            prefix = os.path.normcase(snapshot)
            suffix = key[len(prefix):] if key.startswith(prefix) else ''
            if (suffix in ('.bak', '.viz.jsonl', '.inbox.jsonl', '.log.jsonl')
                    or re.fullmatch(r'\.log\.\d+\.jsonl', suffix)):
                result.append(os.path.join(folder, item))
                break
    return sorted(set(result), key=lambda item: (item != path, os.path.normcase(item)))


def _mapped(src, dst, path):
    if os.path.normcase(path).startswith(os.path.normcase(src)):
        return dst + path[len(src):]
    src_base = src[:-len('.save.json')]
    dst_base = dst[:-len('.save.json')]
    return dst_base + path[len(src_base):]


def _move_bundle(src, dst, operation):
    from game_engine.state_schema import _ensure_no_links, _recover_archive
    files = _associated(src)
    targets = [_mapped(src, dst, path) for path in files]
    for path in files + targets:
        _ensure_no_links(path)
        _recover_archive(path)
    for target in targets:
        if os.path.lexists(target):
            raise FileExistsError('目标已存在: %s' % target)
    if len(_associated(dst)) != 1:
        raise FileExistsError('目标存在关联文件: %s' % dst)
    record = {'operation': operation, 'source': os.path.abspath(src),
              'destination': os.path.abspath(dst),
              'files': [[os.path.abspath(a), os.path.abspath(b)] for a, b in zip(files, targets)]}
    source_dir = os.path.dirname(os.path.abspath(src))
    target_dir = os.path.dirname(os.path.abspath(dst))
    root = os.path.dirname(source_dir) if os.path.basename(source_dir) == TRASH_DIR else source_dir
    other = os.path.dirname(target_dir) if os.path.basename(target_dir) == TRASH_DIR else target_dir
    if os.path.normcase(root) != os.path.normcase(other):
        raise RuntimeError('归档源和目标不在同一存档库')
    guard = os.path.join(root, '.ww-session-transaction-pending')
    _ensure_no_links(guard)
    with open(guard, 'x', encoding='utf-8') as handle:
        json.dump(record, handle, ensure_ascii=True)
        handle.flush()
        os.fsync(handle.fileno())
    journals = [path + '.archive-pending' for path in files + targets]
    for journal in journals:
        _ensure_no_links(journal)
        with open(journal, 'x', encoding='utf-8') as handle:
            json.dump(record, handle, ensure_ascii=True)
            handle.flush()
            os.fsync(handle.fileno())
    for source, target in zip(files, targets):
        os.link(source, target)
        os.unlink(source)
    for journal in reversed(journals):
        os.unlink(journal)
    os.unlink(guard)


def archive(root: str, state_path: str) -> dict:
    """把存档移入回收站（可还原，不物理删除）。"""
    trash = os.path.join(root, TRASH_DIR)
    base_dst = os.path.join(trash, os.path.basename(state_path))
    suffix = '-%d' % time.time_ns()
    stem = os.path.basename(state_path)[:-len('.save.json')]
    dst = (os.path.join(trash, stem[:MAX_NAME - len(suffix)] + suffix + '.save.json')
           if os.path.lexists(base_dst) else base_dst)
    source_files = _associated(state_path)
    target_files = [_mapped(state_path, dst, path) for path in source_files]
    with locked_states(state_path, base_dst, dst, *source_files, *target_files):
        if _associated(state_path) != source_files:
            raise RuntimeError('归档期间关联文件发生变化，请重试')
        if not os.path.exists(state_path):
            raise ValueError("存档不存在: %s" % state_path)
        if os.path.lexists(dst):
            raise ValueError("回收站已有同名存档，不能覆盖: %s" % dst)
        os.makedirs(trash, exist_ok=True)
        _move_bundle(state_path, dst, 'archive')
    return {"archived": dst, "name": os.path.basename(dst)[:-len(".save.json")]}


def list_trash(root: str) -> list:
    from game_engine.state_schema import _key_lock, _library_key
    if not os.path.isdir(root):
        return []
    with _key_lock(_library_key(os.path.join(root, '.ww-list'))):
        return _list_trash_locked(root)


def _list_trash_locked(root):
    trash = os.path.join(root, TRASH_DIR)
    if not os.path.isdir(trash):
        if os.path.lexists(os.path.join(root, '.ww-session-transaction-pending')):
            return [{'name': '', 'path': trash, 'pending_review': True, 'updated': ''}]
        return []
    rows = []
    for fname in os.listdir(trash):
        if not fname.endswith(".save.json"):
            continue
        path = os.path.join(trash, fname)
        try:
            with locked_states(path):
                st = os.stat(path)
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
        except RuntimeError:
            rows.append({"name": fname[:-len(".save.json")], "path": path,
                         "pending_review": True, "updated": ""})
            continue
        except (OSError, ValueError):
            continue
        rows.append({"name": fname[:-len(".save.json")], "path": path,
                     "tick": int(data.get("tick", 0) or 0),
                     "updated": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))})
    if not rows and os.path.lexists(os.path.join(root, '.ww-session-transaction-pending')):
        rows.append({'name': '', 'path': trash, 'pending_review': True, 'updated': ''})
    rows.sort(key=lambda r: r["updated"], reverse=True)
    return rows


def _trash_name(name):
    if not isinstance(name, str) or not name or SAFE_NAME.search(name) or name.strip('._-') != name:
        raise ValueError('回收站标识无效')
    return name


def restore_from_trash(root: str, name: str) -> dict:
    trash = os.path.join(root, TRASH_DIR)
    name = _trash_name(name)
    src = os.path.join(trash, name + ".save.json")
    dst = os.path.join(root, name + ".save.json")
    source_files = _associated(src)
    target_files = [_mapped(src, dst, path) for path in source_files]
    with locked_states(src, dst, *source_files, *target_files):
        if _associated(src) != source_files:
            raise RuntimeError('还原期间关联文件发生变化，请重试')
        if not os.path.exists(src):
            raise ValueError("回收站里没有: %s" % name)
        os.makedirs(root, exist_ok=True)
        if os.path.lexists(dst):
            raise ValueError("同名存档已存在，不能覆盖: %s" % name)
        _move_bundle(src, dst, 'restore')
    return {"restored": dst, "name": name}


def purge_trash(root: str, name: str = "") -> dict:
    """清空回收站（危险：物理删除）。只删 .trash 目录内本程序管理的文件。"""
    trash = os.path.join(root, TRASH_DIR)
    if not os.path.isdir(trash):
        return {"removed": [], "count": 0}
    files = [fname for fname in os.listdir(trash)
             if fname.endswith(".save.json")
             and (not name or fname == _trash_name(name) + ".save.json")]
    removed = []
    results = []
    bundles = {fname: _associated(os.path.join(trash, fname)) for fname in files}
    with locked_states(*(item for bundle in bundles.values() for item in bundle)):
        for fname in files:
            path = os.path.join(trash, fname)
            bundle = bundles[fname]
            if _associated(path) != bundle:
                raise RuntimeError('删除期间关联文件发生变化，请重试')
            from game_engine.state_schema import _ensure_no_links, _recover_archive
            for item in bundle:
                _ensure_no_links(item)
                _recover_archive(item)
            journals = [item + '.archive-pending' for item in bundle]
            for journal in journals:
                with open(journal, 'x', encoding='utf-8') as handle:
                    json.dump({'operation': 'purge', 'files': bundle}, handle)
                    handle.flush()
                    os.fsync(handle.fileno())
            failed = False
            for item in reversed(bundle):
                try:
                    os.unlink(item)
                    results.append({'path': item, 'removed': True})
                except OSError as exc:
                    results.append({'path': item, 'removed': False, 'error': str(exc)})
                    failed = True
                    break
            if not failed:
                for journal in reversed(journals):
                    os.unlink(journal)
                removed.append(fname)
    return {"removed": removed, "count": len(removed), "files": results, "irreversible": True}
