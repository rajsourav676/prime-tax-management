from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, jsonify
import sqlite3, os, csv, io, zipfile, datetime, re, xml.etree.ElementTree as ET
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
    cur.execute('CREATE TABLE IF NOT EXISTS auto_uploads(id INTEGER PRIMARY KEY, company_id INTEGER, filename TEXT, raw_text TEXT, created_at TEXT)')
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
        c.close(); return redirect(url_for('companies'))
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
        c.commit(); flash('Saved'); c.close(); return redirect(url_for('masters', kind=kind))
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
        c.commit(); flash('GST Rate/HSN Saved'); c.close(); return redirect(url_for('gst_rates'))
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
        d=request.form; c.execute('INSERT INTO vouchers(company_id,vtype,vno,vdate,debit_ledger,credit_ledger,amount,narration,optional) VALUES(?,?,?,?,?,?,?,?,?)',(cid,vtype,d.get('vno') or next_no(cid,vtype,'vouchers'),d.get('vdate'),d.get('debit_ledger'),d.get('credit_ledger'),float(d.get('amount') or 0),d.get('narration',''),1 if d.get('optional') else 0)); c.commit(); flash(vtype+' Saved'); c.close(); return redirect(url_for('voucher', vtype=vtype))
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
        new_id=cur.lastrowid
        c.commit(); flash(itype+' Saved: Ledger + Stock + CGST/SGST/IGST connected'); c.close(); return redirect(url_for('invoice_saved', inv_id=new_id))
    rows=c.execute('SELECT * FROM invoices WHERE company_id=? AND itype=? ORDER BY invdate DESC,id DESC',(cid,itype)).fetchall(); c.close(); return render_template('invoice.html', itype=itype, ledgers=ledgers, items=items, rows=rows, today=datetime.date.today().isoformat())

@app.route('/invoice_saved/<int:inv_id>')
@login_required
@company_required
def invoice_saved(inv_id):
    cid=session['company_id']; c=con()
    inv=c.execute('SELECT invoices.*, COALESCE(items.hsn,"") hsn, COALESCE(items.unit,"Nos") unit FROM invoices LEFT JOIN items ON items.company_id=invoices.company_id AND items.name=invoices.item WHERE invoices.id=? AND invoices.company_id=?',(inv_id,cid)).fetchone()
    c.close()
    if not inv:
        flash('Invoice not found')
        return redirect(url_for('dashboard'))
    return render_template('invoice_saved.html', inv=inv)

@app.route('/invoice_print/<int:inv_id>')
@login_required
@company_required
def invoice_print(inv_id):
    cid=session['company_id']; c=con()
    inv=c.execute('SELECT invoices.*, COALESCE(items.hsn,"") hsn, COALESCE(items.unit,"Nos") unit FROM invoices LEFT JOIN items ON items.company_id=invoices.company_id AND items.name=invoices.item WHERE invoices.id=? AND invoices.company_id=?',(inv_id,cid)).fetchone()
    comp=c.execute('SELECT * FROM companies WHERE id=?',(cid,)).fetchone()
    c.close()
    if not inv:
        flash('Invoice not found')
        return redirect(url_for('dashboard'))
    return render_template('invoice_print.html', inv=inv, comp=comp)

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

def stock_avg_rate(cid, item_name):
    qty, val = stock_qty_value(cid, item_name)
    if abs(qty) > 0.0001:
        return round(val/qty, 2)
    c=con(); it=c.execute('SELECT opening_rate FROM items WHERE company_id=? AND name=?',(cid,item_name)).fetchone(); c.close()
    return round(float(it['opening_rate'] or 0), 2) if it else 0.0

def stock_movement_rows(cid, item_name):
    """Item-wise stock ledger: date, party, in/out qty, rate, amount, closing qty/value."""
    c=con(); rows=[]
    it=c.execute('SELECT * FROM items WHERE company_id=? AND name=?',(cid,item_name)).fetchone()
    closing_qty=0.0; closing_val=0.0
    if it:
        oq=float(it['opening_qty'] or 0); orate=float(it['opening_rate'] or 0); oval=round(oq*orate,2)
        if abs(oq)>0.0001 or abs(oval)>0.01:
            closing_qty += oq; closing_val += oval
            rows.append(dict(date='', type='Opening Stock', no='', party='Opening Balance', in_qty=round(oq,2), out_qty='', rate=round(orate,2), amount=oval, closing_qty=round(closing_qty,2), closing_value=round(closing_val,2), hsn=it['hsn'] or ''))
    invs=c.execute('SELECT * FROM invoices WHERE company_id=? AND item=? ORDER BY invdate,id',(cid,item_name)).fetchall()
    for inv in invs:
        q=float(inv['qty'] or 0); rate=float(inv['rate'] or 0); taxable=float(inv['taxable'] or 0)
        in_qty=''; out_qty=''
        # Tally-like movement signs
        if inv['itype'] in ['Purchase','Credit Note']:
            in_qty=round(q,2); closing_qty += q; closing_val += taxable
            amount=round(taxable,2)
        else:  # Sales, Debit Note
            out_qty=round(q,2); closing_qty -= q; closing_val -= round(q*rate,2)
            amount=round(q*rate,2)
        rows.append(dict(date=inv['invdate'], type=inv['itype'], no=inv['invno'], party=inv['party'], in_qty=in_qty, out_qty=out_qty, rate=round(rate,2), amount=amount, closing_qty=round(closing_qty,2), closing_value=round(closing_val,2), hsn=(it['hsn'] if it else '')))
    c.close(); return rows

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
        items=c.execute('SELECT * FROM items WHERE company_id=? ORDER BY name',(cid,)).fetchall()
        for it in items:
            qty,amount=stock_qty_value(cid,it['name'])
            rate=stock_avg_rate(cid,it['name'])
            data.append(dict(item=it['name'], hsn=it['hsn'] or '', unit=it['unit'], qty=qty, rate=rate, amount=amount, reorder=it['reorder'], low=qty<=float(it['reorder'] or 0)))
    elif rtype=='gst':
        data=c.execute('SELECT itype, SUM(taxable) taxable, SUM(cgst) cgst, SUM(sgst) sgst, SUM(igst) igst, SUM(gst) gst, SUM(total) total FROM invoices WHERE company_id=? GROUP BY itype',(cid,)).fetchall()
    elif rtype=='sales_register':
        data=c.execute('SELECT invoices.invdate date, invoices.invno no, invoices.party, invoices.item, COALESCE(items.hsn,"") hsn, invoices.qty, invoices.rate, invoices.taxable, invoices.cgst, invoices.sgst, invoices.igst, invoices.gst, invoices.total, invoices.paid, invoices.total-COALESCE(invoices.paid,0) due FROM invoices LEFT JOIN items ON items.company_id=invoices.company_id AND items.name=invoices.item WHERE invoices.company_id=? AND invoices.itype IN ("Sales","Credit Note") ORDER BY invoices.invdate DESC,invoices.id DESC',(cid,)).fetchall()
    elif rtype=='purchase_register':
        data=c.execute('SELECT invoices.invdate date, invoices.invno no, invoices.party, invoices.item, COALESCE(items.hsn,"") hsn, invoices.qty, invoices.rate, invoices.taxable, invoices.cgst, invoices.sgst, invoices.igst, invoices.gst, invoices.total, invoices.paid, invoices.total-COALESCE(invoices.paid,0) due FROM invoices LEFT JOIN items ON items.company_id=invoices.company_id AND items.name=invoices.item WHERE invoices.company_id=? AND invoices.itype IN ("Purchase","Debit Note") ORDER BY invoices.invdate DESC,invoices.id DESC',(cid,)).fetchall()
    elif rtype=='hsn':
        data=c.execute('SELECT COALESCE(items.hsn,"") hsn, invoices.item, SUM(invoices.qty) qty, SUM(invoices.taxable) taxable, SUM(invoices.cgst) cgst, SUM(invoices.sgst) sgst, SUM(invoices.igst) igst, SUM(invoices.gst) gst, SUM(invoices.total) total FROM invoices LEFT JOIN items ON items.company_id=invoices.company_id AND items.name=invoices.item WHERE invoices.company_id=? GROUP BY COALESCE(items.hsn,""), invoices.item ORDER BY hsn, invoices.item',(cid,)).fetchall()
    elif rtype=='cashbook':
        c.close(); return redirect(url_for('ledger_report', name='Cash'))
    elif rtype=='bankbook':
        c.close(); return redirect(url_for('ledger_report', name='Bank'))
    elif rtype=='audit':
        data=c.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 200').fetchall()
    c.close(); return render_template('reports.html', rtype=rtype, data=data, title=title)


@app.route('/stock_ledger/<path:item_name>')
@login_required
@company_required
def stock_ledger(item_name):
    cid=session['company_id']
    rows=stock_movement_rows(cid,item_name)
    c=con(); item=c.execute('SELECT * FROM items WHERE company_id=? AND name=?',(cid,item_name)).fetchone(); c.close()
    return render_template('stock_ledger.html', item=item, item_name=item_name, rows=rows)

@app.route('/clients', methods=['GET','POST'])
@login_required
def clients():
    c=con()
    if request.method=='POST':
        d=request.form; c.execute('INSERT INTO clients(name,mobile,email,pan,aadhaar,gstin,gst_user,gst_hint,it_user,it_hint,work_type,work_amount,received,remarks) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(d['name'],d.get('mobile',''),d.get('email',''),d.get('pan',''),d.get('aadhaar',''),d.get('gstin',''),d.get('gst_user',''),d.get('gst_hint',''),d.get('it_user',''),d.get('it_hint',''),d.get('work_type',''),float(d.get('work_amount') or 0),float(d.get('received') or 0),d.get('remarks',''))); c.commit(); flash('Client Saved'); c.close(); return redirect(url_for('clients'))
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
        c.commit(); flash('Saved'); c.close(); return redirect(url_for('status', stype=stype))
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
            c.commit(); flash('Invoice-wise payment adjusted and voucher posted'); c.close(); return redirect(url_for('invoice_payment'))
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
        return redirect(url_for('restore'))
    return render_template('restore.html')



def csv_response(filename, headers, rows):
    out=io.StringIO(); w=csv.writer(out); w.writerow(headers)
    for r in rows: w.writerow(r)
    mem=io.BytesIO(out.getvalue().encode('utf-8-sig'))
    return send_file(mem, as_attachment=True, download_name=filename, mimetype='text/csv')

def esc_xml(x):
    import html
    return html.escape('' if x is None else str(x))

def tally_amount(x):
    try: return f"{float(x):.2f}"
    except Exception: return "0.00"

def tally_group_for_ledger(group_name):
    # Tally ke group names mostly same rakhe gaye hain
    return group_name or 'Sundry Debtors'

def build_tally_xml(cid):
    c=con()
    comp=current_company()
    company_name = comp['name'] if comp else 'Prime Tax Management'
    parts=[]
    parts.append('<?xml version="1.0" encoding="UTF-8"?>')
    parts.append('<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA><REQUESTDESC><REPORTNAME>All Masters</REPORTNAME><STATICVARIABLES><SVCURRENTCOMPANY>'+esc_xml(company_name)+'</SVCURRENTCOMPANY></STATICVARIABLES></REQUESTDESC><REQUESTDATA>')
    for g in c.execute('SELECT * FROM groups WHERE company_id=? ORDER BY name',(cid,)).fetchall():
        parts.append('<TALLYMESSAGE><GROUP NAME="'+esc_xml(g['name'])+'" ACTION="Create"><NAME>'+esc_xml(g['name'])+'</NAME><PARENT>'+esc_xml(g['parent'] or 'Primary')+'</PARENT></GROUP></TALLYMESSAGE>')
    for l in c.execute('SELECT * FROM ledgers WHERE company_id=? ORDER BY name',(cid,)).fetchall():
        opening = float(l['opening'] or 0)
        if l['drcr']=='Cr': opening = -opening
        parts.append('<TALLYMESSAGE><LEDGER NAME="'+esc_xml(l['name'])+'" ACTION="Create"><NAME>'+esc_xml(l['name'])+'</NAME><PARENT>'+esc_xml(tally_group_for_ledger(l['group_name']))+'</PARENT><GSTIN>'+esc_xml(l['gstin'] or '')+'</GSTIN><OPENINGBALANCE>'+tally_amount(opening)+'</OPENINGBALANCE></LEDGER></TALLYMESSAGE>')
    for u in c.execute('SELECT * FROM units WHERE company_id=? ORDER BY symbol',(cid,)).fetchall():
        parts.append('<TALLYMESSAGE><UNIT NAME="'+esc_xml(u['symbol'])+'" ACTION="Create"><NAME>'+esc_xml(u['symbol'])+'</NAME><ORIGINALNAME>'+esc_xml(u['formal_name'] or u['symbol'])+'</ORIGINALNAME></UNIT></TALLYMESSAGE>')
    for it in c.execute('SELECT * FROM items WHERE company_id=? ORDER BY name',(cid,)).fetchall():
        parts.append('<TALLYMESSAGE><STOCKITEM NAME="'+esc_xml(it['name'])+'" ACTION="Create"><NAME>'+esc_xml(it['name'])+'</NAME><BASEUNITS>'+esc_xml(it['unit'] or 'Nos')+'</BASEUNITS><GSTAPPLICABLE>&#4; Applicable</GSTAPPLICABLE><GSTTYPEOFSUPPLY>Goods</GSTTYPEOFSUPPLY><HSNCODE>'+esc_xml(it['hsn'] or '')+'</HSNCODE><GST_RATE>'+tally_amount(it['gst_rate'] or 0)+'</GST_RATE><OPENINGBALANCE>'+tally_amount(it['opening_qty'] or 0)+' '+esc_xml(it['unit'] or 'Nos')+'</OPENINGBALANCE></STOCKITEM></TALLYMESSAGE>')
    # Accounting vouchers from vouchers table
    for v in c.execute('SELECT * FROM vouchers WHERE company_id=? AND cancelled=0 AND optional=0 ORDER BY vdate,id',(cid,)).fetchall():
        date=(v['vdate'] or '').replace('-','')
        amt=float(v['amount'] or 0)
        parts.append('<TALLYMESSAGE><VOUCHER VCHTYPE="'+esc_xml(v['vtype'])+'" ACTION="Create"><DATE>'+esc_xml(date)+'</DATE><VOUCHERTYPENAME>'+esc_xml(v['vtype'])+'</VOUCHERTYPENAME><VOUCHERNUMBER>'+esc_xml(v['vno'])+'</VOUCHERNUMBER><NARRATION>'+esc_xml(v['narration'] or '')+'</NARRATION>')
        parts.append('<ALLLEDGERENTRIES.LIST><LEDGERNAME>'+esc_xml(v['debit_ledger'])+'</LEDGERNAME><ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE><AMOUNT>-'+tally_amount(amt)+'</AMOUNT></ALLLEDGERENTRIES.LIST>')
        parts.append('<ALLLEDGERENTRIES.LIST><LEDGERNAME>'+esc_xml(v['credit_ledger'])+'</LEDGERNAME><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><AMOUNT>'+tally_amount(amt)+'</AMOUNT></ALLLEDGERENTRIES.LIST>')
        parts.append('</VOUCHER></TALLYMESSAGE>')
    # Invoice entries in voucher-like tally XML basic
    for inv in c.execute('SELECT * FROM invoices WHERE company_id=? ORDER BY invdate,id',(cid,)).fetchall():
        date=(inv['invdate'] or '').replace('-','')
        vtype = inv['itype']
        party = inv['party']; item = inv['item']
        total=float(inv['total'] or 0); taxable=float(inv['taxable'] or 0); gst=float(inv['gst'] or 0)
        sales_led = 'Sales' if vtype=='Sales' else ('Purchase' if vtype=='Purchase' else ('Sales Return' if vtype=='Credit Note' else 'Purchase Return'))
        tax_led = 'GST Output' if vtype in ['Sales','Credit Note'] else 'GST Input'
        parts.append('<TALLYMESSAGE><VOUCHER VCHTYPE="'+esc_xml(vtype)+'" ACTION="Create"><DATE>'+esc_xml(date)+'</DATE><VOUCHERTYPENAME>'+esc_xml(vtype)+'</VOUCHERTYPENAME><VOUCHERNUMBER>'+esc_xml(inv['invno'])+'</VOUCHERNUMBER><PARTYLEDGERNAME>'+esc_xml(party)+'</PARTYLEDGERNAME><NARRATION>'+esc_xml(inv['narration'] or '')+'</NARRATION>')
        if vtype in ['Sales','Debit Note']:
            parts.append('<ALLLEDGERENTRIES.LIST><LEDGERNAME>'+esc_xml(party)+'</LEDGERNAME><ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE><AMOUNT>-'+tally_amount(total)+'</AMOUNT></ALLLEDGERENTRIES.LIST>')
            parts.append('<ALLLEDGERENTRIES.LIST><LEDGERNAME>'+esc_xml(sales_led)+'</LEDGERNAME><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><AMOUNT>'+tally_amount(taxable)+'</AMOUNT></ALLLEDGERENTRIES.LIST>')
            if gst: parts.append('<ALLLEDGERENTRIES.LIST><LEDGERNAME>'+esc_xml(tax_led)+'</LEDGERNAME><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><AMOUNT>'+tally_amount(gst)+'</AMOUNT></ALLLEDGERENTRIES.LIST>')
        else:
            parts.append('<ALLLEDGERENTRIES.LIST><LEDGERNAME>'+esc_xml(party)+'</LEDGERNAME><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><AMOUNT>'+tally_amount(total)+'</AMOUNT></ALLLEDGERENTRIES.LIST>')
            parts.append('<ALLLEDGERENTRIES.LIST><LEDGERNAME>'+esc_xml(sales_led)+'</LEDGERNAME><ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE><AMOUNT>-'+tally_amount(taxable)+'</AMOUNT></ALLLEDGERENTRIES.LIST>')
            if gst: parts.append('<ALLLEDGERENTRIES.LIST><LEDGERNAME>'+esc_xml(tax_led)+'</LEDGERNAME><ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE><AMOUNT>-'+tally_amount(gst)+'</AMOUNT></ALLLEDGERENTRIES.LIST>')
        parts.append('<INVENTORYENTRIES.LIST><STOCKITEMNAME>'+esc_xml(item)+'</STOCKITEMNAME><RATE>'+tally_amount(inv['rate'] or 0)+'/'+esc_xml('Nos')+'</RATE><ACTUALQTY>'+tally_amount(inv['qty'] or 0)+'</ACTUALQTY><BILLEDQTY>'+tally_amount(inv['qty'] or 0)+'</BILLEDQTY></INVENTORYENTRIES.LIST>')
        parts.append('</VOUCHER></TALLYMESSAGE>')
    parts.append('</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>')
    c.close()
    return '\n'.join(parts)

@app.route('/export/<what>')
@login_required
def export(what):
    cid=session.get('company_id'); c=con(); out=io.StringIO(); w=csv.writer(out)
    if what=='ledgers': rows=c.execute('SELECT * FROM ledgers WHERE company_id=?',(cid,)).fetchall()
    elif what=='invoices': rows=c.execute('SELECT * FROM invoices WHERE company_id=?',(cid,)).fetchall()
    else: rows=c.execute('SELECT * FROM clients').fetchall()
    if rows: w.writerow(rows[0].keys()); [w.writerow(list(r)) for r in rows]
    c.close(); mem=io.BytesIO(out.getvalue().encode()); return send_file(mem, as_attachment=True, download_name=what+'.csv')




def extract_text_from_upload(file_storage):
    """PDF/JPG invoice se best-effort text extraction. PDF text nikal sakta hai; image ke liye manual preview fallback rahega."""
    name=(file_storage.filename or '').lower()
    data=file_storage.read()
    text=''
    if name.endswith('.pdf'):
        try:
            from pypdf import PdfReader
            reader=PdfReader(io.BytesIO(data))
            text='\n'.join([(page.extract_text() or '') for page in reader.pages])
        except Exception:
            text=''
    # JPG/PNG image OCR ke liye server par OCR engine chahiye. Agar available hua to try karega, warna manual correction screen.
    elif name.endswith(('.jpg','.jpeg','.png','.webp')):
        try:
            from PIL import Image
            import pytesseract
            img=Image.open(io.BytesIO(data))
            text=pytesseract.image_to_string(img)
        except Exception:
            text=''
    return text[:20000]

def pick_amount(patterns, text, default=0):
    for pat in patterns:
        m=re.search(pat, text, re.I)
        if m:
            return safe_amount((m.group(1) or '').replace(',',''))
    return default

def pick_value(patterns, text, default=''):
    for pat in patterns:
        m=re.search(pat, text, re.I)
        if m:
            return (m.group(1) or '').strip()[:120]
    return default

def parse_invoice_text(text):
    clean=' '.join((text or '').replace('\r',' ').split())
    invno=pick_value([r'invoice\s*(?:no|number|#)\s*[:\-]?\s*([A-Z0-9\-/]+)', r'bill\s*(?:no|number)\s*[:\-]?\s*([A-Z0-9\-/]+)'], clean)
    date=pick_value([r'(\d{4}-\d{2}-\d{2})', r'(\d{2}[/-]\d{2}[/-]\d{4})'], clean, datetime.date.today().isoformat())
    if '/' in date:
        dd,mm,yy=date.split('/')
        date=f'{yy}-{mm}-{dd}'
    party=pick_value([r'(?:party|customer|buyer|bill\s*to|supplier|vendor)\s*[:\-]?\s*([A-Za-z0-9 &.,\-]{3,80})', r'GSTIN\s*[:\-]?\s*[0-9A-Z]{15}\s*([A-Za-z0-9 &.,\-]{3,80})'], clean, 'New Party')
    gstin=pick_value([r'GSTIN\s*[:\-]?\s*([0-9A-Z]{15})'], clean)
    item=pick_value([r'(?:item|description|particulars)\s*[:\-]?\s*([A-Za-z0-9 &.,\-]{3,80})'], clean, 'New Item')
    qty=pick_amount([r'(?:qty|quantity)\s*[:\-]?\s*([0-9,.]+)'], clean, 1)
    taxable=pick_amount([r'(?:taxable\s*value|taxable|sub\s*total)\s*[:\-]?\s*₹?\s*([0-9,.]+)'], clean, 0)
    total=pick_amount([r'(?:grand\s*total|invoice\s*total|total\s*amount|total)\s*[:\-]?\s*₹?\s*([0-9,.]+)'], clean, 0)
    cgst=pick_amount([r'cgst\s*[:\-]?\s*₹?\s*([0-9,.]+)'], clean, 0)
    sgst=pick_amount([r'sgst\s*[:\-]?\s*₹?\s*([0-9,.]+)'], clean, 0)
    igst=pick_amount([r'igst\s*[:\-]?\s*₹?\s*([0-9,.]+)'], clean, 0)
    gst=cgst+sgst+igst
    if taxable<=0 and total>0:
        taxable=max(total-gst,0)
    gst_rate=0
    if taxable>0 and gst>0:
        gst_rate=round((gst/taxable)*100,2)
    rate=round(taxable/qty,2) if qty else taxable
    place='Interstate' if igst>0 else 'Local'
    return dict(invno=invno, invdate=date, party=party, gstin=gstin, item=item, qty=qty or 1, rate=rate, gst_rate=gst_rate, taxable=taxable, cgst=cgst, sgst=sgst, igst=igst, total=total or taxable+gst, place=place, raw_text=text or '')

@app.route('/auto_entry', methods=['GET','POST'])
@login_required
@company_required
def auto_entry():
    cid=session['company_id']; c=con()
    if request.method=='POST':
        f=request.files.get('file')
        if not f or not f.filename:
            flash('PDF/JPG file select karo'); c.close(); return redirect(url_for('auto_entry'))
        raw=extract_text_from_upload(f)
        c.execute('INSERT INTO auto_uploads(company_id,filename,raw_text,created_at) VALUES(?,?,?,?)',(cid,f.filename,raw,datetime.datetime.now().strftime('%Y-%m-%d %H:%M')))
        c.commit()
        parsed=parse_invoice_text(raw)
        ledgers=c.execute('SELECT name FROM ledgers WHERE company_id=? ORDER BY name',(cid,)).fetchall()
        items=c.execute('SELECT * FROM items WHERE company_id=? ORDER BY name',(cid,)).fetchall()
        units=c.execute('SELECT symbol FROM units WHERE company_id=? ORDER BY symbol',(cid,)).fetchall()
        c.close()
        return render_template('auto_entry_preview.html', parsed=parsed, ledgers=ledgers, items=items, units=units, filename=f.filename, today=datetime.date.today().isoformat())
    rows=c.execute('SELECT * FROM auto_uploads WHERE company_id=? ORDER BY id DESC LIMIT 20',(cid,)).fetchall(); c.close()
    return render_template('auto_entry.html', rows=rows)

@app.route('/auto_entry/save', methods=['POST'])
@login_required
@company_required
def auto_entry_save():
    cid=session['company_id']; d=request.form; c=con()
    itype=d.get('itype') or 'Purchase'
    party=(d.get('party') or '').strip() or 'New Party'
    item=(d.get('item') or '').strip() or 'New Item'
    # missing ledger/item/unit ko preview se create karne ka option
    if d.get('create_party'):
        group='Sundry Debtors' if itype in ['Sales','Credit Note'] else 'Sundry Creditors'
        if not c.execute('SELECT 1 FROM ledgers WHERE company_id=? AND lower(name)=lower(?)',(cid,party)).fetchone():
            c.execute('INSERT INTO ledgers(company_id,name,group_name,gstin,mobile,opening,drcr) VALUES(?,?,?,?,?,?,?)',(cid,party,group,d.get('gstin',''),'',0,'Dr'))
    else:
        create_default_party_if_missing(cid, party, itype)
    if d.get('create_unit'):
        unit=(d.get('unit') or 'Nos').strip()
        if not c.execute('SELECT 1 FROM units WHERE company_id=? AND lower(symbol)=lower(?)',(cid,unit)).fetchone():
            c.execute('INSERT INTO units(company_id,symbol,formal_name) VALUES(?,?,?)',(cid,unit,unit))
    if d.get('create_item'):
        unit=(d.get('unit') or 'Nos').strip()
        if not c.execute('SELECT 1 FROM items WHERE company_id=? AND lower(name)=lower(?)',(cid,item)).fetchone():
            c.execute('INSERT INTO items(company_id,name,unit,hsn,gst_rate,opening_qty,opening_rate,reorder) VALUES(?,?,?,?,?,?,?,?)',(cid,item,unit,d.get('hsn',''),safe_amount(d.get('gst_rate')),0,0,0))
    qty=safe_amount(d.get('qty')) or 1; rate=safe_amount(d.get('rate')); gst_rate=safe_amount(d.get('gst_rate'))
    taxable=round(qty*rate,2)
    place=d.get('place','Local'); cgst,sgst,igst,gst=calc_gst_split(taxable,gst_rate,place); total=round(taxable+gst,2)
    invno=d.get('invno') or next_no(cid,itype,'invoices')
    c.execute('INSERT INTO invoices(company_id,itype,invno,invdate,party,item,qty,rate,gst_rate,taxable,gst,cgst,sgst,igst,total,paid,narration,place) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(cid,itype,invno,d.get('invdate') or datetime.date.today().isoformat(),party,item,qty,rate,gst_rate,taxable,gst,cgst,sgst,igst,total,0,d.get('narration','Auto Entry from PDF/JPG'),place))
    c.commit(); c.close(); flash('Auto Entry saved with ledger/item creation options'); return redirect(url_for('invoice', itype=itype))

@app.route('/utilities/tally')
@login_required
@company_required
def tally_utilities():
    return render_template('tally_utilities.html')

@app.route('/export/tally_xml')
@login_required
@company_required
def export_tally_xml():
    cid=session['company_id']
    xml=build_tally_xml(cid)
    mem=io.BytesIO(xml.encode('utf-8'))
    return send_file(mem, as_attachment=True, download_name='Prime_Tax_Management_Tally_Export.xml', mimetype='application/xml')

@app.route('/export/excel_csv/<what>')
@login_required
@company_required
def export_excel_csv(what):
    cid=session['company_id']; c=con()
    if what=='ledgers':
        rows=c.execute('SELECT name,group_name,gstin,mobile,opening,drcr FROM ledgers WHERE company_id=? ORDER BY name',(cid,)).fetchall()
        c.close(); return csv_response('ledgers_for_excel.csv',['name','group_name','gstin','mobile','opening','drcr'],[list(r) for r in rows])
    if what=='stock':
        rows=c.execute('SELECT name,unit,hsn,gst_rate,opening_qty,opening_rate,reorder FROM items WHERE company_id=? ORDER BY name',(cid,)).fetchall()
        c.close(); return csv_response('stock_items_for_excel.csv',['name','unit','hsn','gst_rate','opening_qty','opening_rate','reorder'],[list(r) for r in rows])
    if what=='vouchers':
        rows=c.execute('SELECT vtype,vno,vdate,debit_ledger,credit_ledger,amount,narration FROM vouchers WHERE company_id=? ORDER BY vdate,id',(cid,)).fetchall()
        c.close(); return csv_response('vouchers_for_excel.csv',['vtype','vno','vdate','debit_ledger','credit_ledger','amount','narration'],[list(r) for r in rows])
    rows=c.execute('SELECT itype,invno,invdate,party,item,qty,rate,gst_rate,cgst,sgst,igst,total,paid,narration FROM invoices WHERE company_id=? ORDER BY invdate,id',(cid,)).fetchall()
    c.close(); return csv_response('invoices_for_excel.csv',['itype','invno','invdate','party','item','qty','rate','gst_rate','cgst','sgst','igst','total','paid','narration'],[list(r) for r in rows])

@app.route('/import/csv/<what>', methods=['POST'])
@login_required
@company_required
def import_csv(what):
    cid=session['company_id']; f=request.files.get('file')
    if not f:
        flash('CSV file select karo'); return redirect(url_for('tally_utilities'))
    text=f.read().decode('utf-8-sig', errors='ignore')
    reader=csv.DictReader(io.StringIO(text)); c=con(); count=0
    try:
        for r in reader:
            if what=='ledgers':
                name=(r.get('name') or r.get('Name') or '').strip()
                if not name: continue
                c.execute('INSERT INTO ledgers(company_id,name,group_name,gstin,mobile,opening,drcr) SELECT ?,?,?,?,?,?,? WHERE NOT EXISTS(SELECT 1 FROM ledgers WHERE company_id=? AND lower(name)=lower(?))',(cid,name,r.get('group_name') or r.get('Group') or 'Sundry Debtors',r.get('gstin',''),r.get('mobile',''),safe_amount(r.get('opening')),r.get('drcr') or 'Dr',cid,name)); count+=1
            elif what=='stock':
                name=(r.get('name') or r.get('Name') or '').strip()
                if not name: continue
                c.execute('INSERT INTO items(company_id,name,unit,hsn,gst_rate,opening_qty,opening_rate,reorder) SELECT ?,?,?,?,?,?,?,? WHERE NOT EXISTS(SELECT 1 FROM items WHERE company_id=? AND lower(name)=lower(?))',(cid,name,r.get('unit') or 'Nos',r.get('hsn',''),safe_amount(r.get('gst_rate')),safe_amount(r.get('opening_qty')),safe_amount(r.get('opening_rate')),safe_amount(r.get('reorder')),cid,name)); count+=1
            elif what=='vouchers':
                vt=r.get('vtype') or r.get('type') or 'Journal'
                c.execute('INSERT INTO vouchers(company_id,vtype,vno,vdate,debit_ledger,credit_ledger,amount,narration) VALUES(?,?,?,?,?,?,?,?)',(cid,vt,r.get('vno') or next_no(cid,vt,'vouchers'),r.get('vdate') or datetime.date.today().isoformat(),r.get('debit_ledger'),r.get('credit_ledger'),safe_amount(r.get('amount')),r.get('narration',''))); count+=1
        c.commit(); flash(str(count)+' row import ho gaya')
    except Exception as e:
        c.rollback(); flash('Import error: '+str(e))
    finally:
        c.close()
    return redirect(url_for('tally_utilities'))

@app.route('/import/tally_xml', methods=['POST'])
@login_required
@company_required
def import_tally_xml():
    cid=session['company_id']; f=request.files.get('file')
    if not f:
        flash('Tally XML file select karo'); return redirect(url_for('tally_utilities'))
    data=f.read(); c=con(); led=stk=vou=0
    try:
        root=ET.fromstring(data)
        # group/ledger/stock import: common Tally XML tags
        for node in root.iter():
            tag=node.tag.upper().split('}')[-1]
            if tag=='LEDGER':
                name=node.attrib.get('NAME') or (node.findtext('NAME') or '').strip()
                parent=(node.findtext('PARENT') or 'Sundry Debtors').strip()
                gstin=(node.findtext('GSTIN') or '').strip()
                op=safe_amount((node.findtext('OPENINGBALANCE') or '0').replace(',',''))
                drcr='Dr' if op>=0 else 'Cr'
                if name:
                    c.execute('INSERT INTO ledgers(company_id,name,group_name,gstin,opening,drcr) SELECT ?,?,?,?,?,? WHERE NOT EXISTS(SELECT 1 FROM ledgers WHERE company_id=? AND lower(name)=lower(?))',(cid,name,parent,gstin,abs(op),drcr,cid,name)); led+=1
            elif tag=='STOCKITEM':
                name=node.attrib.get('NAME') or (node.findtext('NAME') or '').strip()
                unit=(node.findtext('BASEUNITS') or 'Nos').strip()
                hsn=(node.findtext('HSNCODE') or '').strip()
                rate=safe_amount(node.findtext('GST_RATE') or node.findtext('GSTRATE') or '0')
                if name:
                    c.execute('INSERT INTO items(company_id,name,unit,hsn,gst_rate) SELECT ?,?,?,?,? WHERE NOT EXISTS(SELECT 1 FROM items WHERE company_id=? AND lower(name)=lower(?))',(cid,name,unit,hsn,rate,cid,name)); stk+=1
            elif tag=='VOUCHER':
                vt=node.attrib.get('VCHTYPE') or node.findtext('VOUCHERTYPENAME') or 'Journal'
                vno=node.findtext('VOUCHERNUMBER') or next_no(cid,vt,'vouchers')
                rawdate=node.findtext('DATE') or ''
                vdate = rawdate if '-' in rawdate else (rawdate[0:4]+'-'+rawdate[4:6]+'-'+rawdate[6:8] if len(rawdate)>=8 else datetime.date.today().isoformat())
                ledgers=[]; amounts=[]
                for le in node.iter():
                    if le.tag.upper().endswith('ALLLEDGERENTRIES.LIST'):
                        lname=le.findtext('LEDGERNAME') or ''
                        amt=safe_amount((le.findtext('AMOUNT') or '0').replace(',',''))
                        if lname: ledgers.append(lname); amounts.append(amt)
                if len(ledgers)>=2:
                    debit=ledgers[0] if amounts[0]<0 else ledgers[1]
                    credit=ledgers[1] if amounts[0]<0 else ledgers[0]
                    amount=max(abs(amounts[0]), abs(amounts[1]))
                    c.execute('INSERT INTO vouchers(company_id,vtype,vno,vdate,debit_ledger,credit_ledger,amount,narration) VALUES(?,?,?,?,?,?,?,?)',(cid,vt,vno,vdate,debit,credit,amount,node.findtext('NARRATION') or 'Imported from Tally XML')); vou+=1
        c.commit(); flash(f'Tally XML import: {led} ledgers, {stk} stock items, {vou} vouchers')
    except Exception as e:
        c.rollback(); flash('Tally XML import error: '+str(e))
    finally:
        c.close()
    return redirect(url_for('tally_utilities'))

if __name__=='__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
