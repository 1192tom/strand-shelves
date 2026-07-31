#!/usr/bin/env python3
from __future__ import annotations
import json, os, sys, urllib.parse, urllib.request
from pathlib import Path
from typing import Any

API_BASE = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
CONFIG = Path("config/tmdb-catalogs.json")

def get_json(path: str, key: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    q = dict(params or {})
    q["api_key"] = key
    q.setdefault("language", "en-GB")
    url = f"{API_BASE}{path}?{urllib.parse.urlencode(q)}"
    req = urllib.request.Request(url, headers={"Accept":"application/json","User-Agent":"strand-shelves/2.0"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))

def exact(results, query, field="name"):
    matches = [x for x in results if str(x.get(field,"")).casefold() == query.casefold()]
    if matches: return matches[0]
    if results: return results[0]
    raise RuntimeError(f"No TMDB match for {query}")

def meta(m):
    mid, title = m.get("id"), m.get("title") or m.get("original_title")
    if not mid or not title: return None
    out = {"id":f"tmdb:{mid}","type":"movie","name":str(title)}
    if m.get("poster_path"): out["poster"] = IMAGE_BASE + m["poster_path"]
    return out

def dedupe(items):
    out, seen = [], set()
    for x in items:
        m = meta(x)
        if not m or m["id"] in seen: continue
        seen.add(m["id"]); out.append(m)
    return out

def discover(key, params, max_items=400):
    movies, page, total = [], 1, 1
    while page <= total and len(movies) < max_items:
        q = dict(params); q["page"] = page
        data = get_json("/discover/movie", key, q)
        movies.extend(data.get("results", []))
        total = min(int(data.get("total_pages",1)), 500)
        page += 1
    return dedupe(movies[:max_items])

def build_director(entry, key):
    person = exact(get_json("/search/person", key, {"query":entry["name"],"include_adult":"false"}).get("results",[]), entry["name"])
    credits = get_json(f"/person/{person['id']}/movie_credits", key)
    films = [x for x in credits.get("crew",[]) if x.get("job") == "Director"]
    films.sort(key=lambda x: (x.get("release_date") or "9999-12-31", x.get("title") or ""))
    return dedupe(films)

def company_id(name, key):
    results = get_json("/search/company", key, {"query":name}).get("results",[])
    return exact(results, name)["id"]

def provider_id(name, key, region):
    results = get_json("/watch/providers/movie", key, {"watch_region":region}).get("results",[])
    aliases = {
        "Apple TV Plus": ["Apple TV Plus","Apple TV+"],
        "Amazon Prime Video": ["Amazon Prime Video","Prime Video"],
        "Disney Plus": ["Disney Plus","Disney+"],
        "Max": ["Max","HBO Max"],
        "Paramount Plus": ["Paramount Plus","Paramount+"],
        "Peacock Premium": ["Peacock Premium","Peacock"],
    }
    names = aliases.get(name,[name])
    for wanted in names:
        found = [x for x in results if str(x.get("provider_name","")).casefold() == wanted.casefold()]
        if found: return found[0]["provider_id"]
    raise RuntimeError(f"No {region} movie provider match for {name}")

def write(entry, metas):
    if not metas: raise RuntimeError("No movies returned")
    p = Path(entry["output"]); p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({"metas":metas},indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(f"{entry['name']}: wrote {len(metas)} films")

def main():
    key = os.environ.get("TMDB_API_KEY","").strip()
    if not key:
        print("TMDB_API_KEY is missing",file=sys.stderr); return 1
    cfg = json.loads(CONFIG.read_text())
    region = cfg.get("region","GB")
    failures = []

    for e in cfg.get("directors",[]):
        try: write(e, build_director(e,key))
        except Exception as ex: failures.append(f"{e['name']}: {ex}")

    for e in cfg.get("studios",[]):
        try:
            cid = company_id(e["name"],key)
            write(e, discover(key, {"with_companies":cid,"sort_by":"primary_release_date.desc","include_adult":"false"}, int(e.get("max_items",400))))
        except Exception as ex: failures.append(f"{e['name']}: {ex}")

    for e in cfg.get("providers",[]):
        try:
            pid = provider_id(e["name"],key,region)
            write(e, discover(key, {
                "with_watch_providers":pid,
                "watch_region":region,
                "with_watch_monetization_types":"flatrate|free|ads",
                "sort_by":"popularity.desc",
                "include_adult":"false"
            }, int(e.get("max_items",400))))
        except Exception as ex: failures.append(f"{e['name']}: {ex}")

    if failures:
        print("\nFailures:",file=sys.stderr)
        for f in failures: print("- "+f,file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
