#!/usr/bin/env python3
"""
Categorização personalizada de produtos (ignora categorias do Moloni).

Regras pedidas pelo cliente — aplicadas por ordem, primeira match ganha.
Qualquer produto que não bata em nenhuma regra → "Outros".
"""
import re

# Ordem IMPORTA: regras mais específicas primeiro.
# Cada regra: (padrão regex aplicado ao nome em UPPERCASE, categoria)
RULES = [
    # ─── Conjuntos ────────────────────────────────────────────────
    (r"^CONJUNTO",                                    "Conjuntos"),

    # ─── Sobrecamisas (antes de Camisas) ─────────────────────────
    (r"\bSOBRECAMISA",                                "Sobrecamisas"),

    # ─── Cardigan ────────────────────────────────────────────────
    (r"\bCARDIGAN",                                   "Cardigan"),

    # ─── Casaco de Felpa (fato de treino) ────────────────────────
    (r"\bCASACO DE FELPA",                            "CASACO DE FELPA - Fato de Treino"),

    # ─── Casacos (casacos, blusões, parkas, sobretudos) ──────────
    (r"^CASACO\b",                                    "Casacos"),
    (r"^BLUS(?:Ã|A)O",                                "Casacos"),
    (r"^PARKA",                                       "Casacos"),
    (r"^SOBRETUDO",                                   "Casacos"),

    # ─── Coletes ─────────────────────────────────────────────────
    (r"^COLETE",                                      "Coletes"),

    # ─── Perfumes ────────────────────────────────────────────────
    (r"^PERFUME|\bPERFUME\b",                         "Perfumes"),

    # ─── Botões de punho ─────────────────────────────────────────
    (r"^BOT(?:Ã|A)O|^BOT(?:Õ|O)ES DE PUNHO",          "Botões de punho"),

    # ─── Fato Noivo (antes de Fatos) ─────────────────────────────
    (r"^FATO .*NOIVO|^FATO NOIVO",                    "Fato Noivo"),

    # ─── Fatos (FATO SLIM..., FATO TRESPASSE...) ─────────────────
    (r"^FATO\b",                                      "Fatos"),

    # ─── Blazers ─────────────────────────────────────────────────
    (r"^BLAZER",                                      "Blazers"),

    # ─── Calças — técnico antes de tecido ────────────────────────
    (r"CALÇ(?:A|ÃO|ÕES|AS) .*T[ÉE]CNIC",              "Calças de tecido técnico"),
    (r"^CALÇA CHINO|CALÇ(?:A|AS) CHINO|^CALÇ(?:Õ|O)ES CHINO",
                                                      "Calças chino"),
    (r"^CALÇA DE GANGA|^CALÇA GANGA|^CALÇ(?:Õ|O)ES DE GANGA",
                                                      "Calças de ganga"),
    (r"^CALÇA DE ALFAIATARIA",                        "Calças de tecido"),
    (r"^CALÇA DE TECIDO|^CALÇA TECIDO",               "Calças de tecido"),
    (r"^CALÇA DE FATO DE TREINO|^CALÇA FATO DE TREINO",
                                                      "Calças de fato de treino"),
    (r"^CALÇA CL(?:Á|A)SSICA|^CALÇA COMFORT|^CALÇA CROPPED|^CALÇA FATO|^CALÇA DE SARJA|^CALÇA SARJA",
                                                      "Calças de tecido"),
    # Calças genéricas que não bateram acima
    (r"^CALÇA\b",                                     "Calças de tecido"),

    # ─── Camisas ─────────────────────────────────────────────────
    (r"^CAMISA\b|^CAMISEIRO",                         "Camisas"),

    # ─── Camisolas ───────────────────────────────────────────────
    (r"^CAMISOLA\b",                                  "Camisolas"),

    # ─── T-Shirts ────────────────────────────────────────────────
    # (T-SHIRT TRICOT e POLO TRICOT vão para Malhas — regra abaixo)
    (r"^T-SHIRT(?! TRICOT)",                          "T-Shirts"),

    # ─── Polos ───────────────────────────────────────────────────
    (r"^POLO(?! TRICOT)",                             "Polos"),

    # ─── Malhas (gola alta, meia gola, etc.) ─────────────────────
    (r"^MALHA\b|^GOLA ALTA|MEIA GOLA|^T-SHIRT TRICOT|^POLO TRICOT",
                                                      "Malhas"),

    # ─── Hoodies & Sweats ────────────────────────────────────────
    (r"^HOODIE|^SWEAT",                               "Hoodies & Sweats"),

    # ─── Calções ─────────────────────────────────────────────────
    (r"^CALÇ(?:Õ|O)ES|^CALÇÃO",                       "Calções"),

    # ─── Sapatilhas (antes de Sapatos) ───────────────────────────
    (r"^SAPATILHA",                                   "Sapatilhas"),

    # ─── Sapatos / Mocassins / Botins / Calçado ────────────────────
    (r"^SAPATO|^MOCASSIM|^MOCASSIN|^BOTIM|^CALÇADO",  "Sapatos"),

    # ─── Gravatas ────────────────────────────────────────────────
    (r"^GRAVATA",                                     "Gravatas"),

    # ─── Lenços ──────────────────────────────────────────────────
    (r"^LENÇO",                                       "Lenços"),

    # ─── Cachecóis ───────────────────────────────────────────────
    (r"^CACHECOL",                                    "Cachecóis"),

    # ─── Gift Cards ──────────────────────────────────────────────
    (r"^GIFT\s*CARD",                                 "Gift Cards"),

    # ─── Acessórios ──────────────────────────────────────────────
    (r"^PULSEIRA",                                    "Acessórios"),
    (r"^COLAR",                                       "Acessórios"),
    (r"^PACK\b|^PACKS\b",                             "Acessórios"),
    (r"^MALA\b|^MALAS\b|^NECESSAIRE|MALAS? & NECESSAIRES?",
                                                      "Acessórios"),
    (r"^LUVA|^CARTEIRA|CARTEIRAS?",                   "Acessórios"),
    (r"^CINTO .*PELE|CINTOS? EM PELE|^CINTO\b",       "Acessórios"),
    (r"^FIO\b",                                       "Acessórios"),
    (r"^ESCAPUL(?:Á|A)RIO",                           "Acessórios"),
    (r"^CORRENTE",                                    "Acessórios"),
    (r"^MINI NECESSAIRE",                             "Acessórios"),
    (r"^MOCHILA",                                     "Acessórios"),
    (r"^CLUTCH",                                      "Acessórios"),
    (r"^PORTA-CART(?:Õ|O)ES",                         "Acessórios"),
    (r"^PORTA-CHAVES",                                "Acessórios"),
    (r"^PORTA-FATOS",                                 "Acessórios"),
    (r"^WEEKENDER",                                   "Acessórios"),
    (r"^BON(?:É|E)\b",                                "Acessórios"),

    # ─── Saco de Embrulho ────────────────────────────────────────
    (r"^SACO",                                        "Saco de Embrulho"),

    # ─── Serviços internos ───────────────────────────────────────
    (r"^FORRO",                                       "Forro"),
    (r"^FARDAMENTO",                                  "Fardamento"),
    (r"^ESTAMPAGEM",                                  "Estampagem"),
    (r"^ARRANJOS",                                    "Arranjos"),
]


def categorize(name: str) -> str:
    """
    Retorna a categoria para um produto com base no nome.
    Tudo o que não bater em nenhuma regra → "Outros".
    """
    if not name:
        return "Outros"
    upper = name.upper().strip()
    for pattern, cat in RULES:
        if re.search(pattern, upper):
            return cat
    return "Outros"


if __name__ == "__main__":
    # Teste rápido
    tests = [
        "FATO SLIM FIT AZUL MARINHO (PICK STITCH)-M",
        "CAMISA STRETCH BRANCA-L",
        "CALÇA CHINO SLIM FIT AZUL MARINHO-40",
        "CALÇA DE GANGA TAPERED FIT MID-40",
        "CALÇA DE TECIDO TÉCNICO PRETO",
        "SAPATILHA BRANCA DE CORDÃO-41",
        "MOCASSIM EM CAMURÇA CASTANHO",
        "CARDIGAN DE MALHA COM BOTÕES AZUL",
        "SOBRECAMISA DE LÃ",
        "CONJUNTO DESPORTIVO CINZA",
        "PERFUME L'INSTINCT",
        "PULSEIRA INDIA",
        "GOLA ALTA PISTACHIO",
        "GRAVATA AZUL",
        "BONÉ VERDE",
        "CALÇA DE ALFAIATARIA AZUL MARINHO",
        "BLAZER SLIM FIT AZUL",
    ]
    for t in tests:
        print(f"  {t:<55} → {categorize(t)}")
