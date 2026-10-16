from typing import Any

import requests


REMOTEOK_API_URL = "https://remoteok.com/api"
REMOTEOK_URL = "https://remoteok.com/"
REQUEST_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "JobScout/1.0 (local remote-job search app)",
}


def search_jobs() -> list[dict[str, Any]]:
    """Fetch the latest worldwide remote listings from Remote OK's free public API."""
    try:
        response = requests.get(
            REMOTEOK_API_URL,
            headers=REQUEST_HEADERS,
            timeout=20,
        )
    except requests.RequestException:
        raise RuntimeError(
            "Remote OK request failed; check your internet connection and try again."
        ) from None
    if not response.ok:
        raise RuntimeError(f"Remote OK returned HTTP {response.status_code}.")
    try:
        data = response.json()
    except requests.exceptions.JSONDecodeError:
        raise RuntimeError("Remote OK returned a response that was not valid JSON.") from None

    if not isinstance(data, list):
        raise RuntimeError("Remote OK returned an unexpected response format.")

    jobs: list[dict[str, Any]] = []
    for result in data:
        if not isinstance(result, dict) or not result.get("position"):
            continue
        tags = result.get("tags")
        if not isinstance(tags, list):
            tags = []
        company = result.get("company") or "Unknown"
        job_url = result.get("url") or result.get("apply_url") or ""
        jobs.append(
            {
                "title": result["position"],
                "company": company,
                "location": result.get("location") or "Remote",
                "description": result.get("description") or "",
                "url": job_url,
                "apply_url": result.get("apply_url") or job_url,
                "created": result.get("date"),
                "salary_min": result.get("salary_min"),
                "salary_max": result.get("salary_max"),
                "tags": tags,
                "source": "Remote OK",
                "source_url": REMOTEOK_URL,
            }
        )
    return jobs
