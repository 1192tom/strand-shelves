#!/usr/bin/env python3
from common import *
from pathlib import Path
import json, os, sys
CONFIG=Path('config/tmdb-catalogs.json')
def exact(rows,q,field='name'):
 m=[x for x in rows if norm(x.get(field,''))==norm(q)]
 if m:return m[0]
 if rows:return rows[0]
 raise RuntimeError(f'No TMDB match for {q}')
def discover(key,params,max_items=400):
 rows=[];page=1;total=1
 while page<=total and len(rows)<max_items:
  q=dict(params);q['page']=page;d=get('/discover/movie',key,q);rows+=d.get('results',[]);total=min(int(d.get('total_pages',1)),500);page+=1
 return dedupe(rows[:max_items],'movie',key)
def write(e,metas):
 if not metas:raise RuntimeError('No IMDb-backed movies returned')
 p=Path(e['output']);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps({'metas':metas},indent=2,ensure_ascii=False)+'\n')
 print(f"{e['name']}: wrote {len(metas)} IMDb-backed films")
def provider_id(name,key,region):
 aliases={'Apple TV Plus':['Apple TV Plus','Apple TV+'],'Amazon Prime Video':['Amazon Prime Video','Prime Video'],'Disney Plus':['Disney Plus','Disney+'],'Max':['Max','HBO Max'],'Paramount Plus':['Paramount Plus','Paramount+'],'Peacock Premium':['Peacock Premium','Peacock','Peacock Premium Plus']}
 rows=get('/watch/providers/movie',key,{'watch_region':region}).get('results',[]);wanted={norm(x) for x in aliases.get(name,[name])}
 for p in rows:
  if norm(p.get('provider_name','')) in wanted:return p['provider_id']
 raise RuntimeError(f'No {region} provider match for {name}')
def main():
 key=os.environ.get('TMDB_API_KEY','').strip();cfg=json.loads(CONFIG.read_text());warnings=[];success=0;region=cfg.get('default_region',cfg.get('region','GB'))
 for e in cfg.get('directors',[]):
  try:
   person=exact(get('/search/person',key,{'query':e['name'],'include_adult':'false'}).get('results',[]),e['name']);credits=get(f"/person/{person['id']}/movie_credits",key)
   films=[x for x in credits.get('crew',[]) if x.get('job')=='Director'];films.sort(key=lambda x:(x.get('release_date') or '9999',x.get('title') or ''));write(e,dedupe(films,'movie',key));success+=1
  except Exception as ex:warnings.append(f"{e['name']}: {ex}")
 for e in cfg.get('studios',[]):
  try:
   cid=int(e.get('company_id') or exact(get('/search/company',key,{'query':e['name']}).get('results',[]),e['name'])['id']);write(e,discover(key,{'with_companies':cid,'sort_by':'primary_release_date.desc','include_adult':'false'},int(e.get('max_items',400))));success+=1
  except Exception as ex:warnings.append(f"{e['name']}: {ex}")
 for e in cfg.get('providers',[]):
  try:
   r=e.get('region',region);pid=provider_id(e['name'],key,r);write(e,discover(key,{'with_watch_providers':pid,'watch_region':r,'with_watch_monetization_types':'flatrate|free|ads','sort_by':'popularity.desc','include_adult':'false'},int(e.get('max_items',400))));success+=1
  except Exception as ex:warnings.append(f"{e['name']}: {ex}")
 if warnings:
  print('\nWarnings:',file=sys.stderr)
  for w in warnings:print('- '+w,file=sys.stderr)
 return 0 if success else 1
if __name__=='__main__':raise SystemExit(main())
