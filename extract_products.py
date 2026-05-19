#!/usr/bin/env python3
"""
Cavemen Store — Extração detalhada de produtos (com IVA, por dia, categorias normalizadas)
Gera: products_data_v2.json
"""

import requests
import json
import re
import time
from datetime import datetime, timedelta
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

# Categorização personalizada (ignora categorias do Moloni)
from categorize import categorize as custom_categorize

CLIENT_ID     = "cavemenunipessoallda"
CLIENT_SECRET = "a7678d73814b0f8179407c63b6242ca83690b61d"
USERNAME      = "encomendas@cavemenstore.com"
PASSWORD      = "7+LVn*QU+4sdrXN"
COMPANY_ID    = 274475
BASE_URL      = "https://api.moloni.pt/v1"

TERMINALS = {
    125906: "Guimarães",
    125908: "Braga",
    148908: "Porto",
    0:      "Online",
}
STORES = ["Guimarães", "Braga", "Porto", "Online"]

# Category IDs that are generic catch-alls (Moloni root / Magento integration)
GENERIC_CAT_IDS = {7153698, 7588933, 7590304}

# ─── AUTH (with auto-refresh) ──────────────────────────────────────────────────
_token = None
_token_ts = 0

def get_token(force=False):
    global _token, _token_ts
    if _token and not force and (time.time() - _token_ts) < 2400:  # refresh every 40 min
        return _token
    if not _token:
        print("🔐 Autenticando...")
    else:
        print("🔄 Renovando token...")
    r = requests.get(f"{BASE_URL}/grant/", params={
        "grant_type": "password", "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET, "username": USERNAME, "password": PASSWORD,
    }, timeout=15)
    r.raise_for_status()
    _token = r.json()["access_token"]
    _token_ts = time.time()
    print("✅ Token OK")
    return _token

def api_post(endpoint, data=None):
    payload = {"company_id": COMPANY_ID}
    if data:
        payload.update(data)
    for attempt in range(3):
        try:
            token = get_token()  # auto-refreshes if needed
            r = requests.post(f"{BASE_URL}/{endpoint}/",
                              params={"access_token": token},
                              data=payload, timeout=30)
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 401:
                get_token(force=True)  # force refresh on 401
                continue
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt == 2:
                return None
            time.sleep(1)
    return None

def parse_date(s):
    if not s:
        return None
    clean = re.sub(r'[+-]\d{2}:?\d{2}$|Z$', '', s.replace("T", " ")).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(clean[:19], fmt)
        except Exception:
            pass
    return None

# ─── STEP 1: Build product + category catalog ─────────────────────────────────
def build_catalog():
    print("\n📦 Buscando catálogo de produtos...")
    all_prods = []
    offset = 0
    while True:
        batch = api_post("products/getAll", {"qty": 50, "offset": offset})
        if not batch or not isinstance(batch, list):
            break
        all_prods.extend(batch)
        if len(batch) < 50:
            break
        offset += 50
        if offset % 500 == 0:
            print(f"  {offset} produtos...")

    print(f"  ✅ {len(all_prods)} produtos no catálogo")

    # Build category name map: id → name
    raw_cat_map = {}  # cat_id → raw name
    for p in all_prods:
        cat_id = p.get("category_id", -1)
        cat_obj = p.get("category") or {}
        cat_name = cat_obj.get("name", "") if isinstance(cat_obj, dict) else ""
        if cat_id and cat_id not in raw_cat_map and cat_name:
            raw_cat_map[cat_id] = cat_name

    # Normalized category name: generic IDs → "Sem Categoria"
    def normalize_cat(cat_id, raw_name):
        if not raw_name or cat_id in GENERIC_CAT_IDS:
            return "Sem Categoria"
        return raw_name

    cat_map = {cid: normalize_cat(cid, name) for cid, name in raw_cat_map.items()}

    # Product map: product_id → {name, reference, category_id, category_name}
    prod_map = {}
    for p in all_prods:
        pid = p.get("product_id")
        cat_id = p.get("category_id", -1)
        cat_name = cat_map.get(cat_id, "Sem Categoria")
        prod_map[pid] = {
            "name": p.get("name", ""),
            "reference": p.get("reference", ""),
            "category_id": cat_id,
            "category_name": cat_name,
        }

    return prod_map, cat_map

# ─── STEP 2: Fetch document list (from year onwards) ──────────────────────────
def fetch_docs(from_year=2024):
    print(f"\n📅 Buscando documentos desde {from_year}...")
    now = datetime.now()

    # Credit notes are SUBTRACTED from revenue (devoluções/anulações)
    SALE_TYPES = ["simplifiedInvoices", "invoiceReceipts", "invoices"]
    CREDIT_TYPES = ["creditNotes"]
    ALL_TYPES = SALE_TYPES + CREDIT_TYPES

    all_docs = []
    for year in range(from_year, now.year + 1):
        for doc_type in ALL_TYPES:
            offset = 0
            while True:
                batch = api_post(f"{doc_type}/getAll",
                                 {"qty": 50, "offset": offset, "year": year})
                if not batch or not isinstance(batch, list):
                    break
                for d in batch:
                    d["_doc_type"] = doc_type
                    d["_is_credit"] = doc_type in CREDIT_TYPES
                all_docs.extend(batch)
                if len(batch) < 50:
                    break
                offset += 50
        print(f"  {year}: {sum(1 for d in all_docs if str(year) in d.get('date','')[:4])} docs parcial")

    valid = []
    n_credits = 0
    for doc in all_docs:
        dt = parse_date(doc.get("date", ""))
        if dt and float(doc.get("net_value", 0) or 0) > 0:
            doc["_date"] = dt
            valid.append(doc)
            if doc.get("_is_credit"):
                n_credits += 1

    print(f"  ✅ {len(valid)} documentos válidos ({from_year}–{now.year}), {n_credits} notas de crédito")
    return valid

# ─── STEP 3: Fetch product details (getOne) ───────────────────────────────────
def fetch_product_details(docs):
    print(f"\n🔍 Buscando produtos de {len(docs)} documentos (10 threads)...")

    ep_map = {
        "simplifiedInvoices": "simplifiedInvoices/getOne",
        "invoiceReceipts":    "invoiceReceipts/getOne",
        "invoices":           "invoices/getOne",
        "creditNotes":        "creditNotes/getOne",
    }

    def fetch_one(doc):
        ep = ep_map.get(doc["_doc_type"], "simplifiedInvoices/getOne")
        data = api_post(ep, {"document_id": doc["document_id"]})
        products = []
        if data and isinstance(data, dict):
            products = data.get("products", [])
        return doc, products

    results = {}
    done = 0
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(fetch_one, doc): doc for doc in docs}
        for future in as_completed(futures):
            doc, products = future.result()
            results[doc["document_id"]] = {"doc": doc, "products": products}
            done += 1
            if done % 100 == 0:
                print(f"  {done}/{len(docs)}...")

    print(f"  ✅ {done} documentos processados")
    return results

# ─── STEP 4: Aggregate with VAT + day+store granularity ──────────────────────
def aggregate(doc_details, prod_map, cat_map):
    # product_id → full stats
    product_data = defaultdict(lambda: {
        "qty": 0.0, "revenue": 0.0, "orders": 0,
        "name": "", "reference": "", "category_name": "Sem Categoria", "category_id": -1,
        # by_day: { "2024-01-05": {"qty":2, "rev":50, "s":{"Guimarães":[1,25]}} }
        "by_day": defaultdict(lambda: {"qty": 0.0, "rev": 0.0, "s": defaultdict(lambda: [0.0, 0.0])}),
    })

    all_days = set()
    # transactions_by_day: day → store → count of unique documents (= customer visits)
    # POS sales are anonymous, so we count unique invoices as customer visits
    transactions_by_day = defaultdict(lambda: defaultdict(int))

    for doc_id, item in doc_details.items():
        doc = item["doc"]
        terminal_id = doc.get("terminal_id", 0)
        store = TERMINALS.get(terminal_id, f"Terminal {terminal_id}")
        dt = doc["_date"]
        day_key = dt.strftime("%Y-%m-%d")
        all_days.add(day_key)

        # Count transactions per day per physical store (exclude Online and credit notes)
        if store not in ("Online",) and not doc.get("_is_credit", False):
            transactions_by_day[day_key][store] += 1

        doc_net_value = float(doc.get("net_value", 0) or 0)  # WITH VAT (Moloni ground truth)
        is_credit = doc.get("_is_credit", False)

        # Credit notes: revenue is SUBTRACTED, qty is SUBTRACTED
        sign = -1.0 if is_credit else 1.0

        # Compute each product's pre-VAT revenue
        line_items = []
        for p in item["products"]:
            qty   = float(p.get("qty", 0) or 0)
            price = float(p.get("price", 0) or 0)
            disc  = float(p.get("discount", 0) or 0)
            if qty <= 0 or price <= 0:
                continue
            pre_vat = qty * price * (1 - disc / 100)
            line_items.append({"p": p, "qty": qty, "pre_vat": pre_vat})

        if not line_items:
            continue

        # Distribute doc_net_value proportionally by pre-VAT contribution
        # This is 100% accurate: total always equals doc.net_value
        total_pre_vat = sum(li["pre_vat"] for li in line_items)
        if total_pre_vat <= 0:
            continue

        for li in line_items:
            p = li["p"]
            qty = li["qty"] * sign
            rev = (li["pre_vat"] / total_pre_vat) * doc_net_value * sign

            pid = p.get("product_id", 0)

            # Lookup catalog info — prefer catalog name (current) over doc name (may be stale)
            catalog = prod_map.get(pid, {})
            cat_id = catalog.get("category_id") or p.get("category_id", -1)
            cat_name = cat_map.get(cat_id, catalog.get("category_name", "Sem Categoria"))
            if not cat_name or cat_id in GENERIC_CAT_IDS:
                cat_name = "Sem Categoria"

            # Use catalog name/reference if available (always up-to-date)
            catalog_name = catalog.get("name", "")
            catalog_ref  = catalog.get("reference", "")

            pd = product_data[pid]
            pd["qty"]     += qty
            pd["revenue"] += rev
            pd["orders"]  += 1
            # Prefer catalog name (current Moloni name), fallback to doc line name
            if catalog_name:
                pd["name"] = catalog_name
            elif not pd["name"]:
                pd["name"] = p.get("name", "")
            if catalog_ref:
                pd["reference"] = catalog_ref
            elif not pd["reference"]:
                pd["reference"] = p.get("reference", "")
            # Categorização personalizada (ignora categorias do Moloni)
            pd["category_name"] = custom_categorize(pd["name"])
            pd["category_id"]   = cat_id

            # Day + store level data
            day_entry = pd["by_day"][day_key]
            day_entry["qty"] += qty
            day_entry["rev"] += rev
            day_entry["s"][store][0] += qty
            day_entry["s"][store][1] += rev

    # Serialize
    products_list = []
    for pid, pd in product_data.items():
        # Skip products with zero or negative total revenue (fully returned)
        if pd["revenue"] <= 0:
            continue

        # Compact by_day serialization (keep negative values for credit note days)
        by_day_ser = {}
        for d, dv in pd["by_day"].items():
            # Include all days, even negative (credit notes reduce that day's total)
            entry = {"q": round(dv["qty"], 1), "r": round(dv["rev"], 2)}
            stores_data = {}
            for s, vals in dv["s"].items():
                if vals[1] != 0:  # include negative values too
                    stores_data[s] = [round(vals[0], 1), round(vals[1], 2)]
            if stores_data:
                entry["s"] = stores_data
            by_day_ser[d] = entry

        products_list.append({
            "product_id": pid,
            "reference":  pd["reference"],
            "name":       pd["name"],
            "category_name": pd["category_name"],
            "category_id":   pd["category_id"],
            "qty":     round(pd["qty"], 1),
            "revenue": round(pd["revenue"], 2),
            "orders":  pd["orders"],
            "avg_price":    round(pd["revenue"] / pd["qty"], 2) if pd["qty"] else 0,
            "by_day": by_day_ser,
        })
    products_list.sort(key=lambda x: x["revenue"], reverse=True)

    # Build categories + store totals from product data
    category_data = defaultdict(lambda: {"qty": 0.0, "revenue": 0.0, "products": set()})
    store_data = defaultdict(lambda: {"revenue": 0.0, "orders": 0, "qty": 0.0})
    for p in products_list:
        cat_name = p["category_name"]
        category_data[cat_name]["qty"]     += p["qty"]
        category_data[cat_name]["revenue"] += p["revenue"]
        category_data[cat_name]["products"].add(p["product_id"])
        for d, dv in p["by_day"].items():
            for s, vals in dv.get("s", {}).items():
                store_data[s]["qty"]     += vals[0]
                store_data[s]["revenue"] += vals[1]
                store_data[s]["orders"]  += 1

    cats_list = sorted(
        [{"name": n, "qty": round(v["qty"], 1), "revenue": round(v["revenue"], 2),
          "unique_products": len(v["products"])} for n, v in category_data.items()],
        key=lambda x: x["revenue"], reverse=True
    )

    sorted_days = sorted(all_days)

    # Serialize transactions_by_day (plain dict, already ints)
    clients_ser = dict(transactions_by_day)

    return {
        "generated_at": datetime.now().isoformat(),
        "date_from":    sorted_days[0]  if sorted_days else "",
        "date_to":      sorted_days[-1] if sorted_days else "",
        "stores":       STORES,
        "products":     products_list,
        "categories":   cats_list,
        "store_totals": {s: {"revenue": round(store_data[s]["revenue"], 2),
                              "orders": store_data[s]["orders"],
                              "qty": round(store_data[s]["qty"], 1)} for s in STORES},
        "total_revenue":   round(sum(v["revenue"] for v in store_data.values()), 2),
        "total_qty":       round(sum(v["qty"]     for v in store_data.values()), 1),
        "unique_products": len(products_list),
        "clients_by_day":  clients_ser,
    }

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    import os
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_path   = os.path.join(script_dir, "products_data_v2.json")

    start = time.time()
    get_token()  # initial auth

    prod_map, cat_map = build_catalog()
    docs = fetch_docs(from_year=2024)

    if not docs:
        print("❌ Nenhum documento encontrado.")
        return

    doc_details = fetch_product_details(docs)

    print("\n📊 Agregando dados...")
    data = aggregate(doc_details, prod_map, cat_map)

    # Save clients data separately (used by server for customer KPIs)
    clients_path = os.path.join(script_dir, "clients_data.json")
    clients_export = {
        "generated_at": data["generated_at"],
        "date_from":    data["date_from"],
        "date_to":      data["date_to"],
        "by_day":       data["clients_by_day"],
    }
    with open(clients_path, "w", encoding="utf-8") as f:
        json.dump(clients_export, f, ensure_ascii=False)

    # Remove clients_by_day from main products file (keep it lean)
    del data["clients_by_day"]

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - start
    print(f"\n✅ products_data_v2.json gerado em {elapsed:.0f}s")
    print(f"   {data['unique_products']} produtos únicos")
    print(f"   {len(data['categories'])} categorias")
    print(f"   {data['date_from']} → {data['date_to']}")
    print(f"   Total com IVA: {data['total_revenue']:,.2f}€ · {data['total_qty']:.0f} unidades")
    print()
    print("Top 10 produtos:")
    for i, p in enumerate(data["products"][:10]):
        cat = p['category_name'][:18]
        print(f"  {i+1:2}. [{cat:18s}] {p['reference'][:20]:20s} — {p['revenue']:>9,.2f}€  qty={p['qty']:.0f}")

    print()
    print("Categorias:")
    for c in data["categories"][:15]:
        print(f"  {c['name'][:25]:25s} — {c['revenue']:>9,.2f}€  ({c['unique_products']} produtos)")

    # Auto-reload server if running
    try:
        import requests as req
        r = req.get("http://localhost:5001/api/reload_products", timeout=5)
        if r.status_code == 200:
            print("\n🔄 Servidor recarregado automaticamente")
    except Exception:
        print("\n⚠️  Servidor não está a correr — dados guardados, recarrega manualmente")

if __name__ == "__main__":
    main()
