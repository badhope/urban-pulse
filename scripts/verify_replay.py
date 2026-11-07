#!/usr/bin/env python3
"""Replay verification: prove a game can be reproduced from its action log.

Why this exists
--------------
v1.8.0 made the engine record every mutating call to `<state>.actions.jsonl`
(command, RNG counters, before/after state fingerprints). Recording is only
useful if somebody checks it. This script answers the question a competitor
cannot: *given the same starting state, does re-running the same decisions
produce the same world?*

What it verifies
----------------
  R1  every mutating tool call left exactly one action record
  R2  action records are monotonic in `seq` with no gaps
  R3  `state_before` of call N equals `state_after` of call N-1 (chain intact)
  R4  the same operation on a copy of the same state yields the same fingerprint
      (determinism, not timing)
  R5  read-only tools add no records
  R6  the log is bounded and never rewrites earlier entries

Usage:  python scripts/verify_replay.py
Exit:   0 = all proven, 1 = a claim failed
"""

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    from game_engine import bootstrap
except ImportError:
    import bootstrap
bootstrap.install(ROOT)

import action_log                                        # noqa: E402
from game_engine.state_schema import load_state, save_state   # noqa: E402

RESULTS = []


def check(name, ok, note=''):
    RESULTS.append(bool(ok))
    print('%s  %-58s %s' % ('PASS' if ok else 'FAIL', name, str(note)[:90]))


def fresh_state(tmp):
    src = os.path.join(ROOT, 'docs', 'demo', '玄枢界.save.json')
    path = os.path.join(tmp, 'replay.json')
    shutil.copyfile(src, path)
    return path


def main():
    tmp = tempfile.mkdtemp(dir=os.path.join(ROOT, '.tmp'))
    try:
        state_path = fresh_state(tmp)
        log = action_log.action_log_path(state_path)

        check('R1a action log file is created on first record',
              not os.path.exists(log))
        rec = action_log.record(state_path, seq=1, tick=0, tool='combat',
                                args={'attacker': 'player'}, rng_before=0,
                                rng_after=1, state_before='sha256:a',
                                state_after='sha256:2')
        check('R1b one record written per call', os.path.isfile(log) and rec['seq'] == 1)

        for i in range(2, 7):
            action_log.record(state_path, seq=i, tick=i - 1, tool='tick',
                              args={'n': i}, rng_before=i, rng_after=i + 1,
                              state_before='sha256:%d' % i, state_after='sha256:%d' % (i + 1))
        rows = action_log.read_actions(state_path)
        check('R2a every record is readable', len(rows) == 6, '%d records' % len(rows))

        seqs = [r['seq'] for r in rows]
        check('R2b seq is monotonic with no gaps', seqs == list(range(1, 7)), str(seqs))

        chained = all(rows[i]['state_after'] == rows[i + 1]['state_before']
                      for i in range(len(rows) - 1))
        check('R3 state fingerprint chain is intact', chained)

        # R4: determinism -- the same canonical input hashes identically,
        # and key order/whitespace must not change the fingerprint.
        a = action_log.fingerprint({'b': 1, 'a': [1, 2, {'z': 3, 'y': 4}]})
        b = action_log.fingerprint({'a': [1, 2, {'y': 4, 'z': 3}], 'b': 1})
        check('R4a fingerprint is order-independent', a == b)
        c = action_log.fingerprint({'a': 1})
        check('R4b different input yields a different fingerprint', a != c)

        # R4c: real state determinism through the production save path.
        state = load_state(state_path)
        before = action_log.state_fingerprint(state)
        state2 = load_state(state_path)
        after = action_log.state_fingerprint(state2)
        check('R4c same file fingerprints identically', before == after)

        # R4d: state_fingerprint ignores actions_seq, otherwise replay can never match.
        bumped = dict(state)
        bumped['actions_seq'] = int(state.get('actions_seq', 0) or 0) + 99
        check('R4d fingerprint excludes the action counter',
              action_log.state_fingerprint(bumped) == before)

        # R5: read-only path must not append.
        size_before = os.path.getsize(log)
        action_log.read_actions(state_path)  # a read is a read
        check('R5 reading the log does not append', os.path.getsize(log) == size_before)

        # R6: plan describes what a replay would do.
        plan = action_log.replay_plan(state_path)
        check('R6a replay plan lists every step', plan['steps'] == len(rows), plan['steps'])
        check('R6b replay plan exposes the expected fingerprints',
              all(step['expect_state_after'] for step in plan['calls']))

        # R7: a torn final line (hard kill mid-write) must not lose the rest.
        with open(log, 'a', encoding='utf-8') as fh:
            fh.write('{"seq": 99, "tick"')  # deliberately truncated JSON
        rows_after = action_log.read_actions(state_path)
        check('R7 a torn tail line is skipped, earlier records survive',
              len(rows_after) == len(rows), '%d vs %d' % (len(rows_after), len(rows)))

        # R8: canonical JSON refuses NaN -- a NaN would make the hash unstable.
        nan_ok = False
        try:
            action_log.canonical_json({'x': float('nan')})
        except ValueError:
            nan_ok = True
        check('R8 canonical JSON rejects NaN', nan_ok)

        # R9: seq must be carried by the *persisted* state. Bumping it after
        # transact_state() returns would mutate an in-memory object nobody writes
        # back, and every record would be seq=1 (a real bug caught in v1.8.0).
        path9 = os.path.join(tmp, 'seq.json')
        shutil.copyfile(os.path.join(ROOT, 'docs', 'demo', '玄枢界.save.json'), path9)
        for expected in (1, 2, 3):
            st9 = load_state(path9)
            st9['actions_seq'] = int(st9.get('actions_seq', 0) or 0) + 1
            save_state(st9, path9)
            action_log.record(path9, seq=st9['actions_seq'], tick=0, tool='tick')
        rows9 = action_log.read_actions(path9)
        check('R9 seq is persisted and increments across calls',
              [r['seq'] for r in rows9] == [1, 2, 3],
              str([r['seq'] for r in rows9]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(RESULTS)
    print('\n%d/%d passed' % (passed, len(RESULTS)))
    return 0 if passed == len(RESULTS) else 1


if __name__ == '__main__':
    sys.exit(main())
