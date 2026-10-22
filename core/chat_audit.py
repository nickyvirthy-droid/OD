"""Auditor de conversas — acha respostas erradas, devaneios e inconsistências.

Ordem do dono (22/10): criar (se não existir) um analisador das
conversas do chat para descobrir respostas erradas, devaneios e
inconsistências. Ele opera em DOIS mundos com o mesmo juiz:

  * **Legado** — os logs do Nicky antigo (motor AIML PascAlice feito em
    Delphi; `analise/AIML/Nicky Desenvolvimento/conversa/*.log`,
    2022→2024). A patologia clássica do ALICE já aparece na amostra:
    "Bom dia" → "What kind of food do you like?" (devaneio em inglês).
    Encoding corrompido nos originais → leitura com errors="replace".
  * **Sistema atual** — tabela `conversation_messages` (user_id,
    profile, role, content, ts, llm_used) com cascata de fonte:
    PostgreSQL (OD_DB_URL) → SQLite (data/od.db) → JSON legado
    (data/conversations/).

O **juiz é plugável e offline-first**: online = Groq via
`OpenAICompatProvider` (chave GROQ_API_KEY viva apurada em 22/10) e
local = gemma-local. A reserva é **por turno**: se o juiz online falhar
num turno, o local assume na hora; se os dois falharem, o turno vira
`erro` com o motivo — nunca silêncio. Cada turno é classificado
`ok | resposta_errada | devaneio | inconsistente` + justificativa, e o
relatório JSON sai em `analise/` (gitignorado — não entra no repo).

CLI (ferramenta de análise, não sobe com o od-core):
    python -m core.chat_audit --fonte auto --limite 200
    python -m core.chat_audit --fonte legado --pasta "analise/AIML/..."
    python -m core.chat_audit --fonte sistema --juiz local
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from core.logger import get_logger

log = get_logger("omega.core.chat_audit")

VEREDITOS = ("ok", "resposta_errada", "devaneio", "inconsistente", "erro")

# Linha de timestamp dos logs do PascAlice: "23:40:23 -->"
_RE_TIMESTAMP = re.compile(r"^\s*(\d{2}):(\d{2}):\d{2}\s*-->\s*$")
# Linha de fala: "ALEX PROJETI: pergunta" / "Nicky: resposta"
_RE_FALA = re.compile(r"^\s*([^:]{1,60}):\s(.*)$")
# Data no nome do arquivo legado: "ALEX PROJETI_20220608.log"
_RE_DATA_ARQUIVO = re.compile(r"_(\d{8})\.log$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Turno (a unidade auditada)
# ---------------------------------------------------------------------------

@dataclass
class Turno:
    """Um par pergunta→resposta, seja do log legado, seja do sistema."""
    fonte: str          # "legado" | "sistema"
    quando: str         # "YYYY-MM-DD HH:MM:SS" (melhor esforço)
    usuario: str
    pergunta: str
    resposta: str
    llm_used: str = ""
    arquivo: str = ""


@dataclass
class Veredito:
    """Classificação de UM turno pelo juiz."""
    veredito: str
    justificativa: str
    juiz: str


class JuizError(Exception):
    """O juiz não devolveu um veredito utilizável."""


# ---------------------------------------------------------------------------
# Parser dos logs legados (PascAlice)
# ---------------------------------------------------------------------------

def _pegar_lado(texto: str, lado: str) -> str:
    """Logs PascAlice guardam 'original|traducao' — fica o lado útil.

    Fala do usuário: `pt|en` → fica o pt (esquerda). Fala do bot:
    `en|pt` → fica o pt (direita). Sem '|' o texto passa intacto.
    """
    if "|" not in texto:
        return texto.strip()
    esq, _, dir_ = texto.partition("|")
    escolhido = esq if lado == "esquerda" else dir_
    return escolhido.strip() or texto.strip()


def parse_log_legado_texto(texto: str, *, arquivo: str = "") -> list[Turno]:
    """Extrai os turnos de UM log legado já decodificado.

    Formato observado (66 logs, 2022-05-30 → 2024-06-12):

        23:40:23 -->
        ALEX PROJETI: oi|Hi
        Nicky: Hello there.|Olá.

    Regras: o timestamp abre um turno; a PRIMEIRA fala é do usuário e a
    SEGUNDA é do bot (nomes variam — Nicky, Bot). Falas extras no mesmo
    bloco são ignoradas; bloco sem resposta vira turno com resposta
    vazia (o juiz classifica como resposta_errada — é dados, não lixo).
    """
    data_arquivo = ""
    m = _RE_DATA_ARQUIVO.search(arquivo or "")
    if m:
        data_arquivo = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}"

    turnos: list[Turno] = []
    quando_hora = ""
    pergunta: Optional[str] = None
    resposta: Optional[str] = None

    def _fechar() -> None:
        if quando_hora or pergunta is not None:
            turnos.append(Turno(
                fonte="legado",
                quando=f"{data_arquivo} {quando_hora}".strip(),
                usuario="legado",
                pergunta=pergunta or "",
                resposta=resposta or "",
                arquivo=arquivo,
            ))

    for bruta in texto.splitlines():
        linha = bruta.replace("\x00", "")
        m_ts = _RE_TIMESTAMP.match(linha)
        if m_ts:
            _fechar()
            quando_hora = m_ts.group(1) + ":" + m_ts.group(2)
            pergunta, resposta = None, None
            continue
        m_fala = _RE_FALA.match(linha)
        if not m_fala:
            continue
        conteudo = m_fala.group(2)
        if pergunta is None:
            pergunta = _pegar_lado(conteudo, "esquerda")
        elif resposta is None:
            # Resposta do bot no formato en|pt → fica o pt.
            resposta = _pegar_lado(conteudo, "direita")
            if not resposta:
                resposta = conteudo.strip()
    _fechar()
    return [t for t in turnos if t.pergunta or t.resposta]


def parse_log_legado(caminho: Path) -> list[Turno]:
    """Lê UM arquivo de log legado (encoding corrompido → replace)."""
    texto = caminho.read_bytes().decode("utf-8", errors="replace")
    return parse_log_legado_texto(texto, arquivo=caminho.name)


def carregar_turnos_legados(pasta: Path) -> list[Turno]:
    """Varre `pasta` (recursivo) por *.log e junta os turnos por data."""
    turnos: list[Turno] = []
    for caminho in sorted(pasta.rglob("*.log")):
        try:
            turnos.extend(parse_log_legado(caminho))
        except OSError as exc:
            log.warn("Log legado ilegível", arquivo=str(caminho), error=str(exc))
    turnos.sort(key=lambda t: (t.quando, t.arquivo))
    return turnos


# ---------------------------------------------------------------------------
# Fonte sistema (Postgres → SQLite → JSON)
# ---------------------------------------------------------------------------

_SQL_CONVERSACOES = (
    "SELECT user_id, profile, role, content, ts, llm_used "
    "FROM conversation_messages ORDER BY ts ASC, id ASC"
)


def _ts_para_texto(ts: Any) -> str:
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError, OverflowError):
        return str(ts or "")


def turnos_de_mensagens(linhas: list[dict[str, Any]],
                        *, fonte: str = "sistema") -> list[Turno]:
    """Agrupa linhas user→assistant consecutivos do mesmo balde em turnos.

    Baldes = (user_id, profile). Mensagem órfã de assistant (sem
    pergunta anterior) e pergunta sem resposta também viram turno —
    lacuna é achado de auditoria, não é para esconder.
    """
    turnos: list[Turno] = []
    aberto: dict[tuple[str, str], Turno] = {}
    for linha in linhas:
        balde = (str(linha.get("user_id") or ""),
                 str(linha.get("profile") or ""))
        papel = str(linha.get("role") or "").lower()
        conteudo = str(linha.get("content") or "")
        if papel == "user":
            aberto[balde] = Turno(
                fonte=fonte,
                quando=_ts_para_texto(linha.get("ts")),
                usuario=balde[0],
                pergunta=conteudo,
                resposta="",
                llm_used="",
            )
            turnos.append(aberto[balde])
        elif papel == "assistant":
            turno = aberto.pop(balde, None)
            if turno is None:
                turno = Turno(fonte=fonte,
                              quando=_ts_para_texto(linha.get("ts")),
                              usuario=balde[0], pergunta="", resposta=conteudo)
                turnos.append(turno)
            turno.resposta = conteudo
            turno.llm_used = str(linha.get("llm_used") or "")
    return turnos


def carregar_turnos_sistema(db: Any, *, limite: Optional[int] = None) -> list[Turno]:
    """Turnos do sistema via `storage.Database` (Postgres ou SQLite)."""
    linhas = db.query(_SQL_CONVERSACOES, (), limit=limite)
    return turnos_de_mensagens(linhas)


def carregar_turnos_json(pasta: Path) -> list[Turno]:
    """Baldes JSON legados de `data/conversations/` (backend fora de prod).

    Aceita tanto a lista de mensagens quanto o envelope {"messages": [...]}.
    """
    turnos: list[Turno] = []
    for caminho in sorted(Path(pasta).glob("*.json")):
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warn("Conversa JSON ilegível", arquivo=caminho.name, error=str(exc))
            continue
        if isinstance(dados, dict):
            dados = dados.get("messages") or dados.get("conversas") or []
        if not isinstance(dados, list):
            continue
        linhas = [m for m in dados if isinstance(m, dict)]
        turnos.extend(turnos_de_mensagens(linhas, fonte="sistema"))
    return turnos


def carregar_turnos_cascata(*, dsn: str = "", sqlite_path: Optional[Path] = None,
                            json_dir: Optional[Path] = None,
                            limite: Optional[int] = None) -> tuple[list[Turno], str]:
    """Fonte das conversas do sistema atual, em cascata.

    PostgreSQL (dsn) → SQLite (arquivo existente) → JSON legado.
    Devolve (turnos, nome_da_fonte). Nada achado = ([], "vazia").
    """
    if dsn:
        try:
            from storage import Database
            db = Database(pool_size=1, dsn=dsn)
            return carregar_turnos_sistema(db, limite=limite), "postgres"
        except Exception as exc:  # banco fora → tenta a próxima fonte
            log.warn("Cascata: Postgres falhou, seguindo", error=str(exc))
    if sqlite_path and Path(sqlite_path).exists():
        try:
            from storage import Database
            db = Database(sqlite_path, pool_size=1)
            return carregar_turnos_sistema(db, limite=limite), "sqlite"
        except Exception as exc:
            log.warn("Cascata: SQLite falhou, seguindo", error=str(exc))
    if json_dir and Path(json_dir).exists():
        turnos = carregar_turnos_json(Path(json_dir))
        if turnos:
            return turnos, "json"
    return [], "vazia"


# ---------------------------------------------------------------------------
# Juiz (plugável, com reserva por turno)
# ---------------------------------------------------------------------------

def montar_prompt(turno: Turno, anterior: Optional[Turno] = None) -> str:
    """Prompt do auditor (PT-BR). O juiz responde SÓ com JSON."""
    contexto = ""
    if anterior is not None and anterior.pergunta:
        contexto = (
            "\nTurno anterior da mesma conversa (para achar contradição):\n"
            f"  usuário: {anterior.pergunta[:300]}\n"
            f"  assistente: {anterior.resposta[:300]}\n"
        )
    return (
        "Você é o auditor do assistente Omega Drakon. Analise UM turno e "
        "classifique a RESPOSTA do assistente.\n\n"
        f"Pergunta do usuário: {turno.pergunta[:600]}\n"
        f"Resposta do assistente: {turno.resposta[:600]}\n"
        f"{contexto}\n"
        "Classificação (escolha UMA):\n"
        "- ok: resposta pertinente e correta para a pergunta.\n"
        "- resposta_errada: responde algo errado/falso ou ignora o que "
        "foi pedido.\n"
        "- devaneio: muda de assunto sem relação com a pergunta (ex.: "
        "pergunta 'bom dia' e responde sobre comida).\n"
        "- inconsistente: contradiz informação dada antes nesta mesma "
        "conversa.\n\n"
        'Responda SOMENTE um JSON, exatamente neste formato: '
        '{"veredito": "ok|resposta_errada|devaneio|inconsistente", '
        '"justificativa": "uma frase curta"}'
    )


def _normalizar_veredito(bruto: str) -> str:
    texto = (bruto or "").strip().lower().replace(" ", "_").replace("-", "_")
    for nome in VEREDITOS:
        if nome in texto:
            return nome
    return ""


def _interpretar_resposta(texto: str, juiz: str) -> Veredito:
    """Extrai o JSON do veredito da resposta do LLM (melhor esforço)."""
    inicio, fim = (texto or "").find("{"), (texto or "").rfind("}")
    if inicio < 0 or fim <= inicio:
        raise JuizError(f"resposta sem JSON do juiz {juiz}: {texto[:120]!r}")
    try:
        carga = json.loads(texto[inicio:fim + 1])
    except ValueError as exc:
        raise JuizError(f"JSON inválido do juiz {juiz}: {exc}") from exc
    veredito = _normalizar_veredito(str(carga.get("veredito") or ""))
    if not veredito or veredito == "erro":
        raise JuizError(
            f"veredito desconhecido do juiz {juiz}: {carga.get('veredito')!r}")
    justificativa = str(carga.get("justificativa") or "").strip()
    return Veredito(veredito=veredito, justificativa=justificativa, juiz=juiz)


class JuizLLM:
    """Juiz sobre um provider OpenAI-compatível (Groq online | gemma local)."""

    def __init__(self, provider: Any, *, nome: str = "") -> None:
        self.provider = provider
        self.nome = nome or str(getattr(provider, "name", "juiz"))

    def julgar(self, turno: Turno,
               anterior: Optional[Turno] = None) -> Veredito:
        prompt = montar_prompt(turno, anterior)
        try:
            texto = asyncio.run(self.provider.generate(prompt, timeout=90.0))
        except Exception as exc:
            raise JuizError(f"juiz {self.nome} falhou: {exc}") from exc
        if not texto:
            raise JuizError(f"juiz {self.nome} devolveu vazio")
        return _interpretar_resposta(texto, self.nome)


class JuizComReserva:
    """Tenta o juiz principal; num tropeço o reserva assume NO MESMO turno.

    Se os dois falharem, o turno vira veredito `erro` com o motivo —
    a auditoria nunca para por causa de um LLM fora.
    """

    def __init__(self, principal: Any, reserva: Optional[Any] = None) -> None:
        self.principal = principal
        self.reserva = reserva
        self.nome = getattr(principal, "nome", "principal")

    def julgar(self, turno: Turno,
               anterior: Optional[Turno] = None) -> Veredito:
        try:
            return self.principal.julgar(turno, anterior)
        except Exception as exc:
            primeiro_erro = str(exc)
        if self.reserva is not None:
            try:
                return self.reserva.julgar(turno, anterior)
            except Exception as exc:
                return Veredito("erro",
                                f"juiz principal ({primeiro_erro}) e reserva "
                                f"({exc}) falharam",
                                juiz="erro")
        return Veredito("erro", f"juiz {self.nome} falhou: {primeiro_erro}",
                        juiz="erro")


def montar_juiz(modo: str, env: Callable[[str, str], str]) -> Any:
    """Monta o juiz do modo pedido: auto | online | local | nenhum.

    * auto — Groq se houver GROQ_API_KEY, com gemma-local na reserva;
      sem chave, só o local (offline-first preservado).
    * online — Groq com reserva local; sem chave = erro de configuração.
    * local — gemma-local (llama-server em 127.0.0.1:8081).
    * nenhum — só parse/relatório (sem classificação; para conferir fonte).
    """
    from core.llm import DEFAULT_LLM_URL, OpenAICompatProvider

    def _local() -> JuizLLM:
        return JuizLLM(OpenAICompatProvider(
            name="gemma-local", base_url=env("OD_LLM_URL", DEFAULT_LLM_URL),
            temperature=0.0), nome="gemma-local")

    def _groq() -> JuizLLM:
        chave = env("GROQ_API_KEY", "").strip()
        if not chave:
            raise ValueError("--juiz online/auto sem GROQ_API_KEY")
        return JuizLLM(OpenAICompatProvider(
            name="groq-online", base_url="https://api.groq.com/openai/v1",
            model=env("OD_AUDIT_GROQ_MODEL", "openai/gpt-oss-120b"),
            api_key=chave, max_tokens=1024, temperature=0.0),
            nome="groq-online")

    modo = (modo or "auto").lower()
    if modo == "nenhum":
        return None
    if modo == "local":
        return _local()
    if modo == "online":
        return JuizComReserva(_groq(), _local())
    return JuizComReserva(_groq(), _local()) if env("GROQ_API_KEY", "").strip() \
        else _local()


# ---------------------------------------------------------------------------
# Auditoria + relatório
# ---------------------------------------------------------------------------

def veredito_deterministico(turno: Turno) -> Optional[Veredito]:
    """Vereditos que não precisam de LLM — o juiz errava esses.

    Prova viva 22/10: o juiz local classificou resposta VAZIA como
    "pertinente e correta" (alucinou o conteúdo). Lacuna de registro é
    fato, não opinião: pergunta sem resposta = `resposta_errada`;
    assistant órfão (sem pergunta) = `erro` (sem contexto não há o que
    julgar). O juiz só entra nos turnos completos.
    """
    if not turno.resposta.strip():
        return Veredito("resposta_errada",
                        "resposta vazia — lacuna de registro no log/histórico",
                        juiz="deterministico")
    if not turno.pergunta.strip():
        return Veredito("erro",
                        "assistant sem pergunta anterior — sem contexto "
                        "não há o que julgar",
                        juiz="deterministico")
    return None


def auditar(turnos: list[Turno], juiz: Any) -> list[dict[str, Any]]:
    """Classifica cada turno (com o turno anterior como contexto)."""
    resultados: list[dict[str, Any]] = []
    for i, turno in enumerate(turnos):
        anterior = turnos[i - 1] if i > 0 else None
        fixo = veredito_deterministico(turno)
        try:
            if fixo is not None:
                veredito = fixo
            else:
                veredito = juiz.julgar(turno, anterior) if juiz is not None \
                    else Veredito("erro", "sem juiz configurado", juiz="nenhum")
        except Exception as exc:  # defesa extra: auditoria nunca para
            veredito = Veredito("erro", f"juiz explodiu: {exc}", juiz="erro")
        resultados.append({
            "fonte": turno.fonte,
            "quando": turno.quando,
            "usuario": turno.usuario,
            "arquivo": turno.arquivo,
            "pergunta": turno.pergunta,
            "resposta": turno.resposta,
            "llm_used": turno.llm_used,
            "veredito": veredito.veredito,
            "justificativa": veredito.justificativa,
            "juiz": veredito.juiz,
        })
    return resultados


def gerar_relatorio(resultados: list[dict[str, Any]], *, fonte: str) -> dict[str, Any]:
    """Resumo do lote: contagem por veredito + os turnos problemáticos."""
    contagens = {nome: 0 for nome in VEREDITOS}
    for item in resultados:
        contagens[item["veredito"]] = contagens.get(item["veredito"], 0) + 1
    problematicos = [r for r in resultados if r["veredito"] != "ok"]
    return {
        "gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "fonte": fonte,
        "total_turnos": len(resultados),
        "contagens": contagens,
        "problematicos": len(problematicos),
        "resultados": resultados,
    }


def salvar_relatorio(relatorio: dict[str, Any], destino: Path) -> Path:
    """Grava o relatório JSON em `destino` (pasta analise/, gitignorado)."""
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    carimbo = time.strftime("%Y%m%d-%H%M%S")
    caminho = destino / f"relatorio_chat_audit_{carimbo}.json"
    caminho.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    return caminho


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    raiz = Path(__file__).resolve().parents[1]

    def env(nome: str, padrao: str) -> str:
        import os
        return os.environ.get(nome, padrao)

    parser = argparse.ArgumentParser(
        prog="chat_audit",
        description="Audita conversas (legado PascAlice ou sistema atual).")
    parser.add_argument("--fonte", choices=("auto", "legado", "sistema"),
                        default="auto",
                        help="auto = sistema atual se houver, senão legado")
    parser.add_argument("--pasta", default="",
                        help="pasta dos logs legados (auto: analise/AIML)")
    parser.add_argument("--juiz", choices=("auto", "online", "local", "nenhum"),
                        default="auto")
    parser.add_argument("--limite", type=int, default=0,
                        help="limita o nº de turnos (0 = todos)")
    parser.add_argument("--destino", default=str(raiz / "analise"),
                        help="pasta do relatório JSON (padrão: analise/)")
    args = parser.parse_args(argv)

    limite = args.limite or None
    turnos: list[Turno] = []
    fonte = "vazia"
    if args.fonte in ("auto", "sistema"):
        turnos, fonte = carregar_turnos_cascata(
            dsn=env("OD_DB_URL", ""),
            sqlite_path=raiz / "data" / "od.db",
            json_dir=raiz / "data" / "conversations",
            limite=limite)
    if not turnos and args.fonte in ("auto", "legado"):
        pasta = Path(args.pasta or raiz / "analise" / "AIML" /
                     "Nicky Desenvolvimento" / "conversa")
        if pasta.exists():
            turnos = carregar_turnos_legados(pasta)[:limite]
            fonte = "legado"
    if not turnos:
        print(f"Nenhum turno encontrado (fonte={args.fonte}, cascata={fonte}).")
        return 1

    try:
        juiz = montar_juiz(args.juiz, env)
    except ValueError as exc:
        print(f"Juiz indisponível: {exc}")
        return 2

    log.info("Auditoria iniciada", fonte=fonte, turnos=len(turnos),
             juiz=args.juiz)
    resultados = auditar(turnos, juiz)
    relatorio = gerar_relatorio(resultados, fonte=fonte)
    caminho = salvar_relatorio(relatorio, Path(args.destino))

    contagens = relatorio["contagens"]
    print(f"Fonte: {fonte} · turnos: {relatorio['total_turnos']} · "
          f"problemáticos: {relatorio['problematicos']}")
    print("Vereditos: " + " · ".join(
        f"{k}={v}" for k, v in contagens.items() if v))
    print(f"Relatório: {caminho}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
