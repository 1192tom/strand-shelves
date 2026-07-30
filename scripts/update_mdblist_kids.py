#!/usr/bin/env python3
"""Build a Strand/Stremio movie catalogue from an MDBList public list."""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

API_BASE = "https://api.mdblist.com"
USERNAME = "suttydolt"
LIST_SLUG = "top-rated-kids-films-1950-current"
OUTPUT = Path("catalog/movie/kids-family-movies.json")
MAX_ITEMS = 250


def fetch_json(url: str) -> tuple[Any, dict[str, str]]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "strand-shelves-mdblist-generator/1.1",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
        headers = {k.lower(): v for k, v in response.headers.items()}
    return payload, headers


def extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]

    if not isinstance(payload, dict):
        return []

    # MDBList responses may use any of these top-level containers.
    for key in ("movies", "items", "results", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
        if isinstance(value, dict):
            for nested_key in ("movies", "items", "results"):
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    return [x for x in nested if isinstance(x, dict)]

    # Last-resort: find the first list of objects anywhere at top level.
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


def normalise_imdb(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.startswith("tt") and text[2:].isdigit():
        return text
    if text.isdigit():
        return f"tt{text}"
    return None


def normalise_tmdb(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text.isdigit() else None


def to_meta(item: dict[str, Any]) -> dict[str, str] | None:
    title = get_nested(
        item,
        ("title",),
        ("name",),
        ("movie", "title"),
        ("show", "title"),
    )
    if not title:
        return None

    media_type = str(
        get_nested(item, ("mediatype",), ("media_type",), ("type",)) or "movie"
    ).lower()
    if media_type in {"show", "series", "tv"}:
        return None

    imdb = normalise_imdb(
        get_nested(
            item,
            ("imdb_id",),
            ("imdbid",),
            ("imdb",),
            ("ids", "imdb"),
            ("movie", "ids", "imdb"),
        )
    )
    tmdb = normalise_tmdb(
        get_nested(
            item,
            ("tmdb_id",),
            ("tmdbid",),
            ("tmdb",),
            ("ids", "tmdb"),
            ("movie", "ids", "tmdb"),
        )
    )

    if imdb:
        item_id = imdb
        poster = f"https://images.metahub.space/poster/medium/{imdb}/img"
    elif tmdb:
        # Strand/AIO Metadata can resolve TMDB identifiers.
        item_id = f"tmdb:{tmdb}"
        poster = f"https://image.tmdb.org/t/p/w500/null"
    else:
        return None

    meta = {
        "id": item_id,
        "type": "movie",
        "name": str(title),
    }
    # Do not emit a broken TMDB poster URL; metadata add-ons can supply artwork.
    if imdb:
        meta["poster"] = poster
    return meta


def main() -> int:
    api_key = os.environ.get("MDBLIST_API_KEY", "").strip()
    if not api_key:
        print("MDBLIST_API_KEY is missing.", file=sys.stderr)
        return 1

    all_items: list[dict[str, Any]] = []
    cursor: str | None = None

    while len(all_items) < MAX_ITEMS:
        params = {"apikey": api_key, "limit": "100"}
        if cursor:
            params["cursor"] = cursor

        url = (
            f"{API_BASE}/lists/{USERNAME}/{LIST_SLUG}/items/movie?"
            + urllib.parse.urlencode(params)
        )
        payload, headers = fetch_json(url)
        page = extract_items(payload)

        if not page:
            print("No list items were found in the MDBList response.", file=sys.stderr)
            print("Response type:", type(payload).__name__, file=sys.stderr)
            if isinstance(payload, dict):
                print("Top-level keys:", sorted(payload.keys()), file=sys.stderr)
                print(
                    "Response preview:",
                    json.dumps(payload, ensure_ascii=False)[:1500],
                    file=sys.stderr,
                )
            return 1

        print(f"Fetched {len(page)} items from MDBList.")
        print("First item keys:", sorted(page[0].keys()))
        all_items.extend(page)

        cursor = next_cursor(payload, headers)
        if not cursor:
            break

    metas: list[dict[str, str]] = []
    seen: set[str] = set()

    for item in all_items:
        meta = to_meta(item)
        if not meta or meta["id"] in seen:
            continue
        seen.add(meta["id"])
        metas.append(meta)
        if len(metas) >= MAX_ITEMS:
            break

    if not metas:
        print("Fetched items, but none had usable IMDb or TMDB IDs.", file=sys.stderr)
        print(
            "First item preview:",
            json.dumps(all_items[0], ensure_ascii=False)[:1500],
            file=sys.stderr,
        )
        return 1

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps({"metas": metas}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {len(metas)} films to {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
