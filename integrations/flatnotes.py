"""
OMEGA DRAKON • INTEGRATIONS
Tecnologia que respira.
Módulo: integrations/flatnotes.py
Descrição: Caderno de notas do dono — cliente HTTP do FlatNotes
           self-hosted (container `od-flatnotes`, 5ª ferramenta
           interligada; pedido do dono em 2026-10-18: "ligar" — 1ª da
           análise de FlatNotes/File Browser/Calibre).

           - **FlatNotes 5.5.5** (dullage/flatnotes, MIT) em
             `127.0.0.1:8200` → `:8080` do container; `auth=none`
             (só Tailscale — mesmo molde do Stirling/CyberChef; nunca
             no Funnel público). Sem login = sem segredo no `.env`.
           - **Sem banco de dados**: cada nota é um arquivo `.md` numa
             pasta plana (`/home/alex/omegadrakon-tools/flatnotes`,
             bind-mount) — nada preso em cárcere de dados, e a pasta
             já **entra nos snapshots das 2 HDs** (fonte
             `omegadrakon-tools` desde a v1.39.3).
           - Contratos vivos verificados com chamada REAL antes de
             codificar (18/10 — `openapi.json` do próprio container +
             round-trip completo: criar → repetir → buscar → ler →
             apagar minha nota de teste):
             · `POST /api/notes` `{title, content}` → 200
               `Note{title, content, lastModified}` (unix float)
             · `POST` com título repetido → **409**
               ("Cannot create note. A note with the same title
               already exists.") — recusado honesto; atualização só
               com flag explícita via `PATCH /api/notes/{title}`
               `{newContent}`
             · `GET /api/search?term=X[&limit=N]` → 200
               `[{title, lastModified, score, titleHighlights,
               contentHighlights, tagMatches}]` — destaques vêm como
               **HTML** (`<b class="match term0">`); `term=*` lista
               tudo (serve de contagem); `[]` é resposta honesta
             · `GET /api/notes/{title}` → 200 `Note` | 404
               ("The specified note cannot be found.")
             · `GET /api/config` → `{authType, quickAccess*}`;
               `GET /health` → texto "OK"
           - **NENHUMA action apaga**: o `DELETE` da API fica de fora
             do catálogo (régua do dono — nada apagado por acidente).
           - Erros honestos e tipados (`flatnotes_indisponivel`,
             `flatnotes_timeout`, `flatnotes_falhou`,
             `flatnotes_parametro_invalido`, `flatnotes_ja_existe`,
             `flatnotes_nao_encontrada`, `flatnotes_resposta_invalida`).
           - **Lazy por desenho**: `client_padrao()` é fábrica
             cacheada e a URL tem default local — ferramenta fora do
             ar degrada a ação, nunca o boot do od-core.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - docker/tools-compose.yaml (dullage/flatnotes, tag 5.5.5 — o
    compose é a fonte exata, porta
    127.0.0.1:8200 → 8080, bind omegadrakon-tools/flatnotes:/data,
    FLATNOTES_AUTH_TYPE=none)
  - openapi.json vivo + round-trip real (18/10) — contrato de
    POST/409/PATCH/search/GET completo antes de codificar
  - tools/actions/actions.py (actions flatnotes_status/anota/busca)

Decisões registradas (ver CHANGELOG):
  - `sobrescrever=False` por padrão: 409 vira `flatnotes_ja_existe`
    honesto; sobrescrever é flag explícita que vai pelo PATCH e vem
    declarado na resposta (`sobrescrito=True`)
  - Destaques HTML → texto limpo (regex + `html.unescape`): resposta
    de chat não pode carregar marcador HTML alheio (o `<b>` do
    flatnotes não é o `<b>` do Telegram) — zero dependência nova
  - Título com `/` é recusado na camada da API (o título vira
    caminho de arquivo `.md` no lado dele; validar antes de mandar é
    mais honesto que descobrir o 404 depois)
  - Busca vazia (`[]`) NÃO é erro: caderno sem anotações é estado
    normal, não falha

Código associado: integrations/flatnotes.py (este arquivo)
"""

from __future__ import annotations

import html
import json
import os
import pathlib
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

from core.logger import get_logger

log = get_logger("omega.integrations.flatnotes")

URL_PADRAO = "http://127.0.0.1:8200"
TIMEOUT_PADRAO_S = 20.0
LIMITE_MAXIMO_BYTES = 4 * 1024 * 1024  # nota/handler gigante não estoura memória
LIMITE_BUSCA_PADRAO = 10
LIMITE_BUSCA_MAXIMO = 50

_ENV_PATH = pathlib.Path(__file__).resolve().parent.parent / ".env"


def _env(name: str, default: str = "") -> str:
    """Valor de configuração: os.environ primeiro, `.env` depois.

    (Mesmo padrão de `integrations/vault.py`/`kiwix.py` — sem importar
    o launcher para não amarrar este módulo ao boot.)
    """
    valor = os.environ.get(name)
    if valor:
        return valor
    try:
        if _ENV_PATH.exists():
            for linha in _ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
                linha = linha.strip()
                if not linha or linha.startswith("#") or "=" not in linha:
                    continue
                chave, _, valor = linha.partition("=")
                if chave.strip() == name:
                    return valor.strip().strip('"').strip("'")
    except OSError:
        pass
    return default


# ---------------------------------------------------------------------------
# Erros honestos e tipados
# ---------------------------------------------------------------------------

class FlatNotesError(Exception):
    """Erro tipado do FlatNotes: código estável + mensagem honesta."""

    def __init__(self, codigo: str, mensagem: str) -> None:
        super().__init__(mensagem)
        self.codigo = codigo
        self.mensagem = mensagem


def _erro_rede(exc: BaseException, url: str, timeout_s: float) -> FlatNotesError:
    """Falha de rede/tempo → erro tipado honesto."""
    causa = getattr(exc, "reason", exc)
    if isinstance(exc, (socket.timeout, TimeoutError)) or isinstance(
        causa, (socket.timeout, TimeoutError)
    ):
        return FlatNotesError(
            "flatnotes_timeout",
            f"FlatNotes não respondeu em {timeout_s:.0f}s ({url}).",
        )
    return FlatNotesError(
        "flatnotes_indisponivel",
        f"FlatNotes inacessível em {url}: {causa}",
    )


def _transporte(
    url: str,
    *,
    timeout_s: float,
    metodo: str = "GET",
    corpo: Optional[dict[str, Any]] = None,
    cabecalhos: Optional[dict[str, str]] = None,
) -> tuple[int, dict[str, str], bytes]:
    """urllib real → (status, headers, corpo). HTTPError É uma resposta."""
    dados = None
    cabecalhos_envio: dict[str, str] = dict(cabecalhos or {})
    if corpo is not None:
        dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        cabecalhos_envio["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cabecalhos_envio)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return int(resp.status), dict(resp.headers), resp.read(LIMITE_MAXIMO_BYTES)
    except urllib.error.HTTPError as exc:
        try:
            corpo_lido = exc.read()
        except Exception:  # pragma: no cover - corpo ilegível é raro
            corpo_lido = b""
        cabecalhos: dict[str, str] = {}
        try:
            cabecalhos = dict(exc.headers) if exc.headers else {}
        except Exception:  # pragma: no cover
            pass
        return int(exc.code), cabecalhos, corpo_lido
    except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as exc:
        raise _erro_rede(exc, url, timeout_s) from None


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------

def _limpar_destaque(bruto: Optional[str]) -> str:
    """HTML do flatnotes (`<b class="match term0">`) → texto limpo.

    O marcador alheio não pode vazar para resposta de chat (o `<b>`
    de lá não é o `<b>` do Telegram). `None` → string vazia.
    """
    if not bruto:
        return ""
    texto = re.sub(r"<[^>]+>", "", bruto)
    return html.unescape(texto).strip()


def _detalhe_erro(corpo: bytes) -> str:
    """Extrai `detail` (FastAPI) do corpo de erro para a mensagem."""
    try:
        dados = json.loads(corpo.decode("utf-8", "replace"))
    except (ValueError, AttributeError):
        return ""
    if isinstance(dados, dict):
        detalhe = dados.get("detail")
        if isinstance(detalhe, str):
            return detalhe.strip()
    return ""


def _parse_nota(corpo: bytes, onde: str) -> dict[str, Any]:
    """Corpo `Note` → dicionário; corpo malformado é erro honesto."""
    try:
        dados = json.loads(corpo.decode("utf-8", "replace"))
    except ValueError:
        raise FlatNotesError(
            "flatnotes_resposta_invalida",
            f"{onde}: corpo não é JSON válido.",
        ) from None
    if not isinstance(dados, dict) or "title" not in dados:
        raise FlatNotesError(
            "flatnotes_resposta_invalida",
            f"{onde}: JSON sem o campo obrigatório 'title'.",
        )
    return dados


class FlatNotesClient:
    """Cliente do FlatNotes (transporte injetável p/ testes)."""

    def __init__(
        self,
        base_url: str = URL_PADRAO,
        timeout_s: float = TIMEOUT_PADRAO_S,
        transporte: Optional[Callable[..., tuple[int, dict[str, str], bytes]]] = None,
        *,
        usuario: str = "",
        senha: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._transporte = transporte or _transporte
        # 21/10: caderno ganhou senha (FLATNOTES_AUTH_TYPE=password).
        # Vazio = anônimo (contrato antigo intacto); com credencial o
        # cliente faz login sozinho quando a API nega (401) e renova
        # token expirado sem virar erro para o dono.
        self._usuario = usuario
        self._senha = senha
        self._token: Optional[str] = None

    # -- transporte --------------------------------------------------------

    def _chamada(
        self,
        metodo: str,
        caminho: str,
        *,
        corpo: Optional[dict[str, Any]] = None,
        timeout_s: Optional[float] = None,
        _renovou: bool = False,
    ) -> tuple[int, bytes]:
        url = f"{self.base_url}{caminho}"
        tempo = timeout_s or self.timeout_s
        # Authorization SÓ quando há token — o caminho anônimo continua
        # byte a byte o mesmo (contrato intacto p/ testes e 3ºs).
        extra: dict[str, str] = {}
        if self._token:
            extra["Authorization"] = f"Bearer {self._token}"
        try:
            status, _cabecalhos, corpo_bytes = self._transporte(
                url,
                timeout_s=tempo,
                metodo=metodo,
                corpo=corpo,
                **({"cabecalhos": extra} if extra else {}),
            )
        except FlatNotesError:
            raise
        except (
            urllib.error.URLError,
            socket.timeout,
            ConnectionError,
            OSError,
        ) as exc:
            # Transporte injetado (testes/terceiros) sem mapeamento próprio.
            raise _erro_rede(exc, url, tempo) from None
        if status == 401 and not _renovou and self._usuario and self._senha:
            # Caderno com senha (21/10): renova a sessão UMA vez e tenta
            # de novo — token expirado não vira erro para o dono.
            self._login(timeout_s=tempo)
            return self._chamada(
                metodo, caminho, corpo=corpo, timeout_s=timeout_s, _renovou=True
            )
        return status, corpo_bytes

    def _login(self, *, timeout_s: Optional[float] = None) -> None:
        """POST /api/token (JSON) → access_token (contrato apurado ao vivo
        em 21/10 via OpenAPI: form-data dá 422; JSON devolve bearer)."""
        tempo = timeout_s or self.timeout_s
        url = f"{self.base_url}/api/token"
        try:
            status, _cabecalhos, corpo_bytes = self._transporte(
                url,
                timeout_s=tempo,
                metodo="POST",
                corpo={"username": self._usuario, "password": self._senha},
            )
        except FlatNotesError:
            raise
        except (
            urllib.error.URLError,
            socket.timeout,
            ConnectionError,
            OSError,
        ) as exc:
            raise _erro_rede(exc, url, tempo) from None
        if not (200 <= status < 300):
            # Mensagem honesta — e JAMAIS ecoa a senha.
            raise FlatNotesError(
                "flatnotes_login_falhou",
                "Login do Caderno recusado (HTTP "
                f"{status}) — confira FLATNOTES_USERNAME/FLATNOTES_PASSWORD "
                "no .env.",
            )
        try:
            token = json.loads(corpo_bytes.decode("utf-8"))["access_token"]
        except (json.JSONDecodeError, KeyError, UnicodeDecodeError):
            raise FlatNotesError(
                "flatnotes_login_falhou",
                "Login do Caderno: resposta sem access_token (JSON inesperado).",
            ) from None
        self._token = str(token)

    def _espera_200(self, status: int, corpo: bytes, onde: str) -> None:
        if not (200 <= status < 300):
            detalhe = _detalhe_erro(corpo)
            raise FlatNotesError(
                "flatnotes_falhou",
                f"{onde}: HTTP {status}" + (f" — {detalhe}" if detalhe else "."),
            )

    # -- operações ---------------------------------------------------------

    def status(self, *, timeout_s: float = 15.0) -> dict[str, Any]:
        """Vida do caderno: auth, nº de notas e a última editada."""
        status, corpo = self._chamada("GET", "/health", timeout_s=timeout_s)
        if status != 200:
            raise FlatNotesError(
                "flatnotes_falhou", f"/health: HTTP {status}."
            )

        status, corpo = self._chamada("GET", "/api/config", timeout_s=timeout_s)
        self._espera_200(status, corpo, "/api/config")
        try:
            config = json.loads(corpo.decode("utf-8", "replace"))
        except ValueError:
            raise FlatNotesError(
                "flatnotes_resposta_invalida", "/api/config: corpo não é JSON."
            ) from None
        if not isinstance(config, dict):
            raise FlatNotesError(
                "flatnotes_resposta_invalida", "/api/config: JSON não é objeto."
            )

        # term=* lista tudo (contrato vivo) — serve de contagem honesta.
        status, corpo = self._chamada(
            "GET", "/api/search?term=*", timeout_s=timeout_s
        )
        self._espera_200(status, corpo, "/api/search")
        try:
            notas = json.loads(corpo.decode("utf-8", "replace"))
        except ValueError:
            raise FlatNotesError(
                "flatnotes_resposta_invalida", "/api/search: corpo não é JSON."
            ) from None
        if not isinstance(notas, list):
            raise FlatNotesError(
                "flatnotes_resposta_invalida", "/api/search: JSON não é lista."
            )

        ultima: Optional[dict[str, Any]] = None
        if notas:
            maior = max(notas, key=lambda n: float(n.get("lastModified") or 0))
            ultima = {
                "titulo": str(maior.get("title", "")),
                "modificado_em": float(maior.get("lastModified") or 0),
            }
        return {
            "acessivel": True,
            "auth_type": str(config.get("authType", "")),
            "notas": len(notas),
            "ultima_modificada": ultima,
        }

    def anota(
        self,
        titulo: str,
        conteudo: str = "",
        sobrescrever: bool = False,
    ) -> dict[str, Any]:
        """Cria UMA nota (ou atualiza com `sobrescrever=True`, declarado)."""
        titulo = (titulo or "").strip()
        if not titulo:
            raise FlatNotesError(
                "flatnotes_parametro_invalido", "titulo não pode ser vazio."
            )
        if "/" in titulo:
            raise FlatNotesError(
                "flatnotes_parametro_invalido",
                "titulo não pode conter '/' (vira caminho de arquivo .md).",
            )

        status, corpo = self._chamada(
            "POST",
            "/api/notes",
            corpo={"title": titulo, "content": conteudo or ""},
        )
        if status == 409:
            if not sobrescrever:
                raise FlatNotesError(
                    "flatnotes_ja_existe",
                    f"Nota '{titulo}' já existe — use sobrescrever=true "
                    "para atualizar o conteúdo (o original só sai com "
                    "pedido explícito).",
                )
            # Atualização explícita: PATCH com o novo conteúdo.
            caminho = "/api/notes/" + urllib.parse.quote(titulo, safe="")
            status, corpo = self._chamada(
                "PATCH", caminho, corpo={"newContent": conteudo or ""}
            )
            if status == 404:
                raise FlatNotesError(
                    "flatnotes_nao_encontrada",
                    f"Nota '{titulo}' sumiu entre o 409 e a atualização "
                    "(estado inesperado do caderno).",
                )
            self._espera_200(status, corpo, "PATCH /api/notes")
            dados = _parse_nota(corpo, "PATCH /api/notes")
            return {
                "titulo": str(dados.get("title", titulo)),
                "conteudo": dados.get("content") or "",
                "modificado_em": float(dados.get("lastModified") or 0),
                "sobrescrito": True,
            }

        self._espera_200(status, corpo, "POST /api/notes")
        dados = _parse_nota(corpo, "POST /api/notes")
        return {
            "titulo": str(dados.get("title", titulo)),
            "conteudo": dados.get("content") or "",
            "modificado_em": float(dados.get("lastModified") or 0),
            "sobrescrito": False,
        }

    def buscar(self, termo: str, limite: int = LIMITE_BUSCA_PADRAO) -> dict[str, Any]:
        """Busca texto livre nas notas → trechos limpos (sem HTML)."""
        termo = (termo or "").strip()
        if not termo:
            raise FlatNotesError(
                "flatnotes_parametro_invalido", "termo não pode ser vazio."
            )
        # None → default; explícito passa pela faixa (0 vira 1, estouro vira 50).
        numero = LIMITE_BUSCA_PADRAO if limite is None else int(limite)
        limite = max(1, min(numero, LIMITE_BUSCA_MAXIMO))
        consulta = urllib.parse.urlencode({"term": termo, "limit": limite})
        status, corpo = self._chamada("GET", f"/api/search?{consulta}", timeout_s=30.0)
        self._espera_200(status, corpo, "/api/search")
        try:
            itens = json.loads(corpo.decode("utf-8", "replace"))
        except ValueError:
            raise FlatNotesError(
                "flatnotes_resposta_invalida", "/api/search: corpo não é JSON."
            ) from None
        if not isinstance(itens, list):
            raise FlatNotesError(
                "flatnotes_resposta_invalida", "/api/search: JSON não é lista."
            )

        resultados: list[dict[str, Any]] = []
        for item in itens:
            if not isinstance(item, dict):
                continue
            resultados.append({
                "titulo": str(item.get("title", "")),
                "modificado_em": float(item.get("lastModified") or 0),
                "pontuacao": (
                    float(item["score"]) if item.get("score") is not None else None
                ),
                "trecho": _limpar_destaque(item.get("contentHighlights")),
                "trecho_titulo": _limpar_destaque(item.get("titleHighlights")),
            })
        return {"termo": termo, "total": len(resultados), "resultados": resultados}


# ---------------------------------------------------------------------------
# Fábrica cacheada (lazy)
# ---------------------------------------------------------------------------

_CLIENTE: Optional[FlatNotesClient] = None


def client_padrao() -> FlatNotesClient:
    """Cliente do FlatNotes (URL em OD_FLATNOTES_URL ou default local)."""
    global _CLIENTE
    if _CLIENTE is None:
        url = _env("OD_FLATNOTES_URL", URL_PADRAO)
        # 21/10: caderno com senha — credenciais do .env entram aqui e o
        # cliente loga sozinho no primeiro 401 (FLATNOTES_USERNAME/PASSWORD).
        _CLIENTE = FlatNotesClient(
            url,
            usuario=_env("FLATNOTES_USERNAME", ""),
            senha=_env("FLATNOTES_PASSWORD", ""),
        )
        log.info("FlatNotes configurado", url=url)
    return _CLIENTE


def resetar_cliente() -> None:
    """Esquece a instância cacheada (testes / troca de configuração)."""
    global _CLIENTE
    _CLIENTE = None
