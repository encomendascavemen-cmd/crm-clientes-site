#!/usr/bin/env python3
"""
Moloni → Meta Offline Conversions
Envia vendas das lojas físicas Cavemen ao Meta via Conversions API.
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

# ─── CONFIG META ────────────────────────────────────────────────────────────────
META_DATASET_ID   = os.environ.get("META_DATASET_ID", "314882189045033")
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN", "")
META_API_VERSION  = "v19.0"
META_BASE_URL     = f"https://graph.facebook.com/{META_API_VERSION}"

# Ficheiro para tracking de eventos já enviados (evita duplicados)
SENT_EVENTS_FILE  = "meta_sent_events.json"

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

    # País: Portugal
    user_data["country"] = sha256("pt")

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

def get_customer(token, customer_id):
    if not customer_id:
        return {}
    data = api_post("customers/getOne", token, {"customer_id": customer_id})
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict):
        return data
    return {}

# ─── DEDUP ──────────────────────────────────────────────────────────────────────
def load_sent_events():
    try:
        with open(SENT_EVENTS_FILE) as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def save_sent_events(sent: set):
    with open(SENT_EVENTS_FILE, "w") as f:
        json.dump(list(sent), f)

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

    # Valor total
    try:
        value = float(doc.get("global_discount_value") or doc.get("net_value") or 0)
        if value <= 0:
            # fallback: somar produtos
            products = doc.get("products") or []
            value = sum(float(p.get("price", 0)) * float(p.get("qty", 1)) for p in products)
    except Exception:
        value = 0.0

    if value <= 0:
        return None

    event_id = f"moloni_{doc.get('document_id') or doc.get('id')}"

    return {
        "event_name": "Purchase",
        "event_time": event_time,
        "event_id": event_id,  # para deduplicação no Meta
        "action_source": "physical_store",
        "user_data": user_data,
        "custom_data": {
            "value": round(value, 2),
            "currency": "EUR",
            "store": store_name,
        },
    }

# ─── ENVIO PARA META ────────────────────────────────────────────────────────────
def send_to_meta(events: list[dict]) -> dict:
    """Envia até 1000 eventos por chamada."""
    url = f"{META_BASE_URL}/{META_DATASET_ID}/events"
    payload = {
        "access_token": META_ACCESS_TOKEN,
        "data": json.dumps(events),
    }

    r = requests.post(url, data=payload, timeout=30)
    return r.json()

def send_in_batches(events: list[dict], batch_size: int = 1000):
    total = len(events)
    sent = 0
    errors = 0

    for i in range(0, total, batch_size):
        batch = events[i:i + batch_size]
        result = send_to_meta(batch)

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
    print("Cavemen Store — Meta Offline Conversions")
    print("=" * 60)

    # Apenas últimos 7 dias (limite do Meta CAPI)
    current_year = datetime.now().year
    years = [current_year]
    print(f"A processar ano {current_year} (Meta aceita só últimos 7 dias)")

    token = get_token()
    sent_ids = load_sent_events()
    all_events = []

    # Tipos de documento a processar
    doc_types = ["simplifiedInvoices", "invoiceReceipts", "invoices"]

    customer_cache = {}

    for doc_type in doc_types:
        for year in years:
            print(f"\nA buscar {doc_type} ({year})...")
            docs = fetch_documents_by_year(token, doc_type, year)
            print(f"  {len(docs)} documentos encontrados")

        for doc in docs:
            # Filtrar apenas lojas físicas
            terminal_id = doc.get("associated_documents", [{}])
            terminal_id = doc.get("terminal_id") or 0
            if terminal_id not in PHYSICAL_TERMINALS:
                continue

            store_name = PHYSICAL_TERMINALS[terminal_id]
            doc_id = str(doc.get("document_id") or doc.get("id", ""))
            event_key = f"{doc_type}_{doc_id}"

            if event_key in sent_ids:
                continue  # já enviado

            # Buscar cliente (com cache)
            customer_id = doc.get("customer_id")
            if customer_id not in customer_cache:
                customer_cache[customer_id] = get_customer(token, customer_id)
            customer = customer_cache[customer_id]

            event = doc_to_meta_event(doc, customer, store_name)
            if event:
                all_events.append((event_key, event))

    # Filtrar apenas últimos 7 dias
    cutoff = int((datetime.now() - timedelta(days=7)).timestamp())
    all_events = [(k, e) for k, e in all_events if e["event_time"] >= cutoff]

    print(f"\nTotal de eventos a enviar (últimos 7 dias): {len(all_events)}")
    if not all_events:
        print("Nada a enviar.")
        return

    # Separar keys dos eventos
    event_keys = [k for k, _ in all_events]
    events     = [e for _, e in all_events]

    print("\nA enviar ao Meta...")
    sent_count, error_count = send_in_batches(events)

    # Guardar IDs enviados com sucesso
    sent_ids.update(event_keys)
    save_sent_events(sent_ids)

    print("\n" + "=" * 60)
    print(f"Concluído: {sent_count} eventos enviados, {error_count} erros")
    print("=" * 60)

if __name__ == "__main__":
    main()
