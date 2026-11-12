import os, json, re
from google import genai
from google.genai import types

def scan_products(image_path):
    key=os.getenv('GEMINI_API_KEY')
    if not key: raise RuntimeError('Gemini is not configured. Add GEMINI_API_KEY to your .env file.')
    client=genai.Client(api_key=key)
    model=os.getenv('GEMINI_MODEL','gemini-3.8-flash')
    prompt='''Inspect this food/grocery image. Return JSON only: {"products":[{"name":"...","quantity":1,"unit":"item","category":"...","expiry_date":null,"date_confirmed":false,"date_evidence":"","confidence":"low|medium|high"}]}. Identify every distinct visible product, not just the first. Do not invent expiry dates. Only fill expiry_date when a complete date is clearly printed next to EXP, EXPIRY, EXPIRES, USE BY or BEST BEFORE. Never treat MFG/MFD/PKD/manufactured/packed-on dates as expiry. If date format/order/year is ambiguous, use null and date_confirmed false. Quantity defaults to 1 if not readable. Do not infer food safety from appearance.'''
    with open(image_path,'rb') as f: data=f.read()
    import mimetypes
    mime=mimetypes.guess_type(image_path)[0] or 'image/jpeg'
    response=client.models.generate_content(model=model,contents=[prompt,types.Part.from_bytes(data=data,mime_type=mime)],config=types.GenerateContentConfig(response_mime_type='application/json',temperature=0.1))
    text=response.text or '{}'
    try: parsed=json.loads(text)
    except json.JSONDecodeError:
        m=re.search(r'\{.*\}',text,re.S); parsed=json.loads(m.group(0)) if m else {}
    products=parsed.get('products',[])
    clean=[]
    for p in products:
        if not isinstance(p,dict) or not str(p.get('name','')).strip(): continue
        exp=p.get('expiry_date')
        confirmed=bool(exp and p.get('date_confirmed'))
        clean.append({'name':str(p['name'])[:100],'quantity':p.get('quantity') or 1,'unit':str(p.get('unit') or 'item')[:20],'category':str(p.get('category') or 'Other')[:40],'expiry_date':exp if confirmed else None,'date_confirmed':confirmed,'date_evidence':str(p.get('date_evidence') or '')[:120],'confidence':p.get('confidence','low')})
    return clean
