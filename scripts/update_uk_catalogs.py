#!/usr/bin/env python3
from common import *
from pathlib import Path
import json, os, sys
CONFIG=Path('config/uk-catalogs.json')
NETWORK_IDS={'BBC One':4,'BBC Two':332,'BBC Three':3,'BBC Four':100,'ITV1':9,'ITV2':149,'ITV3':590,'ITV4':261,'Channel 4':26,'E4':136,'Channel 5':99,'Dave':388,'Sky One':214,'Sky Atlantic':1063,'Sky Max':3590}
def exact(rows,q,field='name'):
 m=[x for x in rows if norm(x.get(field,''))==norm(q)]
 if m:return m[0]
 if rows:return rows[0]
 raise RuntimeError(f'No TMDB match for {q}')
def discover(path,key,params,max_items=400,typ='movie'):
 rows=[];page=1;total=1
 while page<=total and len(rows)<max_items:
  q=dict(params);q['page']=page;d=get(path,key,q);rows+=d.get('results',[]);total=min(int(d.get('total_pages',1)),500);page+=1
 return dedupe(rows[:max_items],typ,key)
def write(path,metas,name):
 if not metas:raise RuntimeError('No IMDb-backed items returned')
 p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps({'metas':metas},indent=2,ensure_ascii=False)+'\n');print(f'{name}: wrote {len(metas)} IMDb-backed items')
def provider_id(aliases,key,region):
 rows=get('/watch/providers/movie',key,{'watch_region':region}).get('results',[]);wanted={norm(x) for x in aliases}
 for p in rows:
  if norm(p.get('provider_name','')) in wanted:return p['provider_id']
 for p in rows:
  v=norm(p.get('provider_name',''))
  if any(x in v or v in x for x in wanted):return p['provider_id']
 raise RuntimeError('Could not match Sky/NOW Cinema provider')
def main():
 key=os.environ.get('TMDB_API_KEY','').strip();cfg=json.loads(CONFIG.read_text());region=cfg.get('region','GB');warnings=[];success=0
 for e in cfg.get('tv_networks',[]):
  try:
   ids=[str(NETWORK_IDS[n]) for n in e['query'] if n in NETWORK_IDS];metas=discover('/discover/tv',key,{'with_networks':'|'.join(ids),'sort_by':'popularity.desc','include_adult':'false'},400,'series');write(e['output'],metas,e['name']);success+=1
  except Exception as ex:warnings.append(f"{e['name']}: {ex}")
 for e in cfg.get('tv_discover',[]):
  try:write(e['output'],discover('/discover/tv',key,e['params'],400,'series'),e['name']);success+=1
  except Exception as ex:warnings.append(f"{e['name']}: {ex}")
 for e in cfg.get('movie_discover',[]):
  try:write(e['output'],discover('/discover/movie',key,e['params'],400,'movie'),e['name']);success+=1
  except Exception as ex:warnings.append(f"{e['name']}: {ex}")
 for e in cfg.get('movie_companies',[]):
  try:
   company=exact(get('/search/company',key,{'query':e['name']}).get('results',[]),e['name']);write(e['output'],discover('/discover/movie',key,{'with_companies':company['id'],'sort_by':'primary_release_date.desc','include_adult':'false'},400,'movie'),e['name']);success+=1
  except Exception as ex:warnings.append(f"{e['name']}: {ex}")
 try:
  sky=cfg['sky_cinema'];pid=provider_id(sky['provider_aliases'],key,region);base={'with_watch_providers':pid,'watch_region':region,'with_watch_monetization_types':'flatrate','include_adult':'false'}
  write(sky['now_output'],discover('/discover/movie',key,{**base,'sort_by':'popularity.desc'},400,'movie'),'Now on Sky Cinema');success+=1
  write(sky['popular_output'],discover('/discover/movie',key,{**base,'sort_by':'vote_count.desc'},400,'movie'),'Popular on Sky Cinema');success+=1
  write(sky['new_output'],discover('/discover/movie',key,{**base,'sort_by':'primary_release_date.desc'},200,'movie'),'New on Sky Cinema');success+=1
 except Exception as ex:warnings.append(f'Sky Cinema: {ex}')
 if warnings:
  print('\nWarnings:',file=sys.stderr)
  for w in warnings:print('- '+w,file=sys.stderr)
 return 0 if success else 1
if __name__=='__main__':raise SystemExit(main())
