"""ROADMAP.md 2.6 -- "후보 검색 쿼리 생성": find candidate packages/repos
across registries for a set of search keywords.

Real, documented, public APIs -- no guessed endpoints:
- npm: `GET registry.npmjs.org/-/v1/search?text=`
- crates.io: `GET crates.io/api/v1/crates?q=` (User-Agent required by their
  API usage policy, set in http_client.py)
- GitHub: `GET api.github.com/search/repositories?q=`
- PyPI: **no official search API** (XML-RPC search was removed; the only
  documented PyPI API is metadata-by-known-name,
  `GET pypi.org/pypi/<name>/json`). So `lookup_pypi()` takes a name, not a
  query -- candidate PyPI package names have to come from somewhere else
  (an LLM suggestion, or a name already seen elsewhere), not from a
  registry-side text search that doesn't exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .http_client import real_get

HttpGet = Callable[[str, dict | None], dict]


@dataclass
class Candidate:
    ecosystem: str  # "npm" | "crates.io" | "github" | "pypi"
    name: str
    description: str
    license: str | None  # None means "unknown, needs review" -- never guessed
    url: str
    last_updated: str | None = None
    popularity: int | None = None  # stars (github) or downloads/weekly (npm) if available


def search_npm(query: str, limit: int = 5, http_get: HttpGet = real_get) -> list[Candidate]:
    from .http_client import urlencode

    data = http_get(f"https://registry.npmjs.org/-/v1/search?{urlencode({'text': query, 'size': limit})}", None)
    results = []
    for obj in data.get("objects", []):
        pkg = obj["package"]
        results.append(
            Candidate(
                ecosystem="npm",
                name=pkg["name"],
                description=pkg.get("description", ""),
                license=pkg.get("license"),
                url=pkg.get("links", {}).get("npm", f"https://www.npmjs.com/package/{pkg['name']}"),
                last_updated=pkg.get("date"),
            )
        )
    return results


def search_crates(query: str, limit: int = 5, http_get: HttpGet = real_get) -> list[Candidate]:
    from .http_client import urlencode

    data = http_get(f"https://crates.io/api/v1/crates?{urlencode({'q': query, 'per_page': limit})}", None)
    results = []
    for c in data.get("crates", []):
        results.append(
            Candidate(
                ecosystem="crates.io",
                name=c["name"],
                description=c.get("description", "") or "",
                # crates.io's search listing doesn't reliably include license
                # (that's per-version, from Cargo.toml) -- leave unknown
                # rather than assume permissive.
                license=c.get("license"),
                url=f"https://crates.io/crates/{c['name']}",
                last_updated=c.get("updated_at"),
                popularity=c.get("downloads"),
            )
        )
    return results


def search_github(query: str, limit: int = 5, http_get: HttpGet = real_get) -> list[Candidate]:
    from .http_client import urlencode

    data = http_get(
        f"https://api.github.com/search/repositories?{urlencode({'q': query, 'sort': 'stars', 'order': 'desc', 'per_page': limit})}",
        None,
    )
    results = []
    for repo in data.get("items", []):
        license_info = repo.get("license") or {}
        results.append(
            Candidate(
                ecosystem="github",
                name=repo["full_name"],
                description=repo.get("description", "") or "",
                license=license_info.get("spdx_id"),
                url=repo["html_url"],
                last_updated=repo.get("pushed_at"),
                popularity=repo.get("stargazers_count"),
            )
        )
    return results


def lookup_pypi(name: str, http_get: HttpGet = real_get) -> Candidate | None:
    try:
        data = http_get(f"https://pypi.org/pypi/{name}/json", None)
    except Exception:  # noqa: BLE001 - 404 (package doesn't exist) or network error
        return None
    info = data["info"]
    return Candidate(
        ecosystem="pypi",
        name=info["name"],
        description=info.get("summary", "") or "",
        license=info.get("license") or None,
        url=info.get("package_url", f"https://pypi.org/project/{name}/"),
    )
