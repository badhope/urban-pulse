import json
import math
import os
import re


class PolicyError(ValueError):
    pass


MAX_PATH_CHARS = 512
MAX_PATH_SEGMENTS = 32
MAX_SEGMENT_CHARS = 128
MAX_DEPTH = 32
MAX_NODES = 100000
MAX_STRING_CHARS = 1_000_000
MAX_NUMBER_DIGITS = 128
MAX_ABS_NUMBER = 10 ** 100
MAX_ENTITIES = 5000
MAX_COLLECTION = 20000
STATE_ROOT_ENV = "WORLD_GAMES_STATE_ROOT"
_SNAPSHOT_NAME = re.compile(r"^[^/\\]+\.snap\.[0-9A-Za-z_\-\u4e00-\u9fff]+$")
_SESSION_SNAPSHOT_NAME = re.compile(
    r"^[^/\\]+\.[0-9]{6}(?:-[0-9A-Za-z_\-\u4e00-\u9fff]+)?\.snap\.json$")
MAX_BYTES = {
    "state": 32 * 1024 * 1024,
    "setting": 8 * 1024 * 1024,
    "card": 16 * 1024 * 1024,
    "lore": 8 * 1024 * 1024,
}

_WINDOWS_ABS = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|\\\\)[^\s\"'<>|]+")
_POSIX_ABS = re.compile(r"(?<![A-Za-z0-9])/(?:[^\s\"'<>|]+)")


def _reject(message="输入不符合安全策略"):
    raise PolicyError(message)


def redact_message(message):
    text = str(message or "")
    text = _WINDOWS_ABS.sub("<path>", text)
    return _POSIX_ABS.sub("<path>", text)


def _as_path(value):
    try:
        path = os.fspath(value)
    except TypeError:
        _reject()
    if isinstance(path, bytes):
        try:
            path = os.fsdecode(path)
        except UnicodeDecodeError:
            _reject()
    if not isinstance(path, str) or not path or len(path) > MAX_PATH_CHARS:
        _reject()
    if "\x00" in path:
        _reject()
    return path


def _check_segments(path):
    normalized = path.replace("\\", "/")
    drive = re.match(r"^[A-Za-z]:", normalized)
    tail = normalized[2:] if drive else normalized
    segments = [part for part in tail.split("/") if part]
    if len(segments) > MAX_PATH_SEGMENTS:
        _reject()
    for segment in segments:
        if len(segment) > MAX_SEGMENT_CHARS or segment == "..":
            _reject()
        if any(ord(char) < 32 for char in segment):
            _reject()
    return segments


def _is_reparse_point(path):
    checker = getattr(os.path, "isjunction", None)
    if checker is not None:
        try:
            if checker(path):
                return True
        except OSError:
            return True
    if os.name != "nt":
        return False
    try:
        attrs = getattr(os.stat(path, follow_symlinks=False), "st_file_attributes", 0)
    except OSError:
        attrs = 0
    if attrs & 0x0400:
        return True
    try:
        import ctypes
        from ctypes import wintypes
        get_attrs = ctypes.windll.kernel32.GetFileAttributesW
        get_attrs.argtypes = [wintypes.LPCWSTR]
        get_attrs.restype = wintypes.DWORD
        attrs = get_attrs(path)
    except (AttributeError, OSError, TypeError):
        return False
    return attrs != 0xFFFFFFFF and bool(attrs & 0x0400)


def _check_symlinks(path):
    absolute = os.path.abspath(path)
    drive, tail = os.path.splitdrive(absolute)
    current = drive + os.sep if drive else os.sep
    for segment in [part for part in tail.split(os.sep) if part]:
        current = os.path.join(current, segment)
        if os.path.lexists(current) and (os.path.islink(current) or _is_reparse_point(current)):
            _reject()


def ensure_no_links(value):
    path = _as_path(value)
    absolute = os.path.abspath(path)
    _check_symlinks(absolute)
    return absolute


def _configured_state_root(root=None):
    configured = root if root is not None else os.environ.get(STATE_ROOT_ENV, "")
    return configured or os.getcwd()


def _root_path(root):
    checked = _as_path(root)
    _check_segments(checked)
    resolved = os.path.abspath(checked)
    _check_symlinks(resolved)
    if os.path.exists(resolved) and not os.path.isdir(resolved):
        _reject("状态根不是目录")
    return os.path.realpath(resolved)


def _under_root(path, root):
    path_real = os.path.realpath(os.path.abspath(path))
    root_real = os.path.realpath(os.path.abspath(root))
    try:
        common = os.path.commonpath((path_real, root_real))
    except ValueError as exc:
        raise PolicyError("路径不在允许根目录内") from exc
    if os.path.normcase(common) != os.path.normcase(root_real):
        _reject("路径不在允许根目录内")


def validate_root(value):
    return _root_path(value)


def validate_path(value, extensions=(".json",), must_exist=True, root=None):
    raw = _as_path(value)
    _check_segments(raw)
    base = _root_path(root) if root is not None else None
    path = os.path.join(base, raw) if base and not os.path.isabs(raw) else raw
    lowered = path.lower()
    allowed = tuple(str(ext).lower() for ext in extensions)
    if allowed and not any(lowered.endswith(ext) for ext in allowed):
        _reject()
    absolute = os.path.abspath(path)
    if base:
        _under_root(absolute, base)
    _check_symlinks(absolute)
    exists = os.path.exists(absolute)
    if must_exist and not exists:
        _reject("输入文件不存在或不可读")
    if exists and not os.path.isfile(absolute):
        _reject("输入文件不是普通文件")
    return absolute


def validate_state_path(value, must_exist=True, root=None):
    return validate_path(value, (".json",), must_exist=must_exist,
                         root=_configured_state_root(root))


def validate_snapshot_path(value, root=None, state_path=None, must_exist=True):
    base = _configured_state_root(root)
    checked = validate_path(value, (), must_exist=must_exist, root=base)
    name = os.path.basename(checked)
    if not (_SNAPSHOT_NAME.fullmatch(name) or _SESSION_SNAPSHOT_NAME.fullmatch(name)):
        _reject("快照路径非法")
    if state_path is not None:
        state = validate_state_path(state_path, must_exist=False, root=base)
        if os.path.dirname(checked) != os.path.dirname(state):
            _reject("快照必须位于当前状态目录")
        direct_prefix = os.path.basename(state) + ".snap"
        session_base = os.path.basename(state)
        if session_base.endswith(".save.json"):
            session_base = session_base[:-len(".save.json")]
        if not (name.startswith(direct_prefix)
                or (name.startswith(session_base + ".")
                    and _SESSION_SNAPSHOT_NAME.fullmatch(name))):
            _reject("快照不是当前状态生成的快照")
    return checked


def validate_setting_path(value, package_root=""):
    raw = validate_path(value, (".json",), must_exist=False)
    if os.path.isfile(raw):
        return raw
    if os.path.isabs(os.fspath(value)):
        _reject("设定包不存在或不可读")
    if package_root:
        bundled = validate_path(os.path.join(package_root, os.fspath(value)),
                                (".json",), must_exist=True)
        return bundled
    _reject("设定包不存在或不可读")


def _read_bytes(path, kind, extensions=(".json",), root=None):
    checked = validate_path(path, extensions, must_exist=True, root=root)
    limit = int(MAX_BYTES.get(kind, MAX_BYTES["state"]))
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = None
    try:
        fd = os.open(checked, flags)
        with os.fdopen(fd, "rb") as handle:
            fd = None
            size = os.fstat(handle.fileno()).st_size
            if size > limit:
                _reject("输入文件超过大小限制")
            data = handle.read(limit + 1)
    except PolicyError:
        raise
    except (OSError, UnicodeError) as exc:
        raise PolicyError("输入文件不可读") from exc
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
    if len(data) > limit:
        _reject("输入文件超过大小限制")
    return data


def _parse_int(raw):
    if len(raw.lstrip("+-")) > MAX_NUMBER_DIGITS:
        _reject("JSON 数值超过限制")
    try:
        value = int(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise PolicyError("JSON 数值非法") from exc
    if abs(value) > MAX_ABS_NUMBER:
        _reject("JSON 数值超过限制")
    return value


def _parse_float(raw):
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise PolicyError("JSON 数值非法") from exc
    if not math.isfinite(value) or abs(value) > MAX_ABS_NUMBER:
        _reject("JSON 只允许有限数值")
    return value


def _reject_constant(_value):
    _reject("JSON 只允许有限数值")


def _walk(value, depth=0, seen=None):
    if seen is None:
        seen = [0]
    seen[0] += 1
    if seen[0] > MAX_NODES or depth > MAX_DEPTH:
        _reject("JSON 结构超过限制")
    if isinstance(value, str):
        if len(value) > MAX_STRING_CHARS:
            _reject("JSON 字符串超过限制")
    elif isinstance(value, float):
        if not math.isfinite(value) or abs(value) > MAX_ABS_NUMBER:
            _reject("JSON 只允许有限数值")
    elif isinstance(value, int) and abs(value) > MAX_ABS_NUMBER:
        _reject("JSON 数值超过限制")
    elif isinstance(value, dict):
        if len(value) > MAX_COLLECTION:
            _reject("JSON 对象超过限制")
        for key, child in value.items():
            if not isinstance(key, str) or len(key) > MAX_STRING_CHARS:
                _reject("JSON 键非法")
            _walk(child, depth + 1, seen)
    elif isinstance(value, list):
        if len(value) > MAX_COLLECTION:
            _reject("JSON 数组超过限制")
        for child in value:
            _walk(child, depth + 1, seen)


def read_bounded_file(path, kind="state", extensions=(".json",)):
    return _read_bytes(path, kind, extensions=extensions)


def load_json(path, kind="state"):
    data = _read_bytes(path, kind, extensions=(".json",))
    try:
        text = data.decode("utf-8")
        value = json.loads(text, parse_constant=_reject_constant,
                           parse_int=_parse_int, parse_float=_parse_float)
    except PolicyError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, OverflowError) as exc:
        raise PolicyError("JSON 输入非法") from exc
    _walk(value)
    return value


def validate_state_data(value):
    _walk(value)
    if not isinstance(value, dict):
        _reject("状态必须是对象")
    entities = value.get("entities")
    if not isinstance(entities, dict) or len(entities) > MAX_ENTITIES:
        _reject("状态缺少合法 entities")
    for entity_id, entity in entities.items():
        if not isinstance(entity_id, str) or not entity_id or len(entity_id) > MAX_SEGMENT_CHARS:
            _reject("状态实体标识非法")
        if not isinstance(entity, dict):
            _reject("状态实体非法")
        if "name" in entity and not isinstance(entity["name"], str):
            _reject("状态实体名称非法")
    return value


def _load_json_bytes(path, kind, extensions, root=None):
    data = _read_bytes(path, kind, extensions=extensions, root=root)
    try:
        text = data.decode("utf-8")
        value = json.loads(text, parse_constant=_reject_constant,
                           parse_int=_parse_int, parse_float=_parse_float)
    except PolicyError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, OverflowError) as exc:
        raise PolicyError("JSON 输入非法") from exc
    _walk(value)
    return value


def load_state(path, root=None):
    from game_engine.state_schema import state_lock, _recover_archive
    checked = validate_state_path(path, root=root)
    with state_lock(checked):
        _recover_archive(checked)
        return validate_state_data(_load_json_bytes(checked, "state", (".json",), root=root))


def load_snapshot(path, root=None, state_path=None):
    from game_engine.sessions import locked_states
    checked = validate_snapshot_path(path, root=root, state_path=state_path)
    paths = (checked, state_path) if state_path else (checked,)
    with locked_states(*paths):
        return validate_state_data(_load_json_bytes(checked, "state", (), root=root))


def validate_setting_data(value):
    _walk(value)
    if not isinstance(value, dict):
        _reject("设定包必须是对象")
    world = value.get("world")
    player = value.get("player")
    if not isinstance(world, dict) or not isinstance(world.get("name"), str) or not world["name"]:
        _reject("设定包缺少合法 world")
    if not isinstance(player, dict) or not isinstance(player.get("name"), str) or not player["name"]:
        _reject("设定包缺少合法 player")
    for key in ("entities", "market", "relations", "world_flags", "lore"):
        if key in value and not isinstance(value[key], (list, dict)):
            _reject("设定包字段类型非法")
    if isinstance(value.get("entities"), list) and len(value["entities"]) > MAX_COLLECTION:
        _reject("设定包集合超过限制")
    return value


def load_setting(path, package_root=""):
    resolved = validate_setting_path(path, package_root=package_root)
    return validate_setting_data(load_json(resolved, "setting"))


def _card_data(value):
    if not isinstance(value, dict):
        _reject("角色卡必须是对象")
    data = value.get("data") if isinstance(value.get("data"), dict) else value
    if not isinstance(data, dict) or not isinstance(data.get("name"), str) or not data["name"]:
        _reject("角色卡缺少合法 name")
    for key in ("description", "personality", "scenario", "first_mes", "mes_example"):
        if key in data and not isinstance(data[key], str):
            _reject("角色卡文本字段非法")
    book = (data.get("character_book") or {}).get("entries") if isinstance(data.get("character_book"), dict) else None
    if book is not None and not isinstance(book, (list, dict)):
        _reject("角色卡世界书字段非法")
    return value


def validate_card_data(value):
    return _card_data(value)


def validate_card_path(value):
    return validate_path(value, (".json", ".png"), must_exist=True)


def load_card(path):
    checked = validate_card_path(path)
    if not checked.lower().endswith(".json"):
        _reject("PNG 角色卡需由角色卡解析器读取")
    return validate_card_data(load_json(checked, "card"))


def _lore_entries(value):
    data = value
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    if isinstance(data, dict) and isinstance(data.get("character_book"), dict):
        entries = data["character_book"].get("entries")
    elif isinstance(data, dict):
        entries = data.get("entries")
    elif isinstance(data, list):
        entries = data
    else:
        entries = None
    if isinstance(entries, dict):
        entries = list(entries.values())
    if not isinstance(entries, list) or len(entries) > MAX_COLLECTION:
        _reject("世界书缺少合法 entries")
    for entry in entries:
        if not isinstance(entry, dict):
            _reject("世界书条目非法")
        keys = entry.get("keys", entry.get("key"))
        content = entry.get("content")
        if not isinstance(content, str) or not content.strip():
            _reject("世界书条目缺少 content")
        if not isinstance(keys, (str, list)) or not keys:
            _reject("世界书条目缺少 keys")
    return entries


def validate_lore_data(value):
    _walk(value)
    _lore_entries(value)
    return value


def load_lore(path):
    checked = validate_path(path, (".json",), must_exist=True)
    return validate_lore_data(load_json(checked, "lore"))
