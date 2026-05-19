#!/usr/bin/env python3
"""
Sugere categorias para produtos 'Sem Categoria' com base no nome.
Gera um JSON com as sugestões para o relatório.
"""
import json, re

# Regras de mapeamento: (padrão regex no nome, categoria sugerida)
# Ordem importa — a primeira match ganha
RULES = [
    # Fatos (incluindo trespasse)
    (r"^FATO\b", "Fatos"),
    # Coletes de alfaiataria
    (r"^COLETE\b", "Fatos"),
    # Blazers
    (r"^BLAZER\b", "Blazers"),
    # Calças chino
    (r"CALÇA CHINO|CALÇÕES CHINO", "Calças chino"),
    # Calças de ganga
    (r"CALÇA DE GANGA|CALÇA GANGA|CALÇÕES DE GANGA", "Calças de ganga"),
    # Calças de sarja
    (r"CALÇA DE SARJA|CALÇÕES SARJA", "Calças de sarja"),
    # Calças clássicas / alfaiataria
    (r"CALÇA CLÁSSICA|CALÇA DE ALFAIATARIA|CALÇA FATO\b", "Calças de tecido"),
    # Calças de tecido
    (r"CALÇA DE TECIDO|CALÇA TECIDO|CALÇA COMFORT|CALÇA CROPPED", "Calças de tecido"),
    # Calções (fato de treino e outros)
    (r"^CALÇÕES|^CALÇÃO", "Calções"),
    # Camisas de manga curta
    (r"CAMISA MANGA CURTA|CAMISA MC\b", "Camisas de manga curta"),
    # Camisas
    (r"^CAMISA\b|^CAMISEIRO\b", "Camisas"),
    # T-shirts
    (r"^T-SHIRT\b", "T-shirts"),
    # Polos
    (r"^POLO\b", "Polos"),
    # Gola alta / Meia gola
    (r"^GOLA ALTA|MEIA GOLA", "Gola alta / Meia gola"),
    # Camisolas meia gola
    (r"CAMISOLA MEIA GOLA", "Gola alta / Meia gola"),
    # Camisolas e malhas
    (r"^CAMISOLA\b", "Camisolas e malhas"),
    # Cardigans
    (r"^CARDIGAN\b", "Cardigans"),
    # Sweats e Hoodies
    (r"^SWEAT\b|^HOODIE\b", "Sweats e Hoodies"),
    # Sobretudos
    (r"^SOBRETUDO\b", "Sobretudos e casacos"),
    # Casacos (fato de treino e outros)
    (r"^CASACO\b", "Abrigos e casacos"),
    # Sapatilhas
    (r"^SAPATILHA\b", "Calçado"),
    # Sapatos
    (r"^SAPATO\b", "Sapatos"),
    # Gravatas
    (r"^GRAVATA", "Lenços de bolso"),
    # Lenços de bolso
    (r"^LENÇO DE BOLSO", "Lenços de bolso"),
    # Gift Card
    (r"GIFT.?CARD", "Gift Card"),
    # Cachecóis
    (r"^CACHECOL", "Abrigos e casacos"),
    # Bonés
    (r"^BONÉ\b", "Abrigos e casacos"),
    # Perfumes
    (r"^PERFUME\b", "Packs"),
    # Pulseiras
    (r"^PULSEIRA\b|^FIO\b", "Pulseiras"),
    # Sacos e embalagem
    (r"^SACO\b|^PORTA-FATOS", "Malas & Necessaires"),
    # Calçado genérico
    (r"^CALÇADO\b", "Calçado"),
    # Fato de treino (calça/casaco/calções)
    (r"FATO DE TREINO|FATO TREINO", "Sport"),
]


def suggest_category(name):
    """Retorna a categoria sugerida ou None se não houver match."""
    upper = name.upper().strip()
    for pattern, cat in RULES:
        if re.search(pattern, upper):
            return cat
    return None


def run():
    with open("products_data_v2.json") as f:
        data = json.load(f)

    no_cat = [p for p in data["products"] if p.get("category_name", "") == "Sem Categoria"]

    results = {}  # cat -> list of products
    unmatched = []

    for p in no_cat:
        suggested = suggest_category(p["name"])
        if suggested:
            if suggested not in results:
                results[suggested] = []
            results[suggested].append({
                "product_id": p["product_id"],
                "name": p["name"],
                "reference": p.get("reference", ""),
                "revenue": round(p.get("revenue", 0), 2),
                "qty": round(p.get("qty", 0)),
            })
        else:
            unmatched.append({
                "product_id": p["product_id"],
                "name": p["name"],
                "reference": p.get("reference", ""),
                "revenue": round(p.get("revenue", 0), 2),
                "qty": round(p.get("qty", 0)),
            })

    # Sort products within each category by revenue desc
    for cat in results:
        results[cat].sort(key=lambda x: -x["revenue"])

    # Sort unmatched by revenue desc
    unmatched.sort(key=lambda x: -x["revenue"])

    # Summary
    total_matched = sum(len(v) for v in results.values())
    total_rev_matched = sum(p["revenue"] for v in results.values() for p in v)
    total_rev_unmatched = sum(p["revenue"] for p in unmatched)

    output = {
        "total_sem_categoria": len(no_cat),
        "total_sugeridos": total_matched,
        "total_sem_sugestao": len(unmatched),
        "receita_sugeridos": round(total_rev_matched, 2),
        "receita_sem_sugestao": round(total_rev_unmatched, 2),
        "categorias": {},
        "sem_sugestao": unmatched,
    }

    # Sort categories by total revenue
    for cat in sorted(results.keys(), key=lambda c: -sum(p["revenue"] for p in results[c])):
        prods = results[cat]
        output["categorias"][cat] = {
            "total_produtos": len(prods),
            "receita_total": round(sum(p["revenue"] for p in prods), 2),
            "produtos": prods,
        }

    with open("categorize_suggestions.json", "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✅ Sugestões geradas: {total_matched} produtos mapeados, {len(unmatched)} sem sugestão")
    print(f"   Receita mapeada: {total_rev_matched:,.2f}€")
    print(f"   Receita sem sugestão: {total_rev_unmatched:,.2f}€")
    print(f"\nCategorias sugeridas:")
    for cat, info in output["categorias"].items():
        print(f"  {cat}: {info['total_produtos']} produtos ({info['receita_total']:,.2f}€)")
    if unmatched:
        print(f"\nSem sugestão ({len(unmatched)} produtos):")
        for p in unmatched[:15]:
            print(f"  {p['name']} ({p['revenue']:,.2f}€)")


if __name__ == "__main__":
    run()
