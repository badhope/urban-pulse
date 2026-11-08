"""Loop detection: notice when the game is going in circles.

Why this exists
--------------
A long AI-run game can stall without failing: the player walks between the same
two rooms, the same market prices regenerate, the same events re-log. Nothing is
"broken", so no error surfaces, but nothing progresses either. ZorkGPT solved
this with a state hash; we take the detector and leave the LLM-driven generation
behind, because our state is already deterministic and therefore comparable.

Design notes
------------
* The hash covers **play-relevant state only**: location, HP/MP, inventory,
  world flags, quest stages, market prices, unsettled karma. It deliberately
  excludes `tick`, timestamps and the action sequence — including them would make
  every hash unique and the detector useless.
* Detection is advisory, never restrictive. `tick` reports `loop_suspected` and
  suggests a change of scene; it never blocks a tool, because a legitimately
  repetitive stretch (grinding, resting) is a valid way to play.
* Bounded: the ring buffer of recent hashes is capped, so a 10 000-turn save does
  not grow a 10 000-entry list in every state file.
* Edge pruning applies to **suggestions only**: a route that failed three times
  stops being recommended, but `travel` still allows it.
"""

from __future__ import annotations

import hashlib
import json

HASH_WINDOW = 20      # how many recent hashes to remember
LOOP_THRESHOLD = 3    # same hash this many times triggers suspicion
EDGE_FAIL_LIMIT = 3   # failed traversals before an edge is hidden from suggestions


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), default=str)


def state_signature(state: dict) -> str:
    """Hash of the parts of the state a player can perceive and act on."""
    player = (state.get('entities') or {}).get('player') or {}
    summary = {
        'location': player.get('location', ''),
        'hp': player.get('hp'),
        'mp': player.get('mp'),
        'gold': player.get('gold'),
        'level': player.get('level', ''),
        'items': sorted((player.get('items') or {}).keys()),
        'flags': sorted(str(f) for f in (state.get('world_flags') or [])),
        'quests': [
            [q.get('id', ''), (q.get('stage') or {}).get('id', '')]
            for q in (state.get('questlines') or [])
        ],
        'prices': _market_prices(state),
        'karma': round(_unsettled_karma(state), 3),
    }
    return hashlib.sha256(_canonical(summary).encode('utf-8')).hexdigest()[:16]


def _market_prices(state: dict) -> list:
    rows = []
    market = state.get('market') or {}
    if isinstance(market, dict):
        for location in sorted(market.keys()):
            items = (market.get(location) or {}).get('items') or {}
            if not isinstance(items, dict):
                continue
            for key in sorted(items.keys()):
                price = (items.get(key) or {}).get('price')
                if isinstance(price, (int, float)):
                    rows.append([str(location), str(key), round(float(price), 3)])
    return rows


def _unsettled_karma(state: dict) -> float:
    total = 0.0
    for entry in state.get('karma') or []:
        if isinstance(entry, dict) and not entry.get('settled'):
            try:
                total += float(entry.get('amount') or 0)
            except (TypeError, ValueError):
                continue
    return total


def observe(state: dict) -> dict:
    """Record the current signature and report whether a loop is suspected."""
    signature = state_signature(state)
    trail = state.get('_state_hashes')
    if not isinstance(trail, list):
        trail = []
    trail.append(signature)
    if len(trail) > HASH_WINDOW:
        trail = trail[-HASH_WINDOW:]
    state['_state_hashes'] = trail

    seen = trail.count(signature)
    suspected = seen >= LOOP_THRESHOLD
    result = {
        'signature': signature,
        'seen': seen,
        'window': len(trail),
        'loop_suspected': suspected,
    }
    if suspected:
        result['hint'] = ('同一状态已出现 %d 次：位置、资源与市场都没变。'
                          '建议换场景、推进时间或触发一个未尝试的交互。' % seen)
    return result


def record_edge(state: dict, origin: str, destination: str, ok: bool) -> None:
    """Track travel outcomes so suggestions can avoid dead ends."""
    if not origin or not destination:
        return
    edges = state.get('_travel_edges')
    if not isinstance(edges, dict):
        edges = {}
    key = '%s->%s' % (origin, destination)
    entry = edges.get(key)
    if not isinstance(entry, dict):
        entry = {'ok': 0, 'fail': 0}
    if ok:
        entry['ok'] = int(entry.get('ok') or 0) + 1
    else:
        entry['fail'] = int(entry.get('fail') or 0) + 1
    edges[key] = entry
    # Keep the map bounded: on a long game a player can visit hundreds of pairs.
    if len(edges) > 200:
        ordered = sorted(edges.items(), key=lambda kv: -(kv[1].get('ok', 0) + kv[1].get('fail', 0)))
        edges = dict(ordered[:200])
    state['_travel_edges'] = edges


def pruned_edges(state: dict) -> list:
    """Edges hidden from suggestions (never forbidden)."""
    edges = state.get('_travel_edges')
    if not isinstance(edges, dict):
        return []
    return sorted(key for key, value in edges.items()
                  if isinstance(value, dict) and int(value.get('fail') or 0) >= EDGE_FAIL_LIMIT
                  and int(value.get('ok') or 0) == 0)


def summary(state: dict) -> dict:
    """Read-only view for `status` and the panel."""
    trail = state.get('_state_hashes')
    trail = trail if isinstance(trail, list) else []
    latest = trail[-1] if trail else None
    return {
        'window': len(trail),
        'repeats': trail.count(latest) if latest else 0,
        'loop_suspected': bool(latest) and trail.count(latest) >= LOOP_THRESHOLD,
        'pruned_edges': pruned_edges(state),
    }
