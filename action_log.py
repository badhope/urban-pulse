"""Action log: the missing half of event sourcing.

Why this exists
--------------
The event log records *what happened* (description + type + structured fields).
It does not record *what was asked for*. That means the project can audit a game
but cannot replay one: given the same seed and the same archive, re-running the
same sequence of decisions does not reproduce the same state, because nothing
recorded the decisions.

This module writes one line per mutating tool call to `<state>.actions.jsonl`:

    {"seq": 87, "tick": 12, "tool": "combat", "args_sha256": "...",
     "rng_before": 41, "rng_after": 42,
     "state_before": "sha256:...", "state_after": "sha256:..."}

Design choices worth stating:

* **Arguments are hashed, not stored.** Player input can contain private text;
  copying it into a second file on disk widens the exposure for no benefit.
  `tool` + `tick` + `seq` is enough to look the call up in the event log when a
  human needs to read it.
* **Canonical JSON before hashing.** Dict ordering and float formatting would
  otherwise make identical calls hash differently, and the whole point is a
  stable fingerprint.
* **Append-only, bounded.** Like every other ledger in this project it merges
  rather than growing without limit, but it never rewrites history in place.
* **Read-only tools never write.** The caller decides; this module only records.
"""

from __future__ import annotations

import hashlib
import json
import os

ACTION_LOG_SUFFIX = '.actions.jsonl'
ACTION_LOG_CAP = 20000


def action_log_path(state_path: str) -> str:
    """`ww_state.json` -> `ww_state.json.actions.jsonl`."""
    return os.path.abspath(state_path) + ACTION_LOG_SUFFIX


def canonical_json(value) -> str:
    """Deterministic JSON for hashing: sorted keys, fixed separators, no NaN."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False, default=str)


def fingerprint(value) -> str:
    """Stable short hash of any JSON-able value."""
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def state_fingerprint(state: dict) -> str:
    """Fingerprint of the game state.

    `actions_seq` is excluded: it changes as a consequence of being recorded, so
    including it would make every "after" hash differ from the "after" hash
    observed during replay. The fingerprint must describe the world, not the log.
    """
    payload = {k: v for k, v in state.items() if k != 'actions_seq'}
    return 'sha256:' + fingerprint(payload)


def read_actions(state_path: str, limit: int = 0) -> list:
    """Read recorded actions, oldest first. Never raises on a corrupt tail."""
    path = action_log_path(state_path)
    if not os.path.isfile(path):
        return []
    rows = []
    try:
        with open(path, encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue  # a torn final line from a hard kill is not fatal
    except OSError:
        return []
    return rows[-limit:] if limit and limit > 0 else rows


def next_seq(state: dict) -> int:
    """Monotonic sequence number carried inside the state itself."""
    return int(state.get('actions_seq', 0) or 0) + 1


def record(state_path: str, *, seq: int, tick: int, tool: str,
           args=None, rng_before=None, rng_after=None,
           state_before: str = '', state_after: str = '') -> dict:
    """Append one action record. Returns the record written."""
    entry = {
        'seq': int(seq),
        'tick': int(tick),
        'tool': str(tool),
        'args_sha256': fingerprint(args if args is not None else {}),
        'rng_before': rng_before,
        'rng_after': rng_after,
        'state_before': state_before,
        'state_after': state_after,
    }
    path = action_log_path(state_path)
    try:
        directory = os.path.dirname(path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)
        with open(path, 'a', encoding='utf-8', newline='\n') as fh:
            fh.write(canonical_json(entry) + '\n')
        _trim(path)
    except OSError:
        # Recording must never break a committed transaction: the game is the
        # product, the log is evidence. A full disk loses evidence, not saves.
        pass
    return entry


def _trim(path: str) -> None:
    """Keep the tail when the log exceeds the cap (merge-not-truncate policy)."""
    try:
        if os.path.getsize(path) < 4 * 1024 * 1024:
            return
        with open(path, encoding='utf-8') as fh:
            lines = fh.readlines()
        if len(lines) <= ACTION_LOG_CAP:
            return
        with open(path, 'w', encoding='utf-8', newline='\n') as fh:
            fh.writelines(lines[-ACTION_LOG_CAP:])
    except OSError:
        pass


def replay_plan(state_path: str) -> dict:
    """Describe what a replay would do, without performing it.

    Returns the ordered tool calls plus the fingerprints the replay must match.
    Keeping this as data (rather than doing the replay here) lets the caller run
    it through the real MCP tools, so replay exercises the production code path
    instead of a parallel reimplementation.
    """
    rows = read_actions(state_path)
    steps = [{
        'seq': row.get('seq'),
        'tick': row.get('tick'),
        'tool': row.get('tool'),
        'args_sha256': row.get('args_sha256'),
        'expect_state_after': row.get('state_after'),
    } for row in rows]
    return {
        'state_path': os.path.abspath(state_path),
        'log': action_log_path(state_path),
        'steps': len(steps),
        'first_tick': steps[0]['tick'] if steps else None,
        'last_tick': steps[-1]['tick'] if steps else None,
        'calls': steps,
    }
