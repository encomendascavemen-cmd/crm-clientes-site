#!/usr/bin/env python3
"""
Dados Demográficos — Cavemen Store (Magento)
Classifica clientes por género, cidade e termos de pesquisa.
Armazena dados por mês para filtragem dinâmica no browser.
"""

import requests, json, time, os, re
from datetime import datetime, timedelta
from collections import defaultdict
import gender_guesser.detector as gender_lib

BASE_URL           = "https://www.cavemenstore.com"
ADMIN_USER         = "marketing@cavemenstore.com"
ADMIN_PASSWORD     = "3}rRPvf5_5Wj_a6e4s6e5"
CACHE_FILE         = "gender_orders_cache.json"
SEARCH_CACHE_FILE  = "gender_search_terms_cache.json"
OUTPUT_HTML        = "relatorio_genero.html"
DATE_FROM          = datetime(2024, 1, 1)

# ── Gender detection ──────────────────────────────────────────────────────────
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
detector = gender_lib.Detector(case_sensitive=False)

def get_gender(firstname):
    if not firstname:
        return "unknown"
    name = firstname.strip().split()[0]
    if name in MANUAL_GENDER:
        return MANUAL_GENDER[name]
    import unicodedata
    name_norm = ''.join(c for c in unicodedata.normalize('NFD', name)
                        if unicodedata.category(c) != 'Mn')
    if name_norm in MANUAL_GENDER:
        return MANUAL_GENDER[name_norm]
    result = detector.get_gender(name)
    if result in ("female","mostly_female"): return "female"
    if result in ("male","mostly_male"):    return "male"
    return "unknown"

def to_lisbon_date(dt_str):
    if not dt_str or len(dt_str) < 19: return dt_str[:10] if dt_str else ""
    dt = datetime.strptime(dt_str[:19], "%Y-%m-%d %H:%M:%S")
    offset = timedelta(hours=1) if 4 <= dt.month <= 10 else timedelta(hours=0)
    return (dt + offset).strftime("%Y-%m-%d")

def get_revenue_date(order):
    histories = order.get("status_histories", [])
    if histories:
        sorted_hist = sorted(histories, key=lambda h: h.get("created_at",""))
        if sorted_hist and sorted_hist[0].get("status") == "pending":
            for h in sorted_hist:
                if h.get("status") == "processing":
                    return to_lisbon_date(h.get("created_at",""))
    return to_lisbon_date(order.get("created_at",""))

# ── Auth ──────────────────────────────────────────────────────────────────────
def get_token():
    r = requests.post(f"{BASE_URL}/rest/V1/integration/admin/token",
                      json={"username": ADMIN_USER, "password": ADMIN_PASSWORD}, timeout=30)
    r.raise_for_status()
    return r.json()

def mget(endpoint, token, params=None):
    H = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    r = requests.get(f"{BASE_URL}/rest/V1{endpoint}", headers=H, params=params, timeout=60)
    r.raise_for_status()
    return r.json()

# ── Fetch orders ──────────────────────────────────────────────────────────────
def fetch_all_orders(token):
    if os.path.exists(CACHE_FILE):
        print(f"📦 A usar cache: {CACHE_FILE}")
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)

    print("📥 A buscar todas as encomendas do Magento...")
    all_orders, page, page_size = [], 1, 200
    while True:
        data = mget("/orders", token, params={
            "searchCriteria[pageSize]": page_size,
            "searchCriteria[currentPage]": page,
            "searchCriteria[sortOrders][0][field]": "created_at",
            "searchCriteria[sortOrders][0][direction]": "ASC",
            "fields": "items[entity_id,increment_id,created_at,status,grand_total,"
                      "customer_firstname,customer_lastname,customer_email,"
                      "customer_is_guest,status_histories,billing_address,"
                      "items[name,qty_ordered,price,product_type,sku]],"
                      "total_count",
        })
        items = data.get("items", [])
        all_orders.extend(items)
        total = data.get("total_count", 0)
        print(f"  Página {page}: {len(all_orders)}/{total} encomendas", end="\r")
        if len(items) < page_size or len(all_orders) >= total: break
        page += 1
        time.sleep(0.2)
    print(f"\n✅ Total: {len(all_orders)} encomendas")
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(all_orders, f, ensure_ascii=False)
    return all_orders

# ── Fetch search terms ────────────────────────────────────────────────────────
def fetch_search_terms():
    if os.path.exists(SEARCH_CACHE_FILE):
        print(f"🔍 Search terms: a usar cache")
        with open(SEARCH_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)

    print("🔍 A recolher termos de pesquisa do site...")
    import unicodedata

    def normalize(s):
        return ''.join(c for c in unicodedata.normalize('NFD', s.lower())
                       if unicodedata.category(c) != 'Mn')

    base_words = [
        "camisa","camisola","camiseta","calça","calcão","fato","gravata","casaco",
        "blazer","cinto","sapato","sapatilha","bota","meia","cueca","boxer",
        "polo","parka","jaqueta","sobretudo","cardigan","pullover","sweat",
        "sweater","hoodie","bermuda","short","swim","banho","praia","linho",
        "ganga","jeans","denim","flanela","seda","algodão","lã","couro","pele",
        "colar","pulseira","anel","relógio","carteira","mala","mochila","chapéu",
        "boné","capa","lenço","luva","acessório","sale","desconto","black","friday",
        "promoção","oferta","natal","vestido","saia","blusa","top","conjunto",
        "roupa","underwear","suit","tshirt","shirt","jacket","trouser","chino",
        "formal","casual","slim","fit","regular","oversize","vintage","classic",
        "branco","preto","azul","verde","vermelho","cinza","bege","castanho",
        "men","women","homem","mulher","masculino","feminino","unissex",
    ]

    prefixes_set = set()
    for word in base_words:
        w = normalize(word)
        if len(w) >= 3: prefixes_set.add(w[:3])
        if len(w) >= 4: prefixes_set.add(w[:4])
    vowels, consonants = "aeiou", "bcdfghjklmnpqrstvxz"
    for c in consonants:
        for v in vowels:
            prefixes_set.update([c+v+"a", c+v+"o", c+v+"e", c+"a"+v])
    for a in "abcdefghijklmnoprstuvz":
        for b in "abcdefghijklmnoprstuvz":
            prefixes_set.add(a+b+"a")

    prefixes, seen = sorted(prefixes_set), {}
    total = len(prefixes)
    for i, prefix in enumerate(prefixes):
        try:
            r = requests.get(f"{BASE_URL}/search/ajax/suggest/", params={"q": prefix},
                             headers={"User-Agent":"Mozilla/5.0","X-Requested-With":"XMLHttpRequest"},
                             timeout=8)
            if r.status_code == 200:
                for item in r.json():
                    if item.get("type") == "term":
                        title = item.get("title","").strip()
                        key = normalize(title)
                        if title and key not in seen:
                            seen[key] = {"term": title, "num_results": int(item.get("num_results",0))}
        except Exception: pass
        if (i+1) % 50 == 0:
            print(f"  {i+1}/{total} prefixos · {len(seen)} termos", end="\r")
        time.sleep(0.04)

    terms = sorted(seen.values(), key=lambda x: x["num_results"], reverse=True)
    print(f"\n✅ {len(terms)} termos recolhidos")
    with open(SEARCH_CACHE_FILE,"w",encoding="utf-8") as f:
        json.dump(terms, f, ensure_ascii=False)
    return terms

# ── Aggregate (monthly breakdowns for dynamic filtering) ──────────────────────
def aggregate(orders):
    valid_statuses = {"processing","complete","closed"}

    # monthly_stats[month][gender] = {orders, revenue}
    monthly_stats = defaultdict(lambda: {
        "male":    {"orders":0,"revenue":0.0},
        "female":  {"orders":0,"revenue":0.0},
        "unknown": {"orders":0,"revenue":0.0},
    })
    # monthly_products[month][gender][product_name] = {qty, revenue}
    monthly_products = defaultdict(lambda: {
        "male":   defaultdict(lambda: {"qty":0,"revenue":0.0}),
        "female": defaultdict(lambda: {"qty":0,"revenue":0.0}),
    })
    # monthly_cities[month][city] = {orders, revenue, male, female}
    monthly_cities = defaultdict(lambda: defaultdict(lambda: {"orders":0,"revenue":0.0,"male":0,"female":0}))

    # All-time unique customers per gender
    customers = {"male": set(), "female": set(), "unknown": set()}

    for order in orders:
        if order.get("status","") not in valid_statuses: continue
        total = float(order.get("grand_total",0) or 0)
        if total <= 0: continue

        date_str = get_revenue_date(order)
        try: date = datetime.strptime(date_str, "%Y-%m-%d")
        except Exception: continue
        if date < DATE_FROM: continue

        month_key = date.strftime("%Y-%m")
        firstname = order.get("customer_firstname","") or ""
        email     = order.get("customer_email","") or ""
        g = get_gender(firstname)

        monthly_stats[month_key][g]["orders"]  += 1
        monthly_stats[month_key][g]["revenue"] += total
        customers[g].add(email or firstname)

        # City
        ba   = order.get("billing_address") or {}
        city = (ba.get("city") or "").strip().title()
        if city:
            monthly_cities[month_key][city]["orders"]  += 1
            monthly_cities[month_key][city]["revenue"] += total
            if g == "male":   monthly_cities[month_key][city]["male"]   += 1
            elif g == "female": monthly_cities[month_key][city]["female"] += 1

        # Products
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

    # Serialise monthly_products → top 30 per month/gender
    mp_serial = {}
    for month, genders in monthly_products.items():
        mp_serial[month] = {}
        for g, prods in genders.items():
            mp_serial[month][g] = sorted(
                [{"name":k,"qty":v["qty"],"revenue":v["revenue"]} for k,v in prods.items()],
                key=lambda x: x["revenue"], reverse=True
            )[:30]

    # Serialise monthly_cities → top 30 per month
    mc_serial = {}
    for month, cities in monthly_cities.items():
        mc_serial[month] = sorted(
            [{"city":k,"orders":v["orders"],"revenue":v["revenue"],"male":v["male"],"female":v["female"]}
             for k,v in cities.items()],
            key=lambda x: x["orders"], reverse=True
        )[:30]

    return {
        "generated_at":    datetime.now().isoformat(),
        "all_months":      all_months,
        "date_from":       DATE_FROM.strftime("%Y-%m-%d"),
        "date_to":         datetime.now().strftime("%Y-%m-%d"),
        "monthly_stats":   {m: dict(v) for m,v in monthly_stats.items()},
        "monthly_products":mp_serial,
        "monthly_cities":  mc_serial,
        "total_customers": {g: len(s) for g,s in customers.items()},
    }

# ── HTML ──────────────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dados Demográficos — Cavemen Store</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',Arial,sans-serif;background:#0f0f0f;color:#e0e0e0;min-height:100vh}
header{background:linear-gradient(135deg,#1a1a1a,#2d2d2d);padding:22px 36px;border-bottom:3px solid #c8a96e;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}
header h1{font-size:1.5rem;color:#c8a96e;letter-spacing:1.5px}
header p{color:#666;font-size:.8rem;margin-top:3px}

/* ── Filters ── */
.filters{background:#111;border-bottom:1px solid #1e1e1e;padding:16px 36px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.period-block{display:flex;align-items:center;gap:10px;background:#181818;border:1px solid #2a2a2a;border-radius:10px;padding:10px 16px}
.period-label{font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;padding:3px 10px;border-radius:20px;white-space:nowrap}
.period-label.a{background:rgba(200,169,110,.2);color:#c8a96e}
.period-label.b{background:rgba(126,203,138,.2);color:#7ecb8a}
.period-dates{display:flex;align-items:center;gap:8px}
.date-group{display:flex;flex-direction:column;gap:3px}
.date-group label{font-size:.62rem;color:#555;text-transform:uppercase;letter-spacing:1px}
.date-group input[type=date]{background:#1e1e1e;border:1px solid #2d2d2d;color:#ccc;padding:6px 10px;border-radius:7px;font-size:.82rem;outline:none;cursor:pointer;min-width:130px}
.date-group input[type=date]:focus{border-color:#c8a96e}
.vs-sep{color:#333;font-size:.75rem;font-weight:700;padding:0 4px}
.compare-toggle{display:flex;align-items:center;gap:8px;cursor:pointer;user-select:none}
.compare-toggle input[type=checkbox]{accent-color:#7ecb8a;width:16px;height:16px;cursor:pointer}
.compare-toggle span{font-size:.8rem;color:#888}
.period-b-wrap{display:flex;align-items:center;gap:10px;transition:.2s}
.period-b-wrap.hidden{opacity:0;pointer-events:none;max-width:0;overflow:hidden;padding:0;margin:0}
#btnApply{background:#c8a96e;color:#0f0f0f;border:none;padding:8px 20px;border-radius:8px;font-weight:700;font-size:.8rem;cursor:pointer;letter-spacing:.5px;white-space:nowrap}
#btnApply:hover{background:#d4b87a}

/* ── Layout ── */
.section{padding:24px 36px}
.section-title{font-size:.72rem;text-transform:uppercase;letter-spacing:2px;color:#c8a96e;font-weight:700;margin-bottom:16px;padding-bottom:7px;border-bottom:1px solid #222}
.kpis{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:24px}
.kpi{background:#1a1a1a;border:1px solid #2d2d2d;border-radius:10px;padding:16px 20px;flex:1;min-width:130px}
.kpi.male{border-top:3px solid #5b9bd5}
.kpi.female{border-top:3px solid #e87d7d}
.kpi.neutral{border-top:3px solid #c8a96e}
.kpi .klabel{color:#666;font-size:.67rem;text-transform:uppercase;letter-spacing:1px}
.kpi .kval{font-size:1.5rem;font-weight:700;margin-top:4px}
.kpi.male .kval{color:#5b9bd5}
.kpi.female .kval{color:#e87d7d}
.kpi.neutral .kval{color:#c8a96e}
.kpi .ksub{font-size:.72rem;color:#444;margin-top:3px}
.kpi .kdelta{font-size:.72rem;margin-top:2px;font-weight:600}
.kdelta.up{color:#7ecb8a}.kdelta.down{color:#e87d7d}.kdelta.flat{color:#555}
.charts{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:24px}
.cbox{background:#1a1a1a;border:1px solid #2d2d2d;border-radius:10px;padding:18px}
.cbox.full{grid-column:1/-1}
.cbox h2{color:#c8a96e;font-size:.68rem;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:12px;padding-bottom:7px;border-bottom:1px solid #222}
canvas{max-height:280px}
.tables{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:24px}
.tbox{background:#1a1a1a;border:1px solid #2d2d2d;border-radius:10px;padding:18px}
.tbox.full{grid-column:1/-1}
.tbox h2{font-size:.68rem;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:12px;padding-bottom:7px;border-bottom:1px solid #222}
.tbox.male h2{color:#5b9bd5}.tbox.female h2{color:#e87d7d}.tbox.neutral h2{color:#c8a96e}
table{width:100%;border-collapse:collapse;font-size:.8rem}
th{color:#555;font-weight:600;text-align:left;padding:5px 7px;border-bottom:1px solid #1e1e1e;font-size:.67rem;text-transform:uppercase;letter-spacing:.5px}
td{padding:6px 7px;border-bottom:1px solid #181818;color:#bbb}
tr:last-child td{border-bottom:none}
tr:hover td{background:#1f1f1f}
.bar-bg{flex:1;background:#1e1e1e;border-radius:3px;height:5px;overflow:hidden;margin-top:3px}
.bar-fill{height:100%;border-radius:3px}
.bar-fill.male{background:#5b9bd5}.bar-fill.female{background:#e87d7d}.bar-fill.gold{background:#c8a96e}
.split-row{display:flex;height:7px;border-radius:4px;overflow:hidden;margin:3px 0}
.pct{font-size:.68rem;font-weight:700;color:#555}
footer{text-align:center;color:#2a2a2a;font-size:.72rem;padding:20px;border-top:1px solid #161616}
@media(max-width:800px){.charts,.tables{grid-template-columns:1fr}.cbox.full,.tbox.full{grid-column:auto}}
</style>
</head>
<body>

<header>
  <div>
    <h1>Dados Demográficos</h1>
    <p id="headerSub">Cavemen Store · Online (Magento) · Atualizado: __GENERATED_AT__</p>
  </div>
</header>

<!-- Filtros -->
<div class="filters">
  <div class="period-block">
    <span class="period-label a">Período A</span>
    <div class="period-dates">
      <div class="date-group"><label>De</label><input type="date" id="aFrom"></div>
      <div class="date-group"><label>Até</label><input type="date" id="aTo"></div>
    </div>
  </div>

  <label class="compare-toggle">
    <input type="checkbox" id="chkB">
    <span>Comparar com Período B</span>
  </label>

  <div class="vs-sep" id="vsSep" style="display:none">VS</div>

  <div class="period-b-wrap hidden" id="periodBWrap">
    <div class="period-block">
      <span class="period-label b">Período B</span>
      <div class="period-dates">
        <div class="date-group"><label>De</label><input type="date" id="bFrom"></div>
        <div class="date-group"><label>Até</label><input type="date" id="bTo"></div>
      </div>
    </div>
  </div>

  <button id="btnApply">Aplicar</button>
</div>

<!-- KPIs -->
<div class="section">
  <div class="section-title" id="kpiTitle">Resumo do Período</div>
  <div class="kpis" id="kpis"></div>
</div>

<!-- Charts -->
<div class="section">
  <div class="section-title">Evolução Mensal de Receita por Género</div>
  <div class="charts">
    <div class="cbox full"><h2 id="chartMonthlyTitle">Receita Mensal</h2><canvas id="chartMonthly"></canvas></div>
    <div class="cbox"><h2>Distribuição de Encomendas</h2><canvas id="chartPie"></canvas></div>
    <div class="cbox"><h2>Ticket Médio por Género</h2><canvas id="chartTicket"></canvas></div>
  </div>
</div>

<!-- Products -->
<div class="section">
  <div class="section-title">Top Produtos por Género</div>
  <div class="tables">
    <div class="tbox male">
      <h2>Top 20 Produtos — Masculino</h2>
      <table><thead><tr><th>#</th><th>Produto</th><th>Receita</th><th>Qtd</th></tr></thead>
      <tbody id="tbMale"></tbody></table>
    </div>
    <div class="tbox female">
      <h2>Top 20 Produtos — Feminino</h2>
      <table><thead><tr><th>#</th><th>Produto</th><th>Receita</th><th>Qtd</th></tr></thead>
      <tbody id="tbFemale"></tbody></table>
    </div>
    <div class="tbox full neutral">
      <h2>Preferência por Género (Split)</h2>
      <table><thead><tr><th>Produto</th><th>Split ♂/♀</th><th>♂ €</th><th>♀ €</th><th>Total €</th></tr></thead>
      <tbody id="tbSplit"></tbody></table>
    </div>
  </div>
</div>

<!-- Cities -->
<div class="section">
  <div class="section-title">Vendas por Cidade</div>
  <div class="charts">
    <div class="cbox full"><h2>Top 20 Cidades — Encomendas por Género</h2><canvas id="chartCities"></canvas></div>
  </div>
  <div class="tables">
    <div class="tbox full neutral">
      <h2>Top 30 Cidades — Detalhe</h2>
      <table><thead><tr><th>#</th><th>Cidade</th><th>Encomendas</th><th>Receita</th><th>♂</th><th>♀</th><th>Split</th></tr></thead>
      <tbody id="tbCities"></tbody></table>
    </div>
  </div>
</div>

<!-- Search terms -->
<div class="section">
  <div class="section-title">Termos de Pesquisa no Site</div>
  <div class="charts">
    <div class="cbox full"><h2>Top 25 Termos Pesquisados</h2><canvas id="chartSearch"></canvas></div>
  </div>
  <div class="tables">
    <div class="tbox full neutral">
      <h2>Todos os Termos (__TERMS_COUNT__ termos recolhidos)</h2>
      <table><thead><tr><th>#</th><th>Termo</th><th>Resultados</th><th>Popularidade</th></tr></thead>
      <tbody id="tbSearch"></tbody></table>
    </div>
  </div>
</div>

<footer>Gerado em __GENERATED_AT__ · Cavemen Store Analytics</footer>

<script>
const DATA = __DATA_JSON__;

// ── Helpers ──────────────────────────────────────────────────────────────────
const eur = v => (v||0).toLocaleString('pt-PT',{style:'currency',currency:'EUR',maximumFractionDigits:0});
const pct = (a,b) => b ? Math.round(a/b*100)+'%' : '—';
const fmt = v => (v||0).toLocaleString('pt-PT');
const moLabel = m => {const[y,mo]=m.split('-');return['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'][+mo-1]+' '+y.slice(2)};

function monthsInRange(from, to) {
  const res=[], f=from.slice(0,7), t=to.slice(0,7);
  return DATA.all_months.filter(m => m >= f && m <= t);
}

function aggregateStats(months) {
  const r = {male:{orders:0,revenue:0},female:{orders:0,revenue:0},unknown:{orders:0,revenue:0}};
  for(const m of months) {
    const s = DATA.monthly_stats[m] || {};
    for(const g of ['male','female','unknown']) {
      r[g].orders  += (s[g]||{}).orders  || 0;
      r[g].revenue += (s[g]||{}).revenue || 0;
    }
  }
  return r;
}

function aggregateProducts(months) {
  const agg = {male:{}, female:{}};
  for(const m of months) {
    const mp = DATA.monthly_products[m] || {};
    for(const g of ['male','female']) {
      for(const p of (mp[g]||[])) {
        if(!agg[g][p.name]) agg[g][p.name]={qty:0,revenue:0};
        agg[g][p.name].qty     += p.qty;
        agg[g][p.name].revenue += p.revenue;
      }
    }
  }
  for(const g of ['male','female'])
    agg[g] = Object.entries(agg[g]).map(([name,v])=>({name,...v}))
              .sort((a,b)=>b.revenue-a.revenue).slice(0,20);
  return agg;
}

function aggregateCities(months) {
  const agg = {};
  for(const m of months) {
    for(const c of (DATA.monthly_cities[m]||[])) {
      if(!agg[c.city]) agg[c.city]={orders:0,revenue:0,male:0,female:0};
      agg[c.city].orders  += c.orders;
      agg[c.city].revenue += c.revenue;
      agg[c.city].male    += c.male;
      agg[c.city].female  += c.female;
    }
  }
  return Object.entries(agg).map(([city,v])=>({city,...v}))
    .sort((a,b)=>b.orders-a.orders).slice(0,30);
}

// ── Chart instances ───────────────────────────────────────────────────────────
let charts = {};
function destroyChart(id) { if(charts[id]){charts[id].destroy();delete charts[id];} }

// ── Render ────────────────────────────────────────────────────────────────────
function render() {
  const aFrom = document.getElementById('aFrom').value;
  const aTo   = document.getElementById('aTo').value;
  const useB  = document.getElementById('chkB').checked;
  const bFrom = document.getElementById('bFrom').value;
  const bTo   = document.getElementById('bTo').value;

  const mA = monthsInRange(aFrom, aTo);
  const mB = useB ? monthsInRange(bFrom, bTo) : [];

  const sA = aggregateStats(mA);
  const sB = useB ? aggregateStats(mB) : null;

  renderKPIs(sA, sB, aFrom, aTo, bFrom, bTo, useB);
  renderMonthlyChart(mA, mB, useB);
  renderPieChart(sA, sB, useB);
  renderTicketChart(sA, sB, useB);

  const prA = aggregateProducts(mA);
  const prB = useB ? aggregateProducts(mB) : null;
  renderProductTable('tbMale',   prA.male,   prB?.male,   'male',   useB);
  renderProductTable('tbFemale', prA.female, prB?.female, 'female', useB);
  renderSplitTable(prA, useB ? prB : null);

  const citA = aggregateCities(mA);
  const citB = useB ? aggregateCities(mB) : null;
  renderCityChart(citA, citB, useB);
  renderCityTable(citA, citB, useB);

  renderSearchTerms();
}

// ── KPIs ──────────────────────────────────────────────────────────────────────
function delta(vA, vB) {
  if(!vB) return '';
  const d = vB ? ((vA-vB)/Math.abs(vB)*100) : 0;
  const cls = d>0?'up':d<0?'down':'flat';
  const sign = d>0?'▲':'▼';
  return `<div class="kdelta ${cls}">${sign} ${Math.abs(d).toFixed(1)}% vs Período B</div>`;
}

function renderKPIs(sA, sB, aFrom, aTo, bFrom, bTo, useB) {
  const el = document.getElementById('kpis');
  const totA = sA.male.orders + sA.female.orders;
  const revA = sA.male.revenue + sA.female.revenue;
  const totB = sB ? sB.male.orders + sB.female.orders : 0;
  const revB = sB ? sB.male.revenue + sB.female.revenue : 0;

  const kpis = [
    {label:'Encomendas ♂',  val:fmt(sA.male.orders),    sub:pct(sA.male.orders,totA),           deltaV:sB?sA.male.orders/sB.male.orders:null, cls:'male'},
    {label:'Receita ♂',     val:eur(sA.male.revenue),   sub:pct(sA.male.revenue,revA)+' da receita', deltaV:sB?sA.male.revenue/sB.male.revenue:null, cls:'male'},
    {label:'Ticket Médio ♂',val:eur(sA.male.revenue/(sA.male.orders||1)), sub:'por encomenda',  deltaV:null, cls:'male'},
    {label:'Encomendas ♀',  val:fmt(sA.female.orders),  sub:pct(sA.female.orders,totA),         deltaV:sB?sA.female.orders/sB.female.orders:null, cls:'female'},
    {label:'Receita ♀',     val:eur(sA.female.revenue), sub:pct(sA.female.revenue,revA)+' da receita', deltaV:sB?sA.female.revenue/sB.female.revenue:null, cls:'female'},
    {label:'Ticket Médio ♀',val:eur(sA.female.revenue/(sA.female.orders||1)), sub:'por encomenda', deltaV:null, cls:'female'},
  ];
  el.innerHTML = kpis.map(k=>{
    let dHtml = '';
    if(useB && sB && k.deltaV!==null) {
      const ref = k.cls==='male'?(k.label.includes('Ticket')?sB.male.revenue/(sB.male.orders||1):k.label.includes('Enc')?sB.male.orders:sB.male.revenue)
                                 :(k.label.includes('Ticket')?sB.female.revenue/(sB.female.orders||1):k.label.includes('Enc')?sB.female.orders:sB.female.revenue);
      const cur = parseFloat(k.val.replace(/[^\d,]/g,'').replace(',','.')) || 0;
    }
    const dStr = useB && sB ? delta(
      k.cls==='male'?(k.label.includes('Ticket')?sA.male.revenue/(sA.male.orders||1):k.label.includes('Enc')?sA.male.orders:sA.male.revenue)
                   :(k.label.includes('Ticket')?sA.female.revenue/(sA.female.orders||1):k.label.includes('Enc')?sA.female.orders:sA.female.revenue),
      k.cls==='male'?(k.label.includes('Ticket')?sB.male.revenue/(sB.male.orders||1):k.label.includes('Enc')?sB.male.orders:sB.male.revenue)
                   :(k.label.includes('Ticket')?sB.female.revenue/(sB.female.orders||1):k.label.includes('Enc')?sB.female.orders:sB.female.revenue)
    ) : '';
    return `<div class="kpi ${k.cls}"><div class="klabel">${k.label}</div><div class="kval">${k.val}</div><div class="ksub">${k.sub}</div>${dStr}</div>`;
  }).join('');
}

// ── Monthly chart ─────────────────────────────────────────────────────────────
function renderMonthlyChart(mA, mB, useB) {
  destroyChart('monthly');
  const labels = [...new Set([...mA,...mB])].sort().map(moLabel);
  const allMonths = [...new Set([...mA,...mB])].sort();
  const datasets = [
    {label:'♂ Período A', data:allMonths.map(m=>mA.includes(m)?(DATA.monthly_stats[m]?.male?.revenue||0):null), backgroundColor:'rgba(91,155,213,0.8)', borderRadius:4},
    {label:'♀ Período A', data:allMonths.map(m=>mA.includes(m)?(DATA.monthly_stats[m]?.female?.revenue||0):null), backgroundColor:'rgba(232,125,125,0.8)', borderRadius:4},
  ];
  if(useB && mB.length) {
    datasets.push({label:'♂ Período B', data:allMonths.map(m=>mB.includes(m)?(DATA.monthly_stats[m]?.male?.revenue||0):null), backgroundColor:'rgba(91,155,213,0.35)', borderRadius:4, borderColor:'rgba(91,155,213,0.8)', borderWidth:1});
    datasets.push({label:'♀ Período B', data:allMonths.map(m=>mB.includes(m)?(DATA.monthly_stats[m]?.female?.revenue||0):null), backgroundColor:'rgba(232,125,125,0.35)', borderRadius:4, borderColor:'rgba(232,125,125,0.8)', borderWidth:1});
  }
  charts['monthly'] = new Chart(document.getElementById('chartMonthly'),{
    type:'bar', data:{labels,datasets},
    options:{responsive:true,plugins:{legend:{labels:{color:'#aaa'}}},
      scales:{x:{ticks:{color:'#777'},grid:{color:'#1c1c1c'}},y:{ticks:{color:'#777',callback:v=>eur(v)},grid:{color:'#1c1c1c'}}}}
  });
}

// ── Pie chart ─────────────────────────────────────────────────────────────────
function renderPieChart(sA, sB, useB) {
  destroyChart('pie');
  charts['pie'] = new Chart(document.getElementById('chartPie'),{
    type:'doughnut',
    data:{
      labels:['♂ Masculino','♀ Feminino','Indeterminado'],
      datasets:[{
        data:[sA.male.orders,sA.female.orders,sA.unknown.orders],
        backgroundColor:['rgba(91,155,213,.85)','rgba(232,125,125,.85)','rgba(60,60,60,.6)'],
        borderColor:'#0f0f0f',borderWidth:3
      }]
    },
    options:{responsive:true,plugins:{legend:{labels:{color:'#aaa'}},
      tooltip:{callbacks:{label:ctx=>` ${ctx.label}: ${fmt(ctx.parsed)} enc.`}}}}
  });
}

// ── Ticket chart ──────────────────────────────────────────────────────────────
function renderTicketChart(sA, sB, useB) {
  destroyChart('ticket');
  const datasets = [{
    label:'Período A',
    data:[sA.male.revenue/(sA.male.orders||1), sA.female.revenue/(sA.female.orders||1)],
    backgroundColor:['rgba(91,155,213,.8)','rgba(232,125,125,.8)'],
    borderRadius:6
  }];
  if(useB && sB) datasets.push({
    label:'Período B',
    data:[sB.male.revenue/(sB.male.orders||1), sB.female.revenue/(sB.female.orders||1)],
    backgroundColor:['rgba(91,155,213,.35)','rgba(232,125,125,.35)'],
    borderColor:['rgba(91,155,213,.8)','rgba(232,125,125,.8)'], borderWidth:1, borderRadius:6
  });
  charts['ticket'] = new Chart(document.getElementById('chartTicket'),{
    type:'bar',data:{labels:['Masculino','Feminino'],datasets},
    options:{responsive:true,plugins:{legend:{labels:{color:'#aaa'}}},
      scales:{x:{ticks:{color:'#aaa'},grid:{color:'#1c1c1c'}},y:{ticks:{color:'#777',callback:v=>eur(v)},grid:{color:'#1c1c1c'}}}}
  });
}

// ── Product tables ────────────────────────────────────────────────────────────
function renderProductTable(tbId, prods, prodsB, gClass, useB) {
  const tb = document.getElementById(tbId);
  if(!prods||!prods.length){tb.innerHTML='<tr><td colspan="4" style="color:#444;text-align:center;padding:20px">Sem dados</td></tr>';return;}
  const maxRev = prods[0].revenue;
  tb.innerHTML = prods.map((p,i)=>{
    const w = (p.revenue/maxRev*100).toFixed(0);
    const pB = prodsB?.find(x=>x.name===p.name);
    const dRow = useB && pB ? `<div class="kdelta ${p.revenue>pB.revenue?'up':'down'}" style="font-size:.65rem">${p.revenue>pB.revenue?'▲':'▼'} ${Math.abs((p.revenue-pB.revenue)/pB.revenue*100).toFixed(0)}%</div>` : '';
    return `<tr><td style="color:#444">${i+1}</td><td>${p.name}${dRow}</td>
      <td>${eur(p.revenue)}<div class="bar-bg"><div class="bar-fill ${gClass}" style="width:${w}%"></div></div></td>
      <td>${Math.round(p.qty)}</td></tr>`;
  }).join('');
}

// ── Split table ───────────────────────────────────────────────────────────────
function renderSplitTable(prods, prodsB) {
  const tb = document.getElementById('tbSplit');
  const allNames = new Set([...prods.male.map(p=>p.name),...prods.female.map(p=>p.name)]);
  const rows = [];
  for(const name of allNames) {
    const m = prods.male.find(p=>p.name===name)||{revenue:0};
    const f = prods.female.find(p=>p.name===name)||{revenue:0};
    const tot = m.revenue+f.revenue;
    if(tot < 30) continue;
    rows.push({name, mRev:m.revenue, fRev:f.revenue, tot});
  }
  rows.sort((a,b)=>b.tot-a.tot);
  tb.innerHTML = rows.slice(0,30).map(r=>{
    const mPct = Math.round(r.mRev/r.tot*100);
    const fPct = 100-mPct;
    return `<tr><td>${r.name}</td>
      <td><div class="split-row"><div style="width:${mPct}%;background:#5b9bd5"></div><div style="width:${fPct}%;background:#e87d7d"></div></div>
          <span class="pct">♂${mPct}% ♀${fPct}%</span></td>
      <td style="color:#5b9bd5">${eur(r.mRev)}</td>
      <td style="color:#e87d7d">${eur(r.fRev)}</td>
      <td>${eur(r.tot)}</td></tr>`;
  }).join('');
}

// ── City chart ────────────────────────────────────────────────────────────────
function renderCityChart(citA, citB, useB) {
  destroyChart('cities');
  const top = citA.slice(0,20);
  const labels = top.map(c=>c.city);
  const datasets = [
    {label:'♂ Per. A', data:top.map(c=>c.male),   backgroundColor:'rgba(91,155,213,.85)', borderRadius:3},
    {label:'♀ Per. A', data:top.map(c=>c.female), backgroundColor:'rgba(232,125,125,.85)', borderRadius:3},
  ];
  if(useB && citB) {
    const getB = city => citB.find(c=>c.city===city)||{male:0,female:0};
    datasets.push({label:'♂ Per. B', data:top.map(c=>getB(c.city).male),   backgroundColor:'rgba(91,155,213,.3)', borderRadius:3});
    datasets.push({label:'♀ Per. B', data:top.map(c=>getB(c.city).female), backgroundColor:'rgba(232,125,125,.3)', borderRadius:3});
  }
  charts['cities'] = new Chart(document.getElementById('chartCities'),{
    type:'bar', data:{labels, datasets},
    options:{indexAxis:'y', responsive:true, plugins:{legend:{labels:{color:'#aaa'}}},
      scales:{x:{stacked:true,ticks:{color:'#777'},grid:{color:'#1c1c1c'}},
              y:{stacked:true,ticks:{color:'#ccc',font:{size:11}},grid:{color:'#1c1c1c'}}}}
  });
}

// ── City table ────────────────────────────────────────────────────────────────
function renderCityTable(citA, citB, useB) {
  const tb = document.getElementById('tbCities');
  const sorted = citA.slice().sort((a,b)=>b.revenue-a.revenue);
  const maxRev = sorted[0]?.revenue || 1;
  tb.innerHTML = sorted.map((c,i)=>{
    const tot = c.male+c.female;
    const mPct = tot ? Math.round(c.male/tot*100) : 0;
    const fPct = 100-mPct;
    const w = (c.revenue/maxRev*100).toFixed(0);
    const cB = citB?.find(x=>x.city===c.city);
    const dRow = useB && cB ? `<span class="kdelta ${c.revenue>cB.revenue?'up':'down'}" style="font-size:.65rem;margin-left:6px">${c.revenue>cB.revenue?'▲':'▼'}${Math.abs((c.revenue-cB.revenue)/(cB.revenue||1)*100).toFixed(0)}%</span>` : '';
    return `<tr>
      <td style="color:#444">${i+1}</td>
      <td><strong>${c.city}</strong></td>
      <td>${fmt(c.orders)}</td>
      <td>${eur(c.revenue)}${dRow}<div class="bar-bg"><div class="bar-fill gold" style="width:${w}%"></div></div></td>
      <td style="color:#5b9bd5">${fmt(c.male)}</td>
      <td style="color:#e87d7d">${fmt(c.female)}</td>
      <td><div class="split-row"><div style="width:${mPct}%;background:#5b9bd5"></div><div style="width:${fPct}%;background:#e87d7d"></div></div>
          <span class="pct">♂${mPct}% ♀${fPct}%</span></td>
    </tr>`;
  }).join('');
}

// ── Search terms ──────────────────────────────────────────────────────────────
function renderSearchTerms() {
  if(charts['search']) return; // only build once
  const terms = DATA.search_terms;
  const top25 = terms.slice(0,25);
  charts['search'] = new Chart(document.getElementById('chartSearch'),{
    type:'bar',
    data:{
      labels: top25.map(t=>t.term),
      datasets:[{label:'Resultados',data:top25.map(t=>t.num_results),backgroundColor:'rgba(200,169,110,.8)',borderRadius:4}]
    },
    options:{indexAxis:'y',responsive:true,plugins:{legend:{display:false}},
      scales:{x:{ticks:{color:'#777'},grid:{color:'#1c1c1c'}},y:{ticks:{color:'#ccc',font:{size:11}},grid:{color:'#1c1c1c'}}}}
  });

  const max = terms[0]?.num_results || 1;
  document.getElementById('tbSearch').innerHTML = terms.map((t,i)=>{
    const w=(t.num_results/max*100).toFixed(0);
    return `<tr><td style="color:#444">${i+1}</td><td><strong>${t.term}</strong></td>
      <td>${fmt(t.num_results)}<div class="bar-bg"><div class="bar-fill gold" style="width:${w}%"></div></div></td>
      <td><div class="bar-bg" style="height:7px"><div style="width:${w}%;height:100%;background:linear-gradient(90deg,#c8a96e,#d4b87a);border-radius:3px"></div></div></td></tr>`;
  }).join('');
}

// ── Date picker defaults ──────────────────────────────────────────────────────
(function initDates(){
  const now = new Date();
  const y = now.getFullYear(), m = now.getMonth();
  const pad = n => String(n).padStart(2,'0');

  // Period A: current month
  document.getElementById('aFrom').value = `${y}-${pad(m+1)}-01`;
  document.getElementById('aTo').value   = `${y}-${pad(m+1)}-${pad(new Date(y,m+1,0).getDate())}`;

  // Period B: same month last year
  const ly = y-1;
  document.getElementById('bFrom').value = `${ly}-${pad(m+1)}-01`;
  document.getElementById('bTo').value   = `${ly}-${pad(m+1)}-${pad(new Date(ly,m+1,0).getDate())}`;
})();

// ── Toggle Period B ───────────────────────────────────────────────────────────
document.getElementById('chkB').addEventListener('change', function(){
  const wrap = document.getElementById('periodBWrap');
  const sep  = document.getElementById('vsSep');
  if(this.checked){wrap.classList.remove('hidden');sep.style.display='block';}
  else{wrap.classList.add('hidden');sep.style.display='none';}
});

document.getElementById('btnApply').addEventListener('click', render);

// Initial render
render();
</script>
</body>
</html>
"""

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("🔑 A autenticar no Magento...")
    token = get_token()
    print("✅ Token OK")

    orders       = fetch_all_orders(token)
    search_terms = fetch_search_terms()

    print("📊 A agregar dados por mês...")
    data = aggregate(orders)
    data["search_terms"] = search_terms

    total_m = sum(v["male"]["orders"]    for v in data["monthly_stats"].values())
    total_f = sum(v["female"]["orders"]  for v in data["monthly_stats"].values())
    total_u = sum(v["unknown"]["orders"] for v in data["monthly_stats"].values())
    print(f"\n📈 Resultados (desde 2024):")
    print(f"  Masculino:     {total_m:>5} enc")
    print(f"  Feminino:      {total_f:>5} enc")
    print(f"  Indeterminado: {total_u:>5} enc")
    print(f"  Meses:         {len(data['all_months'])}")
    print(f"  Termos pesq.:  {len(search_terms)}")

    gen_at   = datetime.now().strftime("%d/%m/%Y %H:%M")
    data_json = json.dumps(data, ensure_ascii=False, default=str)

    html = HTML.replace("__GENERATED_AT__", gen_at) \
               .replace("__DATA_JSON__", data_json) \
               .replace("__TERMS_COUNT__", str(len(search_terms)))

    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), OUTPUT_HTML)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n✅ Relatório gerado: {output_path}")
    return output_path

if __name__ == "__main__":
    main()
