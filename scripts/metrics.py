#!/usr/bin/env python3
"""Metric ledger (scripts/metrics.py)

Why this exists: the project repeatedly drifted between "README says 88%" and
"the gate measured 86%". Hand-copied numbers rot. This script measures the
numbers from the source tree and writes them to `docs/metrics.json`, which is
the only place documents are allowed to quote.

Modes
  --write [--coverage N]   measure static counts, optionally record a coverage
                           percentage measured by the calling gate, write the file
  --check                  recompute static counts and fail if the ledger is stale
                           (coverage is not recomputed here; the gate records it)

Every static count is derived from the repository itself, never typed by hand:
  tools          AST count of `@server.tool` decorators in mcp_server.py
  rule_functions AST count of public top-level functions in rules/
  verify_scripts files matching scripts/verify_*.py
  gate_steps     `step "..."` lines in scripts/pre_push_gate.sh
  mutants        mutation entries registered in scripts/verify_mutation.py
  models         named closed-form models in rules/models.py
  bundles        settings/*.setting.json
  templates      templates declared in templates.py

Usage:
  python scripts/metrics.py --write --coverage 86.1
  python scripts/metrics.py --check
Exit code: 0 = ok, 1 = stale/invalid.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(ROOT, 'docs', 'metrics.json')


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding='utf-8') as fh:
        return fh.read()


def _tool_count() -> int:
    tree = ast.parse(_read('mcp_server.py'))
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            func = deco.func if isinstance(deco, ast.Call) else deco
            if (isinstance(func, ast.Attribute) and func.attr == 'tool'
                    and isinstance(func.value, ast.Name) and func.value.id == 'server'):
                names.add(node.name)
    return len(names)


def _rule_functions() -> int:
    total = 0
    rules_dir = os.path.join(ROOT, 'rules')
    for name in sorted(os.listdir(rules_dir)):
        if not name.endswith('.py'):
            continue
        tree = ast.parse(_read(os.path.join('rules', name)))
        total += sum(1 for n in tree.body
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and not n.name.startswith('_'))
    return total


def _verify_scripts() -> int:
    return len([f for f in os.listdir(os.path.join(ROOT, 'scripts'))
                if f.startswith('verify_') and f.endswith('.py')])


def _gate_steps() -> int:
    return len(re.findall(r'^\s*step\s+"', _read('scripts/pre_push_gate.sh'), re.M))


def _mutants() -> int:
    src = _read('scripts/verify_mutation.py')
    ids = set(re.findall(r"\(\s*'(M\d+)'", src))
    return len(ids)


def _models() -> int:
    tree = ast.parse(_read('rules/models.py'))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'MODELS' for t in node.targets)
                and isinstance(node.value, ast.Dict)):
            return len(node.value.keys)
    return 0


def _bundles() -> int:
    return len([f for f in os.listdir(os.path.join(ROOT, 'settings'))
                if f.endswith('.setting.json')])


def _templates() -> int:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'wg_templates_probe', os.path.join(ROOT, 'templates.py'),
        submodule_search_locations=None)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception as exc:  # a template module that cannot import is itself a defect
        print('templates.py failed to import: %s' % exc, file=sys.stderr)
        return -1
    table = getattr(module, 'TEMPLATES', None)
    return len(table) if isinstance(table, dict) else 0


def measure() -> dict:
    return {
        'tools': _tool_count(),
        'rule_functions': _rule_functions(),
        'verify_scripts': _verify_scripts(),
        'gate_steps': _gate_steps(),
        'mutants': _mutants(),
        'models': _models(),
        'bundles': _bundles(),
        'templates': _templates(),
    }


def version() -> str:
    match = re.search(r'__version__\s*=\s*"([^"]+)"', _read('__init__.py'))
    return match.group(1) if match else '0.0.0'


def load_ledger() -> dict:
    if not os.path.isfile(LEDGER):
        return {}
    with open(LEDGER, encoding='utf-8') as fh:
        return json.load(fh)


def write(coverage: float | None) -> int:
    current = measure()
    previous = load_ledger()
    payload = {
        '$comment': 'Generated by scripts/metrics.py — documents must quote these numbers, never hand-typed ones.',
        'version': version(),
        'measured_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        **current,
    }
    if coverage is not None:
        payload['coverage_pct'] = round(float(coverage), 1)
    elif 'coverage_pct' in previous:
        payload['coverage_pct'] = previous['coverage_pct']
    else:
        payload['coverage_pct'] = None
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write('\n')
    print('metrics written → docs/metrics.json')
    for key in sorted(k for k in payload if not k.startswith('$')):
        print('  %-15s %s' % (key, payload[key]))
    return 0


def check() -> int:
    ledger = load_ledger()
    if not ledger:
        print('docs/metrics.json missing — run scripts/metrics.py --write')
        return 1
    current = measure()
    stale = {k: (ledger.get(k), v) for k, v in current.items() if ledger.get(k) != v}
    if ledger.get('version') != version():
        stale['version'] = (ledger.get('version'), version())
    for key, (old, new) in sorted(stale.items()):
        print('STALE %-15s ledger=%s actual=%s' % (key, old, new))
    if stale:
        print('docs/metrics.json 已过期：运行 python scripts/metrics.py --write')
        return 1
    print('metrics ledger is current (%d keys)' % len(current))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='World Games metric ledger')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--write', action='store_true', help='measure and write docs/metrics.json')
    group.add_argument('--check', action='store_true', help='verify the ledger is current')
    parser.add_argument('--coverage', type=float, default=None,
                        help='coverage percentage measured by the calling gate')
    args = parser.parse_args(argv)
    return write(args.coverage) if args.write else check()


if __name__ == '__main__':
    sys.exit(main())
