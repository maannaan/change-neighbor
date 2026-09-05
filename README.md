# Change Neighbor

A read-only analyzer that looks at **uncommitted Git changes**, reads the **actual diffs**, infers a deterministic change intent, then compares that against repository history to rank the **3–10 files you are most likely forgetting**.

It is packaged two ways:

- **Python CLI** — `scripts/change_neighbor.py` (stdlib only)
- **Rote Play** — adapterless TypeScript Play in `play/` that runs the same engine via `process.exec` and `@resource{change_neighbor.py}`

No LLMs. No network calls. It never modifies the target repository, never runs repository code, and never installs dependencies.

## Safety

The engine only runs allowlisted read-only Git commands: `status`, `log`, `rev-parse`, `ls-files`, and `diff`. It does not create commits, checkout branches, write files, push remotes, or call the network. Recommendations use cautious wording: files **may deserve review**. Nothing is marked required, missing, or incomplete.

## Play usage

```bash
rote play run play/main.ts repo_path=/absolute/path/to/git/repo
```

`repo_path` must be an absolute path to a Git working tree. The Play runs one `process.exec` step (`python3` + the packaged engine) and renders `out.human`, `out.summary`, and `out.result`.

Authoring checks (do not publish from these):

```bash
rote play validate play/main.ts
rote play lint play/main.ts
rote play score play/main.ts
```

## Python CLI

```bash
python3 scripts/change_neighbor.py --repo /path/to/repo
python3 scripts/change_neighbor.py --repo /path/to/repo --json
```

JSON includes `change_analysis`, `completeness_map`, `likely_forgotten_neighbors` (`high` / `medium` / `watch`), and a longer `candidates` list.

Against the Mend evaluation repo:

```bash
python3 scripts/change_neighbor.py --repo ~/Desktop/Manan/Hackathons/Mend-change-neighbor-test
```

If the working tree is clean, the report lists no current changes and no neighbors.

Keep `scripts/change_neighbor.py` as the CLI source of truth. `play/resources/change_neighbor.py` is a packaged copy so the Play hash is self-contained.

## What V4 reports

1. **Current changes** — dirty paths.
2. **CHANGE ANALYSIS** — per-file intent and the path/diff signals that produced it.
3. **CHANGE COMPLETENESS MAP** — historically related system surfaces marked COVERED, REVIEW, or UNKNOWN. REVIEW means “inspect this area”; it does **not** mean required or incomplete. There is no completeness percentage.
4. **Likely forgotten neighbors**, capped:
   - HIGH CONFIDENCE — max 5
   - MEDIUM CONFIDENCE — max 5
   - WATCH LIST — max 5
5. **POSSIBLE TEST GAP** — only when source/API/backend changed, no related test is dirty, and a real historical test exists.

Each recommendation includes confidence, detected intent, supporting commits, and why it matters.

## V4 score weights

Neighbor ranking is unchanged from V3. Confidence is 0–100:

```
0.42 * weighted_frequency   # focus × recency
0.16 * frequency            # raw co-change
0.10 * min(support / 8, 1)
0.10 * proximity
0.08 * test_boost
0.14 * intent_compatibility # boost only; never a penalty
× class_multiplier
```

Bands: HIGH ≥ 70, MEDIUM ≥ 45, WATCH ≥ 25. History (weighted + raw + support) is 68% of the pre-multiplier mix. Intent cannot invent a file with no history.

See [research/algorithm.md](research/algorithm.md) for the formulas.

## Completeness map

Surfaces appear only if a current file or a ranked neighbor maps there. Intent never invents a surface.

| Status | Meaning |
| --- | --- |
| COVERED | The current change already contains a file on this surface. |
| REVIEW | This surface often co-changed with the dirty files, but is absent now. Inspect; do not treat as required. |
| UNKNOWN | Weak historical signal only. |

REVIEW is raised when a surface is absent and evidence is strong (`support ≥ 2` and `freq ≥ 0.30`, or `confidence ≥ 45`).

## Tests

```bash
python3 -m unittest tests/test_change_neighbor.py
```

## Limits

- Heuristic diffs, not semantic understanding. Binary or empty diffs fall back to path-only intent.
- Does not follow file renames across history.
- Skips merge commits.
- Thresholds are deterministic heuristics, not a learned model.
- Untracked or brand-new files have no history, so they produce no neighbors.
- No remotes, pull requests, or external APIs.
- The Play needs `python3` ≥ 3.10 and `git` on PATH.
