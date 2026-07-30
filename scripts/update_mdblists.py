#!/usr/bin/env python3
"""Generate multiple Strand/Stremio catalogues from MDBList lists."""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

API_BASE = "https://api.mdblist.com"
CONFIG_PATH = Path("config/mdblists.json")


def fetch_json(url: str) -> tuple[Any, dict[str, str]]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "strand-shelves-mdblist-generator/2.0",
        },
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        payload = json.loads(response.read().decode("utf-8"))
        headers = {k.lower(): v for k, v in response.headers.items()}
    return payload, headers


def extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []

    for key in ("movies", "shows", "items", "results", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
        if isinstance(value, dict):
            for nested_key in ("movies", "shows", "items", "results"):
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    return [x for x in nested if isinstance(x, dict)]

    for value in payload.values():
        if isinstance(value, list) and all(isinstance(x, dict) for x in value):
            return value
    return []


def next_cursor(payload: Any, headers: dict[str, str]) -> str | None:
    if isinstance(payload, dict):
        pagination = payload.get("pagination")
        if isinstance(pagination, dict):
            cursor = pagination.get("next_cursor") or pagination.get("cursor")
            if cursor:
                return str(cursor)
            if pagination.get("has_more") is False:
                return None
        cursor = payload.get("next_cursor")
        if cursor:
            return str(cursor)
    return headers.get("x-next-cursor")


def get_nested(obj: dict[str, Any], *paths: tuple[str, ...]) -> Any:
    for path in paths:
        current: Any = obj
        for part in path:
            if not isinstance(current, dict) or part not in current:
                break
            current = current[part]
        else:
            if current not in (None, ""):
                return current
    return None


def imdb_id(item: dict[str, Any]) -> str | None:
    value = get_nested(
        item,
        ("imdb_id",), ("imdbid",), ("imdb",), ("ids", "imdb"),
        ("movie", "ids", "imdb"), ("show", "ids", "imdb"),
    )
    if value is None:
        return None
    text = str(value).strip()
    if text.startswith("tt") and text[2:].isdigit():
        return text
    if text.isdigit():
        return f"tt{text}"
    return None


def tmdb_id(item: dict[str, Any]) -> str | None:
    value = get_nested(
        item,
        ("tmdb_id",), ("tmdbid",), ("tmdb",), ("ids", "tmdb"),
        ("movie", "ids", "tmdb"), ("show", "ids", "tmdb"),
    )
    if value is None:
        return None
    text = str(value).strip()
    return text if text.isdigit() else None


def to_meta(item: dict[str, Any], media_type: str) -> dict[str, str] | None:
    title = get_nested(
        item, ("title",), ("name",), ("movie", "title"), ("show", "title")
    )
    if not title:
        return None

    imdb = imdb_id(item)
    tmdb = tmdb_id(item)
    strand_type = "series" if media_type in {"show", "series", "tv"} else "movie"

    if imdb:
        return {
            "id": imdb,
            "type": strand_type,
            "name": str(title),
            "poster": f"https://images.metahub.space/poster/medium/{imdb}/img",
        }
    if tmdb:
        return {"id": f"tmdb:{tmdb}", "type": strand_type, "name": str(title)}
    return None


def build_list(entry: dict[str, Any], api_key: str) -> None:
    username = entry["username"]
    slug = entry["slug"]
    media_type = entry["media_type"]
    output = Path(entry["output"])
    max_items = int(entry.get("max_items", 250))

    fetched: list[dict[str, Any]] = []
    cursor: str | None = None

    while len(fetched) < max_items:
        params = {"apikey": api_key, "limit": "100"}
        if cursor:
            params["cursor"] = cursor
        url = (
            f"{API_BASE}/lists/{username}/{slug}/items/{media_type}?"
            + urllib.parse.urlencode(params)
        )
        payload, headers = fetch_json(url)
        page = extract_items(payload)
        if not page:
            raise RuntimeError(f"No usable items returned for {username}/{slug}")
        fetched.extend(page)
        cursor = next_cursor(payload, headers)
        if not cursor:
            break

    metas: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in fetched:
        meta = to_meta(item, media_type)
        if not meta or meta["id"] in seen:
            continue
        seen.add(meta["id"])
        metas.append(meta)
        if len(metas) >= max_items:
            break

    if not metas:
        raise RuntimeError(f"No items with usable IMDb/TMDB IDs for {username}/{slug}")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"metas": metas}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"{entry['name']}: wrote {len(metas)} items to {output}")


def main() -> int:
    api_key = os.environ.get("MDBLIST_API_KEY", "").strip()
    if not api_key:
        print("MDBLIST_API_KEY is missing.", file=sys.stderr)
        return 1

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    failures: list[str] = []

    for entry in config.get("lists", []):
        try:
            build_list(entry, api_key)
        except Exception as exc:
            failures.append(f"{entry.get('name', 'Unnamed list')}: {exc}")
            print(f"ERROR: {failures[-1]}", file=sys.stderr)

    if failures:
        print("\nSome catalogues failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
