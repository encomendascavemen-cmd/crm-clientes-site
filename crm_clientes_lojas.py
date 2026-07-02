#!/usr/bin/env python3
"""
CRM de Clientes — LOJAS FÍSICAS (Moloni)
========================================
Equivalente ao CRM do site (crm_clientes.py) mas com origem nos dados do Moloni,
apenas das 3 lojas físicas (Guimarães, Braga, Porto). Inclui ficha completa de
cada cliente com encomendas, produtos comprados, segmentação RFV e dados pessoais.

EXTRAÇÃO SEGURA: respeita SEMPRE o limite de 200 pedidos/min da API Moloni
(Política de Utilização Aceitável). Excedê-lo bloqueia o IP e deixa as lojas
sem Moloni — ver memory/feedback_moloni_rate_limit.md. NÃO aumentar MAX_REQUESTS_PER_MIN
nem o número de threads.

O detalhe de produtos por cliente obriga a 1 pedido getOne por documento físico.
A 200/min, a extração completa demora ~1-2h. O cache (crm_lojas_getone_cache.json)
torna a extração resumível: re-correr só busca documentos novos.

Uso:
  python3 crm_clientes_lojas.py            # usa cache de documentos+produtos se existir
  python3 crm_clientes_lojas.py --refresh  # vai buscar tudo de novo ao Moloni
"""

import requests, json, time, os, sys, threading
from datetime import datetime, date
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

# Reutiliza toda a lógica de segmentação e geração de HTML do CRM do site
from crm_clientes import (
    SEGMENTS_META, STATUS_COLORS, STATUS_LABELS,
    score_rfv, generate_html,
)

# ─── CONFIG MOLONI ───────────────────────────────────────────────────────────
CLIENT_ID     = "cavemenunipessoallda"
CLIENT_SECRET = "a7678d73814b0f8179407c63b6242ca83690b61d"
USERNAME      = "encomendas@cavemenstore.com"
PASSWORD      = "7+LVn*QU+4sdrXN"
COMPANY_ID    = 274475
BASE          = "https://api.moloni.pt/v1"

PHYSICAL_TERMINALS = {125906: "Guimarães", 125908: "Braga", 148908: "Porto"}
# terminal_id == 0  → Online (EXCLUÍDO — esse é o CRM do site)

DOC_TYPES = ["simplifiedInvoices", "invoiceReceipts", "invoices"]
YEARS     = [2023, 2024, 2025, 2026]

SCRIPT_DIR     = os.path.dirname(os.path.abspath(__file__))
DOCS_CACHE     = os.path.join(SCRIPT_DIR, "crm_lojas_docs_cache.json")     # docs físicos (getAll)
CUSTS_CACHE    = os.path.join(SCRIPT_DIR, "crm_lojas_custs_cache.json")     # clientes (getAll)
GETONE_CACHE   = os.path.join(SCRIPT_DIR, "crm_lojas_getone_cache.json")   # produtos por doc (getOne)
OUTPUT_DATA    = os.path.join(SCRIPT_DIR, "crm_lojas_data.json")
OUTPUT_HTML    = os.path.join(SCRIPT_DIR, "crm_clientes_lojas.html")

# ─── RATE LIMITER (Política Moloni: máx 200/min) ─────────────────────────────
# CRÍTICO: NÃO aumentar. Bloquear o IP deixa as 3 lojas sem Moloni.
MAX_REQUESTS_PER_MIN = 200
MAX_WORKERS          = 4   # threads partilham o RateLimiter global → nunca passa de 200/min

class RateLimiter:
    """Limitador global thread-safe: espaça pedidos para nunca exceder max/min."""
    def __init__(self, mx):
        self.interval = 60.0 / mx
        self.lock = threading.Lock()
        self.next_slot = 0.0
    def acquire(self):
        with self.lock:
            now = time.time()
            slot = max(now, self.next_slot)
            self.next_slot = slot + self.interval
        w = slot - time.time()
        if w > 0:
            time.sleep(w)
_rl = RateLimiter(MAX_REQUESTS_PER_MIN)

# ─── AUTH + API ──────────────────────────────────────────────────────────────
# Token global com refresh automático — a extração dura mais que 1h (validade do
# token), por isso é renovado proativamente (>50 min) e sempre que a API devolve 401.
_token = None
_token_ts = 0.0
_token_lock = threading.Lock()

def get_token():
    print("🔐 Autenticando na API Moloni...", flush=True)
    r = requests.get(f"{BASE}/grant/", params={
        "grant_type": "password", "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET, "username": USERNAME, "password": PASSWORD})
    r.raise_for_status()
    data = r.json()
    if "access_token" not in data:
        raise RuntimeError(f"Auth falhou: {data}")
    print(f"✅ Token obtido (expira em {data['expires_in']}s)", flush=True)
    return data["access_token"]

def refresh_token(force=False):
    """Devolve o token atual; renova-o se forçado ou se tiver mais de 50 min."""
    global _token, _token_ts
    with _token_lock:
        if force or _token is None or (time.time() - _token_ts) > 3000:
            _token = get_token()
            _token_ts = time.time()
    return _token

def api_post(endpoint, data=None):
    payload = {"company_id": COMPANY_ID}
    if data:
        payload.update(data)
    for attempt in range(5):
        try:
            tok = refresh_token()           # renova proativamente se já tiver >50 min
            _rl.acquire()                   # respeita o limite de 200 pedidos/min
            r = requests.post(f"{BASE}/{endpoint}/", params={"access_token": tok},
                              data=payload, timeout=30)
            if r.status_code == 429:
                time.sleep([5, 15, 45, 90, 90][attempt])  # recuo agressivo
                continue
            if r.status_code == 401:
                refresh_token(force=True)   # token expirou — renova e tenta de novo
                continue
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt == 4:
                return None
            time.sleep(2)
    return None

def fetch_all_pages(endpoint, extra=None, label=""):
    """Pagina um endpoint getAll (máx 50/página)."""
    out = []; offset = 0; page = 50
    while True:
        params = {"qty": page, "offset": offset}
        if extra:
            params.update(extra)
        batch = api_post(endpoint, params)
        if not batch or not isinstance(batch, list):
            break
        out.extend(batch)
        if len(batch) < page:
            break
        offset += page
        if label and offset % 500 == 0:
            print(f"  {label}: {offset} documentos…", flush=True)
    return out

# ─── FASE 1: documentos físicos (getAll) ─────────────────────────────────────
def fetch_physical_docs():
    """Devolve a lista de documentos das lojas físicas (status fechado, valor > 0)."""
    docs = []
    for dt in DOC_TYPES:
        for y in YEARS:
            batch = fetch_all_pages(f"{dt}/getAll", {"year": y}, f"{dt} {y}")
            kept = 0
            for d in batch:
                tid = d.get("terminal_id") or 0
                if tid not in PHYSICAL_TERMINALS:
                    continue
                if int(d.get("status", 1) or 0) != 1:   # só documentos fechados
                    continue
                if float(d.get("net_value") or 0) <= 0:
                    continue
                if not d.get("customer_id"):
                    continue
                docs.append({
                    "doc_type":     dt,
                    "document_id":  d.get("document_id"),
                    "customer_id":  d.get("customer_id"),
                    "terminal_id":  tid,
                    "store":        PHYSICAL_TERMINALS[tid],
                    "date":         d.get("date") or "",
                    "net_value":    float(d.get("net_value") or 0),
                    "number":       d.get("number") or "",
                })
                kept += 1
            print(f"  ✅ {dt} {y}: {len(batch)} docs · {kept} de loja física", flush=True)
    return docs

# ─── FASE 2: clientes (getAll) ───────────────────────────────────────────────
def fetch_customers():
    """Devolve a lista bruta de clientes (getAll)."""
    return fetch_all_pages("customers/getAll", {}, "customers")

# ─── FASE 3: produtos por documento (getOne) ─────────────────────────────────
def _getone_key(d):
    return f"{d['doc_type']}:{d['document_id']}"

def fetch_products(docs, cache):
    """Para cada documento físico, getOne → linhas de produto. Resumível via cache."""
    pending = [d for d in docs if _getone_key(d) not in cache]
    print(f"\n🛒 Produtos: {len(docs)} docs · {len(cache)} em cache · {len(pending)} por buscar", flush=True)
    if not pending:
        return
    eta_min = len(pending) / MAX_REQUESTS_PER_MIN
    print(f"   ⏱  A 200 pedidos/min isto demora ~{eta_min:.0f} min. (limite Moloni — não acelerável)", flush=True)

    lock = threading.Lock()
    done = 0
    last_save = time.time()

    def fetch_one(d):
        data = api_post(f"{d['doc_type']}/getOne", {"document_id": d["document_id"]})
        prods = []
        number = ""
        if isinstance(data, dict):
            number = data.get("number") or ""
            for p in (data.get("products") or []):
                qty   = float(p.get("qty") or 0)
                price = float(p.get("price") or 0)
                disc  = float(p.get("discount") or 0)
                prods.append({
                    "name":      p.get("name") or p.get("reference") or "?",
                    "reference": p.get("reference") or "",
                    "qty":       qty,
                    "price":     price,
                    "subtotal":  round(qty * price * (1 - disc / 100), 2),
                })
        return _getone_key(d), {"number": number, "products": prods}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(fetch_one, d): d for d in pending}
        for fut in as_completed(futures):
            key, val = fut.result()
            with lock:
                cache[key] = val
                done += 1
                if done % 100 == 0:
                    remain = len(pending) - done
                    print(f"    produtos: {done}/{len(pending)} · faltam ~{remain/MAX_REQUESTS_PER_MIN:.0f} min", flush=True)
                # Guarda o cache periodicamente — torna a extração resumível
                if time.time() - last_save > 60:
                    _save_json(GETONE_CACHE, cache)
                    last_save = time.time()
    _save_json(GETONE_CACHE, cache)

# ─── CONSTRUÇÃO DOS CLIENTES (mesma forma que build_crm do site) ─────────────
def clean(s):
    s = (s or "").strip()
    return "" if s.lower() in {"desconhecido", "unknown", "n/a", "na", "."} else s

def build_crm_lojas(docs, cust_by_id, getone):
    customers = {}

    for d in docs:
        cid = d["customer_id"]
        store = d["store"]
        total = d["net_value"]
        date_str = (d.get("date") or "")[:10]
        go = getone.get(_getone_key(d), {})
        number = go.get("number") or d.get("number") or str(d.get("document_id", ""))
        items = go.get("products", [])

        if cid not in customers:
            c = cust_by_id.get(cid, {}) or {}
            country = c.get("country")
            country = (country.get("iso_3166_1") if isinstance(country, dict) else country) or "PT"
            customers[cid] = {
                "name":     clean(c.get("name")),
                "email":    clean(c.get("email") or c.get("contact_email") or ""),
                "phone":    clean(c.get("phone") or c.get("contact_phone") or ""),
                "city":     clean(c.get("city")),
                "region":   "",
                "postcode": clean(c.get("zip_code")),
                "street":   clean(c.get("address")),
                "country":  (country or "PT").upper(),
                "vat":      clean(c.get("vat") or c.get("number") or ""),
                "stores":   set(),
                "total_orders": 0,
                "total_spent":  0.0,
                "first_order":  "",
                "last_order":   "",
                "all_orders":   [],
                "products":     defaultdict(lambda: {"name": "", "qty": 0.0, "revenue": 0.0}),
            }

        c = customers[cid]
        c["stores"].add(store)
        c["total_orders"] += 1
        c["total_spent"]  += total
        if date_str:
            if not c["first_order"] or date_str < c["first_order"]:
                c["first_order"] = date_str
            if not c["last_order"] or date_str > c["last_order"]:
                c["last_order"] = date_str

        order_items = []
        for it in items:
            order_items.append({
                "name":     it["name"],
                "sku":      it["reference"],
                "qty":      it["qty"],
                "price":    it["price"],
                "subtotal": it["subtotal"],
            })
            key = it["reference"] or it["name"]
            c["products"][key]["name"]    = it["name"]
            c["products"][key]["qty"]     += it["qty"]
            c["products"][key]["revenue"] += it["subtotal"]

        c["all_orders"].append({
            "id":       f"{number} · {store}",
            "date":     date_str,
            "datetime": (d.get("date") or "")[:16].replace("T", " "),
            "status":   "complete",   # documentos Moloni fechados → reutiliza estilo "Completa"
            "total":    round(total, 2),
            "store":    store,
            "items":    order_items,
        })

    # Monta a lista final na forma esperada por generate_html / score_rfv
    result = []
    for cid, c in customers.items():
        if c["total_orders"] == 0:
            continue
        c["all_orders"].sort(key=lambda x: x["date"], reverse=True)
        top_products = sorted(
            [{"sku": k, **v} for k, v in c["products"].items()],
            key=lambda x: x["revenue"], reverse=True)
        days_since = ""
        if c["last_order"]:
            try:
                days_since = (date.today() - date.fromisoformat(c["last_order"])).days
            except Exception:
                pass
        stores = sorted(c["stores"])
        contact = c["email"] or c["phone"] or ""
        # Balcão / Consumidor Final: NIF genérico 999999990 SEM qualquer contacto.
        # São o "cliente da caixa" reutilizado (milhares de vendas) — não é uma pessoa.
        anonymous = (c["vat"] == "999999990") and not c["email"] and not c["phone"]
        # Remover da lista tudo o que aparece como "Anónimo" (balcão/Consumidor Final)
        # ou "Cliente" (registo genérico da caixa, sem nome real). Fica só quem tem
        # um nome real OU um contacto (email/telefone).
        nome_l = (c["name"] or "").strip().lower()
        GENERICOS = {"cliente", "consumidor final", "consumidor", "cliente final",
                     "consumidor final .", "cliente ."}
        mostra_generico = (nome_l in GENERICOS) or (nome_l == "" and not contact)
        if anonymous or mostra_generico:
            continue
        display_name = c["name"] or contact or f"Cliente {cid}"
        result.append({
            "name":         display_name,
            "orig_name":    c["name"],
            "anonymous":    anonymous,
            "email":        contact,                 # coluna "email" passa a ser o contacto (email/telefone)
            "is_guest":     False,
            "phone":        c["phone"],
            "city":         c["city"],
            "region":       c["region"],
            "postcode":     c["postcode"],
            "street":       c["street"],
            "country":      c["country"],
            "vat":          c["vat"],
            "stores":       stores,
            "store_label":  " · ".join(stores),
            "total_orders": c["total_orders"],
            "total_spent":  round(c["total_spent"], 2),
            "avg_order":    round(c["total_spent"] / c["total_orders"], 2),
            "first_order":  c["first_order"],
            "last_order":   c["last_order"],
            "days_since":   days_since,
            "products":     top_products,
            "all_orders":   c["all_orders"],
        })

    result.sort(key=lambda x: x["total_spent"], reverse=True)
    return result

# ─── ADAPTAÇÃO DO HTML (reutiliza generate_html do site, ajusta p/ lojas) ────
def _v_breakpoints(customers):
    vals = sorted(c["total_spent"] for c in customers)
    if not vals:
        return [0, 0, 0, 0]
    n = len(vals)
    out = []
    for p in [20, 40, 60, 80]:
        idx = p / 100 * (n - 1)
        lo, hi = int(idx), min(int(idx) + 1, n - 1)
        out.append(vals[lo] + (vals[hi] - vals[lo]) * (idx - lo))
    return out

def adapt_html_for_lojas(html, customers):
    bp = _v_breakpoints(customers)
    def eur(v):
        return f"{v:.0f}€"

    repl = [
        # Título / branding
        ("<title>CRM · Cavemen Store</title>", "<title>CRM Lojas · Cavemen Store</title>"),
        ('<div class="logo">CAVEMEN <span>· CRM</span></div>',
         '<div class="logo">CAVEMEN <span>· CRM Lojas</span></div>'),
        ("<div class=\"stat-s\">loja online</div>", "<div class=\"stat-s\">lojas físicas</div>"),
        # Tab Pontos (Mageplaza, só Magento) → link para o CRM do site
        ('<button class="tab-btn" id="tab-btn-pontos" onclick="switchTab(\'pontos\',this)">🏆 Pontos</button>',
         '<a class="tab-btn" href="/crm" style="text-decoration:none;display:inline-flex;align-items:center">🌐 CRM Site</a>'),
        # Endpoints da API → versão lojas
        ("/api/crm/", "/api/crm-lojas/"),
        # Textos de refresh (Magento ~2 min → Moloni ~1-2h, limite 200/min)
        ('title="Vai buscar dados novos ao Magento (~2 min)"',
         'title="Vai buscar dados novos ao Moloni (~1-2h, limite 200 pedidos/min)"'),
        ("'A buscar dados novos do Magento… (pode demorar ~2 min)'",
         "'A buscar dados novos do Moloni… (pode demorar ~1-2h — limite de 200 pedidos/min)'"),
        # Filtros: Registados/Guests (Magento) → filtros por LOJA
        ('  <button class="fbtn" onclick="setFilter(\'member\',this)">Registados</button>\n'
         '  <button class="fbtn" onclick="setFilter(\'guest\',this)">Guests</button>',
         '  <button class="fbtn" onclick="setFilter(\'store:Guimarães\',this)">Guimarães</button>\n'
         '  <button class="fbtn" onclick="setFilter(\'store:Braga\',this)">Braga</button>\n'
         '  <button class="fbtn" onclick="setFilter(\'store:Porto\',this)">Porto</button>\n'
         '  <button class="fbtn" onclick="setFilter(\'contactable\',this)" title="Clientes com email ou telefone (úteis para campanhas)">📧 Contactáveis</button>'),
        # Lógica de filtro: adiciona ramos store:, anon e contactable
        ("if (activeFilter==='recent') matchF = daysVal<=30;",
         "if (activeFilter==='recent') matchF = daysVal<=30;\n"
         "    if (activeFilter==='anon') matchF = row.dataset.anon==='1';\n"
         "    if (activeFilter==='contactable') matchF = (row.dataset.email||'')!=='';\n"
         "    if (activeFilter && activeFilter.indexOf('store:')===0) matchF = (row.dataset.store||'').indexOf(activeFilter.slice(6))!==-1;"),
        # Linha da tabela: badge de loja + data-store + data-anon
        ('data-guest="${isGuest}" data-days=',
         'data-guest="${isGuest}" data-store="${c.store_label||\'\'}" data-anon="${c.anonymous?1:0}" data-days='),
        ("const badge = isGuest ? '<span class=\"badge guest\">Guest</span>' : '<span class=\"badge member\">Registado</span>';",
         "const badge = c.store_label ? '<span class=\"badge member\">🏪 '+c.store_label+'</span>' : '';"),
        # Badge na ficha (drawer)
        ("let badgeHtml = c.is_guest\n"
         "    ? '<span class=\"badge guest\">Guest</span>'\n"
         "    : '<span class=\"badge member\">Cliente Registado</span>';",
         "let badgeHtml = c.store_label ? '<span class=\"badge member\">🏪 '+c.store_label+'</span>' : '';"),
        # Tooltip remanescente da aba Pontos (inacessível) — remove menção a Magento
        ("Apenas vendas online (Magento). Compras em loja física não incluídas.",
         "Apenas vendas online."),
        # Guia do V: breakpoints reais das lojas (eram do site)
        ("<td class=\"guide-range\">≥ 224€</td>",      f"<td class=\"guide-range\">≥ {eur(bp[3])}</td>"),
        ("<td class=\"guide-range\">107–224€</td>",     f"<td class=\"guide-range\">{eur(bp[2])}–{eur(bp[3])}</td>"),
        ("<td class=\"guide-range\">70–107€</td>",      f"<td class=\"guide-range\">{eur(bp[1])}–{eur(bp[2])}</td>"),
        ("<td class=\"guide-range\">45–70€</td>",       f"<td class=\"guide-range\">{eur(bp[0])}–{eur(bp[1])}</td>"),
        ("<td class=\"guide-range\">&lt; 45€</td>",     f"<td class=\"guide-range\">&lt; {eur(bp[0])}</td>"),
    ]
    for a, b in repl:
        if a not in html:
            print(f"⚠️  aviso: padrão não encontrado para substituição: {a[:60]}…", flush=True)
        html = html.replace(a, b)
    return html

# ─── UTIL ────────────────────────────────────────────────────────────────────
def _save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)

def _load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    t0 = time.time()
    force = "--refresh" in sys.argv

    # FASE 1 — documentos físicos (cache opcional)
    docs = None if force else _load_json(DOCS_CACHE, None)
    if docs is None:
        print("\n📦 A extrair documentos das lojas físicas (2023-2026)…", flush=True)
        docs = fetch_physical_docs()
        _save_json(DOCS_CACHE, docs)
    else:
        print(f"📦 Cache de documentos: {len(docs)} docs físicos (usa --refresh p/ refazer)", flush=True)
    print(f"✅ {len(docs)} documentos de loja física", flush=True)

    # FASE 2 — clientes (cache opcional → reconstruções ficam offline)
    custs = None if force else _load_json(CUSTS_CACHE, None)
    if custs is None:
        print("\n👥 A buscar dados dos clientes…", flush=True)
        custs = fetch_customers()
        _save_json(CUSTS_CACHE, custs)
    else:
        print(f"👥 Cache de clientes: {len(custs)} (usa --refresh p/ refazer)", flush=True)
    cust_by_id = {c.get("customer_id"): c for c in custs}
    print(f"✅ {len(cust_by_id)} clientes no Moloni", flush=True)

    # FASE 3 — produtos por documento (getOne, resumível)
    getone = _load_json(GETONE_CACHE, {})
    fetch_products(docs, getone)

    # Construir CRM
    print("\n🧮 A construir o CRM das lojas…", flush=True)
    customers = build_crm_lojas(docs, cust_by_id, getone)
    print(f"✅ {len(customers)} clientes únicos de loja física", flush=True)

    print("📊 A calcular scores RFV…", flush=True)
    customers = score_rfv(customers)
    from collections import Counter
    seg_counts = Counter(c["rfv_segment"] for c in customers)
    for seg, count in sorted(seg_counts.items(), key=lambda x: -x[1]):
        meta = SEGMENTS_META.get(seg, {})
        print(f"  {meta.get('icon','•')} {meta.get('name', seg):<25}: {count:>5} clientes", flush=True)

    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")

    _save_json(OUTPUT_DATA, customers)
    print(f"✅ Dados guardados: {OUTPUT_DATA} ({os.path.getsize(OUTPUT_DATA)//1024}KB)", flush=True)

    html = generate_html(customers, generated_at)
    html = adapt_html_for_lojas(html, customers)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ CRM gerado: {OUTPUT_HTML} ({os.path.getsize(OUTPUT_HTML)//1024}KB)", flush=True)

    print(f"\n📊 TOP 10 CLIENTES (lojas físicas):", flush=True)
    print(f"{'#':<4} {'Nome':<28} {'Loja(s)':<22} {'Enc.':>5} {'Total':>11}")
    print("─" * 75)
    for i, c in enumerate(customers[:10], 1):
        print(f"{i:<4} {c['name'][:27]:<28} {c['store_label'][:21]:<22} {c['total_orders']:>5} {c['total_spent']:>10,.2f}€")
    print(f"\n⏱  Tempo total: {(time.time()-t0)/60:.1f} min", flush=True)

if __name__ == "__main__":
    main()
