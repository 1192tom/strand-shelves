#!/usr/bin/env python3
from __future__ import annotations
import json, os, re, sys, urllib.parse, urllib.request
from pathlib import Path
from typing import Any

API = "https://api.themoviedb.org/3"
IMAGE = "https://image.tmdb.org/t/p/w500"
CONFIG = Path("config/uk-catalogs.json")

def norm(v: str) -> str:
    return re.sub(r"[^a-z0-9]+","",v.casefold())

def get(path: str, key: str, params: dict[str,Any] | None=None):
    q=dict(params or {}); q["api_key"]=key; q.setdefault("language","en-GB")
    url=f"{API}{path}?{urllib.parse.urlencode(q)}"
    req=urllib.request.Request(url,headers={"Accept":"application/json","User-Agent":"strand-shelves-uk/1.0"})
    with urllib.request.urlopen(req,timeout=90) as r:
        return json.loads(r.read().decode())

def exact(results, name, field="name"):
    wanted=norm(name)
    same=[x for x in results if norm(str(x.get(field,"")))==wanted]
    if same:return same[0]
    if results:return results[0]
    raise RuntimeError(f"No TMDB match for {name}")

def meta(item, typ):
    iid=item.get("id")
    name=item.get("title") or item.get("name") or item.get("original_title") or item.get("original_name")
    if not iid or not name:return None
    out={"id":f"tmdb:{iid}","type":typ,"name":str(name)}
    if item.get("poster_path"):out["poster"]=IMAGE+item["poster_path"]
    return out

def dedupe(items,typ):
    out=[];seen=set()
    for i in items:
        m=meta(i,typ)
        if not m or m["id"] in seen:continue
        seen.add(m["id"]);out.append(m)
    return out

def discover(path,key,params,max_items=400,typ="movie"):
    rows=[];page=1;total=1
    while page<=total and len(rows)<max_items:
        q=dict(params);q["page"]=page
        d=get(path,key,q);rows.extend(d.get("results",[]))
        total=min(int(d.get("total_pages",1)),500);page+=1
    return dedupe(rows[:max_items],typ)

def write(path,metas,name):
    if not metas:raise RuntimeError("No items returned")
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({"metas":metas},indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(f"{name}: wrote {len(metas)} items")

def network_ids(names,key):
    ids=[]
    for name in names:
        result=exact(get("/search/tv",key,{"query":name}).get("results",[]),name,"name") if False else None
        # TMDB has no network search endpoint; search network pages through the
        # documented company-style endpoint is unavailable. Use TV discover
        # provider/network name matching through the network list endpoint.
        # The /network/{id} endpoint is ID-only, so resolve common UK networks
        # from a maintained mapping.
    return ids

NETWORK_IDS = {
    "BBC One":4, "BBC Two":332, "BBC Three":3, "BBC Four":100,
    "ITV1":9, "ITV2":149, "ITV3":590, "ITV4":261,
    "Channel 4":26, "E4":136,
    "Channel 5":99, "Dave":388,
    "Sky One":214, "Sky Atlantic":1063, "Sky Max":3590
}

def provider_id(aliases,key,region):
    results=get("/watch/providers/movie",key,{"watch_region":region}).get("results",[])
    wanted={norm(x) for x in aliases}
    for p in results:
        if norm(str(p.get("provider_name",""))) in wanted:return p["provider_id"]
    for p in results:
        pn=norm(str(p.get("provider_name","")))
        if any(w in pn or pn in w for w in wanted):return p["provider_id"]
    raise RuntimeError("Could not match Sky/NOW Cinema provider")

def main():
    key=os.environ.get("TMDB_API_KEY","").strip()
    if not key:
        print("TMDB_API_KEY is missing",file=sys.stderr);return 1
    cfg=json.loads(CONFIG.read_text())
    region=cfg.get("region","GB")
    warnings=[];success=0

    for e in cfg.get("tv_networks",[]):
        try:
            ids=[str(NETWORK_IDS[n]) for n in e["query"] if n in NETWORK_IDS]
            if not ids:raise RuntimeError("No network IDs configured")
            metas=discover("/discover/tv",key,{
                "with_networks":"|".join(ids),
                "sort_by":"popularity.desc",
                "include_adult":"false"
            },400,"series")
            write(e["output"],metas,e["name"]);success+=1
        except Exception as ex:warnings.append(f"{e['name']}: {ex}")

    for e in cfg.get("tv_discover",[]):
        try:
            metas=discover("/discover/tv",key,e["params"],400,"series")
            write(e["output"],metas,e["name"]);success+=1
        except Exception as ex:warnings.append(f"{e['name']}: {ex}")

    for e in cfg.get("movie_discover",[]):
        try:
            metas=discover("/discover/movie",key,e["params"],400,"movie")
            write(e["output"],metas,e["name"]);success+=1
        except Exception as ex:warnings.append(f"{e['name']}: {ex}")

    for e in cfg.get("movie_companies",[]):
        try:
            company=exact(get("/search/company",key,{"query":e["name"]}).get("results",[]),e["name"])
            metas=discover("/discover/movie",key,{
                "with_companies":company["id"],
                "sort_by":"primary_release_date.desc",
                "include_adult":"false"
            },400,"movie")
            write(e["output"],metas,e["name"]);success+=1
        except Exception as ex:
            warnings.append(f"{e['name']}: {ex}")

    try:
        sky=cfg["sky_cinema"]
        pid=provider_id(sky["provider_aliases"],key,region)
        base={
            "with_watch_providers":pid,
            "watch_region":region,
            "with_watch_monetization_types":"flatrate",
            "include_adult":"false"
        }
        now=discover("/discover/movie",key,{**base,"sort_by":"popularity.desc"},400,"movie")
        write(sky["now_output"],now,"Now on Sky Cinema");success+=1
        popular=discover("/discover/movie",key,{**base,"sort_by":"vote_count.desc"},400,"movie")
        write(sky["popular_output"],popular,"Popular on Sky Cinema");success+=1
        new=discover("/discover/movie",key,{**base,"sort_by":"primary_release_date.desc"},200,"movie")
        write(sky["new_output"],new,"New on Sky Cinema");success+=1
    except Exception as ex:warnings.append(f"Sky Cinema: {ex}")

    if warnings:
        print("\nWarnings:",file=sys.stderr)
        for w in warnings:print("- "+w,file=sys.stderr)
    if success==0:return 1
    print(f"\nCompleted with {success} successful UK catalogues.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
