"""
OMEGA DRAKON • INTEGRATIONS
Tecnologia que respira.
Módulo: integrations/filebrowser.py
Descrição: Caixa de arquivos do dono — cliente HTTP do File Browser
           self-hosted (container `od-filebrowser`, 6ª ferramenta
           interligada; pedido do dono em 2026-10-18: "Liga" — 2ª da
           análise de FlatNotes/File Browser/Calibre).

           - **File Browser 2.63.23** (filebrowser/filebrowser, MIT)
             em `127.0.0.1:8410` → `:80` do container; imagem PINADA
             no compose nesta entrega (a tag flutuante `v2` saiu da
             stack). Serve UMA pasta (`omegadrakon-tools/filebrowser/
             files` → `/srv`) — caixa de correio entre o dono
             (celular via Tailscale: sobe/baixa pela web) e o
             sistema (deixa saídas lá). UID do container = 1000 =
             dono — sem conflito de dono de arquivo.
           - **Login próprio**: admin + JWT de 2h (header `X-Auth`),
             senha lida de `OD_FILEBROWSER_PASSWORD` no `.env`
             (ROTACIONADA em 18/10 — o admin/admin nunca chegou a
             funcionar). Segredo: nunca em log, commit ou resposta.
           - Contratos vivos verificados com chamada REAL antes de
             codificar (18/10 — fonte oficial `http/*.go` da tag
             2.63.23 + round-trip completo: login → listar → subir →
             conflito → sobrescrever → baixar → apagar minhas pastas
             de teste):
             · `POST /api/login` `{username, password}` → 200 JWT
               cru | **403** = credencial rejeitada (fonte:
               `os.ErrPermission` → 403, não 401)
             · `GET /health` → 200 `{"status":"OK"}` (sem auth)
             · `GET /` → HTML com `window.FileBrowser = {...}` e o
               campo `Version` (sem auth)
             · `GET /api/resources/` → `{items[], numDirs, numFiles,
               ...}`; item = `{path, name, size, extension, modified,
               isDir, isSymlink, type}`; pasta inexistente → 404;
               arquivo no caminho → objeto de info SEM `items`
             · `POST /api/resources/{caminho}` **corpo cru = o
               arquivo** (`application/octet-stream`; multipart não —
               apurado ao vivo: o servidor guardava o envelope
               inteiro: 272 B contra 67 B do arquivo) → 200 e cria
               as pastas-pai sozinho; repetido sem `?override=true`
               → **409 Conflict**
             · `GET /api/usage/` → `{total, used}` (disco, bytes)
             · `GET /api/raw/{caminho}` → conteúdo (contrato
               provado; FORA do catálogo — o sistema lê o bind direto)
             · `DELETE ... ?recursive=true` → 204 (FORA do catálogo)
           - **NENHUMA action apaga**: o `DELETE` da API fica de
             fora do catálogo (régua do dono — nada apagado por
             acidente).
           - Erros honestos e tipados (`filebrowser_indisponivel`,
             `filebrowser_timeout`, `filebrowser_falhou`,
             `filebrowser_parametro_invalido`, `filebrowser_ja_existe`,
             `filebrowser_nao_encontrado`, `filebrowser_resposta_invalida`,
             `filebrowser_credencial`, `filebrowser_arquivo_ausente`).
           - **Lazy por desenho**: `client_padrao()` é fábrica
             cacheada e a URL tem default local — ferramenta fora do
             ar degrada a ação, nunca o boot do od-core.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - docker/tools-compose.yaml (filebrowser/filebrowser, tag pinada
    2.63.23 — o compose é a fonte exata: porta 127.0.0.1:8410 → 80,
    binds omegadrakon-tools/filebrowser/files:/srv e .../db:/database)
  - fonte oficial http/{auth,resource,raw,http}.go da tag 2.63.23 +
    round-trip real (18/10) — contrato de login/409/raw/listagem
    completo antes de codificar
  - tools/actions/actions.py (actions filebrowser_status/lista/envia)

Decisões registradas (ver CHANGELOG):
  - `substituir=False` por padrão: 409 vira `filebrowser_ja_existe`
    honesto; sobrescrever é flag explícita (`?override=true`) e vem
    DECLARADA (`substituido=True` só quando o arquivo já existia —
    conferido na pasta-pai antes do envio, só metadados)
  - Upload corpo cru (octet-stream), sem multipart: o servidor não
    parseava o multipart e guardava o envelope inteiro — provado ao
    vivo; o contrato do cliente virou corpo de bytes
  - Caminho com `..` recusado na camada da API (a caixa é isolada: o
    sistema não sai do `/srv` nem pelo caminho mais esperto)
  - Pasta VAZIA é estado honesto (`itens=[]` não é erro — mesma
    régua do caderno `[]`)
  - JWT de 2h cacheado com folga de 120s antes do exp — login novo é
    barato; a senha nunca sai do `.env`

Código associado: integrations/filebrowser.py (este arquivo)
"""

from __future__ import annotations

import base64
import json
import os
import pathlib
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

from core.logger import get_logger

log = get_logger("omega.integrations.filebrowser")

URL_PADRAO = "http://127.0.0.1:8410"
USUARIO_PADRAO = "admin"
TIMEOUT_PADRAO_S = 20.0
TIMEOUT_ENVIO_S = 60.0  # subida é local (disco → 127.0.0.1): folga p/ arquivo grande
TOLERANCIA_TOKEN_S = 120.0  # renova o JWT antes do exp
FOLHA_TOKEN_SEM_CLAIM_S = 7000.0  # exp ilegível → folga conservadora (< 2h)
LIMITE_MAXIMO_BYTES = 8 * 1024 * 1024  # respostas de status/listagem; conteúdo cru não passa por aqui
PADRAO_JANELA = re.compile(r"window\.FileBrowser = (\{.*?\});", re.S)

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

class FileBrowserError(Exception):
    """Erro tipado do File Browser: código estável + mensagem honesta."""

    def __init__(self, codigo: str, mensagem: str) -> None:
        super().__init__(mensagem)
        self.codigo = codigo
        self.mensagem = mensagem


def _erro_rede(exc: BaseException, url: str, timeout_s: float) -> FileBrowserError:
    """Falha de rede/tempo → erro tipado honesto."""
    causa = getattr(exc, "reason", exc)
    if isinstance(exc, (socket.timeout, TimeoutError)) or isinstance(
        causa, (socket.timeout, TimeoutError)
    ):
        return FileBrowserError(
            "filebrowser_timeout",
            f"File Browser não respondeu em {timeout_s:.0f}s ({url}).",
        )
    return FileBrowserError(
        "filebrowser_indisponivel",
        f"File Browser inacessível em {url}: {causa}",
    )


def _transporte(
    url: str,
    *,
    timeout_s: float,
    metodo: str = "GET",
    corpo: Optional[dict[str, Any]] = None,
    corpo_bruto: Any = None,
    cabecalhos: Optional[dict[str, str]] = None,
) -> tuple[int, dict[str, str], bytes]:
    """urllib real → (status, headers, corpo). HTTPError É uma resposta.

    `corpo` (dict) vira JSON; `corpo_bruto` (bytes ou file-like) vai
    CRU — o File Browser guarda o corpo inteiro como o arquivo.
    """
    dados: Any = None
    envio: dict[str, str] = dict(cabecalhos or {})
    if corpo is not None:
        dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        envio.setdefault("Content-Type", "application/json")
    if corpo_bruto is not None:
        dados = corpo_bruto
        envio.setdefault("Content-Type", "application/octet-stream")
    req = urllib.request.Request(url, data=dados, method=metodo, headers=envio)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return int(resp.status), dict(resp.headers), resp.read(LIMITE_MAXIMO_BYTES)
    except urllib.error.HTTPError as exc:
        try:
            corpo_lido = exc.read()
        except Exception:  # pragma: no cover - corpo ilegível é raro
            corpo_lido = b""
        cabecalhos_erro: dict[str, str] = {}
        try:
            cabecalhos_erro = dict(exc.headers) if exc.headers else {}
        except Exception:  # pragma: no cover
            pass
        return int(exc.code), cabecalhos_erro, corpo_lido
    except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as exc:
        raise _erro_rede(exc, url, timeout_s) from None


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------

def _detalhe_erro(corpo: bytes) -> str:
    """Detalhe honesto do corpo de erro (JSON comum; texto puro também)."""
    texto = corpo.decode("utf-8", "replace") if corpo else ""
    if not texto:
        return ""
    try:
        dados = json.loads(texto)
    except ValueError:
        dados = None
    if isinstance(dados, dict):
        for chave in ("detail", "message", "error"):
            valor = dados.get(chave)
            if isinstance(valor, str) and valor.strip():
                return valor.strip()[:160]
    limpo = texto.strip().replace("\n", " ").replace("\r", " ")
    # corpo textual curto e legível (ex.: "409 Conflict") também serve
    if limpo and len(limpo) <= 160 and all(c.isprintable() or c == " " for c in limpo):
        return limpo
    return ""


def _parse_json(corpo: bytes, onde: str) -> Any:
    """Corpo → JSON; corpo malformado é erro honesto."""
    try:
        return json.loads(corpo.decode("utf-8", "replace"))
    except ValueError:
        raise FileBrowserError(
            "filebrowser_resposta_invalida",
            f"{onde}: corpo não é JSON válido.",
        ) from None


def _normaliza_caminho(caminho: Optional[str], *, exigir: bool, campo: str) -> str:
    """Caminho relativo da caixa → forma limpa (sem `..`, sem vazios).

    A caixa é isolada no `/srv` do container: `..` recusado aqui é
    mais honesto que descobrir 403/404 depois.
    """
    texto = (caminho or "").strip()
    if exigir and not texto:
        raise FileBrowserError(
            "filebrowser_parametro_invalido", f"{campo} não pode ser vazio."
        )
    partes = [p for p in texto.split("/") if p not in ("", ".")]
    if any(p == ".." for p in partes):
        raise FileBrowserError(
            "filebrowser_parametro_invalido",
            f"{campo} com '..' — o sistema não sai da caixa de arquivos.",
        )
    return "/".join(partes)


def _exp_do_jwt(token: str) -> float:
    """`exp` do payload do JWT (sem assinar — confia no servidor).

    Payload ilegível → folga conservadora menor que o regime de 2h:
    um token torto renova cedo, nunca vence no meio de uma operação.
    """
    try:
        carga = token.split(".")[1]
        carga += "=" * (-len(carga) % 4)
        dados = json.loads(base64.urlsafe_b64decode(carga))
        exp = float(dados.get("exp") or 0)
        if exp > 0:
            return exp
    except (IndexError, KeyError, TypeError, ValueError):
        pass
    return time.time() + FOLHA_TOKEN_SEM_CLAIM_S


class FileBrowserClient:
    """Cliente do File Browser (transporte injetável p/ testes)."""

    def __init__(
        self,
        base_url: str = URL_PADRAO,
        usuario: str = USUARIO_PADRAO,
        senha: str = "",
        timeout_s: float = TIMEOUT_PADRAO_S,
        transporte: Optional[Callable[..., tuple[int, dict[str, str], bytes]]] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.usuario = usuario
        self.senha = senha
        self.timeout_s = timeout_s
        self._transporte = transporte or _transporte
        self._token: Optional[str] = None
        self._token_exp: float = 0.0

    # -- transporte --------------------------------------------------------

    def _chamada(
        self,
        metodo: str,
        caminho: str,
        *,
        corpo: Optional[dict[str, Any]] = None,
        corpo_bruto: Any = None,
        cabecalhos: Optional[dict[str, str]] = None,
        timeout_s: Optional[float] = None,
        autentica: bool = True,
    ) -> tuple[int, bytes]:
        url = f"{self.base_url}{caminho}"
        tempo = timeout_s or self.timeout_s
        envio: dict[str, str] = dict(cabecalhos or {})
        if autentica:
            envio["X-Auth"] = self._token_efetivo()
        try:
            status, _cabecalhos, corpo_bytes = self._transporte(
                url,
                timeout_s=tempo,
                metodo=metodo,
                corpo=corpo,
                corpo_bruto=corpo_bruto,
                cabecalhos=envio,
            )
        except FileBrowserError:
            raise
        except (
            urllib.error.URLError,
            socket.timeout,
            ConnectionError,
            OSError,
        ) as exc:
            # Transporte injetado (testes/terceiros) sem mapeamento próprio.
            raise _erro_rede(exc, url, tempo) from None
        return status, corpo_bytes

    def _espera_200(self, status: int, corpo: bytes, onde: str) -> None:
        if 200 <= status < 300:
            return
        detalhe = _detalhe_erro(corpo)
        if status == 404:
            raise FileBrowserError(
                "filebrowser_nao_encontrado",
                f"{onde}: 404 — {detalhe or 'não encontrado'}.",
            )
        raise FileBrowserError(
            "filebrowser_falhou",
            f"{onde}: HTTP {status}" + (f" — {detalhe}." if detalhe else "."),
        )

    # -- autenticação ------------------------------------------------------

    def _login(self) -> str:
        """Troca admin + senha por JWT cru (cacheia em `_token_efetivo`)."""
        if not self.senha:
            raise FileBrowserError(
                "filebrowser_credencial",
                "OD_FILEBROWSER_PASSWORD não configurada no .env — "
                "login do admin do File Browser.",
            )
        status, corpo = self._chamada(
            "POST",
            "/api/login",
            corpo={"username": self.usuario, "password": self.senha},
            autentica=False,
        )
        if status == 403:
            # Fonte oficial: os.ErrPermission → 403 = credencial rejeitada.
            raise FileBrowserError(
                "filebrowser_credencial",
                "Login recusado (403): a senha do admin mudou no painel? "
                "Atualize OD_FILEBROWSER_PASSWORD no .env (e no cofre).",
            )
        if status != 200:
            detalhe = _detalhe_erro(corpo)
            raise FileBrowserError(
                "filebrowser_falhou",
                f"POST /api/login: HTTP {status}" + (f" — {detalhe}." if detalhe else "."),
            )
        token = corpo.decode("utf-8", "replace").strip()
        if not token.startswith("ey"):
            raise FileBrowserError(
                "filebrowser_resposta_invalida",
                "POST /api/login: corpo não é JWT.",
            )
        return token

    def _token_efetivo(self) -> str:
        """JWT válido (renova antes do exp; login é barato)."""
        if self._token and time.time() < self._token_exp - TOLERANCIA_TOKEN_S:
            return self._token
        token = self._login()
        self._token = token
        self._token_exp = _exp_do_jwt(token)
        return token

    # -- operações ---------------------------------------------------------

    def status(self, *, timeout_s: float = 15.0) -> dict[str, Any]:
        """Vida da caixa: saúde pública, versão, nº de itens e disco."""
        status, corpo = self._chamada("GET", "/health", timeout_s=timeout_s, autentica=False)
        self._espera_200(status, corpo, "GET /health")
        dados = _parse_json(corpo, "GET /health")
        if not isinstance(dados, dict) or not isinstance(dados.get("status"), str):
            raise FileBrowserError(
                "filebrowser_resposta_invalida",
                "GET /health: JSON sem 'status'.",
            )
        saude = dados["status"]

        status, corpo = self._chamada("GET", "/", timeout_s=timeout_s, autentica=False)
        self._espera_200(status, corpo, "GET /")
        pagina = corpo.decode("utf-8", "replace")
        janela = PADRAO_JANELA.search(pagina)
        if not janela:
            raise FileBrowserError(
                "filebrowser_resposta_invalida",
                "GET /: window.FileBrowser ausente no HTML — a página mudou?",
            )
        try:
            config = json.loads(janela.group(1))
        except ValueError:
            raise FileBrowserError(
                "filebrowser_resposta_invalida",
                "GET /: janela FileBrowser não é JSON válido.",
            ) from None
        versao = config.get("Version") if isinstance(config, dict) else None
        if not isinstance(versao, str) or not versao:
            raise FileBrowserError(
                "filebrowser_resposta_invalida",
                "GET /: campo 'Version' ausente na janela FileBrowser.",
            )

        status, corpo = self._chamada("GET", "/api/usage/", timeout_s=timeout_s)
        self._espera_200(status, corpo, "GET /api/usage")
        uso = _parse_json(corpo, "GET /api/usage")
        if not isinstance(uso, dict) or "total" not in uso or "used" not in uso:
            raise FileBrowserError(
                "filebrowser_resposta_invalida",
                "GET /api/usage: JSON sem total/used.",
            )
        total = int(uso["total"])
        usado = int(uso["used"])

        status, corpo = self._chamada("GET", "/api/resources/", timeout_s=timeout_s)
        self._espera_200(status, corpo, "GET /api/resources")
        raiz = _parse_json(corpo, "GET /api/resources")
        if not isinstance(raiz, dict) or "numDirs" not in raiz or "numFiles" not in raiz:
            raise FileBrowserError(
                "filebrowser_resposta_invalida",
                "GET /api/resources: JSON sem numDirs/numFiles.",
            )
        pct = round(usado * 100.0 / total, 1) if total else None
        return {
            "acessivel": True,
            "saude": saude,
            "versao": versao,
            "pastas": int(raiz["numDirs"]),
            "arquivos": int(raiz["numFiles"]),
            "disco": {"total": total, "usado": usado, "uso_pct": pct},
        }

    def lista(self, caminho: str = "", *, timeout_s: Optional[float] = None) -> dict[str, Any]:
        """Lista UMA pasta da caixa (raiz por padrão) — pasta vazia é estado."""
        limpo = _normaliza_caminho(caminho, exigir=False, campo="caminho")
        # Raiz só com a barra final (sem ela o servidor responde 301);
        # subpasta sem barra funciona e distingue arquivo de pasta.
        caminho_url = (
            "/api/resources/"
            if not limpo
            else "/api/resources/" + urllib.parse.quote(limpo, safe="/")
        )
        status, corpo = self._chamada("GET", caminho_url, timeout_s=timeout_s)
        if status == 404:
            raise FileBrowserError(
                "filebrowser_nao_encontrado",
                f"Pasta '{limpo or '/'}' não existe na caixa de arquivos.",
            )
        self._espera_200(status, corpo, "GET /api/resources")
        dados = _parse_json(corpo, "GET /api/resources")
        if not isinstance(dados, dict):
            raise FileBrowserError(
                "filebrowser_resposta_invalida",
                "GET /api/resources: JSON não é objeto.",
            )
        if "items" not in dados:
            raise FileBrowserError(
                "filebrowser_parametro_invalido",
                f"'{limpo}' não é uma pasta (é arquivo) — use a raiz "
                "ou um diretório da caixa.",
            )
        itens_brutos = dados["items"]
        if not isinstance(itens_brutos, list):
            raise FileBrowserError(
                "filebrowser_resposta_invalida",
                "GET /api/resources: 'items' não é lista.",
            )
        itens: list[dict[str, Any]] = []
        for item in itens_brutos:
            if not isinstance(item, dict):
                raise FileBrowserError(
                    "filebrowser_resposta_invalida",
                    "GET /api/resources: item da lista não é objeto.",
                )
            itens.append({
                "nome": str(item.get("name", "")),
                "caminho": str(item.get("path", "")),
                "e_pasta": bool(item.get("isDir")),
                "tamanho": int(item.get("size") or 0),
                "modificado": str(item.get("modified") or ""),
            })
        num_dirs = dados.get("numDirs")
        num_files = dados.get("numFiles")
        if not isinstance(num_dirs, int) or not isinstance(num_files, int):
            raise FileBrowserError(
                "filebrowser_resposta_invalida",
                "GET /api/resources: numDirs/numFiles não são números.",
            )
        return {
            "caminho": "/" + limpo,
            "pastas": num_dirs,
            "arquivos": num_files,
            "itens": itens,
        }

    def _existe_no_pai(self, destino: str) -> bool:
        """Confere a pasta-pai (só metadados) p/ declarar troca real."""
        if "/" in destino:
            pai, nome = destino.rsplit("/", 1)
        else:
            pai, nome = "", destino
        caminho_url = (
            "/api/resources/"
            if not pai
            else "/api/resources/" + urllib.parse.quote(pai, safe="/")
        )
        status, corpo = self._chamada("GET", caminho_url)
        if status == 404:
            return False
        self._espera_200(status, corpo, "GET /api/resources (pai)")
        dados = _parse_json(corpo, "GET /api/resources (pai)")
        if not isinstance(dados, dict) or not isinstance(dados.get("items"), list):
            raise FileBrowserError(
                "filebrowser_resposta_invalida",
                "GET /api/resources (pai): JSON sem lista 'items'.",
            )
        return any(
            isinstance(item, dict) and str(item.get("name", "")) == nome
            for item in dados["items"]
        )

    def envia(
        self,
        origem: str,
        destino: str,
        substituir: bool = False,
    ) -> dict[str, Any]:
        """Deixa UMA arquivo local na caixa (corpo cru; troca só com flag)."""
        origem_txt = str(origem or "").strip()
        if not origem_txt:
            raise FileBrowserError(
                "filebrowser_parametro_invalido", "origem não pode ser vazia."
            )
        origem_path = pathlib.Path(origem_txt)
        if not origem_path.is_file():
            raise FileBrowserError(
                "filebrowser_arquivo_ausente",
                f"Origem não é arquivo local: {origem_txt}",
            )
        destino_txt = str(destino or "").strip()
        if destino_txt.endswith("/"):
            raise FileBrowserError(
                "filebrowser_parametro_invalido",
                "destino precisa nomear um arquivo (não termina em '/').",
            )
        destino_limpo = _normaliza_caminho(destino_txt, exigir=True, campo="destino")
        if not destino_limpo:
            raise FileBrowserError(
                "filebrowser_parametro_invalido", "destino não pode ser vazio."
            )

        # substituir=True → declara a troca REAL conferindo a pasta-pai
        # antes (metadados; nenhum conteúdo de arquivo é baixado).
        substituido = False
        if substituir:
            substituido = self._existe_no_pai(destino_limpo)

        caminho_url = "/api/resources/" + urllib.parse.quote(destino_limpo, safe="/")
        if substituir:
            caminho_url += "?override=true"
        tamanho = origem_path.stat().st_size
        with open(origem_path, "rb") as arquivo:
            status, corpo = self._chamada(
                "POST",
                caminho_url,
                corpo_bruto=arquivo,
                timeout_s=TIMEOUT_ENVIO_S,
            )
        if status == 409:
            raise FileBrowserError(
                "filebrowser_ja_existe",
                f"'{destino_limpo}' já existe na caixa — use substituir=true "
                "(o original só sai com pedido explícito).",
            )
        if status == 403:
            raise FileBrowserError(
                "filebrowser_falhou",
                f"POST /api/resources: HTTP 403 — permissão de criação "
                "recusada no File Browser.",
            )
        self._espera_200(status, corpo, f"POST /api/resources/{destino_limpo}")
        return {
            "arquivo": destino_limpo,
            "tamanho": tamanho,
            "substituido": bool(substituir and substituido),
        }


# ---------------------------------------------------------------------------
# Fábrica cacheada (lazy)
# ---------------------------------------------------------------------------

_CLIENTE: Optional[FileBrowserClient] = None


def client_padrao() -> FileBrowserClient:
    """Cliente do File Browser (URL/senha em OD_FILEBROWSER_* ou defaults)."""
    global _CLIENTE
    if _CLIENTE is None:
        url = _env("OD_FILEBROWSER_URL", URL_PADRAO)
        usuario = _env("OD_FILEBROWSER_USUARIO", USUARIO_PADRAO)
        senha = _env("OD_FILEBROWSER_PASSWORD", "")
        _CLIENTE = FileBrowserClient(url, usuario=usuario, senha=senha)
        log.info("File Browser configurado", url=url, usuario=usuario)
    return _CLIENTE


def resetar_cliente() -> None:
    """Esquece a instância cacheada (testes / troca de configuração)."""
    global _CLIENTE
    _CLIENTE = None
