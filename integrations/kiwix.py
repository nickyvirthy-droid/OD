"""
OMEGA DRAKON • INTEGRATIONS
Tecnologia que respira.
Módulo: integrations/kiwix.py
Descrição: Acervo offline do sistema — cliente HTTP do Kiwix Serve
           self-hosted (container `od-kiwix`, 3ª das 3 interligações de
           ferramenta aprovadas pelo dono em 2026-10-17: Vaultwarden →
           Stirling → **Kiwix**).

           - **kiwix-serve 3.8.1** servindo a Wikipédia en_all_mini
             (12,5 GB, ~18,1 M de artigos) em `127.0.0.1:8090` → `:8080`
             do container; sem login e sem nada exposto à internet.
           - Contratos vivos verificados com chamadas REAIS antes de
             codificar (17/10) — a API do kiwix-serve é HTML/XML puro
             (sem JSON):
               · `GET /catalog/v2/entries` → feed Atom (OPDS) com um
                 `<entry>` por ZIM: id, title, summary, language, name,
                 articleCount, mediaCount
               · `GET /search?pattern=X` → HTML com `<div class="results">`
                 e, por hit: `<a href="/content/<zim>/<caminho>">titulo</a>`,
                 `<cite>` (trecho com <b>) e `<div class="informations">`
                 ("N words")
               · `GET /content/<zim>/<caminho>` → 200 com o HTML do
                 artigo (`<title>`, `<p>`) ou 404 quando não existe
             (Achados: `/A/<titulo>` redireciona para `/content/...`;
             `/random` e `/suggestions` não servem JSON nesta versão.)
           - **Só leitura**: o ZIM é montado `:ro` — nada aqui escreve
             no acervo (mesma régua do dono: sem tela = sem ação).
           - Texto do artigo extraído com parser stdlib (`html.parser`),
             com limite honesto de caracteres (`truncado=True` quando
             cortado) — **zero dependência nova**.
           - Erros honestos e tipados (`kiwix_indisponivel`,
             `kiwix_timeout`, `kiwix_falhou`, `kiwix_parametro_invalido`,
             `kiwix_artigo_nao_encontrado`, `kiwix_resposta_invalida`).
           - **Lazy por desenho**: `client_padrao()` é fábrica cacheada e
             a URL tem default local — ferramenta fora do ar degrada a
             ação, nunca o boot do od-core.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - docker/tools-compose.yaml (ghcr.io/kiwix/kiwix-serve:3.8.1, porta
    127.0.0.1:8090 → 8080, bind /data:ro com wikipedia_en_all_mini.zim)
  - /catalog/v2/entries + /search + /content (contratos vivos, 17/10)
  - tools/actions/actions.py (actions kiwix_status/busca/leitura)

Decisões registradas (ver CHANGELOG):
  - HTML/XML parseado com html.parser + ElementTree do stdlib em vez de
    depender de endpoint JSON: o kiwix-serve 3.8 não expõe JSON nesta
    rota (apurado ao vivo — /suggestions devolveu vazio, /search com
    Accept json devolveu HTML)
  - Busca vazia NÃO é erro: resultado [] é resposta honesta (o artigo
    pode simplesmente não estar no acervo)
  - `ler()` devolve texto limpo + truncamento declarado — o bloco vira
    referência do assistente; mentir sobre tamanho seria pior que cortar

Código associado: integrations/kiwix.py (este arquivo)
"""

from __future__ import annotations

import html
import os
import pathlib
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from typing import Any, Callable, Optional

from core.logger import get_logger

log = get_logger("omega.integrations.kiwix")

URL_PADRAO = "http://127.0.0.1:8090"
TIMEOUT_PADRAO_S = 20.0
PREFIXO_CONTEUDO = "/content/"
LIMITE_PADRAO_TEXTO = 8000
LIMITE_MAXIMO_BYTES = 4 * 1024 * 1024  # artigos gigantes não estouram memória
ATOM = "{http://www.w3.org/2005/Atom}"

_ENV_PATH = pathlib.Path(__file__).resolve().parent.parent / ".env"


def _env(name: str, default: str = "") -> str:
    """Valor de configuração: os.environ primeiro, `.env` depois.

    (Mesmo padrão de `integrations/vault.py`/`stirling.py` — sem importar
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

class KiwixError(Exception):
    """Erro tipado do Kiwix: código estável + mensagem honesta."""

    def __init__(self, codigo: str, mensagem: str) -> None:
        super().__init__(mensagem)
        self.codigo = codigo
        self.mensagem = mensagem


def _erro_rede(exc: BaseException, url: str, timeout_s: float) -> KiwixError:
    """Falha de rede/tempo → erro tipado honesto."""
    causa = getattr(exc, "reason", exc)
    if isinstance(exc, (socket.timeout, TimeoutError)) or isinstance(
        causa, (socket.timeout, TimeoutError)
    ):
        return KiwixError(
            "kiwix_timeout",
            f"Kiwix não respondeu em {timeout_s:.0f}s ({url}).",
        )
    return KiwixError(
        "kiwix_indisponivel",
        f"Kiwix inacessível em {url}: {causa}",
    )


def _transporte(
    url: str,
    *,
    timeout_s: float,
) -> tuple[int, dict[str, str], bytes]:
    """urllib real → (status, headers, corpo). HTTPError É uma resposta."""
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return int(resp.status), dict(resp.headers), resp.read(LIMITE_MAXIMO_BYTES)
    except urllib.error.HTTPError as exc:
        try:
            corpo = exc.read()
        except Exception:  # pragma: no cover - corpo ilegível é raro
            corpo = b""
        cabecalhos: dict[str, str] = {}
        try:
            cabecalhos = dict(exc.headers) if exc.headers else {}
        except Exception:  # pragma: no cover
            pass
        return int(exc.code), cabecalhos, corpo
    except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as exc:
        raise _erro_rede(exc, url, timeout_s) from None


# ---------------------------------------------------------------------------
# Parsers stdlib (HTML da busca, Atom do catálogo, HTML do artigo)
# ---------------------------------------------------------------------------

def _limpar_texto(bruto: str) -> str:
    """Colapsa espaço e remove linhas vazias de um texto extraído."""
    linhas = []
    for linha in bruto.splitlines():
        linha = re.sub(r"[ \t ]+", " ", linha).strip()
        if linha:
            linhas.append(linha)
    return "\n".join(linhas)


class _ParserBusca(HTMLParser):
    """Extrai os hits de /search (título + caminho + trecho + palavras)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.itens: list[dict[str, Any]] = []
        self._atual: Optional[dict[str, Any]] = None
        self._em_a = False
        self._em_cite = False
        self._em_info = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        d = dict(attrs)
        if tag == "a":
            href = d.get("href") or ""
            if href.startswith(PREFIXO_CONTEUDO):
                self._atual = {
                    "titulo": "",
                    "caminho": href[len(PREFIXO_CONTEUDO):],
                    "trecho": "",
                    "palavras": 0,
                }
                self.itens.append(self._atual)
                self._em_a = True
        elif tag == "cite" and self._atual is not None:
            self._em_cite = True
        elif tag == "div" and d.get("class") == "informations" and self._atual is not None:
            self._em_info = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._em_a = False
        elif tag == "cite":
            self._em_cite = False
        elif tag == "div":
            self._em_info = False

    def handle_data(self, data: str) -> None:
        if self._atual is None:
            return
        if self._em_a:
            self._atual["titulo"] += data
        elif self._em_cite:
            self._atual["trecho"] += data
        elif self._em_info:
            m = re.search(r"(\d+)", data)
            if m:
                self._atual["palavras"] = int(m.group(1))


class _ParserArtigo(HTMLParser):
    """Extrai título e parágrafos do /content (bloco de referência)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.titulo = ""
        self.blocos: list[str] = []
        self._em_titulo = False
        self._bloco_atual: Optional[str] = None  # None = fora de p/h

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag == "title":
            self._em_titulo = True
        elif tag in ("p", "h2", "h3"):
            self._bloco_atual = tag
            self.blocos.append("")
        elif tag in ("script", "style"):
            self._bloco_atual = None

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._em_titulo = False
        elif tag in ("p", "h2", "h3"):
            self._bloco_atual = None

    def handle_data(self, data: str) -> None:
        if self._em_titulo:
            self.titulo += data
        elif self._bloco_atual is not None and self.blocos:
            self.blocos[-1] += data


def _parse_busca(corpo: bytes) -> list[dict[str, Any]]:
    """HTML de /search → lista de hits (título limpo, trecho cortado)."""
    parser = _ParserBusca()
    try:
        parser.feed(corpo.decode("utf-8", errors="replace"))
    except Exception as exc:  # pragma: no cover - HTMLParser é tolerante
        raise KiwixError(
            "kiwix_resposta_invalida",
            f"resposta da busca ilegível ({type(exc).__name__}).",
        ) from None
    itens: list[dict[str, Any]] = []
    for bruto in parser.itens:
        titulo = re.sub(r"\s+", " ", html.unescape(bruto["titulo"])).strip()
        caminho = str(bruto["caminho"]).strip()
        if not titulo or not caminho:
            continue
        itens.append({
            "titulo": titulo,
            "caminho": caminho,
            "trecho": re.sub(r"\s+", " ", html.unescape(bruto["trecho"]))[:300],
            "palavras": int(bruto["palavras"] or 0),
        })
    return itens


def _parse_catalogo(corpo: bytes) -> list[dict[str, Any]]:
    """Feed Atom de /catalog/v2/entries → acervos carregados."""
    try:
        raiz = ET.fromstring(corpo.decode("utf-8", errors="replace"))
    except ET.ParseError as exc:
        raise KiwixError(
            "kiwix_resposta_invalida",
            f"catálogo do Kiwix ilegível (XML inválido: {exc}).",
        ) from None
    acervos: list[dict[str, Any]] = []
    for entry in raiz.findall(f"{ATOM}entry"):
        def texto(chave: str) -> str:
            no = entry.find(f"{ATOM}{chave}")
            return (no.text or "").strip() if no is not None else ""

        def inteiro(chave: str) -> int:
            try:
                return int(texto(chave) or 0)
            except ValueError:
                return 0

        nome = texto("name")
        if not nome:
            continue  # entry sem nome não é acervo servível
        acervos.append({
            "id": texto("id").removeprefix("urn:uuid:"),
            "titulo": texto("title"),
            "resumo": texto("summary"),
            "idioma": texto("language"),
            "nome": nome,
            "artigos": inteiro("articleCount"),
            "midias": inteiro("mediaCount"),
        })
    return acervos


def _parse_artigo(corpo: bytes) -> tuple[str, str]:
    """HTML do /content → (titulo, texto limpo de p/h2/h3)."""
    parser = _ParserArtigo()
    try:
        parser.feed(corpo.decode("utf-8", errors="replace"))
    except Exception as exc:  # pragma: no cover - HTMLParser é tolerante
        raise KiwixError(
            "kiwix_resposta_invalida",
            f"artigo ilegível ({type(exc).__name__}).",
        ) from None
    titulo = re.sub(r"\s+", " ", html.unescape(parser.titulo)).strip()
    texto = "\n\n".join(
        bloco for bloco in (_limpar_texto(b) for b in parser.blocos) if bloco
    )
    return titulo, texto


# ---------------------------------------------------------------------------
# Cliente
# ---------------------------------------------------------------------------

class KiwixClient:
    """Cliente do Kiwix Serve — somente leitura do acervo offline.

    Attributes:
        base_url:   URL base do kiwix-serve (default local).
        timeout_s:  Timeout por chamada.
    """

    def __init__(
        self,
        base_url: str = URL_PADRAO,
        *,
        timeout_s: float = TIMEOUT_PADRAO_S,
        transporte: Optional[Callable[..., tuple[int, dict[str, str], bytes]]] = None,
    ) -> None:
        self.base_url = (base_url or URL_PADRAO).rstrip("/")
        self.timeout_s = timeout_s
        self._transporte = transporte or _transporte

    # -- transporte com mapeamento de erro -------------------------------

    def _chamada(self, caminho: str, *, timeout_s: Optional[float] = None) -> tuple[int, bytes]:
        url = f"{self.base_url}{caminho}"
        tempo = timeout_s or self.timeout_s
        try:
            status, _cabecalhos, corpo = self._transporte(url, timeout_s=tempo)
        except KiwixError:
            raise
        except (
            urllib.error.URLError,
            socket.timeout,
            ConnectionError,
            OSError,
        ) as exc:
            # Transporte injetado (testes/terceiros) sem mapeamento próprio.
            raise _erro_rede(exc, url, tempo) from None
        return status, corpo

    # -- operações --------------------------------------------------------

    def status(self, *, timeout_s: float = 15.0) -> dict[str, Any]:
        """Acervos carregados (catálogo Atom): nome, idioma, tamanhos."""
        status, corpo = self._chamada("/catalog/v2/entries", timeout_s=timeout_s)
        if status == 404:
            raise KiwixError(
                "kiwix_falhou",
                "catálogo ausente (HTTP 404) — kiwix-serve sem ZIM carregado?",
            )
        if not (200 <= status < 300):
            raise KiwixError(
                "kiwix_falhou", f"/catalog/v2/entries: HTTP {status}."
            )
        acervos = _parse_catalogo(corpo)
        return {
            "acervos": acervos,
            "total_artigos": sum(a["artigos"] for a in acervos),
            "acessivel": True,
        }

    def buscar(self, pattern: str, quantidade: int = 5) -> dict[str, Any]:
        """Busca no acervo offline → hits (título, caminho, trecho)."""
        pattern = (pattern or "").strip()
        if not pattern:
            raise KiwixError(
                "kiwix_parametro_invalido",
                "pattern não pode ser vazio.",
            )
        quantidade = max(1, min(int(quantidade or 5), 25))
        consulta = urllib.parse.urlencode({"pattern": pattern})
        status, corpo = self._chamada(f"/search?{consulta}", timeout_s=30.0)
        if not (200 <= status < 300):
            raise KiwixError("kiwix_falhou", f"/search: HTTP {status}.")
        itens = _parse_busca(corpo)
        return {"pattern": pattern, "resultados": itens[:quantidade]}

    def ler(self, caminho: str, max_chars: int = LIMITE_PADRAO_TEXTO) -> dict[str, Any]:
        """Lê um artigo pelo caminho (ex.: 'wikipedia_en_all_mini/Unicórnio')."""
        caminho = (caminho or "").strip().lstrip("/")
        if not caminho or ".." in caminho:
            raise KiwixError(
                "kiwix_parametro_invalido",
                "caminho vazio ou com '..' — use o caminho devolvido pela busca "
                "(ex.: wikipedia_en_all_mini/Unicórnio).",
            )
        max_chars = max(200, min(int(max_chars or LIMITE_PADRAO_TEXTO), 100_000))
        rota = f"{PREFIXO_CONTEUDO}{urllib.parse.quote(caminho)}"
        status, corpo = self._chamada(rota, timeout_s=30.0)
        if status == 404:
            raise KiwixError(
                "kiwix_artigo_nao_encontrado",
                f"artigo não encontrado: {caminho} (HTTP 404) — confira o "
                "caminho devolvido por kiwix_busca.",
            )
        if not (200 <= status < 300):
            raise KiwixError("kiwix_falhou", f"{rota}: HTTP {status}.")
        titulo, texto = _parse_artigo(corpo)
        truncado = len(texto) > max_chars
        if truncado:
            texto = texto[:max_chars].rstrip() + " …[cortado]"
        if not texto:
            raise KiwixError(
                "kiwix_resposta_invalida",
                f"artigo {caminho} veio sem texto extraível (HTML inesperado).",
            )
        return {
            "titulo": titulo or caminho.rsplit("/", 1)[-1].replace("_", " "),
            "texto": texto,
            "caminho": caminho,
            "bytes": len(corpo),
            "truncado": truncado,
        }


# ---------------------------------------------------------------------------
# Fábrica cacheada (uma instância por processo — lazy, nunca no boot)
# ---------------------------------------------------------------------------

_CLIENTE: Optional[KiwixClient] = None


def client_padrao() -> KiwixClient:
    """Cliente do Kiwix (URL em OD_KIWIX_URL ou default local)."""
    global _CLIENTE
    if _CLIENTE is None:
        url = _env("OD_KIWIX_URL", URL_PADRAO)
        _CLIENTE = KiwixClient(url)
        log.info("Kiwix configurado", url=url)
    return _CLIENTE


def resetar_cliente() -> None:
    """Esquece a instância cacheada (testes / troca de configuração)."""
    global _CLIENTE
    _CLIENTE = None
