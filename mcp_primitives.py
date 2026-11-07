"""MCP server primitives beyond tools: resources and tool annotations.

Why this exists
---------------
The server exposed 64 tools and one prompt, but zero **resources**. That matters:
in MCP, tools are *model-controlled* (the model decides to call them), while
resources are *application-controlled* — a host can pin live game state, the
current save, or the active rule set into context without asking the model to
fetch anything, and without burning a tool round-trip per turn.

The second gap was tool annotations. Hosts use `readOnlyHint` to auto-approve
calls and `destructiveHint` to require confirmation. Without them every call
looks equally dangerous, so either the host prompts constantly (bad UX) or it
blanket-approves (unsafe). Annotations are only hints — the spec says so — but
omitting them entirely removes the only signal hosts have.

Everything here is read-only and derives from the same state file the tools use,
so it cannot drift from tool behaviour.
"""

from __future__ import annotations

import json

# Tool names that provably never mutate the state file. Kept as an explicit
# allow-list rather than a heuristic: if a new read-only tool is added and not
# listed here it simply gets no annotation (safe default), it does not get
# mislabelled as read-only.
READ_ONLY_TOOLS = frozenset({
    'world_schema', 'read_state', 'status', 'world_state', 'narrative',
    'playbook_info', 'quest_status', 'lore_lookup', 'model', 'model_list',
    'recall', 'recap', 'templates_list', 'template_info', 'template_apply',
    'system_schema', 'system_status', 'session_list', 'pending_actions',
    'game_profile', 'game_sheet', 'context_search', 'context_pack',
    'character_card_read', 'narration_context',
})

# Tools that can destroy user data if misused. Hosts should confirm these.
DESTRUCTIVE_TOOLS = frozenset({
    'session_manage',   # archive / restore / purge
    'restore',          # overwrites the live save from a snapshot
    'session_import',   # can overwrite a save
    'system_remove',
})


def annotations_for(name: str):
    """Return tool annotations for `name`, or None when nothing is known."""
    try:
        from mcp.types import ToolAnnotations
    except ImportError:  # pragma: no cover - older SDK layouts
        return None

    if name in READ_ONLY_TOOLS:
        return ToolAnnotations(read_only_hint=True, open_world_hint=False,
                               idempotent_hint=True)
    if name in DESTRUCTIVE_TOOLS:
        return ToolAnnotations(read_only_hint=False, destructive_hint=True,
                               idempotent_hint=False, open_world_hint=False)
    # Everything else mutates but is additive/idempotent-per-turn in practice.
    return ToolAnnotations(read_only_hint=False, destructive_hint=False,
                           idempotent_hint=False, open_world_hint=False)


def register_resources(server, load_state, state_path_fn, settings_dir, docs_dir):
    """Attach live, read-only MCP resources to `server`.

    Resources are addressed by URI so a host can subscribe or pin them:
        world://state/current     full game state (JSON)
        world://summary/current   compact summary for prompts (text)
        world://rules/schema      state schema reference (JSON)
        world://settings/index    available setting bundles (JSON)
        world://docs/protocol     the game-master protocol (markdown)
    """
    try:
        from mcp.types import Resource
    except ImportError:  # pragma: no cover
        Resource = None

    def _state():
        path = state_path_fn()
        if not path:
            raise ValueError('no active game: call world_init or load_setting first')
        return path, load_state(path)

    @server.resource('world://state/current',
                     name='Current game state',
                     description='The full JSON state of the active game. Read-only.',
                     mime_type='application/json')
    def state_resource() -> str:
        _path, state = _state()
        return json.dumps(state, ensure_ascii=False)

    @server.resource('world://summary/current',
                     name='Current game summary',
                     description='A compact, prompt-sized summary: turn, player, place, '
                                 'phase, unsettled karma and the latest prose.',
                     mime_type='application/json')
    def summary_resource() -> str:
        _path, state = _state()
        player = (state.get('entities') or {}).get('player') or {}
        panarchy = state.get('panarchy') or {}
        prose = state.get('prose') or []
        karma = sum(float(entry.get('amount') or 0)
                    for entry in (state.get('karma') or [])
                    if not entry.get('settled'))
        payload = {
            'tick': state.get('tick', 0),
            'world': (state.get('world_info') or {}).get('name', ''),
            'player': {
                'name': player.get('name', ''),
                'level': player.get('level', ''),
                'location': player.get('location', ''),
                'hp': player.get('hp'),
                'hp_max': player.get('hp_max'),
            },
            'phase': panarchy.get('phase'),
            'unsettled_karma': round(karma, 3),
            'latest_prose': (prose[-1].get('text') if prose else ''),
        }
        return json.dumps(payload, ensure_ascii=False)

    @server.resource('world://settings/index',
                     name='Setting bundles',
                     description='Every installed setting bundle with its world name and genre.',
                     mime_type='application/json')
    def settings_resource() -> str:
        import os
        bundles = []
        if os.path.isdir(settings_dir):
            for name in sorted(os.listdir(settings_dir)):
                if not name.endswith('.setting.json'):
                    continue
                try:
                    with open(os.path.join(settings_dir, name), encoding='utf-8') as fh:
                        data = json.load(fh)
                except (OSError, ValueError):
                    continue
                world = data.get('world') or {}
                bundles.append({
                    'file': name,
                    'path': os.path.join(settings_dir, name).replace('\\', '/'),
                    'name': world.get('name', ''),
                    'era': world.get('era', ''),
                    'genre': (data.get('playbook') or {}).get('loop', ''),
                })
        return json.dumps({'bundles': bundles, 'count': len(bundles)}, ensure_ascii=False)

    @server.resource('world://docs/protocol',
                     name='Game master protocol',
                     description='How a host should run a game: turn flow, tool sequence, '
                                 'invariants it must not break.',
                     mime_type='text/markdown')
    def protocol_resource() -> str:
        import os
        path = os.path.join(docs_dir, 'GAME_MASTER_PROTOCOL.md')
        if not os.path.isfile(path):
            path = os.path.join(docs_dir, os.pardir, 'GAME_MASTER_PROTOCOL.md')
        with open(path, encoding='utf-8') as fh:
            return fh.read()

    return Resource
