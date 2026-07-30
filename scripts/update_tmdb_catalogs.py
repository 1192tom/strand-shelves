#!/usr/bin/env python3
"""Generate Strand/Stremio movie catalogues from TMDB people and companies."""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

API_BASE = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
CONFIG_PATH = Path("config/tmdb-catalogs.json")


def get_json(path: str, api_key: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    query = dict(params or {})
    query["api_key"] = api_key
    query.setdefault("language", "en-GB")
    url = f"{API_BASE}{path}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "strand-shelves-tmdb-generator/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def exact_search(results: list[dict[str, Any]], query: str, field: str) -> dict[str, Any]:
    exact = [r for r in results if str(r.get(field, "")).casefold() == query.casefold()]
    if exact:
        return exact[0]
    if results:
        return results[0]
    raise RuntimeError(f"No TMDB result found for {query}")


def movie_meta(movie: dict[str, Any]) -> dict[str, str] | None:
    tmdb_id = movie.get("id")
    title = movie.get("title") or movie.get("original_title")
    if not tmdb_id or not title:
        return None

    meta = {
        "id": f"tmdb:{tmdb_id}",
        "type": "movie",
        "name": str(title),
    }
    poster_path = movie.get("poster_path")
    if poster_path:
        meta["poster"] = f"{IMAGE_BASE}{poster_path}"
    return meta


def build_director(entry: dict[str, Any], api_key: str) -> list[dict[str, str]]:
    query = entry["query"]
    search = get_json("/search/person", api_key, {"query": query, "include_adult": "false"})
    person = exact_search(search.get("results", []), query, "name")
    credits = get_json(f"/person/{person['id']}/movie_credits", api_key)

    films: list[dict[str, Any]] = []
    for credit in credits.get("crew", []):
        if credit.get("job") == "Director":
            films.append(credit)

    # Release order, unreleased/undated titles last.
    films.sort(key=lambda m: (m.get("release_date") or "9999-12-31", m.get("title") or ""))
    return [m for film in films if (m := movie_meta(film))]


def build_company(entry: dict[str, Any], api_key: str) -> list[dict[str, str]]:
    query = entry["query"]
    search = get_json("/search/company", api_key, {"query": query})
    company = exact_search(search.get("results", []), query, "name")
    max_items = int(entry.get("max_items", 300))

    films: list[dict[str, Any]] = []
    page = 1
    total_pages = 1
    while page <= total_pages and len(films) < max_items:
        payload = get_json(
            "/discover/movie",
            api_key,
            {
                "with_companies": company["id"],
                "sort_by": "primary_release_date.asc",
                "include_adult": "false",
                "page": page,
            },
        )
        films.extend(payload.get("results", []))
        total_pages = min(int(payload.get("total_pages", 1)), 500)
        page += 1

    return [m for film in films[:max_items] if (m := movie_meta(film))]


def dedupe(metas: list[dict[str, str]]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    seen: set[str] = set()
    for meta in metas:
        if meta["id"] in seen:
            continue
        seen.add(meta["id"])
        output.append(meta)
    return output


def main() -> int:
    api_key = os.environ.get("TMDB_API_KEY", "").strip()
    if not api_key:
        print("TMDB_API_KEY is missing.", file=sys.stderr)
        return 1

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    failures: list[str] = []

    for entry in config.get("catalogs", []):
        try:
            if entry["kind"] == "director":
                metas = build_director(entry, api_key)
            elif entry["kind"] == "company":
                metas = build_company(entry, api_key)
            else:
                raise RuntimeError(f"Unsupported kind: {entry['kind']}")

            metas = dedupe(metas)
            if not metas:
                raise RuntimeError("No movies returned")

            output = Path(entry["output"])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps({"metas": metas}, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            print(f"{entry['name']}: wrote {len(metas)} films")
        except Exception as exc:
            message = f"{entry.get('name', 'Unnamed')}: {exc}"
            failures.append(message)
            print(f"ERROR: {message}", file=sys.stderr)

    if failures:
        print("\nSome catalogues failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
