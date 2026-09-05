# Change Neighbor

Source: [https://github.com/maannaan/change-neighbor](https://github.com/maannaan/change-neighbor)

Public Play: [maannaaan/change-neighbor](https://play.modiqo.ai/maannaaan/change-neighbor)

A read-only repository intelligence tool. It looks at **uncommitted Git changes** (or a chosen baseline), reads the **actual diffs**, infers a deterministic change intent, then compares that against local commit history to surface files, tests, and system surfaces that historically change together.

It is packaged two ways:

- **Python CLI** — `scripts/change_neighbor.py` (stdlib only)
- **Rote Play** — adapterless TypeScript Play in `play/` that runs the same engine via `process.exec`

No LLMs. No network. It never modifies the target repository, never runs repository code, and never installs dependencies.

## Why it exists

Developers frequently modify one file while missing historically related implementation changes.

Examples:

- an API route changed but the client integration was not reviewed
- backend behavior changed but related tests were not inspected
- a schema changed but validation surfaces were missed
- a feature route changed but supporting services historically change with it

Change Neighbor uses repository history as **evidence** to surface files and system surfaces that **may deserve review**.

## What it analyzes

- uncommitted Git changes, or a chosen comparison baseline
- file paths and diffs
- commit co-change history
- historical coupling, recency, and focus
- implementation surfaces (API, UI, backend, schema, CI, docs)
- tests and possible test-coverage gaps

## Inputs

| Input | Required | Default | Purpose |
| --- | --- | --- | --- |
| `repo_path` / `--repo` | yes | — | Absolute path to the Git working tree |
| `history_limit` / `--history-limit` | no | 50 | Maximum historical commits to inspect (5–500) |
| `min_confidence` / `--min-confidence` | no | 25 | Hide neighbor recommendations below this 0–100 score |
| `include_tests` / `--include-tests` | no | true | Include test neighbors and possible test gaps |
| `include_surfaces` / `--include-surfaces` | no | true | Build the Change Completeness Map |
| `base_ref` / `--base-ref` | no | empty | Compare against a Git ref; empty means uncommitted changes |

## Play usage

```bash
rote play run play/main.ts repo_path=/absolute/path/to/git/repo
```

Configurable example:

```bash
rote play run play/main.ts \
  repo_path=/absolute/path/to/git/repo \
  history_limit=20 \
  min_confidence=40 \
  include_tests=false \
  include_surfaces=true \
  base_ref=origin/main
```

## Python CLI

```bash
python3 scripts/change_neighbor.py --repo /path/to/repo
python3 scripts/change_neighbor.py --repo /path/to/repo --json
```

Advanced:

```bash
python3 scripts/change_neighbor.py \
  --repo /path/to/repo \
  --history-limit 20 \
  --min-confidence 40 \
  --include-tests false \
  --include-surfaces true \
  --base-ref origin/main \
  --json
```

Keep `scripts/change_neighbor.py` as the CLI source of truth. `play/resources/change_neighbor.py` is a packaged copy so the Play hash is self-contained.

## How confidence works

Neighbor ranking is deterministic V4 scoring, not a machine-learning model.

```
0.42 * weighted_frequency   # focus × recency
0.16 * frequency            # raw co-change
0.10 * min(support / 8, 1)
0.10 * proximity
0.08 * test_boost
0.14 * intent_compatibility # boost only
× class_multiplier
```

| Band | Meaning |
| --- | --- |
| HIGH CONFIDENCE | Score ≥ 70. Strong historical pairing; inspect first. |
| MEDIUM CONFIDENCE | Score ≥ 45. Repeated co-change; worth a look. |
| WATCH LIST | Score ≥ 25 (or your `min_confidence`). Weaker signal. |
| POSSIBLE TEST GAP | A historically related test is absent from the current change. |

REVIEW on the completeness map means “inspect this area.” It does **not** mean required or incomplete.

## Safety model

- Allowlisted read-only Git only: `status`, `log`, `rev-parse`, `diff-tree`, `ls-files`, `diff`
- Executable is always literal `git` with `shell=False`
- Repository path and refs are argv data, never shell text
- No project code execution, npm scripts, or target-repo tests
- No dependency installation
- No network, remotes, credentials, or adapters
- Recommendations say **may deserve review**, **historically related**, **consider inspecting**

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
python3 -m unittest tests/test_change_neighbor.py
```
