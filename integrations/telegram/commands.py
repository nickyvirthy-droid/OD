"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/telegram/commands.py
Descrição: Camada de comandos do Telegram Bot — os 13 comandos de texto do
           legado Nicky + tratamento de voz (STT) como 14º recurso. Cada
           comando é um handler (bot, ctx) -> texto de resposta; acesso
           admin é controlado pelo bot antes da execução.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - Nicky interfaces/telegram_bot.py (14 comandos)
  - docs/NICKY_LEGACY_ANALYSIS.md §10 (tabela de comandos)
  - ROADMAP_ABSORCAO.md Fase 5, item 5.1
"""

from __future__ import annotations

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
            "rotacionar_key",
            _rotacionar_key,
            "Rotacionar API key",
            admin_only=True,
        ),
    ]
