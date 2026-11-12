"""PayPal REST API helpers. Sandbox by default; never expose the secret to browser code."""
import os, requests

def base(): return 'https://api-m.sandbox.paypal.com' if os.getenv('PAYPAL_MODE','sandbox')!='live' else 'https://api-m.paypal.com'

def token():
    cid=os.getenv('PAYPAL_CLIENT_ID'); secret=os.getenv('PAYPAL_CLIENT_SECRET')
    if not cid or not secret: raise RuntimeError('PayPal is not configured. Add Sandbox Client ID and Secret to .env.')
    r=requests.post(base()+'/v1/oauth2/token',auth=(cid,secret),data={'grant_type':'client_credentials'},timeout=20); r.raise_for_status(); return r.json()['access_token']

def api(method,path,**kwargs):
    headers={'Authorization':'Bearer '+token(),'Content-Type':'application/json'}
    r=requests.request(method,base()+path,headers=headers,timeout=30,**kwargs)
    if not r.ok: raise RuntimeError(f'PayPal API error {r.status_code}: {r.text[:500]}')
    return r.json() if r.content else {}

def create_order(amount,description):
    currency=os.getenv('PAYPAL_CURRENCY','USD')
    data={'intent':'CAPTURE','purchase_units':[{'description':description[:120],'amount':{'currency_code':currency,'value':f'{amount:.2f}'}}],'application_context':{'brand_name':'LastBite','user_action':'PAY_NOW','return_url':os.getenv('PAYPAL_RETURN_URL','http://127.0.0.1:5000/payments/return'),'cancel_url':os.getenv('PAYPAL_CANCEL_URL','http://127.0.0.1:5000/payments/cancel')}}
    result=api('POST','/v2/checkout/orders',json=data)
    approve=next((x['href'] for x in result.get('links',[]) if x.get('rel')=='approve'),None)
    if not approve: raise RuntimeError('PayPal did not return an approval URL.')
    return {'id':result['id'],'approve_url':approve}

def capture_order(order_id):
    r=api('POST',f'/v2/checkout/orders/{order_id}/capture',json={})
    pu=r.get('purchase_units',[{}])[0]
    cap=pu.get('payments',{}).get('captures',[{}])[0]
    if r.get('status')!='COMPLETED' or not cap.get('id'): raise RuntimeError('PayPal capture was not completed.')
    return {'capture_id':cap['id']}

def refund_capture(capture_id): return api('POST',f'/v2/payments/captures/{capture_id}/refund',json={})

def create_subscription(plan_id):
    result=api('POST','/v1/billing/subscriptions',json={'plan_id':plan_id,'application_context':{'brand_name':'LastBite','user_action':'SUBSCRIBE_NOW','return_url':os.getenv('PAYPAL_SUBSCRIPTION_RETURN_URL','http://127.0.0.1:5000/subscriptions/return'),'cancel_url':os.getenv('PAYPAL_CANCEL_URL','http://127.0.0.1:5000/payments/cancel')}})
    approve=next((x['href'] for x in result.get('links',[]) if x.get('rel')=='approve'),None)
    if not approve: raise RuntimeError('PayPal did not return a subscription approval URL.')
    return {'id':result['id'],'approve_url':approve}
