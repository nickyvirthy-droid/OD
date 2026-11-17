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
- A REGRA vale para o pedido do ouvinte: se o artista está na lista (ou a
  MÚSICA está na lista de bloqueadas), a música **toca normalmente** (o
  ouvinte pediu) e entra num registro ``data/radio_apagar_depois.json``.
- **Janela de decisão (ordem de 17/11):** o dono é avisado na hora e tem
  ``HORAS_DECISAO`` (24 h) para **permitir** a faixa — ela fica no acervo e
  o par vai para ``data/cantores_excecoes.txt``. Sem decisão, passada a
  janela, o arquivo sai do acervo, o banco e as playlists são refeitos e o
  AzuraCast é sincronizado (mesmo caminho do pipeline;
  ``azuracast:media:sync`` remove o que não existe mais em disco).
- Nada é apagado sem passar por esse registro: quem apaga é
  ``limpar_tocados()``, chamado no webhook da rádio (a cada troca de
  faixa) — nunca no meio de um download.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
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
LISTA_EXCECOES = Path(os.environ.get("OD_CANTORES_EXCECOES",
                                    str(RAIZ / "data" / "cantores_excecoes.txt")))
LISTA_BLOQUEADAS = Path(os.environ.get("OD_MUSICAS_BLOQUEADAS",
                                      str(RAIZ / "data" / "musicas_bloqueadas.txt")))
REGISTRO = Path(os.environ.get("OD_CANTORES_REGISTRO",
                               str(RAIZ / "data" / "radio_apagar_depois.json")))
#: Pedido que nunca tocou não fica pendurado para sempre.
HORAS_LIMITE = int(os.environ.get("OD_CANTORES_HORAS_LIMITE", "48"))
#: Janela de decisão do dono (ordem de 17/11): quando entra faixa de cantor
#: bloqueado OU música bloqueada, ele é avisado e tem 24 h para permitir;
#: sem decisão, a faixa é apagada automaticamente.
HORAS_DECISAO = int(os.environ.get("OD_CANTORES_HORAS_DECISAO", "24"))
MUSICA_PYTHON = Path(os.environ.get("OD_MUSICA_PYTHON",
                                    str(BASE_MUSICAS / "venv/bin/python")))

CABECALHO = """# Cantores que o dono NAO quer no acervo (05/11/2026).
# Um por linha. Linha com # e comentario.
# Regra: se um ouvinte pedir, a musica TOCA UMA VEZ e depois e apagada.
# Exemplo (descomente para valer):
# Annita
"""

CABECALHO_EXCECOES = """# Musicas permitidas de cantores bloqueados (ordem do dono, 17/11/2026).
# Formato: Artista | Titulo (uma por linha. Linha com # e comentario).
# Exemplo:
# Annita | Envolver
"""

CABECALHO_BLOQUEADAS = """# Musicas que o dono NAO quer no acervo (excluidas e bloqueadas individualmente).
# Formato: Artista | Titulo (uma por linha. Linha com # e comentario).
# Exemplo:
# Fulano | Musica Chata
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


# ---------------------------------------------------------------------------
#  Pares Artista | Titulo (Exceções permitidas e Músicas bloqueadas)
# ---------------------------------------------------------------------------

def _ler_pares(caminho: Path) -> list[tuple[str, str]]:
    if not caminho.exists():
        return []
    pares: list[tuple[str, str]] = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        texto = linha.strip()
        if not texto or texto.startswith("#") or "|" not in texto:
            continue
        partes = [p.strip() for p in texto.split("|", 1)]
        if len(partes) == 2 and partes[0] and partes[1]:
            pares.append((partes[0], partes[1]))
    return pares


def _casa_par(artista: str, titulo: str, pares: list[tuple[str, str]]) -> bool:
    art = normalizar(artista)
    tit = normalizar(titulo)
    if not art or not tit:
        return False
    for p_art, p_tit in pares:
        par_art = normalizar(p_art)
        par_tit = normalizar(p_tit)
        if not par_art or not par_tit:
            continue
        art_bate = (par_art == art or par_art in art or art in par_art or
                    f" {par_art} " in f" {art} ")
        tit_bate = (par_tit == tit or par_tit in tit or tit in par_tit)
        if art_bate and tit_bate:
            return True
    return False


def _adicionar_par(arquivo: Path, cabecalho: str, artista: str, titulo: str) -> bool:
    artista = (artista or "").strip()
    titulo = (titulo or "").strip()
    if not artista or not titulo or len(artista) > 80 or len(titulo) > 120:
        return False
    for p_art, p_tit in _ler_pares(arquivo):
        if normalizar(p_art) == normalizar(artista) and normalizar(p_tit) == normalizar(titulo):
            return False
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    if not arquivo.exists():
        arquivo.write_text(cabecalho, encoding="utf-8")
    with arquivo.open("a", encoding="utf-8") as f:
        f.write(f"{artista} | {titulo}\n")
    return True


def _remover_par(arquivo: Path, artista: str, titulo: str) -> bool:
    if not arquivo.exists():
        return False
    alvo_art = normalizar(artista)
    alvo_tit = normalizar(titulo)
    linhas = arquivo.read_text(encoding="utf-8").splitlines()
    restantes = []
    removido = False
    for l in linhas:
        texto = l.strip()
        if texto.startswith("#") or "|" not in texto:
            restantes.append(l)
            continue
        p = [x.strip() for x in texto.split("|", 1)]
        if len(p) == 2 and normalizar(p[0]) == alvo_art and normalizar(p[1]) == alvo_tit:
            removido = True
            continue
        restantes.append(l)
    if not removido:
        return False
    arquivo.write_text("\n".join(restantes).rstrip("\n") + "\n", encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
#  Exceções de cantores bloqueados (músicas permitidas que não são apagadas)
# ---------------------------------------------------------------------------

def eh_excecao(artista: str, titulo: str, *, caminho: Optional[Path] = None) -> bool:
    """True se (artista, titulo) é uma exceção permitida de cantor indesejado."""
    arquivo = Path(caminho or LISTA_EXCECOES)
    return _casa_par(artista, titulo, _ler_pares(arquivo))


def listar_excecoes(*, caminho: Optional[Path] = None) -> list[dict[str, str]]:
    arquivo = Path(caminho or LISTA_EXCECOES)
    return [{"artista": a, "titulo": t} for a, t in _ler_pares(arquivo)]


def adicionar_excecao(artista: str, titulo: str, *, caminho: Optional[Path] = None) -> bool:
    arquivo = Path(caminho or LISTA_EXCECOES)
    ok = _adicionar_par(arquivo, CABECALHO_EXCECOES, artista, titulo)
    if ok:
        log.info("excecao de cantor indesejado incluida", artista=artista, titulo=titulo)
    return ok


def remover_excecao(artista: str, titulo: str, *, caminho: Optional[Path] = None) -> bool:
    arquivo = Path(caminho or LISTA_EXCECOES)
    ok = _remover_par(arquivo, artista, titulo)
    if ok:
        log.info("excecao de cantor indesejado removida", artista=artista, titulo=titulo)
    return ok


def linhas_excecoes(*, caminho: Optional[Path] = None) -> str:
    arquivo = Path(caminho or LISTA_EXCECOES)
    if not arquivo.exists():
        return CABECALHO_EXCECOES
    return arquivo.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
#  Músicas indesejadas (bloqueadas no acervo e na rádio)
# ---------------------------------------------------------------------------

def musica_bloqueada(artista: str, titulo: str = "", *, caminho: Optional[Path] = None) -> bool:
    """True se a música específica está na lista de bloqueadas."""
    arquivo = Path(caminho or LISTA_BLOQUEADAS)
    pares = _ler_pares(arquivo)
    if not titulo:
        alvo = normalizar(artista)
        return any(normalizar(f"{p_art} {p_tit}") in alvo or alvo in normalizar(f"{p_art} {p_tit}")
                   for p_art, p_tit in pares)
    return _casa_par(artista, titulo, pares)


def listar_musicas_bloqueadas(*, caminho: Optional[Path] = None) -> list[dict[str, str]]:
    arquivo = Path(caminho or LISTA_BLOQUEADAS)
    return [{"artista": a, "titulo": t} for a, t in _ler_pares(arquivo)]


def adicionar_musica_bloqueada(artista: str, titulo: str, *, caminho: Optional[Path] = None) -> bool:
    arquivo = Path(caminho or LISTA_BLOQUEADAS)
    ok = _adicionar_par(arquivo, CABECALHO_BLOQUEADAS, artista, titulo)
    if ok:
        log.info("musica bloqueada incluida", artista=artista, titulo=titulo)
    return ok


def remover_musica_bloqueada(artista: str, titulo: str, *, caminho: Optional[Path] = None) -> bool:
    arquivo = Path(caminho or LISTA_BLOQUEADAS)
    ok = _remover_par(arquivo, artista, titulo)
    if ok:
        log.info("musica bloqueada removida", artista=artista, titulo=titulo)
    return ok


def linhas_bloqueadas(*, caminho: Optional[Path] = None) -> str:
    arquivo = Path(caminho or LISTA_BLOQUEADAS)
    if not arquivo.exists():
        return CABECALHO_BLOQUEADAS
    return arquivo.read_text(encoding="utf-8")


def indesejado(
    artista: str,
    titulo: str = "",
    *,
    caminho: Optional[Path] = None,
    caminho_excecoes: Optional[Path] = None,
) -> bool:
    """True quando o artista (ou um dos artistas do campo) está na lista.

    Compara sem caixa/acento. Vale tanto ``Annita`` quanto
    ``Annita e Fulano`` / ``Fulano ft. Annita`` — a lista casa por pessoa.
    EXCEÇÃO: se (artista, titulo) for exceção permitida, devolve False.
    """
    alvo = normalizar(artista)
    if not alvo:
        return False
    if titulo and eh_excecao(artista, titulo, caminho=caminho_excecoes):
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
    *, registro: Optional[Path] = None, motivo: str = "cantor",
    usuario: str = "",
) -> Optional[dict[str, Any]]:
    """Marca a faixa para a DECISÃO do dono (24 h) — idempotente.

    Ordem de 17/11: faixa de cantor bloqueado ou música bloqueada toca uma
    vez para quem pediu e o dono é avisado. Ele tem ``HORAS_DECISAO`` (24 h)
    para permitir (`decidir(..., permitir=True)`); sem decisão, o webhook da
    rádio apaga a faixa (`limpar_tocados`).

    ``motivo`` é "cantor" ou "musica" (vai para o aviso e para o painel).
    """
    if not normalizar(artista) and not normalizar(titulo):
        return None
    itens = _ler_registro(registro)
    chave = (normalizar(artista), normalizar(titulo))
    for item in itens:
        if (normalizar(str(item.get("artista") or "")),
                normalizar(str(item.get("titulo") or ""))) == chave:
            return item
    agora = datetime.now(timezone.utc)
    item = {"artista": str(artista or ""), "titulo": str(titulo or ""),
            "caminho": str(caminho or ""), "motivo": str(motivo or "cantor"),
            "usuario": str(usuario or ""),
            "criado_em": agora.isoformat(timespec="seconds"),
            "decidir_ate": (agora + timedelta(hours=HORAS_DECISAO))
            .isoformat(timespec="seconds"),
            "tocou_em": "", "status": "aguardando"}
    itens.append(item)
    _gravar_registro(itens, registro)
    log.info("faixa aguardando decisao do dono",
             artista=artista, titulo=titulo, motivo=item["motivo"],
             decidir_ate=item["decidir_ate"])
    return item


def aviso_de_decisao(item: Optional[dict[str, Any]]) -> str:
    """Texto do aviso ao dono (Telegram/painel) para uma faixa pendente."""
    if not item:
        return ""
    artista = str(item.get("artista") or "")
    titulo = str(item.get("titulo") or "")
    nome = f"{artista} — {titulo}".strip(" —") or "faixa"
    motivo = ("cantor bloqueado" if item.get("motivo") == "cantor"
              else "música bloqueada")
    quem = str(item.get("usuario") or "")
    origem = f"@{quem} pediu " if quem else "Entrou "
    return (f"⏳ Decisão necessária ({HORAS_DECISAO} h): {origem}\""
            f"{nome}\" ({motivo}). Permita em /admin → Rádio — acervo e"
            " cantores. Sem resposta, ela é apagada automaticamente.")


def pendentes(*, registro: Optional[Path] = None) -> list[dict[str, Any]]:
    """Itens aguardando decisão, com o prazo e o tempo restante."""
    agora = datetime.now(timezone.utc)
    saida: list[dict[str, Any]] = []
    for item in _ler_registro(registro):
        if str(item.get("status") or "") != "aguardando":
            continue
        restante = None
        try:
            prazo = datetime.fromisoformat(str(item.get("decidir_ate") or ""))
            restante = max(0, int((prazo - agora).total_seconds()))
        except ValueError:
            prazo = None
        saida.append({**item,
                      "decidir_ate": (prazo.isoformat(timespec="seconds")
                                      if prazo else ""),
                      "segundos_restantes": restante})
    return saida


def decidir(
    artista: str,
    titulo: str,
    *,
    permitir: bool,
    registro: Optional[Path] = None,
    apagar: Optional[Callable[[str], bool]] = None,
    ressincronizar: Optional[Callable[[], bool]] = None,
    caminho_excecoes: Optional[Path] = None,
) -> dict[str, Any]:
    """Decisão do dono sobre uma faixa pendente (ordem de 17/11).

    ``permitir=True`` tira a faixa da fila de exclusão e grava o par em
    ``data/cantores_excecoes.txt`` — ela fica no acervo e pedidos futuros não
    a marcam de novo. ``permitir=False`` apaga na hora (disco + acervo.db +
    sync) sem esperar as 24 h.

    Devolve ``{"ok": bool, "motivo"?: str, "item": dict}``.
    """
    chave = (normalizar(artista), normalizar(titulo))
    itens = _ler_registro(registro)
    alvo: Optional[dict[str, Any]] = None
    for item in itens:
        if (normalizar(str(item.get("artista") or "")),
                normalizar(str(item.get("titulo") or ""))) == chave:
            alvo = item
            break
    if alvo is None:
        return {"ok": False, "motivo": "nao_encontrado"}
    if str(alvo.get("status") or "") != "aguardando":
        return {"ok": False, "motivo": "ja_decidida", "item": alvo}
    if permitir:
        alvo["status"] = "permitida"
        alvo["decidido_em"] = _agora()
        _gravar_registro(itens, registro)
        adicionar_excecao(str(alvo.get("artista") or ""),
                          str(alvo.get("titulo") or ""),
                          caminho=caminho_excecoes)
        log.info("faixa PERMITIDA pelo dono",
                 artista=alvo.get("artista"), titulo=alvo.get("titulo"))
        return {"ok": True, "permitida": True, "item": alvo}
    apagar_fn = apagar or _apagar_arquivo
    try:
        apagar_fn(str(alvo.get("caminho") or ""))
    except Exception as exc:              # arquivo travado/não existe
        log.warn("apagar faixa negada falhou", error=type(exc).__name__)
    alvo["status"] = "apagada"
    alvo["decidido_em"] = _agora()
    _gravar_registro(itens, registro)
    sincronizado = False
    try:
        sincronizado = bool((ressincronizar or _ressincronizar)())
    except Exception as exc:
        log.warn("sincronizacao apos negar falhou",
                 error=type(exc).__name__)
    log.info("faixa NEGADA pelo dono e apagada",
             artista=alvo.get("artista"), titulo=alvo.get("titulo"))
    return {"ok": True, "permitida": False, "item": alvo,
            "sync": sincronizado}


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
    apagar: Optional[Callable[[str], bool]] = None,
    ressincronizar: Optional[Callable[[], bool]] = None,
    agora: Optional[datetime] = None,
) -> dict[str, Any]:
    """Apaga as faixas cuja JANELA DE DECISÃO venceu (ordem de 17/11).

    Tocar não apaga mais nada: faixa de cantor/música bloqueada toca uma vez,
    o dono é avisado e tem ``HORAS_DECISAO`` (24 h) para permitir. Sem
    decisão, ela sai aqui — este é o relógio do prazo. Registro antigo, sem
    ``decidir_ate``, usa o prazo legado ``HORAS_LIMITE``.

    Devolve ``{"apagadas": n, "restantes": n, "sync": bool}``. Nunca
    levanta: o webhook da rádio não pode cair por causa da limpeza.
    """
    itens = _ler_registro(registro)
    if not itens:
        return {"apagadas": 0, "restantes": 0, "sync": False}
    apagar = apagar or _apagar_arquivo
    agora = agora or datetime.now(timezone.utc)
    legado = agora - timedelta(hours=HORAS_LIMITE)
    apagadas = 0
    restantes: list[dict[str, Any]] = []
    mudou = False
    for item in itens:
        if str(item.get("status") or "") != "aguardando":
            continue
        venceu = False
        try:
            prazo = str(item.get("decidir_ate") or "")
            if prazo:
                venceu = datetime.fromisoformat(prazo) < agora
            else:
                venceu = datetime.fromisoformat(
                    str(item.get("criado_em"))) < legado
        except ValueError:
            venceu = False
        if not venceu:
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


def excluir_musica_do_acervo(
    identificador: str,
    *,
    bloquear: bool = False,
    banco: Optional[Path] = None,
    caminho_bloqueadas: Optional[Path] = None,
    apagar: Optional[Callable[[str], bool]] = None,
    ressincronizar: Optional[Callable[[], bool]] = None,
) -> dict[str, Any]:
    """Exclui uma música do acervo (disco + acervo.db).

    NÃO bloqueia por padrão (ordem de 17/11: "músicas apagadas podem voltar a
    ser baixadas, posso apagar simplesmente por achar uma versão melhor");
    só grava em ``musicas_bloqueadas`` com ``bloquear=True`` explícito.
    """
    banco = Path(banco or (BASE_MUSICAS / "acervo.db"))
    if not banco.exists():
        return {"ok": False, "motivo": "banco_acervo_inexistente"}
    conn = sqlite3.connect(str(banco))
    try:
        cur = conn.cursor()
        linha = cur.execute(
            "SELECT caminho, artista, titulo FROM musicas WHERE caminho = ? OR caminho LIKE ?",
            (identificador, f"%{identificador}%"),
        ).fetchone()
        if not linha and " - " in identificador:
            art, tit = identificador.split(" - ", 1)
            linha = cur.execute(
                "SELECT caminho, artista, titulo FROM musicas WHERE artista LIKE ? AND titulo LIKE ?",
                (f"%{art.strip()}%", f"%{tit.strip()}%"),
            ).fetchone()
        if not linha:
            return {"ok": False, "motivo": "musica_nao_encontrada"}
        caminho_rel, artista, titulo = str(linha[0]), str(linha[1] or ""), str(linha[2] or "")
        cur.execute("DELETE FROM musicas WHERE caminho = ?", (caminho_rel,))
        conn.commit()
    finally:
        conn.close()

    apagar_fn = apagar or _apagar_arquivo
    try:
        apagar_fn(caminho_rel)
    except Exception as exc:
        log.warn("apagar arquivo da musica falhou", caminho=caminho_rel, error=type(exc).__name__)

    bloqueada_ok = False
    if bloquear and artista and titulo:
        bloqueada_ok = adicionar_musica_bloqueada(artista, titulo, caminho=caminho_bloqueadas)

    sync_fn = ressincronizar or _ressincronizar
    sync_ok = False
    try:
        sync_ok = bool(sync_fn())
    except Exception as exc:
        log.warn("sync apos exclusao falhou", error=type(exc).__name__)

    log.info("musica excluida do acervo", artista=artista, titulo=titulo, caminho=caminho_rel, bloqueada=bloquear)
    return {
        "ok": True,
        "caminho": caminho_rel,
        "artista": artista,
        "titulo": titulo,
        "bloqueada": bloquear,
        "sync": sync_ok,
    }


def linhas_do_arquivo(*, caminho: Optional[Path] = None) -> str:
    """Conteúdo cru da lista (para a API mostrar o arquivo como ele é)."""
    arquivo = _arquivo(caminho)
    if not arquivo.exists():
        return CABECALHO
    return arquivo.read_text(encoding="utf-8")


__all__ = [
    "LISTA", "LISTA_EXCECOES", "LISTA_BLOQUEADAS", "REGISTRO", "HORAS_LIMITE",
    "HORAS_DECISAO", "decidir", "aviso_de_decisao",
    "normalizar", "listar", "adicionar", "remover", "indesejado",
    "eh_excecao", "listar_excecoes", "adicionar_excecao", "remover_excecao", "linhas_excecoes",
    "musica_bloqueada", "listar_musicas_bloqueadas", "adicionar_musica_bloqueada",
    "remover_musica_bloqueada", "linhas_bloqueadas",
    "excluir_musica_do_acervo", "registrar_para_apagar", "pendentes",
    "historico_azuracast", "limpar_tocados", "linhas_do_arquivo",
]

