"""Publish a local commit to GitHub mirrors through the REST API.

Why the API instead of `git push`: on some networks github.com's git endpoint
fails TLS handshakes while api.github.com responds normally. The Git Data API
can reconstruct the same commit graph (blobs -> trees -> commit) and move a ref,
which is exactly what a push does, over a transport that works.

Why this lives in scripts/ and not a scratch file: mirror synchronisation is a
recurring maintenance operation, so it belongs in the repository with the rest
of the release tooling rather than being retyped each time.

Order matters: blobs must exist before a tree can reference them, and trees must
exist before the commit can reference the root tree.

Usage:
    python scripts/publish_github.py <account-key> <owner/repo> [--ref main] [--local main]

Credentials are read from the local credential store (never printed, never
passed on a command line). Set WG_DRY_RUN=1 to print the plan without writing.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

API = 'https://api.github.com'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.expanduser('~/.agent-secrets/accounts.json')


def token(account: str) -> str:
    with open(STORE, encoding='utf-8') as fh:
        data = json.load(fh)
    return data['platforms']['github']['accounts'][account]['token']


def call(tok: str, method: str, path: str, payload=None, attempts: int = 4):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {
        'Authorization': 'Bearer %s' % tok,
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'world-games-release',
    }
    if data is not None:
        headers['Content-Type'] = 'application/json'
    last = None
    for attempt in range(attempts):
        req = urllib.request.Request(API + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                body = resp.read().decode('utf-8')
                return resp.status, (json.loads(body) if body.strip() else {})
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode('utf-8') or '{}')
            except Exception:
                detail = {}
            return exc.code, detail
        except Exception as exc:
            last = '%s: %s' % (type(exc).__name__, str(exc)[:120])
            time.sleep(1.5 * (attempt + 1))
    raise SystemExit('API %s %s failed after %d attempts (%s)' % (method, path, attempts, last))


def git(*args) -> str:
    out = subprocess.run(['git'] + list(args), cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit('git %s failed: %s' % (' '.join(args), out.stderr[:300]))
    return out.stdout.strip()


def read_entries(commit: str) -> list:
    raw = subprocess.run(['git', 'ls-tree', '-r', '-z', commit], cwd=ROOT,
                         capture_output=True).stdout
    entries = []
    for chunk in raw.split(b'\0'):
        if not chunk:
            continue
        meta, path = chunk.split(b'\t', 1)
        mode, kind, sha = meta.split(b' ')
        if kind.decode() != 'blob':
            continue
        entries.append((mode.decode(), sha.decode(), path.decode('utf-8')))
    return entries


def existing_blobs(tok: str, repo: str, ref: str = 'main') -> set:
    """Blob SHAs already reachable from the remote ref.

    Why: a re-publish after a single failed upload re-sends ~160 unchanged blobs,
    which takes ten minutes and re-trips whatever limit caused the failure. Git
    addresses blobs by content hash, so an unchanged file's blob is *already the
    same object* — skip it and only upload what actually differs.

    Falls back to an empty set when the ref does not exist yet (first publish).
    """
    status, ref_info = call(tok, 'GET', '/repos/%s/git/ref/heads/%s' % (repo, ref))
    if status != 200:
        return set()
    status, tree = call(tok, 'GET', '/repos/%s/git/trees/%s?recursive=1'
                        % (repo, ref_info['object']['sha']))
    if status != 200:
        return set()
    return {entry['sha'] for entry in tree.get('tree', []) if entry.get('type') == 'blob'}


def upload_blobs(tok: str, repo: str, entries: list) -> None:
    uploaded = 0
    skipped = 0
    present = existing_blobs(tok, repo)
    for mode, sha, path in entries:
        if sha in present:
            skipped += 1
            continue
        blob = subprocess.run(['git', 'cat-file', 'blob', sha], cwd=ROOT,
                              capture_output=True).stdout
        payload = {'content': base64.b64encode(blob).decode(), 'encoding': 'base64'}
        body = None
        for attempt in range(5):
            req = urllib.request.Request(
                API + '/repos/%s/git/blobs' % repo,
                data=json.dumps(payload).encode(), method='POST',
                headers={'Authorization': 'Bearer %s' % tok,
                         'Accept': 'application/vnd.github+json',
                         'Content-Type': 'application/json',
                         'Connection': 'close',
                         'User-Agent': 'world-games-release'})
            try:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    body = json.loads(resp.read().decode('utf-8'))
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode('utf-8')[:200]
                # 401 on a large blob here is secondary-rate-limit, not a bad
                # token (the same token just authenticated): GitHub throttles
                # large writes per account. Back off and retry rather than
                # reporting an auth failure that sends the operator chasing a
                # credential problem that does not exist.
                if exc.code in (400, 401, 422) and attempt < 4:
                    time.sleep(3.0 * (attempt + 1))
                    continue
                raise SystemExit('blob %s (%s) failed: %s %s' % (sha[:8], path, exc.code, detail))
            except Exception:
                if attempt < 4:
                    time.sleep(1.0 + attempt)
                    continue
                raise SystemExit('blob %s (%s) network failure' % (sha[:8], path))
        if not body or body.get('sha') != sha:
            raise SystemExit('blob %s rehashed to %s' % (sha[:8], (body or {}).get('sha')))
        uploaded += 1
    print('blobs uploaded: %d (skipped %d already on remote)' % (uploaded, skipped))


def build_trees(tok: str, repo: str, entries: list) -> str:
    by_dir = defaultdict(list)
    for mode, sha, path in entries:
        directory, _, name = path.rpartition('/')
        by_dir[directory].append((mode, sha, name))

    created = {}

    def build(directory: str) -> str:
        if directory in created:
            return created[directory]
        items = [{'path': name, 'mode': mode, 'type': 'blob', 'sha': sha}
                 for mode, sha, name in by_dir.get(directory, [])]
        prefix = directory + '/' if directory else ''
        children = sorted({d[len(prefix):].split('/')[0] for d in by_dir
                           if d.startswith(prefix) and d != directory and d[len(prefix):]})
        for child in children:
            items.append({'path': child, 'mode': '040000', 'type': 'tree',
                          'sha': build(prefix + child)})
        status, body = call(tok, 'POST', '/repos/%s/git/trees' % repo, {'tree': items})
        if status not in (200, 201):
            raise SystemExit('create tree %r failed: %s %s' % (directory, status, body))
        created[directory] = body['sha']
        return body['sha']

    return build('')


def main() -> int:
    if len(sys.argv) < 3:
        raise SystemExit('usage: publish_github.py <account> <owner/repo> '
                         '[--ref main] [--local main]')
    account, repo = sys.argv[1], sys.argv[2]
    ref, local = 'main', 'main'
    args = sys.argv[3:]
    for i, arg in enumerate(args):
        if arg == '--ref':
            ref = args[i + 1]
        elif arg == '--local':
            local = args[i + 1]

    tok = token(account)
    commit = git('rev-parse', local)
    message = git('log', '-1', '--format=%B', commit)
    author_name = git('log', '-1', '--format=%an', commit)
    author_email = git('log', '-1', '--format=%ae', commit)
    when = git('log', '-1', '--format=%aI', commit)

    # Only keep parents the remote can resolve: a force-push that replaces
    # unrelated history must not claim a parent it does not have.
    parents = []
    for parent in git('rev-list', '--parents', '-n', '1', commit).split()[1:]:
        status, _ = call(tok, 'GET', '/repos/%s/git/commits/%s' % (repo, parent))
        if status == 200:
            parents.append(parent)
        else:
            print('dropping parent %s (absent on remote)' % parent[:10])

    print('account=%s repo=%s commit=%s parents=%s'
          % (account, repo, commit[:10], [p[:10] for p in parents]))

    status, me = call(tok, 'GET', '/user')
    print('auth user:', me.get('login'), 'status', status)
    if status != 200:
        raise SystemExit('token rejected: %s' % me.get('message'))

    status, info = call(tok, 'GET', '/repos/%s' % repo)
    print('repo:', info.get('full_name'), 'default=%s' % info.get('default_branch'),
          'status', status)
    if status != 200:
        raise SystemExit('cannot access repo: %s' % info.get('message'))

    entries = read_entries(commit)
    print('files:', len(entries))
    if os.environ.get('WG_DRY_RUN') == '1':
        print('dry run: blobs -> trees -> commit -> refs/heads/%s' % ref)
        return 0

    upload_blobs(tok, repo, entries)
    root_tree = build_trees(tok, repo, entries)
    print('root tree:', root_tree[:12])

    status, check = call(tok, 'GET', '/repos/%s/git/trees/%s?recursive=1' % (repo, root_tree))
    remote_paths = {e['path'] for e in check.get('tree', []) if e['type'] == 'blob'}
    local_paths = {p for _, _, p in entries}
    if remote_paths != local_paths:
        raise SystemExit('tree mismatch: missing=%s extra=%s'
                         % (sorted(local_paths - remote_paths)[:5],
                            sorted(remote_paths - local_paths)[:5]))
    print('tree verified: %d blobs' % len(remote_paths))

    status, body = call(tok, 'POST', '/repos/%s/git/commits' % repo, {
        'message': message,
        'tree': root_tree,
        'parents': parents,
        'author': {'name': author_name, 'email': author_email, 'date': when},
        'committer': {'name': author_name, 'email': author_email, 'date': when},
    })
    if status not in (200, 201):
        raise SystemExit('create commit failed: %s %s' % (status, body))
    new_commit = body['sha']
    print('commit:', new_commit[:12], '(local %s)' % commit[:12])

    status, body = call(tok, 'PATCH', '/repos/%s/git/refs/heads/%s' % (repo, ref),
                        {'sha': new_commit, 'force': True})
    if status not in (200, 201):
        raise SystemExit('update ref failed: %s %s' % (status, body))
    print('ref refs/heads/%s -> %s' % (ref, new_commit[:12]))

    status, refinfo = call(tok, 'GET', '/repos/%s/git/ref/heads/%s' % (repo, ref))
    print('verified:', (refinfo.get('object') or {}).get('sha', '?')[:12])
    return 0


if __name__ == '__main__':
    sys.exit(main())
