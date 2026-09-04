"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/intents.py
Descrição: FAST PATH de intenções determinísticas (v0.27.5) — responde
           perguntas operacionais SEM LLM, executando actions de leitura
           do catálogo direto no pipeline (antes do cache/LLM) e avaliando
           matemática básica com segurança (ast, sem eval arbitrário).

           Objetivo: perguntas simples do tipo "quantas pessoas estão
           conectadas na rede?", "quanto está usando de memória?", "quanto
           é 2+2*3?" respondem em milissegundos em vez dos ~17s do LLM
           local em CPU.

           Segurança por construção:
             - Só actions de LEITURA (allowlist FASTPATH_ACTIONS) — nenhuma
               action de escrita/destrutiva é executável pelo fast path;
             - Matemática avaliada apenas com nós de expressão numérica
               (BinOp/UnaryOp/Constant numérica) — nada de chamadas,
               atributos, strings ou builtins;
             - Falha/negação em qualquer etapa NUNCA quebra o pipeline —
               devolve None e a mensagem segue para o LLM normalmente.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - core/orchestrator.py (pipeline de 8 etapas — a intenção entra como
    etapa 3.5, entre quick responses e cache)
  - tools/actions/actions.py (catálogo — network_hosts, process_list,
    memory_usage, cpu_info, disk_usage, uptime, system_info)
  - docs/CAPACIDADES.md §4 (análise do ambiente sob pedido)
"""

from __future__ import annotations

import ast
import re
from typing import Any, Optional

__signature__ = "OD // CORE"

# Actions de LEITURA seguras para o fast path (nunca escrita/destrutiva).
FASTPATH_ACTIONS: frozenset[str] = frozenset({
    "network_hosts",   # dispositivos na rede (ARP)
    "process_list",    # processos ativos
    "memory_usage",    # RAM/swap
    "cpu_info",        # núcleos/modelo/load
    "disk_usage",      # disco
    "uptime",          # tempo no ar
    "system_info",     # sistema geral
})

# ---------------------------------------------------------------------------
# Intenções operacionais (PT-BR, determinísticas)
# ---------------------------------------------------------------------------

# Palavras que indicam "pessoas/dispositivos conectados na rede".
_NETWORK_SUBJECTS = (
    "pessoas", "dispositivos", "equipamentos", "computadores", "pcs",
    "maquinas", "máquinas", "hosts", "conectado", "conectados",
    "conectadas", "aparelhos", "celulares",
)
_NETWORK_PLACES = ("rede", "wifi", "wi-fi", "wi fi", "local", "lan")


def _detect_network(text: str) -> Optional[str]:
    """'quantas pessoas estão conectadas na rede?' → network_hosts."""
    low = text.lower()
    if not any(place in low for place in _NETWORK_PLACES):
        return None
    if any(subject in low for subject in _NETWORK_SUBJECTS):
        return "network_hosts"
    return None


def _detect_operational(text: str) -> Optional[str]:
    """Padrões operacionais diretos (processos/memória/cpu/disco/uptime)."""
    low = text.lower()
    # processos
    if re.search(r"(quantos|lista|ver).{0,12}processos", low):
        return "process_list"
    # memória
    if re.search(r"(mem[oó]ria|ram)\b", low) and re.search(r"(us[oa]ndo|uso|consumo|quanta|como est[áa])", low):
        return "memory_usage"
    if re.search(r"quanta\s+(mem[oó]ria|ram)", low):
        return "memory_usage"
    # cpu
    if re.search(r"(uso\s+da\s+cpu|cpu\s+em|quanto\s+.*cpu|processador)", low):
        return "cpu_info"
    # disco
    if re.search(r"(disco|espa[çc]o|armazenamento|hd|ssd)", low) and \
       re.search(r"(us[oa]do|livre|quanto|como est[áa])", low):
        return "disk_usage"
    # uptime
    if re.search(r"(uptime|h[aá] quanto tempo|tempo\s+(de\s+)?(ligado|no ar|atividade))", low):
        return "uptime"
    # sistema
    if re.search(r"(informa[çc][õo]es|info|sobre|dados).{0,12}(do|da|sobre).{0,8}sistema", low) or \
       re.search(r"(qual|o que).{0,12}(sistema|m[aá]quina|servidor).{0,12}(tem|roda|usa)", low):
        return "system_info"
    return None


def detect_action_intent(text: str) -> Optional[tuple[str, dict[str, Any]]]:
    """Detecta uma intenção operacional de LEITURA na mensagem.

    Returns:
        (action_name, params) quando casou uma intenção conhecida, senão
        None (a mensagem segue para cache/LLM normalmente).
    """
    if not text or not text.strip():
        return None
    action = _detect_network(text) or _detect_operational(text)
    if action is None:
        return None
    if action == "disk_usage":
        return action, {"path": "/"}
    return action, {}


# ---------------------------------------------------------------------------
# Matemática básica segura (ast — sem eval arbitrário)
# ---------------------------------------------------------------------------

_MATH_TRIGGER = re.compile(r"quanto\s+(?:é|d[aá]|faz|fica)\s+(.+)", re.IGNORECASE)
_MATH_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd, ast.Load,
)


def safe_math(text: str) -> Optional[str]:
    """Avalia 'quanto é <expressão>' com nós numéricos apenas.

    Returns:
        Resultado formatado (ex: "2+2 = 4") ou None se não casar/for
        inseguro. Nunca executa código arbitrário.
    """
    match = _MATH_TRIGGER.search(text.strip())
    if match is None:
        return None
    expr = match.group(1).strip().rstrip("?.")
    if not expr or len(expr) > 120:
        return None
    expr = (expr.replace("×", "*").replace("x", "*").replace("÷", "/")
            .replace(",", "."))
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(
                node.value, (int, float)
            ):
                return None  # strings etc. fora
        elif not isinstance(node, _MATH_NODES):
            return None  # chamadas/atributos/listas fora
    try:
        value = eval(compile(tree, "<math>", "eval"), {"__builtins__": {}}, {})
    except (ArithmeticError, ValueError, TypeError):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if value.is_integer():
            value = int(value)
        else:
            value = round(value, 4)
    return f"{expr} = {value}"


# ---------------------------------------------------------------------------
# Formatação de resultado (PT-BR, curto)
# ---------------------------------------------------------------------------

def _gb(bytes_value: float) -> str:
    return f"{bytes_value / (1024 ** 3):.1f}"


def format_intent_result(action: str, data: Any) -> Optional[str]:
    """Converte o retorno da action em uma resposta PT-BR curta.

    Returns:
        Texto da resposta, ou None se o resultado não for aproveitável
        (o pipeline então cai para o LLM — nunca responde vazio).
    """
    if not isinstance(data, dict):
        return None
    ok = data.get("ok", True)
    if ok is not True:
        return None  # action degradou — deixa o LLM responder

    if action == "network_hosts":
        hosts = data.get("hosts", [])
        count = data.get("count", len(hosts))
        if count == 0:
            return ("🖧 Nenhum dispositivo vizinho na rede agora (tabela ARP "
                    "vazia — sem tráfego recente de outros aparelhos).")
        lines = [f"🖧 Há {count} dispositivo(s) na rede local:"]
        for host in hosts[:10]:
            lines.append(
                f"  • {host.get('ip')}  ({host.get('mac')} · "
                f"{host.get('interface')} · {host.get('state')})"
            )
        if count > 10:
            lines.append(f"  ... e mais {count - 10}")
        return "\n".join(lines)

    if action == "process_list":
        return f"📊 {data.get('count', 0)} processos ativos no sistema."

    if action == "memory_usage":
        percent = data.get("percent", 0)
        used = _gb(data.get("used", 0))
        total = _gb(data.get("total", 0))
        swap = data.get("swap_percent", 0)
        return (f"🧠 Memória: {percent}% em uso ({used} GB de {total} GB) · "
                f"swap {swap}%")

    if action == "cpu_info":
        model = (data.get("model") or "desconhecido").strip()
        if len(model) > 40:
            model = model[:40] + "…"
        return (f"⚙️ CPU: {data.get('cores', 0)} núcleos · load {data.get('load1', 0)} · "
                f"{model}")

    if action == "disk_usage":
        percent = data.get("percent", 0)
        free = _gb(data.get("free", 0))
        total = _gb(data.get("total", 0))
        path = data.get("path", "/")
        return f"💾 Disco {path}: {percent}% usado · {free} GB livres de {total} GB"

    if action == "uptime":
        days = data.get("days", 0)
        seconds = data.get("seconds", 0)
        return (f"⏱️ Sistema no ar há {days:.1f} dia(s) "
                f"({int(seconds)} s de uptime).")

    if action == "system_info":
        return (f"🖥️ {data.get('system')} {data.get('release')} "
                f"({data.get('node')}) · {data.get('cores')} núcleos · "
                f"Python {data.get('python')}")

    # Fallback genérico: pares chave=valor escalares (sem aninhados).
    parts = [
        f"{key}: {value}" for key, value in data.items()
        if not isinstance(value, (dict, list)) and not key.startswith("_")
    ]
    return "; ".join(parts) if parts else None


__all__ = [
    "FASTPATH_ACTIONS",
    "detect_action_intent",
    "safe_math",
    "format_intent_result",
]