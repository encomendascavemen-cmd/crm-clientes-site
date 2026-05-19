#!/usr/bin/env python3
"""
Cavemen Store Dashboard Server
Corre: python3 server.py
Abre: http://localhost:5001
"""

from flask import Flask, jsonify, request, send_from_directory, Response
from flask_cors import CORS
import requests as req
import json, os, re, time, subprocess, threading
from datetime import datetime, timedelta
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

# ─── NEON (PostgreSQL) ────────────────────────────────────────────
try:
    import psycopg2
    _PSYCOPG2_OK = True
except ImportError:
    _PSYCOPG2_OK = False

def _neon_conn():
    """Devolve uma conexão Neon, ou None se DATABASE_URL não estiver definido."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url or not _PSYCOPG2_OK:
        return None
    try:
        return psycopg2.connect(db_url, sslmode="require")
    except Exception as e:
        print(f"⚠️  Neon: erro de conexão — {e}")
        return None

def neon_init():
    """Cria a tabela kv_store se não existir."""
    conn = _neon_conn()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kv_store (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
        conn.commit()
        print("✅ Neon: tabela kv_store pronta")
    except Exception as e:
        print(f"⚠️  Neon init: {e}")
    finally:
        conn.close()

def neon_save(key: str, data):
    """Guarda data (serializado como JSON) no Neon."""
    conn = _neon_conn()
    if not conn:
        return False
    try:
        payload = json.dumps(data, ensure_ascii=False)
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO kv_store (key, value, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value, updated_at = NOW()
            """, (key, payload))
        conn.commit()
        print(f"✅ Neon: '{key}' guardado ({len(payload)//1024} KB)")
        return True
    except Exception as e:
        print(f"⚠️  Neon save '{key}': {e}")
        return False
    finally:
        conn.close()

def neon_load(key: str):
    """Carrega e devolve o objeto JSON guardado no Neon, ou None."""
    conn = _neon_conn()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM kv_store WHERE key = %s", (key,))
            row = cur.fetchone()
        if not row:
            return None
        val = row[0]
        # JSONB columns are already deserialized by psycopg2; TEXT columns need json.loads
        if isinstance(val, (dict, list)):
            return val
        return json.loads(val)
    except Exception as e:
        print(f"⚠️  Neon load '{key}': {e}")
        return None
    finally:
        conn.close()

# ─── CONFIG ─────────────────────────────────────────────────────
CLIENT_ID     = "cavemenunipessoallda"
CLIENT_SECRET = "a7678d73814b0f8179407c63b6242ca83690b61d"
USERNAME      = "encomendas@cavemenstore.com"
PASSWORD      = "7+LVn*QU+4sdrXN"
COMPANY_ID    = 274475
BASE_URL      = "https://api.moloni.pt/v1"
SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR     = os.path.join(SCRIPT_DIR, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

TERMINALS = {125906: "Guimarães", 125908: "Braga", 148908: "Porto", 0: "Online"}
ALL_STORES = ["Guimarães", "Braga", "Porto", "Online"]
STORES     = ["Guimarães", "Braga", "Porto"]  # Only physical stores in products report
EXCLUDED_STORES = {"Online"}  # Excluded from products report

app = Flask(__name__, static_folder=SCRIPT_DIR, static_url_path="")
CORS(app)

# ─── IN-MEMORY STORE (loaded once at startup) ───────────────────
_monthly_cache = {}   # "YYYY-MM" → { store → { revenue, orders, avg_ticket, docs_count } }
_products_cache = {}  # "YYYY-MM" → [ product_stats ]
_daily_cache  = {}    # "YYYY-MM-DD" → { store → revenue }

# v2 products data (day-level, with VAT, normalized categories)
_products_v2 = {}          # product_id → full product object (with by_day)
_products_v2_date_from = ""
_products_v2_date_to   = ""

# clients data: day → store → [client_ids]
_clients_by_day = {}       # "YYYY-MM-DD" → { store → [client_ids] }

# CRM data (loaded once at startup, reloaded after refresh)
_crm_customers = []        # lista completa com todos os campos
_crm_lite      = []        # lista leve para a tabela (sem orders/products)
_crm_rfv       = []        # lista com campos rfv para a matriz

def load_crm_data():
    """Carrega crm_data.json (ou Neon) em memória e pré-computa as vistas lite e rfv."""
    global _crm_customers, _crm_lite, _crm_rfv
    data_path = os.path.join(SCRIPT_DIR, "crm_data.json")
    if os.path.exists(data_path):
        with open(data_path, encoding="utf-8") as f:
            _crm_customers = json.load(f)
        print(f"✅ crm_data.json carregado do disco: {len(_crm_customers)} clientes")
    else:
        db_data = neon_load("crm_data")
        if db_data:
            _crm_customers = db_data
            print(f"✅ crm_data carregado do Neon: {len(_crm_customers)} clientes")
        else:
            print("⚠️  crm_data: ficheiro e Neon vazios — usa 'Dados Novos' para carregar")
            return
    _crm_lite = [{
        "email":        c["email"],
        "name":         c["name"],
        "is_guest":     c["is_guest"],
        "phone":        c.get("phone", ""),
        "city":         c.get("city", ""),
        "region":       c.get("region", ""),
        "postcode":     c.get("postcode", ""),
        "country":      c.get("country", "PT"),
        "vat":          c.get("vat", ""),
        "total_orders": c["total_orders"],
        "total_spent":  c["total_spent"],
        "avg_order":    c["avg_order"],
        "first_order":  c["first_order"],
        "last_order":   c["last_order"],
        "days_since":   c["days_since"],
        "top_product":  c["products"][0]["name"] if c.get("products") else "",
    } for c in _crm_customers]
    _crm_rfv = [{
        "email":        c["email"],
        "name":         c.get("name", ""),
        "is_guest":     c.get("is_guest", True),
        "city":         c.get("city", ""),
        "region":       c.get("region", ""),
        "total_orders": c["total_orders"],
        "total_spent":  c["total_spent"],
        "last_order":   c.get("last_order", ""),
        "days_since":   c.get("days_since", ""),
        "rfv_r":        c.get("rfv_r", 1),
        "rfv_f":        c.get("rfv_f", 1),
        "rfv_v":        c.get("rfv_v", 1),
        "rfv_score":    c.get("rfv_score", 3),
        "rfv_segment":  c.get("rfv_segment", "lost"),
    } for c in _crm_customers]
    print(f"✅ CRM em memória: {len(_crm_customers)} clientes")


def load_precomputed():
    """Load already-extracted data into memory at startup."""
    global _monthly_cache, _products_cache, _daily_cache, _products_v2, _products_v2_date_from, _products_v2_date_to, _clients_by_day

    # Load dashboard_data.json (monthly + daily aggregates)
    dash_path = os.path.join(SCRIPT_DIR, "dashboard_data.json")
    if os.path.exists(dash_path):
        with open(dash_path, encoding="utf-8") as f:
            d = json.load(f)
        for month in d.get("months", []):
            if month not in _monthly_cache:
                _monthly_cache[month] = {}
            for store in ALL_STORES:
                rev = d["monthly_revenue"].get(store, {}).get(month, 0)
                ord_ = d["monthly_orders"].get(store, {}).get(month, 0)
                _monthly_cache[month][store] = {
                    "revenue": rev, "orders": ord_,
                    "avg_ticket": d["store_avg_ticket"].get(store, 0),
                }
        for store, days in d.get("daily_sales_30d", {}).items():
            for day, rev in days.items():
                if day not in _daily_cache:
                    _daily_cache[day] = {}
                _daily_cache[day][store] = rev
        print(f"✅ dashboard_data.json carregado: {len(_monthly_cache)} meses em memória")

    # Load products_data.json (product details for last 90 days)
    prod_path = os.path.join(SCRIPT_DIR, "products_data.json")
    if os.path.exists(prod_path):
        with open(prod_path, encoding="utf-8") as f:
            p = json.load(f)
        # Store products indexed by month
        for product in p.get("products", []):
            for month, mdata in product.get("by_month", {}).items():
                if month not in _products_cache:
                    _products_cache[month] = {}
                pid = product["product_id"]
                if pid not in _products_cache[month]:
                    _products_cache[month][pid] = {
                        "product_id": pid,
                        "reference": product["reference"],
                        "name": product["name"],
                        "category_name": product["category_name"],
                        "qty": 0.0, "revenue": 0.0, "orders": 0,
                        "by_store": defaultdict(lambda: {"qty":0.0,"revenue":0.0}),
                    }
                ps = _products_cache[month][pid]
                ps["qty"]     += mdata.get("qty", 0)
                ps["revenue"] += mdata.get("revenue", 0)
                ps["orders"]  += 1
                for store, sv in product.get("by_store", {}).items():
                    ps["by_store"][store]["qty"]     += sv.get("qty", 0)
                    ps["by_store"][store]["revenue"] += sv.get("revenue", 0)
        print(f"✅ products_data.json carregado: {len(_products_cache)} meses de produtos")

    # Load per-month cache files (from migrate_cache.py)
    for fname in sorted(os.listdir(CACHE_DIR)):
        if not fname.endswith(".json"):
            continue
        month_key = fname.replace(".json", "")
        if month_key in _monthly_cache:
            continue  # already loaded from dashboard_data.json
        try:
            with open(os.path.join(CACHE_DIR, fname), encoding="utf-8") as f:
                mdata = json.load(f)
            _load_month_cache(month_key, mdata)
        except Exception as e:
            print(f"  ⚠️  Erro ao carregar {fname}: {e}")

    # Load products_data_v2.json (day-level, with VAT)
    prod_v2_path = os.path.join(SCRIPT_DIR, "products_data_v2.json")
    if os.path.exists(prod_v2_path):
        with open(prod_v2_path, encoding="utf-8") as f:
            pv2 = json.load(f)
        for product in pv2.get("products", []):
            _products_v2[product["product_id"]] = product
        _products_v2_date_from = pv2.get("date_from", "")
        _products_v2_date_to   = pv2.get("date_to", "")
        print(f"✅ products_data_v2.json carregado: {len(_products_v2)} produtos ({_products_v2_date_from} → {_products_v2_date_to})")

    # Load clients_data.json
    clients_path = os.path.join(SCRIPT_DIR, "clients_data.json")
    if os.path.exists(clients_path):
        with open(clients_path, encoding="utf-8") as f:
            cdata = json.load(f)
        _clients_by_day = cdata.get("by_day", {})
        print(f"✅ clients_data.json carregado: {len(_clients_by_day)} dias")

    print(f"📊 Cache total: {len(_monthly_cache)} meses disponíveis")

    # Load CRM data
    neon_init()
    load_crm_data()
    print(f"   Intervalo: {min(_monthly_cache) if _monthly_cache else '—'} → {max(_monthly_cache) if _monthly_cache else '—'}")

def _load_month_cache(month_key, mdata):
    """Parse a raw month cache file into the in-memory structures."""
    if month_key not in _monthly_cache:
        _monthly_cache[month_key] = {s: {"revenue":0,"orders":0,"avg_ticket":0} for s in ALL_STORES}

    for doc in mdata.get("docs", []):
        net = float(doc.get("net_value", 0) or 0)
        if net <= 0:
            continue
        tid   = doc.get("terminal_id", 0)
        store = TERMINALS.get(tid, f"Terminal {tid}")
        dt    = _parse_date(doc.get("date",""))
        if not dt:
            continue

        day_key = dt.strftime("%Y-%m-%d")
        if day_key not in _daily_cache:
            _daily_cache[day_key] = {}
        _daily_cache[day_key][store] = _daily_cache[day_key].get(store, 0) + net

        ms = _monthly_cache[month_key].setdefault(store, {"revenue":0,"orders":0,"avg_ticket":0})
        ms["revenue"] += net
        ms["orders"]  += 1

        # Products
        if month_key not in _products_cache:
            _products_cache[month_key] = {}
        for p in doc.get("_products", []):
            pid = p.get("product_id", 0)
            qty = float(p.get("qty", 0) or 0)
            price = float(p.get("price", 0) or 0)
            disc  = float(p.get("discount", 0) or 0)
            rev   = qty * price * (1 - disc / 100)
            if qty <= 0 or rev <= 0:
                continue
            if pid not in _products_cache[month_key]:
                _products_cache[month_key][pid] = {
                    "product_id": pid,
                    "reference": p.get("reference",""),
                    "name": p.get("name",""),
                    "category_name": "",
                    "qty": 0.0, "revenue": 0.0, "orders": 0,
                    "by_store": defaultdict(lambda: {"qty":0.0,"revenue":0.0}),
                }
            ps = _products_cache[month_key][pid]
            ps["qty"] += qty
            ps["revenue"] += rev
            ps["orders"]  += 1
            ps["by_store"][store]["qty"]     += qty
            ps["by_store"][store]["revenue"] += rev

# ─── AUTH ────────────────────────────────────────────────────────
_token = None
_token_ts = 0

def get_token():
    global _token, _token_ts
    if _token and (time.time() - _token_ts) < 3000:
        return _token
    r = req.get(f"{BASE_URL}/grant/", params={
        "grant_type":"password","client_id":CLIENT_ID,
        "client_secret":CLIENT_SECRET,"username":USERNAME,"password":PASSWORD,
    }, timeout=15)
    r.raise_for_status()
    _token = r.json()["access_token"]
    _token_ts = time.time()
    return _token

def _parse_date(s):
    if not s: return None
    clean = re.sub(r'[+-]\d{2}:?\d{2}$|Z$','', s.replace("T"," ")).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S","%Y-%m-%d"):
        try: return datetime.strptime(clean[:19], fmt)
        except: pass
    return None

def _api_post(endpoint, data=None):
    token = get_token()
    payload = {"company_id": COMPANY_ID}
    if data: payload.update(data)
    for attempt in range(3):
        try:
            r = req.post(f"{BASE_URL}/{endpoint}/",
                params={"access_token":token}, data=payload, timeout=30)
            if r.status_code == 429:
                time.sleep(2**attempt); continue
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt == 2: return None
            time.sleep(1)

def fetch_month_summaries(year, month):
    """Fetch document summaries (no product details) for a month — fast."""
    print(f"  📥 Buscando {year}-{month:02d} da API (resumos)...")
    month_key = f"{year}-{month:02d}"
    _monthly_cache[month_key] = {s: {"revenue":0,"orders":0,"avg_ticket":0} for s in STORES}

    for doc_type in ["simplifiedInvoices","invoiceReceipts","invoices"]:
        offset = 0
        while True:
            batch = _api_post(f"{doc_type}/getAll",
                              {"qty":50,"offset":offset,"year":year})
            if not batch or not isinstance(batch, list): break
            for d in batch:
                net = float(d.get("net_value",0) or 0)
                if net <= 0: continue
                dt = _parse_date(d.get("date",""))
                if not dt or dt.month != month: continue
                tid   = d.get("terminal_id", 0)
                store = TERMINALS.get(tid, f"Terminal {tid}")
                ms = _monthly_cache[month_key].setdefault(store, {"revenue":0,"orders":0,"avg_ticket":0})
                ms["revenue"] += net
                ms["orders"]  += 1
                day_key = dt.strftime("%Y-%m-%d")
                if day_key not in _daily_cache:
                    _daily_cache[day_key] = {}
                _daily_cache[day_key][store] = _daily_cache[day_key].get(store, 0) + net
            if len(batch) < 50: break
            offset += 50

    total = sum(v["orders"] for v in _monthly_cache[month_key].values())
    print(f"  ✅ {month_key}: {total} documentos")

# ─── AGGREGATION ─────────────────────────────────────────────────
def build_response(months_list, include_daily=True):
    """Build the API response from in-memory caches."""
    store_totals  = {s: 0.0 for s in ALL_STORES}
    store_orders  = {s: 0   for s in ALL_STORES}
    monthly_rev   = {s: {}  for s in ALL_STORES}
    monthly_ord   = {s: {}  for s in ALL_STORES}

    # Determine date range for daily data
    if months_list:
        from_day = months_list[0] + "-01"
        last_month = months_list[-1]
        y, m = int(last_month[:4]), int(last_month[5:])
        import calendar
        last_day_num = calendar.monthrange(y, m)[1]
        to_day = f"{last_month}-{last_day_num:02d}"
    else:
        from_day = to_day = ""

    for month in months_list:
        mdata = _monthly_cache.get(month, {})
        for store in ALL_STORES:
            sd = mdata.get(store, {"revenue":0,"orders":0})
            rev = sd.get("revenue", 0)
            ord_ = sd.get("orders", 0)
            store_totals[store]     += rev
            store_orders[store]     += ord_
            monthly_rev[store][month] = round(rev, 2)
            monthly_ord[store][month] = ord_

    # avg ticket
    store_avg = {}
    for store in ALL_STORES:
        rev = store_totals[store]
        ord_ = store_orders[store]
        store_avg[store] = round(rev / ord_, 2) if ord_ > 0 else 0

    # Daily data (all days in range)
    daily_rev = {s: {} for s in ALL_STORES}
    if include_daily and from_day and to_day:
        cur = datetime.strptime(from_day, "%Y-%m-%d")
        end = datetime.strptime(to_day,   "%Y-%m-%d")
        while cur <= end:
            day = cur.strftime("%Y-%m-%d")
            day_data = _daily_cache.get(day, {})
            for store in ALL_STORES:
                v = day_data.get(store, 0)
                if v > 0:
                    daily_rev[store][day] = round(v, 2)
            cur += timedelta(days=1)

    all_days = sorted(set(d for sv in daily_rev.values() for d in sv.keys()))

    # Products (aggregate across months)
    prod_agg = {}
    for month in months_list:
        for pid, ps in _products_cache.get(month, {}).items():
            if pid not in prod_agg:
                prod_agg[pid] = {
                    "product_id": pid,
                    "reference": ps["reference"],
                    "name": ps["name"],
                    "category_name": ps.get("category_name",""),
                    "qty": 0.0, "revenue": 0.0, "orders": 0,
                    "by_store": defaultdict(lambda: {"qty":0.0,"revenue":0.0}),
                }
            pa = prod_agg[pid]
            pa["qty"]     += ps.get("qty", 0)
            pa["revenue"] += ps.get("revenue", 0)
            pa["orders"]  += ps.get("orders", 0)
            for store, sv in (ps.get("by_store") or {}).items():
                pa["by_store"][store]["qty"]     += sv.get("qty",0)
                pa["by_store"][store]["revenue"] += sv.get("revenue",0)

    top_products = sorted(
        [{"product_id":pid,
          "reference": pa["reference"],
          "name": pa["name"],
          "category_name": pa["category_name"],
          "qty": round(pa["qty"],1),
          "revenue": round(pa["revenue"],2),
          "orders": pa["orders"],
          "avg_price": round(pa["revenue"]/pa["qty"],2) if pa["qty"] else 0,
          "by_store": {s:{"qty":round(v["qty"],1),"revenue":round(v["revenue"],2)}
                       for s,v in pa["by_store"].items()}}
         for pid, pa in prod_agg.items()],
        key=lambda x: x["revenue"], reverse=True
    )[:30]

    total_rev    = sum(store_totals.values())
    total_orders = sum(store_orders.values())

    return {
        "months":        months_list,
        "days":          all_days,
        "stores":        ALL_STORES,
        "total_revenue": round(total_rev, 2),
        "total_orders":  total_orders,
        "store_totals":  {s: round(store_totals[s], 2) for s in ALL_STORES},
        "store_orders":  {s: store_orders[s]           for s in ALL_STORES},
        "store_avg_ticket": store_avg,
        "monthly_revenue": {s: monthly_rev[s] for s in ALL_STORES},
        "monthly_orders":  {s: monthly_ord[s] for s in ALL_STORES},
        "daily_revenue":   {s: daily_rev[s]   for s in ALL_STORES},
        "top_products":    top_products,
        "has_products":    len(top_products) > 0,
    }

# ─── ROUTES ──────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(SCRIPT_DIR, "dynamic_dashboard.html")

@app.route("/api/data")
def api_data():
    from_str = request.args.get("from", "")
    to_str   = request.args.get("to",   "")
    try:
        from_dt = datetime.strptime(from_str, "%Y-%m")
        to_dt   = datetime.strptime(to_str,   "%Y-%m")
    except Exception:
        to_dt   = datetime.now().replace(day=1)
        from_dt = datetime(to_dt.year - 1, to_dt.month, 1)

    # Build list of months in range
    months_list = []
    cur = from_dt
    while cur <= to_dt:
        months_list.append(cur.strftime("%Y-%m"))
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)

    print(f"📊 /api/data {from_str}→{to_str} ({len(months_list)} meses)")

    # Fetch any missing months from Moloni (summaries only — fast)
    missing = [m for m in months_list if m not in _monthly_cache]
    if missing:
        print(f"  🔄 {len(missing)} meses em falta: {missing}")
        for m in missing:
            y, mo = int(m[:4]), int(m[5:])
            try:
                fetch_month_summaries(y, mo)
            except Exception as e:
                print(f"  ⚠️  {m}: {e}")

    result = build_response(months_list)
    return jsonify(result)

@app.route("/api/available_months")
def api_available_months():
    cached   = sorted(_monthly_cache.keys())
    now      = datetime.now()
    start    = datetime(2024, 1, 1)
    available = []
    cur = start
    while cur <= now:
        available.append(cur.strftime("%Y-%m"))
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
    return jsonify({"cached": cached, "available": available,
                    "has_products": sorted(_products_cache.keys())})

@app.route("/products")
def products_page():
    return send_from_directory(SCRIPT_DIR, "products_v2.html")

@app.route("/products/categorizar")
def categorize_page():
    return send_from_directory(SCRIPT_DIR, "categorize.html")

@app.route("/magento")
def magento_report():
    return send_from_directory(SCRIPT_DIR, "relatorio_magento.html")

@app.route("/genero")
def genero_report():
    return send_from_directory(SCRIPT_DIR, "relatorio_genero.html")

@app.route("/crm")
def crm_page():
    return send_from_directory(SCRIPT_DIR, "crm_clientes.html")

_crm_refresh_lock = threading.Lock()
_crm_refresh_status = {"running": False, "log": [], "last_run": "", "error": ""}

@app.route("/api/crm/refresh")
def api_crm_refresh():
    """Corre crm_clientes.py e regenera o HTML. Use ?full=1 para buscar do Magento."""
    if _crm_refresh_status["running"]:
        return jsonify({"ok": False, "error": "Atualização já em curso"}), 409

    full = request.args.get("full", "0") == "1"

    def run():
        _crm_refresh_status["running"] = True
        _crm_refresh_status["log"] = []
        _crm_refresh_status["error"] = ""
        try:
            script = os.path.join(SCRIPT_DIR, "crm_clientes.py")
            cmd = ["python3", script] + (["--refresh"] if full else [])
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, cwd=SCRIPT_DIR)
            for line in proc.stdout:
                _crm_refresh_status["log"].append(line.rstrip())
            proc.wait()
            if proc.returncode != 0:
                _crm_refresh_status["error"] = f"Erro ao correr script (código {proc.returncode})"
            else:
                load_crm_data()  # recarrega em memória após refresh bem-sucedido
                if _crm_customers:
                    neon_save("crm_data", _crm_customers)
        except Exception as e:
            _crm_refresh_status["error"] = str(e)
        finally:
            _crm_refresh_status["running"] = False
            _crm_refresh_status["last_run"] = datetime.now().strftime("%d/%m/%Y %H:%M")

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return jsonify({"ok": True, "full": full})

@app.route("/api/crm/status")
def api_crm_status():
    return jsonify(_crm_refresh_status)

@app.route("/api/crm/lite")
def api_crm_lite():
    """Lista leve de todos os clientes (sem orders/products) — servida da memória."""
    if not _crm_lite:
        return jsonify({"error": "crm_data.json não encontrado. Corre crm_clientes.py primeiro."}), 404
    from flask import make_response
    resp = make_response(json.dumps(_crm_lite, ensure_ascii=False))
    resp.headers["Content-Type"] = "application/json; charset=utf-8"
    resp.headers["Cache-Control"] = "no-cache"
    return resp

@app.route("/api/crm/customer/<int:idx>")
def api_crm_customer(idx):
    """Devolve o perfil completo de um cliente pelo seu índice no ranking — da memória."""
    if not _crm_customers:
        return jsonify({"error": "crm_data.json não encontrado. Corre crm_clientes.py primeiro."}), 404
    if idx < 0 or idx >= len(_crm_customers):
        return jsonify({"error": "Cliente não encontrado"}), 404
    return jsonify(_crm_customers[idx])

@app.route("/api/categorize_suggestions")
def api_categorize():
    path = os.path.join(SCRIPT_DIR, "categorize_suggestions.json")
    if not os.path.exists(path):
        return jsonify({"error": "Corre primeiro: python3 categorize_products.py"}), 404
    with open(path) as f:
        return jsonify(json.load(f))

def _unique_clients(from_key, to_key, store_filter=None):
    """Count total transactions (customer visits) across a date range (physical stores only)."""
    total = 0
    cur = datetime.strptime(from_key, "%Y-%m-%d")
    end = datetime.strptime(to_key, "%Y-%m-%d")
    while cur <= end:
        day = cur.strftime("%Y-%m-%d")
        day_data = _clients_by_day.get(day, {})
        for store, count in day_data.items():
            if store_filter and store != store_filter:
                continue
            total += count
        cur += timedelta(days=1)
    return total

def _aggregate_period(from_key, to_key, granularity="day", buckets=None, store_filter=None):
    """Aggregate product data for a date range with optional store filter.
    New format: by_day.{day}.s.{store} = [qty, revenue] (exact per-store data).
    """

    def date_to_bucket(day_str):
        if granularity == "month":
            return day_str[:7]
        elif granularity == "week":
            d = datetime.strptime(day_str, "%Y-%m-%d")
            monday = d - timedelta(days=d.weekday())
            return monday.strftime("%Y-%m-%d")
        return day_str

    prod_agg  = {}
    cat_agg   = defaultdict(lambda: {"qty": 0.0, "revenue": 0.0, "products": set()})
    store_agg = {s: {"qty": 0.0, "revenue": 0.0, "orders": 0} for s in STORES}

    for pid, product in _products_v2.items():
        qty_total = 0.0
        rev_total = 0.0
        orders_total = 0
        by_bucket = defaultdict(lambda: {"qty": 0.0, "revenue": 0.0})
        by_store_acc = defaultdict(lambda: {"qty": 0.0, "revenue": 0.0})

        for day_str, dv in product.get("by_day", {}).items():
            if day_str < from_key or day_str > to_key:
                continue

            # New format: dv = {"q": qty, "r": rev, "s": {"Store": [qty, rev]}}
            # Old format: dv = {"qty": qty, "revenue": rev}
            stores_data = dv.get("s", {})

            if stores_data:
                # New format (v3) — exact per-store data (may include negatives from credit notes)
                for store_name, vals in stores_data.items():
                    sq, sr = vals[0], vals[1]
                    if store_name in EXCLUDED_STORES:
                        continue
                    if store_filter and store_name != store_filter:
                        continue
                    qty_total += sq
                    rev_total += sr
                    if sr > 0:
                        orders_total += 1
                    by_store_acc[store_name]["qty"]     += sq
                    by_store_acc[store_name]["revenue"] += sr
                    if buckets is not None:
                        bucket = date_to_bucket(day_str)
                        by_bucket[bucket]["qty"]     += sq
                        by_bucket[bucket]["revenue"] += sr
            else:
                # Old format (v2) — no store breakdown, skip if store filter active
                if store_filter:
                    continue
                q = dv.get("qty") or dv.get("q", 0)
                r = dv.get("revenue") or dv.get("r", 0)
                qty_total += q
                rev_total += r
                orders_total += 1
                if buckets is not None:
                    bucket = date_to_bucket(day_str)
                    by_bucket[bucket]["qty"]     += q
                    by_bucket[bucket]["revenue"] += r

        # Always apply store-level contributions (even for zero/negative total products)
        # This handles cross-store returns (sold in Porto, returned via Online)
        has_store_data = False
        for store in STORES:
            sv = by_store_acc.get(store, {"qty": 0.0, "revenue": 0.0})
            if sv["revenue"] != 0 or sv["qty"] != 0:
                has_store_data = True
            store_agg[store]["qty"]     += sv["qty"]
            store_agg[store]["revenue"] += sv["revenue"]
            if sv["revenue"] > 0:
                store_agg[store]["orders"] += orders_total

        # Skip products with no activity at all
        if not has_store_data:
            continue

        cat_name = product.get("category_name", "Sem Categoria") or "Sem Categoria"
        cat_agg[cat_name]["qty"]      += qty_total
        cat_agg[cat_name]["revenue"]  += rev_total
        cat_agg[cat_name]["products"].add(pid)

        # Only add to product list if revenue > 0 (products fully returned don't show in table)
        if rev_total <= 0:
            continue

        entry = {
            "product_id":    pid,
            "reference":     product.get("reference", ""),
            "name":          product.get("name", ""),
            "category_name": cat_name,
            "qty":     round(qty_total, 1),
            "revenue": round(rev_total, 2),
            "orders":  orders_total,
            "avg_price": round(rev_total / qty_total, 2) if qty_total else 0,
            "by_store": {s: {"qty":     round(by_store_acc[s]["qty"], 1),
                             "revenue": round(by_store_acc[s]["revenue"], 2)}
                         for s in STORES if by_store_acc[s]["revenue"] != 0},
        }
        if buckets is not None:
            entry["trend"] = {b: round(by_bucket[b]["revenue"], 2)
                              for b in buckets if by_bucket[b]["revenue"] != 0}
        prod_agg[pid] = entry

    # Total revenue/qty comes from store_agg (includes credit note subtractions)
    # prod_agg only has products with positive revenue (for display)
    total_rev = sum(store_agg[s]["revenue"] for s in STORES)
    total_qty = sum(store_agg[s]["qty"]     for s in STORES)
    return prod_agg, cat_agg, store_agg, round(total_rev, 2), round(total_qty, 1)


def _pct_change(cur, prev):
    if not prev or prev == 0:
        return None
    return round((cur - prev) / prev * 100, 1)


@app.route("/api/products")
def api_products():
    from_str    = request.args.get("from", "")
    to_str      = request.args.get("to",   "")
    granularity = request.args.get("granularity", "day")
    store_filter = request.args.get("store", "") or None  # optional store filter

    now = datetime.now()
    try:
        from_dt = datetime.strptime(from_str, "%Y-%m-%d")
    except Exception:
        from_dt = (now - timedelta(days=89)).replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        to_dt = datetime.strptime(to_str, "%Y-%m-%d")
    except Exception:
        to_dt = now.replace(hour=23, minute=59, second=59, microsecond=0)

    from_key = from_dt.strftime("%Y-%m-%d")
    to_key   = to_dt.strftime("%Y-%m-%d")

    # Build bucket list
    def date_to_bucket(day_str):
        if granularity == "month":
            return day_str[:7]
        elif granularity == "week":
            d = datetime.strptime(day_str, "%Y-%m-%d")
            monday = d - timedelta(days=d.weekday())
            return monday.strftime("%Y-%m-%d")
        return day_str

    buckets_set = set()
    cur = from_dt
    while cur <= to_dt:
        buckets_set.add(date_to_bucket(cur.strftime("%Y-%m-%d")))
        cur += timedelta(days=1)
    buckets = sorted(buckets_set)

    # ── Current period ──
    prod_agg, cat_agg, store_agg, total_rev, total_qty = _aggregate_period(
        from_key, to_key, granularity, buckets, store_filter)

    # ── Unique clients ──
    unique_clients     = _unique_clients(from_key, to_key, store_filter)
    avg_ticket_client  = round(total_rev / unique_clients, 2) if unique_clients else 0

    # ── Previous period ──
    period_days = (to_dt - from_dt).days + 1
    prev_to_dt   = from_dt - timedelta(days=1)
    prev_from_dt = prev_to_dt - timedelta(days=period_days - 1)
    prev_from_key = prev_from_dt.strftime("%Y-%m-%d")
    prev_to_key   = prev_to_dt.strftime("%Y-%m-%d")

    prev_prod, prev_cat, prev_store, prev_total_rev, prev_total_qty = _aggregate_period(
        prev_from_key, prev_to_key, store_filter=store_filter)

    # ── Year-over-year period (same dates, previous year) ──
    yoy_from_dt = from_dt.replace(year=from_dt.year - 1)
    yoy_to_dt   = to_dt.replace(year=to_dt.year - 1)
    yoy_from_key = yoy_from_dt.strftime("%Y-%m-%d")
    yoy_to_key   = yoy_to_dt.strftime("%Y-%m-%d")

    yoy_prod, yoy_cat, yoy_store, yoy_total_rev, yoy_total_qty = _aggregate_period(
        yoy_from_key, yoy_to_key, store_filter=store_filter)

    # ── Custom comparison period (compare_from / compare_to) ──
    compare_from_str = request.args.get("compare_from", "")
    compare_to_str   = request.args.get("compare_to", "")
    has_compare = False
    compare_prod = {}
    compare_cat  = {}
    compare_store = {}
    compare_total_rev = 0
    compare_total_qty = 0
    compare_from_key = ""
    compare_to_key   = ""

    if compare_from_str and compare_to_str:
        try:
            compare_from_dt = datetime.strptime(compare_from_str, "%Y-%m-%d")
            compare_to_dt   = datetime.strptime(compare_to_str, "%Y-%m-%d")
            compare_from_key = compare_from_dt.strftime("%Y-%m-%d")
            compare_to_key   = compare_to_dt.strftime("%Y-%m-%d")
            compare_prod, compare_cat, compare_store, compare_total_rev, compare_total_qty = _aggregate_period(
                compare_from_key, compare_to_key, store_filter=store_filter)
            has_compare = True
        except Exception:
            pass

    # ── Enrich products ──
    for pid, entry in prod_agg.items():
        prev = prev_prod.get(pid)
        if prev:
            entry["prev_revenue"] = prev["revenue"]
            entry["prev_qty"]     = prev["qty"]
            entry["rev_change"]   = _pct_change(entry["revenue"], prev["revenue"])
            entry["qty_change"]   = _pct_change(entry["qty"],     prev["qty"])
        else:
            entry["prev_revenue"] = 0
            entry["prev_qty"]     = 0
            entry["rev_change"]   = None
            entry["qty_change"]   = None
        # YoY
        yoy = yoy_prod.get(pid)
        if yoy:
            entry["yoy_revenue"]  = yoy["revenue"]
            entry["yoy_rev_change"] = _pct_change(entry["revenue"], yoy["revenue"])
        else:
            entry["yoy_revenue"]  = 0
            entry["yoy_rev_change"] = None
        # Custom comparison
        if has_compare:
            comp = compare_prod.get(pid)
            if comp:
                entry["compare_revenue"]    = comp["revenue"]
                entry["compare_rev_change"] = _pct_change(entry["revenue"], comp["revenue"])
            else:
                entry["compare_revenue"]    = 0
                entry["compare_rev_change"] = None

    products_sorted = sorted(prod_agg.values(), key=lambda x: x["revenue"], reverse=True)

    # ── Enrich categories ──
    cats_sorted = []
    for name, v in cat_agg.items():
        prev_c = prev_cat.get(name, {"revenue": 0, "qty": 0})
        yoy_c  = yoy_cat.get(name, {"revenue": 0, "qty": 0})
        cat_entry = {
            "name": name,
            "qty": round(v["qty"], 1),
            "revenue": round(v["revenue"], 2),
            "unique_products": len(v["products"]),
            "prev_revenue": round(prev_c["revenue"], 2),
            "rev_change": _pct_change(v["revenue"], prev_c["revenue"]),
            "yoy_revenue": round(yoy_c["revenue"], 2),
            "yoy_rev_change": _pct_change(v["revenue"], yoy_c["revenue"]),
        }
        if has_compare:
            comp_c = compare_cat.get(name, {"revenue": 0, "qty": 0})
            cat_entry["compare_revenue"]    = round(comp_c["revenue"], 2)
            cat_entry["compare_rev_change"] = _pct_change(v["revenue"], comp_c["revenue"])
        cats_sorted.append(cat_entry)
    cats_sorted.sort(key=lambda x: x["revenue"], reverse=True)

    # ── Enrich stores ──
    store_totals = {}
    for s in STORES:
        cur_s  = store_agg[s]
        prev_s = prev_store.get(s, {"revenue": 0, "qty": 0, "orders": 0})
        yoy_s  = yoy_store.get(s, {"revenue": 0, "qty": 0, "orders": 0})
        st_entry = {
            "qty":     round(cur_s["qty"], 1),
            "revenue": round(cur_s["revenue"], 2),
            "orders":  cur_s["orders"],
            "prev_revenue": round(prev_s["revenue"], 2),
            "rev_change":   _pct_change(cur_s["revenue"], prev_s["revenue"]),
            "yoy_revenue":  round(yoy_s["revenue"], 2),
            "yoy_rev_change": _pct_change(cur_s["revenue"], yoy_s["revenue"]),
        }
        if has_compare:
            comp_s = compare_store.get(s, {"revenue": 0, "qty": 0, "orders": 0})
            st_entry["compare_revenue"]    = round(comp_s["revenue"], 2)
            st_entry["compare_rev_change"] = _pct_change(cur_s["revenue"], comp_s["revenue"])
        store_totals[s] = st_entry

    result = {
        "from":         from_key,
        "to":           to_key,
        "granularity":  granularity,
        "buckets":      buckets,
        "period_days":  period_days,
        "prev_from":    prev_from_key,
        "prev_to":      prev_to_key,
        "yoy_from":     yoy_from_key,
        "yoy_to":       yoy_to_key,
        "store_filter": store_filter or "",
        "total_revenue":      total_rev,
        "total_qty":          total_qty,
        "prev_total_revenue": prev_total_rev,
        "prev_total_qty":     prev_total_qty,
        "rev_change":   _pct_change(total_rev, prev_total_rev),
        "qty_change":   _pct_change(total_qty, prev_total_qty),
        "yoy_total_revenue":  yoy_total_rev,
        "yoy_total_qty":      yoy_total_qty,
        "yoy_rev_change":     _pct_change(total_rev, yoy_total_rev),
        "yoy_qty_change":     _pct_change(total_qty, yoy_total_qty),
        "unique_products":      len(prod_agg),
        "unique_clients":       unique_clients,
        "avg_ticket_client":    avg_ticket_client,
        "categories":           cats_sorted,
        "store_totals":         store_totals,
        "products":             products_sorted,
        "data_from":    _products_v2_date_from,
        "data_to":      _products_v2_date_to,
        "has_v2_data":  len(_products_v2) > 0,
    }

    if has_compare:
        result["compare_from"]          = compare_from_key
        result["compare_to"]            = compare_to_key
        result["compare_total_revenue"] = compare_total_rev
        result["compare_total_qty"]     = compare_total_qty
        result["compare_rev_change"]    = _pct_change(total_rev, compare_total_rev)
        result["compare_qty_change"]    = _pct_change(total_qty, compare_total_qty)

    return jsonify(result)

@app.route("/api/reload_products")
def api_reload_products():
    """Hot-reload products_data_v2.json and clients_data.json without restarting."""
    global _products_v2, _products_v2_date_from, _products_v2_date_to, _clients_by_day
    prod_v2_path = os.path.join(SCRIPT_DIR, "products_data_v2.json")
    if not os.path.exists(prod_v2_path):
        return jsonify({"ok": False, "error": "products_data_v2.json not found"}), 404
    with open(prod_v2_path, encoding="utf-8") as f:
        pv2 = json.load(f)
    _products_v2 = {}
    for product in pv2.get("products", []):
        _products_v2[product["product_id"]] = product
    _products_v2_date_from = pv2.get("date_from", "")
    _products_v2_date_to   = pv2.get("date_to", "")
    # Reload clients data
    clients_path = os.path.join(SCRIPT_DIR, "clients_data.json")
    if os.path.exists(clients_path):
        with open(clients_path, encoding="utf-8") as f:
            _clients_by_day = json.load(f).get("by_day", {})
    return jsonify({"ok": True, "products": len(_products_v2),
                    "date_from": _products_v2_date_from, "date_to": _products_v2_date_to})


# ── Magento Report Update ────────────────────────────────────────────────────
_update_state = {"running": False, "log": [], "last_update": None, "error": None}

@app.route("/api/magento_update", methods=["POST"])
def api_magento_update():
    global _update_state
    if _update_state["running"]:
        return jsonify({"ok": False, "error": "Atualização já em curso"}), 409

    def run():
        global _update_state
        _update_state = {"running": True, "log": [], "last_update": None, "error": None}
        try:
            import importlib, sys
            # Forçar reload para garantir que o código mais recente é sempre usado
            import update_relatorio
            importlib.reload(update_relatorio)
            from update_relatorio import run_update
            def log(msg):
                _update_state["log"].append(msg)
                print(msg)
            run_update(log=log)
            _update_state["last_update"] = datetime.now().strftime("%d/%m/%Y %H:%M")
        except Exception as e:
            _update_state["error"] = str(e)
            _update_state["log"].append(f"❌ Erro: {e}")
        finally:
            _update_state["running"] = False

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True, "message": "Atualização iniciada"})

@app.route("/api/magento_update/status")
def api_magento_update_status():
    return jsonify({
        "running":     _update_state["running"],
        "log":         _update_state["log"][-50:],
        "last_update": _update_state["last_update"],
        "error":       _update_state["error"],
    })

@app.route("/rfv")
def rfv_page():
    return send_from_directory(SCRIPT_DIR, "rfv.html")

@app.route("/api/crm/rfv")
def api_crm_rfv():
    """Matriz RFV — servida da memória."""
    if not _crm_rfv:
        return jsonify({"error": "crm_data.json não encontrado"}), 404
    from flask import make_response
    resp = make_response(json.dumps(_crm_rfv, ensure_ascii=False))
    resp.headers['Content-Type'] = 'application/json; charset=utf-8'
    return resp

if __name__ == "__main__":
    print("=" * 45)
    print("🪨  Cavemen Store Dashboard")
    print("=" * 45)
    load_precomputed()
    print()
    print("🌐  Abre no browser: http://localhost:5001")
    print("─" * 45)
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=False, port=port, host="0.0.0.0", threaded=True)
