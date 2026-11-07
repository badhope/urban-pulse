# Release process

World Games follows [Semantic Versioning](https://semver.org/). The version has exactly one
source of truth: `__init__.py:__version__`. `pyproject.toml` must match it, and `verify_docs.py`
fails the gate if they disagree.

## Version numbers

| Part | Bump when |
|---|---|
| MAJOR | The state schema or tool contract breaks without a compatibility path |
| MINOR | New tools, subsystems, templates or layers; backward compatible |
| PATCH | Bug fixes, documentation, tests, internal refactors |

## Cutting a release

1. **Land the work on `main`.** No long-lived branches: `main` is the only branch, and it always
   matches `origin/main`.
2. **Update `CHANGELOG.md`.** Move the entry out of "未发布" into a dated `## vX.Y.Z — YYYY-MM-DD`
   section. Keep the categories `新增` / `变更` / `修复` / `验证`.
3. **Bump the version** in `__init__.py` and `pyproject.toml` (both, same value).
4. **Regenerate the metric ledger:**

   ```bash
   python scripts/metrics.py --write --coverage <measured>
   ```

   Never hand-edit `docs/metrics.json`, and never type a number into a document that the ledger
   already tracks.
5. **Run the full gate:**

   ```bash
   bash scripts/pre_push_gate.sh
   ```

   All 33 steps must pass. Coverage must be ≥70%, mutation survival must be 0%, and no check may
   be skipped for a missing dependency — a missing tool fails the gate.

6. **Commit and tag:**

   ```bash
   git add -A
   git commit -m "release: vX.Y.Z"
   git tag -a vX.Y.Z -m "World Games vX.Y.Z"
   ```

7. **Push `main` and the tag:**

   ```bash
   git push origin main
   git push origin vX.Y.Z
   ```

8. **Verify the remote actually has it:**

   ```bash
   git ls-remote --tags origin vX.Y.Z
   git ls-remote --heads origin main
   ```

   Report the remote commit hash, never "should be pushed".

## What a release must contain

- `CHANGELOG.md` entry with a date and a `验证` line quoting real numbers.
- `README.md` and `README.zh-CN.md` in sync (both are checked by `verify_docs.py` D7b/D20).
- `docs/metrics.json` regenerated from the tree, not from memory.
- A tag whose name matches `v<version>`.
- A clean working tree: `git status --short` prints nothing.

## Hotfixes

Same process with a PATCH bump. If the fix touches the state schema, it is not a hotfix — cut a
MINOR or MAJOR release instead, and document the migration.

## Deprecations

Removing a tool or renaming a command requires:

1. A `CHANGELOG.md` entry under `变更` that names the old and new surface.
2. At least one MINOR release where both work (the `world-walker` / `world-walker-mcp` aliases are
   the standing example).
3. `GAME_MASTER_PROTOCOL.md` updated in the same commit.
