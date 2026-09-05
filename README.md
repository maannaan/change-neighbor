# Change Neighbor

Source: [https://github.com/maannaan/change-neighbor](https://github.com/maannaan/change-neighbor)

A read-only analyzer for the question: **when I change this part of a codebase, what other files, tests, and system surfaces historically tend to change with it?**

It looks at **uncommitted Git changes** (or an optional baseline revision), reads the **actual diffs**, infers a deterministic change intent, then ranks historically co-changed files that **may deserve review** before you commit.

It is packaged two ways:

- **Python CLI** — `scripts/change_neighbor.py` (stdlib only)
- **Rote Play** — `maannaaan/change-neighbor` (`play/main.ts`)

No LLMs. No network calls. It never modifies the target repository, never runs repository code, and never installs dependencies.

## Why it exists

Developers frequently modify one file while leaving historically related work untouched. Typical cases:

- an API route changed but the client integration was not reviewed
- backend behavior changed but related tests were not inspected
- a schema changed but validation surfaces were missed
- a feature route changed alongside services that usually move with it

Change Neighbor uses repository history as **evidence**, not proof. A HIGH neighbor or a REVIEW surface is a suggestion to inspect that area. It does not mean the change is required, missing, or incomplete.

## What it analyzes

- uncommitted Git changes, or a chosen baseline revision
- file paths and diffs
- non-merge commit co-change history
- historical coupling, recency, and path proximity
- implementation surfaces (API, UI, backend, schema, CI, docs)
- tests and possible test gaps

## Inputs

| Input | Required | Default | Purpose |
| --- | --- | --- | --- |
| `repo_path` | yes | — | Absolute path to the Git repository |
| `history_limit` | no | 50 | Max historical commits to inspect (5–500) |
| `min_confidence` | no | 25 | Hide neighbors below this 0–100 score |
| `include_tests` | no | true | Include test neighbors and test-gap hints |
| `include_surfaces` | no | true | Build the Change Completeness Map |
| `base_ref` | no | empty | Compare against a Git revision; empty uses the uncommitted working tree |

## Example

Basic (uncommitted changes, defaults):

```bash
python3 scripts/change_neighbor.py --repo /absolute/path/to/repo
```

JSON:

```bash
python3 scripts/change_neighbor.py --repo /absolute/path/to/repo --json
```

Configurable:

```bash
python3 scripts/change_neighbor.py \
  --repo /absolute/path/to/repo \
  --history-limit 20 \
  --min-confidence 40 \
  --include-tests false \
  --include-surfaces true \
  --base-ref HEAD \
  --json
```

Play:

```bash
rote play run play/main.ts repo_path=/absolute/path/to/repo
rote play run play/main.ts \
  repo_path=/absolute/path/to/repo \
  history_limit=20 \
  min_confidence=40 \
  include_tests=false \
  include_surfaces=true
```

Keep `scripts/change_neighbor.py` as the CLI source of truth. `play/resources/change_neighbor.py` is a packaged copy.

## How confidence works

Neighbor ranking is a deterministic V3/V4 composite, not a machine-learning model:

```
0.42 * weighted_frequency   # focus × recency
0.16 * frequency            # raw co-change
0.10 * min(support / 8, 1)
0.10 * proximity
0.08 * test_boost
0.14 * intent_compatibility # boost only
× class_multiplier
```

| Band | Score | Meaning |
| --- | --- | --- |
| HIGH CONFIDENCE | ≥ 70 | Strong historical pairing; inspect first |
| MEDIUM CONFIDENCE | ≥ 45 | Repeated co-change; worth a look |
| WATCH LIST | ≥ 25 | Weaker but real history |
| POSSIBLE TEST GAP | evidence-only | A related test historically moves with this change and is not dirty |

`min_confidence` hides recommended neighbors below the chosen floor. The completeness map still uses historical evidence when surface analysis is enabled.

REVIEW on a surface means “inspect this area.” It does **not** mean required or incomplete. There is no completeness percentage.

See [research/algorithm.md](research/algorithm.md) for the formulas.

## Safety model

- Allowlisted read-only Git only: `status`, `log`, `rev-parse`, `diff-tree`, `ls-files`, `diff`
- Executable is always the literal `git` with `shell=False`
- Repository path and revisions are argv data, never shell text
- No repository code execution, no install commands, no network, no credentials
- The Play is adapterless: `requires_endpoints: []`, `requires_sessions: false`

## Limitations

- Historical co-change is evidence, not proof.
- New repositories may lack enough history to recommend anything.
- Large monorepos may need a lower `history_limit`.
- Unrelated files can occasionally land in the same commit.
- Recommendations are not requirements.
- Heuristic diffs, not semantic understanding. Binary or empty diffs fall back to path-only intent.
- File renames are not followed across history. Merge commits are skipped.

## Tests

```bash
python3 -m unittest tests/test_change_neighbor.py
```
