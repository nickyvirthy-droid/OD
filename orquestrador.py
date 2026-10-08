"""
OMEGA DRAKON • SYSTEMS
Tecnologia que respira.
Módulo: orquestrador.py
Descrição: ecossistema de redundância (fallback) automática para geração de
           código com múltiplas CLIs de IA. Monitora `pedido.txt` a cada
           PEDIDO_INTERVALO_S segundos; ao detectar um pedido, monta um prompt
           blindado (código puro, sem markdown) e tenta executá-lo em cascata:
           Freebuff → OpenCode → Kilo. O resultado só vale se passar na
           validação de sintaxe (ast.parse); sintaxe quebrada = pular para a
           próxima CLI. Arquivo gerado: ARQUIVO_SAIDA (default
           `codigo_gerado.py`).
           Modo `--sessao` (2026-10-08): sessão de desenvolvimento ON-DEMAND
           do canal do painel /admin — lê a ideia em pedido.txt, executa a
           CLI com contexto (iniciar/, docs/, txt.txt), pausa na caixa de
           desenvolvimento quando precisa de autorização do dono, valida com
           a suíte canônica e commita (sem push).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

#: Arquivo monitorado (caminho relativo à raiz do projeto).
PEDIDO_FILE: Path = Path("pedido.txt")

#: Intervalo de varredura em segundos.
PEDIDO_INTERVALO_S: int = 5

#: Arquivo onde o código gerado e validado é gravado.
ARQUIVO_SAIDA: Path = Path("codigo_gerado.py")

#: Timeout de cada CLI em segundos (LLMs podem demorar; 10 min cobre o pior caso).
CLI_TIMEOUT_S: int = 600

#: Chaves carregadas do .env que são repassadas ao ambiente dos subprocessos.
ENV_KEYS: tuple[str, ...] = ("GEMINI_API_KEY", "GROQ_API_KEY")

#: Modelo grátis do provedor opencode (o default 'build' usa OpenAI e morre
#: sem créditos — 'credit_balance_exhausted'; o provedor opencode/* é free).
OPENCODE_MODELO: str = "opencode/nemotron-3-ultra-free"

#: Modelo grátis do provedor kilo (gemini default exige chave/quota; os
#: modelos groq estouram o TPM 8000 do tier free com o prompt do sistema).
KILO_MODELO: str = "kilo/inclusionai/ling-3.0-flash-sante:free"

#: Reforço de sistema embutido no prompt blindado (sem markdown, sem cercas).
INSTRUCAO_BLINDADA: str = (
    "Você é um gerador de código. Responda APENAS com o conteúdo do arquivo "
    "Python pedido — código puro e completo, sem texto extra, sem formatação "
    "markdown, sem cercas de código (``` ou ```python) e sem comentários "
    "explicando a resposta. O arquivo deve começar diretamente com código "
    "Python válido e ser executável por si só."
)

#: Logger do módulo (padrão do projeto: logging, journald do usuário captura).
log = logging.getLogger("orquestrador")

# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CliSpec:
    """Especificação de uma CLI de geração de código na cascata de fallback."""

    #: Nome de exibição (logs).
    nome: str
    #: Executável procurado no PATH.
    binario: str
    #: Argumentos fixos ANTES do prompt (ex: ['run', '-m', 'modelo']).
    args_antes: tuple[str, ...]
    #: Argumentos fixos DEPOIS do prompt (ex: ['--auto']).
    args_depois: tuple[str, ...] = ()
    #: Caminho alternativo quando o binário NÃO está no PATH do serviço
    #: (instalação com prefix de usuário, fora do PATH default).
    caminho_candidato: str = ""

    def comando_base(self) -> list[str]:
        """Executável resolvido: PATH primeiro, candidato depois.

        Expande '~' do caminho_candidato; devolve o binário do PATH quando
        existir, senão o candidato se existir, senão o binário (para o erro
        de execução padrão ser o mesmo de antes).
        """
        if shutil.which(self.binario):
            return [self.binario]
        if self.caminho_candidato:
            candidato = Path(self.caminho_candidato).expanduser()
            if candidato.is_file() and os.access(candidato, os.X_OK):
                return [str(candidato)]
        return [self.binario]


#: Cascata oficial de fallback — a ordem É a política (Freebuff primeiro).
CLIS: tuple[CliSpec, ...] = (
    # Freebuff: wrapper Node sem subcomando de prompt não-interativo no
    # PATH público (0.2.1 aceita só 'login'); o binário real
    # (~/.config/manicode/freebuff) aceita PROMPT posicional direto.
    CliSpec(
        nome="Freebuff",
        binario="freebuff",
        args_antes=(),
        caminho_candidato="~/.config/manicode/freebuff",
    ),
    # OpenCode: 'run PROMPT' — modelo grátis por padrão (o default 'build'
    # usa OpenAI e morre sem créditos; o provedor opencode/* é free).
    CliSpec(
        nome="OpenCode",
        binario="opencode",
        args_antes=("run", "-m", OPENCODE_MODELO),
        caminho_candidato="~/.npm-global/bin/opencode",
    ),
    # Kilo: 'run PROMPT --auto --pure' — modelo free do provedor kilo
    # (gemini default exige chave/quota; groq default estoura o TPM).
    CliSpec(
        nome="Kilo",
        binario="kilo",
        args_antes=("run", "-m", KILO_MODELO, "--pure"),
        args_depois=("--auto",),
        caminho_candidato="~/.npm-global/bin/kilo",
    ),
)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


def montar_prompt(pedido: str) -> str:
    """Monta o prompt blindado a partir do pedido bruto do usuário.

    O pedido entra limpo (sem espaços sobrando) e o reforço de sistema exige
    código puro — sem markdown, sem cercas ```python.
    """
    pedido_limpo = pedido.strip()
    return f"{INSTRUCAO_BLINDADA}\n\nTarefa: crie o arquivo Python solicitado.\n\nPedido do usuário: {pedido_limpo}"


# ---------------------------------------------------------------------------
# Extração e validação de código
# ---------------------------------------------------------------------------


def extrair_codigo(resposta: str) -> str:
    """Extrai o código Python de uma resposta da CLI.

    Se a resposta vier com cerca de markdown (```python ... ```), o bloco é
    extraído e a cerca removida — camada de defesa para o caso de a CLI
    ignorar a instrução de responder sem formatação. Resposta sem cerca volta
    intacta.
    """
    texto = resposta.strip()
    fence = "```"
    inicio = texto.find(fence)
    if inicio == -1:
        return texto
    # Salta a linha da cerca inicial (com ou sem linguagem: ```python etc.)
    linha_fim = texto.find("\n", inicio)
    if linha_fim == -1:
        return texto
    corpo = texto[linha_fim + 1 :]
    fim = corpo.find(fence)
    if fim == -1:
        # Cerca aberta sem fechamento: devolve o corpo assim mesmo.
        return corpo.strip()
    return corpo[:fim].strip()


def validar_sintaxe(codigo: str) -> bool:
    """Valida que `codigo` é um módulo Python sintaticamente válido (ast.parse)."""
    try:
        ast.parse(codigo)
    except (SyntaxError, ValueError):
        return False
    return bool(codigo.strip())


# ---------------------------------------------------------------------------
# Execução das CLIs
# ---------------------------------------------------------------------------


def _ambiente_com_chaves() -> dict[str, str]:
    """Monta o ambiente do subprocesso: os do processo + as chaves do .env."""
    env = dict(os.environ)
    for chave in ENV_KEYS:
        valor = os.environ.get(chave)
        if valor:
            env[chave] = valor
    return env


def executar_cli(spec: CliSpec, prompt: str, timeout_s: int = CLI_TIMEOUT_S) -> str | None:
    """Executa UMA CLI com o prompt e devolve stdout em caso de sucesso.

    Devolve None em qualquer falha: binário ausente, erro de execução
    (ex: falta de créditos), timeout ou saída vazia. O stderr é capturado para
    o log — nunca engolido.
    """
    base = spec.comando_base()
    if base == [spec.binario] and shutil.which(spec.binario) is None:
        log.info("%s indisponível (binário '%s' não encontrado)", spec.nome, spec.binario)
        return None

    comando: list[str] = [*base, *spec.args_antes, prompt, *spec.args_depois]
    try:
        resultado = subprocess.run(  # noqa: S603 — comando fixo da cascata oficial
            comando,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            env=_ambiente_com_chaves(),
        )
    except subprocess.TimeoutExpired:
        log.warning("%s excedeu %ss — tratado como falha", spec.nome, timeout_s)
        return None
    except OSError as erro:
        log.warning("%s falhou ao executar: %s", spec.nome, erro)
        return None

    if resultado.returncode != 0:
        stderr = (resultado.stderr or "").strip()
        log.warning(
            "%s falhou (exit=%s): %s",
            spec.nome,
            resultado.returncode,
            stderr[:300] if stderr else "sem stderr",
        )
        return None

    saida = (resultado.stdout or "").strip()
    if not saida:
        log.warning("%s respondeu vazio", spec.nome)
        return None
    return saida


# ---------------------------------------------------------------------------
# Pipeline de um pedido
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResultadoPedido:
    """Desfecho do processamento de um pedido."""

    #: True quando uma CLI produziu código sintaticamente válido.
    ok: bool
    #: CLI que entregou o código (None se todas falharam).
    cli: str | None
    #: Código final gravado (None se todas falharam).
    codigo: str | None


def processar_pedido(
    pedido: str,
    arquivo_saida: Path = ARQUIVO_SAIDA,
    executar: Callable[[CliSpec, str], str | None] = executar_cli,
    clis: Sequence[CliSpec] = CLIS,
) -> ResultadoPedido:
    """Executa a cascata de fallback para um pedido e grava o arquivo gerado.

    Regras:
      - A 1ª CLI que devolver código SINTATICAMENTE VÁLIDO vence;
      - Saída com erro de sintaxe NÃO encerra: pula para a próxima CLI;
      - O código vencedor é gravado em `arquivo_saida` e devolvido;
      - Todas falharam → ResultadoPedido(ok=False) e nada é gravado.
    """
    prompt = montar_prompt(pedido)
    for spec in clis:
        resposta = executar(spec, prompt)
        if resposta is None:
            continue
        codigo = extrair_codigo(resposta)
        if not validar_sintaxe(codigo):
            log.warning(
                "%s devolveu código com sintaxe inválida — pulando para a próxima CLI",
                spec.nome,
            )
            continue
        arquivo_saida.write_text(
            codigo if codigo.endswith("\n") else codigo + "\n", encoding="utf-8"
        )
        log.info("Código válido gravado em %s (via %s)", arquivo_saida, spec.nome)
        return ResultadoPedido(ok=True, cli=spec.nome, codigo=codigo)

    log.error("Todas as CLIs falharam para o pedido: %.120r", pedido)
    return ResultadoPedido(ok=False, cli=None, codigo=None)


# ---------------------------------------------------------------------------
# Monitor do pedido.txt
# ---------------------------------------------------------------------------


def ler_e_limpar_pedido(caminho: Path = PEDIDO_FILE) -> str | None:
    """Lê o conteúdo do pedido e limpa o arquivo imediatamente (anti-loop).

    Devolve o pedido como string, ou None se o arquivo está ausente/em
    branco (nada a fazer — e nada é escrito de volta).
    """
    try:
        conteudo = caminho.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError as erro:
        log.warning("Falha ao ler %s: %s", caminho, erro)
        return None
    if not conteudo:
        return None
    # Limpeza imediata para não reprocessar o mesmo pedido no próximo ciclo.
    try:
        caminho.write_text("", encoding="utf-8")
    except OSError as erro:
        log.warning("Falha ao limpar %s: %s", caminho, erro)
    return conteudo


def ciclo(
    arquivo_pedido: Path = PEDIDO_FILE,
    arquivo_saida: Path = ARQUIVO_SAIDA,
    executar: Callable[[CliSpec, str], str | None] = executar_cli,
    clis: Sequence[CliSpec] = CLIS,
) -> bool:
    """Um ciclo de varredura: lê o pedido, processa e devolve True se houve trabalho."""
    pedido = ler_e_limpar_pedido(arquivo_pedido)
    if pedido is None:
        return False
    log.info("Pedido recebido: %.120s", pedido.replace("\n", " "))
    resultado = processar_pedido(pedido, arquivo_saida, executar, clis)
    return resultado.ok


def monitorar(
    intervalo_s: int = PEDIDO_INTERVALO_S,
    arquivo_pedido: Path = PEDIDO_FILE,
    arquivo_saida: Path = ARQUIVO_SAIDA,
) -> None:  # pragma: no cover — loop infinito por desenho
    """Loop principal: varre `pedido.txt` a cada `intervalo_s` segundos, para sempre.

    Um ciclo que levanta exceção inesperada é logado e não derruba o monitor
    (o objetivo é redundância; o monitor é o último a cair).
    """
    log.info(
        "Monitor no ar | pedido=%s | saida=%s | intervalo=%ss | CLIs=%s",
        arquivo_pedido,
        arquivo_saida,
        intervalo_s,
        " → ".join(spec.nome for spec in CLIS),
    )
    while True:
        try:
            ciclo(arquivo_pedido, arquivo_saida)
        except Exception:  # noqa: BLE001 — o monitor não morre por um ciclo ruim
            log.exception("Ciclo com erro — continuando no próximo intervalo")
        time.sleep(intervalo_s)


# ---------------------------------------------------------------------------
# Modo SESSÃO — canal de desenvolvimento on-demand (2026-10-08)
# ---------------------------------------------------------------------------
#
# O dono escreve a ideia no `pedido.txt` (seção "Canal de desenvolvimento" do
# painel /admin) e aperta ▶ Ativar desenvolvimento. O od-core sobe ESTE
# processo com `--sessao` (desanexado); ele:
#   1. lê a ideia em pedido.txt (NÃO limpa — só a fila antiga limpava);
#   2. executa a CLI escolhida (cascata automática por padrão) com um prompt
#      de CONTEXTO: a CLI deve ler iniciar/, docs/ e txt.txt antes de codar;
#   3. se a CLI precisar de autorização, publica em data/dev_caixa.json e
#      ESPERA a resposta do dono (caixa de desenvolvimento do painel);
#   4. valida com a suíte canônica e, com testes verdes, commita (sem push —
#      decisão do dono de 2026-10-08: "pode commitar").
# Deploy/restart/systemctl continuam PROIBIDOS para a sessão (regra 13).

#: Estado da sessão (painel lê; este processo escreve — atômico).
SESSAO_ESTADO_FILE: Path = Path("data/dev_sessao.json")

#: Caixa de desenvolvimento: mensagens sistema ↔ dono durante a sessão.
SESSAO_CAIXA_FILE: Path = Path("data/dev_caixa.json")

#: Fonte da ideia do dono — a MESMA fila do canal de desenvolvimento.
IDEIA_FILE: Path = PEDIDO_FILE

#: Marcador de autorização: linha da CLI que começo exatamente com isto.
MARCADOR_AUTORIZACAO: str = "[AUTORIZACAO]"

#: Espera máxima pela resposta do dono na caixa (30 min — decisão 5).
SESSAO_AUTORIZACAO_TIMEOUT_S: int = 1800

#: Máximo de pedidos de autorização por sessão (sem loop infinito).
SESSAO_MAX_AUTORIZACOES: int = 5

#: Intervalo de varredura da caixa durante a espera.
SESSAO_POLL_S: float = 2.0

#: Seletor de CLI do painel (--cli); 'auto' = cascata oficial.
CLI_SESSAO_OPCOES: tuple[str, ...] = ("auto", "freebuff", "opencode", "kilo")

#: Instrução de sistema do modo sessão — código puro NÃO é o contrato aqui:
#: a CLI é um agente com ferramentas, que lê o repo e edita arquivos.
INSTRUCAO_SESSAO: str = (
    "Você é o desenvolvedor do OmegaDrakon. O diretório atual é o repositório "
    "do projeto — trate-o como seu workspace de trabalho.\n"
    "ANTES de codar, leia: (1) iniciar/session.json e iniciar/RULES.md "
    "(estado da sessão e regras); (2) docs/ — README_VERSAO.md, "
    "REGRAS_DE_TRABALHO.md, VERSIONAMENTO.md e o topo do CHANGELOG.md; "
    "(3) txt.txt (recados e ideias do dono) e pedido.txt (esta tarefa).\n"
    "Regras OBRIGATÓRIAS:\n"
    "- implemente a ideia com código e testes no padrão da casa (pytest);\n"
    "- NÃO rode git commit nem git push (quem commita é o orquestrador ao fim);\n"
    "- NÃO reinicie serviços (systemctl), NÃO edite .env nem backups/;\n"
    "- se a tarefa exigir deploy, reinício, credencial ou qualquer ação que "
    "precise da autorização do dono, TERMINE a resposta com uma linha que "
    "comece com [AUTORIZACAO] e a pergunta — e não siga até responderem;\n"
    "- sem markdown e sem cercas de código; termine com um resumo curto do "
    "que mudou (arquivos) e do resultado dos testes;\n"
    "- se já existe ou não puder ser feito, diga isso em vez de inventar."
)


def montar_prompt_sessao(ideia: str, historico: str = "") -> str:
    """Monta o prompt do modo sessão: instrução + ideia + histórico da rodada."""
    partes = [INSTRUCAO_SESSAO, "", "Ideia do dono (pedido.txt):", ideia.strip()]
    if historico.strip():
        partes += ["", "Histórico desta sessão:", historico.strip()]
    return "\n".join(partes)


def extrair_autorizacao(saida: str) -> str | None:
    """Devolve a pergunta de autorização, se a CLI emitir o marcador.

    O marcador precisa estar no COMEÇO de uma linha (é o contrato que o
    prompt ensina); sem marcador → None (sessão segue sem pausa).
    """
    for linha in (saida or "").splitlines():
        limpa = linha.strip()
        if limpa.startswith(MARCADOR_AUTORIZACAO):
            pergunta = limpa[len(MARCADOR_AUTORIZACAO):].strip()
            if pergunta:
                return pergunta
    return None


def resolver_clis(escolha: str) -> tuple[CliSpec, ...]:
    """Resolve o seletor do painel para a cascata de execução.

    'auto' → cascata oficial (Freebuff → OpenCode → Kilo); nome de uma CLI →
    só ela; qualquer outra coisa → ValueError (o handler responde 400).
    """
    chave = (escolha or "auto").strip().lower()
    if chave == "auto":
        return CLIS
    for spec in CLIS:
        if chave in (spec.nome.lower(), spec.binario.lower()):
            return (spec,)
    raise ValueError(f"CLI desconhecida: {escolha!r}")


# -- Estado e caixa (JSON atômico, padrão do canal) ------------------------


def _agora_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _gravar_json(caminho: Path, objeto: object) -> None:
    """Escrita ATÔMICA (tmp + rename) — o painel lê concorrentemente."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    tmp.write_text(json.dumps(objeto, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(caminho)


def gravar_estado(estado: dict, caminho: Path = SESSAO_ESTADO_FILE) -> None:
    estado["updated_at"] = _agora_iso()
    _gravar_json(caminho, estado)


def ler_caixa(caminho: Path = SESSAO_CAIXA_FILE) -> list[dict]:
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return dados if isinstance(dados, list) else []


def gravar_caixa(mensagens: list[dict], caminho: Path = SESSAO_CAIXA_FILE) -> None:
    _gravar_json(caminho, mensagens)


def publicar_na_caixa(
    de: str, texto: str, tipo: str, caminho: Path = SESSAO_CAIXA_FILE
) -> dict:
    """Acrescenta uma mensagem na caixa de desenvolvimento e devolve a entrada."""
    mensagem = {
        "id": str(time.time_ns()),
        "ts": _agora_iso(),
        "de": de,
        "tipo": tipo,
        "texto": texto,
        "respondida": False,
    }
    mensagens = ler_caixa(caminho)
    mensagens.append(mensagem)
    gravar_caixa(mensagens, caminho)
    return mensagem


def aguardar_resposta_dono(
    ja_ditadas: int,
    caminho: Path = SESSAO_CAIXA_FILE,
    timeout_s: int = SESSAO_AUTORIZACAO_TIMEOUT_S,
    intervalo_s: float = SESSAO_POLL_S,
    dormir: Callable[[float], None] = time.sleep,
) -> str | None:
    """Espera o dono responder na caixa — devolve o texto ou None no timeout.

    `ja_ditadas` é a contagem de mensagens DO DONO antes do pedido: só a
    resposta NOVA vale (a história inteira nunca é re-enviada à CLI).
    """
    tentativas = max(1, int(timeout_s / max(intervalo_s, 0.001)))
    for _ in range(tentativas):
        dono = [m for m in ler_caixa(caminho) if m.get("de") == "dono"]
        if len(dono) > ja_ditadas:
            texto = str(dono[-1].get("texto", "")).strip()
            if texto:
                return texto
        dormir(intervalo_s)
    return None


def _marcar_respondidas(pergunta: str, caminho: Path = SESSAO_CAIXA_FILE) -> None:
    """Marca como respondida a última pergunta igual — só cosmético do painel."""
    mensagens = ler_caixa(caminho)
    for mensagem in reversed(mensagens):
        if mensagem.get("de") == "sistema" and mensagem.get("texto") == pergunta:
            mensagem["respondida"] = True
            break
    gravar_caixa(mensagens, caminho)


# -- Validação e commit (regras 6 e decisão 2 do dono) ----------------------


def _rodar(cmd: list[str], cwd: Path) -> tuple[int, str]:
    """Executa um comando e devolve (código, saída combinada) — nunca exceção."""
    try:
        resultado = subprocess.run(  # noqa: S603 — comandos fixos desta casa
            cmd, capture_output=True, text=True, timeout=3600, check=False, cwd=cwd
        )
    except OSError as erro:
        return 1, str(erro)
    return resultado.returncode, (resultado.stdout or "") + (resultado.stderr or "")


#: Comando canônico da suíte (mesmo do CI: .coveragerc + gate 90).
SUITE_CANONICA: tuple[str, ...] = (
    "-m", "pytest", "--cov", "--cov-config=.coveragerc", "--cov-fail-under=90", "-q",
)


def validar_sessao(
    rodar: Callable[[list[str], Path], tuple[int, str]] = _rodar,
    repo: Path = Path("."),
) -> dict:
    """Roda a suíte canônica e mede o diff do working tree.

    Devolve {ok, testes, arquivos, diff} — `ok` É o gate de cobertura
    (o pytest sai != 0 quando o gate derruba, como no CI).
    """
    rc_testes, saida_testes = rodar([sys.executable, *SUITE_CANONICA], repo)
    rc_diff, saida_diff = rodar(["git", "status", "--porcelain"], repo)
    arquivos = _arquivos_do_porcelain(saida_diff)
    linhas = [l.strip() for l in saida_testes.splitlines() if l.strip()]
    resumo = next((l for l in reversed(linhas) if "passed" in l or "failed" in l), linhas[-1] if linhas else "")
    return {
        "ok": rc_testes == 0,
        "testes": resumo[:200],
        "arquivos": arquivos,
        "diff": " · ".join(arquivos[:20]),
    }


def _arquivos_do_porcelain(porcelain: str) -> list[str]:
    """Linhas `git status --porcelain` → caminhos (resolvendo renames e aspas)."""
    arquivos: list[str] = []
    for linha in porcelain.splitlines():
        if len(linha) < 4:
            continue
        caminho = linha[3:]
        if " -> " in caminho:
            caminho = caminho.split(" -> ")[-1]
        caminho = caminho.strip().strip('"')
        if caminho:
            arquivos.append(caminho)
    return arquivos


#: Prefixos que NUNCA entram no commit da sessão (dados pessoais/estado).
COMMIT_EXCECOES: tuple[str, ...] = ("backups/", "data/", "logs/")


def commitar_sessao(
    titulo: str,
    rodar: Callable[[list[str], Path], tuple[int, str]] = _rodar,
    repo: Path = Path("."),
) -> dict | None:
    """Commita o diff da sessão (sem push — decisão do dono de 08/10).

    Só staged: arquivos alterados/novos FORA de backups/, data/ e logs/
    (snapshots pessoais ficam fora do git por decisão antiga). Sem diff →
    None (nada a commitar, não é falha).
    """
    _rc, saida = rodar(["git", "status", "--porcelain"], repo)
    alvos = [
        caminho
        for caminho in _arquivos_do_porcelain(saida)
        if not caminho.startswith(COMMIT_EXCECOES)
    ]
    if not alvos:
        return None
    rc_add, erro_add = rodar(["git", "add", "--", *alvos], repo)
    if rc_add != 0:
        return {"ok": False, "erro": erro_add[-400:]}
    primeira = titulo.strip().splitlines()[0][:72] if titulo.strip() else "sessão de desenvolvimento"
    rc_commit, saida_commit = rodar(
        [
            "git", "commit",
            "-m", f"feat(dev): {primeira}",
            "-m", "Sessão de desenvolvimento on-demand (orquestrador --sessao).",
        ],
        repo,
    )
    if rc_commit != 0:
        return {"ok": False, "erro": saida_commit[-400:]}
    _rc_sha, saida_sha = rodar(["git", "rev-parse", "--short", "HEAD"], repo)
    return {"ok": True, "commit": saida_sha.strip(), "arquivos": len(alvos)}


# -- Ciclo de vida da sessão ------------------------------------------------


def _encerrar(
    estado: dict,
    status: str,
    motivo: str,
    arquivo_estado: Path,
    arquivo_caixa: Path,
    detalhe: str = "",
) -> dict:
    """Fecha a sessão: estado final + aviso na caixa (nunca some sem registro)."""
    estado["status"] = status
    estado["motivo"] = motivo
    estado["ativo"] = False
    gravar_estado(estado, arquivo_estado)
    texto = f"Sessão {status}: {motivo}"
    if detalhe:
        texto += f" — {detalhe}"
    publicar_na_caixa("sistema", texto, "info", arquivo_caixa)
    log.info("Sessão encerrada | status=%s | motivo=%s", status, motivo)
    return estado


def executar_sessao(
    ideia: str,
    *,
    cli: str = "auto",
    clis: Sequence[CliSpec] | None = None,
    executar: Callable[[CliSpec, str], str | None] = executar_cli,
    arquivo_estado: Path = SESSAO_ESTADO_FILE,
    arquivo_caixa: Path = SESSAO_CAIXA_FILE,
    esperar_resposta: Callable[[int], str | None] | None = None,
    validar: Callable[[], dict] | None = None,
    commitar: Callable[[str], dict | None] | None = None,
) -> dict:
    """Uma sessão completa de desenvolvimento: CLI → autorizações → validação → commit.

    Tudo injetável (estado/caixa em tmp_path nos testes); os defaults são as
    implementações reais. Devolve o estado final.
    """
    escolha = clis if clis is not None else resolver_clis(cli)
    if esperar_resposta is None:
        esperar_resposta = lambda ja_ditadas: aguardar_resposta_dono(  # noqa: E731
            ja_ditadas, arquivo_caixa
        )
    if validar is None:
        validar = validar_sessao
    if commitar is None:
        commitar = commitar_sessao

    estado: dict = {
        "ativo": True,
        "pid": os.getpid(),
        "cli": cli,
        "rodando": " → ".join(spec.nome for spec in escolha),
        "cli_usada": "",
        "status": "executando",
        "started_at": _agora_iso(),
        "ideia_preview": ideia.strip()[:2000],
        "rodada": 0,
        "autorizacoes": 0,
        "testes": "",
        "diff": "",
        "commit": "",
        "motivo": "",
    }
    gravar_estado(estado, arquivo_estado)
    publicar_na_caixa(
        "sistema", f"Sessão iniciada — CLI: {estado['rodando']}.", "info", arquivo_caixa
    )

    historico = ""
    resposta_cli: str | None = None
    for rodada in range(1, SESSAO_MAX_AUTORIZACOES + 2):
        estado["rodada"] = rodada
        estado["status"] = "executando"
        gravar_estado(estado, arquivo_estado)
        prompt = montar_prompt_sessao(ideia, historico)
        resposta_cli = None
        for spec in escolha:
            resposta_cli = executar(spec, prompt)
            if resposta_cli is not None:
                estado["cli_usada"] = spec.nome
                break
        if resposta_cli is None:
            return _encerrar(
                estado, "falhou", "todas_as_clis_falharam",
                arquivo_estado, arquivo_caixa,
            )
        pergunta = extrair_autorizacao(resposta_cli)
        if pergunta is None:
            break
        estado["autorizacoes"] += 1
        if estado["autorizacoes"] > SESSAO_MAX_AUTORIZACOES:
            return _encerrar(
                estado, "falhou", "limite_de_autorizacoes_excedido",
                arquivo_estado, arquivo_caixa,
            )
        ja_ditadas = len([m for m in ler_caixa(arquivo_caixa) if m.get("de") == "dono"])
        publicar_na_caixa(
            "sistema", pergunta, "pedir_autorizacao", arquivo_caixa
        )
        estado["status"] = "aguardando_autorizacao"
        gravar_estado(estado, arquivo_estado)
        log.info("Sessão aguardando autorização: %s", pergunta[:120])
        resposta = esperar_resposta(ja_ditadas)
        if not resposta:
            return _encerrar(
                estado, "falhou", "autorizacao_nao_respondida",
                arquivo_estado, arquivo_caixa,
                detalhe=f"pergunta: {pergunta[:120]}",
            )
        _marcar_respondidas(pergunta, arquivo_caixa)
        historico += (
            f"\n[Autorização pedida] {pergunta}\n[Resposta do dono] {resposta}\n"
        )

    estado["status"] = "validando"
    gravar_estado(estado, arquivo_estado)
    resultado = validar()
    estado["testes"] = str(resultado.get("testes", ""))
    estado["diff"] = str(resultado.get("diff", ""))
    if not resultado.get("ok"):
        return _encerrar(
            estado, "falhou", "testes_vermelhos",
            arquivo_estado, arquivo_caixa,
            detalhe=estado["testes"][:120],
        )
    if not resultado.get("arquivos"):
        return _encerrar(
            estado, "concluido", "nada_mudou",
            arquivo_estado, arquivo_caixa,
            detalhe="sem diff no working tree",
        )
    info_commit = commitar(ideia)
    if info_commit and info_commit.get("ok"):
        estado["commit"] = str(info_commit.get("commit", ""))
        motivo = "implantado"
    else:
        motivo = "commit_nao_realizado"
    detalhe = estado["commit"] or str((info_commit or {}).get("erro", ""))[:120]
    return _encerrar(
        estado, "concluido", motivo, arquivo_estado, arquivo_caixa, detalhe=detalhe
    )


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------


def main_sessao(cli: str = "auto") -> int:
    """Modo sessão: lê a ideia do pedido.txt e executa UMA sessão de dev."""
    try:
        ideia = IDEIA_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        ideia = ""
    if not ideia:
        log.error(
            "Sem ideia: %s vazio/inexistente — sessão não iniciada (o painel valida antes)",
            IDEIA_FILE,
        )
        return 2
    try:
        clis = resolver_clis(cli)
    except ValueError as erro:
        log.error("%s", erro)
        return 2
    log.info(
        "Sessão de desenvolvimento | cli=%s | ideia=%.120s",
        cli,
        ideia.replace("\n", " "),
    )
    estado = executar_sessao(ideia, cli=cli, clis=clis)
    log.info(
        "Sessão finalizada | status=%s | motivo=%s | testes=%s",
        estado.get("status"),
        estado.get("motivo"),
        estado.get("testes"),
    )
    return 0 if estado.get("status") == "concluido" else 1


def main(argv: Sequence[str] | None = None) -> int:
    """Ponto de entrada: carrega o .env, configura o log e escolhe o modo.

    Padrão (sem flag) = fila do monitor — compatível com o
    deploy/od-orchestrator.service. `--sessao` é o que o painel /admin
    spawna no botão ▶ Ativar desenvolvimento.
    """
    parser = argparse.ArgumentParser(description="OmegaDrakon — orquestrador de CLIs")
    parser.add_argument(
        "--sessao", action="store_true",
        help="modo sessão de desenvolvimento on-demand (lê a ideia do pedido.txt)",
    )
    parser.add_argument(
        "--cli", default="auto", choices=CLI_SESSAO_OPCOES,
        help="CLI do modo sessão (default: auto = cascata Freebuff→OpenCode→Kilo)",
    )
    parser.add_argument(
        "--fila", action="store_true",
        help="modo fila (default, explícito por causa do serviço)",
    )
    args = parser.parse_args(argv)

    # O .env da raiz carrega GEMINI_API_KEY/GROQ_API_KEY e o OD_* do sistema.
    load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    chaves_presentes = [chave for chave in ENV_KEYS if os.environ.get(chave)]
    log.info("Chaves carregadas do .env: %s", ", ".join(chaves_presentes) or "nenhuma")

    if args.sessao:
        return main_sessao(args.cli)
    monitorar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
