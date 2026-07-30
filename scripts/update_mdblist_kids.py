#!/usr/bin/env python3
"""Build a Strand/Stremio movie catalogue from an MDBList list."""

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
            "User-Agent": "strand-shelves-mdblist-generator/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read().decode("utf-8")
        headers = {k.lower(): v for k, v in response.headers.items()}
    return json.loads(body), headers


def item_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]

    if not isinstance(payload, dict):
        return []

    for key in ("items", "results", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
        if isinstance(value, dict):
            for nested_key in ("items", "results"):
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    return [x for x in nested if isinstance(x, dict)]
    return []


def next_cursor(payload: Any, headers: dict[str, str]) -> str | None:
    if isinstance(payload, dict):
        pagination = payload.get("pagination")
        if isinstance(pagination, dict):
            cursor = pagination.get("next_cursor")
            if cursor:
                return str(cursor)
            if pagination.get("has_more") is False:
                return None
        cursor = payload.get("next_cursor")
        if cursor:
            return str(cursor)

    return headers.get("x-next-cursor")


def first_value(obj: dict[str, Any], *paths: tuple[str, ...]) -> Any:
    for path in paths:
        current: Any = obj
        ok = True
        for part in path:
            if not isinstance(current, dict) or part not in current:
                ok = False
                break
            current = current[part]
        if ok and current not in (None, ""):
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


def to_meta(item: dict[str, Any]) -> dict[str, str] | None:
    imdb = normalise_imdb(
        first_value(
            item,
            ("imdb_id",),
            ("imdb",),
            ("ids", "imdb"),
            ("movie", "ids", "imdb"),
            ("show", "ids", "imdb"),
        )
    )
    if not imdb:
        return None

    title = first_value(
        item,
        ("title",),
        ("name",),
        ("movie", "title"),
        ("show", "title"),
    )
    if not title:
        return None

    media_type = str(
        first_value(item, ("mediatype",), ("media_type",), ("type",)) or "movie"
    ).lower()

    # This particular list is a movie list. Ignore any unexpected TV entries.
    if media_type in {"show", "series", "tv"}:
        return None

    return {
        "id": imdb,
        "type": "movie",
        "name": str(title),
        "poster": f"https://images.metahub.space/poster/medium/{imdb}/img",
    }


def main() -> int:
    api_key = os.environ.get("MDBLIST_API_KEY", "").strip()
    if not api_key:
        print("MDBLIST_API_KEY is missing.", file=sys.stderr)
        return 1

    all_items: list[dict[str, Any]] = []
    cursor: str | None = None

    while len(all_items) < MAX_ITEMS:
        params = {
            "apikey": api_key,
            "limit": "100",
        }
        if cursor:
            params["cursor"] = cursor

        url = (
            f"{API_BASE}/lists/{USERNAME}/{LIST_SLUG}/items/movie?"
            + urllib.parse.urlencode(params)
        )
        payload, headers = fetch_json(url)
        page = item_list(payload)
        all_items.extend(page)

        cursor = next_cursor(payload, headers)
        if not cursor or not page:
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
        print(
            "MDBList returned no usable movie items with IMDb IDs. "
            "Check the API key, list URL, and workflow log.",
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
