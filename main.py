import hashlib
import json
import re
from pathlib import Path
from typing import Any

from config import AppConfig, load_config
from job_matcher import calculate_match_score
from job_search import search_jobs
from job_tailor import generate_cover_letter

MAX_JOBS_TO_SCORE_PER_RUN = 50


def _job_identity(job: dict[str, Any]) -> str:
    url = job.get("url")
    if isinstance(url, str) and url.strip():
        return url.strip().casefold()
    return "|".join(
        str(job.get(key, "")).strip().casefold()
        for key in ("title", "company", "location")
    )


def _role_matches_job(role: str, job: dict[str, Any]) -> bool:
    role_words = re.findall(r"[a-z0-9]+", role.casefold())
    searchable = " ".join(
        [
            str(job.get("title", "")),
            " ".join(str(tag) for tag in job.get("tags", [])),
        ]
    ).casefold()
    normalized_searchable = " ".join(re.findall(r"[a-z0-9]+", searchable))
    normalized_role = " ".join(role_words)
    if normalized_role and normalized_role in normalized_searchable:
        return True

    generic_words = {
        "developer",
        "engineer",
        "job",
        "manager",
        "of",
        "position",
        "role",
        "senior",
        "software",
        "specialist",
        "the",
    }
    meaningful_words = {
        word
        for word in role_words
        if word not in generic_words and (len(word) > 2 or word in {"ai", "ml"})
    }
    job_words = set(re.findall(r"[a-z0-9]+", searchable))
    return len(meaningful_words & job_words) >= min(len(meaningful_words), 2)


def _save_draft(
    output_dir: Path,
    job: dict[str, Any],
    match: dict[str, Any],
    cover_letter: str,
) -> Path:
    identity = _job_identity(job)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:10]
    title = re.sub(r"[^a-zA-Z0-9-]+", "-", str(job.get("title", "job"))).strip("-")
    filename = f"{title[:50] or 'job'}-{digest}"
    output_dir.mkdir(parents=True, exist_ok=True)

    draft = {
        "job": job,
        "match": match,
        "cover_letter": cover_letter,
    }
    (output_dir / f"{filename}.json").write_text(
        json.dumps(draft, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    markdown = (
        f"# {job.get('title', 'Untitled role')} at {job.get('company', 'Unknown')}\n\n"
        f"- **Location:** {job.get('location', 'Unknown')}\n"
        f"- **Match score:** {match['score']}/100\n"
        f"- **Why it matched:** {match['reasoning']}\n"
        f"- **Job listing:** [View listing]({job.get('url')})\n"
        f"- **Source:** [{job.get('source', 'Job board')}]"
        f"({job.get('source_url', '')})\n\n"
        f"## Cover letter draft\n\n{cover_letter}\n"
    )
    markdown_path = output_dir / f"{filename}.md"
    markdown_path.write_text(markdown, encoding="utf-8")
    return markdown_path


def run_pipeline(
    config: AppConfig,
    output_dir: Path = Path("output"),
) -> list[Path]:
    """Find, score, and save qualifying job drafts without submitting applications."""
    preferences = config.search_preferences
    matching = config.matching
    results = search_jobs()
    discovered: dict[str, dict[str, Any]] = {}
    for job in results:
        if any(_role_matches_job(role, job) for role in preferences.target_roles):
            identity = _job_identity(job)
            if identity:
                discovered.setdefault(identity, job)

    saved_paths: list[Path] = []
    for job in list(discovered.values())[:MAX_JOBS_TO_SCORE_PER_RUN]:
        if len(saved_paths) >= matching.max_jobs_per_run:
            break
        match = calculate_match_score(
            job_description=str(job.get("description", "")),
            resume_text=config.candidate.resume_text,
            job_title=str(job.get("title", "")),
            company=str(job.get("company", "")),
        )
        score = match["score"]
        if score < matching.min_score_threshold:
            continue
        letter = generate_cover_letter(
            job_description=str(job.get("description", "")),
            resume_text=config.candidate.resume_text,
            job_title=str(job.get("title", "")),
            company=str(job.get("company", "")),
            candidate_name=config.candidate.name,
        )
        saved_paths.append(_save_draft(output_dir, job, match, letter))

    return saved_paths


def main() -> None:
    config = load_config()
    saved_paths = run_pipeline(config)
    print(f"Saved {len(saved_paths)} cover-letter draft(s) for human review.")
    for path in saved_paths:
        print(f"- {path}")
    if not saved_paths:
        print("No jobs met the configured match-score threshold.")


if __name__ == "__main__":
    main()
