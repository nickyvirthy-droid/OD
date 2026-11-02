#!/usr/bin/env python3
"""
OMEGA DRAKON • MCP SERVER
Módulo: runtime/mcp_od.py
Descrição: Expõe o catálogo do OD (ActionRegistry — 116 actions) via
           Model Context Protocol (stdio JSON-RPC 2.0) para clientes
           desktop externos (Claude Desktop, Cursor etc.). Idea do parking
           lot do dono (21/10: "MCP Server — expor actions/ferramentas do
           OD via Model Context Protocol"), entregue 01/11.

Protocolo (MCP 2024-11-05, stdio = newline-delimited JSON-RPC):
   initialize          → capabilities {tools:{}} + serverInfo
   notifications/initialized → sem resposta (notificação)
   tools/list           → todas as actions ativas com inputSchema
   tools/call           → ActionRegistry.execute(role="admin")
   ping                 → {}

Segurança (declarada, não improvisada):
   - SEM rede: só stdio (o processo é iniciado pelo cliente local — nada
     escuta em porta; a regra 7 não é tocada).
   - role="admin" porque o servidor nasce NA MÁQUINA do dono sob comando
     dele (stdio = o cliente local é o próprio dono); o gate de permissão
     do Security Layer continua valendo action a action (permission=nome).
   - .env do repo é carregado sem sobrescrever env já existente (as
     actions leem segredos de lá, como no od-core).

Env:
   OD_MCP_NOME / OD_MCP_VERSAO  identificação no serverInfo
   OD_MCP_ENV                   caminho do .env (padrão <repo>/.env)

Uso (no cliente MCP do dono):
   command: /home/alex/OmegaDrakon/.venv/bin/python
   args:    ["/home/alex/OmegaDrakon/runtime/mcp_od.py"]
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parent.parent
# Script avulso: o diretório do arquivo vira sys.path[0]; o repo root
# precisa estar no caminho para `tools.*`/`core.*` importarem (mesma
# solução do tools/monitor/vigia_rich.py).
sys.path.insert(0, str(REPO))

PROTOCOLO = "2024-11-05"
NOME = os.environ.get("OD_MCP_NOME", "omega-drakon")
VERSAO = os.environ.get("OD_MCP_VERSAO", "1.44.0")

# Mapa tipo-da-casa → JSON Schema (o schema do OD usa "str"/"int"/...)
_TIPOS = {
    "str": "string", "string": "string",
    "int": "integer", "integer": "integer",
    "float": "number", "number": "number",
    "bool": "boolean", "boolean": "boolean",
    "list": "array", "array": "array",
    "dict": "object", "object": "object",
}


def carregar_env(caminho: Optional[Path] = None) -> None:
    """Carrega o .env do repo para o ambiente (sem sobrescrever o que já
    existe — o cliente MCP pode trazer env próprio; mesmo padrão do od-core
    via EnvironmentFile)."""
    alvo = caminho or Path(os.environ.get("OD_MCP_ENV", str(REPO / ".env")))
    if not alvo.exists():
        return
    try:
        for linha in alvo.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            chave, _, valor = linha.partition("=")
            chave = chave.strip()
            if chave and chave not in os.environ:
                os.environ[chave] = valor
    except OSError:  # env parcial é melhor que boot quebrado
        pass


def params_para_json_schema(params: dict[str, Any]) -> dict[str, Any]:
    """Converte o schema da casa ({required, properties: {type: "str"}})
    em JSON Schema (draft-07) para o inputSchema do MCP."""
    props: dict[str, Any] = {}
    for nome, spec in (params.get("properties") or {}).items():
        spec = spec if isinstance(spec, dict) else {}
        tipo_casa = str(spec.get("type", "string")).lower()
        entrada: dict[str, Any] = {"type": _TIPOS.get(tipo_casa, "string")}
        if "default" in spec:
            entrada["default"] = spec["default"]
        if spec.get("description"):
            entrada["description"] = str(spec["description"])
        props[nome] = entrada
    schema: dict[str, Any] = {"type": "object", "properties": props}
    if params.get("required"):
        schema["required"] = [str(r) for r in params["required"]]
    return schema


def ferramentas_do_registry(registry: Any) -> list[dict[str, Any]]:
    """Catálogo do registry → lista tools do MCP (só ativas)."""
    saida: list[dict[str, Any]] = []
    for acao in registry.list_actions():
        if not acao.get("active", True):
            continue
        nome = str(acao["name"])
        desc = str(acao.get("description") or nome)
        if acao.get("category"):
            desc = f"[{acao['category']}] {desc}"
        saida.append({
            "name": nome,
            "description": desc,
            "inputSchema": params_para_json_schema(acao.get("params") or {}),
        })
    return saida


def _resposta(msg: dict[str, Any], resultado: Any) -> dict[str, Any]:
    resp: dict[str, Any] = {
        "jsonrpc": "2.0", "id": msg.get("id"),
        "result": resultado,
    }
    return resp


def _erro(msg: dict[str, Any], codigo: int, texto: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg.get("id"),
            "error": {"code": codigo, "message": texto}}


def tratar_mensagem(
    msg: dict[str, Any],
    registry: Any,
    estado: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Processa UM JSON-RPC e devolve a resposta (None = notificação).

    Função pura de protocolo — testada sem stdin/stdout (regra da casa:
    prova no estado, não no teclado).
    """
    metodo = msg.get("method")
    if metodo == "initialize":
        estado["inicializado"] = True
        cliente = (msg.get("params") or {}).get("protocolVersion") or PROTOCOLO
        return _resposta(msg, {
            "protocolVersion": PROTOCOLO if cliente == PROTOCOLO else cliente,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": NOME, "version": VERSAO},
            "instructions": (
                "Catálogo OmegaDrakon: as "
                f"{len(registry.list_actions())} actions do OD executadas "
                "localmente (stdio). Permissão = gate do próprio OD."
            ),
        })
    if metodo == "notifications/initialized":
        return None  # notificação: sem resposta
    if metodo == "ping":
        return _resposta(msg, {})
    if metodo == "tools/list":
        return _resposta(msg, {"tools": ferramentas_do_registry(registry)})
    if metodo == "tools/call":
        params = msg.get("params") or {}
        nome = str(params.get("name") or "")
        argumentos = params.get("arguments") or {}
        if not registry.has(nome):
            # erro do PROTOCOLO (o cliente mostra) — não executa nada
            return _erro(msg, -32602, f"Ferramenta desconhecida: {nome}")
        try:
            resultado = asyncio.run(registry.execute(
                nome, params=dict(argumentos),
                role="admin", session_id="mcp",
            ))
        except Exception as exc:  # handler explodiu → honesto, sem traceback
            return _resposta(msg, {
                "content": [{"type": "text",
                             "text": f"{type(exc).__name__}: {exc}"[:2000]}],
                "isError": True,
            })
        d = resultado.to_dict()
        texto = json.dumps(
            {"status": d["status"], "data": d.get("data"),
             "error": d.get("error") or None, "errors": d.get("errors") or []},
            ensure_ascii=False, default=str)
        return _resposta(msg, {
            "content": [{"type": "text", "text": texto}],
            "isError": d["status"] != "ok",
        })
    if metodo:
        return _erro(msg, -32601, f"Método não suportado: {metodo}")
    return None  # resposta/eco sem method → ignora


def principal(entrada: Any = None, saida: Any = None) -> int:
    """Loop stdio: uma linha JSON-RPC por linha de saída. Logs no STDERR
    (stdout é o protocolo — nunca poluir)."""
    entrada = entrada or sys.stdin
    saida = saida or sys.stdout  # captura ANTES do redirect: o protocolo
    # (JSON-RPC) sai sempre pelo stdout REAL; os logs do logger da casa
    # escrevem em sys.stdout, então TUDO que roda aqui vai para o stderr
    # — uma linha de log no stdout quebraria o cliente MCP (newline = msg).
    carregar_env()
    with contextlib.redirect_stdout(sys.stderr):
        # import lazy: só registra as actions no boot de verdade (e fora do
        # caminho de import dos testes de protocolo)
        from tools.actions import build_registry
        registry = build_registry()
    estado: dict[str, Any] = {"inicializado": False}
    print(f"[MCP] {NOME} v{VERSAO} no ar — "
          f"{len(registry.list_actions())} actions (stdio)", file=sys.stderr)
    with contextlib.redirect_stdout(sys.stderr):
        for linha in entrada:
            linha = linha.strip()
            if not linha:
                continue
            try:
                msg = json.loads(linha)
            except ValueError:
                resp = _erro({"id": None}, -32700, "Parse error")
                saida.write(json.dumps(resp, ensure_ascii=False) + "\n")
                saida.flush()
                continue
            try:
                resp = tratar_mensagem(msg, registry, estado)
            except Exception as exc:  # nunca derrubar o loop por 1 msg
                resp = _erro(msg, -32603, f"Internal error: {exc}"[:300])
            if resp is not None:
                saida.write(json.dumps(resp, ensure_ascii=False,
                                       default=str) + "\n")
                saida.flush()
    return 0


if __name__ == "__main__":
    sys.exit(principal())
