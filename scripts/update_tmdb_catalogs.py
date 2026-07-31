#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

API_BASE = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
CONFIG = Path("config/tmdb-catalogs.json")


def get_json(path: str, key: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    query = dict(params or {})
    query["api_key"] = key
    query.setdefault("language", "en-GB")
    url = f"{API_BASE}{path}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "strand-shelves/2.1"},
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def exact(results: list[dict[str, Any]], query: str, field: str = "name") -> dict[str, Any]:
    wanted = normalize_name(query)
    exact_matches = [
        item for item in results
        if normalize_name(str(item.get(field, ""))) == wanted
    ]
    if exact_matches:
        return exact_matches[0]
    if results:
        return results[0]
    raise RuntimeError(f"No TMDB match for {query}")


def movie_meta(movie: dict[str, Any]) -> dict[str, str] | None:
    movie_id = movie.get("id")
    title = movie.get("title") or movie.get("original_title")
    if not movie_id or not title:
        return None

    meta = {"id": f"tmdb:{movie_id}", "type": "movie", "name": str(title)}
    poster_path = movie.get("poster_path")
    if poster_path:
        meta["poster"] = IMAGE_BASE + poster_path
    return meta


def dedupe(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        meta = movie_meta(item)
        if not meta or meta["id"] in seen:
            continue
        seen.add(meta["id"])
        output.append(meta)
    return output


def discover(key: str, params: dict[str, Any], max_items: int = 400) -> list[dict[str, str]]:
    movies: list[dict[str, Any]] = []
    page = 1
    total_pages = 1

    while page <= total_pages and len(movies) < max_items:
        query = dict(params)
        query["page"] = page
        payload = get_json("/discover/movie", key, query)
        movies.extend(payload.get("results", []))
        total_pages = min(int(payload.get("total_pages", 1)), 500)
        page += 1

    return dedupe(movies[:max_items])


def build_director(entry: dict[str, Any], key: str) -> list[dict[str, str]]:
    search = get_json(
        "/search/person",
        key,
        {"query": entry["name"], "include_adult": "false"},
    )
    person = exact(search.get("results", []), entry["name"])
    credits = get_json(f"/person/{person['id']}/movie_credits", key)

    films = [
        credit for credit in credits.get("crew", [])
        if credit.get("job") == "Director"
    ]
    films.sort(
        key=lambda film: (
            film.get("release_date") or "9999-12-31",
            film.get("title") or "",
        )
    )
    return dedupe(films)


def resolve_company_id(entry: dict[str, Any], key: str) -> int:
    fixed_id = entry.get("company_id")
    if fixed_id:
        return int(fixed_id)

    results = get_json(
        "/search/company",
        key,
        {"query": entry["name"]},
    ).get("results", [])
    return int(exact(results, entry["name"])["id"])


def resolve_provider_id(name: str, key: str, region: str) -> int:
    results = get_json(
        "/watch/providers/movie",
        key,
        {"watch_region": region},
    ).get("results", [])

    aliases = {
        "Apple TV Plus": ["Apple TV Plus", "Apple TV+"],
        "Amazon Prime Video": ["Amazon Prime Video", "Prime Video"],
        "Disney Plus": ["Disney Plus", "Disney+"],
        "Max": ["Max", "HBO Max"],
        "Paramount Plus": ["Paramount Plus", "Paramount+"],
        "Peacock Premium": ["Peacock Premium", "Peacock", "Peacock Premium Plus"],
    }

    wanted_names = aliases.get(name, [name])
    normalized_wanted = {normalize_name(item) for item in wanted_names}

    # Exact normalized match first.
    for provider in results:
        provider_name = str(provider.get("provider_name", ""))
        if normalize_name(provider_name) in normalized_wanted:
            return int(provider["provider_id"])

    # Then allow a cautious containment match for branding variants.
    for provider in results:
        provider_name = normalize_name(str(provider.get("provider_name", "")))
        if any(wanted in provider_name or provider_name in wanted for wanted in normalized_wanted):
            return int(provider["provider_id"])

    available = ", ".join(
        str(provider.get("provider_name", ""))
        for provider in results
        if any(token in normalize_name(str(provider.get("provider_name", "")))
               for token in ("apple", "hulu", "peacock"))
    )
    raise RuntimeError(
        f"No {region} provider match for {name}. Relevant available names: {available or 'none'}"
    )


def write_catalog(entry: dict[str, Any], metas: list[dict[str, str]]) -> None:
    if not metas:
        raise RuntimeError("No movies returned")

    path = Path(entry["output"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"metas": metas}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"{entry['name']}: wrote {len(metas)} films")


def main() -> int:
    key = os.environ.get("TMDB_API_KEY", "").strip()
    if not key:
        print("TMDB_API_KEY is missing.", file=sys.stderr)
        return 1

    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    default_region = config.get("default_region", "GB")
    warnings: list[str] = []
    success_count = 0

    for entry in config.get("directors", []):
        try:
            write_catalog(entry, build_director(entry, key))
            success_count += 1
        except Exception as exc:
            warnings.append(f"{entry['name']}: {exc}")

    for entry in config.get("studios", []):
        try:
            company_id = resolve_company_id(entry, key)
            metas = discover(
                key,
                {
                    "with_companies": company_id,
                    "sort_by": "primary_release_date.desc",
                    "include_adult": "false",
                },
                int(entry.get("max_items", 400)),
            )
            write_catalog(entry, metas)
            success_count += 1
        except Exception as exc:
            warnings.append(f"{entry['name']}: {exc}")

    for entry in config.get("providers", []):
        try:
            region = entry.get("region", default_region)
            provider_id = resolve_provider_id(entry["name"], key, region)
            metas = discover(
                key,
                {
                    "with_watch_providers": provider_id,
                    "watch_region": region,
                    "with_watch_monetization_types": "flatrate|free|ads",
                    "sort_by": "popularity.desc",
                    "include_adult": "false",
                },
                int(entry.get("max_items", 400)),
            )
            write_catalog(entry, metas)
            success_count += 1
        except Exception as exc:
            warnings.append(f"{entry['name']}: {exc}")

    if warnings:
        print("\nWarnings — these catalogues were skipped:", file=sys.stderr)
        for warning in warnings:
            print(f"- {warning}", file=sys.stderr)

    # Successful catalogues should still be committed even if one optional
    # provider is unavailable in TMDB for a particular region.
    if success_count == 0:
        print("No catalogue was generated successfully.", file=sys.stderr)
        return 1

    print(f"\nCompleted with {success_count} successful catalogues.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
