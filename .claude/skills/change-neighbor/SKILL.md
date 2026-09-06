---
name: change-neighbor
description: >
  This skill should be used when planning or reviewing a code change and the
  user asks what else may need changing, which files historically change
  together, related tests, docs, or configs, impact analysis, neighboring
  components, or what to inspect before editing, opening a PR, or merging.
  Use it for questions like "which files should I inspect before changing
  authentication?", "what else usually changes with this module?", "help me
  understand the impact of modifying this API", or a safe implementation
  plan before touching a flow. It runs Change Neighbor, a historical
  co-change analyzer. Do not use it for typo-only, documentation-only, or
  formatting-only edits. For clone, onboarding, or portability questions
  use clone-trap. For previous bugs, reverts, or regressions use merge-memory.
---

# Change Neighbor

Surface files, tests, and surfaces that historically change together. Output is review evidence, not a required edit list.

## When to use

- Impact analysis before editing
- "What else usually changes with this module?"
- Preparing a PR or merge
- Understanding neighboring components of an API, auth flow, or similar area

## When not to use

- Typo-only, documentation-only, or formatting-only edits
- Clone/onboarding/portability questions → use **clone-trap**
- "Has this area failed before?" / reverts / regressions → use **merge-memory**

## Natural-language triggers

- "Which files should I inspect before changing authentication?"
- "What else usually changes with this module?"
- "Help me understand the impact of modifying this API."
- "I need a safe implementation plan before changing this flow."

## Command

Files are **not** CLI arguments. The change set comes from the dirty tree, or from `--base-ref` when the tree is clean.

Prefer the skill launcher (resolves this checkout even when the skill is symlinked):

```bash
bash ~/.claude/skills/change-neighbor/scripts/run --repo /absolute/path/to/git/repo --json
```

Clean working tree (required, or neighbors will be empty):

```bash
bash ~/.claude/skills/change-neighbor/scripts/run \
  --repo /absolute/path/to/git/repo \
  --base-ref HEAD~5 \
  --history-limit 30 \
  --json
```

Equivalent direct command (`python` may be missing; use `python3`):

```bash
python3 /absolute/path/to/change-neighbor/scripts/change_neighbor.py \
  --repo /absolute/path/to/git/repo --json
```

`--repo` is required. Do not invent file path arguments.

## How to interpret output

JSON includes `current_changes`, neighbor bands (HIGH / MEDIUM / WATCH), optional tests and surfaces.

- Empty `current_changes` on a clean tree without `--base-ref` is honest, not a crash. Re-run with `--base-ref`.
- Neighbor scores are historical co-change, not requirements.
- Inspect cited files. Do not auto-edit them because they appeared.

## Evidence language rules

- Say: "Historically related changes often included…"
- Never say: "This file must also change."
- Never say a change is incomplete because a neighbor is missing.
- Empty neighbors mean insufficient historical pairing, not "nothing else matters."
