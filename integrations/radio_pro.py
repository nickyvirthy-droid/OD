"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/radio_pro.py
Descrição: Área do ouvinte LOGADO da rádio Nicky (ordem do dono, 04/11/2026):
           letra da música que está tocando, busca no acervo e fila de
           pedidos de música com recado para a locutora.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Decisões registradas (ver iniciar/2026-11-04_conversa_omegadrakon.md):
  - Só stdlib (urllib + sqlite3 + json): a área do ouvinte não ganha
    dependência nova — mesma régua de radio_agora.
  - Letra vem de serviço público sem chave (lyrics.ovh), com cache em
    arquivo: a página sonda a cada 15 s e não pode martelar a API. Letra
    não encontrada fica no cache por 6 h (negativa curta) e encontrada
    por 7 dias. Fonte fora do ar NUNCA derruba a página: devolve
    {"ok": false, "motivo": "indisponivel"} e o resto da tela funciona.
  - acervo.db aberto em modo leitura (file:?mode=ro): quem ESCREVE é só
    o pipeline de músicas; aqui só se lê o catálogo.
  - Pedido é FILA (decisão do dono, 04/11: "Ligue o pedido de música para
    tocar de verdade na rádio, com fila e aviso da locutora"): cria linha
    em data/radio_pedidos.db (SQLite próprio, fora do banco do core),
    empurra para a fila REAL do AzuraCast via lancar_pedido_na_fila() e o
    dono é avisado no Telegram. Sem chave da API o pedido continua
    'pendente' (o caminho de antes) — nada some, nada inventa fila.
  - O aviso da locutora: anuncio_de_pedido() devolve o texto do recado no
    ciclo de locução em que a faixa pedida está por vir — lido antes de
    ela tocar e marcado 'tocada' para não repetir (radio_webhook).
  - Limites de segurança já no MVP: 1 pedido pendente por conta, 3 por
    dia, recado de até 200 caracteres e só música que existe no acervo
    (nada de caminho inventado — o nome vem do catálogo do servidor).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sqlite3
import subprocess
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from core.logger import get_logger

log = get_logger("omega.integrations.radio_pro")

BASE_MUSICAS = Path(os.environ.get("MP3_BASE_DIR", "/home/alex/dados/musicas"))
BANCO_ACERVO = BASE_MUSICAS / "acervo.db"          # Item 4 — só o link, nunca o áudio
BANCO_PEDIDOS = Path(
    os.environ.get("OD_RADIO_PEDIDOS_DB", "data/radio_pedidos.db")
)
CACHE_LETRAS = Path(
    os.environ.get("OD_RADIO_LETRAS_CACHE", "data/radio_letras_cache.json")
)
LETRAS_API = os.environ.get("OD_RADIO_LETRAS_API", "https://api.lyrics.ovh/v1")
LRCLIB_API = os.environ.get("OD_RADIO_LRCLIB_API", "https://lrclib.net/api")
USER_AGENT = "od-core-radio/1.0 (+https://nicky-server.tail1b1f51.ts.net)"

# AzuraCast (fila real da estação): a chave é criada no admin e vive só no
# .env — sem ela o pedido fica registrado como "manual" e o dono decide.
AZURA_API = os.environ.get("OD_AZURA_API", "http://127.0.0.1:8091")
AZURA_KEY = os.environ.get("AZURACAST_API_KEY", "")
AZURA_STATION = os.environ.get("OD_AZURA_STATION", "nicky")

TTL_ENCONTRADA_S = 7 * 24 * 3600         # letra boa dura a semana
TTL_NAO_ENCONTRADA_S = 6 * 3600          # negativa curta: pode aparecer depois
CACHE_MAX = 400                          # teto do arquivo de cache
RECADO_MAX = 200                         # recado da locução
COOLDOWN_MINUTOS = 30                    # um pedido por conta a cada meia hora
CATALOGO_LIMITE = 40
CATALOGO_LIMITE_MAX = 200


# ---------------------------------------------------------------------------
#  Letra da música (serviço público, cache em arquivo)
# ---------------------------------------------------------------------------

def _sem_acento(texto: str) -> str:
    """Minúsculas sem acento — a busca do serviço de letras é literal."""
    base = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in base if not unicodedata.combining(c)).lower()


def _variacoes_artista(artista: str) -> list[str]:
    """Artista completo e, quando há dupla ("A e B"), só o primeiro.

    O acervo do dono grava dupla como "Giselli Cristina e Moisés Cleyton";
    o serviço de letras indexa cada cantor separado.
    """
    nome = (artista or "").strip()
    if not nome:
        return [""]
    variacoes = [nome]
    for separador in (" e ", " & ", " feat. ", " ft. "):
        if separador in nome.lower():
            primeiro = nome[: nome.lower().index(separador)].strip()
            if primeiro and primeiro not in variacoes:
                variacoes.append(primeiro)
    return variacoes


def _le_cache(cache: Path) -> dict[str, Any]:
    try:
        dados = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dados if isinstance(dados, dict) else {}


def _grava_cache(cache: Path, dados: dict[str, Any]) -> None:
    """Grava o cache por arquivo temporário — leitor nunca vê JSON pela metade."""
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        if len(dados) > CACHE_MAX:               # descarta as mais antigas
            for chave, _ in sorted(
                dados.items(), key=lambda kv: float(kv[1].get("em") or 0)
            )[: len(dados) - CACHE_MAX]:
                dados.pop(chave, None)
        temporario = cache.with_suffix(cache.suffix + ".tmp")
        temporario.write_text(
            json.dumps(dados, ensure_ascii=False), encoding="utf-8"
        )
        temporario.replace(cache)
    except OSError as exc:                      # cache é enfeite, não defeito
        log.warn("cache de letras não gravou", error=str(exc))


def _busca_lrclib(artista: str, titulo: str, timeout: float = 8.0) -> Optional[str]:
    """lrclib.net (aberto, sem chave) — 2ª fonte, com letra simples.

    A busca é por track_name/artist_name; escolhe o primeiro resultado com
    `plainLyrics` não vazio. Nunca levanta exceção.
    """
    url = (f"{LRCLIB_API}/search?track_name={quote(titulo, safe='')}"
           f"&artist_name={quote(artista, safe='')}")
    req = Request(url, headers={"User-Agent": USER_AGENT,
                                "Accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            dados = json.loads(resp.read().decode("utf-8", "replace"))
    except HTTPError as exc:
        # 404 do lrclib é "não achei esta música no catálogo", não é pane —
        # WARN aqui viraria ruído no journal (a régua de reverificação conta).
        if exc.code != 404:
            log.warn("lrclib indisponível", status=exc.code)
        return None
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        log.warn("lrclib indisponível", error=type(exc).__name__)
        return None
    if isinstance(dados, dict) and dados.get("plainLyrics"):
        return str(dados["plainLyrics"]).strip() or None
    if not isinstance(dados, list):
        return None
    # prefere o resultado que casa artista (sem acento) e ordem original
    for item in dados:
        letra = str((item or {}).get("plainLyrics") or "").strip()
        if letra:
            return letra
    return None


def _busca_lyrics_ovh(artista: str, titulo: str, timeout: float = 6.0) -> Optional[str]:
    """Chama lyrics.ovh; devolve a letra ou None. Nunca levanta exceção."""
    url = f"{LETRAS_API}/{quote(artista, safe='')}/{quote(titulo, safe='')}"
    req = Request(url, headers={"User-Agent": USER_AGENT,
                                "Accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:       # stdlib, sem requests
            dados = json.loads(resp.read().decode("utf-8", "replace"))
    except HTTPError as exc:
        if exc.code == 404:
            return None
        log.warn("serviço de letras respondeu erro", status=exc.code)
        return None
    except (URLError, TimeoutError, ValueError) as exc:
        log.warn("serviço de letras indisponível", error=type(exc).__name__)
        return None
    letra = str((dados or {}).get("lyrics") or "").strip()
    return letra or None


def letra_da_musica(
    artista: str,
    titulo: str,
    *,
    cache_arq: Optional[Path] = None,
    buscar: Optional[Callable[[str, str], Optional[str]]] = None,
) -> dict[str, Any]:
    """Letra da música do ar — contrato da área do ouvinte.

    {"ok": true, "letra": str, "fonte": "lyrics.ovh", "cache": bool}
    {"ok": false, "motivo": "sem_musica"|"nao_encontrada"|"indisponivel"}

    NUNCA levanta exceção: a tela mostra o que der e o resto continua.
    """
    titulo = (titulo or "").strip()
    artista = (artista or "").strip()
    if not titulo or _sem_acento(titulo).startswith("locucao"):
        return {"ok": False, "motivo": "sem_musica"}

    cache_arq = cache_arq or CACHE_LETRAS
    chave = f"{_sem_acento(artista)}|{_sem_acento(titulo)}"
    cache = _le_cache(cache_arq)
    agora = time.time()
    entrada = cache.get(chave)
    if isinstance(entrada, dict):
        ttl = TTL_ENCONTRADA_S if entrada.get("letra") else TTL_NAO_ENCONTRADA_S
        if agora - float(entrada.get("em") or 0) < ttl:
            if entrada.get("letra"):
                return {"ok": True, "letra": entrada["letra"],
                        "fonte": entrada.get("fonte") or "lrclib",
                        "cache": True}
            return {"ok": False, "motivo": "nao_encontrada"}

    # Duas fontes em cadeia (ordem do dono, 04/11: "cobrir gospel e
    # lançamentos"): lrclib.net primeiro (catálogo aberto e amplo) e
    # lyrics.ovh como reserva. `buscar` injetado vira a única fonte.
    fontes = ([(buscar, "injetada")] if buscar is not None else
              [(_busca_lrclib, "lrclib"), (_busca_lyrics_ovh, "lyrics.ovh")])
    indisponivel = False
    letra = None
    fonte = ""
    for funcao, nome_fonte in fontes:
        for variacao in _variacoes_artista(artista):
            if not variacao:
                continue
            try:
                letra = funcao(variacao, titulo)
            except Exception as exc:          # fonte quebrada não derruba a tela
                log.warn("busca de letra falhou", fonte=nome_fonte,
                         error=type(exc).__name__)
                indisponivel = True
                letra = None
            if letra:
                fonte = nome_fonte
                break
        if letra:
            break

    if letra:
        cache[chave] = {"letra": letra, "em": agora, "fonte": fonte}
        _grava_cache(cache_arq, cache)
        return {"ok": True, "letra": letra, "fonte": fonte or "lrclib",
                "cache": False}
    if indisponivel:
        return {"ok": False, "motivo": "indisponivel"}
    cache[chave] = {"letra": "", "em": agora}
    _grava_cache(cache_arq, cache)
    return {"ok": False, "motivo": "nao_encontrada"}


# ---------------------------------------------------------------------------
#  Catálogo do acervo (leitura pura do acervo.db)
# ---------------------------------------------------------------------------

def catalogo_musicas(
    termo: str = "",
    limite: int = CATALOGO_LIMITE,
    *,
    banco: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Músicas do acervo para a lista de pedido — só o que existe no servidor.

    O caminho é o MESMO do acervo.db (o "link" para o arquivo, nunca o
    áudio). Busca por artista ou título, sem acento e sem caixa.
    """
    banco = banco or BANCO_ACERVO
    try:
        limite = max(1, min(int(limite), CATALOGO_LIMITE_MAX))
    except (TypeError, ValueError):
        limite = CATALOGO_LIMITE
    termo = (termo or "").strip()
    try:
        conn = sqlite3.connect(f"file:{banco}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as exc:
        log.warn("acervo.db inacessível para o catálogo", error=str(exc))
        return []
    try:
        sql = ("SELECT caminho, artista, titulo, genero FROM musicas"
               " ORDER BY artista COLLATE NOCASE, titulo COLLATE NOCASE"
               " LIMIT ?")
        parametros: tuple[Any, ...] = (limite,)
        if termo:
            alvo = f"%{termo.lower()}%"
            sql = ("SELECT caminho, artista, titulo, genero FROM musicas"
                   " WHERE lower(artista) LIKE ? OR lower(titulo) LIKE ?"
                   " ORDER BY artista COLLATE NOCASE, titulo COLLATE NOCASE"
                   " LIMIT ?")
            parametros = (alvo, alvo, limite)
        linhas = conn.execute(sql, parametros).fetchall()
    except sqlite3.Error as exc:
        log.warn("consulta do catálogo falhou", error=str(exc))
        return []
    finally:
        conn.close()
    return [
        {"caminho": str(c), "artista": str(a or ""), "titulo": str(t or ""),
         "genero": str(g or "")}
        for c, a, t, g in linhas
    ]


def musica_do_acervo(
    caminho: str, *, banco: Optional[Path] = None
) -> Optional[dict[str, Any]]:
    """A música do acervo com esse caminho, ou None (fora do acervo)."""
    caminho = (caminho or "").strip()
    if not caminho:
        return None
    banco = banco or BANCO_ACERVO
    try:
        conn = sqlite3.connect(f"file:{banco}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None
    try:
        linha = conn.execute(
            "SELECT caminho, artista, titulo, genero FROM musicas"
            " WHERE caminho = ?", (caminho,)
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if linha is None:
        return None
    return {"caminho": str(linha[0]), "artista": str(linha[1] or ""),
            "titulo": str(linha[2] or ""), "genero": str(linha[3] or "")}


# ---------------------------------------------------------------------------
#  Fila de pedidos (SQLite próprio — tabela nova, sem migração do core)
# ---------------------------------------------------------------------------

_ESQUEMA_PEDIDOS = """
CREATE TABLE IF NOT EXISTS pedidos (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em TEXT NOT NULL,
    usuario   TEXT NOT NULL,
    artista   TEXT NOT NULL DEFAULT '',
    titulo    TEXT NOT NULL DEFAULT '',
    caminho   TEXT NOT NULL,
    recado    TEXT NOT NULL DEFAULT '',
    status    TEXT NOT NULL DEFAULT 'pendente'
)
"""


def _conexao(banco: Path) -> sqlite3.Connection:
    banco.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(banco), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(_ESQUEMA_PEDIDOS)
    return conn


def limpar_recado(recado: str) -> str:
    """Recado numa linha só, sem espaço sobrando — é fala de locutora."""
    return " ".join(str(recado or "").split())


def criar_pedido(
    usuario: str,
    caminho: str,
    recado: str = "",
    *,
    banco: Optional[Path] = None,
    banco_acervo: Optional[Path] = None,
    agora: Optional[datetime] = None,
) -> dict[str, Any]:
    """Registra um pedido de música do ouvinte logado.

    Levanta ValueError com um motivo estável (o handler vira status HTTP):
      login_obrigatorio · musica_desconhecida · recado_longo ·
      limite_tempo

    Um pedido por conta a cada COOLDOWN_MINUTOS (ordem do dono, 04/11:
    "deixe o usuário realizar pedidos a cada meia hora") — o relógio é
    por conta e vale para QUALQUER status: conta o tempo desde o último
    pedido da conta, nem o pendente perdido nem a música já tocada
    voltam a segurar a fila. `agora` injeta o instante nos testes.
    """
    usuario = (usuario or "").strip()
    if not usuario:
        raise ValueError("login_obrigatorio")
    musica = musica_do_acervo(caminho, banco=banco_acervo)
    if musica is None:
        raise ValueError("musica_desconhecida")
    recado = limpar_recado(recado)
    if len(recado) > RECADO_MAX:
        raise ValueError("recado_longo")

    banco = banco or BANCO_PEDIDOS
    instante = agora or datetime.now()
    conn = _conexao(banco)
    try:
        # O único limite é o tempo desde o ÚLTIMO pedido da conta — o
        # status dele nem importa (antigamente eram "1 pendente" e
        # "3 por dia"; o dono pediu 1 a cada meia hora).
        ultima = conn.execute(
            "SELECT criado_em FROM pedidos WHERE usuario = ?"
            " ORDER BY id DESC LIMIT 1",
            (usuario,),
        ).fetchone()
        if ultima is not None:
            try:
                anterior = datetime.fromisoformat(str(ultima[0]))
            except ValueError:
                anterior = None
            if (anterior is not None
                    and instante - anterior < timedelta(
                        minutes=COOLDOWN_MINUTOS)):
                raise ValueError("limite_tempo")
        agora = instante.strftime("%Y-%m-%dT%H:%M:%S")
        cursor = conn.execute(
            "INSERT INTO pedidos (criado_em, usuario, artista, titulo,"
            " caminho, recado, status) VALUES (?, ?, ?, ?, ?, ?, 'pendente')",
            (agora, usuario, musica["artista"], musica["titulo"],
             musica["caminho"], recado),
        )
        conn.commit()
        pedido_id = int(cursor.lastrowid or 0)
    finally:
        conn.close()
    return {"id": pedido_id, "criado_em": agora, "usuario": usuario,
            "artista": musica["artista"], "titulo": musica["titulo"],
            "recado": recado, "status": "pendente"}


def meus_pedidos(
    usuario: str, limite: int = 5, *, banco: Optional[Path] = None
) -> list[dict[str, Any]]:
    """Últimos pedidos da conta (o mais novo primeiro) — nada de outra conta."""
    usuario = (usuario or "").strip()
    if not usuario:
        return []
    banco = banco or BANCO_PEDIDOS
    if not banco.exists():
        return []
    try:
        conn = _conexao(banco)
    except sqlite3.Error:
        return []
    try:
        linhas = conn.execute(
            "SELECT id, criado_em, artista, titulo, recado, status"
            " FROM pedidos WHERE usuario = ? ORDER BY id DESC LIMIT ?",
            (usuario, max(1, int(limite))),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    return [
        {"id": int(i), "criado_em": str(c), "artista": str(a or ""),
         "titulo": str(t or ""), "recado": str(r or ""), "status": str(s)}
        for i, c, a, t, r, s in linhas
    ]


# ---------------------------------------------------------------------------
#  Fila real da estação (AzuraCast) — o pedido TOCA
# ---------------------------------------------------------------------------

#: unique_id do jingle "anuncio musica" no acervo do AzuraCast — o mesmo
#: id da URL /request/{unique_id}; no INSERT ele vira track_id via um
#: SELECT em station_media.
JINGLE_ANUNCIO = "e3115b6a17e7ee9d668d5e9d"
#: Título da mídia do jingle (o dono troca o MP3, o nome fica).
ANUNCIO_TITULO = "anuncio musica"
#: request_delay do AzuraCast (15 min) + folga: timestamp com 31 min já
#: consumidos vence o shouldPlayNow mesmo com o sorteio no máximo
#: (15 + random_int(0..15)) — jingle e música nascem jogáveis juntos e
#: o AutoDJ (getNextSongFromRequests, ordem por id) monta [jingle, música].
ATRASO_SEGURO_MIN = 31
#: request_threshold do AzuraCast: o jingle tocado há menos de 10 min
#: trava um novo jingle (isDuplicateOfPlayedTrack). Nesse caso a música
#: entra com timestamp NORMAL — ela só fica jogável (15 min) depois de o
#: jingle destravar (10 min), e a ordem J→P se mantém mesmo assim.
JINGLE_ESPERA_MIN = 10
#: Coluna ip de station_requests é NOT NULL: o SubmitAction grava o IP
#: do ouvinte, aqui é sempre o nosso núcleo.
PEDIDO_IP = "od-core"

def _azuracast(
    caminho: str,
    *,
    metodo: str = "GET",
    api: Optional[str] = None,
    chave: Optional[str] = None,
    timeout: float = 8.0,
) -> tuple[Optional[int], Any]:
    """Chamada JSON à API do AzuraCast. Devolve (status, dados); nunca levanta."""
    api = api or AZURA_API
    chave = chave if chave is not None else AZURA_KEY
    if not chave:
        return None, None
    req = Request(
        api + caminho, method=metodo,
        data=b"{}" if metodo == "POST" else None,
        headers={"X-API-Key": chave, "Accept": "application/json",
                 "Content-Type": "application/json",
                 "User-Agent": USER_AGENT},
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            corpo = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(corpo)
            except ValueError:
                return resp.status, corpo
    except HTTPError as exc:
        log.warn("AzuraCast recusou o pedido", status=exc.code)
        return exc.code, None
    except (URLError, TimeoutError, OSError) as exc:
        log.warn("AzuraCast indisponível para o pedido", error=type(exc).__name__)
        return None, None


def _mesma_musica(a: str, b: str) -> bool:
    """Compara artista/título sem caixa e sem acento (nomes do acervo × Azura)."""
    a, b = _sem_acento(a).strip(), _sem_acento(b).strip()
    return bool(a) and bool(b) and a == b


def _uid_valido(uid: str) -> bool:
    """unique_id do AzuraCast:24 hex — só isso chega ao SQL."""
    return bool(re.fullmatch(r"[0-9a-f]{24}", uid or ""))


def _jingle_tocou_recentemente(
    *, api: Optional[str] = None, chave: Optional[str] = None
) -> bool:
    """True quando o jingle "anuncio musica" tocou nos últimos 10 min.

    É a régua do request_threshold do AzuraCast lida pelo nosso lado:
    jingle recente trava o próximo jingle dele, e aí a música pedida
    entra com timestamp normal para a ordem J→P não se perder.
    """
    status, dados = _azuracast(
        f"/api/station/{AZURA_STATION}/history?limit=50", api=api, chave=chave
    )
    if status != 200 or not isinstance(dados, list):
        return False
    corte = time.time() - JINGLE_ESPERA_MIN * 60
    for item in dados:
        song = (item or {}).get("song") or {}
        if not _mesma_musica(str(song.get("title") or ""), ANUNCIO_TITULO):
            continue
        try:
            quando = float((item or {}).get("played_at") or 0)
        except (TypeError, ValueError):
            quando = 0.0
        if quando >= corte:
            return True
    return False


def _mariadb(sql: str) -> tuple[bool, str]:
    """Roda SQL no MariaDB do container AzuraCast (docker exec).

    Devolve (ok, saída). É o mesmo caminho das demais operações da casa
    (sem porta nova na rede e sem dependência de driver no od-core).
    """
    comando = (
        'mariadb -N -B -h"$MYSQL_HOST" -u"$MYSQL_USER"'
        ' -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" -e ' + shlex.quote(sql)
    )
    try:
        proc = subprocess.run(
            ["docker", "exec", "azuracast", "sh", "-c", comando],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warn("MariaDB do AzuraCast inacessível", error=type(exc).__name__)
        return False, ""
    return proc.returncode == 0, proc.stdout or ""


def _inserir_requests(
    uid_jingle: str, uid_musica: str, ts_jingle: str, ts_musica: str,
    *, rodar: Optional[Callable[[str], tuple[bool, str]]] = None,
) -> bool:
    """Enfileira J (jingle) e P (música) direto em station_requests.

    É o MESMO INSERT do SubmitAction da API do AzuraCast (station_id,
    track_id, timestamp, skip_delay=0, played_at NULL) — só que com o
    timestamp já vencido nos DOIS, o que garante a ordem J→P na fila
    (getNextSongFromRequests devolve por id) sem o sorteio de 15–30 min
    por música que inverteria as duas quase metade das vezes.

    `rodar` é o executor de SQL (padrão: docker exec no mariadb) —
    injetável nos testes, que exercitam o parser e o INSERT sem container.
    """
    if not (_uid_valido(uid_jingle) and _uid_valido(uid_musica)):
        return False
    rodar = rodar or _mariadb
    ok, saida = rodar(
        "SELECT 'mid', unique_id, id FROM station_media"
        f" WHERE unique_id IN ('{uid_jingle}', '{uid_musica}');"
        " SELECT 'st', '', id FROM station WHERE LOWER(name)"
        f" = LOWER('{AZURA_STATION}');"
    )
    if not ok:
        return False
    mids: dict[str, int] = {}
    estacao = 0
    for linha in saida.splitlines():
        partes = linha.split("\t")
        if len(partes) != 3:
            continue
        marca, chave, valor = partes
        if marca == "mid":
            try:
                mids[chave] = int(valor)
            except ValueError:
                continue
        elif marca == "st":
            try:
                estacao = int(valor)
            except ValueError:
                continue
    if not estacao or uid_jingle not in mids or uid_musica not in mids:
        log.warn("AzuraCast sem jingle/música/estação no acervo",
                 jingle=uid_jingle in mids, musica=uid_musica in mids,
                 estacao=estacao)
        return False
    valores = ", ".join(
        f"({estacao}, {mids[uid]}, '{ts}', 0, '{PEDIDO_IP}')"
        for uid, ts in ((uid_jingle, ts_jingle), (uid_musica, ts_musica))
    )
    ok, _ = rodar(
        "INSERT INTO station_requests"
        " (station_id, track_id, timestamp, skip_delay, ip)"
        f" VALUES {valores};"
    )
    return ok


def pedir_no_ar(
    artista: str,
    titulo: str,
    *,
    api: Optional[str] = None,
    chave: Optional[str] = None,
    jingle_recente: Optional[Callable[[], bool]] = None,
    inserir: Optional[Callable[[str, str, str, str], bool]] = None,
) -> dict[str, Any]:
    """Coloca a música na fila REAL da estação (o pedido toca de verdade).

    Enfileira o JINGLE ("anuncio musica") e a MÚSICA pedida como duas
    linhas em station_requests com timestamps de 31 min atrás: os dois
    nascem jogáveis e a fila monta [jingle, música] adjacente — a
    locutora fala o recado na vinheta imediatamente anterior ao pedido.
    A ordem não pode vir do sorteio da API (15–30 min POR música, quase
    metade das vezes invertida): por isso o INSERT direto, o mesmo do
    SubmitAction do AzuraCast, só com o atraso já consumido.

    {"ok": true, "fila": "azuracast"} quando as linhas entram;
    {"ok": false, "motivo": "sem_chave"|"fila_fora"|"nao_pedivel"|"recusado"}.

    `jingle_recente` (10 min de histórico — trava o jingle novo) e
    `inserir` (o docker exec no mariadb) são injetáveis nos testes, como
    `enviar` é em lancar_pedido_na_fila: rede e container ficam fora do gate.
    """
    if not (chave if chave is not None else AZURA_KEY):
        return {"ok": False, "motivo": "sem_chave"}
    status, itens = _azuracast(
        f"/api/station/{AZURA_STATION}/requests", api=api, chave=chave
    )
    if status != 200 or not isinstance(itens, list):
        return {"ok": False, "motivo": "fila_fora"}
    alvo = None
    for item in itens:
        song = (item or {}).get("song") or {}
        if (_mesma_musica(str(song.get("artist") or ""), artista)
                and _mesma_musica(str(song.get("title") or ""), titulo)):
            alvo = item
            break
    if alvo is None:                      # cai no texto "Artista - Título"
        for item in itens:
            song = (item or {}).get("song") or {}
            texto = _sem_acento(str(song.get("text") or ""))
            if (artista and titulo and _sem_acento(artista) in texto
                    and _sem_acento(titulo) in texto):
                alvo = item
                break
    if alvo is None:
        return {"ok": False, "motivo": "nao_pedivel"}
    request_url = str(alvo.get("request_url") or "")
    if not request_url.startswith("/api/"):     # nunca URL de fora
        return {"ok": False, "motivo": "nao_pedivel"}
    uid_musica = request_url.rsplit("/", 1)[-1]
    if not _uid_valido(uid_musica):
        return {"ok": False, "motivo": "nao_pedivel"}
    if jingle_recente is None:
        jingle_recente = _jingle_tocou_recentemente
    try:
        travado = bool(jingle_recente())
    except Exception as exc:              # histórico é pista, não portão
        log.warn("histórico do jingle indisponível", error=type(exc).__name__)
        travado = False
    instante = datetime.now()
    ts_jingle = (instante - timedelta(
        minutes=ATRASO_SEGURO_MIN)).strftime("%Y-%m-%d %H:%M:%S")
    # Jingle travado pelo histórico → música com timestamp NORMAL: ela só
    # fica jogável (15 min) DEPOIS de o jingle destravar (10 min), e a
    # ordem J→P se mantém; fora disso, os dois juntos e adjacentes.
    ts_musica = (instante.strftime("%Y-%m-%d %H:%M:%S")
                 if travado else ts_jingle)
    if inserir is None:
        inserir = _inserir_requests
    try:
        ok = inserir(JINGLE_ANUNCIO, uid_musica, ts_jingle, ts_musica)
    except Exception as exc:
        log.warn("enfileirar pedido falhou", error=type(exc).__name__)
        ok = False
    if not ok:
        return {"ok": False, "motivo": "recusado"}
    return {"ok": True, "fila": "azuracast"}


def marcar_status(
    pedido_id: int, status: str, *, banco: Optional[Path] = None
) -> bool:
    """Muda o estado de um pedido (pendente → na_fila → tocada)."""
    banco = banco or BANCO_PEDIDOS
    if not banco.exists():
        return False
    try:
        conn = _conexao(banco)
    except sqlite3.Error:
        return False
    try:
        conn.execute("UPDATE pedidos SET status = ? WHERE id = ?",
                     (str(status), int(pedido_id)))
        conn.commit()
        return True
    except (sqlite3.Error, ValueError):
        return False
    finally:
        conn.close()


def confirmar_recados_no_ar(*, banco: Optional[Path] = None) -> int:
    """Marca como 'tocada' todo recado em 'no_ar' — o jingle começou a tocar.

    O webhook chama isso no instante em que "anuncio musica" entra no ar:
    o arquivo que o liquidsoap está lendo É a locução com o recado, então
    o recado foi ao ar e não pode se repetir no ciclo seguinte.
    Devolve quantos recados confirmados.
    """
    banco = banco or BANCO_PEDIDOS
    if not banco.exists():
        return 0
    try:
        conn = _conexao(banco)
    except sqlite3.Error:
        return 0
    try:
        cursor = conn.execute(
            "UPDATE pedidos SET status = 'tocada' WHERE status = 'no_ar'"
        )
        conn.commit()
        return int(cursor.rowcount or 0)
    except (sqlite3.Error, ValueError):
        return 0
    finally:
        conn.close()


def anuncio_de_pedido(
    artista: str, titulo: str, *, banco: Optional[Path] = None
) -> str:
    """Fala da locutora para o pedido que está entrando no ar.

    Duas entradas — a ordem importa, é o par que montar_locucao faz:
      1. `titulo` é o jingle "anuncio musica" (a PRÓXIMA faixa): é a
         janela exata do recado — pega o pedido mais antigo em 'na_fila'
         (ou 'no_ar', de ciclo anterior), marca 'no_ar' e devolve a fala;
      2. `titulo` é uma música com pedido (a ATUAL, em queda): o recado
         não foi ao ar a tempo — marca 'tocada' com WARN e devolve ""
         (o aviso atrasado saía DEPOIS da música: era o bug do 04/11).
    Sem pedido: "".
    """
    if not titulo:
        return ""
    banco = banco or BANCO_PEDIDOS
    if not banco.exists():
        return ""
    try:
        conn = _conexao(banco)
    except sqlite3.Error:
        return ""
    try:
        if _mesma_musica(titulo, ANUNCIO_TITULO):
            linha = conn.execute(
                "SELECT id, usuario, recado FROM pedidos"
                " WHERE status IN ('na_fila', 'no_ar')"
                " ORDER BY id LIMIT 1"
            ).fetchone()
            if linha is None:
                return ""
            pedido_id, usuario, recado = linha
            conn.execute(
                "UPDATE pedidos SET status = 'no_ar' WHERE id = ?",
                (int(pedido_id),),
            )
            conn.commit()
            recado = str(recado or "").strip()
            if recado:
                return f"Pedido de {usuario}: {recado}"
            return f"Pedido do ouvinte {usuario}."
        linhas = conn.execute(
            "SELECT id, usuario, recado, artista, titulo, status FROM pedidos"
            " WHERE status IN ('pendente', 'na_fila', 'no_ar') ORDER BY id"
        ).fetchall()
        for pedido_id, usuario, recado, ped_artista, ped_titulo, status in linhas:
            if not _mesma_musica(str(ped_titulo or ""), titulo):
                continue
            if artista and ped_artista and not _mesma_musica(
                    str(ped_artista), artista):
                continue
            conn.execute(
                "UPDATE pedidos SET status = 'tocada' WHERE id = ?",
                (int(pedido_id),),
            )
            conn.commit()
            if status in ("na_fila", "no_ar"):
                log.warn("recado não foi ao ar antes da música",
                         pedido=int(pedido_id), status=str(status))
            return ""
    except sqlite3.Error:
        return ""
    finally:
        conn.close()
    return ""


def lancar_pedido_na_fila(
    pedido: dict[str, Any],
    *,
    enviar: Optional[Callable[[str, str], dict[str, Any]]] = None,
    banco: Optional[Path] = None,
) -> dict[str, Any]:
    """Empurra o pedido para a fila REAL da estação (ordem do dono 04/11).

    "Ligue o pedido de música para tocar de verdade na rádio, com fila":
    o AzuraCast é quem enfileira — o pedido entra como JINGle + MÚSICA
    (pedir_no_ar), com a ordem já garantida [jingle, música] para o
    recado cair na vinheta imediatamente anterior. Aqui só submete e
    atualiza o status.

    Devolve o MESMO pedido com:
      fila="azuracast"         → aceito, status vira 'na_fila';
      fila=None, motivo=...    → continua 'pendente' (sem chave, fora do
                                  acervo, recusado ou AzuraCast fora) — o
                                  aviso do Telegram já saiu e nada some.

    `enviar` é injetável nos testes (mesma régua das fontes de letra) e
    `banco` aponta o SQLite dos pedidos (padrão: o real, data/...).
    """
    if not pedido or pedido.get("status") != "pendente":
        return pedido
    enviar = enviar or pedir_no_ar
    try:
        resultado = enviar(str(pedido.get("artista") or ""),
                           str(pedido.get("titulo") or ""))
    except Exception as exc:                  # fila é caminho, não destino
        log.warn("submissão de pedido falhou", error=type(exc).__name__)
        resultado = {"ok": False, "motivo": "recusado"}
    if isinstance(resultado, dict) and resultado.get("ok"):
        if marcar_status(int(pedido.get("id") or 0), "na_fila",
                         banco=banco):
            pedido = dict(pedido, status="na_fila")
        return dict(pedido, fila="azuracast")
    motivo = str((resultado or {}).get("motivo") or "recusado")
    return dict(pedido, fila=None, motivo=motivo)
