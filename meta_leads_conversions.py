#!/usr/bin/env python3
"""
Moloni → Meta Offline Conversions (Conta Leads)
Envia ao pixel dedicado da Conta Leads apenas as vendas que incluem
o produto "Fato Noivo", via Conversions API.
"""

import os
import requests
import json
import time
import hashlib
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Optional

# ─── CONFIG MOLONI ──────────────────────────────────────────────────────────────
CLIENT_ID     = os.environ.get("MOLONI_CLIENT_ID", "cavemenunipessoallda")
CLIENT_SECRET = os.environ.get("MOLONI_CLIENT_SECRET", "")
USERNAME      = os.environ.get("MOLONI_USERNAME", "encomendas@cavemenstore.com")
PASSWORD      = os.environ.get("MOLONI_PASSWORD", "")
COMPANY_ID    = int(os.environ.get("MOLONI_COMPANY_ID", "274475"))
BASE_URL      = "https://api.moloni.pt/v1"

# Apenas lojas físicas (excluir Online terminal_id=0)
PHYSICAL_TERMINALS = {
    125906: "Guimarães",
    125908: "Braga",
    148908: "Porto",
}

# ─── CONFIG META (Conta Leads) ──────────────────────────────────────────────────
META_LEADS_DATASET_ID = os.environ.get("META_LEADS_DATASET_ID", "1923843178285898")  # Pixel Leads (Conta Leads)
META_LEADS_ACCESS_TOKEN = (
    os.environ.get("META_LEADS_ACCESS_TOKEN")
    or os.environ.get("META_ACCESS_TOKEN", "")
)
META_API_VERSION = "v19.0"
META_BASE_URL    = f"https://graph.facebook.com/{META_API_VERSION}"

# Só enviar vendas que incluam este produto
TARGET_PRODUCT = "fato noivo"

# ─── HASHING (obrigatório pelo Meta) ───────────────────────────────────────────
def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def normalize_email(email: str) -> str:
    return email.strip().lower()

def normalize_phone(phone: str) -> str:
    # Remove tudo exceto dígitos, adiciona prefixo PT se necessário
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("351"):
        return digits
    if len(digits) == 9:
        return "351" + digits
    return digits

def normalize_name_part(name: str) -> str:
    # lowercase, remove acentos, remove pontuação
    nfkd = unicodedata.normalize("NFKD", name.lower().strip())
    return "".join(c for c in nfkd if not unicodedata.combining(c))

def build_user_data(customer: dict) -> dict:
    """Constrói user_data com campos hasheados para matching."""
    user_data = {}

    # Email — principal e secundário
    email = (customer.get("email") or customer.get("contact_email") or "").strip()
    if email and "@" in email:
        user_data["em"] = sha256(normalize_email(email))

    FAKE_PHONES = {"999999990", "000000000", "111111111"}
    # Telefone — principal, secundário e mobile
    phone = (customer.get("phone") or customer.get("contact_phone") or customer.get("mobile_phone") or "").strip()
    phone_digits = re.sub(r"\D", "", phone)
    if phone and phone_digits not in FAKE_PHONES and len(phone_digits) >= 9:
        user_data["ph"] = sha256(normalize_phone(phone))

    name = customer.get("name", "").strip()
    if name:
        parts = name.split()
        if parts:
            user_data["fn"] = sha256(normalize_name_part(parts[0]))
        if len(parts) > 1:
            user_data["ln"] = sha256(normalize_name_part(parts[-1]))

    # Extern ID — ID do cliente no Moloni (identificador estável)
    extern_id = str(customer.get("customer_id") or customer.get("id") or "").strip()
    if extern_id and extern_id != "0":
        user_data["external_id"] = sha256(extern_id)

    # País: Portugal
    user_data["country"] = sha256("pt")

    # Cidade e código postal
    city = (customer.get("city") or "").strip()
    if city and city.lower() not in ["desconhecido", "unknown", ""]:
        user_data["ct"] = sha256(normalize_name_part(city))

    zip_code = re.sub(r"\D", "", (customer.get("zip_code") or ""))
    if zip_code and zip_code not in ["0000000", "0000-000", ""]:
        user_data["zp"] = sha256(zip_code)

    return user_data

# ─── AUTH MOLONI ────────────────────────────────────────────────────────────────
def get_token():
    print("Autenticando na API Moloni...")
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
    print("Token obtido.")
    return data["access_token"]

# ─── MOLONI API ─────────────────────────────────────────────────────────────────
def api_post(endpoint, token, data=None):
    payload = {"company_id": COMPANY_ID}
    if data:
        payload.update(data)
    for attempt in range(3):
        try:
            r = requests.post(
                f"{BASE_URL}/{endpoint}/",
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
    """Busca todos os documentos de um tipo para um dado ano (paginado)."""
    results = []
    offset = 0
    page_size = 50

    while True:
        batch = api_post(f"{doc_type}/getAll", token, {
            "qty": page_size,
            "offset": offset,
            "year": year,
        })
        if not batch or not isinstance(batch, list):
            break
        results.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    return results

def get_doc_products(token, doc_type, doc_id):
    """Busca os produtos de um documento específico."""
    data = api_post(f"{doc_type}/getOne", token, {"document_id": doc_id})
    if isinstance(data, list) and data:
        return data[0].get("products") or []
    if isinstance(data, dict):
        return data.get("products") or []
    return []

def get_customer(token, customer_id):
    if not customer_id:
        return {}
    data = api_post("customers/getOne", token, {"customer_id": customer_id})
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict):
        return data
    return {}

# ─── FILTRO FATO NOIVO ──────────────────────────────────────────────────────────
def has_target_product(products: list) -> bool:
    """True se algum produto do documento for o Fato Noivo."""
    for p in products or []:
        name = normalize_name_part(p.get("name") or "")
        if TARGET_PRODUCT in name:
            return True
    return False

# Nota: deduplicação feita pelo Meta via event_id único por documento

# ─── CONVERTER DOCUMENTO → EVENTO META ─────────────────────────────────────────
def doc_to_meta_event(doc: dict, customer: dict, store_name: str) -> Optional[dict]:
    """Converte um documento Moloni num evento Meta CAPI."""

    # Só documentos com cliente identificado
    user_data = build_user_data(customer)
    if not user_data.get("em") and not user_data.get("ph"):
        return None  # sem dados de matching, inútil enviar

    # Data da venda → unix timestamp (formato: "2026-01-11T00:00:00+0000")
    date_str = doc.get("date", "")
    try:
        clean = date_str.replace("+0000", "+00:00").replace("+0100", "+01:00")
        event_time = int(datetime.fromisoformat(clean).timestamp())
    except Exception:
        return None

    # Valor e produtos
    products = doc.get("products") or []
    try:
        value = float(doc.get("net_value") or 0)
        if value <= 0:
            value = sum(float(p.get("price", 0)) * float(p.get("qty", 1)) for p in products)
    except Exception:
        value = 0.0

    if value <= 0:
        return None

    # Produtos para o Meta (content_ids, contents, num_items)
    contents = []
    for p in products:
        name = (p.get("name") or "").strip()
        qty = int(float(p.get("qty") or 1))
        price = round(float(p.get("price") or 0), 2)
        ref = (p.get("reference") or p.get("ean") or name or "").strip()
        if name:
            contents.append({
                "id": ref,
                "quantity": qty,
                "item_price": price,
                "title": name,
            })

    event_id = f"moloni_{doc.get('document_id') or doc.get('id')}"

    custom_data = {
        "value": round(value, 2),
        "currency": "EUR",
        "store": store_name,
        "num_items": sum(int(float(p.get("qty") or 1)) for p in products),
    }
    if contents:
        custom_data["contents"] = contents
        custom_data["content_type"] = "product"

    return {
        "event_name": "Purchase",
        "event_time": event_time,
        "event_id": event_id,
        "action_source": "physical_store",
        "user_data": user_data,
        "custom_data": custom_data,
    }

# ─── ENVIO PARA META ────────────────────────────────────────────────────────────
def send_to_meta(events: list[dict], dataset_id: str) -> dict:
    """Envia até 1000 eventos para um dataset."""
    url = f"{META_BASE_URL}/{dataset_id}/events"
    payload = {
        "access_token": META_LEADS_ACCESS_TOKEN,
        "data": json.dumps(events),
    }
    r = requests.post(url, data=payload, timeout=30)
    return r.json()

def send_in_batches(events: list[dict], dataset_id: str, batch_size: int = 1000):
    total = len(events)
    sent = 0
    errors = 0

    for i in range(0, total, batch_size):
        batch = events[i:i + batch_size]
        result = send_to_meta(batch, dataset_id)

        events_received = result.get("events_received", 0)
        sent += events_received

        if "error" in result:
            print(f"  ERRO Meta: {result['error']}")
            errors += len(batch)
        else:
            print(f"  Batch {i // batch_size + 1}: {events_received}/{len(batch)} aceites pelo Meta")

        time.sleep(0.5)  # respeitar rate limits

    return sent, errors

# ─── MAIN ────────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("Cavemen Store — Meta Offline Conversions (Conta Leads / Fato Noivo)")
    print("=" * 60)

    if not META_LEADS_DATASET_ID:
        raise RuntimeError("META_LEADS_DATASET_ID não definido — configurar o ID do pixel da Conta Leads")
    if not META_LEADS_ACCESS_TOKEN:
        raise RuntimeError("META_LEADS_ACCESS_TOKEN/META_ACCESS_TOKEN não definido")

    # Apenas últimos 7 dias (limite do Meta CAPI)
    current_year = datetime.now().year
    years = [current_year]
    print(f"A processar ano {current_year} (Meta aceita só últimos 7 dias)")

    token = get_token()
    all_events = []
    customer_cache = {}
    doc_types = ["simplifiedInvoices", "invoiceReceipts", "invoices"]
    cutoff = int((datetime.now() - timedelta(days=7)).timestamp())

    # Diagnóstico: distinguir "sem vendas" de "vendas sem contacto/fora de janela"
    diag_fato_total = 0        # docs com Fato Noivo (qualquer data)
    diag_fato_recent = 0       # + dentro dos últimos 7 dias
    diag_dropped_no_match = 0  # + Fato Noivo recente mas sem email/telefone

    for doc_type in doc_types:
        for year in years:
            print(f"\nA buscar {doc_type} ({year})...")
            docs = fetch_documents_by_year(token, doc_type, year)
            print(f"  {len(docs)} documentos encontrados")

            for doc in docs:
                terminal_id = doc.get("terminal_id") or 0
                if terminal_id not in PHYSICAL_TERMINALS:
                    continue

                store_name = PHYSICAL_TERMINALS[terminal_id]

                # Garantir que temos produtos (vêm no getAll mas por precaução)
                if not doc.get("products"):
                    doc_id = doc.get("document_id") or doc.get("id")
                    doc["products"] = get_doc_products(token, doc_type, doc_id)

                # Só vendas que incluam o Fato Noivo
                if not has_target_product(doc.get("products")):
                    continue

                diag_fato_total += 1

                customer_id = doc.get("customer_id")
                if customer_id not in customer_cache:
                    customer_cache[customer_id] = get_customer(token, customer_id)
                customer = customer_cache[customer_id]

                event = doc_to_meta_event(doc, customer, store_name)
                if event and event["event_time"] >= cutoff:
                    all_events.append(event)
                else:
                    # Diagnóstico: perceber porque não foi enviado
                    ud = build_user_data(customer)
                    is_recent = False
                    try:
                        clean = doc.get("date", "").replace("+0000", "+00:00").replace("+0100", "+01:00")
                        is_recent = int(datetime.fromisoformat(clean).timestamp()) >= cutoff
                    except Exception:
                        pass
                    if is_recent:
                        diag_fato_recent += 1
                        if not ud.get("em") and not ud.get("ph"):
                            diag_dropped_no_match += 1

    diag_fato_recent += len(all_events)
    print("\n" + "-" * 60)
    print("DIAGNÓSTICO Fato Noivo:")
    print(f"  Documentos com Fato Noivo (todo o ano):        {diag_fato_total}")
    print(f"  Desses, dentro dos últimos 7 dias:             {diag_fato_recent}")
    print(f"  Recentes descartados por falta de email/tel:   {diag_dropped_no_match}")
    print("-" * 60)

    print(f"\nTotal de vendas Fato Noivo a enviar (últimos 7 dias): {len(all_events)}")
    if not all_events:
        print("Nada a enviar.")
        return

    print(f"\nA enviar ao Pixel Conta Leads ({META_LEADS_DATASET_ID})...")
    sent, errors = send_in_batches(all_events, META_LEADS_DATASET_ID)

    print("\n" + "=" * 60)
    print(f"Pixel Conta Leads: {sent} eventos enviados, {errors} erros")
    print("=" * 60)

if __name__ == "__main__":
    main()
