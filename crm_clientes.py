#!/usr/bin/env python3
"""
CRM de Clientes — Cavemen Store (Magento)
Ranking de clientes + ficha completa com encomendas, produtos e dados pessoais.
"""

import requests, json, time, os
from datetime import datetime, date
from collections import defaultdict

BASE_URL       = os.getenv("MAGENTO_URL",  "https://www.cavemenstore.com")
ADMIN_USER     = os.getenv("MAGENTO_USER", "marketing@cavemenstore.com")
ADMIN_PASSWORD = os.getenv("MAGENTO_PASS", "")
CACHE_FILE     = "crm_orders_cache.json"
FALLBACK_CACHE = "gender_orders_cache.json"
OUTPUT_HTML    = "crm_clientes.html"
OUTPUT_DATA    = "crm_data.json"

VALID_STATUSES = {"complete", "processing", "closed"}
STATUS_LABELS  = {
    "complete": "Completa", "processing": "Em processo",
    "closed": "Fechada",    "canceled": "Cancelada",
    "pending": "Pendente",  "holded": "Em espera",
    "pending_payment": "Pag. pendente",
}
STATUS_COLORS = {
    "complete": "#4caf89", "processing": "#5b9bd5",
    "closed": "#888",      "canceled": "#e05454",
    "pending": "#f0a732",  "holded": "#888",
    "pending_payment": "#f0a732",
}

def get_token():
    print("🔐 Autenticando no Magento...")
    r = requests.post(f"{BASE_URL}/rest/V1/integration/admin/token",
                      json={"username": ADMIN_USER, "password": ADMIN_PASSWORD}, timeout=30)
    r.raise_for_status()
    print("✅ Token obtido")
    return r.json()

def mget(endpoint, token, params=None):
    H = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    r = requests.get(f"{BASE_URL}/rest/V1{endpoint}", headers=H, params=params, timeout=90)
    r.raise_for_status()
    return r.json()

def fetch_all_orders(token, force_refresh=False):
    for cache in ([CACHE_FILE, FALLBACK_CACHE] if not force_refresh else []):
        if os.path.exists(cache):
            print(f"📦 Cache: {cache}")
            with open(cache, encoding="utf-8") as f:
                orders = json.load(f)
            print(f"✅ {len(orders)} encomendas — usa --refresh para actualizar")
            return orders

    print("📥 A buscar TODAS as encomendas do Magento...")
    all_orders, page, page_size = [], 1, 200
    while True:
        for attempt in range(3):
            try:
                data = mget("/orders", token, params={
                    "searchCriteria[pageSize]": page_size,
                    "searchCriteria[currentPage]": page,
                    "searchCriteria[sortOrders][0][field]": "created_at",
                    "searchCriteria[sortOrders][0][direction]": "ASC",
                    "fields": (
                        "items[entity_id,increment_id,created_at,status,grand_total,"
                        "customer_firstname,customer_lastname,customer_email,"
                        "customer_is_guest,billing_address,"
                        "items[name,qty_ordered,price,product_type,sku]],"
                        "total_count"
                    ),
                })
                break
            except Exception as e:
                if attempt == 2: raise
                print(f"\n  ⚠️  Timeout, a tentar novamente ({attempt+1}/3)...")
                time.sleep(3)

        items = data.get("items", [])
        all_orders.extend(items)
        total = data.get("total_count", 0)
        print(f"  Página {page}: {len(all_orders)}/{total}", end="\r")
        if len(items) < page_size or len(all_orders) >= total:
            break
        page += 1
        time.sleep(0.3)

    print(f"\n✅ {len(all_orders)} encomendas")
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(all_orders, f, ensure_ascii=False)
    return all_orders

SEGMENTS_META = {
    'champions':   {'name':'Champions',          'color':'#e8c98a', 'icon':'🏆', 'desc':'Compraram recentemente, frequentemente e gastaram muito'},
    'loyal':       {'name':'Clientes Fiéis',     'color':'#4caf89', 'icon':'💚', 'desc':'Compram com frequência e gastam bem'},
    'potential':   {'name':'Potenciais Fiéis',   'color':'#5b9bd5', 'icon':'⭐', 'desc':'Clientes recentes com potencial para fidelizar'},
    'new':         {'name':'Novos Clientes',     'color':'#7ec8a4', 'icon':'🆕', 'desc':'Compraram pela primeira vez recentemente'},
    'promising':   {'name':'Promissores',        'color':'#a8c8ff', 'icon':'🌱', 'desc':'Mostram interesse, ainda a crescer'},
    'attention':   {'name':'Precisam Atenção',   'color':'#f0a732', 'icon':'⚠️',  'desc':'Acima da média mas a distanciar-se'},
    'at_risk':     {'name':'Em Risco',           'color':'#e07054', 'icon':'🔴', 'desc':'Compravam muito mas não compram há algum tempo'},
    'cant_lose':   {'name':'Não Perder',         'color':'#c94b4b', 'icon':'🚨', 'desc':'Grandes compradores inativos — reactivar urgente'},
    'hibernating': {'name':'A Hibernar',         'color':'#666666', 'icon':'😴', 'desc':'Última compra há muito tempo, pouca frequência'},
    'lost':        {'name':'Perdidos',           'color':'#333333', 'icon':'💀', 'desc':'Inactivos há muito tempo e pouco frequentes'},
}

# Tabela de segmentos indexada por (F, R) — F=frequência, R=recência (ambos 1-5)
_SEG_TABLE = {
    (5,5):'champions', (5,4):'champions', (5,3):'loyal',    (5,2):'at_risk',    (5,1):'cant_lose',
    (4,5):'champions', (4,4):'loyal',     (4,3):'loyal',    (4,2):'at_risk',    (4,1):'cant_lose',
    (3,5):'potential', (3,4):'potential', (3,3):'attention',(3,2):'attention',  (3,1):'hibernating',
    (2,5):'new',       (2,4):'promising', (2,3):'promising',(2,2):'hibernating',(2,1):'lost',
    (1,5):'new',       (1,4):'new',       (1,3):'promising',(1,2):'lost',       (1,1):'lost',
}

def _quintile_score(value, breakpoints, invert=False):
    """Devolve score 1-5 baseado em breakpoints (lista de 4 valores = percentis 20,40,60,80)."""
    if invert:
        if value <= breakpoints[0]: return 5
        if value <= breakpoints[1]: return 4
        if value <= breakpoints[2]: return 3
        if value <= breakpoints[3]: return 2
        return 1
    else:
        if value >= breakpoints[3]: return 5
        if value >= breakpoints[2]: return 4
        if value >= breakpoints[1]: return 3
        if value >= breakpoints[0]: return 2
        return 1

def _freq_score(orders):
    """Score de Frequência com limiares absolutos.
    Quintis não funcionam quando a maioria tem 1 encomenda — colapsam todos
    no mesmo breakpoint e inflacionam os scores. Limiares fixos são mais honestos.
      F=1  →  1 encomenda   (comprador único)
      F=2  →  2 encomendas
      F=3  →  3–4 encomendas
      F=4  →  5–9 encomendas
      F=5  → 10+ encomendas
    """
    if orders >= 10: return 5
    if orders >= 5:  return 4
    if orders >= 3:  return 3
    if orders >= 2:  return 2
    return 1


def _recency_score(days):
    """Score de Recência com limiares absolutos (dias desde a última compra).
    Quintis não funcionam quando há 3 anos de histórico — distribuem igualmente
    clientes activos e inativos, tornando R=4 equivalente a "comprou há ~1 ano".
    Limiares fixos espelham o comportamento real de compra em moda masculina:
      R=5  →  ≤ 30 dias     (comprou este mês)
      R=4  →  31–90 dias    (comprou este trimestre)
      R=3  →  91–180 dias   (comprou neste semestre)
      R=2  →  181–365 dias  (comprou este ano)
      R=1  →  > 365 dias    (inactivo há mais de 1 ano)
    """
    if days <= 30:  return 5
    if days <= 90:  return 4
    if days <= 180: return 3
    if days <= 365: return 2
    return 1


def score_rfv(customers):
    """Calcula scores RFV (1-5) e segmento para cada cliente. Modifica a lista in-place e devolve-a.

    Recência:   limiares absolutos (ver _recency_score) — reflecte inactividade real.
    Frequência: limiares absolutos (ver _freq_score) — evita inflação de scores.
    Valor:      quintis — o gasto é relativo à base de clientes da loja.
    """
    v_vals = sorted([c['total_spent'] for c in customers])

    def percentiles(vals, ps):
        n = len(vals)
        result = []
        for p in ps:
            idx = p / 100 * (n - 1)
            lo, hi = int(idx), min(int(idx) + 1, n - 1)
            result.append(vals[lo] + (vals[hi] - vals[lo]) * (idx - lo))
        return result

    v_bp = percentiles(v_vals, [20, 40, 60, 80])

    for c in customers:
        days = c.get('days_since')
        r = _recency_score(days if isinstance(days, (int, float)) else 9999)
        f = _freq_score(c['total_orders'])
        v = _quintile_score(c['total_spent'], v_bp)
        c['rfv_r'] = r
        c['rfv_f'] = f
        c['rfv_v'] = v
        c['rfv_score'] = r + f + v
        c['rfv_segment'] = _SEG_TABLE.get((f, r), 'lost')

    return customers


def build_crm(orders):
    customers = {}

    for order in orders:
        status = order.get("status", "")
        email = (order.get("customer_email") or "").lower().strip()
        ba = order.get("billing_address") or {}
        if not email:
            email = (ba.get("email") or "").lower().strip()
        if not email:
            continue

        total = float(order.get("grand_total") or 0)
        fname = order.get("customer_firstname") or ba.get("firstname") or ""
        lname = order.get("customer_lastname") or ba.get("lastname") or ""
        full_name = f"{fname} {lname}".strip()
        date_str = (order.get("created_at") or "")[:10]
        is_guest = bool(order.get("customer_is_guest"))

        if email not in customers:
            customers[email] = {
                "name": full_name,
                "email": email,
                "is_guest": is_guest,
                "phone": ba.get("telephone") or "",
                "city": ba.get("city") or "",
                "region": ba.get("region") or "",
                "postcode": ba.get("postcode") or "",
                "street": ", ".join(ba.get("street") or []),
                "country": ba.get("country_id") or "PT",
                "vat": ba.get("vat_id") or "",
                "total_orders": 0,
                "total_spent": 0.0,
                "first_order": "",
                "last_order": "",
                "all_orders": [],
                "products": defaultdict(lambda: {"name": "", "qty": 0.0, "revenue": 0.0}),
            }

        c = customers[email]
        # Update name/address from registered orders (prefer non-guest)
        if full_name and (not c["name"] or (not is_guest and c["is_guest"])):
            c["name"] = full_name
            c["phone"] = ba.get("telephone") or c["phone"]
            c["city"] = ba.get("city") or c["city"]
            c["region"] = ba.get("region") or c["region"]
            c["postcode"] = ba.get("postcode") or c["postcode"]
            c["street"] = ", ".join(ba.get("street") or []) or c["street"]
            c["vat"] = ba.get("vat_id") or c["vat"]
        if not is_guest:
            c["is_guest"] = False

        # Only count valid orders in totals
        if status in VALID_STATUSES and total > 0:
            c["total_orders"] += 1
            c["total_spent"] += total
            if not c["first_order"] or date_str < c["first_order"]:
                c["first_order"] = date_str
            if not c["last_order"] or date_str > c["last_order"]:
                c["last_order"] = date_str

        # Store all orders (including canceled) for history
        # Magento structure: configurable has the real price; virtual/simple children have price=0
        # Strategy: keep configurable (real price + name) and standalone simple; skip virtual children
        order_items = []
        for item in (order.get("items") or []):
            ptype = item.get("product_type") or ""
            price = float(item.get("price") or 0)

            # Skip virtual (children of configurables — price=0, just carry size/colour)
            # Skip bundle (complex wrapper, children will have individual prices)
            if ptype in ("virtual", "bundle"):
                continue

            # For simple items with price=0 skip — they are likely configurable children
            # that Magento tagged as simple instead of virtual
            if ptype == "simple" and price == 0:
                continue

            qty = float(item.get("qty_ordered") or 0)
            order_items.append({
                "name": item.get("name") or item.get("sku") or "?",
                "sku": item.get("sku") or "",
                "qty": qty,
                "price": price,
                "subtotal": round(qty * price, 2),
            })
            if status in VALID_STATUSES:
                sku = item.get("sku") or item.get("name") or "?"
                c["products"][sku]["name"] = item.get("name") or sku
                c["products"][sku]["qty"] += qty
                c["products"][sku]["revenue"] += qty * price

        c["all_orders"].append({
            "id": order.get("increment_id") or str(order.get("entity_id", "")),
            "date": date_str,
            "datetime": (order.get("created_at") or "")[:16].replace("T", " "),
            "status": status,
            "total": round(total, 2),
            "items": order_items,
        })

    # Sort each customer's orders by date desc
    for c in customers.values():
        c["all_orders"].sort(key=lambda x: x["date"], reverse=True)

    # Convert products to sorted list
    result = []
    today = date.today().isoformat()
    for email, c in customers.items():
        if c["total_orders"] == 0:
            continue
        top_products = sorted(
            [{"sku": k, **v} for k, v in c["products"].items()],
            key=lambda x: x["revenue"], reverse=True
        )
        days_since = ""
        if c["last_order"]:
            try:
                d = (date.today() - date.fromisoformat(c["last_order"])).days
                days_since = d
            except:
                pass

        result.append({
            "name":         c["name"] or email.split("@")[0].title(),
            "email":        email,
            "is_guest":     c["is_guest"],
            "phone":        c["phone"],
            "city":         c["city"],
            "region":       c["region"],
            "postcode":     c["postcode"],
            "street":       c["street"],
            "country":      c["country"],
            "vat":          c["vat"],
            "total_orders": c["total_orders"],
            "total_spent":  round(c["total_spent"], 2),
            "avg_order":    round(c["total_spent"] / c["total_orders"], 2) if c["total_orders"] else 0,
            "first_order":  c["first_order"],
            "last_order":   c["last_order"],
            "days_since":   days_since,
            "products":     top_products,
            "all_orders":   c["all_orders"],
        })

    result.sort(key=lambda x: x["total_spent"], reverse=True)
    return result


def generate_html(customers, generated_at, show_lojas_tab=False):
    from collections import Counter, defaultdict

    total_customers = len(customers)
    total_revenue   = sum(c["total_spent"] for c in customers)
    total_orders    = sum(c["total_orders"] for c in customers)
    avg_order       = total_revenue / total_orders if total_orders else 0
    top10_revenue   = sum(c["total_spent"] for c in customers[:10])
    recurring       = sum(1 for c in customers if c["total_orders"] >= 2)

    # Stats only — embedded in HTML (just numbers, tiny)
    stats = {
        "total_customers": total_customers,
        "total_revenue":   round(total_revenue, 0),
        "total_orders":    total_orders,
        "avg_order":       round(avg_order, 2),
        "recurring":       recurring,
        "top10_revenue":   round(top10_revenue, 0),
        "top10_pct":       round(top10_revenue / total_revenue * 100, 1) if total_revenue else 0,
        "recurring_pct":   round(recurring / total_customers * 100, 0) if total_customers else 0,
        "generated_at":    generated_at,
    }
    stats_json = json.dumps(stats)
    status_colors_json = json.dumps(STATUS_COLORS)
    status_labels_json = json.dumps(STATUS_LABELS)

    # RFV data for embedded matrix
    seg_counts  = Counter(c["rfv_segment"] for c in customers if "rfv_segment" in c)
    seg_revenue = defaultdict(float)
    for c in customers:
        if "rfv_segment" in c:
            seg_revenue[c["rfv_segment"]] += c["total_spent"]
    matrix = {}
    for c in customers:
        if "rfv_f" in c and "rfv_r" in c:
            key = f"{c['rfv_f']}_{c['rfv_r']}"
            matrix[key] = matrix.get(key, 0) + 1
    matrix_json        = json.dumps(matrix)
    segments_meta_json = json.dumps(SEGMENTS_META)
    seg_table_js = "{" + ",".join(f"'{k}':'{v}'" for k, v in {
        '5_5':'champions','5_4':'champions','5_3':'loyal','5_2':'at_risk','5_1':'cant_lose',
        '4_5':'champions','4_4':'loyal','4_3':'loyal','4_2':'at_risk','4_1':'cant_lose',
        '3_5':'potential','3_4':'potential','3_3':'attention','3_2':'attention','3_1':'hibernating',
        '2_5':'new','2_4':'promising','2_3':'promising','2_2':'hibernating','2_1':'lost',
        '1_5':'new','1_4':'new','1_3':'promising','1_2':'lost','1_1':'lost',
    }.items()) + "}"

    # Aba opcional "Clientes Loja" (só no CRM do site) — embebe o CRM das lojas via iframe.
    lojas_btn = ('<button class="tab-btn" id="tab-btn-lojas" onclick="switchTab(\'lojas\',this)">🏪 Clientes Loja</button>'
                 if show_lojas_tab else '')
    lojas_tab = ('<div id="tab-lojas" style="display:none">'
                 '<iframe id="lojasFrame" src="" title="Clientes Loja" '
                 'style="width:100%;height:calc(100vh - 56px);border:0;display:block"></iframe></div>'
                 if show_lojas_tab else '')

    return f"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CRM · Cavemen Store</title>
<style>
:root{{--bg:#0f0f0f;--s1:#1a1a1a;--s2:#222;--s3:#2a2a2a;--border:#2e2e2e;--text:#e8e8e8;--muted:#777;--accent:#c9a96e;--gold:#e8c98a;--green:#4caf89;--red:#e05454;--blue:#5b9bd5;--orange:#f0a732;}}
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:var(--bg);color:var(--text);font-family:'Inter',system-ui,sans-serif;}}

/* ── Header ── */
header{{background:var(--s1);border-bottom:1px solid var(--border);padding:16px 28px;display:flex;align-items:center;gap:12px;}}
.logo{{font-size:1.3rem;font-weight:800;color:var(--gold);letter-spacing:.05em;}}
.logo span{{color:var(--muted);font-weight:400;}}
.gen{{font-size:.72rem;color:var(--muted);}}

/* ── Tab Navigation ── */
.tab-nav{{background:var(--s1);border-bottom:2px solid var(--border);padding:0 28px;display:flex;gap:0;align-items:stretch;margin-left:auto;}}
.tab-btn{{padding:12px 22px;background:none;border:none;border-bottom:2px solid transparent;color:var(--muted);font-size:.82rem;font-weight:600;cursor:pointer;transition:.15s;white-space:nowrap;margin-bottom:-2px;letter-spacing:.02em;}}
.tab-btn:hover{{color:var(--text);}}
.tab-btn.active{{color:var(--gold);border-bottom-color:var(--gold);}}

/* ── Stats bar ── */
.stats{{display:grid;grid-template-columns:repeat(6,1fr);gap:1px;background:var(--border);border-bottom:1px solid var(--border);}}
.stats-4{{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--border);border-bottom:1px solid var(--border);}}
.stat{{background:var(--s1);padding:14px 20px;}}
.stat-l{{font-size:.65rem;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin-bottom:5px;}}
.stat-v{{font-size:1.45rem;font-weight:700;color:var(--gold);line-height:1;}}
.stat-s{{font-size:.7rem;color:var(--muted);margin-top:3px;}}

/* ── Controls ── */
.controls{{padding:12px 28px;background:var(--s1);border-bottom:1px solid var(--border);display:flex;gap:10px;align-items:center;flex-wrap:wrap;}}
.search{{flex:1;min-width:220px;max-width:340px;position:relative;}}
.search input{{width:100%;padding:8px 12px 8px 34px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:.88rem;outline:none;}}
.search input:focus{{border-color:var(--accent);}}
.search::before{{content:"🔍";position:absolute;left:10px;top:50%;transform:translateY(-50%);font-size:.8rem;pointer-events:none;}}
.fbtn{{padding:6px 13px;border-radius:6px;border:1px solid var(--border);background:var(--s2);color:var(--muted);font-size:.78rem;cursor:pointer;transition:.15s;white-space:nowrap;}}
.fbtn:hover,.fbtn.on{{background:var(--accent);color:#000;border-color:var(--accent);font-weight:600;}}
.cnt{{margin-left:auto;font-size:.78rem;color:var(--muted);}}

/* ── Table ── */
.tbl-wrap{{padding:0 28px 60px;overflow-x:auto;}}
table{{width:100%;border-collapse:collapse;margin-top:14px;font-size:.88rem;}}
thead th{{font-size:.68rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);padding:9px 12px;text-align:left;border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--bg);cursor:pointer;user-select:none;white-space:nowrap;}}
thead th:hover{{color:var(--accent);}}
thead th.sorted{{color:var(--gold);}}
.customer-row{{cursor:pointer;transition:background .1s;}}
.customer-row:hover{{background:var(--s2);}}
.customer-row td{{padding:11px 12px;border-bottom:1px solid var(--border);vertical-align:middle;}}
.td-rank{{width:44px;font-weight:700;color:var(--muted);font-size:.85rem;}}
.rank-gold{{color:var(--gold)!important;font-size:.95rem;}}
.c-name{{font-weight:600;margin-bottom:2px;}}
.c-email{{font-size:.75rem;color:var(--muted);margin-bottom:3px;}}
.c-meta{{display:flex;align-items:center;gap:6px;}}
.c-loc{{font-size:.7rem;color:var(--muted);}}
.badge{{font-size:.62rem;padding:2px 7px;border-radius:20px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;}}
.badge.member{{background:#1e3a2f;color:var(--green);}}
.badge.guest{{background:#2a1e1e;color:var(--red);}}
.num{{font-size:1.05rem;font-weight:700;}}
.gold{{color:var(--gold);}}
.sub{{font-size:.7rem;color:var(--muted);margin-top:2px;}}
.bar-wrap{{background:var(--border);border-radius:2px;height:3px;margin:4px 0;width:110px;}}
.bar{{background:var(--accent);height:3px;border-radius:2px;}}
.days-hot{{color:var(--green);font-weight:600;font-size:.8rem;}}
.days-warm{{color:var(--orange);font-size:.8rem;}}
.days-cold{{color:var(--muted);font-size:.8rem;}}
.td-product{{font-size:.8rem;color:var(--muted);max-width:180px;}}
.hidden{{display:none!important;}}

/* ── Modal overlay ── */
.overlay{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:100;backdrop-filter:blur(3px);}}
.overlay.open{{display:flex;align-items:stretch;justify-content:flex-end;}}

/* ── Profile drawer ── */
.drawer{{width:680px;max-width:100vw;background:var(--s1);display:flex;flex-direction:column;overflow:hidden;animation:slideIn .22s ease;box-shadow:-8px 0 40px rgba(0,0,0,.5);}}
@keyframes slideIn{{from{{transform:translateX(100%)}}to{{transform:translateX(0)}}}}

.drawer-header{{padding:20px 24px 16px;border-bottom:1px solid var(--border);display:flex;align-items:flex-start;gap:14px;flex-shrink:0;}}
.drawer-avatar{{width:52px;height:52px;border-radius:50%;background:var(--s3);border:2px solid var(--border);display:flex;align-items:center;justify-content:center;font-size:1.3rem;font-weight:700;color:var(--gold);flex-shrink:0;}}
.drawer-title{{flex:1;}}
.drawer-name{{font-size:1.2rem;font-weight:700;margin-bottom:4px;}}
.drawer-email{{font-size:.82rem;color:var(--muted);}}
.drawer-badges{{display:flex;gap:6px;margin-top:6px;align-items:center;flex-wrap:wrap;}}
.drawer-close{{background:none;border:none;color:var(--muted);font-size:1.4rem;cursor:pointer;padding:4px;line-height:1;flex-shrink:0;}}
.drawer-close:hover{{color:var(--text);}}

.drawer-body{{flex:1;overflow-y:auto;padding:20px 24px;}}
.drawer-body::-webkit-scrollbar{{width:5px;}}
.drawer-body::-webkit-scrollbar-track{{background:var(--s1);}}
.drawer-body::-webkit-scrollbar-thumb{{background:var(--border);border-radius:3px;}}

/* ── Profile sections ── */
.section{{margin-bottom:24px;}}
.section-title{{font-size:.68rem;text-transform:uppercase;letter-spacing:.1em;color:var(--accent);font-weight:700;margin-bottom:12px;padding-bottom:6px;border-bottom:1px solid var(--border);}}

.kpi-row{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:20px;}}
.kpi{{background:var(--s2);border:1px solid var(--border);border-radius:8px;padding:12px;text-align:center;}}
.kpi-val{{font-size:1.3rem;font-weight:700;color:var(--gold);}}
.kpi-lbl{{font-size:.65rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-top:3px;}}

.info-grid{{display:grid;grid-template-columns:1fr 1fr;gap:8px;}}
.info-item{{background:var(--s2);border:1px solid var(--border);border-radius:6px;padding:10px 12px;}}
.info-lbl{{font-size:.65rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:3px;}}
.info-val{{font-size:.88rem;color:var(--text);}}
.info-val.empty{{color:var(--border);font-style:italic;}}

/* ── Products list ── */
.products-list{{display:flex;flex-direction:column;gap:6px;}}
.prod-item{{background:var(--s2);border:1px solid var(--border);border-radius:6px;padding:10px 14px;display:flex;align-items:center;gap:12px;}}
.prod-rank{{font-size:.7rem;font-weight:700;color:var(--muted);width:20px;text-align:center;}}
.prod-name{{flex:1;font-size:.85rem;}}
.prod-sku{{font-size:.68rem;color:var(--muted);margin-top:1px;}}
.prod-qty{{font-size:.78rem;color:var(--muted);white-space:nowrap;}}
.prod-rev{{font-size:.9rem;font-weight:700;color:var(--gold);white-space:nowrap;min-width:70px;text-align:right;}}

/* ── Orders timeline ── */
.orders-list{{display:flex;flex-direction:column;gap:8px;}}
.order-card{{background:var(--s2);border:1px solid var(--border);border-radius:8px;overflow:hidden;}}
.order-head{{padding:10px 14px;display:flex;align-items:center;gap:10px;cursor:pointer;transition:background .1s;}}
.order-head:hover{{background:var(--s3);}}
.order-num{{font-size:.78rem;font-weight:700;color:var(--gold);}}
.order-date{{font-size:.75rem;color:var(--muted);}}
.order-status{{font-size:.65rem;padding:2px 8px;border-radius:20px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;margin-left:auto;}}
.order-total{{font-size:.9rem;font-weight:700;}}
.order-chevron{{font-size:.7rem;color:var(--muted);transition:transform .2s;margin-left:6px;}}
.order-items{{padding:0 14px 12px;display:none;}}
.order-item-row{{display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid var(--border);font-size:.8rem;}}
.order-item-row:last-child{{border-bottom:none;}}
.oi-name{{flex:1;color:var(--muted);}}
.oi-qty{{color:var(--muted);white-space:nowrap;}}
.oi-price{{font-weight:600;white-space:nowrap;min-width:55px;text-align:right;}}
.refresh-btn{{padding:7px 14px;border-radius:6px;border:1px solid var(--border);background:var(--s2);color:var(--text);font-size:.8rem;cursor:pointer;transition:.15s;white-space:nowrap;}}
.refresh-btn:hover{{background:var(--accent);color:#000;border-color:var(--accent);}}
.refresh-btn:disabled{{opacity:.4;cursor:not-allowed;}}
.refresh-full{{color:var(--muted);}}
.refresh-full:hover{{background:var(--blue);color:#fff;border-color:var(--blue);}}
.export-btn{{background:var(--s2);color:var(--green);border-color:var(--green);font-weight:600;}}
.export-btn:hover{{background:var(--green);color:#000;border-color:var(--green);}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
.spin{{display:inline-block;animation:spin 1s linear infinite;}}

/* ── Date filter ── */
.date-filter{{display:flex;align-items:center;gap:6px;background:var(--s3);border:1px solid var(--border);border-radius:8px;padding:5px 10px;}}
.date-filter-label{{font-size:.62rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);font-weight:600;}}
.date-filter input[type=date]{{background:none;border:none;color:var(--text);font-size:.8rem;outline:none;cursor:pointer;padding:2px 4px;font-family:inherit;width:112px;}}
.date-filter input[type=date]::-webkit-calendar-picker-indicator{{filter:invert(.5);cursor:pointer;}}
.date-filter-sep{{color:var(--border);font-size:.9rem;padding:0 2px;}}
.date-reset{{padding:5px 10px;border-radius:6px;border:1px solid var(--border);background:none;color:var(--muted);font-size:.75rem;cursor:pointer;transition:.15s;}}
.date-reset:hover{{color:var(--text);border-color:var(--text);}}
.date-active{{border-color:var(--accent)!important;}}

/* ── RFV Tab ── */
.rfv-main{{padding:24px 28px 60px;}}
.rfv-section-title{{font-size:.75rem;text-transform:uppercase;letter-spacing:.1em;color:var(--accent);font-weight:700;margin-bottom:16px;padding-bottom:6px;border-bottom:1px solid var(--border);}}
.matrix-section{{margin-bottom:32px;}}
.matrix-and-guide{{display:flex;gap:28px;align-items:flex-start;flex-wrap:wrap;}}
.matrix-left{{display:flex;flex-direction:column;gap:20px;}}
.rfv-guide{{background:var(--s1);border:1px solid var(--border);border-radius:12px;padding:20px 22px;flex:1;min-width:560px;}}
.guide-title{{font-size:.72rem;text-transform:uppercase;letter-spacing:.1em;color:var(--accent);font-weight:700;margin-bottom:14px;padding-bottom:8px;border-bottom:1px solid var(--border);}}
.guide-inner{{display:grid;grid-template-columns:1fr 1fr;gap:24px;align-items:start;}}
.guide-col{{}}
.guide-dim{{margin-bottom:16px;}}
.guide-dim-header{{display:flex;align-items:center;gap:8px;margin-bottom:8px;}}
.guide-dim-badge{{font-size:.7rem;font-weight:700;padding:3px 9px;border-radius:20px;letter-spacing:.04em;}}
.guide-dim-label{{font-size:.8rem;font-weight:600;color:var(--text);}}
.guide-dim-sub{{font-size:.72rem;color:var(--muted);font-style:italic;}}
.guide-table{{width:100%;border-collapse:collapse;font-size:.75rem;}}
.guide-table tr{{border-bottom:1px solid var(--border);}}
.guide-table tr:last-child{{border-bottom:none;}}
.guide-table td{{padding:5px 8px;vertical-align:middle;}}
.guide-score{{font-weight:700;font-size:.82rem;width:36px;text-align:center;}}
.guide-range{{color:var(--muted);width:120px;}}
.guide-desc{{color:var(--text);}}
.guide-seg-table{{width:100%;border-collapse:collapse;font-size:.73rem;}}
.guide-seg-table tr{{border-bottom:1px solid var(--border);}}
.guide-seg-table tr:last-child{{border-bottom:none;}}
.guide-seg-table td{{padding:5px 8px;vertical-align:middle;}}
.guide-formula{{background:var(--s2);border:1px solid var(--border);border-radius:8px;padding:10px 14px;font-size:.75rem;color:var(--muted);margin-top:14px;line-height:1.6;}}
.matrix-wrap{{display:flex;gap:0;}}
.matrix-y-labels{{display:flex;flex-direction:column;justify-content:space-around;padding-right:10px;padding-top:28px;padding-bottom:4px;}}
.matrix-y-label{{font-size:.65rem;color:var(--muted);text-align:right;width:60px;display:flex;align-items:center;justify-content:flex-end;}}
.matrix-x-labels{{display:flex;justify-content:space-around;padding-left:4px;margin-top:6px;}}
.matrix-x-label{{font-size:.65rem;color:var(--muted);text-align:center;width:80px;}}
.matrix-x-title{{text-align:center;font-size:.7rem;color:var(--muted);margin-top:4px;}}
.matrix-y-title{{font-size:.7rem;color:var(--muted);writing-mode:vertical-rl;transform:rotate(180deg);text-align:center;padding-right:6px;}}
.matrix-grid{{display:grid;grid-template-columns:repeat(5,90px);grid-template-rows:repeat(5,76px);gap:0;}}
.seg-cards{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:32px;}}
.seg-card{{background:var(--s1);border:1px solid var(--border);border-radius:10px;padding:14px;cursor:pointer;transition:border-color .15s,background .15s;position:relative;overflow:hidden;}}
.seg-card:hover,.seg-card.active{{border-color:var(--card-color,var(--accent));}}
.seg-card.active{{background:color-mix(in srgb,var(--card-color,var(--accent)) 10%,var(--s1));}}
.seg-icon{{font-size:1.4rem;margin-bottom:6px;}}
.seg-name{{font-size:.78rem;font-weight:700;margin-bottom:2px;}}
.seg-count{{font-size:1.3rem;font-weight:700;}}
.seg-rev{{font-size:.7rem;color:var(--muted);margin-top:3px;}}
.seg-pct{{font-size:.65rem;padding:2px 6px;border-radius:12px;font-weight:600;margin-top:4px;display:inline-block;}}
.rfv-controls{{padding:0 0 14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;}}
.rfv-search{{position:relative;}}
.rfv-search input{{padding:8px 12px 8px 34px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:.88rem;outline:none;width:280px;}}
.rfv-search input:focus{{border-color:var(--accent);}}
.rfv-search::before{{content:"🔍";position:absolute;left:10px;top:50%;transform:translateY(-50%);font-size:.8rem;pointer-events:none;}}
.rfv-tbl-wrap{{overflow-x:auto;}}
.rfv-badge{{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:5px;font-size:.75rem;font-weight:700;}}
.r-badge{{background:#1a3a5c;color:#5b9bd5;}}
.f-badge{{background:#1a3a2a;color:#4caf89;}}
.v-badge{{background:#3a2f0a;color:#e8c98a;}}
.score-badge{{display:inline-block;padding:2px 8px;border-radius:12px;font-size:.7rem;font-weight:700;background:var(--s3);color:var(--text);}}
.seg-pill{{display:inline-block;padding:3px 10px;border-radius:20px;font-size:.65rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em;}}
</style>
</head>
<body>

<header>
  <div class="logo">CAVEMEN <span>· CRM</span></div>
  <div class="gen" id="genDate" style="margin-left:16px;">Gerado em {generated_at} · {total_customers:,} clientes</div>
  <div style="display:flex;gap:8px;margin-left:auto;">
    <button class="refresh-btn" id="btnRefresh" onclick="refreshCRM(false)" title="Atualiza usando cache (rápido)">↻ Atualizar</button>
    <button class="refresh-btn refresh-full" id="btnFull" onclick="refreshCRM(true)" title="Vai buscar dados novos ao Magento (~2 min)">⬇ Dados Novos</button>
  </div>
  <div class="tab-nav">
    <button class="tab-btn active" id="tab-btn-clientes" onclick="switchTab('clientes',this)">👥 Clientes</button>
    <button class="tab-btn" id="tab-btn-rfv" onclick="switchTab('rfv',this)">📊 Matriz RFV</button>
    <button class="tab-btn" id="tab-btn-pontos" onclick="switchTab('pontos',this)">🏆 Pontos</button>
    {lojas_btn}
  </div>
</header>

<div id="refreshBar" style="display:none;background:#1a1a1a;border-bottom:1px solid #2e2e2e;padding:10px 28px;font-size:.8rem;color:#888;align-items:center;gap:12px;">
  <span class="spin">⟳</span>
  <span id="refreshMsg">A atualizar dados…</span>
  <span id="refreshLog" style="color:#555;margin-left:8px;font-family:monospace;"></span>
</div>

<!-- ═══════════════════════════════════════════════ TAB: CLIENTES ═══ -->
<div id="tab-clientes">

<div class="stats" id="statsBar">
  <div class="stat"><div class="stat-l">Clientes únicos</div><div class="stat-v" id="s-cu">…</div><div class="stat-s">loja online</div></div>
  <div class="stat"><div class="stat-l">Receita total</div><div class="stat-v" id="s-rev">…</div><div class="stat-s">encomendas válidas</div></div>
  <div class="stat"><div class="stat-l">Encomendas</div><div class="stat-v" id="s-ord">…</div><div class="stat-s">completas/processadas</div></div>
  <div class="stat"><div class="stat-l">Ticket médio</div><div class="stat-v" id="s-avg">…</div><div class="stat-s">por encomenda</div></div>
  <div class="stat"><div class="stat-l">Clientes recorrentes</div><div class="stat-v" id="s-rec">…</div><div class="stat-s" id="s-rec-s"></div></div>
  <div class="stat"><div class="stat-l">Top 10 clientes</div><div class="stat-v" id="s-top">…</div><div class="stat-s" id="s-top-s"></div></div>
</div>

<div class="controls">
  <div class="search"><input type="text" id="searchInput" placeholder="Pesquisar por nome ou email…" oninput="applyFilters()"></div>
  <button class="fbtn on" onclick="setFilter('all',this)">Todos</button>
  <button class="fbtn" onclick="setFilter('multi',this)">Recorrentes (2+)</button>
  <button class="fbtn" onclick="setFilter('member',this)">Registados</button>
  <button class="fbtn" onclick="setFilter('guest',this)">Guests</button>
  <button class="fbtn" onclick="setFilter('recent',this)">Activos (30d)</button>

  <div class="date-filter" id="dateFilter">
    <span class="date-filter-label">Última compra</span>
    <span class="date-filter-sep">·</span>
    <span class="date-filter-label">De</span>
    <input type="date" id="dateFrom" oninput="applyFilters()" onchange="applyFilters()">
    <span class="date-filter-sep">—</span>
    <span class="date-filter-label">Até</span>
    <input type="date" id="dateTo" oninput="applyFilters()" onchange="applyFilters()">
    <button class="date-reset" id="dateResetBtn" onclick="resetDateFilter()" title="Limpar datas" style="display:none">✕</button>
  </div>

  <span class="cnt" id="cnt">A carregar…</span>
  <div style="display:flex;gap:6px;margin-left:auto;">
    <button class="fbtn export-btn" onclick="exportCSV()" title="Exporta os clientes visíveis para CSV">⬇ Exportar CSV</button>
  </div>
</div>

<div class="tbl-wrap">
  <div id="loadingMsg" style="text-align:center;padding:60px;color:var(--muted);">
    <div class="spin" style="font-size:2rem">⟳</div>
    <div style="margin-top:12px;font-size:.9rem">A carregar clientes…</div>
  </div>
  <table id="tbl" style="display:none">
    <thead><tr>
      <th onclick="sortTbl(0)">#</th>
      <th onclick="sortTbl(1)">Cliente</th>
      <th onclick="sortTbl(2)">Enc.</th>
      <th onclick="sortTbl(3)" class="sorted">Total Gasto ↓</th>
      <th onclick="sortTbl(4)">Última Compra</th>
      <th>Produto Principal</th>
    </tr></thead>
    <tbody id="tbody"></tbody>
  </table>
</div>

</div><!-- /tab-clientes -->

<!-- ═══════════════════════════════════════════════ TAB: MATRIZ RFV ═══ -->
<div id="tab-rfv" style="display:none">

<div class="stats-4">
  <div class="stat"><div class="stat-l">Total Clientes</div><div class="stat-v" id="rfv-s-total">{total_customers:,}</div><div class="stat-s">com encomendas válidas</div></div>
  <div class="stat"><div class="stat-l">Champions + Fiéis</div><div class="stat-v" id="rfv-s-champ">—</div><div class="stat-s" id="rfv-s-champ-s">calculando…</div></div>
  <div class="stat"><div class="stat-l">Em Risco + Não Perder</div><div class="stat-v" id="rfv-s-risk">—</div><div class="stat-s">reactivar urgente</div></div>
  <div class="stat"><div class="stat-l">Receita Champions</div><div class="stat-v" id="rfv-s-rev">—</div><div class="stat-s">segmento topo</div></div>
</div>

<div class="rfv-main">
  <div class="matrix-section">
    <div class="rfv-section-title">Matriz RFV 5×5</div>
    <div class="matrix-and-guide">

      <!-- Matriz + legenda -->
      <div class="matrix-left">
        <div class="matrix-wrap">
          <div style="display:flex;flex-direction:column;align-items:center;padding-top:28px;padding-bottom:10px;padding-right:4px;">
            <div class="matrix-y-title">Frequência (F) →</div>
          </div>
          <div class="matrix-y-labels">
            <div class="matrix-y-label">F=5 (Alta)</div>
            <div class="matrix-y-label">F=4</div>
            <div class="matrix-y-label">F=3</div>
            <div class="matrix-y-label">F=2</div>
            <div class="matrix-y-label">F=1 (Baixa)</div>
          </div>
          <div>
            <div class="matrix-grid" id="matrixGrid"></div>
            <div class="matrix-x-labels">
              <div class="matrix-x-label">R=1 (Antiga)</div>
              <div class="matrix-x-label">R=2</div>
              <div class="matrix-x-label">R=3</div>
              <div class="matrix-x-label">R=4</div>
              <div class="matrix-x-label">R=5 (Recente)</div>
            </div>
            <div class="matrix-x-title">← Recência (R)</div>
          </div>
        </div>
        <div id="matrixLegend"></div>
      </div>

      <!-- Painel de explicação -->
      <div class="rfv-guide">
        <div class="guide-title">📖 Guia de Leitura — Como funciona o RFV</div>

        <div class="guide-inner">

          <!-- Coluna esquerda: R, F, V -->
          <div class="guide-col">

            <!-- R -->
            <div class="guide-dim">
              <div class="guide-dim-header">
                <span class="guide-dim-badge" style="background:#1a3a5c;color:#5b9bd5;">R</span>
                <span class="guide-dim-label">Recência</span>
                <span class="guide-dim-sub">— dias desde a última compra</span>
              </div>
              <table class="guide-table">
                <tr><td class="guide-score" style="color:#4caf89;">R=5</td><td class="guide-range">0–30 dias</td><td class="guide-desc">Comprou este mês</td></tr>
                <tr><td class="guide-score" style="color:#7ec8a4;">R=4</td><td class="guide-range">31–90 dias</td><td class="guide-desc">Comprou este trimestre</td></tr>
                <tr><td class="guide-score" style="color:#f0a732;">R=3</td><td class="guide-range">91–180 dias</td><td class="guide-desc">Comprou neste semestre</td></tr>
                <tr><td class="guide-score" style="color:#e07054;">R=2</td><td class="guide-range">181–365 dias</td><td class="guide-desc">Comprou este ano</td></tr>
                <tr><td class="guide-score" style="color:#e05454;">R=1</td><td class="guide-range">&gt;365 dias</td><td class="guide-desc">Inativo há +1 ano</td></tr>
              </table>
            </div>

            <!-- F -->
            <div class="guide-dim">
              <div class="guide-dim-header">
                <span class="guide-dim-badge" style="background:#1a3d2a;color:#4caf89;">F</span>
                <span class="guide-dim-label">Frequência</span>
                <span class="guide-dim-sub">— nº total de encomendas</span>
              </div>
              <table class="guide-table">
                <tr><td class="guide-score" style="color:#e8c98a;">F=5</td><td class="guide-range">10+ encomendas</td><td class="guide-desc">Muito fiel</td></tr>
                <tr><td class="guide-score" style="color:#c9a96e;">F=4</td><td class="guide-range">5–9 encomendas</td><td class="guide-desc">Frequente</td></tr>
                <tr><td class="guide-score" style="color:#a88a52;">F=3</td><td class="guide-range">3–4 encomendas</td><td class="guide-desc">Recorrente</td></tr>
                <tr><td class="guide-score" style="color:#888;">F=2</td><td class="guide-range">2 encomendas</td><td class="guide-desc">Comprou 2 vezes</td></tr>
                <tr><td class="guide-score" style="color:#555;">F=1</td><td class="guide-range">1 encomenda</td><td class="guide-desc">Comprou 1 vez</td></tr>
              </table>
            </div>

            <!-- V -->
            <div class="guide-dim" style="margin-bottom:0;">
              <div class="guide-dim-header">
                <span class="guide-dim-badge" style="background:#3a2e1a;color:#e8c98a;">V</span>
                <span class="guide-dim-label">Valor</span>
                <span class="guide-dim-sub">— total gasto na loja</span>
              </div>
              <table class="guide-table">
                <tr><td class="guide-score" style="color:#e8c98a;">V=5</td><td class="guide-range">≥ 224€</td><td class="guide-desc">Top 20%</td></tr>
                <tr><td class="guide-score" style="color:#c9a96e;">V=4</td><td class="guide-range">107–224€</td><td class="guide-desc">Acima da média</td></tr>
                <tr><td class="guide-score" style="color:#a88a52;">V=3</td><td class="guide-range">70–107€</td><td class="guide-desc">Valor médio</td></tr>
                <tr><td class="guide-score" style="color:#888;">V=2</td><td class="guide-range">45–70€</td><td class="guide-desc">Abaixo da média</td></tr>
                <tr><td class="guide-score" style="color:#555;">V=1</td><td class="guide-range">&lt; 45€</td><td class="guide-desc">Valor baixo</td></tr>
              </table>
              <div style="font-size:.65rem;color:var(--muted);margin-top:5px;">⚠ Breakpoints do V recalculam com novos clientes.</div>
            </div>

          </div><!-- /guide-col -->

          <!-- Coluna direita: Segmentos -->
          <div class="guide-col">
            <div class="guide-dim" style="margin-bottom:0;">
              <div class="guide-dim-header">
                <span class="guide-dim-badge" style="background:#2a2a2a;color:#e8e8e8;">F×R</span>
                <span class="guide-dim-label">Segmentos</span>
              </div>
              <table class="guide-seg-table">
                <tr><td>🏆</td><td style="color:#e8c98a;font-weight:700;">Champions</td><td class="guide-range" style="color:var(--muted);">F≥4 + R≥4</td><td style="color:var(--muted);font-size:.7rem;">Compram muito e estão ativos</td></tr>
                <tr><td>💚</td><td style="color:#4caf89;font-weight:700;">Fiéis</td><td class="guide-range" style="color:var(--muted);">F≥3 + R≥3</td><td style="color:var(--muted);font-size:.7rem;">Regularidade alta</td></tr>
                <tr><td>⭐</td><td style="color:#5b9bd5;font-weight:700;">Potenciais</td><td class="guide-range" style="color:var(--muted);">F=3 + R≥4</td><td style="color:var(--muted);font-size:.7rem;">A ganhar hábito</td></tr>
                <tr><td>🆕</td><td style="color:#7ec8a4;font-weight:700;">Novos</td><td class="guide-range" style="color:var(--muted);">F=1 + R≥4</td><td style="color:var(--muted);font-size:.7rem;">1ª compra recente</td></tr>
                <tr><td>🌱</td><td style="color:#a8c8ff;font-weight:700;">Promissores</td><td class="guide-range" style="color:var(--muted);">F≤2 + R=3</td><td style="color:var(--muted);font-size:.7rem;">Algum interesse</td></tr>
                <tr><td>⚠️</td><td style="color:#f0a732;font-weight:700;">Atenção</td><td class="guide-range" style="color:var(--muted);">F=3 + R≤3</td><td style="color:var(--muted);font-size:.7rem;">A afastar-se</td></tr>
                <tr><td>🔴</td><td style="color:#e07054;font-weight:700;">Em Risco</td><td class="guide-range" style="color:var(--muted);">F≥4 + R=2</td><td style="color:var(--muted);font-size:.7rem;">Inativos 6–12 meses</td></tr>
                <tr><td>🚨</td><td style="color:#c94b4b;font-weight:700;">Não Perder</td><td class="guide-range" style="color:var(--muted);">F≥4 + R=1</td><td style="color:var(--muted);font-size:.7rem;">Grandes compradores perdidos</td></tr>
                <tr><td>😴</td><td style="color:#666;font-weight:700;">A Hibernar</td><td class="guide-range" style="color:var(--muted);">F=2–3 + R≤2</td><td style="color:var(--muted);font-size:.7rem;">Pouco frequentes + inativos</td></tr>
                <tr><td>💀</td><td style="color:#444;font-weight:700;">Perdidos</td><td class="guide-range" style="color:var(--muted);">F=1–2 + R≤2</td><td style="color:var(--muted);font-size:.7rem;">1–2 compras, muito antigos</td></tr>
              </table>

              <div class="guide-formula">
                <strong style="color:var(--accent);">Score total</strong> = R + F + V &nbsp;(3 a 15 pontos)<br>
                <strong style="color:var(--accent);">Segmento</strong> = F × R (V não altera o segmento)<br>
                <strong style="color:var(--accent);">Válidas:</strong> complete · processing · closed
              </div>
            </div>
          </div><!-- /guide-col -->

        </div><!-- /guide-inner -->
      </div>

    </div>
  </div>
  <div class="rfv-section-title">Segmentos</div>
  <div class="seg-cards" id="segCards"></div>
  <div class="rfv-section-title">Clientes por Segmento</div>
  <div class="rfv-controls">
    <div class="rfv-search"><input type="text" id="rfv-searchInput" placeholder="Pesquisar por nome ou email…" oninput="rfvApplyFilters()"></div>
    <button class="fbtn on" id="rfv-btn-all" onclick="clearSegFilter(this)">Todos</button>
    <span class="cnt" id="rfv-cnt">A carregar…</span>
    <div style="margin-left:auto;">
      <button class="fbtn export-btn" onclick="rfvExportCSV()">⬇ Exportar CSV RFV</button>
    </div>
  </div>
  <div class="rfv-tbl-wrap">
    <div id="rfv-loadingMsg" style="text-align:center;padding:60px;color:var(--muted);">
      <div class="spin" style="font-size:2rem">⟳</div>
      <div style="margin-top:12px;font-size:.9rem">A carregar clientes…</div>
    </div>
    <table id="rfv-tbl" style="display:none">
      <thead><tr>
        <th>#</th><th>Cliente</th><th>R 🔵  F 🟢  V 🟡</th>
        <th>Score</th><th>Total Gasto</th><th>Última Compra</th><th>Segmento</th>
      </tr></thead>
      <tbody id="rfv-tbody"></tbody>
    </table>
  </div>
</div>

</div><!-- /tab-rfv -->

<!-- ═══════════════════════════════════════════════ TAB: PONTOS ════ -->
<div id="tab-pontos" style="display:none">
  <div class="stats-4" id="pontos-stats" style="padding:24px 28px 0">
    <div class="stat"><div class="stat-l">Clientes com pontos</div><div class="stat-v" id="pontos-s-total">…</div></div>
    <div class="stat"><div class="stat-l">Pontos em circulação</div><div class="stat-v" id="pontos-s-balance">…</div></div>
    <div class="stat"><div class="stat-l">Média por cliente</div><div class="stat-v" id="pontos-s-avg">…</div></div>
    <div class="stat"><div class="stat-l">Pts de compras</div><div class="stat-v" id="pontos-s-earned">…</div></div>
  </div>
  <div style="padding:16px 28px 8px;display:flex;gap:10px;align-items:center">
    <input id="pontos-search" type="search" placeholder="Pesquisar cliente…" oninput="pontosApplyFilter()" style="padding:8px 14px;background:#1a1a1a;border:1px solid #2e2e2e;border-radius:6px;color:#e0e0e0;font-size:.82rem;width:240px;">
    <span id="pontos-cnt" style="color:#666;font-size:.8rem;margin-left:4px"></span>
  </div>
  <div style="padding:0 28px 32px;overflow-x:auto">
    <div id="pontos-loadingMsg" style="color:#666;padding:40px 0;text-align:center">A carregar pontos…</div>
    <table id="pontos-tbl" style="display:none;width:100%;border-collapse:collapse;font-size:.82rem">
      <thead>
        <tr style="border-bottom:1px solid #2e2e2e;color:#888">
          <th style="padding:10px 8px;text-align:left;width:36px">#</th>
          <th onclick="pontosSortTbl(1)" style="padding:10px 8px;text-align:left;cursor:pointer">Cliente</th>
          <th onclick="pontosSortTbl(2)" id="pontos-sort-2" style="padding:10px 8px;text-align:right;cursor:pointer;color:var(--gold)">Pontos Disponíveis ↓</th>
          <th onclick="pontosSortTbl(3)" style="padding:10px 8px;text-align:right;cursor:pointer" title="Pontos disponíveis + pontos já usados = total alguma vez recebido">Total Recebido</th>
          <th onclick="pontosSortTbl(4)" style="padding:10px 8px;text-align:right;cursor:pointer" title="Pontos ganhos apenas através de compras online">Pts de Compras</th>
          <th onclick="pontosSortTbl(5)" style="padding:10px 8px;text-align:right;cursor:pointer">Pontos Usados</th>
          <th onclick="pontosSortTbl(6)" style="padding:10px 8px;text-align:right;cursor:pointer" title="Apenas vendas online (Magento). Compras em loja física não incluídas.">Gasto Online</th>
          <th onclick="pontosSortTbl(7)" style="padding:10px 8px;text-align:right;cursor:pointer">Encomendas</th>
          <th onclick="pontosSortTbl(8)" style="padding:10px 8px;text-align:right;cursor:pointer">Última Compra</th>
          <th onclick="pontosSortTbl(9)" style="padding:10px 8px;text-align:left;cursor:pointer">Cidade</th>
        </tr>
      </thead>
      <tbody id="pontos-tbody"></tbody>
    </table>
  </div>
</div><!-- /tab-pontos -->

{lojas_tab}

<!-- Profile Modal -->
<div class="overlay" id="overlay" onclick="closeProfile(event)">
  <div class="drawer" id="drawer">
    <div class="drawer-header">
      <div class="drawer-avatar" id="dAvatar"></div>
      <div class="drawer-title">
        <div class="drawer-name" id="dName"></div>
        <div class="drawer-email" id="dEmail"></div>
        <div class="drawer-badges" id="dBadges"></div>
      </div>
      <button class="drawer-close" onclick="closeProfile()">✕</button>
    </div>
    <div class="drawer-body" id="drawerBody"></div>
  </div>
</div>

<script>
const STATS = {stats_json};
const STATUS_COLORS = {status_colors_json};
const STATUS_LABELS = {status_labels_json};
const MATRIX_DATA = {matrix_json};
const SEGMENTS_META = {segments_meta_json};
const SEG_TABLE = {seg_table_js};
let CUSTOMERS = [];
let RFV_CUSTOMERS = [];
let rfvLoaded = false;
let activeFilter = 'all';
let activeSegment = null;

// ── Inicialização ─────────────────────────────────────────────────────────────
(function init() {{
  const fmtN = n => n.toLocaleString('pt-PT');
  document.getElementById('s-cu').textContent  = fmtN(STATS.total_customers);
  document.getElementById('s-rev').textContent = fmtN(STATS.total_revenue)+'€';
  document.getElementById('s-ord').textContent = fmtN(STATS.total_orders);
  document.getElementById('s-avg').textContent = STATS.avg_order.toFixed(2)+'€';
  document.getElementById('s-rec').textContent = fmtN(STATS.recurring);
  document.getElementById('s-rec-s').textContent = STATS.recurring_pct+'% do total';
  document.getElementById('s-top').textContent = fmtN(STATS.top10_revenue)+'€';
  document.getElementById('s-top-s').textContent = STATS.top10_pct+'% da receita';
  document.getElementById('genDate').textContent = 'Gerado em '+STATS.generated_at+' · '+fmtN(STATS.total_customers)+' clientes';

  fetch('/api/crm/lite')
    .then(r => r.json())
    .then(data => {{
      CUSTOMERS = data;
      renderTable(data);
      document.getElementById('loadingMsg').style.display = 'none';
      document.getElementById('tbl').style.display = '';
      document.getElementById('cnt').textContent = data.length + ' clientes';
    }})
    .catch(() => {{
      document.getElementById('loadingMsg').innerHTML = '<div style="color:var(--red)">Erro ao carregar dados.<br>Verifica se o servidor está a correr em localhost:5001</div>';
    }});

  // Garante que os inputs de data disparam o filtro em qualquer browser
  ['dateFrom','dateTo'].forEach(id => {{
    const el = document.getElementById(id);
    if (el) {{
      el.addEventListener('change', applyFilters);
      el.addEventListener('input',  applyFilters);
    }}
  }});
}})();

// ── Tab Switching ─────────────────────────────────────────────────────────────
function switchTab(tab, btn) {{
  ['clientes','rfv','pontos','lojas'].forEach(t => {{
    const el = document.getElementById('tab-'+t);
    if (el) el.style.display = (t === tab) ? '' : 'none';
  }});
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  if (tab === 'rfv' && !rfvLoaded) loadRFV();
  if (tab === 'pontos' && !pontosLoaded) loadPontos();
  if (tab === 'lojas') {{
    const f = document.getElementById('lojasFrame');
    if (f && !f.src) f.src = '/crm-lojas?embed=1';   // lazy-load na 1ª abertura
  }}
}}

// ── Pontos: globals ───────────────────────────────────────────────────────────
let PONTOS_ALL = [];
let pontos_filtered = [];
let pontosLoaded = false;
let pontosSortCol = 2;
let pontosSortAsc = false;

// ── Pontos: carregamento ──────────────────────────────────────────────────────
function loadPontos() {{
  fetch('/api/crm/pontos')
    .then(r => r.json())
    .then(data => {{
      if (data.error) throw new Error(data.error);
      PONTOS_ALL = data;
      pontosLoaded = true;
      const fmtN = n => n.toLocaleString('pt-PT');
      const totalBalance = data.reduce((s,c) => s + (c.point_balance||0), 0);
      const totalEarned  = data.reduce((s,c) => s + (c.point_earned||0), 0);
      document.getElementById('pontos-s-total').textContent   = fmtN(data.length);
      document.getElementById('pontos-s-balance').textContent = fmtN(totalBalance);
      document.getElementById('pontos-s-avg').textContent     = data.length ? fmtN(Math.round(totalBalance/data.length)) : '0';
      document.getElementById('pontos-s-earned').textContent  = fmtN(totalEarned);
      pontosApplyFilter();
      document.getElementById('pontos-loadingMsg').style.display = 'none';
      document.getElementById('pontos-tbl').style.display = '';
    }})
    .catch(e => {{
      document.getElementById('pontos-loadingMsg').innerHTML = '<div style="color:var(--red)">Erro ao carregar pontos: '+e.message+'</div>';
    }});
}}

function pontosSortTbl(col) {{
  if (pontosSortCol === col) {{ pontosSortAsc = !pontosSortAsc; }}
  else {{ pontosSortCol = col; pontosSortAsc = col === 1 || col === 9 || col === 8; }}
  pontosRenderTable(pontos_filtered);
}}

function pontosApplyFilter() {{
  const q = (document.getElementById('pontos-search').value || '').toLowerCase();
  pontos_filtered = q ? PONTOS_ALL.filter(c =>
    (c.name||'').toLowerCase().includes(q) ||
    (c.email||'').toLowerCase().includes(q) ||
    (c.city||'').toLowerCase().includes(q)
  ) : PONTOS_ALL.slice();
  document.getElementById('pontos-cnt').textContent = pontos_filtered.length + ' clientes';
  pontosRenderTable(pontos_filtered);
}}

function pontosRenderTable(data) {{
  const sorted = data.slice().sort((a, b) => {{
    let va, vb;
    switch(pontosSortCol) {{
      case 1: va = (a.name||'').toLowerCase(); vb = (b.name||'').toLowerCase(); break;
      case 2: va = a.point_balance||0; vb = b.point_balance||0; break;
      case 3: va = (a.point_balance||0)+(a.point_spent||0); vb = (b.point_balance||0)+(b.point_spent||0); break;
      case 4: va = a.point_earned||0; vb = b.point_earned||0; break;
      case 5: va = a.point_spent||0; vb = b.point_spent||0; break;
      case 6: va = a.total_spent||0; vb = b.total_spent||0; break;
      case 7: va = a.orders||0; vb = b.orders||0; break;
      case 8: va = a.last_order||''; vb = b.last_order||''; break;
      case 9: va = (a.city||'').toLowerCase(); vb = (b.city||'').toLowerCase(); break;
      default: va = 0; vb = 0;
    }}
    if (va < vb) return pontosSortAsc ? -1 : 1;
    if (va > vb) return pontosSortAsc ? 1 : -1;
    return 0;
  }});
  const fmtN = n => n.toLocaleString('pt-PT');
  const rows = sorted.map((c, i) => {{
    const totalReceived = (c.point_balance||0) + (c.point_spent||0);
    return `<tr style="border-bottom:1px solid #1e1e1e">
      <td style="padding:9px 8px;color:#555">${{i+1}}</td>
      <td style="padding:9px 8px">
        <div style="font-weight:600;color:#e0e0e0">${{c.name||'—'}}</div>
        <div style="color:#555;font-size:.77rem">${{c.email||''}}</div>
      </td>
      <td style="padding:9px 8px;text-align:right;color:var(--gold);font-weight:700">${{fmtN(c.point_balance||0)}}</td>
      <td style="padding:9px 8px;text-align:right;color:#a0c0e0">${{fmtN(totalReceived)}}</td>
      <td style="padding:9px 8px;text-align:right;color:#888">${{fmtN(c.point_earned||0)}}</td>
      <td style="padding:9px 8px;text-align:right;color:#888">${{fmtN(c.point_spent||0)}}</td>
      <td style="padding:9px 8px;text-align:right">${{(c.total_spent||0).toFixed(2)}}€</td>
      <td style="padding:9px 8px;text-align:right">${{c.orders||0}}</td>
      <td style="padding:9px 8px;text-align:right;color:#666">${{c.last_order||'—'}}</td>
      <td style="padding:9px 8px;color:#888">${{c.city||'—'}}</td>
    </tr>`;
  }}).join('');
  document.getElementById('pontos-tbody').innerHTML = rows;
  document.getElementById('pontos-cnt').textContent = sorted.length + ' clientes';
}}

// ── RFV: Carregamento lazy ────────────────────────────────────────────────────
function loadRFV() {{
  buildMatrix();
  fetch('/api/crm/rfv')
    .then(r => r.json())
    .then(data => {{
      RFV_CUSTOMERS = data;
      rfvLoaded = true;
      buildSegCards(data);
      rfvRenderTable(data);
      document.getElementById('rfv-loadingMsg').style.display = 'none';
      document.getElementById('rfv-tbl').style.display = '';
      document.getElementById('rfv-cnt').textContent = data.length + ' clientes';
      const fmtN = n => n.toLocaleString('pt-PT');
      const segCounts = {{}}, segRevenue = {{}};
      data.forEach(c => {{
        const s = c.rfv_segment || 'lost';
        segCounts[s]  = (segCounts[s]||0) + 1;
        segRevenue[s] = (segRevenue[s]||0) + c.total_spent;
      }});
      const champCount = (segCounts.champions||0) + (segCounts.loyal||0);
      const riskCount  = (segCounts.at_risk||0)   + (segCounts.cant_lose||0);
      const champPct   = data.length ? (champCount/data.length*100).toFixed(1) : 0;
      const champRev   = Math.round(segRevenue.champions||0);
      document.getElementById('rfv-s-total').textContent = fmtN(data.length);
      document.getElementById('rfv-s-champ').textContent = fmtN(champCount);
      document.getElementById('rfv-s-champ-s').textContent = champPct + '% do total';
      document.getElementById('rfv-s-risk').textContent  = fmtN(riskCount);
      document.getElementById('rfv-s-rev').textContent   = fmtN(champRev) + '€';
    }})
    .catch(() => {{
      document.getElementById('rfv-loadingMsg').innerHTML = '<div style="color:var(--red)">Erro ao carregar dados RFV.</div>';
    }});
}}

// ── RFV: Matriz ───────────────────────────────────────────────────────────────
function buildMatrix() {{
  const grid = document.getElementById('matrixGrid');

  const ANCHORS = {{
    champions:   {{f:5, r:5}},
    loyal:       {{f:4, r:3}},
    cant_lose:   {{f:5, r:1}},
    at_risk:     {{f:5, r:2}},
    potential:   {{f:3, r:5}},
    attention:   {{f:3, r:2}},
    hibernating: {{f:2, r:2}},
    promising:   {{f:2, r:3}},
    new:         {{f:1, r:5}},
    lost:        {{f:1, r:1}},
  }};

  const total = Object.values(MATRIX_DATA).reduce((a,b) => a+b, 0);
  const segCounts = {{}};
  for (const [key, count] of Object.entries(MATRIX_DATA)) {{
    const seg = SEG_TABLE[key] || 'lost';
    segCounts[seg] = (segCounts[seg]||0) + count;
  }}

  let html = '';
  for (let f = 5; f >= 1; f--) {{
    for (let r = 1; r <= 5; r++) {{
      const seg   = SEG_TABLE[f+'_'+r] || 'lost';
      const meta  = SEGMENTS_META[seg] || {{}};
      const color = meta.color || '#333';

      const getSeg = (ff, rr) => (ff>=1&&ff<=5&&rr>=1&&rr<=5) ? (SEG_TABLE[ff+'_'+rr]||'lost') : null;
      const sameTop    = getSeg(f+1, r) === seg;
      const sameRight  = getSeg(f,   r+1) === seg;
      const sameBottom = getSeg(f-1, r) === seg;
      const sameLeft   = getSeg(f,   r-1) === seg;

      const bT = sameTop    ? 'transparent' : color;
      const bR = sameRight  ? 'transparent' : color;
      const bB = sameBottom ? 'transparent' : color;
      const bL = sameLeft   ? 'transparent' : color;

      const isAnchor = ANCHORS[seg] && ANCHORS[seg].f === f && ANCHORS[seg].r === r;
      const count    = segCounts[seg] || 0;
      const pct      = total > 0 ? (count / total * 100).toFixed(1) : '0.0';

      const label = isAnchor ? `
        <div style="font-size:.6rem;font-weight:700;color:${{color}};line-height:1.3;margin-bottom:2px;">${{meta.icon||''}} ${{meta.name||seg}}</div>
        <div style="font-size:1.05rem;font-weight:800;color:${{color}};line-height:1;">${{pct}}%</div>
        <div style="font-size:.58rem;color:${{color}}99;margin-top:2px;">${{count.toLocaleString('pt-PT')}} clientes</div>
      ` : '';

      html += `<div style="
          background:${{color}}30;
          border-top:2px solid ${{bT}};
          border-right:2px solid ${{bR}};
          border-bottom:2px solid ${{bB}};
          border-left:2px solid ${{bL}};
          display:flex;flex-direction:column;align-items:center;justify-content:center;
          text-align:center;padding:4px;box-sizing:border-box;cursor:pointer;
          transition:filter .15s;
        "
        onmouseover="this.style.filter='brightness(1.25)'"
        onmouseout="this.style.filter=''"
        onclick="filterBySeg('${{seg}}')"
        title="${{meta.name||seg}}: ${{count}} clientes (${{pct}}%)"
      >${{label}}</div>`;
    }}
  }}
  grid.innerHTML = html;

  const legend = document.getElementById('matrixLegend');
  const segsOrdered = ['champions','loyal','potential','new','promising','attention','at_risk','cant_lose','hibernating','lost'];
  let lhtml = '<div style="display:flex;flex-direction:column;gap:5px;">';
  segsOrdered.forEach(seg => {{
    const meta  = SEGMENTS_META[seg] || {{}};
    const color = meta.color || '#333';
    const count = segCounts[seg] || 0;
    const pct   = total > 0 ? (count/total*100).toFixed(1) : '0.0';
    lhtml += `<div style="display:flex;align-items:center;gap:8px;font-size:.76rem;cursor:pointer;padding:4px 6px;border-radius:5px;transition:background .1s;"
        onmouseover="this.style.background='${{color}}18'" onmouseout="this.style.background=''"
        onclick="filterBySeg('${{seg}}')">
      <div style="width:10px;height:10px;border-radius:2px;background:${{color}};flex-shrink:0;"></div>
      <span style="color:${{color}};font-weight:700;white-space:nowrap;">${{meta.icon||''}} ${{meta.name||seg}}</span>
      <span style="color:var(--muted);font-size:.7rem;white-space:nowrap;">${{pct}}% · ${{count.toLocaleString('pt-PT')}}</span>
      <span style="color:var(--muted);font-size:.68rem;font-style:italic;">— ${{meta.desc||''}}</span>
    </div>`;
  }});
  lhtml += '</div>';
  legend.innerHTML = lhtml;
}}

// ── RFV: Cards de Segmentos ───────────────────────────────────────────────────
function buildSegCards(data) {{
  const container = document.getElementById('segCards');
  const segOrder = ['champions','loyal','potential','new','promising','attention','at_risk','cant_lose','hibernating','lost'];
  const segCounts = {{}}, segRevenue = {{}}, totalRev = data.reduce((s,c)=>s+c.total_spent,0);
  data.forEach(c => {{
    const s = c.rfv_segment||'lost';
    segCounts[s]  = (segCounts[s]||0) + 1;
    segRevenue[s] = (segRevenue[s]||0) + c.total_spent;
  }});
  let html = '';
  segOrder.forEach(seg => {{
    const meta  = SEGMENTS_META[seg] || {{}};
    const color = meta.color || '#333';
    const count = segCounts[seg] || 0;
    const rev   = segRevenue[seg] || 0;
    const revPct = totalRev > 0 ? (rev/totalRev*100).toFixed(1) : '0';
    html += `<div class="seg-card" id="card_${{seg}}" style="--card-color:${{color}}" onclick="filterBySeg('${{seg}}')">
      <div class="seg-icon">${{meta.icon||''}}</div>
      <div class="seg-name" style="color:${{color}}">${{meta.name||seg}}</div>
      <div class="seg-count">${{count.toLocaleString('pt-PT')}}</div>
      <div class="seg-rev">${{Math.round(rev).toLocaleString('pt-PT')}}€</div>
      <span class="seg-pct" style="background:${{color}}22;color:${{color}}">${{revPct}}% receita</span>
    </div>`;
  }});
  container.innerHTML = html;
}}

// ── RFV: Tabela ───────────────────────────────────────────────────────────────
function rfvRenderTable(data) {{
  const tbody = document.getElementById('rfv-tbody');
  const html = data.map((c, idx) => {{
    const days = c.days_since;
    let daysCls = 'days-cold', daysTxt = '—';
    if (typeof days === 'number') {{
      daysTxt = days === 0 ? 'Hoje' : days === 1 ? 'Ontem' : days+'d atrás';
      daysCls = days <= 30 ? 'days-hot' : days <= 90 ? 'days-warm' : 'days-cold';
    }}
    const seg   = c.rfv_segment || 'lost';
    const meta  = SEGMENTS_META[seg] || {{}};
    const color = meta.color || '#555';
    const r = c.rfv_r||1, f = c.rfv_f||1, v = c.rfv_v||1;
    return `<tr data-seg="${{seg}}" data-email="${{c.email}}" data-name="${{(c.name||'').toLowerCase()}}" data-score="${{c.rfv_score||0}}">
      <td style="color:var(--muted);font-size:.85rem">${{idx+1}}</td>
      <td>
        <div style="font-weight:600">${{c.name||c.email}}</div>
        <div style="font-size:.75rem;color:var(--muted)">${{c.email}}</div>
        ${{c.city ? `<div style="font-size:.7rem;color:var(--muted)">📍 ${{c.city}}</div>` : ''}}
      </td>
      <td><span class="rfv-badge r-badge">${{r}}</span> <span class="rfv-badge f-badge">${{f}}</span> <span class="rfv-badge v-badge">${{v}}</span></td>
      <td><span class="score-badge">${{c.rfv_score||0}}/15</span></td>
      <td>
        <div class="gold">${{c.total_spent.toLocaleString('pt-PT',{{minimumFractionDigits:2,maximumFractionDigits:2}})}}€</div>
        <div class="sub">${{c.total_orders}} enc.</div>
      </td>
      <td><span class="${{daysCls}}">${{daysTxt}}</span><div class="sub">${{c.last_order||''}}</div></td>
      <td><span class="seg-pill" style="background:${{color}}22;color:${{color}}">${{meta.icon||''}} ${{meta.name||seg}}</span></td>
    </tr>`;
  }}).join('');
  tbody.innerHTML = html;
}}

function rfvApplyFilters() {{
  const q = document.getElementById('rfv-searchInput').value.toLowerCase();
  const rows = document.querySelectorAll('#rfv-tbody tr');
  let visible = 0;
  rows.forEach(row => {{
    const email = row.dataset.email||'';
    const name  = row.dataset.name||'';
    const seg   = row.dataset.seg||'';
    const matchQ   = !q || email.includes(q) || name.includes(q);
    const matchSeg = !activeSegment || seg === activeSegment;
    const show = matchQ && matchSeg;
    row.classList.toggle('hidden', !show);
    if (show) visible++;
  }});
  document.getElementById('rfv-cnt').textContent = visible+' cliente'+(visible!==1?'s':'');
}}

function filterBySeg(seg) {{
  if (activeSegment === seg) {{
    activeSegment = null;
    document.querySelectorAll('.seg-card').forEach(c => c.classList.remove('active'));
  }} else {{
    activeSegment = seg;
    document.querySelectorAll('.seg-card').forEach(c => c.classList.toggle('active', c.id==='card_'+seg));
  }}
  rfvApplyFilters();
}}

function clearSegFilter() {{
  activeSegment = null;
  document.querySelectorAll('.seg-card').forEach(c => c.classList.remove('active'));
  rfvApplyFilters();
}}

function rfvExportCSV() {{
  const rows = [...document.querySelectorAll('#rfv-tbody tr:not(.hidden)')];
  const headers = ['email','name','rfv_r','rfv_f','rfv_v','rfv_score','rfv_segment','total_orders','total_spent','last_order','days_since','city'];
  const lines = [headers];
  rows.forEach(row => {{
    const email = row.dataset.email;
    const c = RFV_CUSTOMERS.find(x => x.email === email);
    if (!c) return;
    lines.push([
      c.email, c.name||'', c.rfv_r, c.rfv_f, c.rfv_v, c.rfv_score, c.rfv_segment,
      c.total_orders, c.total_spent.toFixed(2), c.last_order||'',
      typeof c.days_since==='number'?c.days_since:'', c.city||''
    ].map(v => {{ const s=String(v??''); return s.includes(',')||s.includes('"')?'"'+s.replace(/"/g,'""')+'"':s; }}));
  }});
  const csv = '\\uFEFF'+lines.map(r=>r.join(',')).join('\\r\\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv],{{type:'text/csv;charset=utf-8;'}}));
  const d = new Date();
  a.download = `cavemen_rfv_${{d.getFullYear()}}-${{String(d.getMonth()+1).padStart(2,'0')}}-${{String(d.getDate()).padStart(2,'0')}}.csv`;
  a.click();
}}

function renderTable(data) {{
  const maxSpent = data.length ? data[0].total_spent : 1;
  const tbody = document.getElementById('tbody');
  const html = data.map((c, idx) => {{
    const barW = Math.min(100, (c.total_spent / maxSpent) * 100).toFixed(1);
    const isGuest = c.is_guest;
    const badge = isGuest ? '<span class="badge guest">Guest</span>' : '<span class="badge member">Registado</span>';
    const loc = [c.city, c.region].filter(Boolean).join(', ');
    const days = c.days_since;
    let daysCls = 'days-cold', daysTxt = '—';
    if (typeof days === 'number') {{
      daysTxt = days === 0 ? 'Hoje' : days === 1 ? 'Ontem' : days+'d atrás';
      daysCls = days <= 30 ? 'days-hot' : days <= 90 ? 'days-warm' : 'days-cold';
    }}
    const topProd = (c.top_product||'—').substring(0,40) + ((c.top_product||'').length > 40 ? '…' : '');
    const rank = idx + 1;
    return `<tr class="customer-row" data-rank="${{rank}}" data-email="${{c.email}}" data-name="${{(c.name||'').toLowerCase()}}" data-orders="${{c.total_orders}}" data-guest="${{isGuest}}" data-days="${{typeof days==='number'?days:9999}}" data-last-order="${{c.last_order||''}}" onclick="openProfile(${{idx}})">
      <td class="td-rank${{rank<=3?' rank-gold':''}}">#${{rank}}</td>
      <td class="td-customer">
        <div class="c-name">${{c.name||c.email}}</div>
        <div class="c-email">${{c.email}}</div>
        <div class="c-meta">${{badge}}${{loc?`<span class="c-loc">📍 ${{loc}}</span>`:''}}</div>
      </td>
      <td class="td-orders"><span class="num">${{c.total_orders}}</span></td>
      <td class="td-spent">
        <div class="num gold">${{c.total_spent.toLocaleString('pt-PT',{{minimumFractionDigits:2,maximumFractionDigits:2}})}}€</div>
        <div class="bar-wrap"><div class="bar" style="width:${{barW}}%"></div></div>
        <div class="sub">avg ${{c.avg_order.toFixed(2)}}€</div>
      </td>
      <td class="td-last"><span class="${{daysCls}}">${{daysTxt}}</span><div class="sub">${{c.last_order||''}}</div></td>
      <td class="td-product">${{topProd}}</td>
    </tr>`;
  }}).join('');
  tbody.innerHTML = html;
}}

function fmt(n){{ return n.toLocaleString('pt-PT',{{minimumFractionDigits:2,maximumFractionDigits:2}})+'€'; }}
function fmtDate(s){{ if(!s) return '—'; const[y,m,d]=s.split('-'); return d+'/'+m+'/'+y; }}

function openProfile(idx) {{
  // Abre o drawer com loading
  document.getElementById('dAvatar').textContent = '…';
  document.getElementById('dName').textContent = 'A carregar…';
  document.getElementById('dEmail').textContent = '';
  document.getElementById('dBadges').innerHTML = '';
  document.getElementById('drawerBody').innerHTML = '<div style="padding:40px;text-align:center;color:var(--muted)"><div class="spin" style="font-size:2rem">⟳</div><div style="margin-top:12px">A carregar ficha…</div></div>';
  document.getElementById('overlay').classList.add('open');
  document.body.style.overflow = 'hidden';

  // Busca os dados completos ao servidor
  fetch(`/api/crm/customer/${{idx}}`)
    .then(r => r.json())
    .then(c => renderProfile(c))
    .catch(e => {{
      document.getElementById('drawerBody').innerHTML = '<div style="padding:40px;text-align:center;color:var(--red)">Erro ao carregar ficha. Verifica se o servidor está a correr.</div>';
    }});
}}

function renderProfile(c) {{
  const initials = (c.name||c.email).split(' ').slice(0,2).map(w=>w[0]||'').join('').toUpperCase();
  document.getElementById('dAvatar').textContent = initials;
  document.getElementById('dName').textContent = c.name || c.email;
  document.getElementById('dEmail').textContent = c.email;

  const badges = document.getElementById('dBadges');
  let badgeHtml = c.is_guest
    ? '<span class="badge guest">Guest</span>'
    : '<span class="badge member">Cliente Registado</span>';
  if (c.city) badgeHtml += `<span style="font-size:.72rem;color:var(--muted)">📍 ${{c.city}}${{c.region ? ', '+c.region : ''}}</span>`;
  badges.innerHTML = badgeHtml;

  const days = c.days_since;
  const daysText = typeof days === 'number'
    ? (days === 0 ? 'Hoje' : days === 1 ? 'Ontem' : days + ' dias atrás')
    : '—';

  let html = '';

  // KPIs
  html += `<div class="kpi-row">
    <div class="kpi"><div class="kpi-val">${{c.total_orders}}</div><div class="kpi-lbl">Encomendas</div></div>
    <div class="kpi"><div class="kpi-val">${{fmt(c.total_spent)}}</div><div class="kpi-lbl">Total Gasto</div></div>
    <div class="kpi"><div class="kpi-val">${{fmt(c.avg_order)}}</div><div class="kpi-lbl">Ticket Médio</div></div>
    <div class="kpi"><div class="kpi-val">${{daysText}}</div><div class="kpi-lbl">Última Compra</div></div>
  </div>`;

  // Dados pessoais
  html += `<div class="section">
    <div class="section-title">Dados Pessoais</div>
    <div class="info-grid">
      <div class="info-item"><div class="info-lbl">Nome</div><div class="info-val">${{c.name||'—'}}</div></div>
      <div class="info-item"><div class="info-lbl">Email</div><div class="info-val">${{c.email}}</div></div>
      <div class="info-item"><div class="info-lbl">Telefone</div><div class="info-val ${{c.phone?'':'empty'}}">${{c.phone||'Não disponível'}}</div></div>
      <div class="info-item"><div class="info-lbl">NIF</div><div class="info-val ${{c.vat?'':'empty'}}">${{c.vat||'Não disponível'}}</div></div>
      <div class="info-item"><div class="info-lbl">Cidade</div><div class="info-val ${{c.city?'':'empty'}}">${{c.city||'—'}}${{c.postcode ? ' · '+c.postcode : ''}}</div></div>
      <div class="info-item"><div class="info-lbl">Região / País</div><div class="info-val ${{c.region?'':'empty'}}">${{c.region||'—'}} · ${{c.country||'PT'}}</div></div>
      ${{c.street ? `<div class="info-item" style="grid-column:1/-1"><div class="info-lbl">Morada</div><div class="info-val">${{c.street}}</div></div>` : ''}}
    </div>
    <div class="info-grid" style="margin-top:8px">
      <div class="info-item"><div class="info-lbl">1ª Compra</div><div class="info-val">${{fmtDate(c.first_order)}}</div></div>
      <div class="info-item"><div class="info-lbl">Última Compra</div><div class="info-val">${{fmtDate(c.last_order)}}</div></div>
    </div>
  </div>`;

  // Produtos comprados
  if (c.products && c.products.length > 0) {{
    html += `<div class="section"><div class="section-title">Produtos Comprados (${{c.products.length}})</div><div class="products-list">`;
    c.products.forEach((p,i) => {{
      html += `<div class="prod-item">
        <div class="prod-rank">${{i+1}}</div>
        <div style="flex:1"><div class="prod-name">${{p.name}}</div><div class="prod-sku">${{p.sku}}</div></div>
        <div class="prod-qty">${{Math.round(p.qty)}}x</div>
        <div class="prod-rev">${{fmt(p.revenue)}}</div>
      </div>`;
    }});
    html += `</div></div>`;
  }}

  // Histórico de encomendas
  html += `<div class="section"><div class="section-title">Histórico de Encomendas (${{c.all_orders.length}})</div><div class="orders-list">`;
  c.all_orders.forEach(o => {{
    const sColor = STATUS_COLORS[o.status] || '#888';
    const sLabel = STATUS_LABELS[o.status] || o.status;
    const hasItems = o.items && o.items.length > 0;
    html += `<div class="order-card">
      <div class="order-head" onclick="toggleOrder(this)">
        <div><div class="order-num">#${{o.id}}</div><div class="order-date">${{fmtDate(o.date)}}</div></div>
        <span class="order-status" style="background:${{sColor}}22;color:${{sColor}}">${{sLabel}}</span>
        <div class="order-total">${{fmt(o.total)}}</div>
        ${{hasItems ? '<div class="order-chevron">▼</div>' : ''}}
      </div>`;
    if (hasItems) {{
      html += `<div class="order-items">`;
      o.items.forEach(item => {{
        html += `<div class="order-item-row">
          <div class="oi-name">${{item.name}}</div>
          <div class="oi-qty">${{Math.round(item.qty)}}x · ${{fmt(item.price)}}</div>
          <div class="oi-price">${{fmt(item.subtotal)}}</div>
        </div>`;
      }});
      html += `</div>`;
    }}
    html += `</div>`;
  }});
  html += `</div></div>`;

  document.getElementById('drawerBody').innerHTML = html;
}}

function toggleOrder(head) {{
  const items = head.nextElementSibling;
  const chevron = head.querySelector('.order-chevron');
  if (!items) return;
  const open = items.style.display === 'block';
  items.style.display = open ? 'none' : 'block';
  if (chevron) chevron.style.transform = open ? '' : 'rotate(180deg)';
}}

function closeProfile(e) {{
  if (e && e.target !== document.getElementById('overlay')) return;
  document.getElementById('overlay').classList.remove('open');
  document.body.style.overflow = '';
}}

document.addEventListener('keydown', e => {{ if(e.key==='Escape') closeProfile(); }});

function applyFilters() {{
  const q        = document.getElementById('searchInput').value.toLowerCase();
  const dateFrom = document.getElementById('dateFrom').value;
  const dateTo   = document.getElementById('dateTo').value;
  const hasDate  = dateFrom || dateTo;
  document.getElementById('dateResetBtn').style.display = hasDate ? '' : 'none';
  document.getElementById('dateFilter').classList.toggle('date-active', !!hasDate);
  const rows = document.querySelectorAll('#tbody .customer-row');
  let visible = 0;
  rows.forEach(row => {{
    const email = row.dataset.email||'';
    const name = row.dataset.name||'';
    const orders = parseInt(row.dataset.orders||0);
    const isGuest = row.dataset.guest === 'true';
    const daysVal = parseInt(row.dataset.days||9999);
    const lastOrder = row.dataset.lastOrder||'';

    const matchQ = !q || email.includes(q) || name.includes(q);
    let matchF = true;
    if (activeFilter==='multi') matchF = orders>=2;
    if (activeFilter==='member') matchF = !isGuest;
    if (activeFilter==='guest') matchF = isGuest;
    if (activeFilter==='recent') matchF = daysVal<=30;

    let matchDate = true;
    if (hasDate) {{
      if (!lastOrder) {{ matchDate = false; }}
      else {{
        if (dateFrom) matchDate = lastOrder >= dateFrom;
        if (dateTo && matchDate) matchDate = lastOrder <= dateTo;
      }}
    }}

    const show = matchQ && matchF && matchDate;
    row.classList.toggle('hidden', !show);
    if (show) visible++;
  }});
  document.getElementById('cnt').textContent = visible+' cliente'+(visible!==1?'s':'');
}}

function resetDateFilter() {{
  document.getElementById('dateFrom').value = '';
  document.getElementById('dateTo').value   = '';
  document.getElementById('dateResetBtn').style.display = 'none';
  document.getElementById('dateFilter').classList.remove('date-active');
  applyFilters();
}}

function setFilter(type, btn) {{
  activeFilter = type;
  document.querySelectorAll('#tab-clientes .fbtn').forEach(b=>b.classList.remove('on'));
  btn.classList.add('on');
  applyFilters();
}}

function sortTbl(col) {{
  const tbody = document.getElementById('tbody');
  const rows = [...tbody.querySelectorAll('.customer-row')];
  const dir = tbody.dataset.col==col && tbody.dataset.dir=='asc' ? 'desc' : 'asc';
  tbody.dataset.col=col; tbody.dataset.dir=dir;
  rows.sort((a,b)=>{{
    let va,vb;
    if(col===0){{va=parseInt(a.dataset.rank);vb=parseInt(b.dataset.rank);}}
    else if(col===1){{va=a.dataset.name;vb=b.dataset.name;return dir==='asc'?va.localeCompare(vb):vb.localeCompare(va);}}
    else if(col===2){{va=parseInt(a.dataset.orders);vb=parseInt(b.dataset.orders);}}
    else if(col===3){{va=parseFloat(a.querySelector('.gold').textContent.replace(/[€.,\s]/g,''));vb=parseFloat(b.querySelector('.gold').textContent.replace(/[€.,\s]/g,''));}}
    else if(col===4){{va=a.querySelector('.sub').textContent;vb=b.querySelector('.sub').textContent;return dir==='asc'?va.localeCompare(vb):vb.localeCompare(va);}}
    return dir==='asc'?va-vb:vb-va;
  }});
  rows.forEach(r=>tbody.appendChild(r));
  document.querySelectorAll('thead th').forEach((th,i)=>th.classList.toggle('sorted',i===col));
}}

// ── Refresh ──────────────────────────────────────────────────────────────────
let _refreshPoller = null;

function refreshCRM(full) {{
  const bar = document.getElementById('refreshBar');
  const msg = document.getElementById('refreshMsg');
  const log = document.getElementById('refreshLog');
  const btn1 = document.getElementById('btnRefresh');
  const btn2 = document.getElementById('btnFull');

  bar.style.display = 'flex';
  msg.textContent = full ? 'A buscar dados novos do Magento… (pode demorar ~2 min)' : 'A atualizar dados em cache…';
  log.textContent = '';
  btn1.disabled = true;
  btn2.disabled = true;

  fetch('/api/crm/refresh' + (full ? '?full=1' : ''))
    .then(r => r.json())
    .then(d => {{
      if (!d.ok) {{ alert('Erro: ' + d.error); resetRefreshUI(); return; }}
      _refreshPoller = setInterval(pollRefreshStatus, 1500);
    }})
    .catch(() => {{
      bar.style.display = 'none';
      btn1.disabled = false;
      btn2.disabled = false;
      alert('Servidor não encontrado.\\n\\nPara activar o botão de atualizar, o servidor tem de estar a correr.\\nAbre o ficheiro start_dashboard.command ou corre:\\n  python3 server.py');
    }});
}}

function pollRefreshStatus() {{
  fetch('/api/crm/status')
    .then(r => r.json())
    .then(s => {{
      const log = document.getElementById('refreshLog');
      if (s.log && s.log.length) log.textContent = s.log[s.log.length - 1];
      if (!s.running) {{
        clearInterval(_refreshPoller);
        if (s.error) {{ alert('Erro: ' + s.error); resetRefreshUI(); }}
        else {{ document.getElementById('refreshMsg').textContent = '✅ Dados atualizados! A recarregar…'; setTimeout(() => location.reload(), 1200); }}
      }}
    }})
    .catch(() => {{ clearInterval(_refreshPoller); resetRefreshUI(); }});
}}

function resetRefreshUI() {{
  document.getElementById('refreshBar').style.display = 'none';
  document.getElementById('btnRefresh').disabled = false;
  document.getElementById('btnFull').disabled = false;
}}

// ── Exportar CSV ──────────────────────────────────────────────────────────────
function exportCSV() {{
  const visibleRanks = new Set();
  document.querySelectorAll('#tbody .customer-row:not(.hidden)').forEach(row => {{
    visibleRanks.add(parseInt(row.dataset.rank) - 1);
  }});

  const headers = [
    'email','first_name','last_name','total_orders','total_spent_eur','avg_order_eur',
    'first_purchase','last_purchase','days_since_last_purchase',
    'city','region','postcode','country','phone','vat_nif',
    'customer_type','top_product','tags'
  ];
  const rows = [headers];

  CUSTOMERS.forEach((c, idx) => {{
    if (!visibleRanks.has(idx)) return;
    const firstName = c.name ? c.name.split(' ')[0] : '';
    const lastName  = c.name ? c.name.split(' ').slice(1).join(' ') : '';
    const tags = [];
    if (c.total_orders >= 5)       tags.push('vip');
    if (c.total_orders >= 2)       tags.push('recorrente');
    if (c.total_spent >= 500)      tags.push('high_value');
    if (typeof c.days_since === 'number') {{
      if (c.days_since <= 30)      tags.push('ativo_30d');
      else if (c.days_since <= 90) tags.push('ativo_90d');
      else if (c.days_since > 365) tags.push('inativo_1ano');
    }}
    tags.push(c.is_guest ? 'guest' : 'registado');
    const topProduct = c.top_product || '';
    const row = [
      c.email, firstName, lastName, c.total_orders,
      c.total_spent.toFixed(2), c.avg_order.toFixed(2),
      c.first_order||'', c.last_order||'',
      typeof c.days_since==='number' ? c.days_since : '',
      c.city||'', c.region||'', c.postcode||'', c.country||'PT',
      c.phone||'', c.vat||'',
      c.is_guest ? 'guest' : 'registado',
      topProduct, tags.join(';')
    ];
    rows.push(row.map(v => {{
      const s = String(v ?? '');
      return s.includes(',') || s.includes('"') || s.includes('\\n')
        ? '"' + s.replace(/"/g, '""') + '"' : s;
    }}));
  }});

  const csv = '\\uFEFF' + rows.map(r => r.join(',')).join('\\r\\n');
  const blob = new Blob([csv], {{type:'text/csv;charset=utf-8;'}});
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  const now  = new Date();
  const d    = now.getFullYear()+'-'+String(now.getMonth()+1).padStart(2,'0')+'-'+String(now.getDate()).padStart(2,'0');
  a.href = url; a.download = `cavemen_crm_clientes_${{d}}.csv`; a.click();
  URL.revokeObjectURL(url);
}}
</script>
</body>
</html>"""


def generate_rfv_html(customers, generated_at):
    from collections import Counter, defaultdict

    total_customers = len(customers)
    total_revenue = sum(c['total_spent'] for c in customers)

    # Counts per segment
    seg_counts = Counter(c['rfv_segment'] for c in customers)
    seg_revenue = defaultdict(float)
    for c in customers:
        seg_revenue[c['rfv_segment']] += c['total_spent']

    champions_count = seg_counts.get('champions', 0) + seg_counts.get('loyal', 0)
    champions_pct = round(champions_count / total_customers * 100, 1) if total_customers else 0
    at_risk_count = seg_counts.get('at_risk', 0) + seg_counts.get('cant_lose', 0)
    champions_rev = round(seg_revenue.get('champions', 0), 0)

    # Matrix 5x5: cell[f][r] = count (f=1..5, r=1..5)
    matrix = {}
    for c in customers:
        key = f"{c['rfv_f']}_{c['rfv_r']}"
        matrix[key] = matrix.get(key, 0) + 1

    matrix_json = json.dumps(matrix)
    segments_meta_json = json.dumps(SEGMENTS_META)
    seg_counts_json = json.dumps(dict(seg_counts))
    seg_revenue_json = json.dumps({k: round(v, 2) for k, v in seg_revenue.items()})

    return f"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Matriz RFV · Cavemen Store</title>
<style>
:root{{--bg:#0f0f0f;--s1:#1a1a1a;--s2:#222;--s3:#2a2a2a;--border:#2e2e2e;--text:#e8e8e8;--muted:#777;--accent:#c9a96e;--gold:#e8c98a;--green:#4caf89;--red:#e05454;--blue:#5b9bd5;--orange:#f0a732;}}
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:var(--bg);color:var(--text);font-family:'Inter',system-ui,sans-serif;}}
header{{background:var(--s1);border-bottom:1px solid var(--border);padding:16px 28px;display:flex;align-items:center;gap:12px;}}
.logo{{font-size:1.3rem;font-weight:800;color:var(--gold);letter-spacing:.05em;}}
.logo span{{color:var(--muted);font-weight:400;}}
.gen{{margin-left:auto;font-size:.72rem;color:var(--muted);}}
.back-btn{{padding:7px 14px;border-radius:6px;border:1px solid var(--border);background:var(--s2);color:var(--text);font-size:.8rem;text-decoration:none;white-space:nowrap;}}
.back-btn:hover{{background:var(--s3);}}
.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--border);border-bottom:1px solid var(--border);}}
.stat{{background:var(--s1);padding:14px 20px;}}
.stat-l{{font-size:.65rem;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin-bottom:5px;}}
.stat-v{{font-size:1.45rem;font-weight:700;color:var(--gold);line-height:1;}}
.stat-s{{font-size:.7rem;color:var(--muted);margin-top:3px;}}
.main-wrap{{padding:24px 28px 60px;}}
.section-title{{font-size:.75rem;text-transform:uppercase;letter-spacing:.1em;color:var(--accent);font-weight:700;margin-bottom:16px;padding-bottom:6px;border-bottom:1px solid var(--border);}}
/* Matrix */
.matrix-section{{margin-bottom:32px;}}
.matrix-container{{display:inline-block;}}
.matrix-wrap{{display:flex;gap:0;}}
.matrix-y-labels{{display:flex;flex-direction:column;justify-content:space-around;padding-right:10px;padding-top:28px;padding-bottom:4px;}}
.matrix-y-label{{font-size:.65rem;color:var(--muted);text-align:right;width:60px;display:flex;align-items:center;justify-content:flex-end;}}
.matrix-inner{{}}
.matrix-x-labels{{display:flex;justify-content:space-around;padding-left:4px;margin-top:6px;}}
.matrix-x-label{{font-size:.65rem;color:var(--muted);text-align:center;width:80px;}}
.matrix-x-title{{text-align:center;font-size:.7rem;color:var(--muted);margin-top:4px;}}
.matrix-y-title{{font-size:.7rem;color:var(--muted);writing-mode:vertical-rl;transform:rotate(180deg);text-align:center;padding-right:6px;}}
.matrix-grid{{display:grid;grid-template-columns:repeat(5,90px);grid-template-rows:repeat(5,76px);gap:0;}}
/* Segment cards */
.seg-cards{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:32px;}}
.seg-card{{background:var(--s1);border:1px solid var(--border);border-radius:10px;padding:14px;cursor:pointer;transition:border-color .15s,background .15s;position:relative;overflow:hidden;}}
.seg-card::before{{content:'';position:absolute;inset:0;border-radius:10px;opacity:.07;}}
.seg-card:hover,.seg-card.active{{border-color:var(--card-color,var(--accent));}}
.seg-card.active{{background:color-mix(in srgb,var(--card-color,var(--accent)) 10%,var(--s1));}}
.seg-icon{{font-size:1.4rem;margin-bottom:6px;}}
.seg-name{{font-size:.78rem;font-weight:700;margin-bottom:2px;}}
.seg-count{{font-size:1.3rem;font-weight:700;}}
.seg-rev{{font-size:.7rem;color:var(--muted);margin-top:3px;}}
.seg-pct{{font-size:.65rem;padding:2px 6px;border-radius:12px;font-weight:600;margin-top:4px;display:inline-block;}}
/* Controls */
.controls{{padding:0 0 14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;}}
.search{{position:relative;}}
.search input{{padding:8px 12px 8px 34px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:.88rem;outline:none;width:280px;}}
.search input:focus{{border-color:var(--accent);}}
.search::before{{content:"🔍";position:absolute;left:10px;top:50%;transform:translateY(-50%);font-size:.8rem;pointer-events:none;}}
.fbtn{{padding:6px 13px;border-radius:6px;border:1px solid var(--border);background:var(--s2);color:var(--muted);font-size:.78rem;cursor:pointer;transition:.15s;white-space:nowrap;}}
.fbtn:hover,.fbtn.on{{background:var(--accent);color:#000;border-color:var(--accent);font-weight:600;}}
.cnt{{font-size:.78rem;color:var(--muted);}}
.export-btn{{background:var(--s2);color:#4caf89;border-color:#4caf89;font-weight:600;}}
.export-btn:hover{{background:#4caf89;color:#000;}}
/* Table */
.tbl-wrap{{overflow-x:auto;}}
table{{width:100%;border-collapse:collapse;font-size:.88rem;}}
thead th{{font-size:.68rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);padding:9px 12px;text-align:left;border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--bg);white-space:nowrap;}}
tbody tr{{transition:background .1s;}}
tbody tr:hover{{background:var(--s2);}}
tbody td{{padding:10px 12px;border-bottom:1px solid var(--border);vertical-align:middle;}}
.rfv-badge{{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:5px;font-size:.75rem;font-weight:700;}}
.r-badge{{background:#1a3a5c;color:#5b9bd5;}}
.f-badge{{background:#1a3a2a;color:#4caf89;}}
.v-badge{{background:#3a2f0a;color:#e8c98a;}}
.score-badge{{display:inline-block;padding:2px 8px;border-radius:12px;font-size:.7rem;font-weight:700;background:var(--s3);color:var(--text);}}
.seg-pill{{display:inline-block;padding:3px 10px;border-radius:20px;font-size:.65rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em;}}
.gold{{color:var(--gold);font-weight:700;}}
.sub{{font-size:.7rem;color:var(--muted);margin-top:2px;}}
.days-hot{{color:#4caf89;font-weight:600;}}
.days-warm{{color:#f0a732;}}
.days-cold{{color:var(--muted);}}
.hidden{{display:none!important;}}
.loading{{text-align:center;padding:60px;color:var(--muted);}}
.spin{{display:inline-block;animation:spin 1s linear infinite;}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
</style>
</head>
<body>
<header>
  <div class="logo">CAVEMEN <span>· RFV</span></div>
  <div class="gen">Gerado em {generated_at} · {total_customers:,} clientes</div>
  <div style="margin-left:auto;display:flex;gap:8px;align-items:center;">
    <a href="/crm" class="back-btn">← CRM</a>
  </div>
</header>

<div class="stats">
  <div class="stat"><div class="stat-l">Total Clientes</div><div class="stat-v">{total_customers:,}</div><div class="stat-s">com encomendas válidas</div></div>
  <div class="stat"><div class="stat-l">Champions + Fiéis</div><div class="stat-v" id="s-champ">{champions_count:,}</div><div class="stat-s">{champions_pct}% do total</div></div>
  <div class="stat"><div class="stat-l">Em Risco + Não Perder</div><div class="stat-v" id="s-risk">{at_risk_count:,}</div><div class="stat-s">reactivar urgente</div></div>
  <div class="stat"><div class="stat-l">Receita Champions</div><div class="stat-v">{champions_rev:,.0f}€</div><div class="stat-s">segmento topo</div></div>
</div>

<div class="main-wrap">

  <!-- Matriz 5x5 -->
  <div class="matrix-section">
    <div class="section-title">Matriz RFV 5×5</div>
    <div style="display:flex;gap:32px;align-items:flex-start;flex-wrap:wrap;">
      <div class="matrix-container">
        <div class="matrix-wrap">
          <div style="display:flex;flex-direction:column;align-items:center;padding-top:28px;padding-bottom:10px;padding-right:4px;">
            <div class="matrix-y-title">Frequência (F) →</div>
          </div>
          <div class="matrix-y-labels">
            <div class="matrix-y-label">F=5 (Alta)</div>
            <div class="matrix-y-label">F=4</div>
            <div class="matrix-y-label">F=3</div>
            <div class="matrix-y-label">F=2</div>
            <div class="matrix-y-label">F=1 (Baixa)</div>
          </div>
          <div class="matrix-inner">
            <div class="matrix-grid" id="matrixGrid"></div>
            <div class="matrix-x-labels">
              <div class="matrix-x-label">R=1 (Antiga)</div>
              <div class="matrix-x-label">R=2</div>
              <div class="matrix-x-label">R=3</div>
              <div class="matrix-x-label">R=4</div>
              <div class="matrix-x-label">R=5 (Recente)</div>
            </div>
            <div class="matrix-x-title">← Recência (R)</div>
          </div>
        </div>
      </div>
      <div id="matrixLegend" style="flex:1;min-width:260px;"></div>
    </div>
  </div>

  <!-- Cards de Segmentos -->
  <div class="section-title">Segmentos</div>
  <div class="seg-cards" id="segCards"></div>

  <!-- Tabela de Clientes -->
  <div class="section-title">Clientes por Segmento</div>
  <div class="controls">
    <div class="search"><input type="text" id="searchInput" placeholder="Pesquisar por nome ou email…" oninput="applyFilters()"></div>
    <button class="fbtn on" onclick="clearSegFilter(this)">Todos</button>
    <span class="cnt" id="cnt">A carregar…</span>
    <div style="margin-left:auto;">
      <button class="fbtn export-btn" onclick="exportCSV()">⬇ Exportar CSV</button>
    </div>
  </div>
  <div class="tbl-wrap">
    <div id="loadingMsg" class="loading">
      <div class="spin" style="font-size:2rem">⟳</div>
      <div style="margin-top:12px;font-size:.9rem">A carregar clientes…</div>
    </div>
    <table id="tbl" style="display:none">
      <thead><tr>
        <th>#</th>
        <th>Cliente</th>
        <th>R 🔵 F 🟢 V 🟡</th>
        <th>Score</th>
        <th>Total Gasto</th>
        <th>Última Compra</th>
        <th>Segmento</th>
      </tr></thead>
      <tbody id="tbody"></tbody>
    </table>
  </div>
</div>

<script>
const MATRIX_DATA = {matrix_json};
const SEGMENTS_META = {segments_meta_json};
const SEG_COUNTS = {seg_counts_json};
const SEG_REVENUE = {seg_revenue_json};
const TOTAL_REVENUE = {round(total_revenue, 2)};
const SEG_TABLE = {{
  '5_5':'champions','5_4':'champions','5_3':'loyal','5_2':'at_risk','5_1':'cant_lose',
  '4_5':'champions','4_4':'loyal','4_3':'loyal','4_2':'at_risk','4_1':'cant_lose',
  '3_5':'potential','3_4':'potential','3_3':'attention','3_2':'attention','3_1':'hibernating',
  '2_5':'new','2_4':'promising','2_3':'promising','2_2':'hibernating','2_1':'lost',
  '1_5':'new','1_4':'new','1_3':'promising','1_2':'lost','1_1':'lost',
}};

let CUSTOMERS = [];
let activeSegment = null;

// ── Matriz ────────────────────────────────────────────────────────────────────
function buildMatrix() {{
  const grid = document.getElementById('matrixGrid');
  // F rows descending (5→1), R cols ascending (1→5)
  let html = '';
  for (let f = 5; f >= 1; f--) {{
    for (let r = 1; r <= 5; r++) {{
      const key = f+'_'+r;
      const seg = SEG_TABLE[key] || 'lost';
      const meta = SEGMENTS_META[seg] || {{}};
      const color = meta.color || '#333';
      const count = MATRIX_DATA[key] || 0;
      html += `<div class="matrix-cell" style="background:${{color}}22;border:1px solid ${{color}}55;"
        onclick="filterBySeg('${{seg}}')" title="${{meta.name||seg}}: ${{count}} clientes">
        <div class="matrix-cell-count" style="color:${{color}}">${{count}}</div>
        <div class="matrix-cell-seg">${{meta.icon||''}} ${{(meta.name||seg).split(' ').slice(0,2).join(' ')}}</div>
      </div>`;
    }}
  }}
  grid.innerHTML = html;

  // Legend
  const legend = document.getElementById('matrixLegend');
  const segsInMatrix = [...new Set(Object.values(SEG_TABLE))];
  let lhtml = '<div style="display:flex;flex-direction:column;gap:6px;">';
  segsInMatrix.forEach(seg => {{
    const meta = SEGMENTS_META[seg] || {{}};
    const color = meta.color || '#333';
    lhtml += `<div style="display:flex;align-items:center;gap:8px;font-size:.78rem;">
      <div style="width:12px;height:12px;border-radius:3px;background:${{color}};flex-shrink:0;"></div>
      <span>${{meta.icon||''}} ${{meta.name||seg}}</span>
      <span style="color:var(--muted);font-size:.7rem;">— ${{meta.desc||''}}</span>
    </div>`;
  }});
  lhtml += '</div>';
  legend.innerHTML = lhtml;
}}

// ── Cards de Segmentos ─────────────────────────────────────────────────────
function buildSegCards() {{
  const container = document.getElementById('segCards');
  const segOrder = ['champions','loyal','potential','new','promising','attention','at_risk','cant_lose','hibernating','lost'];
  let html = '';
  segOrder.forEach(seg => {{
    const meta = SEGMENTS_META[seg] || {{}};
    const color = meta.color || '#333';
    const count = SEG_COUNTS[seg] || 0;
    const rev = SEG_REVENUE[seg] || 0;
    const revPct = TOTAL_REVENUE > 0 ? (rev/TOTAL_REVENUE*100).toFixed(1) : '0';
    html += `<div class="seg-card" id="card_${{seg}}" style="--card-color:${{color}}" onclick="filterBySeg('${{seg}}')">
      <div class="seg-icon">${{meta.icon||''}}</div>
      <div class="seg-name" style="color:${{color}}">${{meta.name||seg}}</div>
      <div class="seg-count">${{count.toLocaleString('pt-PT')}}</div>
      <div class="seg-rev">${{rev.toLocaleString('pt-PT',{{minimumFractionDigits:0,maximumFractionDigits:0}})}}€</div>
      <span class="seg-pct" style="background:${{color}}22;color:${{color}}">${{revPct}}% receita</span>
    </div>`;
  }});
  container.innerHTML = html;
}}

// ── Tabela ────────────────────────────────────────────────────────────────────
function renderTable(data) {{
  const tbody = document.getElementById('tbody');
  const html = data.map((c, idx) => {{
    const days = c.days_since;
    let daysCls = 'days-cold', daysTxt = '—';
    if (typeof days === 'number') {{
      daysTxt = days === 0 ? 'Hoje' : days === 1 ? 'Ontem' : days+'d atrás';
      daysCls = days <= 30 ? 'days-hot' : days <= 90 ? 'days-warm' : 'days-cold';
    }}
    const seg = c.rfv_segment || 'lost';
    const meta = SEGMENTS_META[seg] || {{}};
    const color = meta.color || '#555';
    const r = c.rfv_r || 1, f = c.rfv_f || 1, v = c.rfv_v || 1;
    return `<tr data-seg="${{seg}}" data-email="${{c.email}}" data-name="${{(c.name||'').toLowerCase()}}" data-score="${{c.rfv_score||0}}">
      <td style="color:var(--muted);font-size:.85rem">${{idx+1}}</td>
      <td>
        <div style="font-weight:600">${{c.name||c.email}}</div>
        <div style="font-size:.75rem;color:var(--muted)">${{c.email}}</div>
        ${{c.city ? `<div style="font-size:.7rem;color:var(--muted)">📍 ${{c.city}}</div>` : ''}}
      </td>
      <td><span class="rfv-badge r-badge">${{r}}</span> <span class="rfv-badge f-badge">${{f}}</span> <span class="rfv-badge v-badge">${{v}}</span></td>
      <td><span class="score-badge">${{c.rfv_score||0}}/15</span></td>
      <td>
        <div class="gold">${{c.total_spent.toLocaleString('pt-PT',{{minimumFractionDigits:2,maximumFractionDigits:2}})}}€</div>
        <div class="sub">${{c.total_orders}} enc.</div>
      </td>
      <td><span class="${{daysCls}}">${{daysTxt}}</span><div class="sub">${{c.last_order||''}}</div></td>
      <td><span class="seg-pill" style="background:${{color}}22;color:${{color}}">${{meta.icon||''}} ${{meta.name||seg}}</span></td>
    </tr>`;
  }}).join('');
  tbody.innerHTML = html;
}}

function applyFilters() {{
  const q = document.getElementById('searchInput').value.toLowerCase();
  const rows = document.querySelectorAll('#tbody tr');
  let visible = 0;
  rows.forEach(row => {{
    const email = row.dataset.email||'';
    const name = row.dataset.name||'';
    const seg = row.dataset.seg||'';
    const matchQ = !q || email.includes(q) || name.includes(q);
    const matchSeg = !activeSegment || seg === activeSegment;
    const show = matchQ && matchSeg;
    row.classList.toggle('hidden', !show);
    if (show) visible++;
  }});
  document.getElementById('cnt').textContent = visible+' cliente'+(visible!==1?'s':'');
}}

function filterBySeg(seg) {{
  if (activeSegment === seg) {{
    activeSegment = null;
    document.querySelectorAll('.seg-card').forEach(c => c.classList.remove('active'));
  }} else {{
    activeSegment = seg;
    document.querySelectorAll('.seg-card').forEach(c => c.classList.toggle('active', c.id==='card_'+seg));
  }}
  applyFilters();
}}

function clearSegFilter(btn) {{
  activeSegment = null;
  document.querySelectorAll('.seg-card').forEach(c => c.classList.remove('active'));
  applyFilters();
}}

// ── Export CSV ────────────────────────────────────────────────────────────────
function exportCSV() {{
  const rows = [...document.querySelectorAll('#tbody tr:not(.hidden)')];
  const headers = ['email','name','rfv_r','rfv_f','rfv_v','rfv_score','rfv_segment','total_orders','total_spent','last_order','days_since','city'];
  const lines = [headers];
  rows.forEach(row => {{
    const email = row.dataset.email;
    const c = CUSTOMERS.find(x => x.email === email);
    if (!c) return;
    lines.push([
      c.email, c.name||'', c.rfv_r, c.rfv_f, c.rfv_v, c.rfv_score, c.rfv_segment,
      c.total_orders, c.total_spent.toFixed(2), c.last_order||'',
      typeof c.days_since==='number'?c.days_since:'', c.city||''
    ].map(v => {{ const s=String(v??''); return s.includes(',')||s.includes('"')?'"'+s.replace(/"/g,'""')+'"':s; }}));
  }});
  const csv = '\\uFEFF'+lines.map(r=>r.join(',')).join('\\r\\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv],{{type:'text/csv;charset=utf-8;'}}));
  const d = new Date(); a.download = `cavemen_rfv_${{d.getFullYear()}}-${{String(d.getMonth()+1).padStart(2,'0')}}-${{String(d.getDate()).padStart(2,'0')}}.csv`;
  a.click();
}}

// ── Init ──────────────────────────────────────────────────────────────────────
buildMatrix();
buildSegCards();

fetch('/api/crm/rfv')
  .then(r => r.json())
  .then(data => {{
    CUSTOMERS = data;
    renderTable(data);
    document.getElementById('loadingMsg').style.display = 'none';
    document.getElementById('tbl').style.display = '';
    document.getElementById('cnt').textContent = data.length+' clientes';
  }})
  .catch(e => {{
    document.getElementById('loadingMsg').innerHTML = '<div style="color:var(--red)">Erro ao carregar dados. Verifica se o servidor está a correr em localhost:5001</div>';
  }});
</script>
</body>
</html>"""


def main():
    import sys
    force = "--refresh" in sys.argv

    orders = fetch_all_orders(None if not force else get_token(), force_refresh=force)

    print(f"\n🧮 A construir CRM ({len(orders)} encomendas)...")
    customers = build_crm(orders)
    print(f"✅ {len(customers)} clientes únicos")

    print("📊 A calcular scores RFV...")
    customers = score_rfv(customers)
    # Mostrar distribuição
    from collections import Counter
    seg_counts = Counter(c['rfv_segment'] for c in customers)
    for seg, count in sorted(seg_counts.items(), key=lambda x: -x[1]):
        meta = SEGMENTS_META.get(seg, {})
        print(f"  {meta.get('icon','•')} {meta.get('name', seg):<25}: {count:>5} clientes")

    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")

    # Guarda JSON completo (para a API de perfis)
    data_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), OUTPUT_DATA)
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(customers, f, ensure_ascii=False)
    print(f"✅ Dados guardados: {data_path} ({os.path.getsize(data_path)//1024}KB)")

    # Gera HTML leve (sem JSON embutido) — com a aba "Clientes Loja" (lojas físicas)
    html = generate_html(customers, generated_at, show_lojas_tab=True)
    output = os.path.join(os.path.dirname(os.path.abspath(__file__)), OUTPUT_HTML)
    with open(output, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ CRM gerado: {output} ({os.path.getsize(output)//1024}KB)")

    # Gera RFV HTML
    rfv_html = generate_rfv_html(customers, generated_at)
    rfv_output = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rfv.html")
    with open(rfv_output, "w", encoding="utf-8") as f:
        f.write(rfv_html)
    print(f"✅ RFV gerado: {rfv_output} ({os.path.getsize(rfv_output)//1024}KB)")

    print(f"\n📊 TOP 10 CLIENTES:")
    print(f"{'#':<4} {'Nome':<30} {'Email':<35} {'Enc.':>5} {'Total':>10}")
    print("─" * 88)
    for i, c in enumerate(customers[:10], 1):
        print(f"{i:<4} {c['name'][:29]:<30} {c['email'][:34]:<35} {c['total_orders']:>5} {c['total_spent']:>10,.2f}€")

if __name__ == "__main__":
    main()
