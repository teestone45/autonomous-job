import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


@dataclass(frozen=True)
class Candidate:
    name: str
    resume_text: str


@dataclass(frozen=True)
class SearchPreferences:
    target_roles: list[str]


@dataclass(frozen=True)
class MatchingPreferences:
    min_score_threshold: int
    max_jobs_per_run: int


@dataclass(frozen=True)
class AppConfig:
    candidate: Candidate
    search_preferences: SearchPreferences
    matching: MatchingPreferences


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"'{name}' must be a JSON object.")
    return value


def _required_string(data: dict[str, Any], key: str, name: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{name}.{key}' must be a non-empty string.")
    return value.strip()


def _string_list(data: dict[str, Any], key: str, name: str) -> list[str]:
    value = data.get(key)
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise ValueError(f"'{name}.{key}' must be a non-empty list of strings.")
    return [item.strip() for item in value]


def _positive_int(data: dict[str, Any], key: str, name: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"'{name}.{key}' must be a positive integer.")
    return value


def load_config(path: Path = Path("config.json")) -> AppConfig:
    """Load and validate the local candidate and job-search settings."""
    load_dotenv()
    try:
        with path.open(encoding="utf-8") as config_file:
            raw_config = json.load(config_file)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Configuration file not found: {path}. "
            "Copy config.example.json to config.json and edit it."
        ) from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"Configuration file is not valid JSON: {exc}") from None

    root = _object(raw_config, "config")
    candidate = _object(root.get("candidate"), "candidate")
    search = _object(root.get("search_preferences"), "search_preferences")
    matching = _object(root.get("matching"), "matching")

    threshold = matching.get("min_score_threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, int) or not 0 <= threshold <= 100:
        raise ValueError("'matching.min_score_threshold' must be an integer from 0 to 100.")

    return AppConfig(
        candidate=Candidate(
            name=_required_string(candidate, "name", "candidate"),
            resume_text=_required_string(candidate, "resume_text", "candidate"),
        ),
        search_preferences=SearchPreferences(
            target_roles=_string_list(search, "target_roles", "search_preferences"),
        ),
        matching=MatchingPreferences(
            min_score_threshold=threshold,
            max_jobs_per_run=_positive_int(matching, "max_jobs_per_run", "matching"),
        ),
    )
