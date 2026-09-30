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
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import ast
import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
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
    #: Argumentos fixos ANTES do prompt (ex: ['ask']).
    args_antes: tuple[str, ...]
    #: Argumentos fixos DEPOIS do prompt (ex: ['--auto']).
    args_depois: tuple[str, ...] = ()


#: Cascata oficial de fallback — a ordem É a política (Freebuff primeiro).
CLIS: tuple[CliSpec, ...] = (
    CliSpec(nome="Freebuff", binario="freebuff", args_antes=("ask",)),
    CliSpec(nome="OpenCode", binario="opencode", args_antes=("run",)),
    CliSpec(nome="Kilo", binario="kilo", args_antes=("run",), args_depois=("--auto",)),
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
    if shutil.which(spec.binario) is None:
        log.info("%s indisponível (binário '%s' não encontrado)", spec.nome, spec.binario)
        return None

    comando: list[str] = [spec.binario, *spec.args_antes, prompt, *spec.args_depois]
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
# Entrada
# ---------------------------------------------------------------------------


def main() -> int:
    """Ponto de entrada: carrega o .env, configura o log e sobe o monitor."""
    # O .env da raiz carrega GEMINI_API_KEY/GROQ_API_KEY e o OD_* do sistema.
    load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    chaves_presentes = [chave for chave in ENV_KEYS if os.environ.get(chave)]
    log.info("Chaves carregadas do .env: %s", ", ".join(chaves_presentes) or "nenhuma")

    monitorar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
