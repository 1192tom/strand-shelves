#!/usr/bin/env python3
from __future__ import annotations
import json, os, re, sys, urllib.parse, urllib.request
from pathlib import Path

API="https://api.themoviedb.org/3"
IMAGE="https://image.tmdb.org/t/p/w500"
CONFIG=Path("config/franchise-catalogs.json")

def norm(v):
    return re.sub(r"[^a-z0-9]+","",str(v).casefold())

def get(path,key,params=None):
    q=dict(params or {});q["api_key"]=key;q.setdefault("language","en-GB")
    url=f"{API}{path}?{urllib.parse.urlencode(q)}"
    req=urllib.request.Request(url,headers={"Accept":"application/json","User-Agent":"strand-franchises/1.0"})
    with urllib.request.urlopen(req,timeout=90) as r:
        return json.loads(r.read().decode())

def collection(name,key):
    rows=get("/search/collection",key,{"query":name,"include_adult":"false"}).get("results",[])
    wanted=norm(name)
    exact=[x for x in rows if norm(x.get("name"))==wanted]
    if exact:chosen=exact[0]
    elif rows:chosen=rows[0]
    else:raise RuntimeError(f"No collection match for {name}")
    return get(f"/collection/{chosen['id']}",key).get("parts",[])

def meta(m):
    mid=m.get("id");name=m.get("title") or m.get("original_title")
    if not mid or not name:return None
    out={"id":f"tmdb:{mid}","type":"movie","name":str(name)}
    if m.get("poster_path"):out["poster"]=IMAGE+m["poster_path"]
    out["_date"]=m.get("release_date") or "9999-12-31"
    return out

def build(entry,key):
    rows=[];warnings=[]
    for cname in entry["collections"]:
        try:rows.extend(collection(cname,key))
        except Exception as ex:warnings.append(f"{cname}: {ex}")
    metas=[];seen=set()
    for row in rows:
        m=meta(row)
        if not m or m["id"] in seen:continue
        seen.add(m["id"]);metas.append(m)
    metas.sort(key=lambda x:(x["_date"],x["name"]))
    for m in metas:m.pop("_date",None)
    return metas,warnings

def main():
    key=os.environ.get("TMDB_API_KEY","").strip()
    if not key:
        print("TMDB_API_KEY is missing",file=sys.stderr);return 1
    cfg=json.loads(CONFIG.read_text())
    total=0;all_warnings=[]
    for e in cfg["franchises"]:
        try:
            metas,warnings=build(e,key)
            all_warnings.extend(f"{e['name']} / {w}" for w in warnings)
            if not metas:raise RuntimeError("No films returned")
            p=Path(e["output"]);p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text(json.dumps({"metas":metas},indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
            print(f"{e['name']}: wrote {len(metas)} films")
            total+=1
        except Exception as ex:
            all_warnings.append(f"{e['name']}: {ex}")
    if all_warnings:
        print("\nWarnings:",file=sys.stderr)
        for w in all_warnings:print("- "+w,file=sys.stderr)
    if total==0:return 1
    print(f"\nCompleted with {total} successful franchise catalogues.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
