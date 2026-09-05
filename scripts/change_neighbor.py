#!/usr/bin/env python3
"""Change Neighbor: suggest historically co-changed files you may have forgotten."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple


READ_ONLY_GIT_COMMANDS = frozenset(
    {"status", "log", "rev-parse", "diff-tree", "ls-files", "diff"}
)

FOCUS_REF = 4.0
RECENCY_HALF_LIFE_DAYS = 90.0
RECENCY_FLOOR = 0.15
SECONDS_PER_DAY = 86400.0

HIGH_MIN_CONFIDENCE = 70
MEDIUM_MIN_CONFIDENCE = 45
WATCH_MIN_CONFIDENCE = 25
DEFAULT_HISTORY_LIMIT = 50
HISTORY_LIMIT_MIN = 5
HISTORY_LIMIT_MAX = 500
BAND_CAP = 5
JSON_CANDIDATE_CAP = 25
TEST_GAP_CAP = 3
DIFF_BYTE_CAP = 100_000
SURFACE_REPRESENTATIVE_CAP = 3
REVIEW_MIN_SUPPORT = 2
REVIEW_MIN_FREQUENCY = 0.30
REVIEW_MIN_CONFIDENCE = 45

SURFACE_LABELS = {
    "backend_api": "Backend API",
    "api_integration": "API Integration",
    "frontend_ui": "Frontend UI",
    "backend_logic": "Backend Logic",
    "tests": "Tests",
    "data_schema": "Data / Schema",
    "configuration": "Configuration",
    "ci": "CI",
    "documentation": "Documentation",
    "dependency": "Dependency",
    "unknown": "Unknown",
}
SURFACE_ORDER = (
    "backend_api",
    "api_integration",
    "frontend_ui",
    "backend_logic",
    "tests",
    "data_schema",
    "configuration",
    "ci",
    "documentation",
    "dependency",
    "unknown",
)

INTENT_LABELS = {
    "api": "API / backend route",
    "database": "database / schema",
    "authentication": "authentication",
    "frontend_ui": "frontend UI",
    "backend_logic": "backend logic",
    "configuration": "configuration",
    "dependency": "dependency",
    "test": "test",
    "documentation": "documentation",
    "ci": "CI / workflow",
    "unknown": "unknown",
}
ChangeAnalysis = Dict[str, object]

SOURCE_EXTENSIONS = frozenset(
    {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".c",
        ".cpp",
        ".cc",
        ".h",
        ".hpp",
        ".rb",
        ".php",
        ".swift",
        ".cs",
        ".vue",
        ".svelte",
        ".m",
        ".mm",
        ".scala",
        ".kts",
    }
)
DOC_EXTENSIONS = frozenset({".md", ".rst", ".adoc", ".txt"})
CONFIG_EXTENSIONS = frozenset(
    {".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".env"}
)
LOCKFILE_NAMES = frozenset(
    {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "cargo.lock",
        "poetry.lock",
        "go.sum",
        "gemfile.lock",
        "pipfile.lock",
        "composer.lock",
        "bun.lock",
        "bun.lockb",
        "npm-shrinkwrap.json",
    }
)
GENERATED_DIRS = frozenset({"dist", "build", ".next", "coverage", "__pycache__"})
TEST_DIRS = frozenset({"test", "tests", "__tests__", "spec", "specs"})
DUMP_DIRS = frozenset(
    {"benchmark", "bench", "perf", "results", "collectors", "examples"}
)
CI_DIR_MARKERS = (
    (".github", "workflows"),
    (".gitlab-ci",),
    (".circleci",),
)
CI_BASENAMES = frozenset(
    {
        "jenkinsfile",
        "azure-pipelines.yml",
        "azure-pipelines.yaml",
        ".travis.yml",
        ".gitlab-ci.yml",
    }
)
META_TOKENS = frozenset(
    {
        "submission",
        "judge",
        "judges",
        "linkedin",
        "prize",
        "prizes",
        "hackathon",
        "changelog",
        "contributing",
        "license",
        "licence",
        "authors",
        "codeofconduct",
        "pitch",
        "tweet",
        "twitter",
    }
)
DB_DIR_MARKERS = frozenset({"migrations", "alembic"})
CONTRACT_MARKERS = ("openapi", "swagger", "graphql")

Neighbor = Dict[str, object]
NeighborBuckets = Dict[str, List[Neighbor]]
CommitRecord = Tuple[str, int, List[str]]


class ChangeNeighborError(Exception):
    """User-facing error with a helpful message."""


def parse_bool(value: object) -> bool:
    """Parse Play/CLI boolean scalars (`true`/`false`/`1`/`0`)."""
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    raise ChangeNeighborError(
        f"Invalid boolean {value!r}. Use true or false."
    )


def parse_bounded_int(
    value: object,
    *,
    name: str,
    minimum: int,
    maximum: int,
) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ChangeNeighborError(
            f"{name} must be an integer between {minimum} and {maximum}."
        ) from exc
    if number < minimum or number > maximum:
        raise ChangeNeighborError(
            f"{name} must be between {minimum} and {maximum}."
        )
    return number


def normalize_base_ref(value: Optional[str]) -> str:
    """Return a validated baseline ref, or empty for uncommitted analysis."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if "\n" in text or "\r" in text or "\0" in text:
        raise ChangeNeighborError("base_ref must be a single Git reference.")
    if text.startswith("-"):
        raise ChangeNeighborError(
            "base_ref looks like a command option and was refused."
        )
    return text


def resolve_base_ref(repo: str, value: Optional[str]) -> str:
    """Validate and resolve a Git comparison baseline, if provided."""
    ref = normalize_base_ref(value)
    if not ref:
        return ""
    try:
        run_git(repo, ["rev-parse", "--verify", "--end-of-options", "--", ref])
    except ChangeNeighborError as exc:
        raise ChangeNeighborError(
            f"base_ref is not a valid Git reference: {ref}"
        ) from exc
    return ref


def empty_completeness_map(*, disabled: bool = False) -> Dict[str, object]:
    return {
        "surfaces": [],
        "summary": {
            "review_count": 0,
            "covered_count": 0,
            "unknown_count": 0,
        },
        "disabled": disabled,
    }


def is_test_path(path: str) -> bool:
    return classify_file(path) == "test" or classify_surface(path) == "tests"


def filter_test_neighbors(neighbors: Sequence[Neighbor]) -> List[Neighbor]:
    return [item for item in neighbors if not is_test_path(str(item.get("path") or ""))]


def filter_neighbors_by_confidence(
    neighbors: Sequence[Neighbor],
    min_confidence: int,
) -> List[Neighbor]:
    return [
        item
        for item in neighbors
        if int(item.get("confidence") or 0) >= min_confidence
    ]


def run_git(repo: str, args: Sequence[str], *, check: bool = True) -> str:
    """Run a read-only git command in repo and return stdout."""
    if not args or args[0] not in READ_ONLY_GIT_COMMANDS:
        raise ChangeNeighborError(
            "Internal error: refused to run a non-read-only git command."
        )

    # Executable is always the literal PATH tool `git`. The repo path and
    # allowlisted subcommand are argv data, never shell text. shell=False is
    # explicit so the Play auditor can see the boundary statically.
    try:
        completed = subprocess.run(
            ["git", "-C", repo, *args],
            shell=False,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as exc:
        raise ChangeNeighborError(
            "Git is not installed or not on PATH. Install Git and try again."
        ) from exc

    if check and completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        display = " ".join(["git", "-C", repo, *args])
        raise ChangeNeighborError(
            f"Git command failed ({display}): {detail or 'unknown error'}"
        )
    return completed.stdout


def validate_repo(repo: str) -> str:
    """Resolve and validate a local Git working tree."""
    if not repo:
        raise ChangeNeighborError("Please provide a repository path with --repo.")

    repo_path = os.path.abspath(os.path.expanduser(repo))
    if not os.path.exists(repo_path):
        raise ChangeNeighborError(f"Path does not exist: {repo_path}")
    if not os.path.isdir(repo_path):
        raise ChangeNeighborError(f"Path is not a directory: {repo_path}")

    try:
        inside = run_git(
            repo_path, ["rev-parse", "--is-inside-work-tree"]
        ).strip()
    except ChangeNeighborError as exc:
        message = str(exc)
        if "not a git repository" in message.lower():
            raise ChangeNeighborError(
                f"Not a Git repository: {repo_path}"
            ) from exc
        raise ChangeNeighborError(
            f"Not a Git repository or Git could not read it: {repo_path}"
        ) from exc

    if inside != "true":
        raise ChangeNeighborError(f"Not a Git working tree: {repo_path}")
    return repo_path


def parse_porcelain_paths(raw: str) -> List[str]:
    """Parse `git status --porcelain -z` output into current file paths."""
    paths: List[str] = []
    entries = raw.split("\0")
    i = 0
    while i < len(entries):
        entry = entries[i]
        if not entry:
            i += 1
            continue
        if len(entry) < 4:
            i += 1
            continue

        status = entry[:2]
        first_path = entry[3:]
        # Rename/copy records are "XY origin\0dest".
        if status[0] in {"R", "C"} or status[1] in {"R", "C"}:
            i += 1
            dest = entries[i] if i < len(entries) else ""
            path = dest or first_path
        else:
            path = first_path
        if path:
            paths.append(path)
        i += 1

    seen = set()
    unique: List[str] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def parse_name_only_paths(raw: str) -> List[str]:
    """Parse `git diff --name-only -z` output into unique paths."""
    seen = set()
    unique: List[str] = []
    for path in raw.split("\0"):
        if path and path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def get_changed_files(repo: str, base_ref: str = "") -> List[str]:
    """Return current change paths against HEAD working tree or a baseline ref."""
    if base_ref:
        raw = run_git(
            repo,
            ["diff", "--name-only", "-z", "--end-of-options", "--", base_ref],
            check=False,
        )
        return parse_name_only_paths(raw)
    raw = run_git(
        repo, ["status", "--porcelain", "-z", "--untracked-files=all"]
    )
    return parse_porcelain_paths(raw)


def is_tracked_file(repo: str, path: str) -> bool:
    listed = run_git(repo, ["ls-files", "--", path], check=False).strip()
    return bool(listed)


def get_file_diff(repo: str, path: str, base_ref: str = "") -> str:
    """Return a read-only staged+unstaged diff, or untracked file as added lines."""
    if is_tracked_file(repo, path):
        if base_ref:
            raw = run_git(
                repo,
                ["diff", "--end-of-options", "--", base_ref, "--", path],
                check=False,
            )
        else:
            raw = run_git(repo, ["diff", "HEAD", "--", path], check=False)
        if "Binary files" in raw and "differ" in raw:
            return ""
        return raw[:DIFF_BYTE_CAP]

    full = os.path.join(repo, path)
    if not os.path.isfile(full):
        return ""
    try:
        with open(full, "rb") as handle:
            data = handle.read(DIFF_BYTE_CAP + 1)
    except OSError:
        return ""
    if b"\0" in data:
        return ""
    try:
        text = data[:DIFF_BYTE_CAP].decode("utf-8")
    except UnicodeDecodeError:
        return ""
    return "".join(f"+{line}\n" for line in text.splitlines())


def get_change_analysis(
    repo: str,
    changed_files: Sequence[str],
    base_ref: str = "",
) -> List[ChangeAnalysis]:
    return [
        analyze_change(path, get_file_diff(repo, path, base_ref))
        for path in changed_files
    ]


def _diff_body(diff_text: str) -> str:
    lines: List[str] = []
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            continue
        if line.startswith("+") or line.startswith(" "):
            lines.append(line[1:])
    return "\n".join(lines)


def analyze_change(path: str, diff_text: str) -> ChangeAnalysis:
    """Infer deterministic intents from path and diff text."""
    intents: List[str] = []
    signals: List[str] = []

    def add(intent: str, signal: str) -> None:
        if intent not in intents:
            intents.append(intent)
        if signal and signal not in signals and len(signals) < 3:
            signals.append(signal)

    _add_path_intents(path, add)
    _add_diff_intents(path, diff_text, add)

    if not intents:
        intents.append("unknown")
        add("unknown", "no strong path or diff pattern")

    return {
        "path": path,
        "intents": intents,
        "signals": signals,
        "primary_label": format_intent_label(intents),
    }


def _add_path_intents(path: str, add) -> None:
    parts = [part.lower() for part in _path_parts(path)]
    base = _basename(path).lower()
    file_type = classify_file(path)

    if file_type == "test" or _is_test_path(parts, base):
        add("test", "test-related file path")
    if file_type == "ci":
        add("ci", "CI / workflow file path")
    if file_type == "documentation":
        add("documentation", "documentation file path")
    if file_type == "dependency" or base in LOCKFILE_NAMES:
        add("dependency", "dependency manifest path")
    if file_type == "configuration":
        add("configuration", "configuration file path")
    if file_type == "database" or any(
        part in {"models", "migrations", "schema", "alembic"} for part in parts
    ):
        add("database", "schema / migration / model path")
    if any(part in {"auth", "jwt", "session", "login"} for part in parts):
        add("authentication", "authentication-related file path")
    if any(part in {"components", "pages", "frontend", "ui"} for part in parts):
        add("frontend_ui", "frontend / UI file path")
    if any(part in {"routes", "api", "controller", "endpoints"} for part in parts):
        add("api", "route-related file path")
        if any(part in {"backend", "server"} for part in parts):
            add("backend_logic", "backend route file path")
    elif any(part in {"backend", "server", "services"} for part in parts):
        if file_type == "source":
            add("backend_logic", "backend source file path")


def _add_diff_intents(path: str, diff_text: str, add) -> None:
    body = _diff_body(diff_text)
    if not body:
        return
    lowered = body.lower()
    base = _basename(path).lower()

    if re.search(
        r"@app\.route|@router\.|apirouter|app\.(get|post|put|patch|delete)\s*\("
        r"|router\.(get|post|put|patch|delete)\s*\(|@(get|post|put|patch|delete)mapping",
        body,
        re.I,
    ) or re.search(r"\b(GET|POST|PUT|PATCH|DELETE)\b\s+[\"'/]", body):
        add("api", "HTTP route patterns found in diff")
        parts = [part.lower() for part in _path_parts(path)]
        if any(part in {"backend", "server"} for part in parts):
            add("backend_logic", "backend route patterns found in diff")

    if re.search(
        r"\b(CREATE\s+TABLE|ALTER\s+TABLE|INSERT\s+INTO|FOREIGN\s+KEY)\b"
        r"|\bSELECT\s+.+\s+FROM\b",
        body,
        re.I,
    ):
        add("database", "SQL / schema patterns found in diff")

    if re.search(
        r"\b(jwt|password|login|logout|bearer|oauth|authenticate|session)\b",
        lowered,
    ):
        add("authentication", "authentication tokens found in diff")

    if re.search(r"process\.env|os\.environ|\.env\b", body):
        add("configuration", "environment / config patterns found in diff")

    if base in {
        "package.json",
        "requirements.txt",
        "pyproject.toml",
        "cargo.toml",
        "go.mod",
        "gemfile",
    } and re.search(r"\b\d+\.\d+", body):
        add("dependency", "dependency version changes found in diff")


def format_intent_label(intents: Sequence[str]) -> str:
    if "api" in intents:
        return INTENT_LABELS["api"]
    labels: List[str] = []
    for intent in intents:
        label = INTENT_LABELS.get(intent, intent)
        if label not in labels:
            labels.append(label)
    return " / ".join(labels) if labels else INTENT_LABELS["unknown"]


def collect_intents(change_analysis: Optional[Sequence[ChangeAnalysis]]) -> List[str]:
    intents: List[str] = []
    for item in change_analysis or []:
        for intent in item.get("intents", []):
            if intent != "unknown" and intent not in intents:
                intents.append(str(intent))
    return intents


def intent_compatibility(
    candidate_path: str,
    file_type: str,
    current_intents: Sequence[str],
) -> float:
    """0–1 boost. Neutral when unmatched; never a penalty."""
    if not current_intents:
        return 0.0
    return max(
        _intent_compatibility_one(candidate_path, file_type, intent)
        for intent in current_intents
    )


def _intent_compatibility_one(path: str, file_type: str, intent: str) -> float:
    parts = [part.lower() for part in _path_parts(path)]
    stem = _stem(path).lower()
    lowered = _norm_path(path).lower()

    if intent == "api":
        if file_type == "api_contract":
            return 1.0
        if any(token in parts or token in stem for token in ("api", "client", "sdk")):
            return 1.0
        if file_type == "test" and "api" in stem:
            return 1.0
        if file_type == "test":
            return 0.5
        if "frontend" in parts and file_type == "source":
            return 0.5
        return 0.0

    if intent == "frontend_ui":
        if any(token in parts for token in ("components", "pages", "ui", "frontend")):
            return 1.0
        if file_type == "test" and any(
            token in parts for token in ("frontend", "components", "pages")
        ):
            return 1.0
        if "api" in stem or "/lib/api" in lowered:
            return 0.5
        return 0.0

    if intent == "authentication":
        if any(token in parts or token in stem for token in ("auth", "middleware", "session", "login", "jwt")):
            return 1.0
        if file_type == "test" and any(token in stem for token in ("auth", "login", "session")):
            return 1.0
        if file_type == "configuration":
            return 0.5
        return 0.0

    if intent == "database":
        if file_type == "database" or any(
            token in parts for token in ("migrations", "models", "schema", "alembic")
        ):
            return 1.0
        if file_type == "test" and any(token in stem for token in ("model", "schema", "migration", "db")):
            return 1.0
        if file_type == "api_contract":
            return 0.5
        return 0.0

    if intent == "backend_logic":
        if file_type == "test" and any(token in parts for token in ("backend", "server", "services", "routes")):
            return 1.0
        if file_type == "test":
            return 0.5
        if file_type == "source" and any(token in parts for token in ("services", "routes", "backend")):
            return 0.5
        return 0.0

    if intent in {"configuration", "ci", "documentation", "dependency", "test"}:
        type_map = {
            "configuration": "configuration",
            "ci": "ci",
            "documentation": "documentation",
            "dependency": "dependency",
            "test": "test",
        }
        if file_type == type_map[intent] or intent in parts or intent in stem:
            return 1.0
        return 0.0

    return 0.0


def load_history(
    repo: str,
    history_limit: int = DEFAULT_HISTORY_LIMIT,
) -> List[CommitRecord]:
    """Load non-merge commits with timestamps and the files each one modified."""
    limit = parse_bounded_int(
        history_limit,
        name="history_limit",
        minimum=HISTORY_LIMIT_MIN,
        maximum=HISTORY_LIMIT_MAX,
    )
    raw = run_git(
        repo,
        [
            "log",
            "--no-merges",
            "--max-count",
            str(limit),
            "--pretty=format:%H %ct",
            "--name-only",
        ],
        check=False,
    )
    if not raw.strip():
        return []
    return _parse_history(raw)


def _parse_history(raw: str) -> List[CommitRecord]:
    commits: List[CommitRecord] = []
    current_sha: Optional[str] = None
    current_ts = 0
    current_files: List[str] = []

    for line in raw.splitlines():
        if not line:
            continue
        header = _parse_commit_header(line)
        if header is not None:
            if current_sha is not None:
                commits.append((current_sha, current_ts, current_files))
            current_sha, current_ts = header
            current_files = []
        elif current_sha is not None:
            current_files.append(line)

    if current_sha is not None:
        commits.append((current_sha, current_ts, current_files))
    return commits


def _parse_commit_header(line: str) -> Optional[Tuple[str, int]]:
    parts = line.split()
    if not parts or not _looks_like_sha(parts[0]):
        return None
    timestamp = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    return parts[0], timestamp


def _looks_like_sha(value: str) -> bool:
    return len(value) == 40 and all(ch in "0123456789abcdef" for ch in value.lower())


def _norm_path(path: str) -> str:
    return path.replace("\\", "/")


def _path_parts(path: str) -> List[str]:
    return [part for part in _norm_path(path).split("/") if part]


def _basename(path: str) -> str:
    return os.path.basename(_norm_path(path))


def _stem(path: str) -> str:
    return os.path.splitext(_basename(path))[0]


def _extension(path: str) -> str:
    return os.path.splitext(_basename(path))[1].lower()


def _name_tokens(path: str) -> Set[str]:
    stem = _stem(path).lower()
    return {tok for tok in re.split(r"[^a-z0-9]+", stem) if tok}


def classify_file(path: str) -> str:
    """Classify a path using filename and directory heuristics only."""
    normalized = _norm_path(path)
    lowered = normalized.lower()
    parts = [part.lower() for part in _path_parts(normalized)]
    base = _basename(normalized)
    base_lower = base.lower()
    ext = _extension(normalized)

    if ext == ".tsbuildinfo" or base_lower.endswith(".min.js") or ext == ".map":
        return "generated"
    if any(part in GENERATED_DIRS for part in parts):
        return "generated"

    if base_lower in LOCKFILE_NAMES:
        return "dependency"

    if _is_meta_name(normalized):
        return "meta"

    if base_lower in CI_BASENAMES:
        return "ci"
    if any(
        all(marker in parts for marker in markers) for markers in CI_DIR_MARKERS
    ):
        return "ci"

    if ext == ".sql" or any(part in DB_DIR_MARKERS for part in parts):
        return "database"

    if ext == ".proto" or any(marker in lowered for marker in CONTRACT_MARKERS):
        return "api_contract"

    if _is_test_path(parts, base_lower):
        return "test"

    if ext in DOC_EXTENSIONS or "docs" in parts:
        return "documentation"

    if _is_config_path(base_lower, ext):
        return "configuration"

    if ext in SOURCE_EXTENSIONS:
        return "source"
    return "unknown"


def classify_surface(path: str) -> str:
    """Map a file onto a coarse system surface using path heuristics."""
    file_type = classify_file(path)
    parts = [part.lower() for part in _path_parts(path)]
    stem = _stem(path).lower()

    if file_type == "test":
        return "tests"
    if file_type == "ci":
        return "ci"
    if file_type == "documentation":
        return "documentation"
    if file_type == "configuration" or any(
        part in {"config", "settings"} for part in parts
    ) or "settings" in stem:
        return "configuration"
    if file_type == "dependency":
        return "dependency"
    if file_type in {"database", "api_contract"} or any(
        part in {"models", "schemas", "migrations", "database", "alembic"}
        for part in parts
    ):
        return "data_schema"

    if any(part in {"routes", "controller", "endpoints"} for part in parts):
        return "backend_api"
    if "api" in parts and any(part in {"backend", "server"} for part in parts):
        return "backend_api"

    integration_token = any(
        token in parts or token in stem for token in ("api", "client", "sdk")
    )
    frontendish = any(
        part in {"frontend", "client", "web", "lib"} for part in parts
    )
    backendish = any(part in {"backend", "server", "routes"} for part in parts)
    if integration_token and frontendish and not backendish:
        return "api_integration"

    if any(part in {"components", "pages", "frontend", "ui"} for part in parts):
        return "frontend_ui"
    if any(part in {"backend", "server", "services"} for part in parts):
        return "backend_logic"
    return "unknown"


def _current_surfaces(changed_files: Sequence[str]) -> List[str]:
    surfaces: List[str] = []
    for path in changed_files:
        surface = classify_surface(path)
        if surface not in surfaces:
            surfaces.append(surface)
    if len(surfaces) > 1:
        surfaces = [surface for surface in surfaces if surface != "unknown"]
    return surfaces


def _is_review_evidence(candidates: Sequence[Neighbor]) -> bool:
    if not candidates:
        return False
    strongest = _strongest_candidate(candidates)
    support = int(strongest["supporting_commits"])
    frequency = float(strongest.get("frequency") or 0.0)
    confidence = int(strongest.get("confidence") or 0)
    return (support >= REVIEW_MIN_SUPPORT and frequency >= REVIEW_MIN_FREQUENCY) or (
        confidence >= REVIEW_MIN_CONFIDENCE
    )


def _strongest_candidate(candidates: Sequence[Neighbor]) -> Neighbor:
    return max(
        candidates,
        key=lambda item: (
            int(item.get("confidence") or 0),
            int(item["supporting_commits"]),
            float(item.get("frequency") or 0.0),
        ),
    )


def _sorted_surface_candidates(candidates: Sequence[Neighbor]) -> List[Neighbor]:
    return sorted(
        candidates,
        key=lambda item: (
            -int(item.get("confidence") or 0),
            -int(item["supporting_commits"]),
            -float(item.get("frequency") or 0.0),
            str(item["path"]),
        ),
    )


def _surface_explanation(
    surface: str,
    status: str,
    candidates: Sequence[Neighbor],
    strongest: Optional[Neighbor],
) -> str:
    label = SURFACE_LABELS.get(surface, surface)
    if status == "covered":
        return f"Observed: the current change set already includes {label} files."
    if status == "review" and strongest is not None:
        return (
            f"Historical evidence: {len(candidates)} related {label} candidate(s). "
            f"Strongest signal: {strongest['path']}. "
            f"No {label} files are part of the current change."
        )
    return f"Insufficient evidence to determine whether {label} should participate."


def build_completeness_map(
    changed_files: Sequence[str],
    ranked: Sequence[Neighbor],
) -> Dict[str, object]:
    """Group existing V3 neighbors into COVERED / REVIEW / UNKNOWN surfaces."""
    current = set(_current_surfaces(changed_files))
    grouped: Dict[str, List[Neighbor]] = defaultdict(list)
    for neighbor in ranked:
        surface = classify_surface(str(neighbor["path"]))
        if surface == "unknown":
            continue
        grouped[surface].append(neighbor)

    included = current | set(grouped)
    surfaces: List[Dict[str, object]] = []
    for surface in SURFACE_ORDER:
        if surface not in included:
            continue
        candidates = grouped.get(surface, [])
        if surface in current:
            status = "covered"
        elif _is_review_evidence(candidates):
            status = "review"
        elif candidates:
            status = "unknown"
        else:
            status = "covered"

        ordered = _sorted_surface_candidates(candidates)
        strongest = ordered[0] if ordered else None
        representatives: List[Dict[str, object]] = []
        if status == "review":
            for item in ordered[:SURFACE_REPRESENTATIVE_CAP]:
                representatives.append(
                    {
                        "path": item["path"],
                        "supporting_commits": item["supporting_commits"],
                        "relevant_commits": item.get("relevant_commits"),
                        "frequency": item.get("frequency"),
                    }
                )
        evidence: Dict[str, object] = {}
        if strongest is not None:
            evidence = {
                "strongest_frequency": float(strongest.get("frequency") or 0.0),
                "strongest_path": strongest["path"],
                "strongest_support": int(strongest["supporting_commits"]),
                "strongest_relevant": int(strongest.get("relevant_commits") or 0),
            }
        surfaces.append(
            {
                "surface": surface,
                "status": status,
                "candidate_count": len(candidates),
                "representatives": representatives,
                "evidence": evidence,
                "explanation": _surface_explanation(
                    surface, status, candidates, strongest
                ),
            }
        )

    return {
        "surfaces": surfaces,
        "summary": {
            "review_count": sum(1 for item in surfaces if item["status"] == "review"),
            "covered_count": sum(1 for item in surfaces if item["status"] == "covered"),
            "unknown_count": sum(1 for item in surfaces if item["status"] == "unknown"),
        },
    }


def _is_meta_name(path: str) -> bool:
    """Hackathon, social, and license-style docs — not source files that mention those words."""
    ext = _extension(path)
    if ext not in DOC_EXTENSIONS and ext != "":
        return False
    tokens = _name_tokens(path)
    if tokens & META_TOKENS:
        return True
    collapsed = re.sub(r"[^a-z0-9]", "", _stem(path).lower())
    return any(token in collapsed for token in META_TOKENS if len(token) >= 5)


def _is_test_path(parts: Sequence[str], base_lower: str) -> bool:
    if any(part in TEST_DIRS for part in parts):
        return True
    if base_lower.startswith("test_"):
        return True
    if ".test." in base_lower or ".spec." in base_lower:
        return True
    stem = os.path.splitext(base_lower)[0]
    return stem.endswith("_test") or stem.endswith("_spec") or stem.endswith("-test")


def _is_config_path(base_lower: str, ext: str) -> bool:
    if ext in CONFIG_EXTENSIONS:
        return True
    if base_lower in {"dockerfile", "docker-compose.yml", "docker-compose.yaml"}:
        return True
    if base_lower.startswith(".") and "rc" in base_lower:
        return True
    if "config" in base_lower or base_lower.startswith(".env"):
        return True
    return False


def is_result_dump(path: str) -> bool:
    """True for benchmark/result artifacts that are not useful neighbors."""
    base = _basename(path).lower()
    if base == "latest.json" or base.endswith(".tsbuildinfo"):
        return True
    parts = [part.lower() for part in _path_parts(path)]
    in_dump_dir = any(part in DUMP_DIRS for part in parts)
    if not in_dump_dir:
        return False
    return base.endswith(".json") and (
        "output" in base or "result" in base or "latest" in base
    )


def should_exclude(path: str, file_type: Optional[str] = None) -> bool:
    kind = file_type if file_type is not None else classify_file(path)
    return kind in {"generated", "dependency"} or is_result_dump(path)


def class_multiplier(path: str, file_type: Optional[str] = None) -> float:
    kind = file_type if file_type is not None else classify_file(path)
    if kind == "meta":
        return 0.15
    if kind == "documentation":
        if "/" not in _norm_path(path) and _stem(path).lower().startswith("readme"):
            return 0.25
        return 0.45
    if kind == "ci":
        return 0.80
    if kind == "configuration":
        return 0.85
    if kind in {"source", "test", "database", "api_contract"}:
        return 1.0
    return 0.70


def focus_weight(file_count: int) -> float:
    """Normalized commit-size weight. A 4-file commit scores 1.0."""
    return min(1.0, FOCUS_REF / max(file_count, 1))


def recency_weight(commit_ts: int, newest_ts: int) -> float:
    """Exponential decay with a 90-day half-life, floored at 0.15."""
    age_days = max(0.0, (newest_ts - commit_ts) / SECONDS_PER_DAY)
    return max(RECENCY_FLOOR, 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS))


def commit_weight(file_count: int, commit_ts: int, newest_ts: int) -> float:
    return recency_weight(commit_ts, newest_ts) * focus_weight(file_count)


def path_proximity(left: str, right: str) -> float:
    """1.0 for the same directory; otherwise shared prefix / max depth."""
    left_dirs = _path_parts(left)[:-1]
    right_dirs = _path_parts(right)[:-1]
    if left_dirs == right_dirs:
        return 1.0
    shared = 0
    for a_part, b_part in zip(left_dirs, right_dirs):
        if a_part != b_part:
            break
        shared += 1
    max_depth = max(len(left_dirs), len(right_dirs), 1)
    return shared / max_depth


def likely_test_basenames(source_path: str) -> Set[str]:
    """Convention-based test filenames for a source path."""
    base = _basename(source_path)
    stem, ext = os.path.splitext(base)
    ext = ext.lower()
    names: Set[str] = set()
    if ext == ".py":
        names.update({f"test_{stem}.py", f"{stem}_test.py"})
        return names
    if ext in {".ts", ".tsx", ".js", ".jsx"}:
        for test_ext in (ext, ".ts", ".tsx", ".js", ".jsx"):
            names.add(f"{stem}.test{test_ext}")
            names.add(f"{stem}.spec{test_ext}")
        return names
    if ext:
        names.update(
            {
                f"{stem}.test{ext}",
                f"{stem}.spec{ext}",
                f"{stem}_test{ext}",
                f"test_{stem}{ext}",
            }
        )
    return names


def is_convention_matched_test(candidate: str, source_paths: Sequence[str]) -> bool:
    if classify_file(candidate) != "test":
        return False
    cand_base = _basename(candidate)
    cand_stem = _stem(candidate).lower()
    for source in source_paths:
        if classify_file(source) != "source":
            continue
        if cand_base in likely_test_basenames(source):
            return True
        src_stem = _stem(source).lower()
        stripped = (
            cand_stem.replace(".test", "")
            .replace(".spec", "")
            .replace("_test", "")
        )
        if cand_stem in {
            f"test_{src_stem}",
            f"{src_stem}_test",
            f"{src_stem}.test",
            f"{src_stem}.spec",
        }:
            return True
        if stripped == src_stem:
            return True
    return False


def test_boost_for(candidate: str, changed_files: Sequence[str]) -> float:
    source_files = [path for path in changed_files if classify_file(path) == "source"]
    if not source_files or classify_file(candidate) != "test":
        return 0.0
    if is_convention_matched_test(candidate, source_files):
        return 1.0
    if any(path_proximity(source, candidate) >= 0.5 for source in source_files):
        return 0.4
    return 0.0


def best_proximity(candidate: str, changed_files: Sequence[str]) -> float:
    if not changed_files:
        return 0.0
    return max(path_proximity(changed, candidate) for changed in changed_files)


def composite_confidence(
    *,
    weighted_frequency: float,
    frequency: float,
    supporting_commits: int,
    proximity: float,
    test_boost: float,
    multiplier: float,
    intent_compatibility: float = 0.0,
) -> int:
    raw = 100.0 * (
        0.42 * weighted_frequency
        + 0.16 * frequency
        + 0.10 * min(supporting_commits / 8.0, 1.0)
        + 0.10 * proximity
        + 0.08 * test_boost
        + 0.14 * intent_compatibility
    )
    return int(round(max(0.0, min(100.0, raw * multiplier))))


def assign_band(confidence: int) -> Optional[str]:
    """Map a 0-100 score onto HIGH / MEDIUM / WATCH."""
    if confidence >= HIGH_MIN_CONFIDENCE:
        return "high"
    if confidence >= MEDIUM_MIN_CONFIDENCE:
        return "medium"
    if confidence >= WATCH_MIN_CONFIDENCE:
        return "watch"
    return None


def build_explanation(candidate: Neighbor) -> Dict[str, str]:
    support = int(candidate["supporting_commits"])
    total = int(candidate["relevant_commits"])
    anchor = str(candidate["anchor"])
    evidence = f"changed with {anchor} in {support}/{total} relevant commits."
    label = str(candidate.get("intent_label") or "unknown")
    intents = [str(item) for item in candidate.get("change_intents") or []]

    weighted = float(candidate["weighted_frequency"])
    proximity = float(candidate["proximity"])
    boost = float(candidate["test_boost"])
    compat = float(candidate.get("intent_compatibility") or 0.0)
    mean_focus = float(candidate.get("mean_focus", 0.0))
    mean_recency = float(candidate.get("mean_recency", 0.0))

    if boost >= 1.0:
        signal = "likely corresponding test for the changed source file."
    elif weighted >= 0.7 and support >= 4:
        signal = "repeated strong historical co-change pattern."
    elif weighted >= 0.5 and mean_focus >= 0.5:
        signal = "usually together in small, focused commits."
    elif mean_recency >= 0.6 and weighted >= 0.4:
        signal = "recent history still shows this pairing."
    elif boost >= 0.4:
        signal = "related test in the same component as a current change."
    elif proximity >= 0.8:
        signal = "same directory or component as a current change."
    elif weighted >= 0.5:
        signal = "repeated historical co-change pattern."
    else:
        signal = "historical co-change with a current change."

    why = _why_it_matters(candidate, intents, label, compat)
    return {
        "evidence": evidence,
        "signal": signal,
        "why_it_matters": why,
        "change_intent": label,
    }


def _why_it_matters(
    candidate: Neighbor,
    intents: Sequence[str],
    label: str,
    compat: float,
) -> str:
    file_type = str(candidate.get("file_type") or "")
    path = str(candidate["path"])
    if not intents or label == "unknown":
        return "This file historically changes with the current edit."
    if "api" in intents or "backend_logic" in intents:
        if file_type == "test":
            return (
                "The current change modifies an API route and this test "
                "historically changes with related API behavior."
            )
        if "api" in path.lower() or file_type == "api_contract" or compat >= 1.0:
            return (
                "The current change modifies an API route and this file "
                "historically changes alongside API behavior."
            )
    if file_type == "test":
        return (
            f"The current change is a {label} and this test "
            "historically changes with it."
        )
    return (
        f"The current change is a {label} and this file "
        "historically changes with it."
    )


def score_neighbors(
    changed_files: Sequence[str],
    history: Sequence[CommitRecord],
    change_analysis: Optional[Sequence[ChangeAnalysis]] = None,
) -> Tuple[int, List[Neighbor]]:
    """Score forgotten neighbors with the V3 composite model.

    Returns (historical_commits_analyzed, ranked neighbor records).
    Missing change_analysis keeps intent compatibility at 0.
    """
    current_intents = collect_intents(change_analysis)
    intent_label = format_intent_label(current_intents) if current_intents else "unknown"
    changed_set = set(changed_files)
    file_to_commits: Dict[str, List[str]] = defaultdict(list)
    commit_to_files: Dict[str, Sequence[str]] = {}
    commit_to_ts: Dict[str, int] = {}

    newest_ts = 0
    for sha, timestamp, files in history:
        commit_to_files[sha] = files
        commit_to_ts[sha] = timestamp
        newest_ts = max(newest_ts, timestamp)
        for path in files:
            file_to_commits[path].append(sha)

    relevant_shas = set()
    best: Dict[str, Neighbor] = {}

    for changed in changed_files:
        shas = file_to_commits.get(changed, [])
        if not shas:
            continue
        relevant_shas.update(shas)
        total = len(shas)
        weights = []
        for sha in shas:
            files = commit_to_files[sha]
            weights.append(
                commit_weight(len(files), commit_to_ts[sha], newest_ts)
            )
        total_weight = sum(weights)
        if total_weight <= 0:
            continue

        counts: Dict[str, int] = defaultdict(int)
        weighted_sums: Dict[str, float] = defaultdict(float)
        focus_sums: Dict[str, float] = defaultdict(float)
        recency_sums: Dict[str, float] = defaultdict(float)
        for sha, weight in zip(shas, weights):
            files = commit_to_files[sha]
            focus = focus_weight(len(files))
            recency = recency_weight(commit_to_ts[sha], newest_ts)
            for other in files:
                if other == changed or other in changed_set:
                    continue
                counts[other] += 1
                weighted_sums[other] += weight
                focus_sums[other] += focus
                recency_sums[other] += recency

        for path, support in counts.items():
            file_type = classify_file(path)
            if should_exclude(path, file_type):
                continue
            frequency = support / total
            weighted_frequency = weighted_sums[path] / total_weight
            proximity = best_proximity(path, changed_files)
            boost = test_boost_for(path, changed_files)
            multiplier = class_multiplier(path, file_type)
            compatibility = intent_compatibility(path, file_type, current_intents)
            confidence = composite_confidence(
                weighted_frequency=weighted_frequency,
                frequency=frequency,
                supporting_commits=support,
                proximity=proximity,
                test_boost=boost,
                multiplier=multiplier,
                intent_compatibility=compatibility,
            )
            candidate: Neighbor = {
                "path": path,
                "file_type": file_type,
                "confidence": confidence,
                "frequency": frequency,
                "weighted_frequency": weighted_frequency,
                "supporting_commits": support,
                "relevant_commits": total,
                "proximity": proximity,
                "class_multiplier": multiplier,
                "test_boost": boost,
                "intent_compatibility": compatibility,
                "change_intents": list(current_intents),
                "intent_label": intent_label,
                "anchor": changed,
                "mean_focus": focus_sums[path] / support,
                "mean_recency": recency_sums[path] / support,
            }
            candidate["explanation"] = build_explanation(candidate)
            previous = best.get(path)
            if previous is None or _is_stronger(candidate, previous):
                best[path] = candidate

    ranked = sorted(
        (
            item
            for item in best.values()
            if int(item["confidence"]) >= WATCH_MIN_CONFIDENCE
        ),
        key=lambda item: (
            -int(item["confidence"]),
            -int(item["supporting_commits"]),
            str(item["path"]),
        ),
    )
    return len(relevant_shas), ranked


def _is_stronger(candidate: Neighbor, previous: Neighbor) -> bool:
    if int(candidate["confidence"]) != int(previous["confidence"]):
        return int(candidate["confidence"]) > int(previous["confidence"])
    if int(candidate["supporting_commits"]) != int(previous["supporting_commits"]):
        return int(candidate["supporting_commits"]) > int(
            previous["supporting_commits"]
        )
    return str(candidate["path"]) < str(previous["path"])


def bucket_neighbors(neighbors: Iterable[Neighbor]) -> NeighborBuckets:
    buckets: NeighborBuckets = {"high": [], "medium": [], "watch": []}
    for neighbor in neighbors:
        band = assign_band(int(neighbor["confidence"]))
        if not band:
            continue
        if len(buckets[band]) < BAND_CAP:
            buckets[band].append(neighbor)
    return buckets


def find_test_gaps(
    changed_files: Sequence[str],
    ranked: Sequence[Neighbor],
    change_analysis: Optional[Sequence[ChangeAnalysis]] = None,
) -> List[Neighbor]:
    """Suggest related tests only when source changed and no related test is dirty."""
    source_files = [path for path in changed_files if classify_file(path) == "source"]
    if not source_files:
        return []

    current_tests = [path for path in changed_files if classify_file(path) == "test"]
    if any(is_convention_matched_test(path, source_files) for path in current_tests):
        return []
    if any(
        path_proximity(source, test_path) >= 0.5
        for source in source_files
        for test_path in current_tests
    ):
        return []

    intents = collect_intents(change_analysis)
    api_like = any(intent in {"api", "backend_logic"} for intent in intents)
    label = format_intent_label(intents) if intents else "source"

    gaps: List[Neighbor] = []
    for candidate in ranked:
        if str(candidate.get("file_type")) != "test":
            continue
        convention = is_convention_matched_test(
            str(candidate["path"]), source_files
        )
        support = int(candidate["supporting_commits"])
        compat = float(candidate.get("intent_compatibility") or 0.0)
        accepted = support >= 2 or convention
        if not accepted and api_like and compat >= 0.5 and support >= 1:
            accepted = True
        if not accepted:
            continue
        gap = dict(candidate)
        gap["gap_reason"] = (
            f"Current {label} change. This test historically changes with "
            f"related {label} files but is not part of the current change."
        )
        gaps.append(gap)
        if len(gaps) >= TEST_GAP_CAP:
            break
    return gaps


def _render_neighbor_block(neighbor: Neighbor) -> List[str]:
    explanation = neighbor.get("explanation") or build_explanation(neighbor)
    intent = explanation.get("change_intent") or neighbor.get("intent_label") or "unknown"
    why = explanation.get("why_it_matters") or ""
    lines = [
        str(neighbor["path"]),
        "",
        f"Confidence: {int(neighbor['confidence'])}/100",
        f"Change intent detected: {intent} change",
        f"Evidence: {explanation['evidence']}",
        f"Why it matters: {why}",
    ]
    if neighbor.get("gap_reason"):
        lines.append(f"Reason: {neighbor['gap_reason']}")
    return lines


def _render_change_analysis(change_analysis: Sequence[ChangeAnalysis]) -> List[str]:
    if not change_analysis:
        return []
    lines = ["", "CHANGE ANALYSIS", ""]
    for index, item in enumerate(change_analysis):
        if index:
            lines.append("")
        lines.append(str(item.get("path")))
        lines.append("")
        lines.append("Detected intent:")
        lines.append(str(item.get("primary_label") or "unknown"))
        lines.append("")
        lines.append("Signals:")
        signals = list(item.get("signals") or [])
        if signals:
            lines.extend(f"- {signal}" for signal in signals)
        else:
            lines.append("- no strong path or diff pattern")
    return lines


def _render_completeness_map(
    completeness_map: Optional[Dict[str, object]],
) -> List[str]:
    if not completeness_map or completeness_map.get("disabled"):
        return []
    surfaces = list(completeness_map.get("surfaces") or [])
    if not surfaces:
        return []

    lines = ["", "CHANGE COMPLETENESS MAP", "", f"{'CHANGE SURFACE':<30}STATUS"]
    for item in surfaces:
        label = SURFACE_LABELS.get(str(item["surface"]), str(item["surface"]))
        lines.append(f"{label:<30}{str(item['status']).upper()}")

    for item in surfaces:
        if item["status"] != "review":
            continue
        label = SURFACE_LABELS.get(str(item["surface"]), str(item["surface"]))
        lines.extend(["", f"{label.upper()} — REVIEW", ""])
        lines.append("Evidence:")
        count = int(item.get("candidate_count") or 0)
        lines.append(f"{count} historically related candidate{'s' if count != 1 else ''}.")
        evidence = item.get("evidence") or {}
        strongest = evidence.get("strongest_path")
        if strongest:
            lines.extend(
                [
                    "",
                    "Strongest signal:",
                    str(strongest),
                    "",
                    "Historical support:",
                    f"{evidence.get('strongest_support', 0)} relevant commits.",
                ]
            )
        lines.extend(
            [
                "",
                "Current status:",
                f"No {label} files are part of the current change.",
                "",
            ]
        )
        for rep in item.get("representatives") or []:
            support = rep.get("supporting_commits")
            relevant = rep.get("relevant_commits")
            lines.append(str(rep["path"]))
            if relevant:
                lines.append(
                    f"Historical evidence: {support}/{relevant} relevant commits."
                )
            else:
                lines.append(f"Historical evidence: {support} supporting commits.")
            lines.append("")

    summary = completeness_map.get("summary") or {}
    review_count = int(summary.get("review_count") or 0)
    lines.extend(["CHANGE REVIEW SUMMARY", ""])
    if review_count:
        plural = "s" if review_count != 1 else ""
        lines.extend(
            [
                f"{review_count} related system surface{plural} are not represented "
                "in the current change set and have meaningful historical evidence.",
                "",
                "Recommended action:",
                "Inspect the highlighted areas before committing.",
            ]
        )
    else:
        lines.extend(
            [
                "No historically evidenced surfaces are absent from the current change set.",
                "This does not prove the change is complete.",
            ]
        )
    return lines


def _render_configuration(configuration: Optional[Dict[str, object]]) -> List[str]:
    if not configuration:
        return []
    include_tests = bool(configuration.get("include_tests", True))
    include_surfaces = bool(configuration.get("include_surfaces", True))
    base_ref = str(configuration.get("base_ref") or "").strip()
    lines = [
        "",
        "ANALYSIS CONFIGURATION",
        "",
        f"Repository: {configuration.get('repo_path') or 'provided path'}",
        f"History limit: {configuration.get('history_limit', DEFAULT_HISTORY_LIMIT)}",
        f"Minimum confidence: {configuration.get('min_confidence', WATCH_MIN_CONFIDENCE)}/100",
        f"Test analysis: {'Enabled' if include_tests else 'Disabled'}",
        f"Surface analysis: {'Enabled' if include_surfaces else 'Disabled'}",
        f"Baseline: {base_ref or 'Uncommitted working tree'}",
    ]
    if not include_tests:
        lines.extend(
            [
                "",
                "TEST ANALYSIS DISABLED",
                "",
                "Test-related historical neighbors were excluded for this run.",
            ]
        )
    if not include_surfaces:
        lines.extend(
            [
                "",
                "SURFACE ANALYSIS DISABLED",
                "",
                "The completeness map was not generated for this run.",
            ]
        )
    return lines


def render_text(
    changed_files: Sequence[str],
    commits_analyzed: int,
    buckets: NeighborBuckets,
    test_gap: Optional[Sequence[Neighbor]] = None,
    change_analysis: Optional[Sequence[ChangeAnalysis]] = None,
    completeness_map: Optional[Dict[str, object]] = None,
    configuration: Optional[Dict[str, object]] = None,
) -> str:
    lines = [
        "CHANGE NEIGHBOR REPORT",
        "",
        "This report surfaces historical neighbors that may deserve review.",
        "It does not claim that any file is required or that the change is incomplete.",
    ]
    lines.extend(_render_configuration(configuration))
    lines.extend(
        [
            "",
            "CURRENT CHANGES",
            "",
        ]
    )
    if changed_files:
        lines.extend(f"- {path}" for path in changed_files)
    else:
        lines.append("- None")

    lines.extend(_render_change_analysis(change_analysis or []))
    lines.extend(_render_completeness_map(completeness_map))

    lines.extend(
        [
            "",
            "Historical commits analyzed:",
            f"- {commits_analyzed}",
            "",
            "Likely forgotten neighbors:",
            "",
        ]
    )

    for heading, key in (
        ("HIGH CONFIDENCE", "high"),
        ("MEDIUM CONFIDENCE", "medium"),
        ("WATCH LIST", "watch"),
    ):
        lines.append(heading)
        items = buckets.get(key, [])
        if not items:
            lines.append("None")
        else:
            for index, neighbor in enumerate(items):
                if index:
                    lines.append("")
                lines.extend(_render_neighbor_block(neighbor))
        lines.append("")

    if test_gap:
        lines.append("POSSIBLE TEST GAP")
        for index, neighbor in enumerate(test_gap):
            if index:
                lines.append("")
            lines.extend(_render_neighbor_block(neighbor))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_json(
    changed_files: Sequence[str],
    commits_analyzed: int,
    buckets: NeighborBuckets,
    test_gap: Optional[Sequence[Neighbor]] = None,
    candidates: Optional[Sequence[Neighbor]] = None,
    change_analysis: Optional[Sequence[ChangeAnalysis]] = None,
    completeness_map: Optional[Dict[str, object]] = None,
    configuration: Optional[Dict[str, object]] = None,
) -> str:
    payload = {
        "configuration": configuration or {},
        "current_changes": list(changed_files),
        "change_analysis": [
            {
                "path": item.get("path"),
                "intents": list(item.get("intents") or []),
                "signals": list(item.get("signals") or []),
            }
            for item in (change_analysis or [])
        ],
        "completeness_map": completeness_map
        or {"surfaces": [], "summary": {"review_count": 0, "covered_count": 0, "unknown_count": 0}},
        "historical_commits_analyzed": commits_analyzed,
        "likely_forgotten_neighbors": {
            "high": [_json_neighbor(item) for item in buckets.get("high", [])],
            "medium": [_json_neighbor(item) for item in buckets.get("medium", [])],
            "watch": [_json_neighbor(item) for item in buckets.get("watch", [])],
        },
        "possible_test_gap": [_json_neighbor(item) for item in (test_gap or [])],
        "candidates": [
            _json_neighbor(item) for item in (candidates or [])[:JSON_CANDIDATE_CAP]
        ],
    }
    return json.dumps(payload, indent=2) + "\n"


def _json_neighbor(neighbor: Neighbor) -> Dict[str, object]:
    explanation = neighbor.get("explanation") or build_explanation(neighbor)
    payload = {
        "path": neighbor["path"],
        "file_type": neighbor.get("file_type"),
        "confidence": neighbor.get("confidence"),
        "frequency": neighbor.get("frequency"),
        "weighted_frequency": neighbor.get("weighted_frequency"),
        "supporting_commits": neighbor["supporting_commits"],
        "relevant_commits": neighbor.get("relevant_commits"),
        "proximity": neighbor.get("proximity"),
        "class_multiplier": neighbor.get("class_multiplier"),
        "test_boost": neighbor.get("test_boost"),
        "intent_compatibility": neighbor.get("intent_compatibility", 0.0),
        "anchor": neighbor.get("anchor"),
        "explanation": explanation,
    }
    if neighbor.get("gap_reason"):
        payload["reason"] = neighbor["gap_reason"]
    return payload


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze uncommitted Git changes against repository history "
            "and suggest the files a developer is most likely forgetting."
        )
    )
    parser.add_argument(
        "--repo",
        required=True,
        help="Path to a local Git repository (working tree).",
    )
    parser.add_argument(
        "--history-limit",
        default=DEFAULT_HISTORY_LIMIT,
        help="Maximum number of historical commits to inspect (5-500, default 50).",
    )
    parser.add_argument(
        "--min-confidence",
        default=WATCH_MIN_CONFIDENCE,
        help="Minimum confidence for recommended neighbors (0-100, default 25).",
    )
    parser.add_argument(
        "--include-tests",
        default="true",
        help="Include historically related tests (true/false, default true).",
    )
    parser.add_argument(
        "--include-surfaces",
        default="true",
        help="Build the change completeness map (true/false, default true).",
    )
    parser.add_argument(
        "--base-ref",
        default="",
        help="Optional Git baseline. Leave empty to analyze uncommitted changes.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the report as JSON instead of text.",
    )
    return parser.parse_args(argv)


def analyze_repo(
    repo: str,
    *,
    history_limit: int = DEFAULT_HISTORY_LIMIT,
    min_confidence: int = WATCH_MIN_CONFIDENCE,
    include_tests: bool = True,
    include_surfaces: bool = True,
    base_ref: str = "",
) -> Dict[str, object]:
    history_limit = parse_bounded_int(
        history_limit,
        name="history_limit",
        minimum=HISTORY_LIMIT_MIN,
        maximum=HISTORY_LIMIT_MAX,
    )
    min_confidence = parse_bounded_int(
        min_confidence,
        name="min_confidence",
        minimum=0,
        maximum=100,
    )
    include_tests = parse_bool(include_tests)
    include_surfaces = parse_bool(include_surfaces)
    resolved_ref = resolve_base_ref(repo, base_ref)
    configuration = {
        "repo_path": repo,
        "history_limit": history_limit,
        "min_confidence": min_confidence,
        "include_tests": include_tests,
        "include_surfaces": include_surfaces,
        "base_ref": resolved_ref,
    }

    changed_files = get_changed_files(repo, resolved_ref)
    empty_buckets: NeighborBuckets = {"high": [], "medium": [], "watch": []}
    if not changed_files:
        return {
            "changed_files": [],
            "commits_analyzed": 0,
            "buckets": empty_buckets,
            "test_gap": [],
            "candidates": [],
            "change_analysis": [],
            "completeness_map": empty_completeness_map(disabled=not include_surfaces),
            "configuration": configuration,
        }

    change_analysis = get_change_analysis(repo, changed_files, resolved_ref)
    history = load_history(repo, history_limit)
    commits_analyzed, ranked = score_neighbors(
        changed_files, history, change_analysis
    )
    evidence = ranked if include_tests else filter_test_neighbors(ranked)
    display = filter_neighbors_by_confidence(evidence, min_confidence)
    if include_surfaces:
        map_changed = (
            changed_files
            if include_tests
            else [path for path in changed_files if not is_test_path(path)]
        )
        completeness_map = build_completeness_map(map_changed, evidence)
    else:
        completeness_map = empty_completeness_map(disabled=True)
    return {
        "changed_files": changed_files,
        "commits_analyzed": commits_analyzed,
        "buckets": bucket_neighbors(display),
        "test_gap": (
            find_test_gaps(changed_files, evidence, change_analysis)
            if include_tests
            else []
        ),
        "candidates": evidence[:JSON_CANDIDATE_CAP],
        "change_analysis": change_analysis,
        "completeness_map": completeness_map,
        "configuration": configuration,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        repo = validate_repo(args.repo)
        result = analyze_repo(
            repo,
            history_limit=args.history_limit,
            min_confidence=args.min_confidence,
            include_tests=args.include_tests,
            include_surfaces=args.include_surfaces,
            base_ref=args.base_ref,
        )
    except ChangeNeighborError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    changed_files = result["changed_files"]
    commits_analyzed = int(result["commits_analyzed"])
    buckets = result["buckets"]
    test_gap = result["test_gap"]
    candidates = result["candidates"]
    change_analysis = result.get("change_analysis") or []
    completeness_map = result.get("completeness_map") or empty_completeness_map()
    configuration = result.get("configuration") or {}

    if args.json:
        sys.stdout.write(
            render_json(
                changed_files,
                commits_analyzed,
                buckets,
                test_gap,
                candidates,
                change_analysis,
                completeness_map,
                configuration,
            )
        )
    else:
        sys.stdout.write(
            render_text(
                changed_files,
                commits_analyzed,
                buckets,
                test_gap,
                change_analysis,
                completeness_map,
                configuration,
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
