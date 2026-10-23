"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/security/permissions.py
Descrição: Permission Engine — papéis (roles) mapeados para padrões de ações
           permitidas, com menor privilégio por padrão.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - NV Runtime Security Layer (camada 2: Permission Engine)
  - OMEGADRAKON_SPEC.md §7.2 (Least Privilege)
"""

from __future__ import annotations

__signature__ = "OD // CORE"

import fnmatch
from core.logger import make_audit_nicky
from dataclasses import dataclass, field
from typing import Any, Optional

from core.security.models import ActionRequest, CheckResult

_audit_nicky = make_audit_nicky("omega.core.security.permissions")





# ---------------------------------------------------------------------------
# Defaults — menor privilégio
# ---------------------------------------------------------------------------

# Papéis padrão com permissões mínimas seguras (catálogo tools/ chega na Fase 4)
DEFAULT_ROLE_PERMISSIONS: dict[str, list[str]] = {
    "agent": [
        "system.status",
        "system.health",
        "system.info",
        "filesystem.read",
        "filesystem.list",
        "filesystem.info",
        "filesystem.search",
        "filesystem.exists",
        "memory.*",
        "knowledge.*",
        "config.read",
        "config.get",
    ],
    # Conta de usuário comum: conversa e AÇÕES DE LEITURA sobre a própria
    # máquina/conversa. Nada de escrever, executar serviço ou ação destrutiva —
    # isso é do papel admin (o dono, confirmado pela OD_API_KEY).
    #
    # Os nomes são os das actions reais (tools/actions, com underscore) — os
    # padrões com ponto abaixo ("agent") são a nomenclatura da spec e NÃO casam
    # com o ActionRegistry real; por isso a lista do "user" é explícita.
    # Ficam de fora, de propósito: `system_env` (segredos), `filesystem_read`
    # (ler qualquer arquivo), `database_*`, `network_hosts` (topologia da
    # rede), `ip_address` e `listening_ports` (superfície de rede do servidor
    # — v1.7.0: vazavam para o papel user pela intenção do chat).
    "user": [
        "system_info", "uptime", "datetime", "disk_usage",
        "memory_usage", "cpu_info", "cpu_temp",
        "ha_weather", "ha_lights",  # v1.8.0: leitura do lar (sem ha_summary)
        # Dado PÚBLICO de leitura (API sem chave) — mesma natureza de
        # ha_weather. Conserto 2026-10-13 (pegou o eval da Parte A): o
        # user perguntando clima de cidade/cotação caía em permission
        # denied → o LLM respondia SEM dado (e no dólar, ALUCINOU
        # 'USD 5.478 (USD/CLP)'). As duas actions nasceram para o chat
        # do usuário (v1.12.0/v1.14.0) e esqueceram da lista daqui.
        "weather_city", "exchange_rate",
        # Saúde — referência (Parte C NOMAD, v1.25.0): leitura de curadoria
        # de domínio público (CDC/NIH/NCCIH) + bula FDA (openFDA). NATUREZA
        # DE LEITURA como ha_weather: sem escrita, sem credencial, sem
        # segredo; resposta sempre com disclaimer (SAUDE_AVISO) e nunca
        # inventa (fonte ausente = 'não achei').
        "saude_condicao", "saude_interacoes", "saude_medicamento",
        # Google Workspace SOMENTE LEITURA — decisão explícita do
        # dono (2026-10-02: 'dono + usuário leitura'). Toda a escrita é do
        # admin (2º lote). Sem credencial configurada as actions degradam.
        "google_drive_list", "google_drive_read",
        "google_calendar_events",
        "google_gmail_list", "google_gmail_read", "google_gmail_labels",
        "process_list", "process_info",
        "service_list", "service_status",
        "docker_list", "docker_status", "docker_stats",
        "filesystem_list", "filesystem_info", "filesystem_exists",
        "filesystem_tree", "filesystem_hash", "filesystem_search",
        "git_status", "git_branch", "git_log", "git_diff",
        "action_list", "action_info", "action_schema",
    ],
    # Papel FAMÍLIA (23/10, frente C da fila do dono): a conta comum de
    # casa que pode LIGAR/DESLIGAR aparelhos e luzes, mas nada além disso.
    #
    # É a lista do "user" (leitura) + a ÚNICA ação de escrita do lar:
    # `ha_device_control`. O alvo precisa ser específico e a ação tem a
    # confirmação de 2 passos (120s) já embutida — o mesmo fluxo do dono.
    #
    # Ficam DE PROPOSITO fora do alcance do família:
    #   - toda a escrita Google (drive/calendar/gmail) — é do admin;
    #   - `ha_summary` (raio-x: pessoas, bateria, rede) — leitura mais
    #     ampla que ha_lights, já fora do "user";
    #   - `system_env`, `database_*`, `network_hosts`, `listening_ports`,
    #     `ip_address` — segredo/topologia do servidor (mesmo corte do user).
    # Herda a lista do user POR CÓDIGO (abaixo) para o família nunca
    # esquecer uma leitura nova que o user ganhar — a escrita do lar é a
    # única diferença e é explícita.
    "familia": [
        "ha_device_control",
    ],
    "admin": ["*"],
    "router": ["router.*"],
}

UNKNOWN_ROLE_POLICY = "deny"  # "deny" | "allow" — papéis desconhecidos


# Papéis que HERDAM a lista de outro papel: {filho: pai}. 23/10 (frente C —
# papel FAMÍLIA): o família herda tudo do user (leitura) e soma só a escrita
# do lar. Herança por CÓDIGO, não por cópia manual — uma leitura nova que o
# user ganhar chega ao família sozinha, e a única diferença entre os dois
# papéis continua sendo a lista explícita do filho.
ROLE_HIERARQUIA: dict[str, str] = {
    "familia": "user",
}


def _build_role_permissions() -> dict[str, list[str]]:
    """Copia o DEFAULT_ROLE_PERMISSIONS resolvendo a hierarquia de papéis.

    O filho recebe os padrões do pai (pai primeiro) e depois os seus — a
    ordem importa só para leitura/debug; `is_allowed` aceita qualquer
    correspondência. Papel pai inexistente é ignorado (fail-safe: o filho
    fica só com o que declarou, nunca levanta).
    """
    out: dict[str, list[str]] = {
        role: list(patterns)
        for role, patterns in DEFAULT_ROLE_PERMISSIONS.items()
    }
    for filho, pai in ROLE_HIERARQUIA.items():
        if filho not in out:
            out[filho] = []
        herdados = list(out.get(pai, []))
        # pai primeiro; o que o filho já tinha (e não está no pai) fica no fim
        juntos = herdados + [
            p for p in out[filho] if p not in herdados
        ]
        out[filho] = juntos
    return out


# ---------------------------------------------------------------------------
# PermissionEngine
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class PermissionEngine:
    """Camada 2 — Permission Engine: permissões por papel.

    Cada papel possui um conjunto de padrões fnmatch de ações permitidas.
    O padrão "*" concede acesso total. Papéis desconhecidos são negados
    por padrão (fail-safe).

    Attributes:
        role_permissions: dict role -> lista de padrões de ações.
        unknown_role_policy: "deny" (padrão) ou "allow".
    """

    role_permissions: dict[str, list[str]] = field(
        default_factory=_build_role_permissions
    )
    unknown_role_policy: str = UNKNOWN_ROLE_POLICY

    # -- Regras --------------------------------------------------------------

    def grant(self, role: str, action_pattern: str) -> None:
        """Concede a um papel o padrão de ação (ex: "filesystem.*")."""
        if role not in self.role_permissions:
            self.role_permissions[role] = []
        if action_pattern not in self.role_permissions[role]:
            self.role_permissions[role].append(action_pattern)

    def revoke(self, role: str, action_pattern: str) -> bool:
        """Remove um padrão de ação de um papel. Retorna True se existia."""
        patterns = self.role_permissions.get(role)
        if not patterns or action_pattern not in patterns:
            return False
        patterns.remove(action_pattern)
        return True

    def revoke_role(self, role: str) -> bool:
        """Remove um papel inteiro. Retorna True se existia."""
        return self.role_permissions.pop(role, None) is not None

    def is_allowed(self, role: str, action: str) -> bool:
        """Verifica se um papel pode executar uma ação (sem audit)."""
        patterns = self.role_permissions.get(role)
        if patterns is None:
            return self.unknown_role_policy == "allow"
        for pattern in patterns:
            if fnmatch.fnmatchcase(action, pattern):
                return True
        return False

    def list_roles(self) -> list[str]:
        return sorted(self.role_permissions.keys())

    def permissions_for(self, role: str) -> list[str]:
        return list(self.role_permissions.get(role, []))

    # -- Avaliação -----------------------------------------------------------

    def evaluate(self, request: ActionRequest) -> CheckResult:
        """Avalia se o papel da requisição pode executar a ação."""
        patterns = self.role_permissions.get(request.role)

        if patterns is None:
            denied = self.unknown_role_policy == "deny"
            reason = (
                f"Unknown role '{request.role}' is denied by policy"
                if denied
                else ""
            )
            if denied:
                _audit_nicky(
                    "WARN",
                    "Unknown role denied",
                    role=request.role,
                    action=request.action,
                    request_id=request.request_id,
                )
            return CheckResult(
                layer="permission",
                allowed=not denied,
                reason=reason,
            )

        if self._matches_any(request.action, patterns):
            return CheckResult(layer="permission", allowed=True)

        _audit_nicky(
            "WARN",
            "Permission denied",
            role=request.role,
            action=request.action,
            request_id=request.request_id,
        )
        return CheckResult(
            layer="permission",
            allowed=False,
            reason=f"Role '{request.role}' has no permission for action '{request.action}'",
        )

    # -- Helpers -------------------------------------------------------------

    @staticmethod
    def _matches_any(value: str, patterns: list[str]) -> bool:
        for pattern in patterns:
            if fnmatch.fnmatchcase(value, pattern):
                return True
        return False

    # -- Inspeção ------------------------------------------------------------

    def dump(self) -> dict[str, Any]:
        return {
            "unknown_role_policy": self.unknown_role_policy,
            "roles": {
                role: list(patterns)
                for role, patterns in self.role_permissions.items()
            },
        }