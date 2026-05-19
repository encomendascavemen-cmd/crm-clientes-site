#!/usr/bin/env python3
"""
Migra os dados do dashboard_data.json e products_data.json
para o sistema de cache mensal usado pelo server.py.
Evita ter de re-buscar tudo da API Moloni.
"""
import requests, json, os, re, time
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

CLIENT_ID     = "cavemenunipessoallda"
CLIENT_SECRET = "a7678d73814b0f8179407c63b6242ca83690b61d"
USERNAME      = "encomendas@cavemenstore.com"
PASSWORD      = "7+LVn*QU+4sdrXN"
COMPANY_ID    = 274475
BASE_URL      = "https://api.moloni.pt/v1"
CACHE_DIR     = os.path.join(os.path.dirname(__file__), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

TERMINALS = {125906:"Guimarães", 125908:"Braga", 148908:"Porto", 0:"Online"}

def get_token():
    r = requests.get(f"{BASE_URL}/grant/", params={
        "grant_type":"password","client_id":CLIENT_ID,
        "client_secret":CLIENT_SECRET,"username":USERNAME,"password":PASSWORD,
    }, timeout=15)
    return r.json()["access_token"]

def api_post(endpoint, token, data=None):
    payload = {"company_id": COMPANY_ID}
    if data: payload.update(data)
    for attempt in range(3):
        try:
            r = requests.post(f"{BASE_URL}/{endpoint}/",
                params={"access_token":token}, data=payload, timeout=30)
            if r.status_code == 429:
                time.sleep(2**attempt); continue
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt == 2: return None
            time.sleep(1)

def parse_date(s):
    if not s: return None
    clean = re.sub(r'[+-]\d{2}:?\d{2}$|Z$','', s.replace("T"," ")).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S","%Y-%m-%d"):
        try: return datetime.strptime(clean[:19], fmt)
        except: pass
    return None

def fetch_month_docs(token, year, month):
    """Fetch all docs for a specific month with product details."""
    print(f"  📥 {year}-{month:02d}...")
    all_docs = []
    for doc_type in ["simplifiedInvoices","invoiceReceipts","invoices"]:
        offset = 0
        while True:
            batch = api_post(f"{doc_type}/getAll", token,
                             {"qty":50,"offset":offset,"year":year})
            if not batch or not isinstance(batch, list): break
            for d in batch:
                dt = parse_date(d.get("date",""))
                if dt and dt.month == month and float(d.get("net_value",0) or 0) > 0:
                    d["_doc_type"] = doc_type
                    all_docs.append(d)
            if len(batch) < 50: break
            offset += 50

    ep_map = {
        "simplifiedInvoices":"simplifiedInvoices/getOne",
        "invoiceReceipts":"invoiceReceipts/getOne",
        "invoices":"invoices/getOne",
    }

    def fetch_one(doc):
        ep = ep_map.get(doc["_doc_type"],"simplifiedInvoices/getOne")
        data = api_post(ep, token, {"document_id":doc["document_id"]})
        products = []
        if data and isinstance(data, dict):
            products = data.get("products", [])
        return doc, products

    docs_with_prods = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(fetch_one,d): d for d in all_docs}
        for f in as_completed(futures):
            doc, prods = f.result()
            doc["_products"] = prods
            docs_with_prods.append(doc)

    return docs_with_prods

def main():
    print("🪨 Cavemen Store — Migração para cache mensal")

    # List which months already have cache
    cached = set()
    for f in os.listdir(CACHE_DIR):
        if f.endswith(".json"):
            cached.add(f.replace(".json",""))

    # Determine which months to fetch (2024-01 to now)
    now = datetime.now()
    months_needed = []
    for year in [2024, 2025, 2026]:
        for month in range(1, 13):
            key = f"{year}-{month:02d}"
            if key > now.strftime("%Y-%m"):
                break
            if key not in cached:
                months_needed.append((year, month))

    if not months_needed:
        print("✅ Todos os meses já estão em cache!")
        return

    print(f"\n📅 {len(months_needed)} meses a buscar: {[f'{y}-{m:02d}' for y,m in months_needed]}")
    print("⏱  Estimativa: ~", len(months_needed) * 3, "min\n")

    token = get_token()
    print(f"✅ Token OK")

    for i, (year, month) in enumerate(months_needed):
        key = f"{year}-{month:02d}"
        try:
            docs = fetch_month_docs(token, year, month)
            cache_data = {
                "year": year, "month": month,
                "fetched_at": datetime.now().isoformat(),
                "docs": docs,
            }
            with open(os.path.join(CACHE_DIR, f"{key}.json"), "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False)
            print(f"  ✅ {key}: {len(docs)} documentos")
        except Exception as e:
            print(f"  ⚠️  {key}: erro — {e}")

        # Refresh token periodically
        if (i + 1) % 5 == 0:
            token = get_token()

    print("\n✅ Migração concluída!")
    print("🌐 Agora podes correr: python3 server.py")
    print("   E abrir: http://localhost:5000")

if __name__ == "__main__":
    main()
