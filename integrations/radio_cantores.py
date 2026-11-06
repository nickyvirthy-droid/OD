"""Cantores indesejados do dono — lista e regra "toca uma vez e apaga".

Ordem do dono (recado de 05/11 no txt.txt, confirmada em 05/11 20:40):

    "Existem cantores que não desejo no meu acervo. Por exemplo Annita, se o
    usuário pedir essa música ela baixa, toca pra ele e depois é deletada.
    Vamos fazer uma lista de Cantores indesejados, vou preenchendo conforme
    lembro."

Desenho (mínimo e honesto):

- A LISTA é um arquivo de texto simples, uma pessoa por linha, editável à
  mão ou pela API — ``data/cantores_indesejados.txt`` (linha com ``#`` é
  comentário). Vazia por padrão: o dono vai preenchendo.
- A REGRA vale para o pedido do ouvinte: se o artista está na lista, a
  música **toca normalmente** (o ouvinte pediu) e entra num registro
  ``data/radio_apagar_depois.json``. Quando o AzuraCast informa que ela
  tocou — ou passadas ``HORAS_LIMITE`` sem tocar (pedido que morreu) — o
  arquivo sai do acervo, o banco e as playlists são refeitos e o AzuraCast
  é sincronizado (mesmo caminho do pipeline; ``azuracast:media:sync``
  remove o que não existe mais em disco).
- Nada é apagado sem passar por esse registro: quem apaga é
  ``limpar_tocados()``, chamado no webhook da rádio (a cada troca de
  faixa) — nunca no meio de um download.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from core.logger import get_logger

log = get_logger("omega.integrations.radio_cantores")

RAIZ = Path(__file__).resolve().parents[1]
BASE_MUSICAS = Path(os.environ.get("OD_BASE_MUSICAS", "/home/alex/dados/musicas"))
LISTA = Path(os.environ.get("OD_CANTORES_LISTA",
                            str(RAIZ / "data" / "cantores_indesejados.txt")))
REGISTRO = Path(os.environ.get("OD_CANTORES_REGISTRO",
                               str(RAIZ / "data" / "radio_apagar_depois.json")))
#: Pedido que nunca tocou não fica pendurado para sempre.
HORAS_LIMITE = int(os.environ.get("OD_CANTORES_HORAS_LIMITE", "48"))
MUSICA_PYTHON = Path(os.environ.get("OD_MUSICA_PYTHON",
                                    str(BASE_MUSICAS / "venv/bin/python")))

CABECALHO = """# Cantores que o dono NAO quer no acervo (05/11/2026).
# Um por linha. Linha com # e comentario.
# Regra: se um ouvinte pedir, a musica TOCA UMA VEZ e depois e apagada.
# Exemplo (descomente para valer):
# Annita
"""


def _sem_acento(texto: str) -> str:
    decomposto = unicodedata.normalize("NFD", str(texto or ""))
    return "".join(c for c in decomposto if unicodedata.category(c) != "Mn")


def normalizar(texto: str) -> str:
    """Compara sem caixa, sem acento e sem pontuação (``Annita`` = ``annitá``)."""
    limpo = re.sub(r"[^a-z0-9 ]+", " ", _sem_acento(texto).lower())
    return re.sub(r"\s+", " ", limpo).strip()


def _arquivo(caminho: Optional[Path] = None) -> Path:
    return Path(caminho or LISTA)


def _ler(caminho: Optional[Path] = None) -> list[str]:
    arquivo = _arquivo(caminho)
    if not arquivo.exists():
        return []
    nomes = []
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        texto = linha.strip()
        if not texto or texto.startswith("#"):
            continue
        nomes.append(texto)
    return nomes


def listar(*, caminho: Optional[Path] = None) -> list[str]:
    """Nomes cadastrados, na ordem do arquivo (sem duplicados)."""
    vistos: set[str] = set()
    saida = []
    for nome in _ler(caminho):
        chave = normalizar(nome)
        if chave and chave not in vistos:
            vistos.add(chave)
            saida.append(nome)
    return saida


def adicionar(nome: str, *, caminho: Optional[Path] = None) -> bool:
    """Inclui um cantor. Idempotente; False se vazio ou já estava na lista."""
    nome = (nome or "").strip()
    if not nome or len(nome) > 80:
        return False
    if indesejado(nome, caminho=caminho):
        return False
    arquivo = _arquivo(caminho)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    if not arquivo.exists():
        arquivo.write_text(CABECALHO, encoding="utf-8")
    with arquivo.open("a", encoding="utf-8") as f:
        f.write(nome + "\n")
    log.info("cantor indesejado incluido", nome=nome)
    return True


def remover(nome: str, *, caminho: Optional[Path] = None) -> bool:
    """Tira o cantor da lista; False se não estava lá."""
    alvo = normalizar(nome)
    if not alvo:
        return False
    arquivo = _arquivo(caminho)
    if not arquivo.exists():
        return False
    linhas = arquivo.read_text(encoding="utf-8").splitlines()
    restantes = [l for l in linhas if l.strip().startswith("#")
                 or normalizar(l) != alvo]
    if len(restantes) == len(linhas):
        return False
    arquivo.write_text("\n".join(restantes).rstrip("\n") + "\n", encoding="utf-8")
    log.info("cantor indesejado removido", nome=nome)
    return True


def indesejado(artista: str, *, caminho: Optional[Path] = None) -> bool:
    """True quando o artista (ou um dos artistas do campo) está na lista.

    Compara sem caixa/acento. Vale tanto ``Annita`` quanto
    ``Annita e Fulano`` / ``Fulano ft. Annita`` — a lista casa por pessoa.
    """
    alvo = normalizar(artista)
    if not alvo:
        return False
    tokens = set(alvo.split())
    for nome in _ler(caminho):
        chave = normalizar(nome)
        if not chave:
            continue
        if alvo == chave or chave in tokens or f" {chave} " in f" {alvo} ":
            return True
    return False


# ---------------------------------------------------------------------------
#  "Toca uma vez e apaga" — registro dos pedidos marcados
# ---------------------------------------------------------------------------

def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ler_registro(caminho: Optional[Path] = None) -> list[dict[str, Any]]:
    arquivo = Path(caminho or REGISTRO)
    if not arquivo.exists():
        return []
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8") or "[]")
    except (ValueError, OSError):
        return []
    return [item for item in dados if isinstance(item, dict)]


def _gravar_registro(itens: list[dict[str, Any]],
                     caminho: Optional[Path] = None) -> None:
    arquivo = Path(caminho or REGISTRO)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    temporario = arquivo.with_suffix(".tmp")
    temporario.write_text(json.dumps(itens, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    temporario.replace(arquivo)


def registrar_para_apagar(
    artista: str, titulo: str, caminho: str = "",
    *, registro: Optional[Path] = None,
) -> Optional[dict[str, Any]]:
    """Marca a faixa para sair do acervo depois de tocar (idempotente)."""
    if not normalizar(artista) and not normalizar(titulo):
        return None
    itens = _ler_registro(registro)
    chave = (normalizar(artista), normalizar(titulo))
    for item in itens:
        if (normalizar(str(item.get("artista") or "")),
                normalizar(str(item.get("titulo") or ""))) == chave:
            return item
    item = {"artista": str(artista or ""), "titulo": str(titulo or ""),
            "caminho": str(caminho or ""), "criado_em": _agora(),
            "tocou_em": "", "status": "aguardando"}
    itens.append(item)
    _gravar_registro(itens, registro)
    log.info("faixa marcada para apagar depois de tocar",
             artista=artista, titulo=titulo)
    return item


def pendentes(*, registro: Optional[Path] = None) -> list[dict[str, Any]]:
    return [i for i in _ler_registro(registro)
            if str(i.get("status") or "") == "aguardando"]


def historico_azuracast(limite: int = 50) -> list[dict[str, str]]:
    """Últimas faixas tocadas (artista/título) — fonte: API do AzuraCast."""
    from integrations import radio_pro as rp

    status, dados = rp._azuracast(
        f"/api/station/{rp.AZURA_STATION}/history?limit={int(limite)}")
    if status != 200 or not isinstance(dados, list):
        return []
    saida = []
    for item in dados:
        song = (item or {}).get("song") or {}
        saida.append({"artista": str(song.get("artist") or ""),
                      "titulo": str(song.get("title") or "")})
    return saida


def _ressincronizar() -> bool:
    """Refaz banco/.m3u/sync no venv do acervo (o mesmo do pipeline)."""
    if not MUSICA_PYTHON.exists():
        log.warn("venv do acervo ausente; sync nao rodou",
                 python=str(MUSICA_PYTHON))
        return False
    codigo = (
        "import musica;"
        "musica.indexar_acervo();"
        "musica.exportar_playlists_m3u();"
        "musica.publicar_azuracast()"
    )
    try:
        proc = subprocess.run([str(MUSICA_PYTHON), "-c", codigo],
                              cwd=str(BASE_MUSICAS), capture_output=True,
                              text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warn("sync do acervo falhou", error=type(exc).__name__)
        return False
    if proc.returncode != 0:
        log.warn("sync do acervo saiu com erro", codigo=proc.returncode)
        return False
    return True


def _apagar_arquivo(relativo: str) -> bool:
    if not relativo:
        return False
    alvo = (BASE_MUSICAS / relativo).resolve()
    try:
        alvo.relative_to(BASE_MUSICAS.resolve())
    except ValueError:            # nunca apaga fora do acervo
        log.warn("caminho fora do acervo ignorado", caminho=relativo)
        return False
    if not alvo.is_file():
        return False
    alvo.unlink()
    return True


def limpar_tocados(
    *,
    registro: Optional[Path] = None,
    historico: Optional[Callable[[], list[dict[str, str]]]] = None,
    apagar: Optional[Callable[[str], bool]] = None,
    ressincronizar: Optional[Callable[[], bool]] = None,
    agora: Optional[datetime] = None,
) -> dict[str, Any]:
    """Apaga as faixas marcadas que já tocaram (ou venceram o prazo).

    Devolve ``{"apagadas": n, "restantes": n, "sync": bool}``. Nunca
    levanta: o webhook da rádio não pode cair por causa da limpeza.
    """
    itens = _ler_registro(registro)
    if not itens:
        return {"apagadas": 0, "restantes": 0, "sync": False}
    tocou = historico or historico_azuracast
    apagar = apagar or _apagar_arquivo
    try:
        tocadas = {(normalizar(i.get("artista", "")), normalizar(i.get("titulo", "")))
                   for i in tocou()}
    except Exception as exc:
        log.warn("historico da radio indisponivel", error=type(exc).__name__)
        tocadas = set()
    agora = agora or datetime.now(timezone.utc)
    limite = agora - timedelta(hours=HORAS_LIMITE)
    apagadas = 0
    restantes: list[dict[str, Any]] = []
    mudou = False
    for item in itens:
        chave = (normalizar(str(item.get("artista") or "")),
                 normalizar(str(item.get("titulo") or "")))
        if str(item.get("status") or "") != "aguardando":
            continue
        venceu = False
        try:
            venceu = datetime.fromisoformat(
                str(item.get("criado_em"))) < limite
        except ValueError:
            venceu = False
        if chave not in tocadas and not venceu:
            restantes.append(item)
            continue
        try:
            apagar(str(item.get("caminho") or ""))
        except Exception as exc:          # arquivo travado/não existe
            log.warn("apagar faixa indesejada falhou",
                     error=type(exc).__name__)
        item["status"] = "apagada"
        item["tocou_em"] = item.get("tocou_em") or _agora()
        apagadas += 1
        mudou = True
        log.info("faixa indesejada apagada",
                 artista=item.get("artista"), titulo=item.get("titulo"))
    if mudou:
        _gravar_registro(itens, registro)
    sincronizado = False
    if apagadas:
        ressincronizar = ressincronizar or _ressincronizar
        try:
            sincronizado = bool(ressincronizar())
        except Exception as exc:
            log.warn("sincronizacao apos limpeza falhou",
                     error=type(exc).__name__)
    return {"apagadas": apagadas, "restantes": len(restantes),
            "sync": sincronizado}


def linhas_do_arquivo(*, caminho: Optional[Path] = None) -> str:
    """Conteúdo cru da lista (para a API mostrar o arquivo como ele é)."""
    arquivo = _arquivo(caminho)
    if not arquivo.exists():
        return CABECALHO
    return arquivo.read_text(encoding="utf-8")


__all__ = [
    "LISTA", "REGISTRO", "HORAS_LIMITE", "normalizar", "listar", "adicionar",
    "remover", "indesejado", "registrar_para_apagar", "pendentes",
    "historico_azuracast", "limpar_tocados", "linhas_do_arquivo",
]
