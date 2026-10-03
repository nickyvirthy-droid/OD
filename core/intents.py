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
    "network_hosts",       # dispositivos na rede (ARP)
    "process_list",        # processos ativos
    "memory_usage",        # RAM/swap
    "cpu_info",            # núcleos/modelo/load
    "cpu_temp",            # temperatura do servidor (zones térmicos)
    "disk_usage",          # disco
    "uptime",              # tempo no ar
    "system_info",         # sistema geral
    "ip_address",          # endereços IP do host
    "listening_ports",     # portas abertas/escutando
    # Google Workspace — SOMENTE LEITURA (Drive/Agenda/Gmail)
    "google_drive_list",
    "google_drive_read",
    "google_calendar_events",
    "google_gmail_list",
    "google_gmail_read",
    "google_gmail_labels",
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


def detect_infra_intent(text: str) -> bool:
    """True quando a mensagem pede INFRAESTRUTURA do servidor (IP, portas,
    topologia de rede).

    Usada pela guarda do pipeline (Etapa 3.4): para quem NÃO é o dono, a
    pergunta é negada determinísticamente — nem chega ao LLM (o modelo
    entregava o IP mesmo com a vedação no prompt). Os MESMOS padrões que
    disparam as actions `ip_address`/`listening_ports` para o dono.

    Bug fixado (2026-09-27, reportado pelo dono): perguntas do MUNDO
    EXTERNO (clima/temperatura de cidade) NÃO são infraestrutura —
    "temperatura em presidente venceslau sp" nunca deve ser bloqueada.
    A vedação é para dados que possam PREJUDICAR O SISTEMA (IP, portas,
    paths, credenciais), não para conhecimento geral.
    """
    if not text or not text.strip():
        return False
    # Perguntas sobre o mundo externo valem antes de qualquer padrão de
    # infra: "qual a temperatura em <cidade>" não é do servidor.
    if detect_external_intent(text):
        return False
    low = text.lower()
    if re.search(r"\b(ip|ipv[46]|endere[çc]o\s+de\s+ip)\b", low) and re.search(
        r"(servidor|m[aá]quina|host|local|externo|p[uú]blico|meu|privado)", low
    ):
        return True
    if re.search(r"\bportas?\b", low) and re.search(
        r"(abertas?|escutando|listening|em\s+uso|livres?|ocupadas?)", low
    ):
        return True
    return False


# Assuntos do MUNDO EXTERNO — conhecimento geral, livre para qualquer
# usuário autenticado (o dono reportou: bloquear "temperatura em cidade"
# era vedação indevida — a proteção é para o que pode PREJUDICAR O
# SISTEMA, não para curiosidades gerais). 'tempo' só conta com sujeito
# de clima — não pega "quanto tempo de uptime".
_EXTERNAL_SUBJECTS = re.compile(
    r"\b(temperatura|temperatuda|clima|umidade|previs[aã]o\s+do\s+tempo|"
    r"chover|chove|vento)\b|\btempo\s+(em|agora|hoje|amanh[aã])"
)
_EXTERNAL_PLACE = re.compile(r"\b(em|no|na|para)\s+\w")


def detect_external_intent(text: str) -> bool:
    """True quando a pergunta é do MUNDO EXTERNO (clima/temperatura de
    lugar, tempo em cidade) — conhecimento geral, NÃO dado do sistema.

    Conservador: só escapa da vedação de infra quando o sujeito é
    claramente de clima OU 'temperatura/clima' seguido de lugar ("em X").
    Temperatura DO SERVIDOR segue para a action cpu_temp (dado real).
    """
    if not text or not text.strip():
        return False
    low = text.lower()
    # 'temperatura do servidor/da máquina/cpu' NÃO é externo (dado real).
    if re.search(r"\b(temperatura|temperatuda)\b", low) and re.search(
        r"(servidor|m[aá]quina|cpu|sistema|host)", low
    ):
        return False
    if _EXTERNAL_SUBJECTS.search(low):
        return True
    if re.search(r"\b(temperatura|temperatuda|clima)\b", low) and _EXTERNAL_PLACE.search(low):
        return True
    return False


def _detect_operational(text: str) -> Optional[str]:
    """Padrões operacionais diretos (processos/memória/cpu/disco/uptime/ip/portas)."""
    low = text.lower()
    # IP do servidor — o dono pergunta e recebe (dado REAL, não LLM).
    # Palavra 'ip' como token inteiro (evita casar em 'descriptor', 'particular').
    if re.search(r"\b(ip|ipv[46]|endere[çc]o\s+de\s+ip)\b", low) and re.search(
        r"(servidor|m[aá]quina|host|local|externo|p[uú]blico|meu|privado)", low
    ):
        return "ip_address"
    # Portas abertas/escutando.
    if re.search(r"\bportas?\b", low) and re.search(
        r"(abertas?|escutando|listening|em\s+uso|livres?|ocupadas?)", low
    ):
        return "listening_ports"
    # CÂMBIO (v1.14.0, §12.1): cotação de moeda é dado REAL de fonte
    # externa — o LLM inventava 'US$ 5.20' e a mentira entrava no cache.
    # A action intercepta ANTES do modelo: AwesomeAPI (sem chave) ou erro
    # honesto. Casa moeda + sinal de cotação ('cotação', 'quanto está',
    # 'valor', 'preço'); sigla USD/EUR/BTC direta também.
    _moeda = re.search(
        r"\b(d[oó]lar|dolar|euro|libra|peso|iene|yen|yuan|franco\s+su[ií]ço|"
        r"bitcoin|btc|usd|eur|gbp|ars|jpy|cny|cad|aud|chf)\b",
        low,
    )
    if _moeda and re.search(
        r"(cota[çc][aã]o|cota\s|quanto\s+(est[áa]|custa|vale)|valor|pre[çc]o)",
        low,
    ):
        return "exchange_rate", {"moeda": _moeda.group(1)}
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
    # temperatura DO SERVIDOR (a de cidade é do mundo externo — e, com HA
    # ligado, vira dado REAL pela action ha_weather; a da máquina é
    # cpu_temp via sensors térmicos)
    if re.search(r"\b(temperatura|temperatuda)\b", low) and re.search(
        r"(servidor|m[aá]quina|cpu|sistema|host|rodando)", low
    ):
        return "cpu_temp"
    # CLIMA/tempo da região da casa (v1.8.0): o weather.* do HA tem a
    # leitura real — nunca o LLM (que inventava '23°C' e repetia a mentira
    # quando o dono disse 'mentira'). Casa / clima genérico / cidade.
    # 'tempo' (fraco, ambíguo com duração) só conta seguido de lugar/hora
    # e SEM palavras de duração ('tempo em média', 'tempo de build').
    _duracao = re.search(
        r"(m[ée]dia|demor|leva|build|compil|processo|upload|download|respost|"
        r"lat[êe]nci|uptime|ligad|no ar|batid)",
        low,
    )
    _clima_forte = re.search(
        r"\b(clima|temperatura|temperatuda|umidade|previs[aã]o|vento|chover|chove)\b",
        low,
    )
    _clima_fraco = (
        re.search(r"\btempo\s+(em|no|na|agora|hoje|amanh[aã])", low)
        and not _duracao
    )
    if (_clima_forte or _clima_fraco) and re.search(
        r"(casa|aqui|agora|hoje|amanh[aã]|fora|rua|em\s+\w|no\s+\w|l[aá])",
        low,
    ):
        # v1.12.0: cidade EXPLÍCITA na pergunta de clima → weather_city
        # (leitura externa Open-Meteo). Caso real §14 (30/09): 'qual a
        # temperatura em presidente venceslau' recebia o clima DA CASA —
        # honesto sobre a fonte, mas não era o pedido. Sem cidade (ou só
        # 'aqui/casa/hoje'), continua ha_weather (weather.* do HA).
        cidade = extract_city_from_weather_text(text)
        if cidade:
            return "weather_city", {"city": cidade}
        return "ha_weather"
    # Luzes/dispositivos do lar (v1.8.0) — estado REAL das entidades
    # switch.*/light.*. v1.8.1: COMANDO (liga/desliga) separado da LEITURA
    # — a intenção carrega o alvo resolvido; a execução tem gate de papel
    # + confirmação de 2 passos. v1.9.0: comando estendido a TOMADAS e
    # dispositivos switch.* ('liga a tomada do servidor').
    _comando = re.search(
        r"\b(liga|ligue|acende|acenda|acende|desliga|desligue|apaga|apague|"
        r"toggle|desconecta|desconecte|desplug|conecta|conecte|plug)\b",
        low,
    )
    _cmd_luz = bool(re.search(r"\b(luz|luzes|l[áa]mpada|interruptor)\b", low))
    _cmd_tomada = bool(re.search(
        r"\b(tomada|tomadas|soquete|soquetes|socket|dispositivo|dispositivos|"
        r"aparelho|energia)\b",
        low,
    ))
    if _comando and (_cmd_luz or _cmd_tomada):
        # v1.9.1: comando em PLURAL/sem alvo ('luzes acesas' dito de forma
        # ambígua, 'as luzes') NUNCA vira confirmação com entidade
        # inventada ('Luzes Acessas') — o alvo específico é OBRIGATÓRIO;
        # sem ele, a resposta é genérica e honesta.
        _plural = bool(re.search(
            r"\b(luzes|l[áa]mpadas|tomadas|soquetes|dispositivos|interruptores)\b",
            low,
        ))
        from core.intents import resolve_light_target

        target = resolve_light_target(low)
        # Plural SEM entidade casada ('liga as luzes', 'luzes acessas'):
        # resposta genérica — o verbo/substantivo NUNCA vira nome de
        # entidade (BUG-B real de 09:41: 'Confirmar: ligar Luzes Acessas').
        if target is not None and target[0] is None and _plural:
            return "ha_device_control", {
                "entity_id": "", "on": target[1], "plural": True,
            }
        if target is not None:
            entity_id, on, alvo = target
            if entity_id is None:
                if _plural:
                    # 'liga as luzes'/'luzes acessas': sem alvo específico —
                    # a action responde o pedido genérico de alvo (o verbo
                    # de liga/desliga NÃO vira nome de entidade).
                    return "ha_device_control", {
                        "entity_id": "", "on": on, "plural": True,
                    }
                # Nomeou uma luz/dispositivo que não existe no HA — a action
                # responde 'entidade_inexistente' com o termo procurado.
                return "ha_device_control", {
                    "entity_id": "", "on": on, "termo": alvo,
                }
            return "ha_device_control", {
                "entity_id": entity_id, "on": on, "alvo": alvo,
            }
        # Comando de luz/tomada SEM alvo específico: nunca executa em lote
        # — pede o alvo genérico (o formatador responde 'Qual luz ou
        # tomada?'). Nunca inventa entidade a partir do próprio comando.
        return "ha_device_control", {"entity_id": "", "on": bool(
            _comando.group(1) not in ("desliga", "desligue", "apaga", "apague",
                                      "desconecta", "desconecte", "desplug")
        )}
    if re.search(r"\b(luz(es)?|l[áa]mpada(s)?|interruptor(es)?)\b", low) and re.search(
        r"(aces[ao]s?|apagad[ao]s?|acesas|acessas|ligad[ao]s?|desligad[ao]s?|"
        r"est[ãa]o|qual|quais|como|quantas)",
        low,
    ):
        return "ha_lights"
    # ESTADO das tomadas (v1.9.0): 'tomadas ligadas'/'qual tomada está on'.
    if _cmd_tomada and re.search(
        r"(aces[ao]|apagad[ao]|ligad[ao]|desligad[ao]|conectad[ao]|est[ãa]o|"
        r"qual|quais|como|quantas)",
        low,
    ):
        return "ha_lights"
    # RESUMO do lar (só quem tem permissão executa; a action é iot/leitura).
    if re.search(r"(como est[áa]|resumo|raio.?x).{0,20}(casa|lar)", low):
        return "ha_summary"
    # CREDENCIAIS/SEGREDOS (v1.8.0): o LLM ALUCINOU uma senha de MQTT
    # ('OmegaDrakon2026') para o dono — resposta falsa de dado sensível é
    # pior que recusa. Negação determinística, sem LLM, para qualquer papel.
    if re.search(
        r"\b(senha|senhas|password|credencial|credenciais|token|api.?key|segredo)\b",
        low,
    ) and re.search(
        r"(mqtt|telegram|postgres|banco|home.assistant|homeassistant|wi.?fi|wifi|"
        r"rede|servidor|sistema|api|root|admin|dono)",
        low,
    ):
        return "__secrets_denied__"
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


# ---------------------------------------------------------------------------
# Google Workspace — leitura determinística
#
# Antes destas intenções, perguntas de e-mail/agenda caíam no LLM que
# inventava conteúdo (a 'agenda' nem existia até aqui — ver a v1.11.1).
# Agora vão para as actions google_* (dado REAL). Sem credencial, a resposta
# é honesta ('ainda não autorizado'), NUNCA um e-mail/compromisso inventado.
# ---------------------------------------------------------------------------

_GOOGLE_MAIL_RE = re.compile(
    r"\b(gmail|e-?mails|caixa\s+de\s+entrada|correio)\b", re.IGNORECASE
)
_GOOGLE_CAL_RE = re.compile(
    r"\b(agenda|calend[aá]rio|compromissos?|reuni[õo]es|meus?\s+eventos|"
    r"minha\s+agenda)\b",
    re.IGNORECASE,
)
_GOOGLE_DRIVE_RE = re.compile(r"\b(drive|google\s+drive)\b", re.IGNORECASE)
_GOOGLE_MAIL_ASK_RE = re.compile(
    r"\b(meus?|minha|minhas|ver|listar|ler|leia|checar|checa|conferir|"
    r"tenho|[uú]ltim[oa]s?|novos?|n[ãa]o\s+lid[ao]s?)\b",
    re.IGNORECASE,
)
_GOOGLE_ASK_RE = re.compile(
    r"\b(meus?|minha|minhas|ver|listar|ler|leia|quais|quantos|"
    r"[uú]ltim[oa]s?|pr[óo]xim[oa]s?|hoje|amanh[ãa]|semana)\b",
    re.IGNORECASE,
)
_GOOGLE_SECRET_RE = re.compile(
    r"\b(senha|password|token|credencial|credenciais|api.?key|segredo)\b",
    re.IGNORECASE,
)


def _detect_google(text: str) -> Optional[tuple[str, dict[str, Any]]]:
    """E-mail/Agenda/Drive → action google_* de leitura."""
    low = text.lower()
    if _GOOGLE_SECRET_RE.search(low):
        # 'qual a senha do gmail' NUNCA vira listagem de e-mails.
        return None
    if _GOOGLE_MAIL_RE.search(low) and _GOOGLE_MAIL_ASK_RE.search(low):
        return "google_gmail_list", {"limit": 10}
    if _GOOGLE_CAL_RE.search(low) and _GOOGLE_ASK_RE.search(low):
        days = 7
        if re.search(r"\bhoje\b", low):
            days = 1
        elif re.search(r"\bamanh[ãa]\b", low):
            days = 2
        return "google_calendar_events", {"days": days, "limit": 10}
    if _GOOGLE_DRIVE_RE.search(low) and _GOOGLE_ASK_RE.search(low):
        return "google_drive_list", {"limit": 20}
    return None


# ---------------------------------------------------------------------------
# Google Workspace — ESCRITA determinística (lote 2, 2026-10-03)
#
# Espelho do ha_device_control: o pedido de ESCRITA é detectado SEM LLM e
# vai para a action com gate de papel (só admin) + confirmação de 2 passos.
# Roda ANTES de _detect_google (leitura) — 'apague o e-mail da ana' jamais
# pode casar como listagem. NUNCA entra no FASTPATH_ACTIONS (allowlist de
# leitura é verificada por teste).
# ---------------------------------------------------------------------------

GOOGLE_WRITE_ACTIONS: frozenset[str] = frozenset({
    "google_drive_create", "google_drive_update", "google_drive_delete",
    "google_calendar_create", "google_calendar_delete",
    "google_gmail_send", "google_gmail_delete",
})

_GOOGLE_W_ARQUIVO_RE = re.compile(
    r"\b(arquivos?|ficheiros?|documentos?)\b", re.IGNORECASE
)
_GOOGLE_W_CAL_RE = re.compile(
    r"\b(compromissos?|reuni[õo]es?|agendamentos?|agenda|calend[aá]rio)\b",
    re.IGNORECASE,
)
_GOOGLE_W_CRIAR_RE = re.compile(
    r"\b(criar|crie|cria|criamos|fazer|faz|fa[çc]a|gerar|gere|cria-me|crie-me)\b",
    re.IGNORECASE,
)
_GOOGLE_W_EDITAR_RE = re.compile(
    r"\b(editar|edite|edita|alterar|altere|atualizar|atualize|modificar|"
    r"modifica|substituir|substitua|mudar|mude|reescrever|reescreva|"
    r"ajustar|ajuste|troc[ae]r?|troque)\b",
    re.IGNORECASE,
)
_GOOGLE_W_APAGAR_RE = re.compile(
    r"\b(apagar|apague|apaga|excluir|exclua|exclui|remover|remova|remove|"
    r"deletar|deleta|eliminar|elimine|jogar fora|joga fora|manda pr[oa] lixeira)\b",
    re.IGNORECASE,
)
_GOOGLE_W_ENVIAR_RE = re.compile(
    r"\b(enviar|envie|envia|manda|mande|disparar|dispare|manda pr[oa])\b",
    re.IGNORECASE,
)
_GOOGLE_W_EMAIL_NOME_RE = re.compile(
    r"\b(gmail|e-?mails?|email|caixa\s+de\s+entrada|correio)\b",
    re.IGNORECASE,
)
_GOOGLE_W_EMAIL_RE = re.compile(
    r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"
)
_GOOGLE_W_CONTEUDO_RE = re.compile(
    r"\b(?:conte[uú]do|texto)\s*[:=]\s*(.+)$", re.IGNORECASE
)
_GOOGLE_W_DIZENDO_RE = re.compile(
    r"\b(?:que\s+diga|dizendo|com\s+o\s+texto)\s*[:=]?\s*(.+)$",
    re.IGNORECASE,
)
_GOOGLE_W_QUANDO_RE = re.compile(
    r"\b(hoje|amanh[ãa])\b(?:\s*[àa]s\s+\d{1,2}(?:[:.]\d{2})?\s*h?)?",
    re.IGNORECASE,
)
_GOOGLE_W_STOP_NOME_RE = re.compile(
    r"\s+(?:no|na|do|da|em)\s+(?:google\s+)?(?:drive|agenda|calend[aá]rio)\b"
    r"|\s+com\s+(?:o\s+)?(?:texto|conte[uú]do)\s*[:=]?"
    r"|\s+(?:texto|conte[uú]do)\s*[:=]"
    r"|\s+(?:que\s+)?(?:diga|dizendo|contenha|tenha)\b"
    r"|[.!?;]\s*$",
    re.IGNORECASE,
)
_GOOGLE_W_ARTIGO_RE = re.compile(
    r"^(?:o|a|os|as|um|uma|chamado|chamada|nomeado|nomeada|de|do|da|dos|das)\s+",
    re.IGNORECASE,
)
_GOOGLE_W_LIXEIRA_RE = re.compile(
    r"\s+(?:para|pra|pro)\s+(?:a\s+)?lixeira\b", re.IGNORECASE
)


def _google_limpa_nome(nome: str) -> str:
    """Corta conectores que encerram o nome e remove artigo/preposição inicial."""
    partes = _GOOGLE_W_STOP_NOME_RE.split(nome, maxsplit=1)
    nome = partes[0] if partes else nome
    nome = re.sub(r"^[\s:;,\-–]+", "", nome)
    # artigo/preposição inicial (' o chamado notas' → 'notas')
    for _ in range(3):
        limpo = _GOOGLE_W_ARTIGO_RE.sub("", nome.strip(), count=1)
        if limpo == nome.strip():
            break
        nome = limpo
    return nome.strip().strip("\"'“”").strip()


def _google_nome_depois_do_substantivo(text: str, substantivo: re.Pattern) -> str:
    """Nome/título que vem DEPOIS do substantivo ('o arquivo atas no drive'
    → 'atas')."""
    m = substantivo.search(text)
    if m is None:
        return ""
    return _google_limpa_nome(text[m.end():])


def _google_conteudo(text: str) -> str:
    """Corpo do arquivo/e-mail pedido ('conteúdo: X' / 'texto: X' / 'que diga X')."""
    m = _GOOGLE_W_CONTEUDO_RE.search(text)
    if m:
        return m.group(1).strip().strip("\"'“”").strip()
    m = _GOOGLE_W_DIZENDO_RE.search(text)
    if m:
        return m.group(1).strip().strip("\"'“”").strip()
    return ""


def _google_quando_e_titulo(text: str) -> tuple[str, str]:
    """'o compromisso dentista amanhã às 15h' → (titulo, quando)."""
    m = _GOOGLE_W_CAL_RE.search(text)
    resto = text[m.end():] if m else text
    qm = _GOOGLE_W_QUANDO_RE.search(resto)
    quando = qm.group(0).strip() if qm else ""
    if qm:
        titulo = resto[:qm.start()] + " " + resto[qm.end():]
    else:
        titulo = resto
    return _google_limpa_nome(titulo), quando


def _google_termo_email(text: str) -> str:
    """'apague o e-mail da ana' → 'ana' (busca livre no Gmail)."""
    m = _GOOGLE_W_EMAIL_NOME_RE.search(text)
    resto = text[m.end():] if m else text
    resto = _GOOGLE_W_LIXEIRA_RE.sub("", resto)
    nome = re.sub(r"^[\s:;,\-–]+", "", resto)
    for _ in range(4):
        limpo = _GOOGLE_W_ARTIGO_RE.sub("", nome.strip(), count=1)
        if limpo == nome.strip():
            break
        nome = limpo
    return re.sub(r"[.!?;,]+$", "", nome.strip()).strip()


def _detect_google_write(text: str) -> Optional[tuple[str, dict[str, Any]]]:
    """Escrita no Drive/Agenda/Gmail → action google_* (gate + confirmação).

    Conservador: cada domínio exige o SUBSTANTIVO do objeto (arquivo +
    drive; compromisso/agenda; e-mail) — sem ele a frase nem casa aqui.
    """
    if not text or not text.strip():
        return None
    low = text.lower()
    if _GOOGLE_SECRET_RE.search(low):
        return None
    apagar = _GOOGLE_W_APAGAR_RE.search(low)
    criar = _GOOGLE_W_CRIAR_RE.search(low)
    editar = _GOOGLE_W_EDITAR_RE.search(low)
    enviar = _GOOGLE_W_ENVIAR_RE.search(low)
    tem_mail = bool(_GOOGLE_W_EMAIL_NOME_RE.search(low))

    # -- Gmail -------------------------------------------------------------
    if tem_mail and enviar:
        m = _GOOGLE_W_EMAIL_RE.search(text)
        ms = re.search(
            r"\bassunto\s*[:=]\s*(.+?)(?=\s+\bcorpo\s*[:=]|$)",
            text, re.IGNORECASE,
        )
        mc = re.search(r"\bcorpo\s*[:=]\s*(.+)$", text, re.IGNORECASE)
        params: dict[str, Any] = {
            "para": m.group(0) if m else "",
            "assunto": ms.group(1).strip() if ms else "",
            "corpo": mc.group(1).strip() if mc else "",
            "alvo": (m.group(0) if m else ""),
        }
        return "google_gmail_send", params
    if tem_mail and apagar:
        termo = _google_termo_email(text)
        return "google_gmail_delete", {"termo": termo, "alvo": termo}

    # -- Drive -------------------------------------------------------------
    # O SUBSTANTIVO 'arquivo' basta (sem exigir a palavra 'drive'): a
    # confirmação de 2 passos mostra 'no Google Drive' antes de qualquer
    # execução, então um pedido ambíguo nunca passa em silêncio.
    if _GOOGLE_W_ARQUIVO_RE.search(low):
        nome = _google_nome_depois_do_substantivo(text, _GOOGLE_W_ARQUIVO_RE)
        if apagar:
            return "google_drive_delete", {"name": nome, "alvo": nome}
        if editar:
            return "google_drive_update", {
                "name": nome,
                "content": _google_conteudo(text),
                "alvo": nome,
            }
        if criar:
            return "google_drive_create", {
                "name": nome,
                "content": _google_conteudo(text),
                "alvo": nome,
            }

    # -- Agenda ------------------------------------------------------------
    if _GOOGLE_W_CAL_RE.search(low):
        titulo, quando = _google_quando_e_titulo(text)
        if criar:
            return "google_calendar_create", {
                "titulo": titulo, "quando": quando, "alvo": titulo,
            }
        if apagar:
            return "google_calendar_delete", {"titulo": titulo, "alvo": titulo}
    return None


def detect_action_intent(text: str) -> Optional[tuple[str, dict[str, Any]]]:
    """Detecta uma intenção operacional (leitura OU escrita) na mensagem.

    Returns:
        (action_name, params) quando casou uma intenção conhecida, senão
        None (a mensagem segue para cache/LLM normalmente).
    """
    if not text or not text.strip():
        return None
    action = (
        _detect_network(text)
        or _detect_operational(text)
        or _detect_google_write(text)
        or _detect_google(text)
    )
    if action is None:
        return None
    # Intenções com params próprios (controle de luzes: entity_id/on)
    # retornam (nome, params) completo de _detect_operational.
    if isinstance(action, tuple):
        return action
    if action == "disk_usage":
        return action, {"path": "/"}
    return action, {}


# ---------------------------------------------------------------------------
# Extração de cidade de frases de clima (v1.12.0)
# ---------------------------------------------------------------------------

# Gatilhos de clima — mesma família dos padrões de ha_weather.
_CLIMA_CITY_RE = re.compile(
    r"\b(clima|temp(eratura|eratuda)?|umidade|previs[aã]o|vento|chove[r]?)\b"
)

# Padrões de lugar: 'em X', 'no X', 'na X', 'para X', 'pra X', 'de X' —
# captura o resto da frase e remove ruído de tempo/agregado.
_LUGAR_RE = re.compile(
    r"\b(?:em|no|na|para|pra|de|da|do)\s+(?P<lugar>[a-záàâãéêíóôõúüç]+"
    r"(?:\s+[a-záàâãéêíóôõúüç]+)*)",
    re.IGNORECASE,
)

# Ruído nas PONTAS do lugar (tempo relativo, gatilhos de clima, artigo):
# 'tempo no rio de janeiro' → ponta esquerda 'tempo no' sai, 'de' do MEIO
# fica (pertence à cidade). A extração recorta só das extremidades.
_RUIDO_PONTA_ESQ = (
    "hoje", "amanha", "amanhã", "ontem", "agora", "nesta", "neste",
    "nessa", "nesse", "aqui", "casa", "regiao", "região", "media",
    "média", "maxima", "máxima", "minima", "mínima", "max", "min",
    "tempo", "clima", "temperatura", "temperatuda", "umidade",
    "previsao", "previsão", "vento", "graus", "o", "a", "os", "as",
    "em", "no", "na", "do", "da", "para", "pra", "de", "minha",
    "meu", "minhas", "meus", "essa", "esse", "isso",
)
_RUIDO_PONTA_DIR = (
    "hoje", "amanha", "amanhã", "ontem", "agora", "max", "min",
    "maxima", "máxima", "minima", "mínima", "graus",
)

# UF/sigla solta no final ('em presidente venceslau sp') — faz parte do lugar.
_UF_RE = re.compile(r"\s*\b(sp|rj|mg|es|pr|sc|rs|ba|pe|ce|go|mt|ms|df|ma|pi|pa|"
                    r"am|rr|ap|ac|ro|to|al|pb|rn|se)\s*$", re.IGNORECASE)

def _sem_acento(p: str) -> str:
    """Normaliza para comparação de stopwords (aextração de cidade)."""
    return (
        p.replace("á", "a").replace("ã", "a").replace("â", "a")
        .replace("à", "a").replace("é", "e").replace("ê", "e")
        .replace("í", "i").replace("ó", "o").replace("õ", "o")
        .replace("ô", "o").replace("ú", "u").replace("ü", "u")
        .replace("ç", "c")
    )

def extract_city_from_weather_text(text: str) -> Optional[str]:
    """Extrai o nome de cidade de frases como 'clima em presidente venceslau'.

    Regra das PONTAS: stopwords/gatilhos saem apenas das extremidades do
    lugar casado — 'previsão do tempo no rio de janeiro' → 'rio de
    janeiro' (o 'de' do MEIO pertence à cidade).

    Returns:
        Nome da cidade, ou None quando a frase não menciona lugar explícito
        (aí o clima é o DA CASA — ha_weather).
    """
    if not text:
        return None
    low = text.lower()
    if not _CLIMA_CITY_RE.search(low):
        return None
    melhor: Optional[str] = None
    for m in _LUGAR_RE.finditer(low):
        lugar = _UF_RE.sub("", (m.group("lugar") or "").strip()).strip()
        palavras = lugar.split() if lugar else []
        # recorta ruído da ESQUERDA (gatilhos/artigos/preposições)
        while palavras and _sem_acento(palavras[0]) in _RUIDO_PONTA_ESQ:
            palavras.pop(0)
        # recorta ruído da DIREITA (tempo relativo/qualificador)
        while palavras and _sem_acento(palavras[-1]) in _RUIDO_PONTA_DIR:
            palavras.pop()
        if palavras:
            melhor = " ".join(palavras)
    return melhor


# ---------------------------------------------------------------------------
# Resolução de alvo de luz/dispositivo (v1.8.1/1.9.0) — nome falado →
# entity_id do HA
# ---------------------------------------------------------------------------

# Palavras que a fala costuma omitir do nome oficial da entidade.
# v1.9.0: stopwords também cobrem tomada/dispositivo na fala natural.
_LIGHT_STOPWORDS = ("da", "de", "do", "das", "dos", "a", "o", "luz", "lámpada",
                    "tomada", "socket", "interruptor", "dispositivo", "aparelho",
                    "plug", "tomadas")
_LIGHT_ON_WORDS = ("liga", "ligue", "acende", "acende")


def resolve_light_target(
    text: str,
) -> Optional[tuple[Optional[str], bool, str]]:
    """Resolve (entity_id, on, alvo) a partir de 'liga a luz da cozinha' ou
    'desliga a tomada do servidor' (v1.9.0: qualquer atuador switch/light).

    A resolução consulta as entidades do Home Assistant (injetadas pelo
    launcher em core.intents.configure_ha_entities) e casa o nome falado
    com friendly_name/entity_id (case/acento-insensível, stopwords
    ignoradas).

    Returns:
        None — a frase não tem alvo específico ('liga as luzes').
        (entity_id, on, alvo) — alvo casado com uma entidade real.
        (None, on, alvo) — alvo NOMEADO mas nenhuma entidade casou
        ('quartinho'); o termo cru volta para a mensagem de erro.
    """
    # Remove o verbo e conectores: 'liga a luz da cozinha' → 'cozinha';
    # 'liga a tomada do servidor' → 'servidor' (v1.9.0: tomada/soquete).
    alvo = re.sub(
        r"\b(liga|ligue|acende|desliga|desligue|apaga|apague|toggle|a|o|as|os|"
        r"luz|luzes|l[áa]mpada|interruptor|tomada|tomadas|soquete|soquetes|socket|"
        r"dispositivo|dispositivos|aparelho|por favor|agora)\b",
        " ",
        text,
    )
    alvo = re.sub(r"\s+", " ", alvo).strip(" ?!.,")
    if not alvo or len(alvo) < 3:
        return None
    states = _HA_ENTITIES
    if not states:
        return None

    def _norm(s: str) -> str:
        s = s.lower()
        for a, b in (("á", "a"), ("ã", "a"), ("â", "a"), ("à", "a"),
                     ("é", "e"), ("ê", "e"), ("í", "i"),
                     ("ó", "o"), ("õ", "o"), ("ô", "o"),
                     ("ú", "u"), ("ç", "c")):
            s = s.replace(a, b)
        return " ".join(w for w in s.split() if w not in _LIGHT_STOPWORDS)

    alvo_n = _norm(alvo)
    on = not any(
        w in text
        for w in ("desliga", "desligue", "apaga", "apague", "desconecta",
                  "desconecte", "desplug")
    )
    best: Optional[tuple[int, int, str]] = None
    for s in states:
        eid = s.entity_id
        if eid.split(".", 1)[0] not in ("switch", "light"):
            continue
        name = (s.attributes or {}).get("friendly_name") or eid
        haystack = _norm(f"{name} {eid}")
        score = sum(1 for word in alvo_n.split() if word and word in haystack)
        if score == 0:
            continue
        # Mais palavras casadas = melhor; empate: entidade mais curta.
        cand = (-score, len(haystack), eid)
        if best is None or cand < best:
            best = cand
    if best is None:
        return None, on, alvo
    return best[2], on, alvo


def configure_ha_entities(states: list[Any]) -> None:
    """Injeta as entidades do HA (launcher) para resolução de alvo."""
    global _HA_ENTITIES
    _HA_ENTITIES = states


_HA_ENTITIES: list[Any] = []


_CONFIRM_YES = re.compile(
    r"\s*(sim|si|sim!|s|ok|okay|pode|confirmo|confirmado|isso|isso mesmo|"
    r"pode sim|manda|executa|beleza|blz|va|vai|manda ver|pode mandar)\b.*$",
    re.IGNORECASE,
)


def detect_confirmation(text: str) -> bool:
    """True quando a mensagem é uma CONFIRMAÇÃO curta ('sim', 'pode').

    Conservador: frase longa ou com verbo de luz/dispositivo não é
    confirmação — é comando novo (que vai pedir confirmação de novo).
    """
    if not text or len(text.strip()) > 40:
        return False
    low = text.lower()
    if re.search(
        r"\b(luz|l[áa]mpada|interruptor|liga|desliga|acende|apaga|tomada|"
        r"soquete|socket|dispositivo)\b",
        low,
    ):
        return False
    return bool(_CONFIRM_YES.match(low))


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


def _gcal_when(event: dict[str, Any]) -> str:
    """Início de um evento do Google Calendar → texto curto (pt-BR)."""
    raw = str(event.get("start") or "")
    if not raw:
        return "?"
    if event.get("all_day"):
        return f"{raw} (dia inteiro)"
    try:
        from datetime import datetime

        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.strftime("%d/%m %H:%M")
    except ValueError:
        return raw


def _format_google_write(action: str, data: dict[str, Any], ok: Any) -> str:
    """Resposta da ESCRITA Google (lote 2) — sempre guiada, nunca LLM.

    Espelho do ramo ha_device_control: permissão negada, alvo ausente/
    ambíguo/não encontrado, pendência de confirmação e execução têm textos
    próprios; erro do Google degrada honesto.
    """
    err = str(data.get("error") or "")
    hint = str(data.get("hint") or "")
    if err == "permissao_negada":
        return (
            "🔒 Escrita no Google (criar/editar/apagar arquivos, compromissos "
            "ou e-mails) é só do dono do sistema — a sua conta pode ler, "
            "não escrever."
        )
    if data.get("needs_confirmation"):
        return f"✍️ {hint}" if hint else (
            "✍️ Confirmar a operação? Responda 'sim' para executar (vale por "
            "2 minutos)."
        )
    if data.get("executed"):
        alvo = data.get("alvo") or ""
        if action == "google_drive_create":
            extra = f" ({data['link']})" if data.get("link") else ""
            return f"✅ Arquivo '{alvo}' criado no Google Drive{extra}."
        if action == "google_drive_update":
            return f"✅ Conteúdo de '{alvo}' substituído no Google Drive."
        if action == "google_drive_delete":
            return f"🗑️ Arquivo '{alvo}' apagado do Google Drive."
        if action == "google_calendar_create":
            quando = str(data.get("start") or "").replace("T", " ")[:16]
            sufixo = f" em {quando}" if quando else ""
            return f"✅ Compromisso '{alvo}' criado na sua Agenda{sufixo}."
        if action == "google_calendar_delete":
            return f"🗑️ Compromisso '{alvo}' apagado da sua Agenda."
        if action == "google_gmail_send":
            assunto = data.get("assunto") or "(sem assunto)"
            return (
                f"✅ E-mail enviado para {data.get('para') or alvo} — "
                f"assunto '{assunto}'."
            )
        if action == "google_gmail_delete":
            return f"🗑️ E-mail '{alvo}' movido para a lixeira do Gmail."
        return f"✅ Operação '{action}' executada."
    if ok is not True:
        if "não configurado" in err or "não autorizado" in err:
            return (
                "🔗 O acesso ao Google (Drive/Agenda/Gmail) ainda não está "
                "configurado/autorizado neste sistema.\n"
                "  • Veja docs/GOOGLE.md e rode `python -m runtime.google_auth`."
            )
        if hint:
            return f"🤔 {hint}"
        if err in {"alvo_obrigatorio", "nao_encontrado", "alvo_ambiguo",
                   "conteudo_obrigatorio", "destinatario_invalido",
                   "quando_obrigatorio", "nativo_google"}:
            return f"🤔 {err} — nada foi alterado."
        return f"⚠️ Google indisponível agora: {err or 'falha na operação.'}"
    return f"✅ Operação '{action}' concluída."


def format_intent_result(action: str, data: Any) -> Optional[str]:
    """Converte o retorno da action em uma resposta PT-BR curta.

    Returns:
        Texto da resposta, ou None se o resultado não for aproveitável
        (o pipeline então cai para o LLM — nunca responde vazio).
    """
    if not isinstance(data, dict):
        return None
    ok = data.get("ok", True)
    if (
        ok is not True
        and action != "ha_device_control"
        and not action.startswith("google_")
    ):
        return None  # action degradou — deixa o LLM responder
    # Controle de luzes: erros guiados (alvo/entidade/permissão) SÃO a
    # resposta certa — nunca caem no LLM (que alucinaria a execução).

    if action == "ha_weather":
        temp = data.get("temperature")
        if temp is None:
            return None  # sem leitura — deixa o LLM/fluxo seguir
        unit = data.get("temperature_unit", "°C")
        cond = data.get("condition") or "?"
        _COND_PT = {
            "clear-night": "céu limpo (noite)", "sunny": "ensolarado",
            "partlycloudy": "parcialmente nublado", "cloudy": "nublado",
            "rainy": "chuvoso", "pouring": "chuva forte",
            "thunderstorm": "tempestade", "hail": "granizo",
            "snowy": "nevando", "windy": "ventando", "fog": "neblina",
        }
        cond_pt = _COND_PT.get(cond, cond)
        lines = [f"🌤️ Clima na região da casa: {temp}{unit}, {cond_pt}"]
        extra = []
        hum = data.get("humidity")
        if hum is not None:
            extra.append(f"umidade {hum}%")
        wind = data.get("wind_speed")
        if wind is not None:
            extra.append(f"vento {wind} {data.get('wind_speed_unit', 'km/h')}")
        if extra:
            lines.append("  • " + " · ".join(extra))
        lines.append("  • Fonte: Home Assistant (weather da casa) — leitura real.")
        return "\n".join(lines)

    if action == "weather_city":
        if data.get("error"):
            return None  # degradação guiada pelo fluxo normal (nunca LLM inventa)
        temp = data.get("temperature")
        if temp is None:
            return None
        unit = data.get("temperature_unit", "°C")
        cond = data.get("condition") or "?"
        lines = [f"🌤️ Clima em {data.get('city')}: {temp}{unit}, {cond}"]
        extra = []
        sens = data.get("apparent_temperature")
        if sens is not None:
            extra.append(f"sensação {sens}{unit}")
        hum = data.get("humidity")
        if hum is not None:
            extra.append(f"umidade {hum}%")
        wind = data.get("wind_speed")
        if wind is not None:
            extra.append(f"vento {wind} {data.get('wind_speed_unit', 'km/h')}")
        if extra:
            lines.append("  • " + " · ".join(extra))
        lines.append("  • Fonte: Open-Meteo — leitura real de agora.")
        return "\n".join(lines)

    if action == "exchange_rate":
        if data.get("error"):
            return None  # degradação guiada — nunca o LLM inventa cotação
        bid = data.get("bid")
        if bid is None:
            return None

        def _brl(v: float) -> str:
            # pt-BR: 5.1844 → '5,1844'; 350123.45 → '350123,45' — 4 casas
            # (padrão do câmbio) sem zeros à direita, SEM notação científica
            # (o BTC derrubaria o .4g).
            return f"{v:.4f}".rstrip("0").rstrip(".").replace(".", ",")

        nome = data.get("moeda") or data.get("codigo") or "moeda"
        linhas = [f"💱 {nome.capitalize()}: R$ {_brl(bid)}"]
        ask = data.get("ask")
        if ask is not None:
            linhas[0] += f" (venda R$ {_brl(ask)})"
        var = data.get("variacao_pct")
        if var is not None:
            seta = "📈" if var >= 0 else "📉"
            linhas.append(f"  • {seta} Variação hoje: {var:+.2f}%")
        mx, mn = data.get("maximo"), data.get("minimo")
        if mx is not None and mn is not None:
            linhas.append(f"  • Faixa do dia: R$ {_brl(mn)} – R$ {_brl(mx)}")
        linhas.append("  • Fonte: AwesomeAPI — cotação real de agora.")
        return "\n".join(linhas)

    if action == "ha_device_control":
        if data.get("error") == "permissao_negada":
            return (
                "🔒 Controle de luzes e tomadas é só o dono do sistema — a "
                "sua conta não pode ligar/desligar dispositivos."
            )
        if data.get("error") == "alvo_obrigatorio":
            if data.get("plural"):
                # v1.9.1: comando em plural/sem alvo ('liga as luzes') —
                # resposta genérica e honesta, SEM inventar entidade.
                return (
                    "💡 Não posso acionar várias luzes de uma vez — diga "
                    "qual luz ou tomada (ex: 'liga a luz da cozinha').\n"
                    "(Para ver o estado: 'luzes acesas'.)"
                )
            return (
                "💡 Qual luz ou tomada? Diga, por exemplo: 'liga a luz da "
                "cozinha' ou 'desliga a tomada do servidor'.\n"
                "(Para ver o estado: 'luzes acesas'.)"
            )
        if data.get("error") == "entidade_inexistente":
            return f"🤔 {data.get('hint', 'entidade não encontrada')}"
        if data.get("error") == "nao_e_luz":
            return f"🤔 {data.get('hint', 'não é luz/tomada/interruptor')}"
        if data.get("needs_confirmation"):
            return (
                f"💡 Confirmar: {data.get('action')} '{data.get('name')}' "
                f"(agora: {data.get('current')})?\n"
                "Responda **sim** para executar — a confirmação vale por 2 minutos."
            )
        if data.get("executed"):
            estado = data.get("state_after") or ("on" if data.get("action") == "ligar" else "off")
            emoji = "🟢" if estado == "on" else "⚪"
            return (
                f"✅ {data.get('name')}: {data.get('action')} executado "
                f"({emoji} estado agora: {estado})."
            )
        return None

    if action == "ha_lights":
        lights = data.get("lights") or []
        on_list = [l for l in lights if l.get("on")]
        if not lights:
            return "💡 Nenhuma luz/interruptor acessível no Home Assistant agora."
        header = (f"💡 {data.get('on', 0)} acesa(s) de {data.get('total', 0)} "
                  "no Home Assistant:")
        if on_list:
            lines = [header]
            for l in on_list[:10]:
                lines.append(f"  • 🟢 {l.get('name')} ({l.get('entity')})")
            off_names = [l.get("name") for l in lights if not l.get("on")]
            if off_names:
                lines.append(
                    "  ⚪ Apagadas: " + ", ".join(off_names[:10])
                )
            return "\n".join(lines)
        off_names = [l.get("name") for l in lights]
        return header + " nenhuma acesa. Apagadas: " + ", ".join(off_names[:10])

    if action == "ha_summary":
        w = data.get("weather") or {}
        lights = data.get("lights") or {}
        lines = ["🏠 Raio-X do lar (Home Assistant):"]
        if w.get("temperature") is not None:
            lines.append(
                f"  • Clima: {w.get('temperature')}{w.get('temperature_unit', '°C')}"
                + (f", umidade {w.get('humidity')}%" if w.get("humidity") else "")
            )
        lines.append(
            f"  • Luzes: {lights.get('on', 0)} acesa(s) de {lights.get('total', 0)}"
        )
        for p in data.get("people", [])[:5]:
            lines.append(f"  • {p.get('entity')}: {p.get('state')}")
        for b in data.get("batteries", [])[:5]:
            lines.append(f"  • Bateria {b.get('name')}: {b.get('level')}%")
        router = data.get("router") or {}
        if router.get("external_ip"):
            lines.append(
                f"  • Roteador: IP externo {router.get('external_ip')}"
                + (f", download {router.get('download_kib_s')} KiB/s"
                   if router.get("download_kib_s") else "")
            )
        return "\n".join(lines)

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

    if action == "cpu_temp":
        readings = data.get("readings") or []
        hottest = data.get("hottest") or {}
        temp = data.get("celsius", hottest.get("celsius"))
        if temp is None:
            return None
        lines = [f"🌡️ Temperatura do servidor: {temp}°C (sensor mais quente: "
                 f"{hottest.get('type', '?')})"]
        for r in readings[:5]:
            lines.append(f"  • {r.get('type', r.get('zone', '?'))}: {r.get('celsius')}°C")
        return "\n".join(lines)

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

    if action == "ip_address":
        addresses = data.get("addresses") or []
        outbound = data.get("outbound") or ""
        if not addresses and not outbound:
            return None  # nada identificado — deixa o LLM responder
        parts = ["🌐 IP do servidor:"]
        for ip in addresses[:8]:
            marker = " (saída)" if ip == outbound else ""
            parts.append(f"  • {ip}{marker}")
        if outbound and outbound not in addresses:
            parts.append(f"  • {outbound} (saída padrão)")
        return "\n".join(parts)

    if action == "listening_ports":
        ports = data.get("ports") or []
        if not ports:
            return "🔌 Nenhuma porta TCP escutando agora."
        parts = [f"🔌 {len(ports)} porta(s) TCP escutando:"]
        for entry in ports[:12]:
            addr = entry.get("addr") or ""
            parts.append(
                f"  • {entry.get('port')} ({addr}" +
                (f" · {entry.get('process')}" if entry.get("process") else "") +
                ")"
            )
        if len(ports) > 12:
            parts.append(f"  • … e mais {len(ports) - 12}")
        return "\n".join(parts)

    if action.startswith("google_"):
        # Google Workspace: sem credencial/autorização a resposta é HONESTA (nunca o
        # LLM inventando e-mail/compromisso/arquivo).
        if action in GOOGLE_WRITE_ACTIONS:
            return _format_google_write(action, data, ok)
        if ok is not True:
            err = str(data.get("error", ""))
            if "não configurado" in err or "não autorizado" in err:
                return (
                    "🔗 O acesso ao Google (Drive/Agenda/Gmail) ainda não está "
                    "configurado/autorizado neste sistema.\n"
                    "  • Veja docs/GOOGLE.md e rode `python -m runtime.google_auth`."
                )
            return f"⚠️ Google indisponível agora: {err or 'falha na consulta.'}"
        if action == "google_gmail_list":
            msgs = data.get("messages") or []
            if not msgs:
                return "📧 Nenhuma mensagem encontrada no Gmail."
            lines = [f"📧 {len(msgs)} mensagem(ns) no Gmail:"]
            for m in msgs[:10]:
                lines.append(f"  • {(m.get('subject') or '(sem assunto)')[:80]}")
                if m.get("from"):
                    lines.append(f"      de {str(m['from'])[:60]}")
            return "\n".join(lines)
        if action == "google_calendar_events":
            events = data.get("events") or []
            if not events:
                return (
                    f"📅 Nenhum compromisso nos próximos {data.get('days', 7)} "
                    "dia(s) na sua Agenda."
                )
            lines = [f"📅 Próximos {len(events)} compromisso(s):"]
            for e in events[:10]:
                lines.append(
                    f"  • {_gcal_when(e)} — {e.get('summary', '(sem título)')}"
                )
                if e.get("location"):
                    lines.append(f"      📍 {e['location']}")
            return "\n".join(lines)
        if action == "google_drive_list":
            files = data.get("files") or []
            if not files:
                return "📁 Nenhum arquivo encontrado no Google Drive."
            lines = [f"📁 {len(files)} arquivo(s) no Google Drive:"]
            for f in files[:15]:
                lines.append(
                    f"  • {f.get('name', '(sem nome)')}  "
                    f"({f.get('mime_type', '?')})"
                )
            return "\n".join(lines)
        return None

    # Fallback genérico: pares chave=valor escalares (sem aninhados).
    parts = [
        f"{key}: {value}" for key, value in data.items()
        if not isinstance(value, (dict, list)) and not key.startswith("_")
    ]
    return "; ".join(parts) if parts else None


__all__ = [
    "FASTPATH_ACTIONS",
    "GOOGLE_WRITE_ACTIONS",
    "detect_action_intent",
    "detect_infra_intent",
    "safe_math",
    "format_intent_result",
]