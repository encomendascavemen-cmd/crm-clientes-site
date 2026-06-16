#!/usr/bin/env python3
"""
Moloni → Google Ads Enhanced Conversions (lojas físicas)
Envia vendas das lojas físicas Cavemen ao Google Ads via ConversionUploadService.
"""

import os
import re
import hashlib
import unicodedata
import time
import requests
import warnings
warnings.filterwarnings("ignore")
from datetime import datetime, timedelta
from typing import Optional

# ─── CONFIG MOLONI ──────────────────────────────────────────────────────────────
MOLONI_CLIENT_ID     = os.environ.get("MOLONI_CLIENT_ID", "cavemenunipessoallda")
MOLONI_CLIENT_SECRET = os.environ.get("MOLONI_CLIENT_SECRET", "")
MOLONI_USERNAME      = os.environ.get("MOLONI_USERNAME", "encomendas@cavemenstore.com")
MOLONI_PASSWORD      = os.environ.get("MOLONI_PASSWORD", "")
COMPANY_ID           = int(os.environ.get("MOLONI_COMPANY_ID", "274475"))
MOLONI_BASE_URL      = "https://api.moloni.pt/v1"

PHYSICAL_TERMINALS = {
    125906: "Guimarães",
    125908: "Braga",
    148908: "Porto",
}

# ─── CONFIG GOOGLE ADS ──────────────────────────────────────────────────────────
GOOGLE_DEVELOPER_TOKEN = os.environ.get("GOOGLE_DEVELOPER_TOKEN", "")
GOOGLE_CLIENT_ID       = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET   = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REFRESH_TOKEN   = os.environ.get("GOOGLE_REFRESH_TOKEN", "")
GOOGLE_CUSTOMER_ID     = os.environ.get("GOOGLE_CUSTOMER_ID", "9586857901")

# ID da conversion action "Vendas Loja Fisica (Offline)" criada via API
CONVERSION_ACTION_ID   = os.environ.get("GOOGLE_CONVERSION_ACTION_ID", "7650202502")

# ─── HASHING ────────────────────────────────────────────────────────────────────
def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def normalize_email(email: str) -> str:
    return email.strip().lower()

def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("351"):
        return digits
    if len(digits) == 9:
        return "351" + digits
    return digits

# ─── GOOGLE ADS CLIENT ──────────────────────────────────────────────────────────
def get_google_ads_client():
    from google.ads.googleads.client import GoogleAdsClient
    config = {
        "developer_token":   GOOGLE_DEVELOPER_TOKEN,
        "client_id":         GOOGLE_CLIENT_ID,
        "client_secret":     GOOGLE_CLIENT_SECRET,
        "refresh_token":     GOOGLE_REFRESH_TOKEN,
        "login_customer_id": GOOGLE_CUSTOMER_ID,
        "use_proto_plus":    True,
    }
    return GoogleAdsClient.load_from_dict(config)

# ─── UPLOAD CONVERSÕES ───────────────────────────────────────────────────────────
def upload_conversions(client, customer_id: str, conversions: list) -> dict:
    """Envia conversões via ConversionUploadService com user identifiers."""
    upload_service = client.get_service("ConversionUploadService")
    conversion_action = f"customers/{customer_id}/conversionActions/{CONVERSION_ACTION_ID}"

    click_conversions = []
    for conv in conversions:
        cc = client.get_type("ClickConversion")
        cc.conversion_action = conversion_action
        cc.conversion_date_time = conv["conversion_datetime"]
        cc.conversion_value = conv["value"]
        cc.currency_code = "EUR"

        # User identifiers (hashed)
        for identifier in conv["user_identifiers"]:
            ui = client.get_type("UserIdentifier")
            if "hashed_email" in identifier:
                ui.hashed_email = identifier["hashed_email"]
            elif "hashed_phone_number" in identifier:
                ui.hashed_phone_number = identifier["hashed_phone_number"]
            cc.user_identifiers.append(ui)

        click_conversions.append(cc)

    # Enviar em batches de 2000
    total_sent = 0
    total_errors = 0
    batch_size = 2000

    for i in range(0, len(click_conversions), batch_size):
        batch = click_conversions[i:i + batch_size]
        try:
            response = upload_service.upload_click_conversions(
                customer_id=customer_id,
                conversions=batch,
                partial_failure=True,
            )
            if response.partial_failure_error.message:
                print(f"  Avisos: {response.partial_failure_error.message[:300]}")
            total_sent += len(batch)
            print(f"  Batch {i // batch_size + 1}: {len(batch)} conversões enviadas")
        except Exception as e:
            print(f"  Erro no batch {i // batch_size + 1}: {e}")
            total_errors += len(batch)

    return {"sent": total_sent, "errors": total_errors}

# ─── AUTH MOLONI ────────────────────────────────────────────────────────────────
def get_moloni_token():
    print("Autenticando na API Moloni...")
    r = requests.get(f"{MOLONI_BASE_URL}/grant/", params={
        "grant_type":    "password",
        "client_id":     MOLONI_CLIENT_ID,
        "client_secret": MOLONI_CLIENT_SECRET,
        "username":      MOLONI_USERNAME,
        "password":      MOLONI_PASSWORD,
    })
    r.raise_for_status()
    data = r.json()
    if "access_token" not in data:
        raise RuntimeError(f"Auth falhou: {data}")
    print("Token Moloni obtido.")
    return data["access_token"]

def api_post(endpoint, token, data=None):
    payload = {"company_id": COMPANY_ID}
    if data:
        payload.update(data)
    for attempt in range(3):
        try:
            r = requests.post(
                f"{MOLONI_BASE_URL}/{endpoint}/",
                params={"access_token": token},
                data=payload,
                timeout=30,
            )
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt == 2:
                return None
            time.sleep(1)
    return None

def fetch_documents_by_year(token, doc_type, year):
    results = []
    offset = 0
    page_size = 50
    while True:
        batch = api_post(f"{doc_type}/getAll", token, {"qty": page_size, "offset": offset, "year": year})
        if not batch or not isinstance(batch, list):
            break
        results.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return results

def get_customer(token, customer_id):
    if not customer_id:
        return {}
    data = api_post("customers/getOne", token, {"customer_id": customer_id})
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict):
        return data
    return {}

def get_doc_products(token, doc_type, doc_id):
    data = api_post(f"{doc_type}/getOne", token, {"document_id": doc_id})
    if isinstance(data, list) and data:
        return data[0].get("products") or []
    if isinstance(data, dict):
        return data.get("products") or []
    return []

# ─── CONVERTER DOCUMENTO → CONVERSÃO ────────────────────────────────────────────
def doc_to_conversion(doc: dict, customer: dict) -> Optional[dict]:
    FAKE_PHONES = {"999999990", "000000000", "111111111"}
    user_identifiers = []

    email = (customer.get("email") or customer.get("contact_email") or "").strip()
    if email and "@" in email:
        user_identifiers.append({"hashed_email": sha256(normalize_email(email))})

    phone = (customer.get("phone") or customer.get("contact_phone") or customer.get("mobile_phone") or "").strip()
    phone_digits = re.sub(r"\D", "", phone)
    if phone and phone_digits not in FAKE_PHONES and len(phone_digits) >= 9:
        user_identifiers.append({"hashed_phone_number": sha256(normalize_phone(phone))})

    if not user_identifiers:
        return None

    date_str = doc.get("date", "")
    try:
        clean = date_str.replace("+0000", "+00:00").replace("+0100", "+01:00")
        dt = datetime.fromisoformat(clean)
        # Google Ads formato: "yyyy-MM-dd HH:mm:ss+ZZ:ZZ"
        conversion_datetime = dt.strftime("%Y-%m-%d %H:%M:%S+00:00")
    except Exception:
        return None

    products = doc.get("products") or []
    try:
        value = float(doc.get("net_value") or 0)
        if value <= 0:
            value = sum(float(p.get("price", 0)) * float(p.get("qty", 1)) for p in products)
    except Exception:
        value = 0.0

    if value <= 0:
        return None

    return {
        "user_identifiers":    user_identifiers,
        "value":               round(value, 2),
        "conversion_datetime": conversion_datetime,
    }

# ─── MAIN ────────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("Cavemen Store — Google Ads Enhanced Conversions")
    print("=" * 60)

    current_year = datetime.now().year
    cutoff = int((datetime.now() - timedelta(days=90)).timestamp())
    print(f"A processar conversões dos últimos 90 dias")

    # Auth Google Ads
    print("\nA inicializar cliente Google Ads...")
    try:
        client = get_google_ads_client()
        print("Cliente Google Ads iniciado.")
    except Exception as e:
        print(f"Erro: {e}")
        return

    print(f"Conversion action: customers/{GOOGLE_CUSTOMER_ID}/conversionActions/{CONVERSION_ACTION_ID}")

    # Moloni
    try:
        moloni_token = get_moloni_token()
    except Exception as e:
        print(f"Erro Moloni: {e}")
        return

    all_conversions = []
    customer_cache = {}
    doc_types = ["simplifiedInvoices", "invoiceReceipts", "invoices"]

    for doc_type in doc_types:
        print(f"\nA buscar {doc_type} ({current_year})...")
        docs = fetch_documents_by_year(moloni_token, doc_type, current_year)
        print(f"  {len(docs)} documentos encontrados")

        for doc in docs:
            terminal_id = doc.get("terminal_id") or 0
            if terminal_id not in PHYSICAL_TERMINALS:
                continue

            date_str = doc.get("date", "")
            try:
                clean = date_str.replace("+0000", "+00:00").replace("+0100", "+01:00")
                doc_ts = int(datetime.fromisoformat(clean).timestamp())
                if doc_ts < cutoff:
                    continue
            except Exception:
                continue

            customer_id = doc.get("customer_id")
            if customer_id not in customer_cache:
                customer_cache[customer_id] = get_customer(moloni_token, customer_id)
            customer = customer_cache[customer_id]

            if not doc.get("products"):
                doc_id = doc.get("document_id") or doc.get("id")
                doc["products"] = get_doc_products(moloni_token, doc_type, doc_id)

            conv = doc_to_conversion(doc, customer)
            if conv:
                all_conversions.append(conv)

    print(f"\nTotal de conversões a enviar: {len(all_conversions)}")
    if not all_conversions:
        print("Nada a enviar.")
        return

    print("\nA enviar ao Google Ads...")
    result = upload_conversions(client, GOOGLE_CUSTOMER_ID, all_conversions)

    print("\n" + "=" * 60)
    print(f"✅ Enviadas: {result['sent']}")
    if result['errors']:
        print(f"⚠️  Erros:   {result['errors']}")
    print("=" * 60)

if __name__ == "__main__":
    main()
