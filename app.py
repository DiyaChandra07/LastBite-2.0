from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from pathlib import Path
from datetime import date, datetime, timedelta
from functools import wraps
import sqlite3, os, json, uuid, re

BASE = Path(__file__).resolve().parent
DB = BASE / 'data' / 'lastbite.db'
UPLOADS = BASE / 'static' / 'uploads'
UPLOADS.mkdir(parents=True, exist_ok=True)
DB.parent.mkdir(parents=True, exist_ok=True)
app = Flask(__name__)
app.secret_key = os.getenv('LASTBITE_SECRET', 'change-this-before-deployment')
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024
ALLOWED = {'png','jpg','jpeg','webp'}


def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c

def init_db():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('user','business')), business_type TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, name TEXT NOT NULL, quantity REAL NOT NULL DEFAULT 1, unit TEXT DEFAULT 'item', category TEXT DEFAULT 'Other', expiry_date TEXT, expiry_confirmed INTEGER DEFAULT 0, image TEXT, source TEXT DEFAULT 'manual', created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(owner_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS listings(id INTEGER PRIMARY KEY, seller_id INTEGER NOT NULL, product_id INTEGER, title TEXT NOT NULL, description TEXT, quantity REAL NOT NULL, unit TEXT DEFAULT 'item', original_price REAL NOT NULL, sale_price REAL NOT NULL, expiry_date TEXT, pickup_info TEXT, status TEXT DEFAULT 'active', created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(seller_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, buyer_id INTEGER NOT NULL, listing_id INTEGER NOT NULL, quantity REAL NOT NULL, amount REAL NOT NULL, currency TEXT DEFAULT 'USD', paypal_order_id TEXT, paypal_capture_id TEXT, status TEXT DEFAULT 'pending', created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(buyer_id) REFERENCES users(id), FOREIGN KEY(listing_id) REFERENCES listings(id));
        CREATE TABLE IF NOT EXISTS transactions(id INTEGER PRIMARY KEY, user_id INTEGER, order_id INTEGER, kind TEXT, amount REAL, currency TEXT, provider_id TEXT, status TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS subscriptions(id INTEGER PRIMARY KEY, user_id INTEGER, plan TEXT, paypal_subscription_id TEXT, status TEXT DEFAULT 'pending', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS donations(id INTEGER PRIMARY KEY, user_id INTEGER, amount REAL, currency TEXT, paypal_order_id TEXT, status TEXT DEFAULT 'pending', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS preferences(user_id INTEGER PRIMARY KEY, categories TEXT DEFAULT '[]', dietary TEXT DEFAULT '', FOREIGN KEY(user_id) REFERENCES users(id));
        ''')
        # Demo listings are created only once, when the first business demo account is made.

def login_required(fn):
    @wraps(fn)
    def wrapped(*a, **kw):
        if not session.get('user_id'): return redirect(url_for('login'))
        return fn(*a, **kw)
    return wrapped

def role_required(role):
    def deco(fn):
        @wraps(fn)
        def wrapped(*a, **kw):
            if not session.get('user_id'): return redirect(url_for('login'))
            if session.get('role') != role: flash('That area is not available for this account.', 'error'); return redirect(url_for('dashboard'))
            return fn(*a, **kw)
        return wrapped
    return deco

def current_user():
    if not session.get('user_id'): return None
    with db() as c: return c.execute('SELECT * FROM users WHERE id=?',(session['user_id'],)).fetchone()

def money(v): return f"{float(v):,.2f}"
app.jinja_env.filters['money'] = money

@app.context_processor
def inject(): return {'current_user': current_user(), 'today': date.today().isoformat()}

@app.route('/')
def home():
    if session.get('user_id'): return redirect(url_for('dashboard'))
    return render_template('landing.html')

@app.route('/register', methods=['GET','POST'])
def register():
    role = request.args.get('role', request.form.get('role','user'))
    if role not in ('user','business'): role='user'
    if request.method == 'POST':
        name=request.form.get('name','').strip(); email=request.form.get('email','').strip().lower(); password=request.form.get('password','')
        btype=request.form.get('business_type','restaurant') if role=='business' else None
        if not name or not email or len(password)<8: flash('Enter your name, a valid email and a password of at least 8 characters.','error')
        else:
            try:
                with db() as c:
                    cur=c.execute('INSERT INTO users(name,email,password,role,business_type) VALUES(?,?,?,?,?)',(name,email,generate_password_hash(password),role,btype))
                    uid=cur.lastrowid; c.execute('INSERT OR IGNORE INTO preferences(user_id) VALUES(?)',(uid,))
                session.update(user_id=uid, name=name, role=role); return redirect(url_for('dashboard'))
            except sqlite3.IntegrityError: flash('An account with this email already exists.','error')
    return render_template('auth/register.html', role=role)

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        email=request.form.get('email','').strip().lower(); password=request.form.get('password','')
        with db() as c: u=c.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
        if u and check_password_hash(u['password'],password): session.update(user_id=u['id'],name=u['name'],role=u['role']); return redirect(url_for('dashboard'))
        flash('Incorrect email or password.','error')
    return render_template('auth/login.html')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('home'))

@app.route('/dashboard')
@login_required
def dashboard(): return redirect(url_for('user_dashboard' if session['role']=='user' else 'business_dashboard'))

@app.route('/user')
@role_required('user')
def user_dashboard():
    with db() as c:
        items=c.execute('SELECT * FROM products WHERE owner_id=? ORDER BY expiry_date LIMIT 5',(session['user_id'],)).fetchall()
        listings=c.execute("SELECT l.*,u.name seller FROM listings l JOIN users u ON u.id=l.seller_id WHERE l.status='active' ORDER BY l.created_at DESC LIMIT 4").fetchall()
        count=c.execute('SELECT COUNT(*) n FROM products WHERE owner_id=?',(session['user_id'],)).fetchone()['n']
        orders=c.execute("SELECT COUNT(*) n FROM orders WHERE buyer_id=? AND status='COMPLETED'",(session['user_id'],)).fetchone()['n']
    return render_template('user/dashboard.html',items=items,listings=listings,count=count,orders=orders)

@app.route('/business')
@role_required('business')
def business_dashboard():
    with db() as c:
        stock=c.execute('SELECT COUNT(*) n FROM products WHERE owner_id=?',(session['user_id'],)).fetchone()['n']
        listings=c.execute("SELECT COUNT(*) n FROM listings WHERE seller_id=? AND status='active'",(session['user_id'],)).fetchone()['n']
        sales=c.execute("SELECT COALESCE(SUM(amount),0) total FROM orders o JOIN listings l ON l.id=o.listing_id WHERE l.seller_id=? AND o.status='COMPLETED'",(session['user_id'],)).fetchone()['total']
        rows=c.execute('SELECT * FROM products WHERE owner_id=? ORDER BY expiry_date LIMIT 8',(session['user_id'],)).fetchall()
        recent=c.execute("SELECT l.title,l.sale_price,l.quantity,l.expiry_date,l.status FROM listings l WHERE l.seller_id=? ORDER BY l.created_at DESC LIMIT 5",(session['user_id'],)).fetchall()
    return render_template('business/dashboard.html',stock=stock,listings=listings,sales=sales,rows=rows,recent=recent)

@app.route('/fridge')
@role_required('user')
def fridge():
    with db() as c: rows=c.execute('SELECT * FROM products WHERE owner_id=? ORDER BY expiry_date',(session['user_id'],)).fetchall()
    return render_template('user/fridge.html',rows=rows)

@app.route('/inventory')
@role_required('business')
def inventory():
    with db() as c: rows=c.execute('SELECT * FROM products WHERE owner_id=? ORDER BY expiry_date',(session['user_id'],)).fetchall()
    return render_template('business/inventory.html',rows=rows)

@app.route('/product/add', methods=['POST'])
@login_required
def add_product():
    name=request.form.get('name','').strip(); qty=request.form.get('quantity','1'); unit=request.form.get('unit','item'); category=request.form.get('category','Other'); expiry=request.form.get('expiry_date') or None; confirmed=1 if expiry and request.form.get('expiry_confirmed') else 0
    try: qty=float(qty); assert qty>0
    except: flash('Quantity must be greater than zero.','error'); return redirect(request.referrer or url_for('dashboard'))
    if name:
        with db() as c: c.execute('INSERT INTO products(owner_id,name,quantity,unit,category,expiry_date,expiry_confirmed) VALUES(?,?,?,?,?,?,?)',(session['user_id'],name,qty,unit,category,expiry,confirmed))
        flash('Product added to inventory.','success')
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/product/<int:pid>/delete',methods=['POST'])
@login_required
def delete_product(pid):
    with db() as c: c.execute('DELETE FROM products WHERE id=? AND owner_id=?',(pid,session['user_id']))
    flash('Product removed.','success'); return redirect(request.referrer or url_for('dashboard'))

@app.route('/scan')
@login_required
def scan(): return render_template('scan.html')

@app.route('/api/scan',methods=['POST'])
@login_required
def api_scan():
    f=request.files.get('image')
    if not f or not f.filename: return jsonify(error='Choose an image first.'),400
    if f.filename.rsplit('.',1)[-1].lower() not in ALLOWED: return jsonify(error='Use PNG, JPG or WEBP.'),400
    filename=f"{uuid.uuid4().hex}_{secure_filename(f.filename)}"; path=UPLOADS/filename; f.save(path)
    try:
        from services.gemini_service import scan_products
        results=scan_products(path)
        return jsonify(products=results, image=url_for('static',filename='uploads/'+filename))
    except Exception as e: return jsonify(error=str(e), image=url_for('static',filename='uploads/'+filename)), 503

@app.route('/api/scan/save',methods=['POST'])
@login_required
def save_scan():
    data=request.get_json(silent=True) or {}; products=data.get('products',[]); saved=0
    with db() as c:
        for p in products:
            name=str(p.get('name','')).strip()
            if not name: continue
            exp=p.get('expiry_date') or None
            confirmed=1 if exp and p.get('date_confirmed') else 0
            c.execute('INSERT INTO products(owner_id,name,quantity,unit,category,expiry_date,expiry_confirmed,source) VALUES(?,?,?,?,?,?,?,?)',(session['user_id'],name,float(p.get('quantity') or 1),p.get('unit') or 'item',p.get('category') or 'Other',exp,confirmed,'gemini_scan')); saved+=1
    return jsonify(saved=saved)

@app.route('/market')
@role_required('user')
def market():
    q=request.args.get('q','').strip()
    with db() as c:
        if q: rows=c.execute("SELECT l.*,u.name seller FROM listings l JOIN users u ON u.id=l.seller_id WHERE l.status='active' AND (l.title LIKE ? OR l.description LIKE ?) ORDER BY l.created_at DESC",(f'%{q}%',f'%{q}%')).fetchall()
        else: rows=c.execute("SELECT l.*,u.name seller FROM listings l JOIN users u ON u.id=l.seller_id WHERE l.status='active' ORDER BY l.created_at DESC").fetchall()
    return render_template('user/market.html',rows=rows,q=q)

@app.route('/listings')
@role_required('business')
def listings():
    with db() as c: rows=c.execute('SELECT * FROM listings WHERE seller_id=? ORDER BY created_at DESC',(session['user_id'],)).fetchall()
    return render_template('business/listings.html',rows=rows)

@app.route('/listing/create',methods=['POST'])
@role_required('business')
def create_listing():
    try:
        title=request.form['title'].strip(); qty=float(request.form['quantity']); original=float(request.form['original_price']); sale=float(request.form['sale_price'])
        if not title or qty<=0 or original<=0 or sale<=0 or sale>original: raise ValueError()
        with db() as c: c.execute('INSERT INTO listings(seller_id,title,description,quantity,unit,original_price,sale_price,expiry_date,pickup_info) VALUES(?,?,?,?,?,?,?,?,?)',(session['user_id'],title,request.form.get('description',''),qty,request.form.get('unit','item'),original,sale,request.form.get('expiry_date') or None,request.form.get('pickup_info','')))
        flash('Surplus listing published.','success')
    except: flash('Check the listing details and prices. Sale price must not exceed original price.','error')
    return redirect(url_for('listings'))

@app.route('/listing/<int:lid>/status',methods=['POST'])
@role_required('business')
def listing_status(lid):
    status=request.form.get('status','paused')
    if status not in ('active','paused','sold_out'): status='paused'
    with db() as c: c.execute('UPDATE listings SET status=? WHERE id=? AND seller_id=?',(status,lid,session['user_id']))
    return redirect(url_for('listings'))

@app.route('/ai-insights')
@role_required('business')
def insights():
    with db() as c: rows=c.execute('SELECT * FROM products WHERE owner_id=?',(session['user_id'],)).fetchall()
    suggestions=[]
    for p in rows:
        if p['expiry_confirmed'] and p['expiry_date']:
            try:
                days=(date.fromisoformat(p['expiry_date'])-date.today()).days
                if days<=4:
                    discount=35 if days<=1 else 25 if days<=2 else 15
                    suggestions.append({'name':p['name'],'days':days,'discount':discount,'quantity':p['quantity']})
            except: pass
    return render_template('business/insights.html',suggestions=suggestions)

@app.route('/preferences',methods=['GET','POST'])
@role_required('user')
def preferences():
    cats=['Bakery','Dairy','Fruits','Vegetables','Ready meals','Pantry']
    with db() as c:
        if request.method=='POST':
            selected=request.form.getlist('categories'); dietary=request.form.get('dietary','')
            c.execute('INSERT INTO preferences(user_id,categories,dietary) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET categories=excluded.categories,dietary=excluded.dietary',(session['user_id'],json.dumps(selected),dietary)); flash('Preferences saved.','success')
        p=c.execute('SELECT * FROM preferences WHERE user_id=?',(session['user_id'],)).fetchone()
    return render_template('user/preferences.html',cats=cats,selected=json.loads(p['categories'] or '[]') if p else [],dietary=p['dietary'] if p else '')

@app.route('/payments')
@login_required
def payments():
    with db() as c:
        tx=c.execute('SELECT * FROM transactions WHERE user_id=? ORDER BY created_at DESC',(session['user_id'],)).fetchall()
        subs=c.execute('SELECT * FROM subscriptions WHERE user_id=? ORDER BY created_at DESC',(session['user_id'],)).fetchall()
    return render_template('payments.html',tx=tx,subs=subs)

@app.route('/donate',methods=['GET','POST'])
@login_required
def donate():
    if request.method=='POST':
        try: amount=float(request.form.get('amount',0)); assert 1<=amount<=10000
        except: flash('Enter a valid donation amount.','error'); return redirect(url_for('donate'))
        from services.paypal_service import create_order
        try:
            result=create_order(amount,'Food rescue donation')
            with db() as c: c.execute('INSERT INTO donations(user_id,amount,currency,paypal_order_id) VALUES(?,?,?,?)',(session['user_id'],amount,os.getenv('PAYPAL_CURRENCY','USD'),result['id']))
            return redirect(result['approve_url'])
        except Exception as e: flash(str(e),'error')
    return render_template('donate.html')

@app.route('/subscribe',methods=['GET','POST'])
@role_required('user')
def subscribe():
    plans={'Plus':os.getenv('PAYPAL_PLUS_PLAN_ID',''),'Family':os.getenv('PAYPAL_FAMILY_PLAN_ID','')}
    if request.method=='POST':
        plan=request.form.get('plan'); pid=plans.get(plan)
        if not pid: flash('Add the matching PayPal plan ID in .env before enabling this plan.','error')
        else:
            from services.paypal_service import create_subscription
            try:
                result=create_subscription(pid)
                with db() as c: c.execute('INSERT INTO subscriptions(user_id,plan,paypal_subscription_id) VALUES(?,?,?)',(session['user_id'],plan,result['id']))
                return redirect(result['approve_url'])
            except Exception as e: flash(str(e),'error')
    return render_template('subscribe.html')

@app.route('/api/paypal/create-order',methods=['POST'])
@role_required('user')
def paypal_create_order():
    data=request.get_json(silent=True) or {}; lid=data.get('listing_id'); qty=data.get('quantity',1)
    try: qty=float(qty); assert qty>0
    except: return jsonify(error='Invalid quantity.'),400
    with db() as c: item=c.execute("SELECT * FROM listings WHERE id=? AND status='active'",(lid,)).fetchone()
    if not item or qty>item['quantity']: return jsonify(error='Listing unavailable or quantity exceeds stock.'),400
    amount=round(item['sale_price']*qty,2)
    try:
        from services.paypal_service import create_order
        result=create_order(amount,f"LastBite order: {item['title']}")
        with db() as c:
            cur=c.execute('INSERT INTO orders(buyer_id,listing_id,quantity,amount,currency,paypal_order_id) VALUES(?,?,?,?,?,?)',(session['user_id'],lid,qty,amount,os.getenv('PAYPAL_CURRENCY','USD'),result['id']))
        return jsonify(order_id=cur.lastrowid,paypal_order_id=result['id'],approve_url=result['approve_url'])
    except Exception as e: return jsonify(error=str(e)),503

@app.route('/api/paypal/capture-order',methods=['POST'])
@role_required('user')
def paypal_capture_order():
    data=request.get_json(silent=True) or {}; oid=data.get('paypal_order_id')
    with db() as c: order=c.execute('SELECT * FROM orders WHERE paypal_order_id=? AND buyer_id=?',(oid,session['user_id'])).fetchone()
    if not order: return jsonify(error='Order not found.'),404
    try:
        from services.paypal_service import capture_order
        result=capture_order(oid); capture_id=result['capture_id']
        with db() as c:
            c.execute("UPDATE orders SET status='COMPLETED',paypal_capture_id=? WHERE id=?",(capture_id,order['id']))
            c.execute("UPDATE listings SET quantity=MAX(0,quantity-?) WHERE id=?",(order['quantity'],order['listing_id']))
            c.execute('INSERT INTO transactions(user_id,order_id,kind,amount,currency,provider_id,status) VALUES(?,?,?,?,?,?,?)',(session['user_id'],order['id'],'purchase',order['amount'],order['currency'],capture_id,'COMPLETED'))
        return jsonify(status='COMPLETED',capture_id=capture_id)
    except Exception as e: return jsonify(error=str(e)),400

@app.route('/api/orders/cancel',methods=['POST'])
@login_required
def cancel_order():
    data=request.get_json(silent=True) or {}; order_id=data.get('order_id')
    with db() as c:
        order=c.execute('SELECT * FROM orders WHERE id=? AND buyer_id=?',(order_id,session['user_id'])).fetchone()
        if not order: return jsonify(error='Order not found.'),404
        if order['status']!='pending': return jsonify(error='Only orders that have not been paid can be cancelled here. Completed payments must go through the refund process.'),400
        c.execute("UPDATE orders SET status='CANCELLED' WHERE id=?",(order_id,))
    return jsonify(status='CANCELLED')

@app.route('/api/paypal/refund',methods=['POST'])
@login_required
def paypal_refund():
    data=request.get_json(silent=True) or {}; order_id=data.get('order_id')
    with db() as c:
        order=c.execute('SELECT o.*,l.seller_id FROM orders o JOIN listings l ON l.id=o.listing_id WHERE o.id=?',(order_id,)).fetchone()
    if not order or order['status']!='COMPLETED': return jsonify(error='Only completed orders can be refunded.'),400
    if session['role']=='business' and order['seller_id']!=session['user_id']: return jsonify(error='Not your sale.'),403
    if session['role']=='user' and order['buyer_id']!=session['user_id']: return jsonify(error='Not your order.'),403
    try:
        from services.paypal_service import refund_capture
        result=refund_capture(order['paypal_capture_id'])
        with db() as c:
            c.execute("UPDATE orders SET status='REFUNDED' WHERE id=?",(order_id,))
            c.execute("INSERT INTO transactions(user_id,order_id,kind,amount,currency,provider_id,status) VALUES(?,?,?,?,?,?,?)",(session['user_id'],order_id,'refund',order['amount'],order['currency'],result['id'],'COMPLETED'))
        return jsonify(status='REFUNDED',refund_id=result['id'])
    except Exception as e: return jsonify(error=str(e)),400

@app.route('/payments/return')
@login_required
def paypal_return():
    token=request.args.get('token')
    if not token: flash('PayPal returned without an order reference.','error'); return redirect(url_for('payments'))
    try:
        from services.paypal_service import capture_order
        result=capture_order(token)
        with db() as c:
            order=c.execute('SELECT * FROM orders WHERE paypal_order_id=? AND buyer_id=?',(token,session['user_id'])).fetchone()
            if order:
                c.execute("UPDATE orders SET status='COMPLETED',paypal_capture_id=? WHERE id=?",(result['capture_id'],order['id']))
                c.execute("UPDATE listings SET quantity=MAX(0,quantity-?) WHERE id=?",(order['quantity'],order['listing_id']))
                c.execute('INSERT INTO transactions(user_id,order_id,kind,amount,currency,provider_id,status) VALUES(?,?,?,?,?,?,?)',(session['user_id'],order['id'],'purchase',order['amount'],order['currency'],result['capture_id'],'COMPLETED'))
            else:
                donation=c.execute('SELECT * FROM donations WHERE paypal_order_id=? AND user_id=?',(token,session['user_id'])).fetchone()
                if donation:
                    c.execute("UPDATE donations SET status='COMPLETED' WHERE id=?",(donation['id'],))
                    c.execute('INSERT INTO transactions(user_id,kind,amount,currency,provider_id,status) VALUES(?,?,?,?,?,?)',(session['user_id'],'donation',donation['amount'],donation['currency'],result['capture_id'],'COMPLETED'))
                else: raise RuntimeError('No matching LastBite order or donation was found.')
        flash('PayPal payment completed successfully.','success')
    except Exception as e: flash(f'Payment confirmation failed: {e}','error')
    return redirect(url_for('payments'))

@app.route('/subscriptions/return')
@role_required('user')
def subscription_return():
    sid=request.args.get('subscription_id')
    if sid:
        with db() as c: c.execute("UPDATE subscriptions SET status='APPROVAL_PENDING' WHERE paypal_subscription_id=? AND user_id=?",(sid,session['user_id']))
        flash('PayPal subscription approval was returned. Final activation should be confirmed by a verified PayPal webhook.','success')
    return redirect(url_for('payments'))

@app.route('/payments/cancel')
@login_required
def paypal_cancel():
    flash('PayPal checkout was cancelled. No payment was recorded as completed.','error')
    return redirect(url_for('market' if session.get('role')=='user' else 'business_dashboard'))

@app.route('/orders')
@login_required
def orders():
    with db() as c:
        if session['role']=='user': rows=c.execute('SELECT o.*,l.title FROM orders o JOIN listings l ON l.id=o.listing_id WHERE o.buyer_id=? ORDER BY o.created_at DESC',(session['user_id'],)).fetchall()
        else: rows=c.execute('SELECT o.*,l.title,u.name buyer FROM orders o JOIN listings l ON l.id=o.listing_id JOIN users u ON u.id=o.buyer_id WHERE l.seller_id=? ORDER BY o.created_at DESC',(session['user_id'],)).fetchall()
    return render_template('orders.html',rows=rows)

@app.route('/api/ai/recommendations')
@role_required('user')
def ai_recommendations():
    with db() as c:
        p=c.execute('SELECT * FROM preferences WHERE user_id=?',(session['user_id'],)).fetchone()
        cats=json.loads(p['categories'] or '[]') if p else []
        rows=c.execute("SELECT l.*,u.name seller FROM listings l JOIN users u ON u.id=l.seller_id WHERE l.status='active' ORDER BY l.created_at DESC").fetchall()
    from services.elastic_service import search_listings
    results=search_listings(rows, ' '.join(cats)) if rows else []
    return jsonify(recommendations=[dict(r) for r in results[:8]], engine='elasticsearch' if os.getenv('ELASTICSEARCH_URL') else 'sqlite-fallback')

@app.errorhandler(413)
def too_large(e): return jsonify(error='Image is too large. Maximum upload size is 10 MB.'),413

init_db()
if __name__=='__main__': app.run(debug=os.getenv('FLASK_DEBUG','false').lower()=='true',host='127.0.0.1',port=int(os.getenv('PORT',5000)))
