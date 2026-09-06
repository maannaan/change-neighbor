# Change Neighbor

**What else may deserve review?**

`Python 3.10+` · `Git` · `stdlib tests` · `Rote Play`

Source: [https://github.com/maannaan/change-neighbor](https://github.com/maannaan/change-neighbor)

Published Play: [`maannaaan/change-neighbor@0.1.2`](https://play.modiqo.ai/maannaaan/change-neighbor@0.1.2)

A read-only repository intelligence tool. It looks at uncommitted Git changes (or a chosen baseline), reads the actual diffs, and compares them to local commit history. The output is files, tests, and system surfaces that historically change together and **may deserve review**.

It never says a file is required. It never says a change is incomplete.

## Problem

Developers often edit one file and miss historically related neighbors: the client that calls a new route, the test that covered the last similar change, the schema that moved with the backend.

History already knows those pairings. Most review tools do not surface them.

## Solution

Change Neighbor treats local Git history as evidence. It ranks neighbors by co-change, recency, focus, proximity, and a deterministic change intent. Recommendations stay cautious: inspect, do not treat as required.

```
  dirty tree or base_ref
            |
            v
   read paths + diffs  ----->  change intent
            |                        |
            v                        v
   local commit history  ----->  score neighbors
            |
            +--> HIGH / MEDIUM / WATCH files
            +--> possible test gaps (optional)
            +--> completeness surfaces (optional)
```

## Features

- Stdlib-only Python engine (`scripts/change_neighbor.py`)
- Adapterless Rote Play that execs the same packaged engine
- Six real inputs: repo path, history limit, min confidence, tests, surfaces, baseline ref
- HIGH / MEDIUM / WATCH bands plus an optional completeness map
- Read-only Git argv (`shell=False`, allowlisted subcommands)
- No network, no adapters, no target-repo code execution, no installs

## Clone and install

```bash
git clone https://github.com/maannaan/change-neighbor.git
cd change-neighbor
```

Requirements: Python 3.10+ and Git on `PATH`. There is nothing to pip-install.

## Python CLI

```bash
python3 scripts/change_neighbor.py --repo /absolute/path/to/git/repo
python3 scripts/change_neighbor.py --repo /absolute/path/to/git/repo --json
```

```bash
python3 scripts/change_neighbor.py \
  --repo /absolute/path/to/git/repo \
  --history-limit 20 \
  --min-confidence 40 \
  --include-tests false \
  --include-surfaces true \
  --base-ref HEAD \
  --json
```

`scripts/change_neighbor.py` is the source of truth. `play/resources/change_neighbor.py` is a byte-identical packaged copy.

## Claude Code skill

Canonical agent skill: [`.claude/skills/change-neighbor/`](.claude/skills/change-neighbor/). Claude Code does not load `.cursor/skills`. To make it available in any project:

```bash
ln -sfn "$(pwd)/.claude/skills/change-neighbor" ~/.claude/skills/change-neighbor
```

Skip the command if `~/.claude/skills/change-neighbor` already exists and is not a symlink. Cursor loads the same files via `.cursor/skills/change-neighbor`.

## Published Play (pinned)

```bash
rote play inspect https://play.modiqo.ai/maannaaan/change-neighbor@0.1.2
rote play run https://play.modiqo.ai/maannaaan/change-neighbor@0.1.2 \
  repo_path=/absolute/path/to/git/repo
```

Local checkout:

```bash
rote play run play/main.ts repo_path=/absolute/path/to/git/repo
```

`rote play info` may print `version: 0.80.0`. That is the Rote runtime (`rote_version`). The Play version is frontmatter **0.1.2**.

## Inputs

| Input | Required | Default | Purpose |
| --- | --- | --- | --- |
| `repo_path` / `--repo` | yes | — | Absolute path to the Git working tree |
| `history_limit` / `--history-limit` | no | 50 | Maximum historical commits to inspect (5–500) |
| `min_confidence` / `--min-confidence` | no | 25 | Hide neighbor recommendations below this 0–100 score |
| `include_tests` / `--include-tests` | no | true | Include test neighbors and possible test gaps |
| `include_surfaces` / `--include-surfaces` | no | true | Build the Change Completeness Map |
| `base_ref` / `--base-ref` | no | empty | Compare against a Git ref (`HEAD`, `origin/main`, …). Empty means the uncommitted working tree. Option-shaped values such as `--all` are refused. |

## Example (Mend eval repo)

Dirty file: `backend/app/routes/demo.py`

Strong neighbor: `frontend/lib/api.ts` — HIGH **82/100**, changed together in **8/8** relevant commits.

Inspect that pairing. Do not treat it as required.

## Safety

- Allowlisted read-only Git only: `status`, `log`, `rev-parse`, `diff-tree`, `ls-files`, `diff`
- Executable is always literal `git` with `shell=False`
- Repository path and refs are argv data, never shell text
- No project code execution, npm scripts, or target-repo tests
- No dependency installation
- No network, remotes, credentials, or adapters
- Wording stays **may deserve review**, **historically related**, **consider inspecting**

## Limitations

- Historical co-change is evidence, not proof
- New projects may lack enough history to recommend anything
- Large monorepos may need a lower `history_limit`
- Unrelated files can occasionally co-change
- Recommendations are not requirements
- Does not follow renames; skips merge commits
- Heuristic diffs, not semantic understanding

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Project status

Released. Public Play: [`maannaaan/change-neighbor@0.1.2`](https://play.modiqo.ai/maannaaan/change-neighbor@0.1.2). Licensed MIT. Contributions welcome via pull request.
