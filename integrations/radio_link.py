"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/radio_link.py
Descrição: Piloto do PEDIDO POR LINK do YouTube (ordem do dono, 02/11 —
           item 1): baixa, transforma e classifica pelo MESMO pipeline do
           acervo (musica.py) e devolve a faixa à fila do pedido.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Regras do dono (recado de 02/11, literal):
  * "se não for repetida o sistema baixa, transforma e classifica então
    ela passa a fazer parte do acervo";
  * "se o link for uma lista, baixa todas, mas vai tocar apenas a
    primeira";
  * "se a musica for link deve avisar o dono para que se for incoveniente
    não toca mais e sai da lista, vai cadastrar também o usuário para que
    ele possa ser comunicado da infração".

Desenho (05/11):
  - O POST nasce com status 'baixando' e sem caminho (radio_pro).
  - O handler dispara ESTE módulo como processo DESANEXADO
    (``python -m integrations.radio_link --pedido <id>``): download e
    Gemini levam minutos e não podem prender a thread do http.server.
  - O pipeline é o oficial (/home/alex/dados/musicas/musica.py, venv do
    acervo — o venv do od-core não tem yt-dlp). Cada execução ganha um
    TEMP_DIR isolado para não disputar ``temp/playlist.json`` nem drenar
    ``000/``/``limpar/`` do dono; o acervo, o .m3u e o AzuraCast são os
    compartilhados de propósito.
  - Duas execuções nunca se cruzam: ``flock`` em
    ``/home/alex/dados/musicas/.od_pipeline.lock`` (o flock morre com o
    processo — não fica trava órfã).
  - "Repetida" é decidida na FONTE: o dedupe do musica.py não deixa a
    faixa entrar no acervo.db. Se nada novo apareceu, o pedido vira
    'rejeitada' com motivo 'musica_repetida' e o dono é avisado.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Optional

from core.logger import get_logger
from integrations import radio_pro as rp

log = get_logger("omega.integrations.radio_link")

RAIZ = Path(__file__).resolve().parents[1]
BASE_MUSICAS = rp.BASE_MUSICAS
MUSICA_PY = Path(os.environ.get("OD_MUSICA_PY",
                                str(BASE_MUSICAS / "musica.py")))
MUSICA_PYTHON = Path(os.environ.get("OD_MUSICA_PYTHON",
                                    str(BASE_MUSICAS / "venv/bin/python")))
TRAVA = Path(os.environ.get("OD_RADIO_PIPELINE_LOCK",
                            str(BASE_MUSICAS / ".od_pipeline.lock")))
TEMP_BASE = Path(os.environ.get("OD_RADIO_LINK_TEMP", "/tmp"))
LOG_DIR = Path(os.environ.get("OD_RADIO_LINK_LOG", str(RAIZ / "logs")))
TIMEOUT_PRIMEIRA = int(os.environ.get("OD_RADIO_LINK_TIMEOUT", "1200"))
TIMEOUT_EXTRAIR = int(os.environ.get("OD_RADIO_LINK_TIMEOUT_EXTRACAO", "180"))
#: A lista "baixa todas" pode levar horas (DOWNLOAD_DELAY=3 min por faixa);
#: o teto é só para não deixar um processo pendurado para sempre.
TIMEOUT_RESTO = int(os.environ.get("OD_RADIO_LINK_TIMEOUT_RESTO", "86400"))
#: O resto da lista vai em LOTES: cada lote vira uma execução do pipeline
#: (acervo atualizado a cada lote) e ganha timeout proporcional ao tamanho —
#: antes o lote inteiro herdava os 1200 s do download único e morria no meio.
LOTE_RESTO = int(os.environ.get("OD_RADIO_LINK_LOTE_RESTO", "10"))
SEGUNDOS_POR_FAIXA = int(os.environ.get("OD_RADIO_LINK_SEG_POR_FAIXA",
                                     "300"))

#: Extração plana (rápida, sem baixar): devolve JSON com url/título de cada
#: entrada, na ordem da lista. Roda no venv do acervo (tem yt-dlp).
_EXTRACAO = r"""
import json, re, sys, yt_dlp
opts = {'extract_flat': True, 'skip_download': True,
        'quiet': True, 'no_warnings': True}
with yt_dlp.YoutubeDL(opts) as ydl:
    info = ydl.extract_info(sys.argv[1], download=False) or {}

def url_de(e):
    u = str(e.get('webpage_url') or e.get('url') or '')
    if re.fullmatch(r'[A-Za-z0-9_-]{11}', u):
        u = 'https://www.youtube.com/watch?v=' + u
    return u

def artistas_de(e):
    nomes = []
    for chave in ('artist', 'creator', 'album_artist', 'uploader', 'channel'):
        v = str(e.get(chave) or '').strip()
        if v and v not in nomes:
            nomes.append(v)
    return nomes

entradas = []
for e in (info.get('entries') or []):
    if not e:
        continue
    u = url_de(e)
    if u:
        entradas.append({'url': u, 'title': str(e.get('title') or ''),
                         'artistas': artistas_de(e)})
if not entradas:
    u = str(info.get('webpage_url') or sys.argv[1])
    entradas = [{'url': u, 'title': str(info.get('title') or ''),
                 'artistas': artistas_de(info)}]
print(json.dumps(entradas, ensure_ascii=False))
"""

#: Roda o musica.py com o TEMP_DIR isolado (playlist.json/limpar próprios)
#: e SEM drenar 000/ — o resto do pipeline (dedupe, Gemini, acervo, .m3u,
#: AzuraCast) é o oficial, sem fork de lógica.
_PIPELINE = r"""
import sys
from pathlib import Path
import musica

isolado = Path(sys.argv[1])
urls = sys.argv[2:]
isolado.mkdir(parents=True, exist_ok=True)
musica.TEMP_DIR = isolado
musica.PLAYLIST_FILE = isolado / 'playlist.json'
musica.LIMPAR_DIR = isolado / 'limpar'
musica.drenar_entrada = lambda: None
sys.argv = ['musica.py'] + urls
musica.main()
"""


def _sem_acento(texto: str) -> str:
    return rp._sem_acento(texto)


def _normalizar(texto: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ",
                           _sem_acento(texto)).split())


# ---------------------------------------------------------------------------
#  Pipeline do acervo (injetável nos testes — nada de rede/yt-dlp no gate)
# ---------------------------------------------------------------------------

def extrair_entradas(
    link: str,
    *,
    python: Optional[Path] = None,
    timeout: int = TIMEOUT_EXTRAIR,
) -> list[dict[str, str]]:
    """Lista as entradas do link (título + URL) sem baixar nada."""
    python = Path(python or MUSICA_PYTHON)
    if not python.exists():
        raise FileNotFoundError(f"python do acervo ausente: {python}")
    proc = subprocess.run(
        [str(python), "-c", _EXTRACAO, str(link)],
        cwd=str(BASE_MUSICAS), capture_output=True, text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            (proc.stderr or proc.stdout or "extração falhou").strip()[-400:])
    linhas = [linha for linha in (proc.stdout or "").splitlines()
              if linha.strip().startswith("[")]
    if not linhas:
        return []
    try:
        dados = json.loads(linhas[-1])
    except ValueError:
        return []
    saida = []
    for item in dados:
        if not isinstance(item, dict) or not item.get("url"):
            continue
        pistas = item.get("artistas")
        if isinstance(pistas, str):
            pistas = [pistas]
        saida.append({"url": str(item.get("url") or ""),
                      "title": str(item.get("title") or ""),
                      "artistas": [str(n).strip() for n in (pistas or [])
                                   if str(n).strip()]})
    return saida


def _pistas_de_artista(entrada: dict[str, Any]) -> list[str]:
    """Nomes de artista que o LINK já entrega — sem baixar e sem IA.

    O yt-dlp traz ``artist``/``creator``/``album_artist``/``uploader``/
    ``channel``; canal oficial costuma vir como "Fulano - Topic" e VEVO.
    O primeiro trecho do título ("Fulano - Música") cobre vídeo postado em
    canal de fã, onde o uploader não é o artista. São PISTAS: elas só
    decidem se a faixa nasce marcada para apagar — não bloqueiam nada.
    """
    pistas: list[str] = []
    brutos = entrada.get("artistas")
    if isinstance(brutos, str):
        brutos = [brutos]
    for nome in (brutos or []):
        nome = re.sub(r"\s*-\s*Topic$", "", str(nome).strip(), flags=re.I)
        nome = re.sub(r"\s*VEVO$", "", nome, flags=re.I).strip()
        if nome and nome not in pistas:
            pistas.append(nome)
    titulo = str(entrada.get("title") or "").strip()
    cabeca = re.split(r"\s+[-\u2013\u2014]\s+", titulo, maxsplit=1)[0].strip()
    if cabeca and len(cabeca) <= 60 and cabeca not in pistas:
        pistas.append(cabeca)
    return pistas


def rodar_pipeline(
    urls: list[str],
    *,
    python: Optional[Path] = None,
    script: Optional[Path] = None,
    timeout: Optional[int] = TIMEOUT_PRIMEIRA,
) -> int:
    """Roda o musica.py oficial para as URLs, com TEMP_DIR isolado.

    Devolve o código de saída (0 = pipeline completou). O stdout/stderr
    herdam o log do worker; o diretório isolado é limpo no sucesso e
    preservado no erro (para inspeção).
    """
    python = Path(python or MUSICA_PYTHON)
    script = Path(script or MUSICA_PY)
    if not python.exists():
        raise FileNotFoundError(f"python do acervo ausente: {python}")
    if not script.exists():
        raise FileNotFoundError(f"musica.py ausente: {script}")
    TEMP_BASE.mkdir(parents=True, exist_ok=True)
    isolado = Path(tempfile.mkdtemp(prefix="od_link_", dir=str(TEMP_BASE)))
    codigo = 1
    try:
        proc = subprocess.run(
            [str(python), "-c", _PIPELINE, str(isolado), *urls],
            cwd=str(BASE_MUSICAS), timeout=timeout,
        )
        codigo = int(proc.returncode)
    finally:
        if codigo == 0:
            shutil.rmtree(isolado, ignore_errors=True)
    if codigo != 0:
        log.warn("pipeline do link saiu com erro",
                 codigo=codigo, temp=str(isolado))
    return codigo


@contextmanager
def trava_pipeline(caminho: Optional[Path] = None):
    """Serializa as execuções do pipeline entre workers (flock)."""
    alvo = Path(caminho or TRAVA)
    alvo.parent.mkdir(parents=True, exist_ok=True)
    with alvo.open("w") as arquivo:
        fcntl.flock(arquivo.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(arquivo.fileno(), fcntl.LOCK_UN)


# ---------------------------------------------------------------------------
#  Acervo: o que apareceu de novo depois de rodar o pipeline
# ---------------------------------------------------------------------------

def _musicas_do_acervo(banco: Path) -> dict[str, dict[str, str]]:
    if not banco.exists():
        return {}
    try:
        conn = sqlite3.connect(f"file:{banco}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return {}
    try:
        linhas = conn.execute(
            "SELECT caminho, artista, titulo FROM musicas").fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    return {str(c): {"caminho": str(c), "artista": str(a or ""),
                     "titulo": str(t or "")} for c, a, t in linhas}


def _escolher(novas: list[dict[str, str]], titulo: str) -> dict[str, str]:
    """Entre as faixas novas, a que corresponde à PRIMEIRA entrada da lista."""
    if len(novas) == 1:
        return novas[0]
    alvo = set(_normalizar(titulo).split())
    melhor = novas[0]
    melhor_nota = -1
    for item in novas:
        palavras = set(_normalizar(
            f"{item['artista']} {item['titulo']}").split())
        nota = len({p for p in palavras if len(p) > 2} & alvo)
        if nota > melhor_nota:
            melhor, melhor_nota = item, nota
    return melhor


def _parece_repetida(titulo: str,
                     acervo: dict[str, dict[str, str]]) -> bool:
    """Pré-checagem barata: o título do YouTube já está no acervo?

    Evita baixar o óbvio (título "Artista - Música (Clipe Oficial)"
    contém "Artista Música" do acervo). Quem decide de verdade continua
    sendo o dedupe do pipeline — aqui só se evita o download inútil.
    """
    alvo = f" {_normalizar(titulo)} "
    if alvo.strip() == "":
        return False
    for item in acervo.values():
        nome = _normalizar(f"{item['artista']} {item['titulo']}")
        if len(nome.split()) >= 2 and f" {nome} " in alvo:
            return True
    return False


# ---------------------------------------------------------------------------
#  Aviso ao dono (Nexus — mesmo bot dos alertas de usuários)
# ---------------------------------------------------------------------------

def notificar_dono(
    texto: str, *, enviar: Optional[Callable[[str], Any]] = None
) -> bool:
    """Manda o aviso no Telegram do dono; falha nunca derruba o pedido.

    Resolve o bot igual ao launcher: papel "usuarios" e, sem chat próprio,
    os admins (OD_TELEGRAM_ADMINS). Sem token/chat só registra no log.
    """
    if enviar is not None:
        try:
            enviar(texto)
            return True
        except Exception as exc:
            log.warn("aviso do link falhou", error=type(exc).__name__)
            return False
    token = (os.environ.get("OD_TELEGRAM_USUARIOS_TOKEN")
             or os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chats = (os.environ.get("OD_TELEGRAM_USUARIOS_CHAT")
             or os.environ.get("OD_TELEGRAM_ADMINS") or "").strip()
    ids = [part.strip() for part in chats.split(",") if part.strip()]
    if not token or not ids:
        log.debug("sem token/chat para avisar o dono do link")
        return False
    from urllib.request import Request, urlopen
    enviados = False
    for chat in ids:
        corpo = json.dumps({"chat_id": chat, "text": texto,
                            "disable_web_page_preview": True}).encode()
        req = Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=corpo, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(req, timeout=8) as resp:
                resp.read()
            enviados = True
        except Exception as exc:
            log.warn("Telegram do dono recusou o aviso",
                     error=type(exc).__name__)
    return enviados


def _avisar(texto: str,
            notificar: Optional[Callable[[str], Any]]) -> None:
    if notificar is None:
        notificar_dono(texto)
        return
    try:
        notificar(texto)
    except Exception as exc:                  # aviso é caminho, não destino
        log.warn("aviso do link falhou", error=type(exc).__name__)


# ---------------------------------------------------------------------------
#  O worker
# ---------------------------------------------------------------------------

def _rejeitar(
    pedido: dict[str, Any],
    motivo: str,
    *,
    banco: Path,
    notificar: Optional[Callable[[str], Any]],
) -> dict[str, Any]:
    atualizado = rp.atualizar_pedido(
        int(pedido["id"]), status="rejeitada", motivo=motivo,
        banco=banco) or dict(pedido, status="rejeitada", motivo=motivo)
    texto = (f"⚠️ Pedido por link de @{pedido.get('usuario')} não entrou:"
             f" {motivo}.")
    if pedido.get("link"):
        texto += f"\n{pedido['link']}"
    _avisar(texto, notificar)
    return {"ok": False, "pedido": atualizado, "motivo": motivo}


def _avisar_resultado(
    pedido: dict[str, Any],
    notificar: Optional[Callable[[str], Any]],
) -> None:
    nome = f"{pedido.get('artista') or ''} - {pedido.get('titulo') or ''}"
    nome = nome.strip(" -") or "pedido"
    if pedido.get("status") == "na_fila":
        texto = (f"✅ Pedido por link de @{pedido.get('usuario')}: {nome}"
                 " → na fila da rádio ✓")
    elif pedido.get("status") == "pendente":
        texto = (f"🎵 Pedido por link de @{pedido.get('usuario')}: {nome}"
                 f" → pendente ({pedido.get('motivo') or 'fila fora'})")
    else:
        texto = (f"🎵 Pedido por link de @{pedido.get('usuario')}: {nome}"
                 f" ({pedido.get('status')})")
    if pedido.get("link"):
        texto += f"\n{pedido['link']}"
    _avisar(texto, notificar)


def timeout_do_lote(quantidade: int) -> int:
    """Teto de tempo de um lote do resto da lista (nunca o do download único)."""
    return min(TIMEOUT_RESTO,
               max(TIMEOUT_PRIMEIRA, SEGUNDOS_POR_FAIXA * max(1, quantidade)))


def _baixar_resto(
    restantes: list[dict[str, str]],
    pedido: dict[str, Any],
    *,
    trava: Callable[[], Any],
    rodar: Callable[..., int],
    notificar: Optional[Callable[[str], Any]],
    lote: Optional[int] = None,
) -> None:
    """Lista: baixa TODAS as outras faixas em segundo plano (só a 1ª toca).

    Vai em lotes de ``LOTE_RESTO`` faixas. Cada lote é uma execução do
    pipeline (o acervo cresce a cada lote) com timeout proporcional ao
    tamanho — um lote são 10 faixas × 3 min de espera, não caberia nos
    1200 s do download único. Um lote que falha não derruba os seguintes.
    """
    urls = [str(item["url"]) for item in restantes if item.get("url")]
    if not urls:
        return
    tamanho = max(1, int(lote or LOTE_RESTO))
    _avisar(
        f"📥 Lista de @{pedido.get('usuario')}: {len(urls)} faixa(s)"
        " restante(s) baixando em segundo plano, em lotes de"
        f" {min(tamanho, len(urls))} (só a primeira toca agora).",
        notificar,
    )
    falhas = 0
    lotes = 0
    for inicio in range(0, len(urls), tamanho):
        bloco = urls[inicio:inicio + tamanho]
        lotes += 1
        try:
            with trava():
                codigo = int(rodar(
                    bloco, timeout=timeout_do_lote(len(bloco))) or 0)
        except Exception as exc:
            falhas += 1
            log.warn("download do resto da lista falhou",
                     error=type(exc).__name__,
                     lote=f"{inicio + 1}-{inicio + len(bloco)}")
            continue
        if codigo != 0:
            falhas += 1
            log.warn("lote do resto da lista saiu com erro",
                     codigo=codigo,
                     lote=f"{inicio + 1}-{inicio + len(bloco)}")
    if falhas:
        _avisar(
            f"⚠️ Lista de @{pedido.get('usuario')}: {len(urls)} faixa(s)"
            f" restante(s) em {lotes} lote(s), {falhas} com falha — o resto"
            " entrou no acervo. Detalhe em logs/radio_link_"
            f"{pedido.get('id')}.log.",
            notificar,
        )
    else:
        _avisar(
            f"📥 Lista de @{pedido.get('usuario')}: as {len(urls)} faixa(s)"
            f" restantes foram processadas em {lotes} lote(s) (as repetidas"
            " o dedupe descarta).",
            notificar,
        )


def processar_pedido(
    pedido_id: int,
    *,
    banco: Optional[Path] = None,
    banco_acervo: Optional[Path] = None,
    extrair: Optional[Callable[[str], list[dict[str, str]]]] = None,
    rodar: Optional[Callable[[list[str]], int]] = None,
    lancar: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None,
    notificar: Optional[Callable[[str], Any]] = None,
    trava: Optional[Callable[[], Any]] = None,
    cantores_lista: Optional[Path] = None,
    cantores_registro: Optional[Path] = None,
) -> dict[str, Any]:
    """Baixa/classifica o link do pedido e o devolve à fila.

    Idempotente: só age enquanto o status é 'baixando'; rodar de novo num
    pedido já processado devolve ``motivo='ja_processado'``. Todas as
    peças externas (extração, pipeline, fila, aviso, trava) são
    injetáveis — o gate roda sem rede, sem yt-dlp e sem AzuraCast.
    """
    banco = banco or rp.BANCO_PEDIDOS
    banco_acervo = banco_acervo or rp.BANCO_ACERVO
    pedido = rp.pedido_por_id(pedido_id, banco=banco)
    if pedido is None:
        return {"ok": False, "motivo": "pedido_inexistente",
                "pedido_id": int(pedido_id)}
    if pedido.get("status") != "baixando":
        return {"ok": True, "pedido": pedido, "motivo": "ja_processado"}
    link = str(pedido.get("link") or "")
    if not link:
        return _rejeitar(pedido, "link_invalido", banco=banco,
                         notificar=notificar)

    extrair = extrair or extrair_entradas
    rodar = rodar or rodar_pipeline
    trava = trava or trava_pipeline
    try:
        entradas = extrair(link) or []
    except Exception as exc:
        log.warn("extração do link falhou", pedido=int(pedido_id),
                 error=type(exc).__name__)
        entradas = []
    entradas = [item for item in entradas
                if isinstance(item, dict) and item.get("url")]
    if not entradas:
        return _rejeitar(pedido, "link_invalido", banco=banco,
                         notificar=notificar)

    primeira = entradas[0]
    # Cantor indesejado (ordem do dono 05/11): o link JÁ diz o artista antes
    # de baixar. Se ele está na lista, a faixa nasce marcada — mesmo que o
    # AzuraCast recuse a fila ou a IA tagueie o artista errado depois.
    try:
        from integrations import radio_cantores
        indesejado_no_link = any(
            radio_cantores.indesejado(pista, caminho=cantores_lista)
            for pista in _pistas_de_artista(primeira))
    except Exception as exc:                  # lista é regra, não portão
        log.warn("checagem de cantor indesejado falhou",
                 error=type(exc).__name__)
        radio_cantores = None
        indesejado_no_link = False
    antes = _musicas_do_acervo(banco_acervo)
    if _parece_repetida(str(primeira.get("title") or ""), antes):
        # Já está no acervo pelo título: não baixa de novo (o pipeline
        # também barraria, mas isso economiza download e cota do Gemini).
        resultado = _rejeitar(pedido, "musica_repetida", banco=banco,
                              notificar=notificar)
        if len(entradas) > 1:
            _baixar_resto(entradas[1:], pedido, trava=trava, rodar=rodar,
                          notificar=notificar)
        return resultado
    codigo = 1
    try:
        with trava():
            codigo = int(rodar([str(primeira["url"])]) or 0)
    except Exception as exc:
        log.error("pipeline do link falhou", pedido=int(pedido_id),
                  error=type(exc).__name__)
        codigo = 1

    atuais = _musicas_do_acervo(banco_acervo)
    novas = [item for caminho, item in atuais.items() if caminho not in antes]
    if not novas:
        # Nada entrou: o dedupe do pipeline viu repetida (código 0) ou o
        # download/processamento falhou. A lista ainda vale: baixa o resto.
        motivo = "musica_repetida" if codigo == 0 else "falha_download"
        resultado = _rejeitar(pedido, motivo, banco=banco,
                              notificar=notificar)
        if codigo == 0 and len(entradas) > 1:
            _baixar_resto(entradas[1:], pedido, trava=trava, rodar=rodar,
                          notificar=notificar)
        return resultado

    musica = _escolher(novas, str(primeira.get("title") or ""))
    pedido = rp.atualizar_pedido(
        int(pedido_id), artista=musica["artista"], titulo=musica["titulo"],
        caminho=musica["caminho"], status="pendente", motivo="",
        banco=banco) or pedido

    if radio_cantores is not None:
        try:
            if indesejado_no_link or radio_cantores.indesejado(
                    str(musica.get("artista") or ""),
                    caminho=cantores_lista):
                radio_cantores.registrar_para_apagar(
                    str(musica.get("artista") or ""),
                    str(musica.get("titulo") or ""),
                    str(musica.get("caminho") or ""),
                    registro=cantores_registro)
        except Exception as exc:
            log.warn("registro de cantor indesejado falhou",
                     error=type(exc).__name__)

    lancar = lancar or (lambda p: rp.lancar_pedido_na_fila(p, banco=banco))
    try:
        lancar(pedido)
    except Exception as exc:                  # fila é caminho, não destino
        log.warn("lançar pedido do link falhou",
                 error=type(exc).__name__)
    pedido = rp.pedido_por_id(int(pedido_id), banco=banco) or pedido
    _avisar_resultado(pedido, notificar)

    if len(entradas) > 1:
        _baixar_resto(entradas[1:], pedido, trava=trava, rodar=rodar,
                      notificar=notificar)
    return {"ok": True, "pedido": pedido,
            "fila": pedido.get("status") == "na_fila",
            "motivo": pedido.get("motivo") or ""}


# ---------------------------------------------------------------------------
#  Disparo pelo handler (processo desanexado) e CLI
# ---------------------------------------------------------------------------

def iniciar_processamento(
    pedido_id: int, *, popen: Optional[Callable[..., Any]] = None
) -> Any:
    """Sobe o worker em processo próprio, sem prender o HTTP.

    start_new_session=True desliga o worker do grupo do servidor: um
    restart do od-core não mata o download no meio. O log fica em
    ``logs/radio_link_<id>.log``.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    destino = LOG_DIR / f"radio_link_{int(pedido_id)}.log"
    with destino.open("a", encoding="utf-8") as logf:
        proc = (popen or subprocess.Popen)(
            [sys.executable, "-m", "integrations.radio_link",
             "--pedido", str(int(pedido_id))],
            cwd=str(RAIZ), stdout=logf, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
    return proc


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Worker do pedido por link do YouTube (rádio Nicky)")
    parser.add_argument("--pedido", type=int, required=True,
                        help="id do pedido em data/radio_pedidos.db")
    args = parser.parse_args(argv)
    resultado = processar_pedido(int(args.pedido))
    print(json.dumps(resultado, ensure_ascii=False, default=str))
    return 0 if resultado.get("ok") else 1


if __name__ == "__main__":       # pragma: no cover — processo desanexado
    raise SystemExit(main())
