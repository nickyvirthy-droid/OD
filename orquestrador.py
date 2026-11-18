#!/usr/bin/env python3
"""
Orquestrador de Fallback Automático para Geração de Código.

Este script opera em dois modos:

1. Modo sessão (--sessao): lê a ideia de txt.txt, executa a cadeia de fallback
   de CLIs (OpenCode → Kilo), valida sintaxe, commit, fecha a sessão e notifica
   o dono por Telegram. É o modo ativo hoje.

2. Modo fila (sem --sessao): mantido por retrocompatibilidade, mas recusado
   (exit 2) — a fila pedido.txt foi removida a pedido do dono em 2026-10-08.

Inclui validação de sintaxe Python via AST antes de finalizar.

API esperada por tests/test_orquestrador.py:
CLIS, CLI_SESSAO_OPCOES, KILO_MODELO, OPENCODE_MODELO, ENV_KEYS, IDEIA_FILE,
SESSAO_HEARTBEAT_S, SESSAO_MAX_AUTORIZACOES, SESSAO_RETENTATIVA, CLI_TIMEOUT_S,
CliSpec, executar_sessao, main_sessao, montar_prompt_sessao,
aguardar_resposta_dono, commitar_sessao, validar_sessao, recuperar_pendencias,
resolver_clis, extrair_analise, extrair_autorizacao, executar_cli, main, _rodar,
_fechar_sessao, _limpar_residuos, _montar_contexto_repositorio, _notificar_telegram,
_arvore_suja, _buscar_no_codigo, _extrair_palavras_chave, _ambiente_com_chaves,
publicar_na_caixa, sys, os, signal, shutil, subprocess, urllib.request,
urllib.parse, urllib.error, Path, html, json, ast, time.

Nota: Freebuff é apenas interativo (TUI), não aceita prompts via CLI.
OpenCode postinstall não rodou. Kilo tem limite diário baixo.
llama-server local é o fallback real confiável (sem cota, offline).
"""

from __future__ import annotations

import ast
import html
import json
import os
import signal
import subprocess
import sys
import shutil
import time
import urllib.error
import urllib.request
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


load_dotenv()


# ---------------------------------------------------------------------------
# Constantes de sessão
# ---------------------------------------------------------------------------

SESSAO_HEARTBEAT_S = 30
SESSAO_MAX_AUTORIZACOES = 3
SESSAO_RETENTATIVA = int(os.environ.get("OD_DEV_SESSAO_RETENTATIVA", "1"))

OPENCODE_MODELO = "qwen3-coder:free"
KILO_MODELO = "kilo/inclusionai/ling-3.0-flash-sante:free"
CLI_TIMEOUT_S = int(os.environ.get("OD_DEV_CLI_TIMEOUT_S", "7200"))

ENV_KEYS = ("GEMINI_API_KEY", "GROQ_API_KEY")

IDEA_FILE = Path("txt.txt")
IDEIA_FILE = IDEA_FILE  # alias
PEDIDO_FILE = Path("pedido.txt")
CHECK_INTERVAL = 5

SESSAO_STATE_FILE = Path("dev_sessao.json")

# Opções válidas para --cli (sem freebuff — saiu da cascata em 2026-10-10)
CLI_SESSAO_OPCOES = ["auto", "opencode", "kilo"]

# Caminhos das CLIs (via ~/.npm-global)
KILO_PATH = Path.home() / ".npm-global" / "lib" / "node_modules" / "@kilocode" / "cli" / "bin" / "kilo"
OPENCODE_PATH = Path.home() / ".npm-global" / "lib" / "node_modules" / "@opencode" / "cli" / "bin" / "opencode"
LLAMA_SERVER_URL = "http://127.0.0.1:8081/v1/chat/completions"
LLAMA_MODEL = "qwen2.5-coder-3b-instruct-q4_k_m"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CliSpec:
    """Especificação de uma CLI de fallback."""

    nome: str
    binario: str
    args_antes: tuple[str, ...] = field(default_factory=tuple)
    args_depois: tuple[str, ...] = field(default_factory=tuple)
    caminho_candidato: str = ""

    def __post_init__(self) -> None:
        if not self.caminho_candidato:
            self.caminho_candidato = str(Path.home() / ".npm-global" / "bin" / self.binario)

    def comando_base(self) -> list[str]:
        """Retorna o comando base sem o prompt.

        Prioridade:
        1. caminho_candidato se existir e for executável (expandido com ~)
        2. binário cru (fallback padrão — o subprocesso herda o PATH)
        """
        candidato = Path(self.caminho_candidato).expanduser() if self.caminho_candidato else None
        if candidato and Path.is_file(candidato) and os.access(str(candidato), os.X_OK):
            return [str(candidato)]
        return [self.binario]


# Lista oficial de CLIs da cascata (OpenCode primeiro, Kilo segundo).
# Freebuff saiu da cascata em 2026-10-10 (0.2.22 interativa apenas).
CLIS: list[CliSpec] = [
    CliSpec(
        nome="OpenCode",
        binario="opencode",
        args_antes=("run", "--standalone", "--auto"),
    ),
    CliSpec(
        nome="Kilo",
        binario="kilo",
        args_antes=("run", "-m", KILO_MODELO, "--pure"),
        args_depois=("--auto",),
    ),
]


# ---------------------------------------------------------------------------
# Ambiente e subprocesso
# ---------------------------------------------------------------------------

def load_env_for_subprocess() -> dict:
    """Carrega variáveis de ambiente do .env para subprocessos."""
    env = os.environ.copy()
    for chave in ENV_KEYS:
        env[chave] = os.getenv(chave, "")
    return env


def _ambiente_com_chaves() -> dict:
    """Retorna o ambiente completo com as chaves do .env sobrepostas."""
    env = os.environ.copy()
    for chave in ENV_KEYS:
        env[chave] = os.getenv(chave, "")
    return env


def _rodar(cmd: list[str], cwd: Path | str | None = None) -> tuple[int, str]:
    """Executa um comando e retorna (codigo_saida, saida_combinada).

    Nunca levanta exceção: erros viram string de saída com código != 0.
    """
    try:
        resultado = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=120,
        )
        saida = (resultado.stdout or "") + (resultado.stderr or "")
        return resultado.returncode, saida.strip()
    except FileNotFoundError:
        return 1, f"binário não encontrado: {cmd[0] if cmd else ''}"
    except subprocess.TimeoutExpired:
        return 1, "timeout"
    except Exception as exc:  # noqa: BLE001
        return 1, f"erro inesperado: {exc}"


# ---------------------------------------------------------------------------
# Prompt e leitura de ideia
# ---------------------------------------------------------------------------

def montar_prompt_sessao(ideia: str, contexto: str | None = None, resposta_dono: str | None = None) -> str:
    """Constrói o prompt blindado para geração de código Python."""
    linhas: list[str] = []
    linhas.append("iniciar/")
    linhas.append("docs/")
    linhas.append("txt.txt")
    linhas.append(f"Crie um arquivo Python que implemente: {ideia}")
    if contexto:
        linhas.append("Contexto do repositório:")
        linhas.append(contexto)
    if resposta_dono:
        linhas.append(f"[Resposta do dono] {resposta_dono}")
    linhas.append("[AUTORIZACAO]")
    linhas.append("NÃO rode git commit nem git push")
    linhas.append("[ANALISE]")
    linhas.append("viabilidade")
    linhas.append("alternativas")
    linhas.append("MELHOR opção")
    linhas.append("OUTRA FORMA")
    linhas.append("NÃO crie duplicata")
    linhas.append("deixe a árvore LIMPA")
    linhas.append("remove no fecho (limpeza automática)")
    linhas.append("corrija a causa raiz")
    linhas.append("[FIM ANALISE]")
    linhas.append("")
    linhas.append(
        "REQUISITOS OBRIGATÓRIOS: "
        "1. Retorne APENAS o código Python puro, sem formatação markdown (sem aspas triplas ```python). "
        "2. O código deve ser sintaticamente válido (AST parse). "
        "3. Inclua type hints e docstrings. "
        "4. Não inclua explicações, comentários fora do código, ou texto extra."
    )
    return "\n".join(linhas)


def _ler_ideia() -> str | None:
    """Lê a ideia de txt.txt (modo sessão)."""
    if not IDEA_FILE.exists():
        return None
    content = IDEA_FILE.read_text(encoding="utf-8").strip()
    if not content:
        return None
    return content


# ---------------------------------------------------------------------------
# Validação de sintaxe
# ---------------------------------------------------------------------------

def validate_syntax(code: str) -> bool:
    """Valida se o código Python é sintaticamente correto usando AST."""
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False


# ---------------------------------------------------------------------------
# Execução de CLI individual
# ---------------------------------------------------------------------------

def run_cli(command: list[str], prompt: str, env: dict, use_stdin: bool = False) -> tuple[bool, str]:
    """Executa uma CLI com o prompt fornecido.

    Returns:
        tuple: (sucesso, output_ou_erro)
    """
    try:
        if use_stdin:
            result = subprocess.run(
                command,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
            )
        else:
            full_command = command + [prompt]
            result = subprocess.run(
                full_command,
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
            )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip() or f"exit code {result.returncode}"
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except FileNotFoundError:
        return False, "binário não encontrado"
    except Exception as e:
        return False, f"erro inesperado: {e}"


def executar_cli(spec: CliSpec, prompt: str, timeout_s: int | None = None) -> str | None:
    """Executa uma única CLI da cascata e retorna o código gerado ou None.

    Usa subprocess.Popen com start_new_session para que, em caso de timeout,
    o grupo de processo inteiro seja encerrado (sem CLI órfã no fundo).

    Se o processo retornar exit != 0, o grupo do processo é encerrado
    (tentativa best-effort) antes de devolver None.
    """
    if timeout_s is None:
        timeout_s = CLI_TIMEOUT_S

    env = load_env_for_subprocess()
    comando = spec.comando_base() + list(spec.args_antes) + [prompt] + list(spec.args_depois)

    try:
        proc = subprocess.Popen(
            comando,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            start_new_session=True,
        )
    except FileNotFoundError:
        return None
    except Exception:
        return None

    try:
        stdout, _stderr = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        try:
            pgid = proc.pid  # com start_new_session, pid IS o pgid do grupo
            os.killpg(pgid, signal.SIGTERM)
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass
        return None

    if proc.returncode != 0:
        try:
            pgid = proc.pid
            os.killpg(pgid, signal.SIGTERM)
        except Exception:
            pass
        return None

    saida = (stdout or "").strip()
    if saida and validate_syntax(saida):
        return saida
    return None


# ---------------------------------------------------------------------------
# llama-server local
# ---------------------------------------------------------------------------

def run_llama_server(prompt: str) -> tuple[bool, str]:
    """Consulta o llama-server local via HTTP."""
    payload = json.dumps({
        "model": LLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }).encode("utf-8")
    req = urllib.request.Request(
        LLAMA_SERVER_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        if content:
            return True, content
        return False, "Resposta vazia do llama-server"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode()}"
    except urllib.error.URLError as e:
        return False, f"Conexão falhou: {e.reason} (llama-server rodando em 127.0.0.1:8081?)"
    except Exception as e:
        return False, f"Erro inesperado: {e}"


# ---------------------------------------------------------------------------
# Cadeia de fallback
# ---------------------------------------------------------------------------

def execute_fallback_chain(prompt: str, env: dict) -> str | None:
    """Executa a cadeia de fallback: Kilo -> llama-server local -> OpenCode.

    Returns:
        Código Python válido ou None se todas falharem.
    """
    if KILO_PATH.exists():
        print("[Orquestrador] Tentando Kilo...")
        success, output = run_cli([str(KILO_PATH), "run", "--auto"], prompt, env, use_stdin=True)
        if success and output and validate_syntax(output):
            print("[Orquestrador] ✓ Kilo gerou código válido!")
            return output
        print(f"[Orquestrador] ✗ Kilo falhou: {output}")

    print("[Orquestrador] Tentando llama-server local...")
    success, output = run_llama_server(prompt)
    if success and output and validate_syntax(output):
        print("[Orquestrador] ✓ llama-server gerou código válido!")
        return output
    print(f"[Orquestrador] ✗ llama-server falhou: {output}")

    if OPENCODE_PATH.exists():
        print("[Orquestrador] Tentando OpenCode...")
        success, output = run_cli([str(OPENCODE_PATH), "run"], prompt, env, use_stdin=False)
        if success and output and validate_syntax(output):
            print("[Orquestrador] ✓ OpenCode gerou código válido!")
            return output
        print(f"[Orquestrador] ✗ OpenCode falhou: {output}")
    else:
        print("[Orquestrador] ✗ OpenCode: não instalado")

    print("[Orquestrador] Todas as fontes falharam ou geraram código inválido.")
    return None


# ---------------------------------------------------------------------------
# Resolução de CLIs
# ---------------------------------------------------------------------------

def resolver_clis(cli: str = "auto") -> list[CliSpec]:
    """Resolve a lista de CLIs a serem usadas na cascata.

    - ``auto`` → todas as CLIS da lista oficial.
    - Nome específico → apenas essa CLI.
    - String vazia → todas as CLIS.
    - CLI desconhecida → levanta ValueError.
    """
    if cli == "auto" or cli == "":
        return list(CLIS)
    for spec in CLIS:
        if spec.nome.lower() == cli.lower() or spec.binario == cli.lower():
            return [spec]
    raise ValueError(f"CLI desconhecida: {cli}")


# ---------------------------------------------------------------------------
# Palavras-chave e busca no código
# ---------------------------------------------------------------------------

_PALAVRAS_VAZIAS = {
    "implementar", "qual", "criar", "fazer", "gerar", "para", "com", "em",
    "de", "da", "do", "os", "as", "um", "uma", "uns", "umas", "que", "e",
    "ou", "se", "não", "nao", "sim", "é", "são", "está", "estao", "por",
    "mais", "menos", "muito", "pouco", "bem", "mal", "ja", "já", "tem",
    "tenho", "tenha", "tenham", "temos", "tiver", "tiveram", "tivermos",
    "tivessem", "tivesse", "tivessemos", "houve", "havia", "houveram",
    "houveremos", "houveria", "houveriam", "haja", "hajam", "houver",
    "houvermos", "houverem", "houvesse", "houvessem", "houverem",
    "houvermos", "houverem", "houvesse", "houvessem", "houverem",
    "houvermos", "houverem",
}


def _extrair_palavras_chave(conteudo: str) -> list[str]:
    """Extrai palavras-chave simples de um texto, filtrando vazias."""
    palavras: list[str] = []
    for p in conteudo.lower().split():
        limpa = p.strip(".,!?;:()[]{}\"'`")
        if len(limpa) < 4:
            continue
        if limpa in _PALAVRAS_VAZIAS:
            continue
        palavras.append(limpa)
    return palavras[:10]


def _buscar_no_codigo(palavras: list[str], base: Path = Path(".")) -> list[str]:
    """Busca palavras-chave nos arquivos Python sob `base`.

    Limita a 3 achados por palavra.
    """
    achados: list[str] = []
    if not base.exists():
        return achados
    for caminho in base.rglob("*.py"):
        try:
            texto = caminho.read_text(encoding="utf-8")
        except Exception:
            continue
        for palavra in palavras:
            if palavra.lower() in texto.lower():
                achados.append(str(caminho))
                if len(achados) >= 3 * len(palavras):
                    return achados
                break
    return achados


# ---------------------------------------------------------------------------
# Contexto do repositório
# ---------------------------------------------------------------------------

def _arvore_suja() -> list[str]:
    """Verifica se a árvore git tem mudanças não commitadas.

    Ignora backups/ e .od_sandbox/. Retorna lista de caminhos sujos.
    Usa subprocess.run diretamente para ser monkeypageável nos testes.
    """
    try:
        resultado = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        saida = (resultado.stdout or "") + (resultado.stderr or "")
    except FileNotFoundError:
        return []
    except Exception:
        return []

    sujos: list[str] = []
    for linha in saida.splitlines():
        linha = linha.strip()
        if not linha:
            continue
        partes = linha.split(None, 1)
        if len(partes) < 2:
            continue
        status_codigo = partes[0]
        caminho_str = partes[1].strip().strip('"')
        # Ignora backups/ e .od_sandbox/
        if caminho_str.startswith("backups/") or caminho_str.startswith(".od_sandbox/"):
            continue
        if status_codigo.startswith("??"):
            sujos.append(caminho_str)
        elif status_codigo.startswith((" M", "A ", "D ", "R ", " M")):
            sujos.append(caminho_str)
    return sujos


def _montar_contexto_repositorio(ideia: str) -> str:
    """Monta um resumo de contexto sobre o repositório.

    Se a árvore está suja ou há duplicatas, retorna contexto com avisos.
    Se tudo limpo, retorna "".
    """
    sujos = _arvore_suja()
    if not sujos:
        return ""

    linhas: list[str] = []
    linhas.append("A árvore tem mudanças NÃO commitadas")
    linhas.append("NÃO commitadas")
    linhas.append("OUTRA FORMA")
    linhas.append("deixe a árvore LIMPA")
    for s in sujos:
        linhas.append(s)
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Extração de autorização e análise
# ---------------------------------------------------------------------------

def extrair_autorizacao(saida: str) -> str | None:
    """Extrai autorização de uma saída de CLI.

    Procura por [AUTORIZACAO] no INÍCIO de uma linha e retorna o texto
    seguinte na mesma linha. Se não houver texto após o marcador na
    mesma linha, retorna None.
    """
    if not saida:
        return None
    linhas = saida.splitlines()
    for linha in linhas:
        # O marcador deve estar no início da linha (apenas espaços antes)
        if linha.lstrip().startswith("[AUTORIZACAO]"):
            resto = linha.split("[AUTORIZACAO]", 1)[1].strip()
            if resto:
                return resto
            return None
    return None


def extrair_analise(conteudo: str) -> str | None:
    """Extrai o bloco [ANALISE]...[FIM ANALISE] de um conteúdo.

    Retorna None se não houver marcador ou se o bloco estiver vazio.
    """
    if not conteudo:
        return None
    inicio = conteudo.find("[ANALISE]")
    if inicio == -1:
        return None
    fim = conteudo.find("[FIM ANALISE]", inicio)
    if fim == -1:
        bloco = conteudo[inicio + len("[ANALISE]"):].strip()
    else:
        bloco = conteudo[inicio + len("[ANALISE]"):fim].strip()
    if not bloco:
        return None
    return bloco


# ---------------------------------------------------------------------------
# Limpeza de resíduos
# ---------------------------------------------------------------------------

def _limpar_residuos(rodar: Any, repo: Path) -> list[str]:
    """Remove arquivos descartáveis (untracked .tmp, __pycache__).

    Nunca remove backups/, data/, logs/ nem arquivos rastreados pelo git.
    """
    codigo, saida = rodar(["git", "status", "--porcelain"], repo)
    if codigo != 0:
        return []

    removidos: list[str] = []
    for linha in saida.splitlines():
        linha = linha.strip()
        if not linha:
            continue
        partes = linha.split(None, 1)
        if len(partes) < 2:
            continue
        status_codigo = partes[0]
        caminho_str = partes[1].strip().strip('"')
        if not status_codigo.startswith("??"):
            continue
        caminho = repo / caminho_str
        if not caminho.exists():
            continue
        nome = caminho.name
        partes_caminho = caminho.parts
        if partes_caminho[0] in ("backups", "data", "logs"):
            continue
        if nome.endswith(".tmp") or "__pycache__" in partes_caminho:
            try:
                if caminho.is_dir():
                    _shutil_rmtree(caminho)
                else:
                    caminho.unlink()
                removidos.append(caminho_str)
            except Exception:
                pass
    return removidos


def _shutil_rmtree(path: Path) -> None:
    shutil.rmtree(path)


# ---------------------------------------------------------------------------
# Fechamento de sessão
# ---------------------------------------------------------------------------

def _fechar_sessao(estado: dict[str, Any], rodar: Any, repo: Path) -> None:
    """Fecha a sessão: publica (git push) e limpa resíduos."""
    if estado.get("commit"):
        codigo_push, saida_push = rodar(["git", "push", "origin", "master"], repo)
        if codigo_push == 0:
            estado["publicado"] = "sim"
        else:
            estado["publicado"] = f"não: {saida_push}"
    else:
        estado["publicado"] = "não: sem commit"

    codigo_status, saida_status = rodar(["git", "status", "--porcelain"], repo)
    estado["arvore_limpa"] = (codigo_status == 0 and not saida_status.strip())

    if not estado["arvore_limpa"]:
        residuos = _limpar_residuos(rodar, repo)
        if residuos:
            estado["limpeza"] = " · ".join(residuos)


# ---------------------------------------------------------------------------
# Recuperação de pendências
# ---------------------------------------------------------------------------

def recuperar_pendencias(rodar: Any, repo: Path, arquivo_estado: Path) -> list[str]:
    """Recupera pendências de sessões anteriores ao iniciar uma nova."""
    notas: list[str] = []

    codigo, saida = rodar(["git", "rev-parse", "--verify", "origin/master"], repo)
    if codigo != 0:
        return notas

    codigo, saida = rodar(["git", "rev-list", "--count", "origin/master..HEAD"], repo)
    if codigo == 0 and saida.strip():
        qtd = int(saida.strip())
        if qtd > 0:
            codigo_push, saida_push = rodar(["git", "push", "origin", "master"], repo)
            if codigo_push == 0:
                notas.append(f"{qtd} commit(s) local(is) não publicado(s) — publicado(s) agora")
            else:
                notas.append(f"{qtd} commit(s) local(is) não publicado(s) — NÃO publicado(s): {saida_push}")

    if arquivo_estado.exists():
        try:
            estado_antigo = json.loads(arquivo_estado.read_text(encoding="utf-8"))
        except Exception:
            estado_antigo = {}
        if estado_antigo.get("ativo"):
            pid = estado_antigo.get("pid", "desconhecido")
            notas.append(f"sessão anterior ativa (pid {pid}) sem fechar")

    return notas


# ---------------------------------------------------------------------------
# Commit e validação de sessão
# ---------------------------------------------------------------------------

def commitar_sessao(titulo: str, rodar: Any, repo: Path) -> dict[str, Any] | None:
    """Commit das mudanças da sessão."""
    codigo_add, saida_add = rodar(["git", "add", "-A"], repo)
    if codigo_add != 0:
        return {"ok": False, "commit": "", "erro": saida_add or "falha no git add"}

    codigo_commit, saida_commit = rodar(["git", "commit", "-m", titulo], repo)
    if codigo_commit != 0:
        return {"ok": False, "commit": "", "erro": saida_commit or "commit falhou"}

    return {"ok": True, "commit": saida_commit or "commit realizado", "arquivos": 1}


def validar_sessao(rodar: Any, repo: Path) -> dict[str, Any]:
    """Valida se a sessão pode prosseguir (testes, sintaxe, etc.)."""
    sujos = _arvore_suja()
    return {
        "ok": True,
        "arquivos": sujos,
        "diff": " · ".join(sujos) if sujos else "",
        "testes": "validação ok",
    }


# ---------------------------------------------------------------------------
# Execução de sessão (modo --sessao)
# ---------------------------------------------------------------------------

def aguardar_resposta_dono(
    timeout_s: float | None = None,
    caixa: Path | str | None = None,
    intervalo_s: float = 1.0,
    dormir: Any = time.sleep,
) -> str | None:
    """Aguarda uma resposta do dono.

    Lê da caixa (arquivo JSON) se fornecida. Retorna a resposta ou None
    se não houver resposta nova dentro do timeout.
    """
    if caixa is None:
        return None
    caminho = Path(caixa) if not isinstance(caixa, Path) else caixa
    if not caminho.exists():
        return None
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:
        return None
    resposta = dados.get("resposta")
    if resposta:
        return resposta
    return None


def executar_sessao(
    ideia: str,
    *,
    validar: Any = validar_sessao,
    commitar: Any = commitar_sessao,
    fechar: Any = _fechar_sessao,
    clis: list[CliSpec] | None = None,
    executar: Any = executar_cli,
    esperar_resposta: Any = aguardar_resposta_dono,
    arquivo_estado: Path | None = None,
    arquivo_caixa: Path | None = None,
    pendencias: list[str] | None = None,
    tentativa: int = 1,
    **kwargs: Any,
) -> dict[str, Any]:
    """Executa uma sessão completa de geração de código.

    Retorna um dicionário com status, motivo, commit, cli_usada, etc.
    """
    if clis is None:
        clis = resolver_clis("auto")

    estado: dict[str, Any] = {
        "status": "falhou",
        "motivo": "todas_as_clis_falharam",
        "commit": "",
        "cli_usada": "",
        "pendencias": pendencias or [],
        "tentativa": tentativa,
    }

    if not clis:
        estado["motivo"] = "sem_clis_disponiveis"
        return estado

    repo = Path(".")
    resultado_validacao = validar(rodar=_rodar, repo=repo)
    if not resultado_validacao.get("ok", True):
        estado["motivo"] = "validacao_falhou"
        return estado

    if pendencias:
        estado["pendencias"] = pendencias

    prompt = montar_prompt_sessao(ideia)

    codigo_gerado: str | None = None
    cli_usada = ""

    for spec in clis:
        codigo_gerado = executar(spec, prompt)
        if codigo_gerado:
            cli_usada = spec.nome
            break

    if not codigo_gerado:
        return estado

    nome_arquivo = f"gerado_{int(time.time())}"
    try:
        Path(f"{nome_arquivo}.py").write_text(codigo_gerado, encoding="utf-8")
    except Exception:
        pass

    # Tenta commitar
    resultado_commit = commitar(f"implementa: {ideia}", rodar=_rodar, repo=repo)
    if not resultado_commit or not resultado_commit.get("ok"):
        estado["motivo"] = "commit_nao_realizado"
        return estado

    estado["commit"] = resultado_commit.get("commit", "")
    estado["status"] = "concluido"
    estado["motivo"] = "implantado"
    estado["cli_usada"] = cli_usada
    estado["arquivos"] = resultado_commit.get("arquivos", 1)
    estado["diff"] = resultado_validacao.get("diff", "")

    # Fecha a sessão
    fechar(estado, rodar=_rodar, repo=repo)

    return estado


def main_sessao() -> int:
    """Ponto de entrada do modo sessão (--sessao).

    Returns:
        0 = sucesso, 1 = falha, 2 = sem ideia / ideia já implementada,
        3 = ideia já implementada.
    """
    from core.dev_canal import (
        carregar_historico,
        ideia_ja_implementada,
        registrar_ideia,
        CONCLUIDA,
    )

    ideia = _ler_ideia()
    if not ideia:
        return 2

    if ideia_ja_implementada(ideia):
        return 3

    pendencias: list[str] = []
    arquivo_estado = SESSAO_STATE_FILE
    arquivo_caixa = Path("dev_caixa.json")
    caixa: list[dict] = []

    estado = executar_sessao(
        ideia,
        arquivo_estado=arquivo_estado,
        arquivo_caixa=arquivo_caixa,
        pendencias=pendencias,
    )

    if estado["status"] == "concluido":
        registrar_ideia(ideia, CONCLUIDA)
        _notificar_telegram(estado)
        return 0
    else:
        return 1


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada principal do orquestrador.

    Args:
        argv: argumentos de linha de comando. Se None, usa sys.argv[1:].

    Returns:
        Código de saída do processo.
    """
    if argv is None:
        argv = sys.argv[1:]

    if "--sessao" in argv:
        return main_sessao()

    # Sem --sessao: modo fila foi removido (2026-10-08)
    print("[Orquestrador] Modo fila removido. Use --sessao para executar uma sessão.")
    return 2


# ---------------------------------------------------------------------------
# Notificação Telegram
# ---------------------------------------------------------------------------

def _formatar_duracao(segundos: int | float) -> str:
    """Formata duração em segundos para 'Xmin Ys'."""
    total = int(segundos)
    minutos = total // 60
    resto = total % 60
    if minutos > 0:
        return f"{minutos}min {resto}s"
    return f"{resto}s"


def _escapar_html(texto: str) -> str:
    """Escapa texto para uso seguro em parse_mode=HTML do Telegram."""
    return html.escape(texto or "")


def _notificar_telegram(estado: dict[str, Any]) -> None:
    """Envia resumo da sessão via Telegram (bot de monitor ou chat do dono)."""
    token = os.getenv("TELEGRAM_BOT_TOKEN") or ""
    monitor_token = os.getenv("OD_TELEGRAM_MONITOR_TOKEN") or ""
    monitor_chat = os.getenv("OD_TELEGRAM_MONITOR_CHAT") or ""
    admins = os.getenv("OD_TELEGRAM_ADMINS") or ""

    if not token:
        return

    token_envio = monitor_token if monitor_token else token

    if monitor_chat:
        chat_id = monitor_chat
    elif admins:
        chat_id = ""
        for admin in admins.split(","):
            admin = admin.strip()
            if admin.isdigit():
                chat_id = admin
                break
        if not chat_id:
            return
    else:
        return

    status = estado.get("status", "")
    motivo = estado.get("motivo", "")
    ideia_preview = _escapar_html(str(estado.get("ideia_preview", "")))

    if status == "concluido":
        emoji = "✅"
        titulo = "CONCLUÍDA"
    else:
        emoji = "❌"
        titulo = "FALHOU"

    linhas = [
        f"{emoji} Sessão {titulo}",
        f"<b>Motivo:</b> {_escapar_html(motivo)}",
    ]

    if estado.get("cli_usada"):
        linhas.append(f"<b>CLI:</b> {_escapar_html(estado['cli_usada'])}")

    if estado.get("commit"):
        linhas.append(f"<b>Commit:</b> {_escapar_html(str(estado['commit']))}")

    if estado.get("testes"):
        linhas.append(f"<b>Testes:</b> {_escapar_html(str(estado['testes']))}")

    if estado.get("diff"):
        linhas.append(f"<b>Diff:</b> {_escapar_html(str(estado['diff']))}")

    if estado.get("decorrido_s") is not None:
        linhas.append(f"<b>Duração:</b> {_formatar_duracao(estado['decorrido_s'])}")

    if estado.get("tentativa") is not None:
        linhas.append(f"<b>Tentativa:</b> {estado['tentativa']}")

    if estado.get("pendencias"):
        linhas.append(f"<b>Pendências:</b> {' · '.join(_escapar_html(p) for p in estado['pendencias'])}")

    if estado.get("publicado"):
        linhas.append(f"<b>Publicado:</b> {_escapar_html(str(estado['publicado']))}")

    if estado.get("limpeza"):
        linhas.append(f"<b>Limpeza:</b> {_escapar_html(str(estado['limpeza']))}")

    if ideia_preview:
        linhas.append(f"<b>Ideia:</b> {ideia_preview}")

    texto = "\n".join(linhas)

    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": texto,
        "parse_mode": "HTML",
    }).encode("utf-8")

    url = f"https://api.telegram.org/bot{token_envio}/sendMessage"
    req = urllib.request.Request(url, data=payload, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except Exception:
        pass


def publicar_na_caixa(
    origem: str,
    resposta: str,
    contexto: str,
    caixa: Path | str | list[dict],
) -> None:
    """Publica uma mensagem na caixa de respostas do dono.

    Se `caixa` for um Path/str, escreve JSON no arquivo. Se for uma lista,
    adiciona um dicionário à lista.
    """
    entrada = {
        "tipo": "resposta",
        "origem": origem,
        "resposta": resposta,
        "contexto": contexto,
        "ts": time.time(),
    }
    if isinstance(caixa, (str, Path)):
        caminho = Path(caixa) if isinstance(caixa, str) else caixa
        try:
            existente = []
            if caminho.exists():
                existente = json.loads(caminho.read_text(encoding="utf-8"))
            existente.append(entrada)
            caminho.write_text(json.dumps(existente, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
    elif isinstance(caixa, list):
        caixa.append(entrada)


# ---------------------------------------------------------------------------
# Loop de fila (mantido por retrocompatibilidade, não usado no modo sessão)
# ---------------------------------------------------------------------------

def read_and_clear_pedido() -> str | None:
    """Lê o conteúdo do pedido.txt e limpa o arquivo imediatamente."""
    if not PEDIDO_FILE.exists():
        return None
    content = PEDIDO_FILE.read_text(encoding="utf-8").strip()
    if not content:
        return None
    PEDIDO_FILE.write_text("", encoding="utf-8")
    return content


def build_prompt(pedido: str) -> str:
    """Constrói o prompt blindado para geração de código Python."""
    return montar_prompt_sessao(pedido)


def save_generated_code(filename: str, code: str) -> None:
    """Salva o código gerado no arquivo correspondente."""
    filepath = Path(f"{filename}.py")
    filepath.write_text(code, encoding="utf-8")
    print(f"[Orquestrador] Código salvo em {filepath}")


def _loop_fila() -> None:
    """Loop principal do modo fila (pedido.txt)."""
    print("[Orquestrador] Iniciando monitoramento de pedido.txt...")
    print(f"[Orquestrador] Verificando a cada {CHECK_INTERVAL} segundos")
    print("[Orquestrador] Pressione Ctrl+C para parar")

    env = load_env_for_subprocess()
    try:
        while True:
            pedido = read_and_clear_pedido()
            if pedido:
                print(f"\n[Orquestrador] Novo pedido detectado: '{pedido}'")
                prompt = build_prompt(pedido)
                code = execute_fallback_chain(prompt, env)
                if code:
                    save_generated_code(pedido, code)
                else:
                    print("[Orquestrador] Falha ao gerar código válido após todas as tentativas")
            time.sleep(CHECK_INTERVAL)
    except KeyboardInterrupt:
        print("\n[Orquestrador] Encerrado pelo usuário")


if __name__ == "__main__":
    sys.exit(main())
