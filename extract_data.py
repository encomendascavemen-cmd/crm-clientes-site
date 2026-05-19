#!/usr/bin/env python3
"""
Moloni Sales Data Extractor for Cavemen Store Dashboard
Fetches data from Moloni API and generates dashboard_data.json
"""

import requests
import json
import time
from datetime import datetime, timedelta
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# ─── CONFIG ────────────────────────────────────────────────────────────────────
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

# ─── AUTH ───────────────────────────────────────────────────────────────────────
def get_token():
    print("🔐 Autenticando na API Moloni...")
    r = requests.get(f"{BASE_URL}/grant/", params={
        "grant_type":    "password",
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "username":      USERNAME,
        "password":      PASSWORD,
    })
    r.raise_for_status()
    data = r.json()
    if "access_token" not in data:
        raise RuntimeError(f"Auth falhou: {data}")
    print(f"✅ Token obtido (expira em {data['expires_in']}s)")
    return data["access_token"]

# ─── API HELPERS ────────────────────────────────────────────────────────────────
_token_lock = threading.Lock()
_token = None

def api_post(endpoint, token, data=None):
    params = {"access_token": token}
    payload = {"company_id": COMPANY_ID}
    if data:
        payload.update(data)
    for attempt in range(3):
        try:
            r = requests.post(f"{BASE_URL}/{endpoint}/", params=params, data=payload, timeout=30)
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == 2:
                return None
            time.sleep(1)
    return None

def fetch_all_pages(endpoint, token, extra_params=None, label=""):
    """Fetch all pages from a paginated endpoint (max 50 per page)."""
    results = []
    offset = 0
    page_size = 50
    while True:
        params = {"qty": page_size, "offset": offset}
        if extra_params:
            params.update(extra_params)
        batch = api_post(endpoint + "/getAll", token, params)
        if not batch or not isinstance(batch, list) or len(batch) == 0:
            break
        results.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
        if label and offset % 500 == 0:
            print(f"  {label}: {offset} documentos...")
    return results

# ─── MAIN EXTRACTION ────────────────────────────────────────────────────────────
def extract_documents(token):
    """Fetch all simplified invoices + invoice receipts for 2024, 2025, 2026."""
    all_docs = []

    for year in [2024, 2025, 2026]:
        print(f"\n📅 Buscando documentos de {year}...")

        for doc_type, label in [
            ("simplifiedInvoices", f"Faturas Simplificadas {year}"),
            ("invoiceReceipts",    f"Fatura-Recibo {year}"),
            ("invoices",           f"Faturas {year}"),
        ]:
            docs = fetch_all_pages(doc_type, token, {"year": year}, label)
            # Tag each doc with type
            for d in docs:
                d["_doc_type"] = doc_type
            all_docs.extend(docs)
            print(f"  ✅ {label}: {len(docs)} documentos")

    return all_docs

def fetch_product_details(token, doc_ids, doc_type):
    """Fetch getOne for a list of document IDs to get product lines."""
    results = {}

    def fetch_one(doc_id):
        endpoint_map = {
            "simplifiedInvoices": "simplifiedInvoices/getOne",
            "invoiceReceipts":    "invoiceReceipts/getOne",
            "invoices":           "invoices/getOne",
        }
        endpoint = endpoint_map.get(doc_type, "simplifiedInvoices/getOne")
        data = api_post(endpoint, token, {"document_id": doc_id})
        if data and isinstance(data, dict) and "products" in data:
            return doc_id, data.get("products", [])
        return doc_id, []

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(fetch_one, doc_id): doc_id for doc_id in doc_ids}
        done = 0
        for future in as_completed(futures):
            doc_id, products = future.result()
            results[doc_id] = products
            done += 1
            if done % 50 == 0:
                print(f"    Produtos: {done}/{len(doc_ids)} documentos...")

    return results

# ─── AGGREGATION ────────────────────────────────────────────────────────────────
def aggregate(all_docs, product_details):
    """Build all aggregated data for the dashboard."""

    # Sales by store + month
    monthly_sales = defaultdict(lambda: defaultdict(float))       # store -> YYYY-MM -> revenue
    monthly_orders = defaultdict(lambda: defaultdict(int))        # store -> YYYY-MM -> orders
    store_totals = defaultdict(float)
    store_orders = defaultdict(int)
    store_avg_ticket = defaultdict(list)

    # Products
    product_sales = defaultdict(lambda: {"qty": 0, "revenue": 0.0, "name": "", "reference": ""})
    product_by_store = defaultdict(lambda: defaultdict(lambda: {"qty": 0, "revenue": 0.0}))

    # Daily sales (last 30 days)
    daily_sales = defaultdict(lambda: defaultdict(float))

    cutoff_30d = datetime.now() - timedelta(days=30)
    cutoff_12m = datetime.now() - timedelta(days=365)

    valid_statuses = {0, 1}  # 0=draft? 1=finalized

    for doc in all_docs:
        status = doc.get("status", 1)
        net_value = float(doc.get("net_value", 0) or 0)
        if net_value <= 0:
            continue

        terminal_id = doc.get("terminal_id", 0)
        store = TERMINALS.get(terminal_id, f"Terminal {terminal_id}")

        date_str = doc.get("date", "")
        if not date_str:
            continue
        try:
            date = datetime.fromisoformat(date_str.replace("+0000", "+00:00").replace("+0100", "+01:00"))
            date = date.replace(tzinfo=None)
        except Exception:
            continue

        if date < cutoff_12m:
            continue  # Only last 12 months

        month_key = date.strftime("%Y-%m")
        day_key = date.strftime("%Y-%m-%d")

        monthly_sales[store][month_key] += net_value
        monthly_orders[store][month_key] += 1
        store_totals[store] += net_value
        store_orders[store] += 1
        store_avg_ticket[store].append(net_value)

        if date >= cutoff_30d:
            daily_sales[store][day_key] += net_value

        # Products (only if we have details)
        doc_id = doc.get("document_id")
        products = product_details.get(doc_id, [])
        for p in products:
            pid = p.get("product_id", 0)
            qty = float(p.get("qty", 0) or 0)
            price = float(p.get("price", 0) or 0)
            disc = float(p.get("discount", 0) or 0)
            rev = qty * price * (1 - disc / 100)
            product_sales[pid]["qty"] += qty
            product_sales[pid]["revenue"] += rev
            product_sales[pid]["name"] = p.get("name", "")
            product_sales[pid]["reference"] = p.get("reference", "")
            product_by_store[pid][store]["qty"] += qty
            product_by_store[pid][store]["revenue"] += rev

    # Build sorted months list (last 12 months)
    all_months = sorted(set(
        m for store_data in monthly_sales.values() for m in store_data.keys()
    ))

    # Top 20 products by revenue
    top_products = sorted(
        [{"id": k, **v} for k, v in product_sales.items()],
        key=lambda x: x["revenue"], reverse=True
    )[:20]

    return {
        "generated_at": datetime.now().isoformat(),
        "months": all_months,
        "stores": list(TERMINALS.values()),
        "monthly_revenue": {store: {m: monthly_sales[store].get(m, 0) for m in all_months}
                            for store in TERMINALS.values()},
        "monthly_orders": {store: {m: monthly_orders[store].get(m, 0) for m in all_months}
                           for store in TERMINALS.values()},
        "store_totals": dict(store_totals),
        "store_orders": dict(store_orders),
        "store_avg_ticket": {store: (sum(v) / len(v) if v else 0)
                             for store, v in store_avg_ticket.items()},
        "daily_sales_30d": {store: dict(daily_sales[store]) for store in TERMINALS.values()},
        "top_products": top_products,
        "product_by_store": {
            str(k): dict(v) for k, v in list(product_by_store.items())[:20]
        },
    }

# ─── ENTRY POINT ────────────────────────────────────────────────────────────────
def main():
    start = time.time()
    token = get_token()

    print("\n📦 Extraindo documentos (2024-2026)...")
    all_docs = extract_documents(token)
    print(f"\n✅ Total de documentos extraídos: {len(all_docs)}")

    # Get product details for last 30 days only
    cutoff_30d = datetime.now() - timedelta(days=30)
    recent_docs = []
    for doc in all_docs:
        date_str = doc.get("date", "")
        try:
            date = datetime.fromisoformat(date_str.replace("+0000", "+00:00").replace("+0100", "+01:00"))
            if date.replace(tzinfo=None) >= cutoff_30d:
                recent_docs.append(doc)
        except Exception:
            pass

    print(f"\n🔍 Buscando produtos dos últimos 30 dias ({len(recent_docs)} documentos)...")
    product_details = {}
    for doc_type in ["simplifiedInvoices", "invoiceReceipts", "invoices"]:
        type_docs = [d for d in recent_docs if d.get("_doc_type") == doc_type]
        if type_docs:
            ids = [d["document_id"] for d in type_docs]
            print(f"  📋 {doc_type}: {len(ids)} documentos...")
            details = fetch_product_details(token, ids, doc_type)
            product_details.update(details)

    print(f"\n📊 Agregando dados...")
    dashboard_data = aggregate(all_docs, product_details)

    output_path = "dashboard_data.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dashboard_data, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - start
    print(f"\n✅ Dados guardados em {output_path}")
    print(f"⏱  Tempo total: {elapsed:.1f}s")
    print(f"📈 Resumo:")
    for store, total in dashboard_data["store_totals"].items():
        orders = dashboard_data["store_orders"].get(store, 0)
        print(f"  {store}: {total:,.2f}€ ({orders} vendas)")

if __name__ == "__main__":
    main()
