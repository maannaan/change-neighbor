#!/usr/bin/env -S rote play run
/**
 * Change Neighbor
 *
 * Analyze uncommitted Git changes against repository history and surface files,
 * tests, and implementation surfaces that historically change together.
 * Evidence-based recommendations help reviewers inspect likely neighbors before
 * committing without claiming that any file is required.
 *
 * Safety: reads Git metadata, diffs, and commit history only. Does not modify
 * the target repository, create commits, run repository code, install
 * dependencies, make network calls, or push to remotes.
 *
 * @rote-frontmatter
 * ---
 * name: change-neighbor
 * source: https://github.com/maannaan/change-neighbor
 * description: "Analyze uncommitted Git changes against repository history to discover files, tests, and system surfaces that historically change together. Change Neighbor helps developers review likely implementation neighbors before committing, using configurable historical evidence and confidence thresholds. All analysis runs locally and read-only; it never modifies the repository, executes project code, installs dependencies, or makes network calls."
 * metadata:
 *   rote_version: 0.80.0
 *   version: 0.1.1
 *   status: draft
 *   kind: atomic
 *   flow_type: sequential
 *   execution_model: steps_with_presentation
 *   format: typescript
 *   requires_endpoints: []
 *   requires_sessions: false
 *   contract:
 *     atomic: true
 *     input:
 *       type: none
 *     output:
 *       format: json
 *       destination: stdout
 *     composable: true
 *   discoverability:
 *     tags:
 *     - git
 *     - code-review
 *     - developer-tools
 *     - repository-analysis
 *     - testing
 *     - software-engineering
 *     - effect-read-only
 * tags:
 * - git
 * - code-review
 * - developer-tools
 * - repository-analysis
 * - testing
 * - software-engineering
 * - effect-read-only
 * parameters:
 * - name: repo_path
 *   param_type: string
 *   required: true
 *   description: Absolute path to the Git repository to analyze.
 * - name: history_limit
 *   param_type: integer
 *   required: false
 *   default: 50
 *   description: Maximum number of historical commits to analyze. Larger values provide broader historical evidence but may take longer.
 * - name: min_confidence
 *   param_type: integer
 *   required: false
 *   default: 25
 *   description: Minimum confidence score required for a historical neighbor to appear in recommendations.
 * - name: include_tests
 *   param_type: boolean
 *   required: false
 *   default: true
 *   description: Include historically related tests and potential test coverage gaps.
 * - name: include_surfaces
 *   param_type: boolean
 *   required: false
 *   default: true
 *   description: Analyze related system surfaces such as API integration, frontend UI, backend logic, tests, and schema.
 * - name: base_ref
 *   param_type: string
 *   required: false
 *   default: ""
 *   description: Optional Git reference to use as a comparison baseline. Leave empty to analyze uncommitted changes.
 * steps:
 *   analyze:
 *     type: process.exec
 *     timeout_ms: 120000
 *     argv:
 *     - python3
 *     - '@resource{change_neighbor.py}'
 *     - --repo
 *     - $repo_path
 *     - --history-limit
 *     - $history_limit
 *     - --min-confidence
 *     - $min_confidence
 *     - --include-tests
 *     - $include_tests
 *     - --include-surfaces
 *     - $include_surfaces
 *     - --base-ref
 *     - $base_ref
 *     - --json
 * presentation_fixtures:
 *   analyze: resources/presentation-fixtures/analyze/fixture.yaml
 * ---
 */

const presentationSdk = await import("__ROTE_PRESENTATION_SDK__").catch((cause) => {
  throw new Error(
    "This is a rote steps presentation program. Run it with `rote play run play/main.ts`.",
    { cause },
  );
});

const { FlowOutput, isProcessExecBody, loadPresentationContext, stepName } =
  presentationSdk;

const out = new FlowOutput();
const ctx = await loadPresentationContext();

type Neighbor = {
  path?: string;
  confidence?: number;
  supporting_commits?: number;
  relevant_commits?: number;
  frequency?: number;
  file_type?: string;
  explanation?: {
    evidence?: string;
    why_it_matters?: string;
    change_intent?: string;
  };
};

type Surface = {
  surface?: string;
  status?: string;
  candidate_count?: number;
  representatives?: Array<{
    path?: string;
    supporting_commits?: number;
    relevant_commits?: number;
  }>;
  evidence?: {
    strongest_path?: string;
    strongest_support?: number;
    strongest_relevant?: number;
  };
};

type EngineConfiguration = {
  repo_path?: string;
  history_limit?: number;
  min_confidence?: number;
  include_tests?: boolean;
  include_surfaces?: boolean;
  base_ref?: string;
};

type EngineReport = {
  configuration?: EngineConfiguration;
  current_changes?: string[];
  change_analysis?: Array<{
    path?: string;
    intents?: string[];
    signals?: string[];
  }>;
  historical_commits_analyzed?: number;
  likely_forgotten_neighbors?: {
    high?: Neighbor[];
    medium?: Neighbor[];
    watch?: Neighbor[];
  };
  possible_test_gap?: Neighbor[];
  completeness_map?: {
    surfaces?: Surface[];
    disabled?: boolean;
    summary?: {
      review_count?: number;
      covered_count?: number;
      unknown_count?: number;
    };
  };
};

const INTENT_LABELS: Record<string, string> = {
  api: "API / backend route",
  database: "database / schema",
  authentication: "authentication",
  frontend_ui: "frontend UI",
  backend_logic: "backend logic",
  configuration: "configuration",
  dependency: "dependency",
  test: "test",
  documentation: "documentation",
  ci: "CI / workflow",
  unknown: "unknown",
};

function formatIntentLabel(intents: string[]): string {
  if (intents.includes("api")) {
    return INTENT_LABELS.api;
  }
  const labels: string[] = [];
  for (const intent of intents) {
    const label = INTENT_LABELS[intent] ?? intent;
    if (!labels.includes(label)) {
      labels.push(label);
    }
  }
  return labels.join(" / ") || INTENT_LABELS.unknown;
}

const SURFACE_LABELS: Record<string, string> = {
  backend_api: "Backend API",
  api_integration: "API Integration",
  frontend_ui: "Frontend UI",
  backend_logic: "Backend Logic",
  tests: "Tests",
  data_schema: "Data / Schema",
  configuration: "Configuration",
  ci: "CI",
  documentation: "Documentation",
  dependency: "Dependency",
  unknown: "Unknown",
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function emitFailure(message: string, extra?: Record<string, unknown>): void {
  out.human(
    [
      "CHANGE NEIGHBOR",
      "",
      "Analysis could not finish.",
      message,
      "",
      "The Play only reads Git metadata, diffs, and history. It does not modify the repository.",
    ].join("\n"),
  );
  out.summary(`Change Neighbor could not analyze the repository: ${message}`);
  out.result({
    ok: false,
    tool_version: "4",
    error: message,
    ...(extra ?? {}),
  });
}

function present(): void {
const analyzeStep = ctx.step(stepName("analyze"));
const outcome = analyzeStep.outcome;
if (outcome.status === "blocked") {
  emitFailure("Analyze was blocked by an upstream step and did not run. The neighbor report is unavailable.");
  return;
}
if (outcome.status === "skipped") {
  emitFailure("Analyze did not run (skipped). The neighbor report is unavailable.");
  return;
}
if (outcome.status === "failed") {
  emitFailure(`Analyze failed: ${outcome.output.message}`);
  return;
}

const analyze = outcome.output;
if (!isProcessExecBody(analyze.body)) {
  // Lint without a fixture supplies an opaque body. Do not invent neighbors.
  emitFailure("The analyze step did not record a process.exec observation.");
  return;
}

const exit = analyze.body.status.exit;
if (exit.kind !== "code") {
  emitFailure("The analyze process did not exit with a status code.");
  return;
}
if (exit.code !== 0) {
  const stderr = analyze.body.stderr?.text?.trim() || "no stderr captured";
  emitFailure(stderr, { exit_code: exit.code });
  return;
}

const stdout = analyze.body.stdout?.text;
const stdoutTruncated = analyze.body.stdout?.truncated === true;
if (typeof stdout !== "string" || !stdout.trim()) {
  emitFailure("The analyze step captured no JSON stdout.");
  return;
}
if (stdoutTruncated) {
  emitFailure(
    "Analyze stdout was truncated; the neighbor report is partial and was not scored.",
    { truncated: true },
  );
  return;
}

let report: EngineReport;
try {
  const parsed = JSON.parse(stdout) as unknown;
  const record = asRecord(parsed);
  if (!record) {
    throw new Error("stdout was not a JSON object");
  }
  report = parsed as EngineReport;
} catch (error) {
  emitFailure(
    `Analyze output was not valid JSON: ${error instanceof Error ? error.message : String(error)}`,
  );
  return;
}

const currentChanges = Array.isArray(report.current_changes) ? report.current_changes : [];
const analysis = Array.isArray(report.change_analysis) ? report.change_analysis : [];
const neighbors = report.likely_forgotten_neighbors ?? {};
const high = Array.isArray(neighbors.high) ? neighbors.high : [];
const medium = Array.isArray(neighbors.medium) ? neighbors.medium : [];
const watch = Array.isArray(neighbors.watch) ? neighbors.watch : [];
const gaps = Array.isArray(report.possible_test_gap) ? report.possible_test_gap : [];
const map = report.completeness_map ?? {};
const surfaces = Array.isArray(map.surfaces) ? map.surfaces : [];
const reviewCount = Number(map.summary?.review_count ?? 0);
const commits = Number(report.historical_commits_analyzed ?? 0);
const config = report.configuration ?? {};
const includeTests = config.include_tests !== false;
const includeSurfaces = config.include_surfaces !== false && map.disabled !== true;
const historyLimit = Number(config.history_limit ?? ctx.params.history_limit ?? 50);
const minConfidence = Number(config.min_confidence ?? ctx.params.min_confidence ?? 25);
const displayedRepo = String(config.repo_path ?? ctx.params.repo_path ?? "provided path");
const baseRef = String(config.base_ref ?? ctx.params.base_ref ?? "").trim();

function neighborBlock(item: Neighbor): string[] {
  const path = String(item.path ?? "unknown path");
  const confidence = item.confidence != null ? `${item.confidence}/100` : "n/a";
  const intent = item.explanation?.change_intent ?? "unknown";
  const evidence = item.explanation?.evidence ??
    "historical co-change evidence is available for this path.";
  const why = item.explanation?.why_it_matters ??
    "This file historically changes alongside the current edit and may deserve review.";
  return [
    path,
    "",
    `Confidence: ${confidence}`,
    `Change intent detected: ${intent}`,
    `Evidence: ${evidence}`,
    `Why it matters: ${why}`,
  ];
}

function band(title: string, items: Neighbor[]): string[] {
  const lines = [title];
  if (!items.length) {
    lines.push("None");
    return lines;
  }
  items.forEach((item, index) => {
    if (index) lines.push("");
    lines.push(...neighborBlock(item));
  });
  return lines;
}

const lines: string[] = [
  "CHANGE NEIGHBOR REPORT",
  "",
  "This Play surfaces historical neighbors that may deserve review before committing.",
  "It does not claim that any file is required or that the change is incomplete.",
  "",
  "ANALYSIS CONFIGURATION",
  "",
  `Repository: ${displayedRepo}`,
  `History limit: ${historyLimit}`,
  `Minimum confidence: ${minConfidence}/100`,
  `Test analysis: ${includeTests ? "Enabled" : "Disabled"}`,
  `Surface analysis: ${includeSurfaces ? "Enabled" : "Disabled"}`,
  `Baseline: ${baseRef || "Uncommitted working tree"}`,
];
if (!includeTests) {
  lines.push(
    "",
    "TEST ANALYSIS DISABLED",
    "",
    "Test-related historical neighbors were excluded for this run.",
  );
}
if (!includeSurfaces) {
  lines.push(
    "",
    "SURFACE ANALYSIS DISABLED",
    "",
    "The completeness map was not generated for this run.",
  );
}
lines.push("", "CURRENT CHANGES", "");
if (currentChanges.length) {
  lines.push(...currentChanges.map((path) => `- ${path}`));
} else {
  lines.push("- None");
}

if (analysis.length) {
  lines.push("", "CHANGE ANALYSIS", "");
  analysis.forEach((item, index) => {
    if (index) lines.push("");
    lines.push(String(item.path ?? "unknown path"), "");
    const intents = Array.isArray(item.intents)
      ? formatIntentLabel(item.intents)
      : "unknown";
    lines.push("Detected intent:", intents, "");
    lines.push("Signals:");
    const signals = Array.isArray(item.signals) && item.signals.length
      ? item.signals
      : ["no strong path or diff pattern"];
    lines.push(...signals.map((signal) => `- ${signal}`));
  });
}

if (includeSurfaces && surfaces.length) {
  lines.push("", "CHANGE COMPLETENESS MAP", "", `${"CHANGE SURFACE".padEnd(30)}STATUS`);
  for (const surface of surfaces) {
    const label = SURFACE_LABELS[String(surface.surface)] ?? String(surface.surface);
    lines.push(`${label.padEnd(30)}${String(surface.status ?? "unknown").toUpperCase()}`);
  }
  for (const surface of surfaces) {
    if (surface.status !== "review") continue;
    const label = SURFACE_LABELS[String(surface.surface)] ?? String(surface.surface);
    lines.push("", `${label.toUpperCase()} — REVIEW`, "");
    lines.push("Evidence:");
    const count = Number(surface.candidate_count ?? 0);
    lines.push(`${count} historically related candidate${count === 1 ? "" : "s"}.`);
    const strongest = surface.evidence?.strongest_path;
    if (strongest) {
      lines.push(
        "",
        "Strongest signal:",
        strongest,
        "",
        "Historical support:",
        `${surface.evidence?.strongest_support ?? 0} relevant commits.`,
      );
    }
    lines.push(
      "",
      "Current status:",
      `No ${label} files are part of the current change.`,
      "",
    );
    for (const rep of surface.representatives ?? []) {
      const support = rep.supporting_commits;
      const relevant = rep.relevant_commits;
      lines.push(String(rep.path ?? "unknown path"));
      if (relevant != null) {
        lines.push(`Historical evidence: ${support}/${relevant} relevant commits.`);
      } else {
        lines.push(`Historical evidence: ${support} supporting commits.`);
      }
      lines.push("");
    }
  }
  lines.push("CHANGE REVIEW SUMMARY", "");
  if (reviewCount > 0) {
    lines.push(
      `${reviewCount} related system surface${reviewCount === 1 ? "" : "s"} are not represented in the current change set and have meaningful historical evidence.`,
      "",
      "Recommended action:",
      "Inspect the highlighted areas before committing.",
    );
  } else {
    lines.push(
      "No historically evidenced surfaces are absent from the current change set.",
      "This does not prove the change is complete.",
    );
  }
}

lines.push(
  "",
  "Historical commits analyzed:",
  `- ${commits}`,
  "",
  "Likely forgotten neighbors:",
  "",
);
lines.push(...band("HIGH CONFIDENCE", high), "");
lines.push(...band("MEDIUM CONFIDENCE", medium), "");
lines.push(...band("WATCH LIST", watch), "");

if (includeTests && gaps.length) {
  lines.push("POSSIBLE TEST GAP");
  gaps.forEach((item, index) => {
    if (index) lines.push("");
    lines.push(...neighborBlock(item));
  });
  lines.push("");
}

out.human(lines.join("\n").trimEnd() + "\n");

const topNeighbor = high[0]?.path ?? medium[0]?.path ?? "none";
out.summary(
  currentChanges.length === 0
    ? "No uncommitted changes; nothing to review."
    : `${currentChanges.length} current change(s), ${reviewCount} surface(s) may deserve review. Strongest historical neighbor: ${topNeighbor}.`,
);

out.result({
  ok: true,
  tool_version: "4",
  run_id: ctx.run.run_id,
  repo_path: ctx.params.repo_path,
  configuration: {
    repo_path: displayedRepo,
    history_limit: historyLimit,
    min_confidence: minConfidence,
    include_tests: includeTests,
    include_surfaces: includeSurfaces,
    base_ref: baseRef,
  },
  current_changes: currentChanges,
  change_analysis: analysis,
  historical_commits_analyzed: commits,
  likely_forgotten_neighbors: {
    high,
    medium,
    watch,
  },
  possible_test_gap: gaps,
  completeness_map: map,
});
}

present();

