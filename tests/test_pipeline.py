import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config import AppConfig, Candidate, MatchingPreferences, SearchPreferences, load_config
from job_search import REMOTEOK_URL, search_jobs
from main import MAX_JOBS_TO_SCORE_PER_RUN, _role_matches_job, run_pipeline


def make_config(max_jobs_per_run: int = 10) -> AppConfig:
    return AppConfig(
        candidate=Candidate(name="Test Candidate", resume_text="Python and automation"),
        search_preferences=SearchPreferences(
            target_roles=["Automation Engineer"],
        ),
        matching=MatchingPreferences(
            min_score_threshold=75,
            max_jobs_per_run=max_jobs_per_run,
        ),
    )


class LoadConfigTests(unittest.TestCase):
    def test_loads_valid_configuration(self) -> None:
        raw = {
            "candidate": {"name": "Test Candidate", "resume_text": "Python"},
            "search_preferences": {
                "target_roles": ["Engineer"]
            },
            "matching": {"min_score_threshold": 75, "max_jobs_per_run": 5},
        }
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(raw), encoding="utf-8")
            config = load_config(config_path)

        self.assertEqual(config.search_preferences.target_roles, ["Engineer"])
        self.assertEqual(config.matching.max_jobs_per_run, 5)

    def test_rejects_invalid_score_threshold(self) -> None:
        raw = {
            "candidate": {"name": "Test Candidate", "resume_text": "Python"},
            "search_preferences": {
                "target_roles": ["Engineer"],
            },
            "matching": {"min_score_threshold": 101, "max_jobs_per_run": 5},
        }
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "min_score_threshold"):
                load_config(config_path)


class RemoteOkSearchTests(unittest.TestCase):
    @patch("job_search.requests.get")
    def test_maps_remote_ok_listings_without_credentials(
        self,
        get_mock: unittest.mock.Mock,
    ) -> None:
        response = unittest.mock.Mock()
        response.ok = True
        response.json.return_value = [
            {"legal": "API attribution required"},
            {
                "position": "AI Automation Engineer",
                "company": "Example Co",
                "location": "Worldwide",
                "description": "Build automation systems.",
                "url": "https://remoteok.com/remote-jobs/example",
                "apply_url": "https://example.com/apply",
                "date": "2026-10-15",
                "salary_min": 100000,
                "salary_max": 120000,
                "tags": ["AI", "automation"],
            },
        ]
        get_mock.return_value = response

        jobs = search_jobs()

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "AI Automation Engineer")
        self.assertEqual(jobs[0]["company"], "Example Co")
        self.assertEqual(jobs[0]["tags"], ["AI", "automation"])
        self.assertEqual(jobs[0]["source"], "Remote OK")
        self.assertEqual(jobs[0]["source_url"], REMOTEOK_URL)
        self.assertTrue(get_mock.call_args.kwargs["headers"]["User-Agent"])


class RoleMatchingTests(unittest.TestCase):
    def test_matches_role_using_title_and_tags_without_broad_ai_only_matches(self) -> None:
        self.assertTrue(
            _role_matches_job(
                "AI Automation Engineer",
                {"title": "Automation Engineer", "tags": ["AI", "Python"]},
            )
        )
        self.assertFalse(
            _role_matches_job(
                "AI Automation Engineer",
                {"title": "AI Trainer", "tags": ["education"]},
            )
        )

    def test_matches_hyphenated_role_against_unhyphenated_title(self) -> None:
        self.assertTrue(
            _role_matches_job(
                "Full-Stack Developer",
                {"title": "Senior Full Stack Software Engineer", "tags": ["React"]},
            )
        )


class PipelineTests(unittest.TestCase):
    @patch("main.generate_cover_letter", return_value="A truthful draft.")
    @patch("main.calculate_match_score")
    @patch("main.search_jobs")
    def test_saves_only_qualifying_deduplicated_jobs(
        self,
        search_mock: unittest.mock.Mock,
        score_mock: unittest.mock.Mock,
        _letter_mock: unittest.mock.Mock,
    ) -> None:
        jobs = [
            {
                "title": "Automation Engineer",
                "company": "Example Co",
                "location": "Remote",
                "description": "Build workflows",
                "url": "https://jobs.example/1",
            },
            {
                "title": "Automation Engineer",
                "company": "Example Co",
                "location": "Remote",
                "description": "Build workflows",
                "url": "https://jobs.example/1",
            },
            {
                "title": "Automation Engineer",
                "company": "Other Co",
                "location": "Remote",
                "description": "A different role",
                "url": "https://jobs.example/2",
            },
        ]
        search_mock.return_value = jobs
        score_mock.side_effect = [
            {"score": 90, "reasoning": "Strong skills match."},
            {"score": 40, "reasoning": "Few matching skills."},
        ]

        with tempfile.TemporaryDirectory() as directory:
            paths = run_pipeline(make_config(), Path(directory))
            markdown = paths[0].read_text(encoding="utf-8")
            json_path = paths[0].with_suffix(".json")
            saved_json = json.loads(json_path.read_text(encoding="utf-8"))

        self.assertEqual(len(paths), 1)
        self.assertIn("A truthful draft.", markdown)
        self.assertEqual(saved_json["match"]["score"], 90)
        self.assertEqual(score_mock.call_count, 2)

    @patch("main.generate_cover_letter")
    @patch("main.calculate_match_score", return_value={"score": 50, "reasoning": "Weak match."})
    @patch("main.search_jobs")
    def test_does_not_generate_draft_below_threshold(
        self,
        search_mock: unittest.mock.Mock,
        _score_mock: unittest.mock.Mock,
        letter_mock: unittest.mock.Mock,
    ) -> None:
        search_mock.return_value = [
            {
                "title": "Unrelated Role",
                "company": "Example Co",
                "location": "Remote",
                "description": "Unrelated",
                "url": "https://jobs.example/3",
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            paths = run_pipeline(make_config(), Path(directory))

        self.assertEqual(paths, [])
        letter_mock.assert_not_called()

    @patch("main.generate_cover_letter", return_value="Draft")
    @patch("main.calculate_match_score", return_value={"score": 90, "reasoning": "Good match."})
    @patch("main.search_jobs")
    def test_respects_maximum_number_of_drafts(
        self,
        search_mock: unittest.mock.Mock,
        _score_mock: unittest.mock.Mock,
        _letter_mock: unittest.mock.Mock,
    ) -> None:
        search_mock.return_value = [
            {
                "title": f"Role {index}",
                "company": "Example Co",
                "location": "Remote",
                "description": "Relevant",
                "url": f"https://jobs.example/{index}",
                "tags": ["automation"],
            }
            for index in range(3)
        ]
        with tempfile.TemporaryDirectory() as directory:
            paths = run_pipeline(make_config(max_jobs_per_run=2), Path(directory))

        self.assertEqual(len(paths), 2)

    @patch("main.generate_cover_letter")
    @patch("main.calculate_match_score")
    @patch("main.search_jobs", return_value=[])
    def test_searches_remote_ok_feed_only_once(
        self,
        search_mock: unittest.mock.Mock,
        _score_mock: unittest.mock.Mock,
        _letter_mock: unittest.mock.Mock,
    ) -> None:
        config = make_config()

        run_pipeline(config)

        search_mock.assert_called_once_with()

    @patch("main.generate_cover_letter")
    @patch("main.calculate_match_score")
    @patch("main.search_jobs")
    def test_filters_remote_ok_feed_by_target_role_and_limits_scoring_budget(
        self,
        search_mock: unittest.mock.Mock,
        score_mock: unittest.mock.Mock,
        _letter_mock: unittest.mock.Mock,
    ) -> None:
        search_mock.return_value = [
            {
                "title": f"Automation Engineer {index}",
                "company": "Example Co",
                "location": "Remote",
                "description": "Relevant",
                "url": f"https://jobs.example/{index}",
                "source": "Remote OK",
                "source_url": REMOTEOK_URL,
                "tags": ["automation"],
            }
            for index in range(MAX_JOBS_TO_SCORE_PER_RUN + 5)
        ]
        score_mock.return_value = {"score": 50, "reasoning": "Below threshold."}
        config = make_config()

        run_pipeline(config)

        self.assertEqual(score_mock.call_count, MAX_JOBS_TO_SCORE_PER_RUN)
        self.assertLessEqual(score_mock.call_count, MAX_JOBS_TO_SCORE_PER_RUN)


if __name__ == "__main__":
    unittest.main()
