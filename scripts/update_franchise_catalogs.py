#!/usr/bin/env python3
from common import *
from pathlib import Path
import json, os, sys
CONFIG=Path('config/franchise-catalogs.json')
def collection(name,key):
 rows=get('/search/collection',key,{'query':name,'include_adult':'false'}).get('results',[]);m=[x for x in rows if norm(x.get('name',''))==norm(name)];chosen=(m or rows)[0] if rows else None
 if not chosen:raise RuntimeError(f'No collection match for {name}')
 return get(f"/collection/{chosen['id']}",key).get('parts',[])
def main():
 key=os.environ.get('TMDB_API_KEY','').strip();cfg=json.loads(CONFIG.read_text());warnings=[];success=0
 for e in cfg['franchises']:
  try:
   rows=[]
   for cname in e['collections']:
    try:rows+=collection(cname,key)
    except Exception as ex:warnings.append(f"{e['name']} / {cname}: {ex}")
   rows.sort(key=lambda x:(x.get('release_date') or '9999',x.get('title') or ''));metas=dedupe(rows,'movie',key)
   if not metas:raise RuntimeError('No IMDb-backed films returned')
   p=Path(e['output']);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps({'metas':metas},indent=2,ensure_ascii=False)+'\n');print(f"{e['name']}: wrote {len(metas)} IMDb-backed films");success+=1
  except Exception as ex:warnings.append(f"{e['name']}: {ex}")
 if warnings:
  print('\nWarnings:',file=sys.stderr)
  for w in warnings:print('- '+w,file=sys.stderr)
 return 0 if success else 1
if __name__=='__main__':raise SystemExit(main())
