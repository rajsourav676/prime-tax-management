from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, jsonify
import sqlite3, os, csv, io, zipfile, datetime
from functools import wraps

APP_NAME='PRIME TAX MANAGEMENT'
TAGLINE='Complete Accounting & Tax Office Solution'
DB=os.path.join(os.path.dirname(__file__),'ptm.db')
app=Flask(__name__)
app.secret_key='prime-tax-management-secret'

GROUPS=['Capital Account','Loans','Current Liabilities','Sundry Creditors','Duties & Taxes','Current Assets','Bank Accounts','Cash-in-Hand','Sundry Debtors','Purchase Accounts','Sales Accounts','Direct Expenses','Indirect Expenses','Direct Incomes','Indirect Incomes','Stock-in-Hand']

def con():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def init_db():
    c=con(); cur=c.cursor()
    cur.execute('CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, role TEXT)')
    cur.execute('CREATE TABLE IF NOT EXISTS companies(id INTEGER PRIMARY KEY, name TEXT, owner TEXT, gstin TEXT, pan TEXT, address TEXT, fy_start TEXT, fy_end TEXT, created_at TEXT)')
    cur.execute('CREATE TABLE IF NOT EXISTS groups(id INTEGER PRIMARY KEY, company_id INTEGER, name TEXT, parent TEXT)')
    cur.execute('CREATE TABLE IF NOT EXISTS units(id INTEGER PRIMARY KEY, company_id INTEGER, symbol TEXT, formal_name TEXT)')
    cur.execute('CREATE TABLE IF NOT EXISTS ledgers(id INTEGER PRIMARY KEY, company_id INTEGER, name TEXT, group_name TEXT, gstin TEXT, mobile TEXT, opening REAL DEFAULT 0, drcr TEXT DEFAULT "Dr")')
    cur.execute('CREATE TABLE IF NOT EXISTS items(id INTEGER PRIMARY KEY, company_id INTEGER, name TEXT, unit TEXT, hsn TEXT, gst_rate REAL DEFAULT 0, opening_qty REAL DEFAULT 0, opening_rate REAL DEFAULT 0, reorder REAL DEFAULT 0)')
    cur.execute('CREATE TABLE IF NOT EXISTS vouchers(id INTEGER PRIMARY KEY, company_id INTEGER, vtype TEXT, vno TEXT, vdate TEXT, debit_ledger TEXT, credit_ledger TEXT, amount REAL, narration TEXT, optional INTEGER DEFAULT 0, cancelled INTEGER DEFAULT 0)')
    cur.execute('CREATE TABLE IF NOT EXISTS invoices(id INTEGER PRIMARY KEY, company_id INTEGER, itype TEXT, invno TEXT, invdate TEXT, party TEXT, item TEXT, qty REAL, rate REAL, gst_rate REAL, taxable REAL, gst REAL, total REAL, paid REAL DEFAULT 0, narration TEXT)')
    # V6 GST split columns: local sale/purchase = CGST+SGST, interstate = IGST
    for col in ['cgst REAL DEFAULT 0','sgst REAL DEFAULT 0','igst REAL DEFAULT 0','place TEXT DEFAULT "Local"']:
        try: cur.execute('ALTER TABLE invoices ADD COLUMN '+col)
        except Exception: pass
    cur.execute('CREATE TABLE IF NOT EXISTS clients(id INTEGER PRIMARY KEY, name TEXT, mobile TEXT, email TEXT, pan TEXT, aadhaar TEXT, gstin TEXT, gst_user TEXT, gst_hint TEXT, it_user TEXT, it_hint TEXT, work_type TEXT, work_amount REAL DEFAULT 0, received REAL DEFAULT 0, remarks TEXT)')
    cur.execute('CREATE TABLE IF NOT EXISTS gst_status(id INTEGER PRIMARY KEY, client_id INTEGER, period TEXT, gstr1 TEXT, gstr3b TEXT, due_date TEXT, remarks TEXT)')
    cur.execute('CREATE TABLE IF NOT EXISTS itr_status(id INTEGER PRIMARY KEY, client_id INTEGER, ay TEXT, itr_status TEXT, refund_status TEXT, docs TEXT, remarks TEXT)')
    cur.execute('CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, client_id INTEGER, title TEXT, due_date TEXT, status TEXT, remarks TEXT)')
    cur.execute('CREATE TABLE IF NOT EXISTS invoice_payments(id INTEGER PRIMARY KEY, company_id INTEGER, invoice_id INTEGER, pdate TEXT, ledger TEXT, amount REAL, narration TEXT)')
    cur.execute('CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, ts TEXT, user TEXT, action TEXT)')
    cur.execute('CREATE TABLE IF NOT EXISTS gst_rates(id INTEGER PRIMARY KEY, company_id INTEGER, name TEXT, rate REAL, hsn_sac TEXT)')
    cur.execute('CREATE TABLE IF NOT EXISTS client_payments(id INTEGER PRIMARY KEY, client_id INTEGER, pdate TEXT, amount REAL, mode TEXT, remarks TEXT)')
    cur.execute('INSERT OR IGNORE INTO users(username,password,role) VALUES("admin","1234","Admin")')
    c.commit(); c.close()

def log(action):
    c=con(); c.execute('INSERT INTO audit(ts,user,action) VALUES(?,?,?)',(datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),session.get('user','system'),action)); c.commit(); c.close()

def login_required(f):
    @wraps(f)
    def w(*a,**k):
        if 'user' not in session: return redirect(url_for('login'))
        return f(*a,**k)
    return w

def company_required(f):
    @wraps(f)
    def w(*a,**k):
        if 'company_id' not in session:
            flash('Pahle Company Open karo')
            return redirect(url_for('companies'))
        return f(*a,**k)
    return w

def current_company():
    if 'company_id' not in session: return None
    c=con(); r=c.execute('SELECT * FROM companies WHERE id=?',(session['company_id'],)).fetchone(); c.close(); return r

def ensure_defaults(cid):
    c=con();
    for g in GROUPS: c.execute('INSERT INTO groups(company_id,name,parent) SELECT ?,?,? WHERE NOT EXISTS(SELECT 1 FROM groups WHERE company_id=? AND name=?)',(cid,g,'Primary',cid,g))
    for u in [('Nos','Numbers'),('Kg','Kilogram'),('Pcs','Pieces')]: c.execute('INSERT INTO units(company_id,symbol,formal_name) SELECT ?,?,? WHERE NOT EXISTS(SELECT 1 FROM units WHERE company_id=? AND symbol=?)',(cid,u[0],u[1],cid,u[0]))
    for l,g in [('Cash','Cash-in-Hand'),('Bank','Bank Accounts'),('Sales','Sales Accounts'),('Purchase','Purchase Accounts'),('GST Output','Duties & Taxes'),('GST Input','Duties & Taxes'),('Sales Return','Sales Accounts'),('Purchase Return','Purchase Accounts')]:
        c.execute('INSERT INTO ledgers(company_id,name,group_name) SELECT ?,?,? WHERE NOT EXISTS(SELECT 1 FROM ledgers WHERE company_id=? AND name=?)',(cid,l,g,cid,l))
    for gr in [('GST 0%',0,''),('GST 5%',5,''),('GST 12%',12,''),('GST 18%',18,''),('GST 28%',28,'')]:
        c.execute('INSERT INTO gst_rates(company_id,name,rate,hsn_sac) SELECT ?,?,?,? WHERE NOT EXISTS(SELECT 1 FROM gst_rates WHERE company_id=? AND name=?)',(cid,gr[0],gr[1],gr[2],cid,gr[0]))
    c.commit(); c.close()

@app.context_processor
def ctx(): return dict(app_name=APP_NAME, tagline=TAGLINE, company=current_company())

@app.route('/', methods=['GET','POST'])
def login():
    if request.method=='POST':
        u=request.form['username']; p=request.form['password']; c=con(); r=c.execute('SELECT * FROM users WHERE username=? AND password=?',(u,p)).fetchone(); c.close()
        if r:
            session.clear(); session['user']=u; flash('Welcome to Prime Tax Management'); return redirect(url_for('companies'))
        flash('Wrong username or password')
    return render_template('login.html')
@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

@app.route('/companies', methods=['GET','POST'])
@login_required
def companies():
    c=con()
    if request.method=='POST':
        d=request.form; cur=c.execute('INSERT INTO companies(name,owner,gstin,pan,address,fy_start,fy_end,created_at) VALUES(?,?,?,?,?,?,?,?)',(d['name'],d.get('owner',''),d.get('gstin',''),d.get('pan',''),d.get('address',''),d.get('fy_start','2025-04-01'),d.get('fy_end','2026-03-31'),datetime.date.today().isoformat()))
        cid=cur.lastrowid; c.commit(); ensure_defaults(cid); log('Company Created '+d['name']); flash('Company Created')
    rows=c.execute('SELECT * FROM companies ORDER BY id DESC').fetchall(); c.close(); return render_template('companies.html', rows=rows)
@app.route('/open_company/<int:cid>')
@login_required
def open_company(cid): session['company_id']=cid; ensure_defaults(cid); flash('Company Opened'); return redirect(url_for('dashboard'))
@app.route('/company_delete/<int:cid>')
@login_required
def company_delete(cid):
    c=con()
    for t in ['groups','units','ledgers','items','vouchers','invoices']:
        c.execute(f'DELETE FROM {t} WHERE company_id=?',(cid,))
    c.execute('DELETE FROM companies WHERE id=?',(cid,))
    if session.get('company_id')==cid:
        session.pop('company_id', None)
    c.commit(); c.close(); flash('Company Deleted with related company data'); return redirect(url_for('companies'))

@app.route('/dashboard')
@login_required
@company_required
def dashboard():
    cid=session['company_id']; c=con()
    cash=ledger_balance(cid,'Cash'); bank=ledger_balance(cid,'Bank')
    rec=sum([ledger_balance(cid,r['name']) for r in c.execute('SELECT name FROM ledgers WHERE company_id=? AND group_name="Sundry Debtors"',(cid,)).fetchall()])
    pay=sum([-ledger_balance(cid,r['name']) for r in c.execute('SELECT name FROM ledgers WHERE company_id=? AND group_name="Sundry Creditors"',(cid,)).fetchall()])
    clients_due=c.execute('SELECT SUM(work_amount-received) x FROM clients').fetchone()['x'] or 0
    c.close(); return render_template('dashboard.html', cash=cash, bank=bank, rec=rec, pay=pay, clients_due=clients_due)

@app.route('/masters/<kind>', methods=['GET','POST'])
@login_required
@company_required
def masters(kind):
    cid=session['company_id']; c=con()
    if request.method=='POST':
        d=request.form
        if kind=='group': c.execute('INSERT INTO groups(company_id,name,parent) VALUES(?,?,?)',(cid,d['name'],d.get('parent','Primary')))
        elif kind=='unit': c.execute('INSERT INTO units(company_id,symbol,formal_name) VALUES(?,?,?)',(cid,d['symbol'],d.get('formal_name','')))
        elif kind=='ledger': c.execute('INSERT INTO ledgers(company_id,name,group_name,gstin,mobile,opening,drcr) VALUES(?,?,?,?,?,?,?)',(cid,d['name'],d['group_name'],d.get('gstin',''),d.get('mobile',''),float(d.get('opening') or 0),d.get('drcr','Dr')))
        elif kind=='item': c.execute('INSERT INTO items(company_id,name,unit,hsn,gst_rate,opening_qty,opening_rate,reorder) VALUES(?,?,?,?,?,?,?,?)',(cid,d['name'],d.get('unit','Nos'),d.get('hsn',''),float(d.get('gst_rate') or 0),float(d.get('opening_qty') or 0),float(d.get('opening_rate') or 0),float(d.get('reorder') or 0)))
        c.commit(); flash('Saved')
    data={'group':('groups','SELECT * FROM groups WHERE company_id=?'), 'unit':('units','SELECT * FROM units WHERE company_id=?'), 'ledger':('ledgers','SELECT * FROM ledgers WHERE company_id=?'), 'item':('items','SELECT * FROM items WHERE company_id=?')}[kind]
    rows=c.execute(data[1],(cid,)).fetchall(); groups=c.execute('SELECT name FROM groups WHERE company_id=?',(cid,)).fetchall(); units=c.execute('SELECT symbol FROM units WHERE company_id=?',(cid,)).fetchall(); c.close()
    return render_template('masters.html', kind=kind, rows=rows, groups=groups, units=units)


@app.route('/api/master_options/<kind>')
@login_required
@company_required
def api_master_options(kind):
    """Voucher/Invoice field ke andar Alt+C se master create karne ke liye options."""
    cid=session['company_id']; c=con()
    if kind=='ledger':
        groups=[r['name'] for r in c.execute('SELECT name FROM groups WHERE company_id=? ORDER BY name',(cid,)).fetchall()]
        c.close(); return jsonify(ok=True, kind='ledger', groups=groups)
    if kind=='item':
        units=[r['symbol'] for r in c.execute('SELECT symbol FROM units WHERE company_id=? ORDER BY symbol',(cid,)).fetchall()]
        c.close(); return jsonify(ok=True, kind='item', units=units)
    if kind=='unit':
        c.close(); return jsonify(ok=True, kind='unit')
    c.close(); return jsonify(ok=False, error='Invalid master type'), 400

@app.route('/api/create_master/<kind>', methods=['POST'])
@login_required
@company_required
def api_create_master(kind):
    """Tally style: current entry field par Alt+C dabao aur Ledger/Item/Unit create karo."""
    cid=session['company_id']; d=request.get_json(silent=True) or request.form; c=con()
    try:
        if kind=='ledger':
            name=(d.get('name') or '').strip()
            if not name: return jsonify(ok=False,error='Ledger name required'),400
            old=c.execute('SELECT name FROM ledgers WHERE company_id=? AND lower(name)=lower(?)',(cid,name)).fetchone()
            if not old:
                c.execute('INSERT INTO ledgers(company_id,name,group_name,gstin,mobile,opening,drcr) VALUES(?,?,?,?,?,?,?)',(cid,name,d.get('group_name') or 'Sundry Debtors',d.get('gstin',''),d.get('mobile',''),safe_amount(d.get('opening')),d.get('drcr') or 'Dr'))
                c.commit(); log('Inline Ledger Created '+name)
            c.close(); return jsonify(ok=True,kind='ledger',value=name,label=name)
        if kind=='item':
            name=(d.get('name') or '').strip()
            if not name: return jsonify(ok=False,error='Stock item name required'),400
            old=c.execute('SELECT name FROM items WHERE company_id=? AND lower(name)=lower(?)',(cid,name)).fetchone()
            if not old:
                c.execute('INSERT INTO items(company_id,name,unit,hsn,gst_rate,opening_qty,opening_rate,reorder) VALUES(?,?,?,?,?,?,?,?)',(cid,name,d.get('unit') or 'Nos',d.get('hsn',''),safe_amount(d.get('gst_rate')),safe_amount(d.get('opening_qty')),safe_amount(d.get('opening_rate')),safe_amount(d.get('reorder'))))
                c.commit(); log('Inline Stock Item Created '+name)
            c.close(); return jsonify(ok=True,kind='item',value=name,label=name,gst_rate=safe_amount(d.get('gst_rate')))
        if kind=='unit':
            symbol=(d.get('symbol') or d.get('name') or '').strip()
            if not symbol: return jsonify(ok=False,error='Unit symbol required'),400
            old=c.execute('SELECT symbol FROM units WHERE company_id=? AND lower(symbol)=lower(?)',(cid,symbol)).fetchone()
            if not old:
                c.execute('INSERT INTO units(company_id,symbol,formal_name) VALUES(?,?,?)',(cid,symbol,d.get('formal_name','')))
                c.commit(); log('Inline Unit Created '+symbol)
            c.close(); return jsonify(ok=True,kind='unit',value=symbol,label=symbol)
    except Exception as e:
        c.rollback(); c.close(); return jsonify(ok=False,error=str(e)),500
    c.close(); return jsonify(ok=False,error='Invalid master type'),400

@app.route('/gst_rates', methods=['GET','POST'])
@login_required
@company_required
def gst_rates():
    cid=session['company_id']; c=con()
    if request.method=='POST':
        d=request.form
        c.execute('INSERT INTO gst_rates(company_id,name,rate,hsn_sac) VALUES(?,?,?,?)',(cid,d.get('name') or ('GST '+str(d.get('rate','0'))+'%'),safe_amount(d.get('rate')),d.get('hsn_sac','')))
        c.commit(); flash('GST Rate/HSN Saved')
    rows=c.execute('SELECT * FROM gst_rates WHERE company_id=? ORDER BY rate,name',(cid,)).fetchall(); c.close()
    return render_template('gst_rates.html', rows=rows)

@app.route('/edit/<kind>/<int:id>', methods=['GET','POST'])
@login_required
@company_required
def edit_row(kind,id):
    cid=session['company_id']; c=con()
    allowed={'group':'groups','unit':'units','ledger':'ledgers','item':'items','voucher':'vouchers','invoice':'invoices'}
    if kind not in allowed:
        flash('Invalid edit'); return redirect(url_for('dashboard'))
    table=allowed[kind]
    row=c.execute(f'SELECT * FROM {table} WHERE id=? AND company_id=?',(id,cid)).fetchone()
    if not row:
        c.close(); flash('Record nahi mila'); return redirect(url_for('dashboard'))
    if request.method=='POST':
        d=request.form
        if kind=='group': c.execute('UPDATE groups SET name=?, parent=? WHERE id=? AND company_id=?',(d['name'],d.get('parent','Primary'),id,cid))
        elif kind=='unit': c.execute('UPDATE units SET symbol=?, formal_name=? WHERE id=? AND company_id=?',(d['symbol'],d.get('formal_name',''),id,cid))
        elif kind=='ledger': c.execute('UPDATE ledgers SET name=?, group_name=?, gstin=?, mobile=?, opening=?, drcr=? WHERE id=? AND company_id=?',(d['name'],d['group_name'],d.get('gstin',''),d.get('mobile',''),safe_amount(d.get('opening')),d.get('drcr','Dr'),id,cid))
        elif kind=='item': c.execute('UPDATE items SET name=?, unit=?, hsn=?, gst_rate=?, opening_qty=?, opening_rate=?, reorder=? WHERE id=? AND company_id=?',(d['name'],d.get('unit','Nos'),d.get('hsn',''),safe_amount(d.get('gst_rate')),safe_amount(d.get('opening_qty')),safe_amount(d.get('opening_rate')),safe_amount(d.get('reorder')),id,cid))
        elif kind=='voucher': c.execute('UPDATE vouchers SET vno=?, vdate=?, debit_ledger=?, credit_ledger=?, amount=?, narration=?, optional=?, cancelled=? WHERE id=? AND company_id=?',(d.get('vno'),d.get('vdate'),d.get('debit_ledger'),d.get('credit_ledger'),safe_amount(d.get('amount')),d.get('narration',''),1 if d.get('optional') else 0,1 if d.get('cancelled') else 0,id,cid))
        elif kind=='invoice':
            qty=safe_amount(d.get('qty')); rate=safe_amount(d.get('rate')); gst_rate=safe_amount(d.get('gst_rate')); taxable=round(qty*rate,2); place=d.get('place','Local')
            cgst,sgst,igst,gst=calc_gst_split(taxable,gst_rate,place); total=round(taxable+gst,2)
            create_default_party_if_missing(cid,d.get('party'),d.get('itype'))
            c.execute('UPDATE invoices SET itype=?, invno=?, invdate=?, party=?, item=?, qty=?, rate=?, gst_rate=?, taxable=?, gst=?, cgst=?, sgst=?, igst=?, total=?, paid=?, narration=?, place=? WHERE id=? AND company_id=?',(d.get('itype'),d.get('invno'),d.get('invdate'),d.get('party'),d.get('item'),qty,rate,gst_rate,taxable,gst,cgst,sgst,igst,total,safe_amount(d.get('paid')),d.get('narration',''),place,id,cid))
        c.commit(); c.close(); flash('Alter/Update Saved'); return redirect(request.referrer or url_for('dashboard'))
    groups=c.execute('SELECT name FROM groups WHERE company_id=?',(cid,)).fetchall(); units=c.execute('SELECT symbol FROM units WHERE company_id=?',(cid,)).fetchall(); ledgers=c.execute('SELECT name FROM ledgers WHERE company_id=? ORDER BY name',(cid,)).fetchall(); items=c.execute('SELECT name FROM items WHERE company_id=? ORDER BY name',(cid,)).fetchall(); c.close()
    return render_template('edit.html', kind=kind, row=row, groups=groups, units=units, ledgers=ledgers, items=items)
@app.route('/delete/<kind>/<int:id>')
@login_required
@company_required
def delete_row(kind,id):
    table={'group':'groups','unit':'units','ledger':'ledgers','item':'items','voucher':'vouchers','invoice':'invoices','client':'clients'}[kind]
    c=con()
    if table in ['groups','units','ledgers','items','vouchers','invoices']:
        c.execute(f'DELETE FROM {table} WHERE id=? AND company_id=?',(id,session['company_id']))
    else:
        c.execute(f'DELETE FROM {table} WHERE id=?',(id,))
    c.commit(); c.close(); flash('Deleted safely'); return redirect(request.referrer or url_for('dashboard'))

def next_no(cid,typ,table):
    c=con(); n=c.execute(f'SELECT COUNT(*) c FROM {table} WHERE company_id=? AND '+('vtype' if table=='vouchers' else 'itype')+'=?',(cid,typ)).fetchone()['c']+1; c.close(); return typ[:2].upper()+str(n).zfill(4)
@app.route('/voucher/<vtype>', methods=['GET','POST'])
@login_required
@company_required
def voucher(vtype):
    cid=session['company_id']; c=con(); ledgers=c.execute('SELECT name FROM ledgers WHERE company_id=? ORDER BY name',(cid,)).fetchall()
    if request.method=='POST':
        d=request.form; c.execute('INSERT INTO vouchers(company_id,vtype,vno,vdate,debit_ledger,credit_ledger,amount,narration,optional) VALUES(?,?,?,?,?,?,?,?,?)',(cid,vtype,d.get('vno') or next_no(cid,vtype,'vouchers'),d.get('vdate'),d.get('debit_ledger'),d.get('credit_ledger'),float(d.get('amount') or 0),d.get('narration',''),1 if d.get('optional') else 0)); c.commit(); flash(vtype+' Saved')
    rows=c.execute('SELECT * FROM vouchers WHERE company_id=? AND vtype=? ORDER BY vdate DESC,id DESC',(cid,vtype)).fetchall(); c.close(); return render_template('voucher.html', vtype=vtype, ledgers=ledgers, rows=rows, today=datetime.date.today().isoformat())


def calc_gst_split(taxable, gst_rate, place='Local'):
    taxable=safe_amount(taxable); gst_rate=safe_amount(gst_rate)
    gst=round(taxable*gst_rate/100,2)
    if (place or 'Local')=='Interstate':
        return 0.0,0.0,gst,gst
    half=round(gst/2,2)
    return half, round(gst-half,2), 0.0, gst

def post_invoice_payment_if_any(c, cid, inv_id, invno, itype, party, paid, pdate, ledger='Cash'):
    paid=safe_amount(paid)
    if paid<=0: return
    c.execute('INSERT INTO invoice_payments(company_id,invoice_id,pdate,ledger,amount,narration) VALUES(?,?,?,?,?,?)',(cid,inv_id,pdate,ledger,paid,'Auto payment at invoice entry'))
    if itype in ['Sales','Credit Note']:
        # Sales receipt: Cash/Bank Dr, Party Cr. Credit Note refund also follows cash/bank out normally, but party settlement is kept via voucher.
        vt='Receipt' if itype=='Sales' else 'Payment'
        debit, credit = (ledger, party) if vt=='Receipt' else (party, ledger)
    else:
        vt='Payment' if itype=='Purchase' else 'Receipt'
        debit, credit = (party, ledger) if vt=='Payment' else (ledger, party)
    c.execute('INSERT INTO vouchers(company_id,vtype,vno,vdate,debit_ledger,credit_ledger,amount,narration) VALUES(?,?,?,?,?,?,?,?)',(cid,vt,next_no(cid,vt,'vouchers'),pdate,debit,credit,paid,'Auto Against Invoice '+invno))

@app.route('/invoice/<itype>', methods=['GET','POST'])
@login_required
@company_required
def invoice(itype):
    cid=session['company_id']; c=con(); ledgers=c.execute('SELECT name FROM ledgers WHERE company_id=? ORDER BY name',(cid,)).fetchall(); items=c.execute('SELECT * FROM items WHERE company_id=? ORDER BY name',(cid,)).fetchall()
    if request.method=='POST':
        d=request.form
        # invoice party ko automatic Sundry Debtor/Creditor ledger se connect rakhta hai
        create_default_party_if_missing(cid, d.get('party'), itype)
        qty=safe_amount(d.get('qty')); rate=safe_amount(d.get('rate')); gst_rate=safe_amount(d.get('gst_rate')); taxable=round(qty*rate,2)
        place=d.get('place','Local'); cgst,sgst,igst,gst=calc_gst_split(taxable,gst_rate,place); total=round(taxable+gst,2)
        invno=d.get('invno') or next_no(cid,itype,'invoices'); paid=safe_amount(d.get('paid'))
        cur=c.execute('INSERT INTO invoices(company_id,itype,invno,invdate,party,item,qty,rate,gst_rate,taxable,gst,cgst,sgst,igst,total,paid,narration,place) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(cid,itype,invno,d.get('invdate'),d.get('party'),d.get('item'),qty,rate,gst_rate,taxable,gst,cgst,sgst,igst,total,paid,d.get('narration',''),place))
        post_invoice_payment_if_any(c,cid,cur.lastrowid,invno,itype,d.get('party'),paid,d.get('invdate'),d.get('pay_ledger','Cash'))
        c.commit(); flash(itype+' Saved: Ledger + Stock + CGST/SGST/IGST connected')
    rows=c.execute('SELECT * FROM invoices WHERE company_id=? AND itype=? ORDER BY invdate DESC,id DESC',(cid,itype)).fetchall(); c.close(); return render_template('invoice.html', itype=itype, ledgers=ledgers, items=items, rows=rows, today=datetime.date.today().isoformat())

def invoice_effect(inv, ledger_name):
    """Tally-style invoice posting. Positive = Debit, Negative = Credit.
    Payment is NOT reduced here; invoice-wise payment creates separate Receipt/Payment voucher.
    """
    total=float(inv['total'] or 0); taxable=float(inv['taxable'] or 0)
    gst=float(inv['gst'] or 0); party=inv['party']; typ=inv['itype']
    e=0.0
    if typ=='Sales':
        if ledger_name==party: e += total
        if ledger_name=='Sales': e -= taxable
        if ledger_name=='GST Output': e -= gst
    elif typ=='Purchase':
        if ledger_name==party: e -= total
        if ledger_name=='Purchase': e += taxable
        if ledger_name=='GST Input': e += gst
    elif typ=='Credit Note':  # Sales return: Sales Return Dr + GST Output Dr, Customer Cr
        if ledger_name==party: e -= total
        if ledger_name=='Sales Return': e += taxable
        if ledger_name=='GST Output': e += gst
    elif typ=='Debit Note':   # Purchase return: Supplier Dr, Purchase Return Cr + GST Input Cr
        if ledger_name==party: e += total
        if ledger_name=='Purchase Return': e -= taxable
        if ledger_name=='GST Input': e -= gst
    return e

def ledger_balance(cid,name):
    c=con(); bal=0.0
    r=c.execute('SELECT opening,drcr FROM ledgers WHERE company_id=? AND name=?',(cid,name)).fetchone()
    if r: bal += (float(r['opening'] or 0) if r['drcr']=='Dr' else -float(r['opening'] or 0))
    for v in c.execute('SELECT * FROM vouchers WHERE company_id=? AND cancelled=0 AND optional=0',(cid,)).fetchall():
        amt=float(v['amount'] or 0)
        if v['debit_ledger']==name: bal+=amt
        if v['credit_ledger']==name: bal-=amt
    for inv in c.execute('SELECT * FROM invoices WHERE company_id=?',(cid,)).fetchall():
        bal += invoice_effect(inv, name)
    c.close(); return round(bal,2)

def stock_qty_value(cid, item_name):
    c=con(); it=c.execute('SELECT * FROM items WHERE company_id=? AND name=?',(cid,item_name)).fetchone()
    qty=val=0.0
    if it:
        qty=float(it['opening_qty'] or 0); val=qty*float(it['opening_rate'] or 0)
    for inv in c.execute('SELECT * FROM invoices WHERE company_id=? AND item=?',(cid,item_name)).fetchall():
        q=float(inv['qty'] or 0); taxable=float(inv['taxable'] or 0)
        if inv['itype']=='Purchase' or inv['itype']=='Credit Note':
            # purchase adds stock, sales return adds stock
            qty += q; val += taxable
        elif inv['itype']=='Sales' or inv['itype']=='Debit Note':
            # sales reduces stock, purchase return reduces stock
            qty -= q; val -= q*float(inv['rate'] or 0)
    c.close(); return round(qty,2), round(val,2)

def safe_amount(v):
    try: return float(v or 0)
    except Exception: return 0.0

def create_default_party_if_missing(cid, party, typ):
    if not party: return
    c=con(); exists=c.execute('SELECT id FROM ledgers WHERE company_id=? AND name=?',(cid,party)).fetchone()
    if not exists:
        group='Sundry Debtors' if typ in ['Sales','Credit Note'] else 'Sundry Creditors'
        c.execute('INSERT INTO ledgers(company_id,name,group_name) VALUES(?,?,?)',(cid,party,group)); c.commit()
    c.close()



def group_ledger_rows(cid, group_names):
    """Return Tally-style ledger rows for selected groups with debit-positive balances."""
    c=con(); out=[]
    q_marks=','.join(['?']*len(group_names))
    rows=c.execute(f'SELECT * FROM ledgers WHERE company_id=? AND group_name IN ({q_marks}) ORDER BY group_name,name',[cid]+list(group_names)).fetchall()
    for l in rows:
        bal=ledger_balance(cid,l['name'])
        if abs(bal)>0.01:
            out.append(dict(group=l['group_name'], ledger=l['name'], amount=round(bal,2)))
    c.close(); return out

def stock_opening_value(cid):
    c=con(); total=0.0
    for it in c.execute('SELECT opening_qty, opening_rate FROM items WHERE company_id=?',(cid,)).fetchall():
        total += float(it['opening_qty'] or 0)*float(it['opening_rate'] or 0)
    c.close(); return round(total,2)

def stock_closing_value(cid):
    c=con(); total=0.0
    for it in c.execute('SELECT name FROM items WHERE company_id=?',(cid,)).fetchall():
        total += stock_qty_value(cid,it['name'])[1]
    c.close(); return round(total,2)

def profit_loss_statement(cid):
    """Detailed Tally-style Trading + Profit & Loss statement."""
    opening_stock=stock_opening_value(cid)
    closing_stock=stock_closing_value(cid)
    purchase_rows=group_ledger_rows(cid,['Purchase Accounts'])
    sales_rows=group_ledger_rows(cid,['Sales Accounts'])
    direct_exp_rows=group_ledger_rows(cid,['Direct Expenses'])
    direct_inc_rows=group_ledger_rows(cid,['Direct Incomes'])
    indirect_exp_rows=group_ledger_rows(cid,['Indirect Expenses'])
    indirect_inc_rows=group_ledger_rows(cid,['Indirect Incomes'])

    purchases=sum(max(r['amount'],0) for r in purchase_rows) + sum(max(r['amount'],0) for r in direct_exp_rows)
    sales=sum(abs(r['amount']) for r in sales_rows if r['amount']<0) + sum(abs(r['amount']) for r in direct_inc_rows if r['amount']<0)
    # Sales Return / Purchase Return are naturally in same groups with opposite balance, so include signed totals too.
    purchase_net=sum(r['amount'] for r in purchase_rows) + sum(r['amount'] for r in direct_exp_rows)
    sales_net=sum(-r['amount'] for r in sales_rows) + sum(-r['amount'] for r in direct_inc_rows)
    trading_debit=opening_stock + purchase_net
    trading_credit=sales_net + closing_stock
    gross_profit=round(trading_credit-trading_debit,2)

    indirect_exp=sum(r['amount'] for r in indirect_exp_rows)
    indirect_inc=sum(-r['amount'] for r in indirect_inc_rows)
    net_profit=round(gross_profit + indirect_inc - indirect_exp,2)
    return dict(
        opening_stock=opening_stock, closing_stock=closing_stock,
        purchase_rows=purchase_rows, sales_rows=sales_rows,
        direct_exp_rows=direct_exp_rows, direct_inc_rows=direct_inc_rows,
        indirect_exp_rows=indirect_exp_rows, indirect_inc_rows=indirect_inc_rows,
        purchase_net=round(purchase_net,2), sales_net=round(sales_net,2),
        trading_debit=round(trading_debit,2), trading_credit=round(trading_credit,2),
        gross_profit=gross_profit, indirect_exp=round(indirect_exp,2), indirect_inc=round(indirect_inc,2), net_profit=net_profit
    )

def balance_sheet_statement(cid):
    """Detailed Tally-style Balance Sheet with grouped Assets/Liabilities and P&L effect."""
    pl=profit_loss_statement(cid); net_profit=pl['net_profit']
    liability_groups=['Capital Account','Loans','Current Liabilities','Sundry Creditors','Duties & Taxes']
    asset_groups=['Current Assets','Bank Accounts','Cash-in-Hand','Sundry Debtors','Stock-in-Hand']
    c=con(); ledgers=c.execute('SELECT * FROM ledgers WHERE company_id=? ORDER BY group_name,name',(cid,)).fetchall(); c.close()
    liabilities=[]; assets=[]
    for l in ledgers:
        b=ledger_balance(cid,l['name'])
        if abs(b)<=0.01: continue
        row=dict(group=l['group_name'], ledger=l['name'], amount=round(abs(b),2), raw=round(b,2))
        # credit balances are liabilities; debit balances are assets, with group fallback
        if b < 0 or l['group_name'] in liability_groups:
            liabilities.append(row)
        else:
            assets.append(row)
    closing_stock=stock_closing_value(cid)
    if abs(closing_stock)>0.01:
        assets.append(dict(group='Stock-in-Hand', ledger='Closing Stock', amount=round(closing_stock,2), raw=round(closing_stock,2)))
    if abs(net_profit)>0.01:
        if net_profit>0:
            liabilities.append(dict(group='Profit & Loss A/c', ledger='Net Profit', amount=round(net_profit,2), raw=round(-net_profit,2)))
        else:
            assets.append(dict(group='Profit & Loss A/c', ledger='Net Loss', amount=round(abs(net_profit),2), raw=round(abs(net_profit),2)))
    total_liab=round(sum(r['amount'] for r in liabilities),2)
    total_assets=round(sum(r['amount'] for r in assets),2)
    diff=round(total_assets-total_liab,2)
    return dict(liabilities=liabilities, assets=assets, total_liab=total_liab, total_assets=total_assets, diff=diff, net_profit=net_profit)

@app.route('/reports/<rtype>')
@login_required
@company_required
def reports(rtype):
    cid=session['company_id']; c=con(); data=[]; title=rtype.upper()
    if rtype=='daybook':
        vouchers=[dict(date=r['vdate'], type=r['vtype'], no=r['vno'], debit=r['debit_ledger'], credit=r['credit_ledger'], amount=r['amount'], narration=r['narration']) for r in c.execute('SELECT * FROM vouchers WHERE company_id=? ORDER BY vdate DESC,id DESC',(cid,)).fetchall()]
        invoices=[dict(date=r['invdate'], type=r['itype'], no=r['invno'], debit=(r['party'] if r['itype']=='Sales' else ('Purchase/GST Input' if r['itype']=='Purchase' else ('Sales Return/GST Output' if r['itype']=='Credit Note' else r['party']))), credit=('Sales/GST Output' if r['itype']=='Sales' else (r['party'] if r['itype']=='Purchase' else (r['party'] if r['itype']=='Credit Note' else 'Purchase Return/GST Input'))), amount=r['total'], narration=r['item']) for r in c.execute('SELECT * FROM invoices WHERE company_id=? ORDER BY invdate DESC,id DESC',(cid,)).fetchall()]
        data=sorted(vouchers+invoices, key=lambda x:(x.get('date') or '', x.get('no') or ''), reverse=True)
    elif rtype in ['trial','ledger','outstanding']:
        leds=c.execute('SELECT * FROM ledgers WHERE company_id=? ORDER BY group_name,name',(cid,)).fetchall()
        data=[dict(name=l['name'], group=l['group_name'], balance=ledger_balance(cid,l['name'])) for l in leds]
        if rtype=='outstanding':
            data=[r for r in data if r['group'] in ['Sundry Debtors','Sundry Creditors'] and abs(r['balance'])>0.01]
    elif rtype=='pl':
        stmt=profit_loss_statement(cid)
        c.close(); return render_template('pl_tally.html', rtype=rtype, title='PROFIT & LOSS A/C', stmt=stmt)
    elif rtype=='balance':
        stmt=balance_sheet_statement(cid)
        c.close(); return render_template('balance_tally.html', rtype=rtype, title='BALANCE SHEET', stmt=stmt)
    elif rtype=='stock':
        items=c.execute('SELECT * FROM items WHERE company_id=?',(cid,)).fetchall()
        for it in items:
            qty,val=stock_qty_value(cid,it['name'])
            data.append(dict(name=it['name'], unit=it['unit'], qty=qty, value=val, reorder=it['reorder'], low=qty<=float(it['reorder'] or 0)))
    elif rtype=='gst':
        data=c.execute('SELECT itype, SUM(taxable) taxable, SUM(cgst) cgst, SUM(sgst) sgst, SUM(igst) igst, SUM(gst) gst, SUM(total) total FROM invoices WHERE company_id=? GROUP BY itype',(cid,)).fetchall()
    elif rtype=='sales_register':
        data=c.execute('SELECT invdate date, invno no, party, item, taxable, cgst, sgst, igst, gst, total, paid, total-COALESCE(paid,0) due FROM invoices WHERE company_id=? AND itype IN ("Sales","Credit Note") ORDER BY invdate DESC,id DESC',(cid,)).fetchall()
    elif rtype=='purchase_register':
        data=c.execute('SELECT invdate date, invno no, party, item, taxable, cgst, sgst, igst, gst, total, paid, total-COALESCE(paid,0) due FROM invoices WHERE company_id=? AND itype IN ("Purchase","Debit Note") ORDER BY invdate DESC,id DESC',(cid,)).fetchall()
    elif rtype=='cashbook':
        c.close(); return redirect(url_for('ledger_report', name='Cash'))
    elif rtype=='bankbook':
        c.close(); return redirect(url_for('ledger_report', name='Bank'))
    elif rtype=='audit':
        data=c.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 200').fetchall()
    c.close(); return render_template('reports.html', rtype=rtype, data=data, title=title)

@app.route('/clients', methods=['GET','POST'])
@login_required
def clients():
    c=con()
    if request.method=='POST':
        d=request.form; c.execute('INSERT INTO clients(name,mobile,email,pan,aadhaar,gstin,gst_user,gst_hint,it_user,it_hint,work_type,work_amount,received,remarks) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(d['name'],d.get('mobile',''),d.get('email',''),d.get('pan',''),d.get('aadhaar',''),d.get('gstin',''),d.get('gst_user',''),d.get('gst_hint',''),d.get('it_user',''),d.get('it_hint',''),d.get('work_type',''),float(d.get('work_amount') or 0),float(d.get('received') or 0),d.get('remarks',''))); c.commit(); flash('Client Saved')
    rows=c.execute('SELECT *, work_amount-received due FROM clients ORDER BY id DESC').fetchall(); c.close(); return render_template('clients.html', rows=rows)
@app.route('/status/<stype>', methods=['GET','POST'])
@login_required
def status(stype):
    c=con(); clients=c.execute('SELECT id,name FROM clients ORDER BY name').fetchall()
    if request.method=='POST':
        d=request.form
        if stype=='gst': c.execute('INSERT INTO gst_status(client_id,period,gstr1,gstr3b,due_date,remarks) VALUES(?,?,?,?,?,?)',(d['client_id'],d['period'],d.get('gstr1','Pending'),d.get('gstr3b','Pending'),d.get('due_date',''),d.get('remarks','')))
        elif stype=='itr': c.execute('INSERT INTO itr_status(client_id,ay,itr_status,refund_status,docs,remarks) VALUES(?,?,?,?,?,?)',(d['client_id'],d['ay'],d.get('itr_status','Pending'),d.get('refund_status',''),d.get('docs',''),d.get('remarks','')))
        else: c.execute('INSERT INTO tasks(client_id,title,due_date,status,remarks) VALUES(?,?,?,?,?)',(d['client_id'],d['title'],d.get('due_date',''),d.get('status','Pending'),d.get('remarks','')))
        c.commit(); flash('Saved')
    table={'gst':'gst_status','itr':'itr_status','task':'tasks'}[stype]
    rows=c.execute(f'SELECT {table}.*, clients.name client FROM {table} LEFT JOIN clients ON clients.id={table}.client_id ORDER BY {table}.id DESC').fetchall(); c.close(); return render_template('status.html', stype=stype, clients=clients, rows=rows)



@app.route('/invoice_payment', methods=['GET','POST'])
@login_required
@company_required
def invoice_payment():
    cid=session['company_id']; c=con()
    if request.method=='POST':
        d=request.form; iid=int(d.get('invoice_id'))
        inv=c.execute('SELECT * FROM invoices WHERE id=? AND company_id=?',(iid,cid)).fetchone()
        if inv:
            amt=safe_amount(d.get('amount'))
            c.execute('INSERT INTO invoice_payments(company_id,invoice_id,pdate,ledger,amount,narration) VALUES(?,?,?,?,?,?)',(cid,iid,d.get('pdate'),d.get('ledger','Cash'),amt,d.get('narration','')))
            c.execute('UPDATE invoices SET paid=COALESCE(paid,0)+? WHERE id=? AND company_id=?',(amt,iid,cid))
            # also create accounting receipt/payment voucher
            if inv['itype'] in ['Sales','Credit Note']:
                c.execute('INSERT INTO vouchers(company_id,vtype,vno,vdate,debit_ledger,credit_ledger,amount,narration) VALUES(?,?,?,?,?,?,?,?)',(cid,'Receipt',next_no(cid,'Receipt','vouchers'),d.get('pdate'),d.get('ledger','Cash'),inv['party'],amt,'Against Invoice '+inv['invno']))
            else:
                c.execute('INSERT INTO vouchers(company_id,vtype,vno,vdate,debit_ledger,credit_ledger,amount,narration) VALUES(?,?,?,?,?,?,?,?)',(cid,'Payment',next_no(cid,'Payment','vouchers'),d.get('pdate'),inv['party'],d.get('ledger','Cash'),amt,'Against Invoice '+inv['invno']))
            c.commit(); flash('Invoice-wise payment adjusted and voucher posted')
    invoices=c.execute('SELECT *, total-COALESCE(paid,0) due FROM invoices WHERE company_id=? AND ABS(total-COALESCE(paid,0))>0.01 ORDER BY invdate DESC',(cid,)).fetchall()
    ledgers=c.execute('SELECT name FROM ledgers WHERE company_id=? AND group_name IN ("Cash-in-Hand","Bank Accounts") ORDER BY name',(cid,)).fetchall()
    rows=c.execute('SELECT invoice_payments.*, invoices.invno, invoices.party FROM invoice_payments LEFT JOIN invoices ON invoices.id=invoice_payments.invoice_id WHERE invoice_payments.company_id=? ORDER BY invoice_payments.id DESC',(cid,)).fetchall()
    c.close(); return render_template('invoice_payment.html', invoices=invoices, ledgers=ledgers, rows=rows, today=datetime.date.today().isoformat())

@app.route('/client_payment/<int:client_id>', methods=['POST'])
@login_required
def client_payment(client_id):
    c=con(); d=request.form; amt=safe_amount(d.get('amount'))
    c.execute('INSERT INTO client_payments(client_id,pdate,amount,mode,remarks) VALUES(?,?,?,?,?)',(client_id,d.get('pdate'),amt,d.get('mode','Cash'),d.get('remarks','')))
    c.execute('UPDATE clients SET received=COALESCE(received,0)+? WHERE id=?',(amt,client_id))
    c.commit(); c.close(); flash('Client payment received updated'); return redirect(url_for('clients'))

@app.route('/ledger_report/<name>')
@login_required
@company_required
def ledger_report(name):
    cid=session['company_id']; c=con(); rows=[]
    led=c.execute('SELECT * FROM ledgers WHERE company_id=? AND name=?',(cid,name)).fetchone()
    if led and led['opening']:
        rows.append(dict(date='', type='Opening', no='', debit=led['opening'] if led['drcr']=='Dr' else 0, credit=led['opening'] if led['drcr']=='Cr' else 0, narration='Opening Balance'))
    for v in c.execute('SELECT * FROM vouchers WHERE company_id=? AND cancelled=0 AND optional=0 ORDER BY vdate,id',(cid,)).fetchall():
        if v['debit_ledger']==name or v['credit_ledger']==name:
            rows.append(dict(date=v['vdate'], type=v['vtype'], no=v['vno'], debit=v['amount'] if v['debit_ledger']==name else 0, credit=v['amount'] if v['credit_ledger']==name else 0, narration=v['narration']))
    for inv in c.execute('SELECT * FROM invoices WHERE company_id=? ORDER BY invdate,id',(cid,)).fetchall():
        eff=invoice_effect(inv,name)
        if abs(eff)>0.01:
            rows.append(dict(date=inv['invdate'], type=inv['itype'], no=inv['invno'], debit=eff if eff>0 else 0, credit=-eff if eff<0 else 0, narration=(inv['party']+' / '+inv['item'])))
    c.close()
    bal=sum(float(r['debit'] or 0)-float(r['credit'] or 0) for r in rows)
    return render_template('ledger_detail.html', name=name, rows=rows, balance=round(bal,2))

@app.route('/checkup')
@login_required
@company_required
def checkup():
    cid=session['company_id']; c=con(); issues=[]
    for l in ['Cash','Bank','Sales','Purchase','GST Output','GST Input','Sales Return','Purchase Return']:
        if not c.execute('SELECT 1 FROM ledgers WHERE company_id=? AND name=?',(cid,l)).fetchone(): issues.append('Missing default ledger: '+l)
    for inv in c.execute('SELECT * FROM invoices WHERE company_id=?',(cid,)).fetchall():
        if not c.execute('SELECT 1 FROM ledgers WHERE company_id=? AND name=?',(cid,inv['party'])).fetchone(): issues.append('Invoice party ledger missing: '+inv['party'])
        if not c.execute('SELECT 1 FROM items WHERE company_id=? AND name=?',(cid,inv['item'])).fetchone(): issues.append('Invoice item missing: '+inv['item'])
    trial=[ledger_balance(cid,r['name']) for r in c.execute('SELECT name FROM ledgers WHERE company_id=?',(cid,)).fetchall()]
    c.close()
    if abs(sum(trial))>0.01: issues.append('Trial Balance difference: '+str(round(sum(trial),2)))
    return render_template('checkup.html', issues=issues)

@app.route('/health')
@login_required
def health():
    return 'OK - Prime Tax Management running'

@app.route('/backup')
@login_required
def backup():
    mem=io.BytesIO();
    with zipfile.ZipFile(mem,'w') as z:
        if os.path.exists(DB): z.write(DB)
    mem.seek(0); return send_file(mem, as_attachment=True, download_name='Prime_Tax_Management_Backup.zip')
@app.route('/restore', methods=['GET','POST'])
@login_required
def restore():
    if request.method=='POST':
        f=request.files.get('backup')
        if not f:
            flash('Backup file select karo'); return redirect(url_for('restore'))
        tmp=os.path.join(os.path.dirname(__file__),'restore_upload.zip')
        f.save(tmp)
        try:
            with zipfile.ZipFile(tmp,'r') as z:
                dbnames=[n for n in z.namelist() if n.endswith('.db') or n=='ptm.db']
                if not dbnames: raise Exception('DB file backup me nahi mila')
                data=z.read(dbnames[0])
                open(DB,'wb').write(data)
            flash('Restore complete. Dobara login/open company karo.')
            session.pop('company_id', None)
        except Exception as e:
            flash('Restore error: '+str(e))
        finally:
            if os.path.exists(tmp): os.remove(tmp)
    return render_template('restore.html')

@app.route('/export/<what>')
@login_required
def export(what):
    cid=session.get('company_id'); c=con(); out=io.StringIO(); w=csv.writer(out)
    if what=='ledgers': rows=c.execute('SELECT * FROM ledgers WHERE company_id=?',(cid,)).fetchall()
    elif what=='invoices': rows=c.execute('SELECT * FROM invoices WHERE company_id=?',(cid,)).fetchall()
    else: rows=c.execute('SELECT * FROM clients').fetchall()
    if rows: w.writerow(rows[0].keys()); [w.writerow(list(r)) for r in rows]
    c.close(); mem=io.BytesIO(out.getvalue().encode()); return send_file(mem, as_attachment=True, download_name=what+'.csv')

if __name__=="__main__":
    import os
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
