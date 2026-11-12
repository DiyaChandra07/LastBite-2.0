"""Elastic retrieval with a safe local fallback. Configure ELASTICSEARCH_URL to enable it."""
import os

def search_listings(rows, query=''):
    rows=[dict(r) for r in rows]
    url=os.getenv('ELASTICSEARCH_URL'); api_key=os.getenv('ELASTICSEARCH_API_KEY')
    if url:
        try:
            from elasticsearch import Elasticsearch
            client=Elasticsearch(url,api_key=api_key) if api_key else Elasticsearch(url)
            index=os.getenv('ELASTICSEARCH_INDEX','lastbite-listings')
            docs=[{'id':r['id'],'title':r['title'],'description':r.get('description') or '', 'category':'food','seller':r.get('seller','')} for r in rows]
            for d in docs: client.index(index=index,id=d['id'],document=d,refresh=True)
            if query:
                res=client.search(index=index,query={'multi_match':{'query':query,'fields':['title^3','description','category']}})
                ids=[int(h['_id']) for h in res['hits']['hits']]
                by_id={r['id']:r for r in rows}
                ordered=[by_id[i] for i in ids if i in by_id]
                return ordered + [r for r in rows if r['id'] not in ids]
        except Exception:
            pass
    q=query.lower().split()
    return sorted(rows,key=lambda r:sum(1 for word in q if word in (r['title']+' '+(r.get('description') or '')).lower()),reverse=True)
