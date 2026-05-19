#!/usr/bin/env python3
"""
Atualiza relatorio_magento.html com dados frescos do Magento.
Pode ser chamado diretamente ou pelo servidor Flask via /api/magento_update.
"""

import requests, json, re, os, unicodedata, time
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# ── Config ────────────────────────────────────────────────────────────────────
MAGENTO_URL  = os.environ.get("MAGENTO_URL",  "https://www.cavemenstore.com")
MAGENTO_USER = os.environ.get("MAGENTO_USER", "marketing@cavemenstore.com")
MAGENTO_PASS = os.environ.get("MAGENTO_PASS", "3}rRPvf5_5Wj_a6e4s6e5")
DATE_FROM    = datetime(2024, 1, 1)
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
HTML_FILE    = os.path.join(SCRIPT_DIR, "relatorio_magento.html")

# ── Gender detection ──────────────────────────────────────────────────────────
try:
    import gender_guesser.detector as gender_lib
    _detector = gender_lib.Detector(case_sensitive=False)
except ImportError:
    _detector = None

MANUAL_GENDER = {
    "Leonor":"female","Matilde":"female","Inês":"female","Beatriz":"female",
    "Margarida":"female","Francisca":"female","Filipa":"female","Madalena":"female",
    "Constança":"female","Bruna":"female","Joana":"female","Daniela":"female",
    "Patrícia":"female","Raquel":"female","Vanessa":"female","Cláudia":"female",
    "Mónica":"female","Verónica":"female","Débora":"female","Nádia":"female",
    "Sónia":"female","Zélia":"female","Fátima":"female","Lurdes":"female",
    "Dulce":"female","Graça":"female","Conceição":"female","Vânia":"female",
    "Tânia":"female","Cátia":"female","Célia":"female","Lídia":"female",
    "Érica":"female","Letícia":"female","Jéssica":"female","Priscila":"female",
    "Íris":"female","Stéphanie":"female","Stephanie":"female","Iara":"female",
    "Rui":"male","Nuno":"male","Luís":"male","Gonçalo":"male","Afonso":"male",
    "Rodrigo":"male","Diogo":"male","Tomás":"male","Duarte":"male","Simão":"male",
    "Dinis":"male","Martim":"male","Vasco":"male","Álvaro":"male","Lourenço":"male",
    "Renato":"male","Sérgio":"male","Hélder":"male","Dário":"male","Valter":"male",
    "Nélson":"male","Fábio":"male","Ivo":"male","Tiago":"male","Flávio":"male",
    "Óscar":"male","Cláudio":"male","Márcio":"male","Mário":"male","Vítor":"male",
    "Humberto":"male","Américo":"male","Telmo":"male","Zé":"male","Zeca":"male",
}

def get_gender(firstname):
    if not firstname: return "unknown"
    name = firstname.strip().split()[0]
    if name in MANUAL_GENDER: return MANUAL_GENDER[name]
    norm = ''.join(c for c in unicodedata.normalize('NFD', name) if unicodedata.category(c) != 'Mn')
    if norm in MANUAL_GENDER: return MANUAL_GENDER[norm]
    if _detector:
        r = _detector.get_gender(name)
        if r in ("female","mostly_female"): return "female"
        if r in ("male","mostly_male"):    return "male"
    return "unknown"

# ── Helpers ───────────────────────────────────────────────────────────────────
def to_lisbon_date(dt_str):
    if not dt_str: return ""
    try:
        dt = datetime.strptime(dt_str[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        lisbon_offset = timedelta(hours=1)  # UTC+1 (simplificado; DST não aplicado)
        return (dt + lisbon_offset).strftime("%Y-%m-%d")
    except Exception:
        return dt_str[:10]

def get_revenue_date(order):
    histories = order.get("status_histories", [])
    if histories:
        sorted_hist = sorted(histories, key=lambda h: h.get("created_at",""))
        if sorted_hist and sorted_hist[0].get("status") == "pending":
            for h in sorted_hist:
                if h.get("status") == "processing":
                    return to_lisbon_date(h.get("created_at",""))
    return to_lisbon_date(order.get("created_at",""))

# ── Magento API ───────────────────────────────────────────────────────────────
def get_token():
    r = requests.post(f"{MAGENTO_URL}/rest/V1/integration/admin/token",
                      json={"username": MAGENTO_USER, "password": MAGENTO_PASS}, timeout=30)
    r.raise_for_status()
    return r.json()

def fetch_orders(token, status="complete", log=print):
    H = {"Authorization": f"Bearer {token}"}
    all_orders, page = [], 1
    fields = ("items[entity_id,increment_id,created_at,status,grand_total,"
              "customer_firstname,customer_email,customer_is_guest,billing_address,"
              "status_histories,items[name,qty_ordered,price,price_incl_tax,"
              "row_total,row_total_incl_tax,product_type,sku,parent_item_id,item_id]],"
              "total_count")
    while True:
        params = {
            "searchCriteria[pageSize]": 200,
            "searchCriteria[currentPage]": page,
            "searchCriteria[filterGroups][0][filters][0][field]": "status",
            "searchCriteria[filterGroups][0][filters][0][value]": status,
            "searchCriteria[filterGroups][0][filters][0][conditionType]": "eq",
            "fields": fields,
        }
        data = requests.get(f"{MAGENTO_URL}/rest/V1/orders", headers=H, params=params, timeout=60).json()
        items = data.get("items", [])
        all_orders.extend(items)
        total = data.get("total_count", 0)
        log(f"  [{status}] Página {page}: {len(all_orders)}/{total}")
        if len(all_orders) >= total or not items: break
        page += 1
        time.sleep(0.1)

    # ── Supplementary fetch: last 45 days to catch orders missed by pagination ──
    # When the API paginates sorted by created_at ASC, orders completing mid-fetch
    # can shift pages and get skipped. We fetch recent orders separately and merge.
    seen_ids = {o["entity_id"] for o in all_orders}
    cutoff = (datetime.utcnow() - timedelta(days=45)).strftime("%Y-%m-%d %H:%M:%S")
    log(f"  [{status}] Verificação suplementar: encomendas desde {cutoff[:10]}...")
    sup_page, sup_added = 1, 0
    while True:
        params = {
            "searchCriteria[pageSize]": 200,
            "searchCriteria[currentPage]": sup_page,
            "searchCriteria[filterGroups][0][filters][0][field]": "status",
            "searchCriteria[filterGroups][0][filters][0][value]": status,
            "searchCriteria[filterGroups][0][filters][0][conditionType]": "eq",
            "searchCriteria[filterGroups][1][filters][0][field]": "created_at",
            "searchCriteria[filterGroups][1][filters][0][value]": cutoff,
            "searchCriteria[filterGroups][1][filters][0][conditionType]": "gteq",
            "searchCriteria[sortOrders][0][field]": "entity_id",
            "searchCriteria[sortOrders][0][direction]": "DESC",
            "fields": fields,
        }
        data = requests.get(f"{MAGENTO_URL}/rest/V1/orders", headers=H, params=params, timeout=60).json()
        items = data.get("items", [])
        if not items: break
        for o in items:
            if o["entity_id"] not in seen_ids:
                all_orders.append(o)
                seen_ids.add(o["entity_id"])
                sup_added += 1
        if len(items) < 200: break
        sup_page += 1
        time.sleep(0.1)
    if sup_added:
        log(f"  [{status}] +{sup_added} encomendas encontradas na verificação suplementar")
    else:
        log(f"  [{status}] Verificação suplementar: sem encomendas em falta")

    return all_orders

# ── Products processing ───────────────────────────────────────────────────────
NAME_CORRECTIONS = {}  # pode ser expandido

CATEGORY_RULES = [
    ("conjunto",                                  "Conjuntos"),
    ("calça com cordão",                          "Calças de Tecido Técnico"),
    ("calças com cordão",                         "Calças de Tecido Técnico"),
    ("calça de tecido técnico",                   "Calças de Tecido Técnico"),
    ("calças de tecido técnico",                  "Calças de Tecido Técnico"),
    ("calça de tecido",                           "Calças de Tecido"),
    ("calças de tecido",                          "Calças de Tecido"),
    ("calça de alfaiataria",                      "Calças de Tecido"),
    ("calças de alfaiataria",                     "Calças de Tecido"),
    ("calça chino",                               "Calças Chino"),
    ("calças chino",                              "Calças Chino"),
    ("calça de ganga",                            "Calças de Ganga"),
    ("calças de ganga",                           "Calças de Ganga"),
    ("sobrecamisa",                               "Sobrecamisas"),
    ("camisola",                                  "Camisolas"),
    ("camisa",                                    "Camisas"),
    ("cardigan",                                  "Cardigans"),
    ("malha",                                     "Malhas"),
    ("calça de sarja",                            "Calças de Sarja"),
    ("calças de sarja",                           "Calças de Sarja"),
    ("calça de fato de treino",                   "Fato de Treino"),
    ("calças de fato de treino",                  "Fato de Treino"),
    ("casaco de felpa",                           "Casaco de Felpa - Fato de Treino"),
    ("casaco",                                    "Casacos"),
    ("fato",                                      "Fatos"),
    ("colete",                                    "Fatos"),
    ("t-shirt",                                   "T-Shirts"),
    ("polo",                                      "Polo"),
    ("perfume",                                   "Perfumes"),
    ("botões de punho",                           "Botões de Punho"),
    ("botão de punho",                            "Botões de Punho"),
    ("blazer",                                    "Blazers"),
    ("sapato",                                    "Sapatos"),
    ("mocassin",                                  "Sapatos"),
    ("sapatilha",                                 "Sapatilhas"),
    ("pulseira",                                  "Acessórios"),
    ("colar",                                     "Acessórios"),
    ("pack",                                      "Acessórios"),
    ("malas & necessaires",                       "Acessórios"),
    ("luvas & carteiras em pele",                 "Acessórios"),
    ("cinto",                                     "Acessórios"),
    ("fio",                                       "Acessórios"),
    ("porta chaves",                              "Acessórios"),
    ("porta-chaves",                              "Acessórios"),
    ("camiseiro",                                 "Camisas"),
]

def categorize_product(name):
    name_lower = name.strip().lower()
    for prefix, category in CATEGORY_RULES:
        if name_lower.startswith(prefix.lower()):
            return category
    if name_lower.startswith("calça") and "de tecido" in name_lower:
        return "Calças de Tecido"
    return "Outros"

def process_products(orders, pending_orders=None):
    products_data = {}
    days_set = set()

    for order in orders:
        day = to_lisbon_date(order.get("created_at", ""))
        if not day or len(day) < 10: continue
        days_set.add(day)

        grand_total = float(order.get("grand_total") or 0)
        raw_item_total = 0.0
        for item in order.get("items", []):
            if item.get("product_type") == "configurable":
                raw_item_total += float(item.get("row_total_incl_tax") or 0)
            elif not item.get("parent_item_id"):
                raw_item_total += float(item.get("row_total_incl_tax") or 0)

        scale = (grand_total / raw_item_total) if raw_item_total > 0 else 0.0

        parent_revenue, parent_gross, parent_name = {}, {}, {}
        for item in order.get("items", []):
            if item.get("product_type") == "configurable":
                iid  = item.get("item_id")
                raw  = float(item.get("row_total_incl_tax") or item.get("row_total") or 0)
                qty_ = float(item.get("qty_ordered") or 1)
                price= float(item.get("price_incl_tax") or item.get("price") or 0)
                parent_revenue[iid] = raw * scale
                parent_gross[iid]   = price * qty_
                parent_name[iid]    = item.get("name", "")

        for item in order.get("items", []):
            if item.get("product_type") == "configurable": continue
            sku = item.get("sku", "N/A")
            qty = float(item.get("qty_ordered", 0))
            parent_id = item.get("parent_item_id")
            if parent_id and parent_id in parent_revenue:
                rev   = parent_revenue[parent_id]
                gross = parent_gross.get(parent_id, rev)
                name  = parent_name.get(parent_id) or item.get("name", sku)
            else:
                raw   = float(item.get("row_total_incl_tax") or item.get("row_total") or 0)
                rev   = raw * scale
                price = float(item.get("price_incl_tax") or item.get("price") or 0)
                gross = price * qty
                name  = item.get("name", sku)

            if sku not in products_data:
                products_data[sku] = {"name": name, "categories": [categorize_product(name)], "days": {}, "pending_days": {}}
            d = products_data[sku]["days"]
            if day not in d: d[day] = {"qty": 0, "revenue": 0.0, "gross": 0.0}
            d[day]["qty"]     += qty
            d[day]["revenue"] += rev
            d[day]["gross"]   += gross

    for order in (pending_orders or []):
        day = to_lisbon_date(order.get("created_at", ""))
        if not day or len(day) < 10: continue
        parent_name_p, parent_price_p = {}, {}
        for item in order.get("items", []):
            if item.get("product_type") == "configurable":
                iid = item.get("item_id")
                parent_name_p[iid]  = item.get("name", "")
                parent_price_p[iid] = float(item.get("price_incl_tax") or item.get("price") or 0)
        for item in order.get("items", []):
            if item.get("product_type") == "configurable": continue
            sku = item.get("sku", "N/A")
            qty = float(item.get("qty_ordered", 0))
            parent_id = item.get("parent_item_id")
            name  = parent_name_p.get(parent_id) or item.get("name", sku)
            value = (parent_price_p.get(parent_id, 0) or float(item.get("price_incl_tax") or item.get("price") or 0)) * qty
            if sku not in products_data:
                products_data[sku] = {"name": name, "categories": [categorize_product(name)], "days": {}, "pending_days": {}}
            pd = products_data[sku].setdefault("pending_days", {})
            if day not in pd: pd[day] = {"qty": 0, "value": 0.0}
            pd[day]["qty"]   += qty
            pd[day]["value"] += value

    months_list = sorted(set(d[:7] for d in days_set))
    return products_data, months_list

# ── Gender processing ─────────────────────────────────────────────────────────
def process_gender(orders):
    valid_statuses = {"processing","complete","closed"}
    monthly_stats = defaultdict(lambda: {
        "male":    {"orders":0,"revenue":0.0},
        "female":  {"orders":0,"revenue":0.0},
        "unknown": {"orders":0,"revenue":0.0},
    })
    monthly_products = defaultdict(lambda: {
        "male":   defaultdict(lambda: {"qty":0,"revenue":0.0}),
        "female": defaultdict(lambda: {"qty":0,"revenue":0.0}),
    })
    monthly_cities = defaultdict(lambda: defaultdict(lambda: {"orders":0,"revenue":0.0,"male":0,"female":0}))
    customers = {"male": set(), "female": set(), "unknown": set()}

    for order in orders:
        if order.get("status","") not in valid_statuses: continue
        total = float(order.get("grand_total",0) or 0)
        if total <= 0: continue
        date_str = get_revenue_date(order)
        try: date = datetime.strptime(date_str, "%Y-%m-%d")
        except: continue
        if date < DATE_FROM: continue

        month_key = date.strftime("%Y-%m")
        firstname = order.get("customer_firstname","") or ""
        email     = order.get("customer_email","") or ""
        g = get_gender(firstname)

        monthly_stats[month_key][g]["orders"]  += 1
        monthly_stats[month_key][g]["revenue"] += total
        customers[g].add(email or firstname)

        ba   = order.get("billing_address") or {}
        city = (ba.get("city") or "").strip().title()
        if city:
            monthly_cities[month_key][city]["orders"]  += 1
            monthly_cities[month_key][city]["revenue"] += total
            if g == "male":   monthly_cities[month_key][city]["male"]   += 1
            elif g == "female": monthly_cities[month_key][city]["female"] += 1

        if g in ("male","female"):
            for item in order.get("items",[]):
                price = float(item.get("price",0) or 0)
                qty   = float(item.get("qty_ordered",0) or 0)
                if price <= 0 or qty <= 0: continue
                name = item.get("name","").strip()
                name = re.sub(r'\s*[-–]?\s*(XS|S|M|L|XL|XXL|XXXL|\d{2,3})\s*$','',name,flags=re.I).strip()
                if not name: continue
                monthly_products[month_key][g][name]["qty"]     += qty
                monthly_products[month_key][g][name]["revenue"] += price * qty

    all_months = sorted(monthly_stats.keys())

    mp_serial = {}
    for month, genders in monthly_products.items():
        mp_serial[month] = {}
        for g, prods in genders.items():
            mp_serial[month][g] = sorted(
                [{"name":k,"qty":v["qty"],"revenue":v["revenue"]} for k,v in prods.items()],
                key=lambda x: x["revenue"], reverse=True
            )[:30]

    mc_serial = {}
    for month, cities in monthly_cities.items():
        mc_serial[month] = sorted(
            [{"city":c,**v} for c,v in cities.items()],
            key=lambda x: x["revenue"], reverse=True
        )[:20]

    return {
        "generated_at": datetime.now().isoformat(),
        "all_months":   all_months,
        "date_from":    DATE_FROM.strftime("%Y-%m-%d"),
        "date_to":      datetime.now().strftime("%Y-%m-%d"),
        "monthly_stats": {m: dict(v) for m,v in monthly_stats.items()},
        "monthly_products": mp_serial,
        "monthly_cities":   mc_serial,
        "customers": {g: len(s) for g,s in customers.items()},
        "search_terms": [],
    }

# ── HTML update ───────────────────────────────────────────────────────────────
def update_html(products_data, demo_data, log=print):
    if not os.path.exists(HTML_FILE):
        log(f"❌ HTML não encontrado: {HTML_FILE}")
        return False

    with open(HTML_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    # Update products-data
    old_prod = re.search(
        r'(<script type="application/json" id="products-data">)\s*\{.*?\}\s*(</script>)',
        content, re.DOTALL
    )
    if old_prod:
        new_json = json.dumps(products_data, ensure_ascii=False)
        content = content[:old_prod.start()] + f'{old_prod.group(1)}\n{new_json}\n{old_prod.group(2)}' + content[old_prod.end():]
        log(f"✅ products-data atualizado ({len(products_data)} SKUs)")
    else:
        log("⚠️  products-data tag não encontrada")

    # Update DEMO_DATA
    old_demo = re.search(r'const DEMO_DATA = \{.*?\};\n', content, re.DOTALL)
    if old_demo:
        content = content.replace(old_demo.group(0), f'const DEMO_DATA = {json.dumps(demo_data, ensure_ascii=False)};\n')
        log(f"✅ DEMO_DATA atualizado ({len(demo_data.get('all_months',[]))} meses)")
    else:
        log("⚠️  DEMO_DATA não encontrado")

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(content)

    log(f"✅ {HTML_FILE} guardado")
    return True

# ── Main ──────────────────────────────────────────────────────────────────────
def run_update(log=print):
    log("🔑 A autenticar no Magento...")
    token = get_token()
    log("✅ Token OK")

    log("📦 A buscar encomendas completas...")
    complete_orders = fetch_orders(token, status="complete", log=log)
    log(f"✅ {len(complete_orders)} encomendas completas")

    log("⏳ A buscar encomendas em processamento...")
    processing_orders = fetch_orders(token, status="processing", log=log)
    log(f"✅ {len(processing_orders)} em processamento")

    log("⏳ A buscar pendentes (Multibanco)...")
    pending = fetch_orders(token, status="pending", log=log)
    log(f"✅ {len(pending)} pendentes")

    # Combinar complete + processing para o cálculo de receita
    orders = complete_orders + processing_orders

    log("⚙️  A processar produtos...")
    products_data, months_list = process_products(orders, pending)
    log(f"✅ {len(products_data)} SKUs, {len(months_list)} meses")

    log("👥 A processar dados demográficos...")
    demo_data = process_gender(orders)
    log(f"✅ {len(demo_data['all_months'])} meses de género")

    log("💾 A atualizar HTML...")
    update_html(products_data, demo_data, log=log)

    total_rev = sum(
        d.get("revenue", 0)
        for p in products_data.values()
        for d in p.get("days", {}).values()
    )
    log(f"\n🎉 Concluído! Receita total: €{total_rev:,.2f}")
    return True

if __name__ == "__main__":
    run_update()
