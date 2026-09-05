#!/usr/bin/env python3
"""Unit tests for Change Neighbor V2 scoring (stdlib only, no real Git repo)."""

from __future__ import annotations

import json
import os
import sys
import unittest


SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

import change_neighbor as cn  # noqa: E402


def _sha(n: int) -> str:
    return f"{n:040x}"


def _commit(n: int, files: list, days_ago: int = 0, newest_ts: int = 1_700_000_000):
    timestamp = newest_ts - days_ago * 86400
    return (_sha(n), timestamp, files)


class ClassifyFileTests(unittest.TestCase):
    def test_source_and_test_conventions(self):
        self.assertEqual(cn.classify_file("src/foo.py"), "source")
        self.assertEqual(cn.classify_file("frontend/lib/api.ts"), "source")
        self.assertEqual(cn.classify_file("tests/test_foo.py"), "test")
        self.assertEqual(cn.classify_file("foo.test.ts"), "test")
        self.assertEqual(cn.classify_file("foo.spec.tsx"), "test")
        self.assertEqual(cn.classify_file("backend/tests/test_api.py"), "test")

    def test_noisy_and_infra_classes(self):
        self.assertEqual(cn.classify_file("package-lock.json"), "dependency")
        self.assertEqual(cn.classify_file("frontend/tsconfig.tsbuildinfo"), "generated")
        self.assertEqual(cn.classify_file("JUDGES.md"), "meta")
        self.assertEqual(cn.classify_file("SUBMISSION.md"), "meta")
        self.assertEqual(cn.classify_file("LINKEDIN_POST.md"), "meta")
        self.assertEqual(cn.classify_file("PRIZE_TRACKS.md"), "meta")
        self.assertEqual(cn.classify_file("CHANGELOG.md"), "meta")
        self.assertEqual(cn.classify_file("README.md"), "documentation")
        self.assertEqual(cn.classify_file("docs/guide.md"), "documentation")
        self.assertEqual(cn.classify_file(".github/workflows/ci.yml"), "ci")
        self.assertEqual(cn.classify_file("tsconfig.json"), "configuration")
        self.assertEqual(cn.classify_file("alembic/versions/001_init.sql"), "database")
        self.assertEqual(cn.classify_file("openapi/schema.yaml"), "api_contract")

    def test_source_named_twitter_is_not_meta(self):
        self.assertEqual(cn.classify_file("src/twitter_client.py"), "source")


class ExcludeAndPenaltyTests(unittest.TestCase):
    def test_excludes_lockfiles_generated_and_dumps(self):
        self.assertTrue(cn.should_exclude("package-lock.json"))
        self.assertTrue(cn.should_exclude("frontend/tsconfig.tsbuildinfo"))
        self.assertTrue(cn.should_exclude("latest.json"))
        self.assertTrue(cn.should_exclude("collectors/demo_run_output.json"))
        self.assertFalse(cn.should_exclude("frontend/lib/api.ts"))

    def test_meta_is_penalized_more_than_source(self):
        self.assertLess(cn.class_multiplier("JUDGES.md"), 0.2)
        self.assertLess(cn.class_multiplier("README.md"), 0.3)
        self.assertEqual(cn.class_multiplier("frontend/lib/api.ts"), 1.0)


class WeightTests(unittest.TestCase):
    def test_small_commit_outweighs_large_commit(self):
        self.assertGreater(cn.focus_weight(3), cn.focus_weight(40))
        self.assertAlmostEqual(cn.focus_weight(4), 1.0)
        self.assertAlmostEqual(cn.focus_weight(40), 0.1)

    def test_recency_decays_with_age(self):
        newest = 1_700_000_000
        recent = cn.recency_weight(newest, newest)
        half_year = cn.recency_weight(newest - 180 * 86400, newest)
        self.assertGreater(recent, half_year)
        self.assertGreaterEqual(half_year, cn.RECENCY_FLOOR)
        self.assertAlmostEqual(recent, 1.0)


class ProximityAndTestNameTests(unittest.TestCase):
    def test_same_directory_is_closer_than_other_tree(self):
        same = cn.path_proximity("frontend/lib/api.ts", "frontend/lib/docs.ts")
        nearby = cn.path_proximity("frontend/lib/api.ts", "frontend/app/page.tsx")
        distant = cn.path_proximity("frontend/lib/api.ts", "backend/app/main.py")
        self.assertEqual(same, 1.0)
        self.assertGreater(same, nearby)
        self.assertGreater(nearby, distant)

    def test_likely_test_names(self):
        self.assertIn("test_foo.py", cn.likely_test_basenames("src/foo.py"))
        self.assertIn("foo.test.ts", cn.likely_test_basenames("foo.ts"))
        self.assertIn("foo.spec.ts", cn.likely_test_basenames("foo.ts"))
        self.assertTrue(
            cn.is_convention_matched_test("tests/test_foo.py", ["src/foo.py"])
        )
        self.assertFalse(
            cn.is_convention_matched_test("tests/test_bar.py", ["src/foo.py"])
        )


class ScoringTests(unittest.TestCase):
    def test_strong_cochange_outranks_lockfile_and_meta(self):
        newest = 1_700_000_000
        history = []
        for i in range(1, 9):
            history.append(
                _commit(
                    i,
                    ["frontend/app/page.tsx", "frontend/lib/api.ts"],
                    days_ago=i,
                    newest_ts=newest,
                )
            )
        history.append(
            _commit(
                20,
                ["frontend/app/page.tsx", "package-lock.json", "JUDGES.md", "README.md"]
                + [f"noise/{i}.txt" for i in range(36)],
                days_ago=10,
                newest_ts=newest,
            )
        )

        _count, ranked = cn.score_neighbors(["frontend/app/page.tsx"], history)
        paths = [item["path"] for item in ranked]
        self.assertIn("frontend/lib/api.ts", paths)
        self.assertNotIn("package-lock.json", paths)
        self.assertNotIn("JUDGES.md", paths)

        api = next(item for item in ranked if item["path"] == "frontend/lib/api.ts")
        self.assertGreaterEqual(api["confidence"], 70)
        self.assertEqual(api["supporting_commits"], 8)
        self.assertEqual(cn.assign_band(api["confidence"]), "high")

    def test_focused_recent_commit_beats_old_large_commit(self):
        newest = 1_700_000_000
        history = [
            _commit(
                1,
                ["src/app.py", "tests/test_app.py"],
                days_ago=1,
                newest_ts=newest,
            ),
            _commit(
                2,
                ["src/app.py", "old/unrelated.py"] + [f"bulk/{i}.py" for i in range(38)],
                days_ago=400,
                newest_ts=newest,
            ),
        ]
        _count, ranked = cn.score_neighbors(["src/app.py"], history)
        by_path = {item["path"]: item for item in ranked}
        self.assertIn("tests/test_app.py", by_path)
        self.assertGreater(
            by_path["tests/test_app.py"]["weighted_frequency"],
            by_path.get("old/unrelated.py", {}).get("weighted_frequency", 0),
        )
        self.assertGreater(by_path["tests/test_app.py"]["test_boost"], 0)

    def test_band_caps_and_watch_floor(self):
        neighbors = []
        for i in range(8):
            neighbors.append({"path": f"high/{i}.py", "confidence": 90 - i})
        for i in range(8):
            neighbors.append({"path": f"med/{i}.py", "confidence": 50})
        neighbors.append({"path": "weak.py", "confidence": 10})
        buckets = cn.bucket_neighbors(neighbors)
        self.assertEqual(len(buckets["high"]), 5)
        self.assertEqual(len(buckets["medium"]), 5)
        self.assertEqual(len(buckets["watch"]), 0)
        self.assertIsNone(cn.assign_band(10))
        self.assertEqual(cn.assign_band(30), "watch")

    def test_test_gap_requires_evidence_and_missing_test(self):
        ranked = [
            {
                "path": "tests/test_foo.py",
                "file_type": "test",
                "supporting_commits": 3,
                "relevant_commits": 4,
                "weighted_frequency": 0.8,
                "frequency": 0.75,
                "proximity": 0.6,
                "test_boost": 1.0,
                "anchor": "src/foo.py",
                "confidence": 80,
            }
        ]
        gaps = cn.find_test_gaps(["src/foo.py"], ranked)
        self.assertEqual(len(gaps), 1)

        already_testing = cn.find_test_gaps(
            ["src/foo.py", "tests/test_foo.py"], ranked
        )
        self.assertEqual(already_testing, [])

        no_source = cn.find_test_gaps(["README.md"], ranked)
        self.assertEqual(no_source, [])

        weak = [
            {
                "path": "tests/test_other.py",
                "file_type": "test",
                "supporting_commits": 1,
                "relevant_commits": 4,
                "weighted_frequency": 0.2,
                "frequency": 0.25,
                "proximity": 0.0,
                "test_boost": 0.0,
                "anchor": "src/foo.py",
                "confidence": 30,
            }
        ]
        self.assertEqual(cn.find_test_gaps(["src/foo.py"], weak), [])


class IntentTests(unittest.TestCase):
    def test_path_only_route_is_api_and_backend(self):
        analysis = cn.analyze_change("backend/app/routes/demo.py", "")
        self.assertIn("api", analysis["intents"])
        self.assertIn("backend_logic", analysis["intents"])
        self.assertEqual(analysis["primary_label"], "API / backend route")
        self.assertTrue(
            any("route-related" in signal for signal in analysis["signals"])
        )

    def test_diff_only_http_route(self):
        diff = (
            "--- a/src/service.py\n"
            "+++ b/src/service.py\n"
            "@@ -1,2 +1,3 @@\n"
            " existing\n"
            "+@app.route(\"/items\", methods=[\"GET\"])\n"
            "+def list_items():\n"
            "+    return []\n"
        )
        analysis = cn.analyze_change("src/service.py", diff)
        self.assertIn("api", analysis["intents"])
        self.assertTrue(
            any("HTTP route" in signal for signal in analysis["signals"])
        )

    def test_sql_diff_is_database(self):
        diff = "+CREATE TABLE users (id INTEGER);\n"
        analysis = cn.analyze_change("db/001.sql", diff)
        self.assertIn("database", analysis["intents"])

    def test_empty_unknown_file_is_unknown(self):
        analysis = cn.analyze_change("notes/scratch.bin", "")
        self.assertEqual(analysis["intents"], ["unknown"])

    def test_api_client_more_compatible_than_random_source(self):
        intents = ["api", "backend_logic"]
        api_client = cn.intent_compatibility(
            "frontend/lib/api.ts", "source", intents
        )
        random_source = cn.intent_compatibility(
            "backend/app/services/metrics.py", "source", intents
        )
        self.assertEqual(api_client, 1.0)
        self.assertLess(random_source, api_client)

    def test_intent_boosts_compatible_neighbor(self):
        newest = 1_700_000_000
        history = [
            _commit(
                1,
                [
                    "backend/app/routes/demo.py",
                    "frontend/lib/api.ts",
                    "scripts/other.py",
                ],
                days_ago=1,
                newest_ts=newest,
            )
        ]
        analysis = [
            {
                "path": "backend/app/routes/demo.py",
                "intents": ["api", "backend_logic"],
                "signals": ["route-related file path"],
                "primary_label": "API / backend route",
            }
        ]
        _count, ranked = cn.score_neighbors(
            ["backend/app/routes/demo.py"], history, analysis
        )
        by_path = {item["path"]: item for item in ranked}
        self.assertIn("frontend/lib/api.ts", by_path)
        self.assertGreater(
            by_path["frontend/lib/api.ts"]["intent_compatibility"],
            by_path["scripts/other.py"]["intent_compatibility"],
        )
        self.assertGreater(
            by_path["frontend/lib/api.ts"]["confidence"],
            by_path["scripts/other.py"]["confidence"],
        )

    def test_api_test_gap_uses_intent(self):
        ranked = [
            {
                "path": "backend/tests/test_api.py",
                "file_type": "test",
                "supporting_commits": 1,
                "relevant_commits": 4,
                "weighted_frequency": 0.3,
                "frequency": 0.25,
                "proximity": 0.3,
                "test_boost": 0.0,
                "intent_compatibility": 1.0,
                "anchor": "backend/app/routes/demo.py",
                "confidence": 40,
            }
        ]
        analysis = [
            {
                "path": "backend/app/routes/demo.py",
                "intents": ["api", "backend_logic"],
                "signals": ["route-related file path"],
                "primary_label": "API / backend route",
            }
        ]
        gaps = cn.find_test_gaps(
            ["backend/app/routes/demo.py"], ranked, analysis
        )
        self.assertEqual(len(gaps), 1)
        self.assertIn("test_api.py", gaps[0]["path"])
        self.assertIn("API / backend route", gaps[0]["gap_reason"])

    def test_change_analysis_in_text_and_json(self):
        analysis = [
            {
                "path": "backend/app/routes/demo.py",
                "intents": ["api", "backend_logic"],
                "signals": ["route-related file path", "HTTP route patterns found in diff"],
                "primary_label": "API / backend route",
            }
        ]
        text = cn.render_text(
            ["backend/app/routes/demo.py"],
            8,
            {"high": [], "medium": [], "watch": []},
            change_analysis=analysis,
        )
        self.assertIn("CHANGE ANALYSIS", text)
        self.assertIn("API / backend route", text)
        self.assertIn("route-related file path", text)

        payload = json.loads(
            cn.render_json(
                ["backend/app/routes/demo.py"],
                8,
                {"high": [], "medium": [], "watch": []},
                change_analysis=analysis,
            )
        )
        self.assertEqual(payload["change_analysis"][0]["intents"], ["api", "backend_logic"])


class CompletenessMapTests(unittest.TestCase):
    def test_classify_surface(self):
        self.assertEqual(cn.classify_surface("backend/app/routes/demo.py"), "backend_api")
        self.assertEqual(cn.classify_surface("frontend/lib/api.ts"), "api_integration")
        self.assertEqual(
            cn.classify_surface("frontend/app/dashboard/page.tsx"), "frontend_ui"
        )
        self.assertEqual(cn.classify_surface("frontend/components/Card.tsx"), "frontend_ui")
        self.assertEqual(cn.classify_surface("backend/tests/test_api.py"), "tests")
        self.assertEqual(cn.classify_surface("backend/app/models/schemas.py"), "data_schema")
        self.assertEqual(
            cn.classify_surface("backend/app/services/ingestion.py"), "backend_logic"
        )
        self.assertEqual(cn.classify_surface(".github/workflows/ci.yml"), "ci")
        self.assertEqual(cn.classify_surface("README.md"), "documentation")

    def test_covered_review_and_unknown(self):
        ranked = [
            {
                "path": "frontend/lib/api.ts",
                "supporting_commits": 8,
                "relevant_commits": 8,
                "frequency": 1.0,
                "confidence": 82,
            },
            {
                "path": "frontend/app/dashboard/page.tsx",
                "supporting_commits": 6,
                "relevant_commits": 8,
                "frequency": 0.75,
                "confidence": 62,
            },
            {
                "path": "backend/tests/test_api.py",
                "supporting_commits": 3,
                "relevant_commits": 8,
                "frequency": 0.375,
                "confidence": 32,
            },
            {
                "path": "docs/notes.md",
                "supporting_commits": 1,
                "relevant_commits": 8,
                "frequency": 0.12,
                "confidence": 26,
            },
        ]
        mapping = cn.build_completeness_map(["backend/app/routes/demo.py"], ranked)
        by_surface = {item["surface"]: item for item in mapping["surfaces"]}
        self.assertEqual(by_surface["backend_api"]["status"], "covered")
        self.assertEqual(by_surface["api_integration"]["status"], "review")
        self.assertEqual(by_surface["frontend_ui"]["status"], "review")
        self.assertEqual(by_surface["tests"]["status"], "review")
        self.assertEqual(by_surface["documentation"]["status"], "unknown")
        self.assertNotIn("dependency", by_surface)
        self.assertEqual(mapping["summary"]["review_count"], 3)
        self.assertEqual(mapping["summary"]["covered_count"], 1)
        self.assertEqual(mapping["summary"]["unknown_count"], 1)

    def test_groups_and_caps_representatives(self):
        ranked = [
            {
                "path": f"frontend/app/page{i}.tsx",
                "supporting_commits": 5,
                "relevant_commits": 6,
                "frequency": 0.8,
                "confidence": 70 - i,
            }
            for i in range(5)
        ]
        mapping = cn.build_completeness_map(["backend/app/routes/demo.py"], ranked)
        ui = next(item for item in mapping["surfaces"] if item["surface"] == "frontend_ui")
        self.assertEqual(ui["candidate_count"], 5)
        self.assertEqual(len(ui["representatives"]), 3)
        self.assertEqual(ui["representatives"][0]["path"], "frontend/app/page0.tsx")

    def test_map_in_text_and_json(self):
        mapping = {
            "surfaces": [
                {
                    "surface": "backend_api",
                    "status": "covered",
                    "candidate_count": 0,
                    "representatives": [],
                    "evidence": {},
                    "explanation": "Observed: current change includes Backend API files.",
                },
                {
                    "surface": "api_integration",
                    "status": "review",
                    "candidate_count": 1,
                    "representatives": [
                        {
                            "path": "frontend/lib/api.ts",
                            "supporting_commits": 8,
                            "relevant_commits": 8,
                            "frequency": 1.0,
                        }
                    ],
                    "evidence": {
                        "strongest_frequency": 1.0,
                        "strongest_path": "frontend/lib/api.ts",
                        "strongest_support": 8,
                        "strongest_relevant": 8,
                    },
                    "explanation": "Historical evidence for API Integration.",
                },
            ],
            "summary": {"review_count": 1, "covered_count": 1, "unknown_count": 0},
        }
        text = cn.render_text(
            ["backend/app/routes/demo.py"],
            8,
            {"high": [], "medium": [], "watch": []},
            completeness_map=mapping,
        )
        self.assertIn("CHANGE COMPLETENESS MAP", text)
        self.assertIn("COVERED", text)
        self.assertIn("REVIEW", text)
        self.assertIn("frontend/lib/api.ts", text)
        self.assertIn("CHANGE REVIEW SUMMARY", text)
        self.assertNotIn("INCOMPLETE", text)
        self.assertNotIn("REQUIRED", text)

        payload = json.loads(
            cn.render_json(
                ["backend/app/routes/demo.py"],
                8,
                {"high": [], "medium": [], "watch": []},
                completeness_map=mapping,
            )
        )
        self.assertEqual(payload["completeness_map"]["summary"]["review_count"], 1)
        self.assertEqual(
            payload["completeness_map"]["surfaces"][1]["surface"], "api_integration"
        )


class ParseHistoryTests(unittest.TestCase):
    def test_parses_sha_and_timestamp(self):
        sha = "a" * 40
        raw = f"{sha} 1700000000\nsrc/app.py\ntests/test_app.py\n"
        commits = cn._parse_history(raw)
        self.assertEqual(len(commits), 1)
        self.assertEqual(commits[0][0], sha)
        self.assertEqual(commits[0][1], 1700000000)
        self.assertEqual(commits[0][2], ["src/app.py", "tests/test_app.py"])


if __name__ == "__main__":
    unittest.main()
