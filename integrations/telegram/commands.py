"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/telegram/commands.py
Descrição: Camada de comandos do Telegram Bot — os 13 comandos de texto do
           legado Nicky + tratamento de voz (STT) como 14º recurso, mais os
           comandos OD /executa (actions do catálogo, v0.27.0) e
           /capacidades (manifesto de capacidades, v0.27.3). Cada comando é
           um handler (bot, ctx) -> texto de resposta; acesso admin é
           controlado pelo bot antes da execução.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nicky interfaces/telegram_bot.py (14 comandos)
  - docs/NICKY_LEGACY_ANALYSIS.md §10 (tabela de comandos)
  - ROADMAP_ABSORCAO.md Fase 5, item 5.1
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Optional

__signature__ = "OD // CORE"

if TYPE_CHECKING:
    from integrations.telegram.bot import TelegramBot

PROFILES = ("auto", "guardian", "regulus", "luma", "vox", "athenae", "nyx")
DASHBOARD_URL = "https://localhost:8765"  # OD Control Bridge (docs/CONTROL_BRIDGE.md)

# 13 comandos de texto (o 14º recurso é voz/STT — ver bot.handle_voice)
LEGACY_COMMAND_NAMES = (
    "start", "help", "perfil", "limpar", "status", "uptime", "stats",
    "dashboard", "historico", "cache", "presenca", "codigo", "rotacionar_key",
)
TG_FEATURES = 14  # 13 comandos + voz (STT)

NIVEL_0_PUBLICO = frozenset({
    # Sistema — leitura apenas
    "system_info", "datetime", "uptime", "cpu_info", "memory_usage",
    "ip_address", "system_hostname", "system_user", "system_groups",
    # Processos — leitura
    "process_list", "process_info",
    # Docker — leitura (se disponível)
    "docker_list", "docker_stats",
    # Serviços — leitura
    "service_list", "service_status",
    # Arquivos — leitura
    "filesystem_search", "filesystem_read", "filesystem_exists",
    "filesystem_info", "filesystem_list", "filesystem_tree",
    "filesystem_hash",
    # Git — leitura
    "git_branch", "git_status", "git_log", "git_diff",
    # Banco — leitura
    "database_tables", "database_schema",
    # Introspecção
    "action_list", "action_info", "action_schema", "action_validate",
})

NIVEL_2_DESTRUTIVO = frozenset({
    # Arquivos — escrita/remoção/alteração
    "filesystem_write", "filesystem_delete", "filesystem_mkdir",
    "filesystem_move", "filesystem_copy", "filesystem_touch",
    "filesystem_archive", "filesystem_extract",
    # Git — escrita/alteração (exceto fetch/pull que são leitura+rede)
    "git_commit", "git_add", "git_checkout", "git_push", "git_pull",
    # Processos — alteração/remoção
    "process_kill",
    # Serviços — controle de logs
    "service_logs",
    # Docker — operação de logs
    "docker_logs",
    # Banco — escrita (queries podem ser SELECT ou INSERT/UPDATE/DELETE)
    "database_query",
})

NIVEL_1_ADMIN = frozenset({
    "service_restart", "docker_ps", "docker_run", "docker_stop",
    "docker_rm", "process_tree", "system_ping",
    "git_fetch",
})

NIVEL_3_CRITICO = frozenset({
    "system_reboot", "system_shutdown",
    "process_kill",  # Remove processo (exige confirmação)
    "filesystem_delete",  # Remove arquivo permanentemente
    "git_push",  # Push para remote (modifica repositório remoto)
    "docker_rm",  # Remove container
})


@dataclass(slots=True)
class CommandContext:
    """Contexto de execução de um comando."""

    command: str
    raw: str
    chat_id: int
    user_id: int
    is_admin: bool
    args: list[str] = field(default_factory=list)

    @property
    def arg_text(self) -> str:
        return " ".join(self.args).strip()


CommandFn = Callable[["TelegramBot", CommandContext], str]


@dataclass(slots=True)
class TelegramCommand:
    """Definição de um comando do bot."""

    name: str
    handler: CommandFn
    description: str = ""
    admin_only: bool = False
    aliases: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "admin_only": self.admin_only,
            "aliases": list(self.aliases),
        }


# ---------------------------------------------------------------------------
# Handlers dos 13 comandos legados
# ---------------------------------------------------------------------------

def _welcome(bot: "TelegramBot", ctx: CommandContext) -> str:
    name = bot.profile_display(ctx.chat_id)
    return (
        f"Olá! Eu sou o *Omega Drakon* — tecnologia que respira.\n\n"
        f"Perfil ativo: *{name}*\n"
        f"Envie uma mensagem para conversar ou use /help para ver os comandos."
    )


def _help(bot: "TelegramBot", ctx: CommandContext) -> str:
    lines = ["*Comandos disponíveis:*"]
    for command in bot.commands:
        if command.admin_only and not ctx.is_admin:
            continue
        lines.append(f"/{command.name} — {command.description}")
    lines.append("🎤 Áudio — transcrição de voz (STT)")
    return "\n".join(lines)


def _perfil(bot: "TelegramBot", ctx: CommandContext) -> str:
    if not ctx.args:
        current = bot.get_profile(ctx.chat_id)
        return (
            f"Perfil atual: *{current}*\n"
            f"Opções: {', '.join(PROFILES)}\n"
            f"Uso: /perfil <nome>"
        )
    name = ctx.args[0].lower()
    if name == "auto" and name not in PROFILES:
        name = "guardian"
    if name not in PROFILES:
        return (
            f"Perfil desconhecido: {name!r}.\n"
            f"Opções: {', '.join(PROFILES)}"
        )
    bot.set_profile(ctx.chat_id, name)
    return f"Perfil alterado para *{name}*."


def _limpar(bot: "TelegramBot", ctx: CommandContext) -> str:
    cleared = bot.clear_chat(ctx.chat_id)
    if cleared is None:
        return "Histórico local limpo (o Orchestrator não está conectado)."
    return cleared


def _status(bot: "TelegramBot", ctx: CommandContext) -> str:
    system = bot.system_status()
    lines = ["*Status do sistema:*"]
    for key, value in system.items():
        lines.append(f"• {key}: {value}")
    return "\n".join(lines)


def _uptime(bot: "TelegramBot", ctx: CommandContext) -> str:
    uptime_s = time.time() - bot.started_at
    hours = int(uptime_s // 3600)
    minutes = int((uptime_s % 3600) // 60)
    metrics = bot.metrics.snapshot()
    return (
        f"*Bot ativo há* {hours}h{minutes:02d}\n"
        f"• Mensagens: {metrics['messages']}\n"
        f"• Comandos: {metrics['commands']}\n"
        f"• Respostas: {metrics['replies']}\n"
        f"• Erros: {metrics['errors']}"
    )


def _stats(bot: "TelegramBot", ctx: CommandContext) -> str:
    metrics = bot.metrics.snapshot()
    orch = bot.orchestrator_metrics()
    lines = [
        f"*Estatísticas do bot* — ativo desde {bot.started_at_text}",
        f"• Mensagens: {metrics['messages']}",
        f"• Comandos: {metrics['commands']}",
        f"• Vozes (STT): {metrics['voices']}",
        f"• Erros: {metrics['errors']}",
    ]
    if orch:
        lines.append(f"• Orchestrator: {orch.get('processed', '?')} processadas")
        lines.append(f"• LLM avg: {orch.get('avg_latency_ms', '?')}ms")
    return "\n".join(lines)


def _dashboard(bot: "TelegramBot", ctx: CommandContext) -> str:
    return f"Dashboard: {DASHBOARD_URL}"


def _historico(bot: "TelegramBot", ctx: CommandContext) -> str:
    limit = 5
    target_id = str(ctx.chat_id)
    if ctx.args:
        first = ctx.args[0]
        if first.startswith("@") or first.isdigit():
            target_id = first.lstrip("@")
        try:
            candidate = int(ctx.args[0])
            if ctx.args[0].isdigit() and len(ctx.args) > 1:
                target_id = ctx.args[0]
        except ValueError:
            pass
        for part in ctx.args:
            if part.isdigit():
                limit = int(part)
    limit = max(1, min(limit, 50))
    lines = bot.history_lines(target_id, limit)
    if lines is None:
        return "Histórico indisponível (nenhum provider conectado)."
    if not lines:
        return f"Nenhuma mensagem no histórico de {target_id}."
    return "\n".join(lines)


def _cache(bot: "TelegramBot", ctx: CommandContext) -> str:
    action = ctx.arg_text.lower()
    if action == "limpar":
        cleared = bot.clear_cache()
        return cleared
    stats = bot.cache_stats()
    if stats is None:
        return "Cache gerenciado pelo Orchestrator — use `/cache limpar`."
    return f"*Cache LLM*\n{stats}"


def _presenca(bot: "TelegramBot", ctx: CommandContext) -> str:
    return (
        "Monitor de presença não conectado — capacidade da Fase 6.2 "
        "(Presence Monitor)."
    )


def _codigo(bot: "TelegramBot", ctx: CommandContext) -> str:
    sub = ctx.arg_text.lower()
    if not sub:
        return (
            "*/codigo* — operações sobre o Coder Engine (agêntico):\n"
            "• `/codigo status` — métricas do Coder\n"
            "• `/codigo arvore` — resumo de arquivos (via status)\n"
            "Uso completo (ler/backups/rollback/patch) será exposto com a "
            "interface de agente da Fase 5/6."
        )
    if sub == "status" or sub == "arvore":
        return bot.coder_status()
    return f"Subcomando desconhecido: {sub!r}. Use `/codigo` para ajuda."


def _rotacionar_key(bot: "TelegramBot", ctx: CommandContext) -> str:
    return (
        "Rotação de API key não executada neste ambiente controlado — "
        "segredos são gerenciados via env vars / configs (spec §7)."
    )


def _capacidades(bot: "TelegramBot", ctx: CommandContext) -> str:
    """Manifesto de capacidades do sistema (core/capabilities.py)."""
    from core.capabilities import render_text
    return render_text()


def _executa_handler(bot: "TelegramBot", ctx: CommandContext) -> str:
    """Handler do comando /executa — executa actions do catálogo.

    Uso:
        /executa system_info                  (executa com params default)
        /executa filesystem_read path=/tmp/x  (executa com params)
        /executa action_list                 (lista todas as actions)

    O parsing de parâmetros suporta:
        key=value     → string
        key=int:123  → inteiro
        key=bool:1   → booleano (1/0, true/false)
        key=123      → tenta int, depois float, depois string

    Níveis de acesso (grau de interferência no sistema):
        - NÍVEL 0 — PÚBLICO: leitura/pesquisa sem risco (system_info,
          datetime, uptime, cpu_info, memory_usage, ip_address, process_list,
          action_list, action_info, action_schema, action_validate, etc.).
        - NÍVEL 1 — ADMIN: ações que afetam sistema/arquivos/serviços/
          docker/git (filesystem_*, service_*, docker_*, git_*, process_kill,
          process_tree, system_ping, etc.) — apenas admins.
        - NÍVEL 2 — DESTRUTIVO: ações que removem/alteram estado (filesystem_delete,
          filesystem_write, git_commit, git_push, process_kill com SIGKILL) —
          admin + confirmação explícita.
    """

    registry = bot.action_registry
    if registry is None:
        return "Action Registry não disponível."

    args = ctx.args
    if not args:
        return (
            "*Uso:* `/executa <nome_action> [params]`\n"
            "\n"
            "*Examples:*\n"
            "`/executa system_info`\n"
            "`/executa filesystem_read path=/tmp/x`\n"
            "`/executa action_list`\n"
            "\n"
            f"*Actions disponíveis:* {registry.metrics.actions} actions "
            "cadastradas.\n"
            "Use `/executa action_list` para ver a lista completa."
        )

    action_name = args[0].lower()

    # action_list é especial: lista todas as actions
    if action_name == "action_list":
        try:
            result = asyncio.run(
                registry.execute("action_list", params={}, role="admin")
            )
            if result.status == "ok":
                actions = result.data.get("actions", [])
                lines = [f"*Actions ({len(actions)}):*"]
                for name in actions[:20]:
                    lines.append(f"  • `{name}`")
                if len(actions) > 20:
                    lines.append(f"  ... e mais {len(actions)-20}")
                return "\n".join(lines)
            return f"Erro: {result.error}"
        except Exception as exc:
            return f"Erro ao listar actions: {type(exc).__name__}: {exc}"

    # Verifica se a action existe
    if not registry.has(action_name):
        all_names = [a.name for a in registry.find()]
        suggestions = [n for n in all_names if action_name in n or n in action_name]
        if suggestions:
            return (
                f"Action desconhecida: `{action_name}`.\n"
                f"Actions similares: {', '.join(suggestions[:5])}"
            )
        return (
            f"Action desconhecida: `{action_name}`.\n"
            f"Use `/executa action_list` para ver as {registry.metrics.actions} actions disponíveis."
        )

    # Classificação de risco e controle de acesso
    nivel = _classificar_risco(action_name)
    if nivel == 0:
        pass  # público — qualquer pessoa pode executar
    elif nivel == 1:
        if not ctx.is_admin:
            return (
                f"⛔ Action `{action_name}` requer privilégios de admin.\n"
                f"Nível 1 — ações restritas (afetam sistema/arquivos/serviços)."
            )
    elif nivel == 2:
        if not ctx.is_admin:
            return (
                f"⛔ Action `{action_name}` requer privilégios de admin.\n"
                f"Nível 2 — ação destrutiva (modifica/remove estado)."
            )
        # Confirmação explícita para ações destrutivas
        # Verifica se 'confirmar' ou 'confirm' está nos args (não apenas no arg_text)
        args_lower = [a.lower() for a in ctx.args]
        if "confirmar" not in args_lower and "confirm" not in args_lower:
            return (
                f"⚠️ Ação `{action_name}` é destrutiva (Nível 2).\n"
                f"Para executar, adicione `confirmar` ou `confirm` nos args.\n"
                f"Ex: `/executa filesystem_delete path=/tmp/x confirmar`"
            )

    # Constrói params a partir dos args restantes
    params = {}
    for arg in args[1:]:
        if "=" not in arg:
            continue
        key, value = arg.split("=", 1)
        params[key] = _parse_param_value(value)

    # Executa a action
    try:
        result = asyncio.run(
            registry.execute(action_name, params=params, role="admin")
        )
        if result.status == "ok":
            data = result.data
            if isinstance(data, dict):
                lines = [f"*Resultado de `{action_name}`:*"]
                for key, value in data.items():
                    if isinstance(value, (dict, list)) and len(str(value)) > 200:
                        lines.append(f"  {key}: <objeto grande, use action_info para detalhes>")
                    else:
                        lines.append(f"  {key}: {value}")
                return "\n".join(lines)
            elif isinstance(data, str):
                return f"*Resultado:* {data}"
            else:
                return f"*Resultado:* {data}"
        elif result.status == "denied":
            return f"⛔ Negado: {result.error}"
        elif result.status == "invalid":
            return f"⚠️ Parâmetros inválidos: {'; '.join(result.errors)}"
        elif result.status == "error":
            return f"❌ Erro: {result.error}"
        else:
            return f"Resultado: status={result.status}, error={result.error}"
    except Exception as exc:
        return f"Erro ao executar: {type(exc).__name__}: {exc}"


def _classificar_risco(action_name: str) -> int:
    """Retorna o nível de risco de uma action (0, 1, ou 2).

    0 = público (leitura/pesquisa),
    1 = admin (afeta sistema/arquivos/serviços),
    2 = destrutivo (remove/altera estado critical).
    """
    if action_name in NIVEL_0_PUBLICO:
        return 0
    if action_name in NIVEL_2_DESTRUTIVO:
        return 2
    if action_name in NIVEL_1_ADMIN:
        return 1
    # Por padrão, assume nível 0 (público) se não categorizado
    return 0


def _parse_param_value(value: str) -> Any:
    """Parseia um valor de parâmetro: bool, int, float, ou string."""
    # Bool
    if value.lower() in ("true", "1", "yes", "t", "y"):
        return True
    if value.lower() in ("false", "0", "no", "f", "n"):
        return False
    # Int
    try:
        return int(value)
    except ValueError:
        pass
    # Float
    try:
        return float(value)
    except ValueError:
        pass
    # Remove aspas se presente
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value


# ---------------------------------------------------------------------------
# Catálogo padrão
# ---------------------------------------------------------------------------

def build_default_commands() -> list[TelegramCommand]:
    """Constrói os 13 comandos de texto do legado Nicky."""
    return [
        TelegramCommand("start", _welcome, "Boas-vindas"),
        TelegramCommand("help", _help, "Lista de comandos", aliases=("ajuda",)),
        TelegramCommand(
            "perfil", _perfil, "Trocar/listar perfis (auto/guardian/...)"
        ),
        TelegramCommand("limpar", _limpar, "Limpar histórico do chat"),
        TelegramCommand("status", _status, "Status do sistema", admin_only=True),
        TelegramCommand(
            "uptime", _uptime, "Tempo ativo + métricas", admin_only=True
        ),
        TelegramCommand("stats", _stats, "Estatísticas detalhadas", admin_only=True),
        TelegramCommand(
            "dashboard", _dashboard, "Link do dashboard", admin_only=True
        ),
        TelegramCommand(
            "historico", _historico, "Últimas mensagens [@ID] [N]", admin_only=True
        ),
        TelegramCommand("cache", _cache, "Gerenciar cache LLM", admin_only=True),
        TelegramCommand(
            "presenca", _presenca, "Detecções de presença do dia", admin_only=True
        ),
        TelegramCommand(
            "codigo", _codigo, "Operações do Coder Engine", admin_only=True
        ),
        TelegramCommand(
            "capacidades",
            _capacidades,
            "Capacidades do sistema (manifesto)",
            admin_only=True,
        ),
        TelegramCommand(
            "rotacionar_key",
            _rotacionar_key,
            "Rotacionar API key",
            admin_only=True,
        ),
    ]
