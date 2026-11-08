"""Publish a GitHub Release with the built executable attached.

Why a Release asset instead of a committed file: a 30 MB binary in git makes
every clone permanently heavier, and uploading it through the Git Data API is
unreliable over long transfers. Release assets are the standard binary channel
and keep history clean.

Why this lives in scripts/: mirror synchronisation and release publishing are
recurring release operations, not one-off scratch work. Keeping them here means
the next release does not have to rediscover the API sequence (and does not
fail because a scratch file was cleaned up — which happened twice).

Usage:
    python scripts/publish_release.py <account> <owner/repo> <tag> [--asset PATH]
"""

from __future__ import annotations

import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = 'https://api.github.com'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.expanduser('~/.agent-secrets/accounts.json')

def _ledger() -> dict:
    """Read the published numbers from the single source of truth.

    Why: the release notes used to hard-code "32 steps / 50 mutants / 86%".
    Those went stale the moment the gate grew, and a release page that quotes
    wrong numbers is a worse advertisement than no numbers at all. The ledger is
    generated from the tree (scripts/metrics.py), so read it at publish time.
    """
    path = os.path.join(ROOT, 'docs', 'metrics.json')
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def _body(repo: str, tag: str) -> str:
    m = _ledger()
    return f"""**The AI narrates. The engine decides.**

World Games is the rules layer for AI-driven interactive games: your agent writes the prose, a
deterministic engine resolves every hit, price, relationship and faction shift, then persists it to
one auditable state file.

### What is in this release

- **{m['tools']} MCP tools**, **4 MCP resources**, tool annotations on all of them
- **Remote agents supported**: stdio by default, plus `wg mcp --http` (streamable-http)
- **Replayable**: every mutating call is logged with RNG counters and before/after state
  fingerprints, so the same seed plus the action log reproduces the same world
- **World rules live in the setting bundle** (`rules` field), not in the engine
- **NPC knowledge boundaries**: an NPC cannot cite a fact they did not witness
- **Loop detection** when the player is circling, with dead-end hints pruned from suggestions
- **Light by default**, dark one click away, both measured against WCAG AA
- **One front door**: `wg init / play / serve / mcp / run / doctor / version`
- **Standalone binary**: no Python required
- **Read-only web stage** at `/`, administration console at `/admin`

### Verify it yourself

```bash
world-games.exe doctor            # assets, bundles, optional dependencies
world-games.exe init my-game.json
world-games.exe play --state my-game.json
```

The full gate is {m['gate_steps']} steps with {m['mutants']} mutation tests; coverage {m['coverage_pct']}%.
This build reports version {m['version']} and ships {m['verify_scripts']} self-check scripts.

See the [README](https://github.com/{{repo}}#readme) and
[CHANGELOG](https://github.com/{{repo}}/blob/main/CHANGELOG.md).
"""


def token(account: str) -> str:
    with open(STORE, encoding='utf-8') as fh:
        return json.load(fh)['platforms']['github']['accounts'][account]['token']


def call(tok: str, method: str, path: str, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {
        'Authorization': 'Bearer %s' % tok,
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'world-games-release',
    }
    if data is not None:
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(API + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read().decode('utf-8')
            return resp.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode('utf-8') or '{}')


def upload_asset(tok: str, upload_url: str, path: str) -> dict:
    """Upload one asset; retries because this network truncates large bodies."""
    name = os.path.basename(path)
    size = os.path.getsize(path)
    url = '%s?name=%s' % (upload_url.split('{')[0], urllib.parse.quote(name))
    ctype = mimetypes.guess_type(name)[0] or 'application/octet-stream'
    with open(path, 'rb') as fh:
        payload = fh.read()
    headers = {
        'Authorization': 'Bearer %s' % tok,
        'Accept': 'application/vnd.github+json',
        'Content-Type': ctype,
        'Content-Length': str(size),
        'User-Agent': 'world-games-release',
    }
    for attempt in range(4):
        req = urllib.request.Request(url, data=payload, method='POST', headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode('utf-8')[:200]
            if exc.code == 422 and 'already_exists' in detail:
                return {'already_exists': True}
            if attempt == 3:
                raise SystemExit('asset upload failed: %s %s' % (exc.code, detail))
            time.sleep(2 + attempt)
        except Exception as exc:
            if attempt == 3:
                raise SystemExit('asset upload network failure: %s' % exc)
            time.sleep(2 + attempt)
    return {}


def main() -> int:
    if len(sys.argv) < 4:
        raise SystemExit('usage: publish_release.py <account> <owner/repo> <tag> [--asset PATH]')
    account, repo, tag = sys.argv[1], sys.argv[2], sys.argv[3]
    assets = []
    if '--asset' in sys.argv:
        assets.append(sys.argv[sys.argv.index('--asset') + 1])

    tok = token(account)
    status, existing = call(tok, 'GET', '/repos/%s/releases/tags/%s' % (repo, tag))
    if status == 200:
        print('release %s already exists: %s' % (tag, existing.get('html_url')))
        release = existing
    else:
        status, release = call(tok, 'POST', '/repos/%s/releases' % repo, {
            'tag_name': tag,
            'name': 'World Games ' + tag,
            'body': _body(repo, tag),
            'draft': False,
            'prerelease': False,
        })
        if status not in (200, 201):
            raise SystemExit('release create failed: %s %s' % (status, release))
        print('release created: %s' % release.get('html_url'))

    for path in assets:
        if not os.path.isfile(path):
            raise SystemExit('asset missing: %s' % path)
        print('uploading %s (%.1f MB)...'
              % (os.path.basename(path), os.path.getsize(path) / 1024 / 1024))
        result = upload_asset(tok, release['upload_url'], path)
        if result.get('already_exists'):
            print('  already attached, skipping')
        else:
            print('  attached:', result.get('browser_download_url', '?'))

    status, after = call(tok, 'GET', '/repos/%s/releases/tags/%s' % (repo, tag))
    print('release assets:', [a['name'] for a in after.get('assets', [])])
    return 0


if __name__ == '__main__':
    sys.exit(main())
