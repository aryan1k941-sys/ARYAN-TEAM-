import os, sqlite3, secrets, uuid, requests
from decimal import Decimal, InvalidOperation
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, abort
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE, "aryan_team.db"))
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
ZAP_API = "https://pay.zapupi.com/api"

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user', balance TEXT NOT NULL DEFAULT '0.00', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, order_id TEXT UNIQUE NOT NULL, user_id INTEGER NOT NULL, amount TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', txn_id TEXT, utr TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS transactions(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, order_id TEXT, amount TEXT NOT NULL, kind TEXT NOT NULL, note TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(user_id, order_id, kind));
        """)
        admin_email = os.environ.get("ADMIN_EMAIL", "armanmalikh762@gmail.com").strip().lower()
        admin_password = os.environ.get("ADMIN_PASSWORD", "aryan123")
        row = c.execute("SELECT id FROM users WHERE email=?", (admin_email,)).fetchone()
        if not row:
            c.execute("INSERT INTO users(email,password_hash,role) VALUES(?,?,?)",
                      (admin_email, generate_password_hash(admin_password), "admin"))
        defaults = {"site_name":"ARYAN TEAM","zap_key":"","minimum_topup":"10","support_url":"https://t.me/","currency":"INR"}
        for k,v in defaults.items():
            c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",(k,v))

def setting(key, default=""):
    with db() as c:
        row=c.execute("SELECT value FROM settings WHERE key=?",(key,)).fetchone()
        return row["value"] if row else default

def set_setting(key, value):
    with db() as c:
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(key,value))

def current_user():
    uid=session.get("uid")
    if not uid: return None
    with db() as c: return c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()

def login_required(fn):
    @wraps(fn)
    def wrapper(*a,**kw):
        if not current_user():
            flash("Please sign in to continue.","warning")
            return redirect(url_for("login"))
        return fn(*a,**kw)
    return wrapper

def admin_required(fn):
    @wraps(fn)
    def wrapper(*a,**kw):
        u=current_user()
        if not u or u["role"]!="admin": abort(403)
        return fn(*a,**kw)
    return wrapper

@app.context_processor
def globals_for_templates():
    return {"site_name":setting("site_name","ARYAN TEAM"),"logged_user":current_user()}

@app.route("/")
def home():
    u=current_user()
    if u: return redirect(url_for("admin" if u["role"]=="admin" else "dashboard"))
    return render_template("home.html")

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method=="POST":
        email=request.form.get("email","").strip().lower()
        password=request.form.get("password","")
        if not email or len(password)<8:
            flash("Valid email aur kam se kam 8-character password daalein.","danger")
        else:
            try:
                with db() as c:
                    c.execute("INSERT INTO users(email,password_hash) VALUES(?,?)",(email,generate_password_hash(password)))
                flash("Account ban gaya. Ab login karein.","success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("Is email se account pehle se hai.","danger")
    return render_template("auth.html",mode="register")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        email=request.form.get("email","").strip().lower()
        password=request.form.get("password","")
        with db() as c: u=c.execute("SELECT * FROM users WHERE email=?",(email,)).fetchone()
        if u and check_password_hash(u["password_hash"],password):
            session.clear(); session["uid"]=u["id"]
            return redirect(url_for("admin" if u["role"]=="admin" else "dashboard"))
        flash("Email ya password galat hai.","danger")
    return render_template("auth.html",mode="login")

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("home"))

@app.route("/dashboard")
@login_required
def dashboard():
    u=current_user()
    with db() as c:
        orders=c.execute("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 20",(u["id"],)).fetchall()
        tx=c.execute("SELECT * FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 10",(u["id"],)).fetchall()
    return render_template("dashboard.html",u=u,orders=orders,transactions=tx,min_topup=setting("minimum_topup","10"))

@app.route("/api/payment/create", methods=["POST"])
@login_required
def create_payment():
    u=current_user()
    try:
        amount=Decimal(request.form.get("amount","0")).quantize(Decimal("0.01"))
        minimum=Decimal(setting("minimum_topup","10"))
        if not amount.is_finite() or amount < minimum or amount > Decimal("50000"):
            raise ValueError()
    except (InvalidOperation, ValueError):
        flash("Amount minimum ₹"+setting("minimum_topup","10")+" aur maximum ₹50,000 hona chahiye.","danger")
        return redirect(url_for("dashboard"))
    zap_key=setting("zap_key","").strip()
    if not zap_key:
        flash("Payment gateway abhi admin ne configure nahi kiya.","warning")
        return redirect(url_for("dashboard"))
    oid="ARYAN"+uuid.uuid4().hex[:20].upper()
    with db() as c:
        c.execute("INSERT INTO orders(order_id,user_id,amount,status) VALUES(?,?,?,'pending')",(oid,u["id"],str(amount)))
    base=request.url_root.rstrip("/")
    payload={"zap_key":zap_key,"order_id":oid,"amount":str(amount),
             "remark":f"Wallet top-up | user:{u['id']}","webhook_url":base+"/webhook/zapupi"}
    try:
        r=requests.post(ZAP_API+"/create-order",json=payload,timeout=20)
        data=r.json()
        if r.status_code>=400 or str(data.get("status","")).lower()=="error":
            raise RuntimeError(data.get("message","ZapUPI order create failed"))
        pay_url=data.get("payment_url") or data.get("data",{}).get("payment_url")
        if not pay_url or not pay_url.startswith("https://"):
            raise RuntimeError("Gateway ne valid payment URL nahi diya. ZapUPI dashboard/API response check karein.")
        return redirect(pay_url)
    except Exception as e:
        with db() as c: c.execute("UPDATE orders SET status='failed',updated_at=CURRENT_TIMESTAMP WHERE order_id=? AND status='pending'",(oid,))
        flash("Payment order create nahi hua: "+str(e)[:220],"danger")
        return redirect(url_for("dashboard"))

@app.route("/webhook/zapupi", methods=["POST"])
def zapupi_webhook():
    data=request.get_json(silent=True) or request.form.to_dict()
    oid=str(data.get("order_id","")).strip()
    status=str(data.get("status","")).strip().lower()
    if not oid:
        return jsonify(status="ok"),200
    zap_key=setting("zap_key","").strip()
    # Treat webhook as a notification only. Confirm with ZapUPI order-status API before crediting.
    try:
        r=requests.post(ZAP_API+"/order-status",json={"zap_key":zap_key,"order_id":oid},timeout=15)
        verified=r.json()
        verified_status=str(verified.get("status","")).lower()
        verified_amount=Decimal(str(verified.get("amount",verified.get("pay_amount","0"))))
    except Exception:
        return jsonify(status="retry"),503
    if verified_status not in ("success","paid") or status!="success":
        if verified_status in ("failed","failure"):
            with db() as c: c.execute("UPDATE orders SET status='failed',txn_id=?,utr=?,updated_at=CURRENT_TIMESTAMP WHERE order_id=? AND status='pending'",(str(data.get("txn_id","")),str(data.get("utr","")),oid))
        return jsonify(status="ok"),200
    with db() as c:
        order=c.execute("SELECT * FROM orders WHERE order_id=?",(oid,)).fetchone()
        if not order: return jsonify(status="ok"),200
        if order["status"]=="paid": return jsonify(status="ok"),200
        expected=Decimal(order["amount"])
        # Require amount to match the originally created order.
        if verified_amount != expected:
            c.execute("UPDATE orders SET status='review',txn_id=?,utr=?,updated_at=CURRENT_TIMESTAMP WHERE order_id=?",(str(data.get("txn_id","")),str(data.get("utr","")),oid))
            return jsonify(status="ok"),200
        c.execute("UPDATE orders SET status='paid',txn_id=?,utr=?,updated_at=CURRENT_TIMESTAMP WHERE order_id=?",(str(verified.get("txn_id",data.get("txn_id",""))),str(verified.get("utr",data.get("utr",""))),oid))
        c.execute("UPDATE users SET balance=CAST(balance AS REAL)+? WHERE id=?",(float(expected),order["user_id"]))
        c.execute("INSERT OR IGNORE INTO transactions(user_id,order_id,amount,kind,note) VALUES(?,?,?,?,?)",(order["user_id"],oid,str(expected),"credit","ZapUPI wallet top-up"))
    return jsonify(status="ok"),200

@app.route("/admin")
@login_required
@admin_required
def admin():
    with db() as c:
        users=c.execute("SELECT id,email,role,balance,created_at FROM users ORDER BY id DESC LIMIT 200").fetchall()
        orders=c.execute("SELECT o.*,u.email FROM orders o JOIN users u ON u.id=o.user_id ORDER BY o.id DESC LIMIT 100").fetchall()
        stats={"users":c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"],
               "orders":c.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"],
               "paid":c.execute("SELECT COUNT(*) n FROM orders WHERE status='paid'").fetchone()["n"],
               "revenue":c.execute("SELECT COALESCE(SUM(CAST(amount AS REAL)),0) n FROM orders WHERE status='paid'").fetchone()["n"]}
    return render_template("admin.html",users=users,orders=orders,stats=stats,zap_key=setting("zap_key"),minimum=setting("minimum_topup","10"),support=setting("support_url",""))

@app.route("/admin/settings", methods=["POST"])
@login_required
@admin_required
def admin_settings():
    site=request.form.get("site_name","ARYAN TEAM").strip()[:60] or "ARYAN TEAM"
    zap=request.form.get("zap_key","").strip()
    minimum=request.form.get("minimum_topup","10").strip()
    support=request.form.get("support_url","").strip()
    try:
        if Decimal(minimum)<1 or Decimal(minimum)>50000: raise ValueError()
    except Exception:
        flash("Minimum top-up ₹1 se ₹50,000 ke beech hona chahiye.","danger")
        return redirect(url_for("admin"))
    set_setting("site_name",site); set_setting("zap_key",zap); set_setting("minimum_topup",minimum); set_setting("support_url",support)
    flash("Settings save ho gayi. ZapUPI key server par store hoti hai.","success")
    return redirect(url_for("admin"))

@app.route("/admin/user/<int:user_id>/role", methods=["POST"])
@login_required
@admin_required
def change_role(user_id):
    role=request.form.get("role","user")
    if role not in ("user","admin"): abort(400)
    if user_id==current_user()["id"] and role!="admin":
        flash("Apne admin access ko yahan se remove nahi kar sakte.","warning")
    else:
        with db() as c: c.execute("UPDATE users SET role=? WHERE id=?",(role,user_id))
        flash("User role update ho gaya.","success")
    return redirect(url_for("admin"))

@app.route("/health")
def health(): return jsonify(ok=True)

@app.errorhandler(403)
def forbidden(e): return render_template("message.html",title="Access denied",message="Admin access required."),403

init_db()
if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT","5000")),debug=False)
