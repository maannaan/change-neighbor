# Algorithm (V4)

The tool answers: **which 3–10 files is a developer most likely forgetting?** and **which historically related system surfaces may deserve inspection?** Neighbor ranking is unchanged from V3. V4 only groups that evidence into a Change Completeness Map.

## Architecture

1. Detect dirty paths (`git status`).
2. Extract a read-only diff per path (`git diff HEAD`, or untracked file bytes as added lines).
3. Infer one or more intents from path + diff heuristics.
4. Mine non-merge history (timestamps + file lists) exactly as in V2.
5. Score historically co-changed files with the V3 composite, including `intent_compatibility`.
6. Emit CHANGE ANALYSIS, a Change Completeness Map, top-K bands, optional test gap, and JSON.

No LLMs. No network. History remains the foundation: a file with zero co-change history cannot be recommended, and a surface with no historical candidates is not invented from intent.

## Inputs

- `--repo`: local Git working tree
- Current changes: `git status --porcelain -z --untracked-files=all`
- Diffs: `git diff HEAD -- <path>` (staged + unstaged). Untracked files are read from disk as `+` lines. Binaries and files over 100KB are skipped (path-only intent).
- History: `git log --no-merges --pretty=format:%H %ct --name-only`

## Change intent

Intents: `api`, `database`, `authentication`, `frontend_ui`, `backend_logic`, `configuration`, `dependency`, `test`, `documentation`, `ci`, `unknown`.

**Path tokens** (generic):

| Path | Intent |
| --- | --- |
| `routes/`, `api/`, `controller/`, `endpoints/` | `api` (+ `backend_logic` under `backend/`/`server/`) |
| `components/`, `pages/`, `frontend/`, `ui/` | `frontend_ui` |
| `models/`, `migrations/`, `schema/`, `alembic/` | `database` |
| `auth/`, `jwt/`, `session/`, `login/` | `authentication` |
| `tests/`, `*.test.*`, `test_*` | `test` |
| `.github/workflows/` | `ci` |

**Diff patterns** (added and context lines): route decorators / HTTP verbs, SQL (`CREATE TABLE`, `ALTER TABLE`, `INSERT INTO`), auth tokens (`jwt`, `password`, `login`, …), `process.env` / `os.environ`, dependency version pins.

A file may have several intents. Display: `api` → `API / backend route`. Nothing matched → `unknown`.

## Intent compatibility (boost only)

`intent_compatibility` is 0.0–1.0. Unmatched is **0**, never a penalty.

| Current intent | Strong (1.0) | Related (0.5) |
| --- | --- | --- |
| api | `api`/`client`/`sdk` in path, `api_contract`, `test_api` | frontend source, other tests |
| frontend_ui | components/pages/ui, matching tests | `lib/api` clients |
| authentication | auth/middleware/session/login, auth tests | configuration |
| database | migrations/models/schema, db tests | `api_contract` |
| backend_logic | backend/services/routes tests | nearby source |
| configuration / ci / documentation / dependency / test | matching class or path | — |

## Per-commit weights (unchanged)

```
focus(n)    = min(1.0, 4 / max(n, 1))
age_days    = max(0, (newest_ts - commit_ts) / 86400)
recency     = max(0.15, 0.5 ** (age_days / 90))
w(commit)   = recency * focus
```

```
frequency(B)          = |C_A ∩ C_B| / |C_A|
weighted_frequency(B) = sum(w in C_A ∩ C_B) / sum(w in C_A)
```

## File classification and noise

Same V2 classes and multipliers. Excluded: generated, dependency lockfiles, result dumps. Meta docs keep a 0.15 multiplier.

## Composite score

Relative contribution (before `class_multiplier`):

| Factor | Weight | Notes |
| --- | --- | --- |
| weighted_frequency | 42% | includes commit focus × recency |
| frequency | 16% | raw historical co-change |
| support volume | 10% | `min(support / 8, 1)` |
| path_proximity | 10% | same dir = 1.0 |
| test_boost | 8% | naming conventions / nearby tests |
| intent_compatibility | 14% | boost only |
| class_multiplier | after | file-type penalty |

```
confidence = clamp(0, 100,
  100 * (
    0.42 * weighted_frequency +
    0.16 * frequency +
    0.10 * min(support / 8, 1) +
    0.10 * proximity +
    0.08 * test_boost +
    0.14 * intent_compatibility
  ) * class_multiplier
)
```

History (weighted + raw + support) is 68% of the pre-multiplier mix. Intent cannot create a recommendation from nothing.

Bands (max 5 each): HIGH >= 70, MEDIUM >= 45, WATCH >= 25.

## Explanations

- Change intent detected: display label
- Evidence: `changed with {anchor} in {support}/{relevant} relevant commits.`
- Why it matters: ties the detected intent to the candidate (for example, API route ↔ `frontend/lib/api.ts`)

JSON includes `change_analysis: [{path, intents, signals}]` plus `intent_compatibility` on each neighbor.

## Change Completeness Map

V4 does **not** score whether a change is complete. It groups existing ranked neighbors into system surfaces and labels each:

| Status | Meaning |
| --- | --- |
| COVERED | Observed fact: the current change already contains a file on this surface. |
| REVIEW | Historical evidence: this surface often co-changed with the dirty files, but it is absent now. Inspect, do not treat as required. |
| UNKNOWN | Weak historical signal only. Insufficient to recommend inspection. |

A surface appears only if it is COVERED by a current file **or** at least one ranked neighbor maps to it. Intent alone never invents a surface. No completeness percentage is computed — that would convert evidence into a false precision.

REVIEW requires strongest `support >= 2` and `frequency >= 0.30`, or strongest `confidence >= 45`. Weaker ranked neighbors produce UNKNOWN.

The tool distinguishes:

- **Observed fact** — files in the current change set
- **Historical evidence** — co-change counts from Git history
- **Recommendation** — inspect REVIEW surfaces before committing
- **Unknown** — not enough evidence to say more

Never COMPLETE / INCOMPLETE / MISSING / REQUIRED.

## Possible test gap

Shown when source changed, no related test is already dirty, and a historical test exists. If the current intent is `api` or `backend_logic`, also accept a test with `intent_compatibility >= 0.5` and `support >= 1` (for example `backend/tests/test_api.py`). Cap 3. Paths never seen in Git are never invented.

## Safety

Read-only Git only: `status`, `log`, `rev-parse`, `ls-files`, `diff`. No add, commit, checkout, reset, or network.
