"""
OMEGA DRAKON • INTEGRATIONS
Tecnologia que respira.
Módulo: integrations/stirling.py
Descrição: Pipeline de documentos do sistema — cliente HTTP do Stirling PDF
           self-hosted (container `od-stirling-pdf`, 2ª das 3 interligações
           de ferramenta aprovadas pelo dono em 2026-10-17: Vaultwarden →
           Stirling → Kiwix).

           - **API oficial v1** do s-pdf **2.13.1** (OpenAPI 3.0.3 publicado
             em `GET /v1/api-docs`, 255 rotas apuradas ao vivo em 17/10);
             sem login (`SECURITY_ENABLELOGIN=false`, nenhuma API key no
             env do container) e escuta só em `127.0.0.1:8400` → `:8080` do
             container (nada exposto à internet).
           - Contratos vivos verificados com chamadas REAIS antes de
             codificar (17/10):
               · `GET  /api/v1/info/status` → `{"version","status"}`
               · `POST /api/v1/general/merge-pdfs` (fileInput[] +
                 sortType + removeCertSign OBRIGATÓRIOS) → `application/pdf`
                 síncrono (sem job)
               · `POST /api/v1/general/split-pages` (fileInput +
                 pageNumbers: "2" | "2,5" | "5-9" | "all" | "2n+1") →
                 PDF (1 peça) ou ZIP (várias)
               · `POST /api/v1/misc/compress-pdf` (optimizeLevel 1–9,
                 expectedOutputSize, grayscale/linearize/normalize
                 OBRIGATÓRIOS) → arquivo
               · `POST /api/v1/analysis/page-count` → `{"pageCount"}`
                 (usada só na prova viva; não virou action nesta fatia)
           - `multipart/form-data` montado à mão no padrão stdlib do
             projeto (mesma técnica de `HTTPTransport.build_multipart`) —
             **zero dependência nova** (requirements.txt continua puro).
           - Erros honestos e tipados (`stirling_indisponivel`,
             `stirling_timeout`, `stirling_pdf_invalido`,
             `stirling_gigante`, `stirling_proibido`, `stirling_falhou`,
             `stirling_arquivo_ausente`, `stirling_diretorio_ausente`,
             `stirling_saida_ocupada`, `stirling_parametro_invalido`,
             `stirling_resposta_invalida`).
           - **Saída só grava após validação de mágica** (%PDF ou PK zip):
             resposta inválida NUNCA vira arquivo no disco; arquivo de
             saída existente só é substituído com `substituir=True`
             (nada apagado por acidente).
           - **Lazy por desenho**: `client_padrao()` é fábrica cacheada e
             a URL tem default local — ferramenta fora do ar degrada a
             ação, nunca o boot do od-core.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - docker/tools-compose.yaml (ghcr.io/stirling-tools/s-pdf:2.13.1,
    porta 127.0.0.1:8400 → 8080, JAVA_TOOL_OPTIONS com Metaspace 256m)
  - GET /v1/api-docs (OpenAPI vivo — contratos das 4 operações)
  - tools/actions/actions.py (actions stirling_status/merge/split/compress)
  - integrations/telegram/transport.py (padrão de multipart stdlib)

Decisões registradas (ver CHANGELOG):
  - stdlib `urllib` + multipart manual em vez de httpx/requests: o
    requirements.txt do cliente é stdlib puro (só websockets é não-stdlib,
    e é servidor)
  - Operações SÍNCRONAS nesta fatia (a API devolve o arquivo na resposta)
  - Campos obrigatórios SEMPRE enviados por nós com default conhecido —
    nada depende do default do servidor
  - `arquivos` chega como string "a.pdf,b.pdf" (params de action não têm
    array no catálogo); o parse da lista é no cliente
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import socket
import urllib.error
import urllib.request
import uuid
from typing import Any, Callable, Optional

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.integrations.stirling")

_ENV_PATH = pathlib.Path(__file__).resolve().parent.parent / ".env"

#: URL padrão: só localhost (o compose publica em 127.0.0.1:8400).
URL_PADRAO = "http://127.0.0.1:8400"

#: Timeout das operações pesadas (merge/split/compress — o container tem
#: LibreOffice/OCR no meio; 120s cobre documentos de casa com folga).
TIMEOUT_OPERACAO_S = 120.0

_MAGIC_PDF = b"%PDF"
_MAGIC_ZIP = b"PK"

#: expectedOutputSize da API: "25KB", "100MB", "1.5GB"…
_RE_TAMANHO = re.compile(r"^\d+(\.\d+)?\s*[KMGT]?I?B$", re.I)

#: optimizeLevel aceito pela API (enum int32 1..9 do OpenAPI).
_NIVEIS = range(1, 10)


class StirlingError(Exception):
    """Erro tipado do Stirling — `codigo` vira o campo `error` na action."""

    def __init__(self, codigo: str, mensagem: str) -> None:
        super().__init__(mensagem)
        self.codigo = codigo
        self.mensagem = mensagem


def _env(name: str, default: str = "") -> str:
    """Valor de configuração: os.environ primeiro, `.env` depois.

    (Mesmo padrão de `integrations/vault.py` — sem importar o launcher
    para não amarrar este módulo ao boot.)
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
# Camada baixa: multipart + transporte (stdlib puro)
# ---------------------------------------------------------------------------

def _nome_seguro(caminho: str) -> str:
    """Basename do arquivo com aspas/quebras removidas (injeção no header)."""
    nome = os.path.basename(str(caminho)) or "arquivo"
    return nome.replace('"', "").replace("\r", "").replace("\n", "")[:200]


def _monta_multipart(
    campos: dict[str, str],
    arquivos: list[tuple[str, str, bytes]],
) -> tuple[str, bytes]:
    """Monta corpo `multipart/form-data` (boundary, body) — stdlib.

    `arquivos` = [(campo, nome, conteúdo)…] — vários itens no MESMO campo
    formam o array `fileInput[]` da API (merge).
    """
    boundary = "----od" + uuid.uuid4().hex
    partes: list[bytes] = []
    for chave, valor in campos.items():
        partes.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{chave}"\r\n\r\n'
                f"{valor}\r\n"
            ).encode("utf-8")
        )
    for campo, nome, conteudo in arquivos:
        partes.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{campo}"; '
                f'filename="{_nome_seguro(nome)}"\r\n'
                f"Content-Type: application/pdf\r\n\r\n"
            ).encode("utf-8")
        )
        partes.append(conteudo)
        partes.append(b"\r\n")
    partes.append(f"--{boundary}--\r\n".encode("utf-8"))
    return boundary, b"".join(partes)


def _erro_rede(exc: BaseException, url: str, timeout_s: float) -> StirlingError:
    """Falha de rede/tempo → erro tipado honesto (compartilhado pelo
    adapter urllib e por qualquer transporte injetado)."""
    causa = getattr(exc, "reason", exc)
    if isinstance(exc, (socket.timeout, TimeoutError)) or isinstance(
        causa, (socket.timeout, TimeoutError)
    ):
        return StirlingError(
            "stirling_timeout",
            f"Stirling não respondeu em {timeout_s:.0f}s ({url}).",
        )
    return StirlingError(
        "stirling_indisponivel",
        f"Stirling PDF inacessível em {url}: {causa}",
    )


def _transporte(
    url: str,
    *,
    data: Optional[bytes],
    headers: dict[str, str],
    timeout_s: float,
) -> tuple[int, dict[str, str], bytes]:
    """urllib real → (status, headers, corpo). HTTPError É uma resposta.

    Falha de rede/tempo vira StirlingError tipado (mapeado aqui para o
    erro nascer perto do fio, com a causa verdadeira).
    """
    metodo = "POST" if data is not None else "GET"
    req = urllib.request.Request(url, data=data, headers=headers, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return int(resp.status), dict(resp.headers), resp.read()
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


def _extrai_erro(corpo: bytes) -> str:
    """Mensagem honesta do servidor (ErrorResponse {status,error}) ou bruta."""
    texto = corpo.decode("utf-8", errors="replace").strip()
    try:
        bruto = json.loads(texto)
        if isinstance(bruto, dict):
            para = bruto.get("error") or bruto.get("message") or bruto.get("detail")
            if para:
                return str(para)[:400]
    except (json.JSONDecodeError, ValueError):
        pass
    return texto[:400] or "(corpo vazio)"


def _content_type(headers: dict[str, str]) -> str:
    """Content-Type normalizado (sem parâmetros, minúsculo)."""
    bruto = ""
    for chave, valor in headers.items():
        if chave.lower() == "content-type":
            bruto = valor
            break
    return bruto.split(";")[0].strip().lower()


# ---------------------------------------------------------------------------
# Cliente
# ---------------------------------------------------------------------------

class StirlingClient:
    """Cliente da API v1 do Stirling — transporte injetável para testes."""

    def __init__(
        self,
        base_url: str = URL_PADRAO,
        *,
        timeout_s: float = TIMEOUT_OPERACAO_S,
        transporte: Optional[Callable[..., tuple[int, dict[str, str], bytes]]] = None,
    ) -> None:
        self.base_url = (base_url or URL_PADRAO).rstrip("/")
        self.timeout_s = float(timeout_s)
        self._transporte = transporte or _transporte

    # -- requisição ------------------------------------------------------

    def _chamada(
        self,
        caminho: str,
        *,
        data: Optional[bytes] = None,
        campos: Optional[dict[str, str]] = None,
        arquivos: Optional[list[tuple[str, str, bytes]]] = None,
        timeout_s: Optional[float] = None,
    ) -> tuple[int, dict[str, str], bytes]:
        """Monta multipart (se preciso), chama o transporte e checa status."""
        headers = {"User-Agent": "OmegaDrakon-Stirling/1.0"}
        corpo_envio = data
        if campos is not None or arquivos is not None:
            boundary, corpo_envio = _monta_multipart(campos or {}, arquivos or [])
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        url = f"{self.base_url}{caminho}"
        tempo = timeout_s or self.timeout_s
        try:
            status, cabecalhos, corpo = self._transporte(
                url,
                data=corpo_envio,
                headers=headers,
                timeout_s=tempo,
            )
        except StirlingError:
            raise
        except (
            urllib.error.URLError,
            socket.timeout,
            ConnectionError,
            OSError,
        ) as exc:
            # Transporte injetado (testes/terceiros) sem mapeamento próprio.
            raise _erro_rede(exc, url, tempo) from None
        return status, cabecalhos, self._checa(status, corpo, caminho)

    def _checa(self, status: int, corpo: bytes, contexto: str) -> bytes:
        """2xx → corpo; 4xx/5xx → StirlingError honesto e tipado."""
        if 200 <= status < 300:
            return corpo
        detalhe = _extrai_erro(corpo)
        if status in (400, 422):
            raise StirlingError(
                "stirling_pdf_invalido",
                f"{contexto}: o Stirling recusou o conteúdo (HTTP {status}) — {detalhe}",
            )
        if status == 413:
            raise StirlingError(
                "stirling_gigante",
                f"{contexto}: arquivo grande demais para o Stirling (HTTP 413).",
            )
        if status in (401, 403):
            raise StirlingError(
                "stirling_proibido",
                f"{contexto}: acesso recusado (HTTP {status}) — a API pede "
                "autenticação que este cliente não tem.",
            )
        raise StirlingError(
            "stirling_falhou",
            f"{contexto}: HTTP {status} — {detalhe}",
        )

    # -- validações de entrada/saída -------------------------------------

    @staticmethod
    def _confirma_entrada(caminho: str) -> pathlib.Path:
        caminho = str(caminho or "").strip()
        caminho_obj = pathlib.Path(caminho)
        if not caminho or not caminho_obj.is_file():
            raise StirlingError(
                "stirling_arquivo_ausente",
                f"Arquivo de entrada não encontrado: {caminho or '(vazio)'}",
            )
        return caminho_obj

    @staticmethod
    def _prepara_saida(saida: str, substituir: bool) -> pathlib.Path:
        saida_obj = pathlib.Path(str(saida or "").strip())
        if not str(saida_obj) or str(saida_obj) == ".":
            raise StirlingError(
                "stirling_parametro_invalido",
                "saida: informe o caminho do arquivo de saída.",
            )
        if saida_obj.exists() and not substituir:
            raise StirlingError(
                "stirling_saida_ocupada",
                f"{saida_obj} já existe — passe substituir=True para "
                "sobrescrever (nada é apagado por acidente).",
            )
        if not saida_obj.parent.is_dir():
            raise StirlingError(
                "stirling_diretorio_ausente",
                f"Diretório de saída não existe: {saida_obj.parent}",
            )
        return saida_obj

    @staticmethod
    def _grava(
        saida_obj: pathlib.Path,
        corpo: bytes,
        magics: tuple[bytes, ...],
        contexto: str,
    ) -> dict[str, Any]:
        """Valida a resposta e só ENTÃO grava (resposta ruim nunca vira arquivo)."""
        if not corpo:
            raise StirlingError(
                "stirling_resposta_invalida",
                f"{contexto}: resposta vazia do Stirling — nada foi gravado.",
            )
        if not any(corpo[:1024].find(m) == 0 for m in magics):
            cabeca = repr(corpo[:40])
            raise StirlingError(
                "stirling_resposta_invalida",
                f"{contexto}: resposta não é o arquivo esperado "
                f"(primeiros bytes: {cabeca}) — nada foi gravado.",
            )
        saida_obj.write_bytes(corpo)
        return {
            "arquivo": str(saida_obj),
            "bytes": len(corpo),
            "sha256": hashlib.sha256(corpo).hexdigest(),
        }

    # -- operações -------------------------------------------------------

    def status(self, *, timeout_s: float = 15.0) -> dict[str, Any]:
        """Versão + estado da API (o mesmo que o healthcheck do container)."""
        _status, _cabecalhos, corpo = self._chamada(
            "/api/v1/info/status", timeout_s=timeout_s
        )
        try:
            bruto = json.loads(corpo.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            raise StirlingError(
                "stirling_falhou",
                f"/api/v1/info/status: resposta não-JSON "
                f"({repr(corpo[:60])})",
            ) from None
        if not isinstance(bruto, dict):
            raise StirlingError(
                "stirling_falhou",
                "/api/v1/info/status: formato inesperado (esperado objeto).",
            )
        versao = str(bruto.get("version") or "")
        estado = str(bruto.get("status") or "")
        if not (versao or estado):
            raise StirlingError(
                "stirling_falhou",
                f"/api/v1/info/status: sem version/status no corpo "
                f"({repr(corpo[:60])})",
            )
        return {
            "url": self.base_url,
            "versao": versao,
            "estado": estado,
        }

    def merge(
        self,
        arquivos: list[str],
        saida: str,
        *,
        substituir: bool = False,
    ) -> dict[str, Any]:
        """Junta 2+ PDFs em um só (ordem fornecida, sem cert-sig)."""
        caminhos = [str(a).strip() for a in arquivos if str(a).strip()]
        if len(caminhos) < 2:
            raise StirlingError(
                "stirling_parametro_invalido",
                "merge: informe ao menos 2 caminhos de PDF separados por vírgula.",
            )
        entradas = [self._confirma_entrada(c) for c in caminhos]
        saida_obj = self._prepara_saida(saida, substituir)
        conteudos = [("fileInput", str(e), e.read_bytes()) for e in entradas]
        _status, cabecalhos, corpo = self._chamada(
            "/api/v1/general/merge-pdfs",
            campos={"sortType": "orderProvided", "removeCertSign": "true"},
            arquivos=conteudos,
        )
        resultado = self._grava(saida_obj, corpo, (_MAGIC_PDF,), "merge")
        resultado["content_type"] = _content_type(cabecalhos)
        resultado["entradas"] = len(entradas)
        return resultado

    def split(
        self,
        arquivo: str,
        cortes: str,
        saida: str,
        *,
        substituir: bool = False,
    ) -> dict[str, Any]:
        """Corta um PDF nos pontos `cortes` ("2", "2,5", "5-9", "all", "2n+1")."""
        entrada = self._confirma_entrada(arquivo)
        saida_obj = self._prepara_saida(saida, substituir)
        pontos = str(cortes or "all").strip() or "all"
        _status, cabecalhos, corpo = self._chamada(
            "/api/v1/general/split-pages",
            campos={"pageNumbers": pontos},
            arquivos=[("fileInput", str(entrada), entrada.read_bytes())],
        )
        resultado = self._grava(
            saida_obj, corpo, (_MAGIC_PDF, _MAGIC_ZIP), "split"
        )
        tipo = _content_type(cabecalhos)
        resultado["content_type"] = tipo
        resultado["formato"] = (
            "zip" if corpo.startswith(_MAGIC_ZIP) or tipo == "application/zip"
            else "pdf"
        )
        resultado["cortes"] = pontos
        return resultado

    def compress(
        self,
        arquivo: str,
        saida: str,
        *,
        nivel: int = 4,
        alvo: str = "25KB",
        cinza: bool = False,
        substituir: bool = False,
    ) -> dict[str, Any]:
        """Comprime um PDF: nível 1–9 (maior = mais compressão), alvo de tamanho."""
        entrada = self._confirma_entrada(arquivo)
        saida_obj = self._prepara_saida(saida, substituir)
        try:
            nivel_i = int(nivel)
        except (TypeError, ValueError):
            raise StirlingError(
                "stirling_parametro_invalido",
                f"nivel: inteiro entre 1 e 9 (recebido {nivel!r}).",
            ) from None
        if nivel_i not in _NIVEIS:
            raise StirlingError(
                "stirling_parametro_invalido",
                f"nivel: fora da faixa 1–9 (recebido {nivel_i}).",
            )
        alvo_s = str(alvo or "25KB").strip() or "25KB"
        if not _RE_TAMANHO.match(alvo_s):
            raise StirlingError(
                "stirling_parametro_invalido",
                f"alvo: formato '25KB'/'100MB' (recebido {alvo_s!r}).",
            )
        antes = entrada.stat().st_size
        _status, cabecalhos, corpo = self._chamada(
            "/api/v1/misc/compress-pdf",
            campos={
                "optimizeLevel": str(nivel_i),
                "expectedOutputSize": alvo_s,
                "linearize": "false",
                "normalize": "false",
                "grayscale": "true" if cinza else "false",
            },
            arquivos=[("fileInput", str(entrada), entrada.read_bytes())],
        )
        resultado = self._grava(saida_obj, corpo, (_MAGIC_PDF,), "compress")
        depois = resultado["bytes"]
        resultado["content_type"] = _content_type(cabecalhos)
        resultado["bytes_entrada"] = antes
        resultado["reducao_pct"] = (
            round((1 - depois / antes) * 100, 1) if antes else 0.0
        )
        return resultado


# ---------------------------------------------------------------------------
# Fábrica cacheada (uma instância por processo — lazy, nunca no boot)
# ---------------------------------------------------------------------------

_CLIENTE: Optional[StirlingClient] = None


def client_padrao() -> StirlingClient:
    """Cliente do Stirling (URL em OD_STIRLING_URL ou default local)."""
    global _CLIENTE
    if _CLIENTE is None:
        url = _env("OD_STIRLING_URL", URL_PADRAO)
        _CLIENTE = StirlingClient(url)
        log.info("Stirling PDF configurado", url=url)
    return _CLIENTE


def resetar_cliente() -> None:
    """Esquece a instância cacheada (testes / troca de configuração)."""
    global _CLIENTE
    _CLIENTE = None
