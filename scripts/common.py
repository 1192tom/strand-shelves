from __future__ import annotations
import json, os, re, urllib.parse, urllib.request
from typing import Any
API='https://api.themoviedb.org/3'; IMAGE='https://image.tmdb.org/t/p/w500'
_cache={}
def norm(v): return re.sub(r'[^a-z0-9]+','',str(v).casefold())
def get(path,key,params=None):
 q=dict(params or {}); q['api_key']=key; q.setdefault('language','en-GB')
 req=urllib.request.Request(f"{API}{path}?{urllib.parse.urlencode(q)}",headers={'Accept':'application/json','User-Agent':'strand-imdb/1.0'})
 with urllib.request.urlopen(req,timeout=90) as r: return json.loads(r.read().decode())
def imdb_id(tmdb_id,typ,key):
 k=(typ,int(tmdb_id))
 if k in _cache:return _cache[k]
 endpoint='tv' if typ=='series' else 'movie'; v=get(f'/{endpoint}/{tmdb_id}/external_ids',key).get('imdb_id')
 _cache[k]=v if isinstance(v,str) and re.fullmatch(r'tt\d+',v) else None
 return _cache[k]
def meta(item,typ,key):
 tid=item.get('id'); name=item.get('title') or item.get('name') or item.get('original_title') or item.get('original_name')
 if not tid or not name:return None
 iid=imdb_id(tid,typ,key)
 if not iid:return None
 out={'id':iid,'type':typ,'name':str(name)}
 if item.get('poster_path'):out['poster']=IMAGE+item['poster_path']
 return out
def dedupe(items,typ,key):
 out=[];seen=set()
 for x in items:
  m=meta(x,typ,key)
  if not m or m['id'] in seen:continue
  seen.add(m['id']);out.append(m)
 return out
