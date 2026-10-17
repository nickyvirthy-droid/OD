"""
OMEGA DRAKON • INTEGRATIONS
Tecnologia que respira.
Módulo: integrations/homebox.py
Descrição: Inventário do dono — cliente HTTP do Homebox self-hosted
           (container `od-homebox`, sysadminsmedia/homebox **0.26.2**,
           4ª e última das ferramentas interligadas; uso DEFINIDO pelo
           dono em 17/10: *"me ajudar a cadastrar as ferramentas e peças
           que possuo... sabendo disso, sugerir montagens (ex.: estação
           meteorológica) dizendo as peças que possuo e as que preciso"*).

           - Escuta só em `127.0.0.1:8470` → `:7745` do container; dados
             em `/home/alex/omegadrakon-tools/homebox` (o banco com 0
             usuários de 17/10 foi preservado no desligamento; conta do
             sistema + API key criadas na reativação de 17/10).
           - **Contrato apurado ao vivo ANTES de codificar** (17/10) —
             swagger servido pelo próprio container em `/swagger/doc.json`
             (67 rotas, Swagger 2.0) + chamadas reais:
               · `GET  /api/v1/status` → versão/build (público)
               · `POST /api/v1/users/register` → 204 (primeira conta,
                 superuser; permitido enquanto `allowRegistration`)
               · `POST /api/v1/users/login` → `{token, expiresAt,
                 attachmentToken}` — **ACHADO: a session token NÃO vale
                 como `Authorization: Bearer`** (middleware lê o cookie
                 `hb.auth.token`); já a **API key** vale EXATAMENTE como
                 Bearer (`/v1/users/self/api-keys`, sem expiração) e NÃO
                 vale como cookie — o caminho do sistema é o Bearer da key
               · `GET  /api/v1/entities?q=&pageSize=` → envelope
                 `{page, pageSize, total, items[EntitySummary], totalPrice}`
               · `POST /api/v1/entities` → 201 (`EntityCreate`: name*,
                 quantity, description, entityTypeId, tagIds)
               · `GET/PUT/PATCH/DELETE /api/v1/entities/{id}` — **PATCH é
                 parcial de verdade** (só entityTypeId/parentId/quantity/
                 tagIds); **PUT exige `name` e substitui o objeto** (o
                 resto vira zero) — por isso notas/descrição/preço passam
                 por GET + merge + PUT completo
               · `GET/POST /api/v1/entity-types` (tipos; o seed cria
                 "Location") · `GET/POST /api/v1/tags`
               · `GET  /api/v1/groups/statistics` → totais do grupo
             Erros da API vêm como `{"error": "..."}`.
           - **Sistema usa** (critério do dono): com as actions
             `homebox_status/busca/listar/detalhar/criar/atualizar` o
             assistente responde *"o que você tem"*, cadastra peça nova
             na hora e sugere montagens listando peças em mãos × peças
             faltantes. Tipos e tags inexistentes são **criados sob
             declaração** (`tipo_criado`/`tag_criada` na resposta) —
             cadastro sem fricção, nunca silencioso.
           - Erros honestos e tipados (`homebox_indisponivel`,
             `homebox_timeout`, `homebox_falhou`, `homebox_nao_autenticado`,
             `homebox_nao_encontrado`, `homebox_parametro_invalido`,
             `homebox_resposta_invalida`).
           - **Lazy por desenho**: `client_padrao()` fábrica cacheada
             (`OD_HOMEB_URL` + `HBOX_API_KEY` no `.env`) — ferramenta
             fora do ar degrada a ação, nunca o boot do od-core.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - docker/tools-compose.yaml (ghcr.io/sysadminsmedia/homebox:0.26.2,
    porta 127.0.0.1:8470 → 7745, bind /data com homebox.db preservado)
  - /swagger/doc.json do container vivo + routes.go da tag v0.26.2
    (árvore de rotas: /entities é o inventário — NÃO /items)
  - tools/actions/actions.py (actions homebox_*)

Decisões registradas (ver CHANGELOG):
  - API key estática (Bearer) em vez de login por senha: sem expiração,
    sem fluxo de refresh; a senha da conta vive no `.env`/cofre só para
    administração (bootstrap)
  - PUT completo (GET+merge) para campos fora do PATCH: o PUT do fork
    substitui o objeto — mandar só o campo mudado apagaria os outros
  - Tipo/tag inexistentes são criados com declaração na resposta
    (cadastro do dono é o uso central — fricção aqui seria contra o
    propósito), com `criar_tipo=False`/`criar_tag=False` para recusar
  - Sem exclusão de nada: nenhuma operação de DELETE é exposta em action
    (mesma régua do dono: nada apagado)

Código associado: integrations/homebox.py (este arquivo)
"""

from __future__ import annotations

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

log = get_logger("omega.integrations.homebox")

URL_PADRAO = "http://127.0.0.1:8470"
TIMEOUT_PADRAO_S = 20.0
LIMITE_MAXIMO_BYTES = 4 * 1024 * 1024

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

class HomeboxError(Exception):
    """Erro tipado do Homebox: código estável + mensagem honesta."""

    def __init__(self, codigo: str, mensagem: str) -> None:
        super().__init__(mensagem)
        self.codigo = codigo
        self.mensagem = mensagem


def _erro_rede(exc: BaseException, url: str, timeout_s: float) -> HomeboxError:
    """Falha de rede/tempo → erro tipado honesto."""
    causa = getattr(exc, "reason", exc)
    if isinstance(exc, (socket.timeout, TimeoutError)) or isinstance(
        causa, (socket.timeout, TimeoutError)
    ):
        return HomeboxError(
            "homebox_timeout",
            f"Homebox não respondeu em {timeout_s:.0f}s ({url}).",
        )
    return HomeboxError(
        "homebox_indisponivel",
        f"Homebox inacessível em {url}: {causa}",
    )


def _transporte(
    url: str,
    *,
    metodo: str = "GET",
    headers: Optional[dict[str, str]] = None,
    corpo: Optional[bytes] = None,
    timeout_s: float,
) -> tuple[int, dict[str, str], bytes]:
    """urllib real → (status, headers, corpo). HTTPError É uma resposta."""
    req = urllib.request.Request(url, data=corpo, method=metodo, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return int(resp.status), dict(resp.headers), resp.read(LIMITE_MAXIMO_BYTES)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read()
        except Exception:  # pragma: no cover - corpo ilegível é raro
            body = b""
        cabecalhos: dict[str, str] = {}
        try:
            cabecalhos = dict(exc.headers) if exc.headers else {}
        except Exception:  # pragma: no cover
            pass
        return int(exc.code), cabecalhos, body
    except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as exc:
        raise _erro_rede(exc, url, timeout_s) from None


def _limpar_texto(bruto: str) -> str:
    """Colapsa espaço simples (nomes/descrições de uma linha)."""
    return " ".join(str(bruto or "").split())


# ---------------------------------------------------------------------------
# Mapeamento das respostas (EntitySummary 17 campos / EntityOut 34)
# ---------------------------------------------------------------------------

def _resumo(bruto: dict[str, Any]) -> dict[str, Any]:
    """EntitySummary → resumo enxuto e honesto para o assistente."""
    tipo = bruto.get("entityType") or {}
    tags = [t.get("name", "") for t in (bruto.get("tags") or []) if t.get("name")]
    return {
        "id": bruto.get("id", ""),
        "nome": bruto.get("name", ""),
        "quantidade": bruto.get("quantity", 0),
        "tipo": tipo.get("name", "") if isinstance(tipo, dict) else str(tipo or ""),
        "descricao": _limpar_texto(bruto.get("description", "")),
        "tags": tags,
        "preco": bruto.get("purchasePrice", 0) or 0,
        "arquivado": bool(bruto.get("archived")),
    }


def _detalhe(bruto: dict[str, Any]) -> dict[str, Any]:
    """EntityOut completo → campos que importam (peça + garantia/compra)."""
    r = _resumo(bruto)
    parent = bruto.get("parent") or {}
    r.update({
        "notas": _limpar_texto(bruto.get("notes", "")),
        "fabricante": _limpar_texto(bruto.get("manufacturer", "")),
        "modelo": _limpar_texto(bruto.get("modelNumber", "")),
        "serie": _limpar_texto(bruto.get("serialNumber", "")),
        "local": parent.get("name", "") if isinstance(parent, dict) else str(parent or ""),
        "compra_data": str(bruto.get("purchaseDate", "") or ""),
        "compra_origem": _limpar_texto(bruto.get("purchaseFrom", "")),
        "garantia_vitalicia": bool(bruto.get("lifetimeWarranty")),
        "garantia_detalhes": _limpar_texto(bruto.get("warrantyDetails", "")),
        "criado_em": str(bruto.get("createdAt", "") or ""),
    })
    return r


def _mensagem_erro(corpo: bytes) -> str:
    """Extrai {"error": "..."} do corpo da API (formato do fork)."""
    try:
        dados = json.loads(corpo.decode("utf-8", errors="replace"))
        if isinstance(dados, dict):
            return str(dados.get("error") or dados.get("message") or dados)[:200]
    except (json.JSONDecodeError, AttributeError):
        pass
    return _limpar_texto(corpo.decode("utf-8", errors="replace"))[:200]


_RE_UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _valida_uuid(id_entidade: str) -> str:
    """id vazio/fora de UUID → erro honesto ANTES da chamada.

    (Apurado ao vivo em 17/10: o fork valida a rota com UUID — id torto
    devolve HTTP 400 'invalid route key: id', não 404. Validar aqui dá
    mensagem acionável: use o id de homebox_busca.)
    """
    valor = str(id_entidade or "").strip()
    if not valor:
        raise HomeboxError("homebox_parametro_invalido", "id não pode ser vazio.")
    if not _RE_UUID.match(valor):
        raise HomeboxError(
            "homebox_parametro_invalido",
            f"id '{valor}' não é um UUID válido — use o id devolvido "
            "por homebox_busca.",
        )
    return valor


# ---------------------------------------------------------------------------
# Cliente
# ---------------------------------------------------------------------------

class HomeboxClient:
    """Cliente do Homebox — inventário do dono via API key (Bearer).

    Attributes:
        base_url:  URL base do homebox (default local).
        api_key:   Chave estática de longa duração (usuário do sistema).
    """

    def __init__(
        self,
        base_url: str = URL_PADRAO,
        *,
        api_key: str = "",
        timeout_s: float = TIMEOUT_PADRAO_S,
        transporte: Optional[Callable[..., tuple[int, dict[str, str], bytes]]] = None,
    ) -> None:
        self.base_url = (base_url or URL_PADRAO).rstrip("/")
        self.api_key = api_key or ""
        self.timeout_s = timeout_s
        self._transporte = transporte or _transporte

    # -- transporte com mapeamento de erro -------------------------------

    def _chamada(
        self,
        caminho: str,
        *,
        metodo: str = "GET",
        payload: Optional[dict[str, Any]] = None,
        autenticado: bool = True,
        timeout_s: Optional[float] = None,
    ) -> tuple[int, Any]:
        url = f"{self.base_url}{caminho}"
        tempo = timeout_s or self.timeout_s
        cabec = {"Content-Type": "application/json"}
        if autenticado:
            if not self.api_key:
                raise HomeboxError(
                    "homebox_nao_autenticado",
                    "HBOX_API_KEY ausente — rode o bootstrap da conta do "
                    "sistema (registro + api-keys) antes de usar.",
                )
            cabec["Authorization"] = f"Bearer {self.api_key}"
        corpo = json.dumps(payload).encode() if payload is not None else None
        try:
            status, _headers, body = self._transporte(
                url, metodo=metodo, headers=cabec, corpo=corpo, timeout_s=tempo
            )
        except HomeboxError:
            raise
        except (
            urllib.error.URLError,
            socket.timeout,
            ConnectionError,
            OSError,
        ) as exc:
            # Transporte injetado (testes/terceiros) sem mapeamento próprio.
            raise _erro_rede(exc, url, tempo) from None

        if status in (401, 403):
            raise HomeboxError(
                "homebox_nao_autenticado",
                f"Homebox recusou a credencial (HTTP {status}) — HBOX_API_KEY "
                "inválida/expirada? Crie outra em /users/self/api-keys.",
            )
        if status == 404:
            # 404 é honesto por definição: recurso não existe (qualquer método)
            raise HomeboxError(
                "homebox_nao_encontrado",
                f"{caminho}: não encontrado (404) — {_mensagem_erro(body)}",
            )
        if not (200 <= status < 300):
            raise HomeboxError(
                "homebox_falhou", f"{caminho}: HTTP {status} — {_mensagem_erro(body)}"
            )
        if not body:
            return status, {}
        try:
            return status, json.loads(body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            raise HomeboxError(
                "homebox_resposta_invalida",
                f"{caminho} devolveu corpo não-JSON ({len(body)} bytes).",
            ) from None

    # -- catálogo auxiliar (tipos e tags) --------------------------------

    def _tipos(self) -> list[dict[str, Any]]:
        _s, dados = self._chamada("/api/v1/entity-types")
        return dados if isinstance(dados, list) else []

    def _tags(self) -> list[dict[str, Any]]:
        _s, dados = self._chamada("/api/v1/tags")
        return dados if isinstance(dados, list) else []

    def _tipo_id(self, nome: str, *, criar: bool = True) -> tuple[str, bool]:
        """Nome do tipo → id; cria se faltar (declarado na resposta)."""
        alvo = _limpar_texto(nome).lower()
        for t in self._tipos():
            if str(t.get("name", "")).lower() == alvo:
                return str(t.get("id", "")), False
        if not criar:
            existentes = [t.get("name", "") for t in self._tipos()]
            raise HomeboxError(
                "homebox_parametro_invalido",
                f"tipo '{nome}' não existe (criar_tipo=False). Tipos: "
                f"{existentes}.",
            )
        s, novo = self._chamada(
            "/api/v1/entity-types",
            metodo="POST",
            payload={"name": _limpar_texto(nome), "isLocation": False},
        )
        if s != 201 or not novo.get("id"):
            raise HomeboxError(
                "homebox_falhou", f"criação de tipo '{nome}' não confirmada."
            )
        return str(novo["id"]), True

    def _tag_ids(self, nomes: str, *, criar: bool = True) -> tuple[list[str], list[str]]:
        """Lista "a, b" de tags → (ids, tags_criadas)."""
        pedidas = [t.strip() for t in str(nomes or "").split(",") if t.strip()]
        if not pedidas:
            return [], []
        existentes = {str(t.get("name", "")).lower(): str(t.get("id", "")) for t in self._tags()}
        ids: list[str] = []
        criadas: list[str] = []
        for nome in pedidas:
            achado = existentes.get(nome.lower())
            if achado:
                ids.append(achado)
                continue
            if not criar:
                raise HomeboxError(
                    "homebox_parametro_invalido",
                    f"tag '{nome}' não existe (criar_tag=False).",
                )
            s, nova = self._chamada(
                "/api/v1/tags", metodo="POST", payload={"name": nome}
            )
            if s != 201 or not nova.get("id"):
                raise HomeboxError("homebox_falhou", f"criação de tag '{nome}' não confirmada.")
            ids.append(str(nova["id"]))
            criadas.append(nome)
        return ids, criadas

    def _entao_put(self, entidade: dict[str, Any], mudancas: dict[str, Any]) -> dict[str, Any]:
        """GET + merge + PUT completo (o PUT substitui o objeto — zero apaga).

        Campos fora do PATCH (notes/description/purchasePrice/...) exigem
        o PUT com TODOS os campos atuais — mandar só o campo mudado
        zeraria o resto (regra apurada no swagger do fork). Opcionais só
        entram quando PRESENTES: string vazia em campo UUID/data quebra o
        fork (apurado ao vivo em 17/10: parentId="" → HTTP 500).
        """
        atual: dict[str, Any] = entidade
        if not atual.get("id"):
            raise HomeboxError("homebox_parametro_invalido", "entidade sem id.")
        if "name" not in atual:
            _s, atual = self._chamada(f"/api/v1/entities/{atual['id']}")
        payload: dict[str, Any] = {
            "name": str(atual.get("name") or ""),
            "quantity": int(atual.get("quantity") or 0),
            "description": str(atual.get("description") or ""),
            "notes": str(atual.get("notes") or ""),
        }
        tipo = atual.get("entityType")
        id_tipo = (
            str(tipo.get("id") or "")
            if isinstance(tipo, dict)
            else str(atual.get("entityTypeId") or "")
        )
        if id_tipo:
            payload["entityTypeId"] = id_tipo
        parent = atual.get("parent")
        if isinstance(parent, dict) and parent.get("id"):
            payload["parentId"] = str(parent["id"])
        tag_ids = [str(t.get("id")) for t in (atual.get("tags") or []) if t.get("id")]
        if tag_ids:
            payload["tagIds"] = tag_ids
        if atual.get("purchasePrice"):
            payload["purchasePrice"] = float(atual["purchasePrice"])
        for campo in ("manufacturer", "modelNumber", "serialNumber", "purchaseFrom"):
            valor = str(atual.get(campo) or "")
            if valor:
                payload[campo] = valor
        data_compra = str(atual.get("purchaseDate") or "")
        if data_compra:
            payload["purchaseDate"] = data_compra
        if atual.get("archived"):
            payload["archived"] = True
        if atual.get("insured"):
            payload["insured"] = True
        payload.update({k: v for k, v in mudancas.items() if v is not None})
        _s, salvo = self._chamada(
            f"/api/v1/entities/{atual['id']}", metodo="PUT", payload=payload
        )
        return salvo if isinstance(salvo, dict) else atual

    # -- operações --------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Saudação do inventário: versão + totais do grupo."""
        _s, info = self._chamada("/api/v1/status", autenticado=False)
        _s, stats = self._chamada("/api/v1/groups/statistics")
        return {
            "versao": str((info.get("build") or {}).get("version", "?")),
            "saudavel": bool(info.get("health")),
            "total_itens": stats.get("totalItems", 0),
            "total_locais": stats.get("totalLocations", 0),
            "total_tags": stats.get("totalTags", 0),
            "total_preco": stats.get("totalItemPrice", 0),
            "usuarios": stats.get("totalUsers", 0),
            "acessivel": True,
        }

    def buscar(self, query: str, quantidade: int = 10) -> dict[str, Any]:
        """Busca textual no inventário (q do Homebox) → resumos."""
        query = _limpar_texto(query)
        if not query:
            raise HomeboxError("homebox_parametro_invalido", "query não pode ser vazia.")
        quantidade = max(1, min(int(quantidade or 10), 100))
        consulta = urllib.parse.urlencode({"q": query, "pageSize": quantidade})
        _s, dados = self._chamada(f"/api/v1/entities?{consulta}")
        itens = [_resumo(i) for i in (dados.get("items") or [])]
        return {"query": query, "total": dados.get("total", len(itens)), "itens": itens}

    def listar(self, quantidade: int = 25, tags: str = "") -> dict[str, Any]:
        """Lista inventário (opcional por tags nominais) → resumos."""
        quantidade = max(1, min(int(quantidade or 25), 100))
        params: dict[str, Any] = {"pageSize": quantidade}
        if _limpar_texto(tags):
            # filtro de listagem NÃO cria tag (criar=False = honestidade)
            ids, criadas = self._tag_ids(tags, criar=False)
            if not ids:
                raise HomeboxError(
                    "homebox_parametro_invalido", f"nenhuma tag conhecida em '{tags}'."
                )
            params["tags"] = ",".join(ids)
        else:
            criadas = []
        _s, dados = self._chamada(f"/api/v1/entities?{urllib.parse.urlencode(params)}")
        itens = [_resumo(i) for i in (dados.get("items") or [])]
        return {
            "total": dados.get("total", len(itens)),
            "itens": itens,
            "tags_criadas": criadas,
        }

    def detalhar(self, id_entidade: str) -> dict[str, Any]:
        """Detalhe de UMA peça (compra, garantia, notas, série...)."""
        id_entidade = _valida_uuid(id_entidade)
        rota = f"/api/v1/entities/{urllib.parse.quote(id_entidade)}"
        try:
            _s, dados = self._chamada(rota)
        except HomeboxError as exc:
            if exc.codigo != "homebox_nao_encontrado":
                raise
            # mesma honestidade, mas com o id e a dica de onde veio
            raise HomeboxError(
                "homebox_nao_encontrado",
                f"entidade '{id_entidade}' não existe (404) — confira o id "
                "devolvido por homebox_busca.",
            ) from None
        if not isinstance(dados, dict) or not dados.get("id"):
            raise HomeboxError(
                "homebox_nao_encontrado",
                f"entidade '{id_entidade}' não existe — resposta sem id.",
            )
        return _detalhe(dados)

    def criar(
        self,
        nome: str,
        *,
        quantidade: int = 1,
        tipo: str = "",
        descricao: str = "",
        notas: str = "",
        tags: str = "",
        preco: Optional[float] = None,
        criar_tipo: bool = True,
        criar_tag: bool = True,
    ) -> dict[str, Any]:
        """Cadastra UMA peça (tipo/tags inexistentes são criados e declarados)."""
        nome = _limpar_texto(nome)
        if not nome:
            raise HomeboxError("homebox_parametro_invalido", "nome não pode ser vazio.")
        payload: dict[str, Any] = {
            "name": nome,
            "quantity": max(0, int(quantidade or 0)),
        }
        tipo_criado = False
        if _limpar_texto(tipo):
            payload["entityTypeId"], tipo_criado = self._tipo_id(tipo, criar=criar_tipo)
        tag_ids: list[str] = []
        tags_criadas: list[str] = []
        if _limpar_texto(tags):
            tag_ids, tags_criadas = self._tag_ids(tags, criar=criar_tag)
            payload["tagIds"] = tag_ids
        if _limpar_texto(descricao):
            payload["description"] = _limpar_texto(descricao)
        s, ent = self._chamada("/api/v1/entities", metodo="POST", payload=payload)
        if s != 201 or not isinstance(ent, dict) or not ent.get("id"):
            raise HomeboxError("homebox_falhou", "criação não confirmada (esperado 201).")
        # notas/preço não existem no EntityCreate — completam via PUT cheio
        if _limpar_texto(notas) or preco is not None:
            mudancas: dict[str, Any] = {}
            if _limpar_texto(notas):
                mudancas["notes"] = _limpar_texto(notas)
            if preco is not None:
                mudancas["purchasePrice"] = float(preco)
            ent = self._entao_put(ent, mudancas)
        r = _detalhe(ent)
        r.update({
            "tipo_criado": tipo_criado,
            "tags_criadas": tags_criadas,
        })
        return r

    def atualizar(
        self,
        id_entidade: str,
        *,
        quantidade: Optional[int] = None,
        notas: Optional[str] = None,
        descricao: Optional[str] = None,
        preco: Optional[float] = None,
    ) -> dict[str, Any]:
        """Atualiza UMA peça: quantidade pura → PATCH; o resto → PUT cheio."""
        id_entidade = _valida_uuid(id_entidade)
        mudancas: dict[str, Any] = {}
        if quantidade is not None:
            mudancas["quantity"] = max(0, int(quantidade))
        if notas is not None:
            mudancas["notes"] = _limpar_texto(notas)
        if descricao is not None:
            mudancas["description"] = _limpar_texto(descricao)
        if preco is not None:
            mudancas["purchasePrice"] = float(preco)
        if not mudancas:
            raise HomeboxError(
                "homebox_parametro_invalido",
                "informe ao menos um campo (quantidade/notas/descricao/preco).",
            )
        rota = f"/api/v1/entities/{urllib.parse.quote(id_entidade)}"
        if set(mudancas) == {"quantity"}:
            # PATCH parcial de verdade (só 5 campos aceitos — quantity é um deles)
            _s, ent = self._chamada(rota, metodo="PATCH", payload=mudancas)
        else:
            _s, atual = self._chamada(rota)
            ent = self._entao_put(atual, mudancas)
        return _detalhe(ent if isinstance(ent, dict) else {})


# ---------------------------------------------------------------------------
# Fábrica cacheada (uma instância por processo — lazy, nunca no boot)
# ---------------------------------------------------------------------------

_CLIENTE: Optional[HomeboxClient] = None


def client_padrao() -> HomeboxClient:
    """Cliente do Homebox (OD_HOMEB_URL + HBOX_API_KEY do `.env`)."""
    global _CLIENTE
    if _CLIENTE is None:
        url = _env("OD_HOMEB_URL", URL_PADRAO)
        chave = _env("HBOX_API_KEY", "")
        _CLIENTE = HomeboxClient(url, api_key=chave)
        log.info("Homebox configurado", url=url, tem_chave=bool(chave))
    return _CLIENTE


def resetar_cliente() -> None:
    """Esquece a instância cacheada (testes / troca de configuração)."""
    global _CLIENTE
    _CLIENTE = None
