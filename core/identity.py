"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/identity.py
Descrição: resolve o DONO (username da conta) de identificadores legados de
           transporte.

Antes do login de usuários, cada transporte tinha o próprio balde de
histórico/cache: o chat web usava `web`, o streaming `ws_user`, o app manda
`user_id: "app"` fixo (autenticado pela `OD_API_KEY` do servidor) e o bot do
Telegram usa o id numérico do chat. Depois que a identidade passou a sair da
credencial, esses ids ficaram órfãos: o que foi conversado pelo app/bot não
aparece na conta do dono, nem no cache.

`OD_ACCOUNT_ALIASES` (ex.: `app=alex,660518870=alex`) aponta cada id legado
para a conta do dono. O REST (`POST /message`), o WebSocket (frame `auth`) e o
bot do Telegram resolvem o MESMO mapa — a mensagem cai no balde da conta, sem
mudança nenhuma no cliente. Lista vazia (default) = desligado, comportamento
antigo preservado.

O mapa é configuração de operador (env), não vem do cliente: por isso o valor
de destino é devolvido como está (username já canônico), sem repeneirar.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

__signature__ = "OD // CORE"

# Variável de ambiente que carrega o mapa "id_legado=conta,id_legado=conta".
ALIASES_ENV = "OD_ACCOUNT_ALIASES"


def parse_aliases(spec: Any) -> dict[str, str]:
    """Converte ``"app=alex,660518870=alex"`` em ``{"app": "alex", ...}``.

    Entradas vazias ou malformadas (sem ``=``, ou com um dos lados vazio) são
    ignoradas: uma env torta não pode derrubar a resolução de identidade.
    """
    aliases: dict[str, str] = {}
    for parte in str(spec or "").split(","):
        origem, sep, destino = parte.partition("=")
        origem, destino = origem.strip(), destino.strip()
        if sep and origem and destino:
            aliases[origem] = destino
    return aliases


def resolve_account(raw_id: str, aliases: Optional[Mapping[str, str]]) -> str:
    """Devolve a conta do dono para um id legado — ou o próprio id, se não houver alias.

    O casamento ignora maiúsculas/minúsculas no id bruto (o username da conta já
    é canônico no destino). Sem alias (mapa vazio/ausente) devolve o id recebido,
    que é o comportamento anterior à unificação.
    """
    raw = str(raw_id or "").strip()
    if not aliases or not raw:
        return raw
    if raw in aliases:
        return aliases[raw]
    baixo = raw.lower()
    for origem, destino in aliases.items():
        if origem.lower() == baixo:
            return destino
    return raw
