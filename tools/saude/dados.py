"""OMEGA DRAKON • TOOLS • SAÚDE • DADOS
Carregamento das coleções curadas, matching PT-BR determinístico e consulta
à API openFDA (bula oficial dos EUA).

Nunca escreve conteúdo médico: só lê coleções versionadas (fontes de
domínio público com atribuição) e devolve o texto da fonte.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

COLECOES_DIR = Path(__file__).resolve().parent / "collections"
OPENFDA_LABEL_URL = "https://api.fda.gov/drug/label.json"
TIMEOUT_OPENFDA = 8
MAX_TEXTO_FDA = 600  # truncamento honesto de blocos longos da bula p/ chat

# ---------------------------------------------------------------------------
# Coleções
# ---------------------------------------------------------------------------


@lru_cache(maxsize=None)
def carregar_colecao(nome: str) -> dict[str, Any]:
    """Lê ``collections/<nome>.json`` (cacheado). ``nome`` sem extensão."""
    caminho = COLECOES_DIR / f"{nome}.json"
    return json.loads(caminho.read_text(encoding="utf-8"))


def _bate(termo: str, texto: str) -> bool:
    """Caso-insensitivo com fronteira de palavra (``dor`` não casa ``dormir``)."""
    return re.search(r"\b" + re.escape(termo) + r"\b", texto) is not None


def achar_condicao(texto: str) -> Optional[dict[str, Any]]:
    """Condição cujo termo PT-BR MAIS LONGO casa no texto (empate = ordem)."""
    baixo = (texto or "").casefold()
    if not baixo:
        return None
    melhor_tam = 0
    melhor: Optional[dict[str, Any]] = None
    for cond in carregar_colecao("condicoes")["condicoes"]:
        for termo in cond["termos"]:
            if len(termo) <= melhor_tam:
                continue
            if termo.casefold() in baixo:
                # termo de frase: substring (já vem com fronteira natural);
                # termo de 1 palavra: exige fronteira de palavra.
                if " " not in termo and not _bate(termo, baixo):
                    continue
                melhor_tam = len(termo)
                melhor = cond
    return melhor


def cuidados_da_condicao(slug_en: str) -> list[dict[str, Any]]:
    """Remédios curados (caseiros + naturais) ligados à condição (slug NOMAD)."""
    itens: list[dict[str, Any]] = []
    for arquivo, tipo in (
        ("remedios_caseiros", "caseiro"),
        ("remedios_naturais", "natural"),
    ):
        for rem in carregar_colecao(arquivo)["remedies"]:
            if slug_en in rem.get("conditions", []):
                itens.append({
                    "tipo": tipo,
                    "slug": rem["slug"],
                    "nome": rem["nome"],
                    "resumo": rem["resumo"],
                    "detalhe": rem["detalhe"],
                    "fonte": rem["fonte"]["nome"],
                    "url": rem["fonte"].get("url", ""),
                })
    return itens


# ---------------------------------------------------------------------------
# Medicamentos (lexicon de interface: só nomes)
# ---------------------------------------------------------------------------


def extrair_medicamentos(texto: str) -> list[dict[str, Any]]:
    """Medicamentos citados no texto, na ordem de aparição (sem repetição)."""
    baixo = texto or ""
    achados: list[tuple[int, dict[str, Any]]] = []
    vistos: set[str] = set()
    for med in carregar_colecao("medicamentos")["medicamentos"]:
        if med["nome"] in vistos:
            continue
        for alias in med["aliases"]:
            m = re.search(r"\b" + re.escape(alias) + r"\b", baixo, re.IGNORECASE)
            if m:
                achados.append((m.start(), med))
                vistos.add(med["nome"])
                break
    achados.sort(key=lambda par: par[0])
    return [med for _, med in achados]


def achar_medicamento(termo: str) -> Optional[dict[str, Any]]:
    """Lexicon entry que casa com ``termo`` (primeiro, por ordem do arquivo)."""
    for med in extrair_medicamentos(termo or ""):
        return med
    return None


# ---------------------------------------------------------------------------
# openFDA (bula) — rede real, com honestidade em falha
# ---------------------------------------------------------------------------


def _abrir(url: str) -> bytes:
    """GET simples (substituível em teste — toda a rede passa por aqui)."""
    req = urllib.request.Request(
        url, headers={"User-Agent": "OMEGA-DRAKON/saude-referencia"}
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_OPENFDA) as resp:
        return resp.read()


def openfda_label(generico: str) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Label FDA do genérico. Devolve ``(label | None, motivo | None)``.

    motivo: ``sem_resultado`` (FDA não regula/não tem label) ou
    ``sem_rede`` (falha de rede/serviço — nada foi consultado).
    """
    busca = f'openfda.generic_name:"{generico}"'
    url = f"{OPENFDA_LABEL_URL}?search={urllib.parse.quote(busca)}&limit=1"
    try:
        cru = _abrir(url)
    except urllib.error.HTTPError as exc:  # openFDA responde 404 sem match
        try:
            corpo = exc.read().decode("utf-8", "replace")
        except Exception:  # pragma: no cover - defensivo
            corpo = ""
        return None, "sem_resultado" if '"error"' in corpo else "sem_rede"
    except Exception:
        return None, "sem_rede"
    try:
        dados = json.loads(cru.decode("utf-8"))
    except Exception:
        return None, "sem_rede"
    if "error" in dados:
        return None, "sem_resultado"
    resultados = dados.get("results") or []
    if not resultados:
        return None, "sem_resultado"
    return resultados[0], None


def lista_campo(label: dict[str, Any], campo: str) -> list[str]:
    """Campo de texto da bula como lista de strings (formato FDA)."""
    valor = label.get(campo)
    if isinstance(valor, str):
        return [valor]
    if isinstance(valor, list):
        return [v for v in valor if isinstance(v, str)]
    return []


def truncar(texto: str, maximo: int = MAX_TEXTO_FDA) -> str:
    """Truncamento honesto em limite de caracteres, com reticências."""
    texto = " ".join((texto or "").split())
    if len(texto) <= maximo:
        return texto
    return texto[: maximo - 1].rsplit(" ", 1)[0] + "…"
