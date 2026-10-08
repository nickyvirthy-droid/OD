"""
OMEGA DRAKON • RUNTIME
Tecnologia que respira.
Módulo: runtime/llm_cache_saneamento.py
Descrição: saneamento da tabela `llm_cache` — duas cirurgias datadas da
           auditoria das conversas de 08/10 (§8 de
           iniciar/2026-10-07_conversa_omegadrakon.md):

  1) PERFIL (`--so perfis`): a coluna `profile` gravava `self._profile` (o
     perfil FIXO da instância de cache) em vez do perfil QUE PERGUNTOU —
     71/71 linhas saíram como 'guardian', inclusive as de nyx/nexus/athenae.
     A chave já isola por perfil (make_key entra com instância + params), então
     o valor verdadeiro é RECALCULADO: para cada linha refazemos a chave com
     cada candidato (instância × profile=) e o par que reproduz a chave diz
     quem perguntou. Linha cuja chave não casa com nenhum candidato não é
     tocada (reportada como `nao_reconhecidas`).

  2) PODA (`--so poda`): respostas DEVANEIO gravadas pela prova viva de
     06-07/10 — ação de sistema fabricada (CPU 31.7 °C na porta 5000),
     fonte inventada (fase da lua 'Fonte: Open-Meteo'), recusa falsa sobre
     a Agenda, LLM declarado 'gemma' e dados factualmente errados. Cachadas,
     elas voltam antes do anti-recusa e viram verdade permanente: por isso
     saem da tabela (com snapshot de rollback). Os prompts alvo estão em
     PODA_PROMPTS como EVIDÊNCIA da auditoria — revisar antes de ampliar.

Dry-run por padrão; nada é escrito sem `--apply` (regra 7 — ação destrutiva
só com pedido explícito, snapshot em backups/ para desfazer).

Uso:
    .venv/bin/python -m runtime.llm_cache_saneamento                 # dry-run
    .venv/bin/python -m runtime.llm_cache_saneamento --apply        # aplica as duas
    .venv/bin/python -m runtime.llm_cache_saneamento --so poda --apply

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import time
from typing import Any, Optional

from core.logger import get_logger
from memory.cache import LLMCache, normalize_prompt

__signature__ = "OD // CORE"

log = get_logger("omega.runtime.llm_cache_saneamento")

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
BACKUP_DIR = REPO_ROOT / "backups"

#: Prompts das respostas devaneio (auditoria das conversas de 08/10).
#: Comparados na forma normalizada — a coluna `prompt` já guarda normalizado.
PODA_PROMPTS: tuple[str, ...] = (
    # ação de sistema inventada
    "qual a velocidade da internet",
    "o que tem pra hoje",
    "O que tem pra hoje",
    "já sabe acessar meu Google drive?",
    # fonte/dado fabricado
    "qual a fase da lua",
    "conte uma curiosidade sobre a lua",
    "quem fundou o xintoísmo",
    # recusas que contradizem o sistema real (a Agenda e o papel admin existem)
    "como está minha agenda",
    "como esta minha agenda",
    "Marque na agenda um compromisso. Teste da agenda.",
    "sou o dono adm",
    # identidade errada (o serviço roda qwen2.5-coder-3b, não gemma)
    "qual o LLM que esta usando",
    # devaneio de 'vou criar algo' que não criou nada
    "crie uma sckill, processo ou ação para saber isso",
    # raiz do Drive explicada como se '/' fosse o caminho dele
    "/",
)


# ---------------------------------------------------------------------------
# 1) Perfil da coluna `profile`
# ---------------------------------------------------------------------------

def candidatos_perfis() -> list[str]:
    """Perfis que podem ter escrito uma linha (perfil×perfil = chave)."""
    from agents.nicky_virthy.personality import DEFAULT_PROFILE, PROFILES
    from runtime.launcher import env

    candidatos = set(PROFILES) | {DEFAULT_PROFILE, ""}
    do_env = (env("OD_PROFILE", "") or "").strip()
    if do_env:
        candidatos.add(do_env)
    return sorted(candidatos)


def _chaves_por_instancia(perfis: list[str]) -> dict[str, LLMCache]:
    """Uma LLMCache por perfil de instância — make_key não toca em disco."""
    cache_dir = REPO_ROOT / "data" / "llm_cache"
    return {p: LLMCache(cache_dir=cache_dir, profile=p) for p in perfis}


def plan_perfis(db: Any, perfis: Optional[list[str]] = None) -> dict[str, Any]:
    """O que a correção de `profile` faria — sem escrever nada."""
    perfis = perfis if perfis is not None else candidatos_perfis()
    caches = _chaves_por_instancia(perfis)
    linhas = db.query(
        "SELECT key, prompt, profile FROM llm_cache ORDER BY created_ts"
    )
    correcoes: list[dict[str, Any]] = []
    ambiguas: list[dict[str, Any]] = []
    nao_reconhecidas: list[dict[str, Any]] = []
    ja_ok = 0
    for row in linhas or []:
        prompt = str(row["prompt"] or "")
        chave = str(row["key"] or "")
        verdadeiros: set[str] = set()
        for perfil_instancia, cache in caches.items():
            # com profile= nos params (como o orquestrador grava hoje e ontem)
            for param in perfis:
                if cache.make_key(prompt, profile=param) == chave:
                    verdadeiros.add(param)
            # sem profile= nos params (escrita legada de outra porta)
            if cache.make_key(prompt) == chave:
                verdadeiros.add(perfil_instancia)
        atual = str(row["profile"] or "")
        if len(verdadeiros) == 1:
            verdadeiro = next(iter(verdadeiros))
            if verdadeiro == atual:
                ja_ok += 1
            else:
                correcoes.append({
                    "key": chave, "prompt": prompt,
                    "profile": atual, "profile_correto": verdadeiro,
                })
        elif not verdadeiros:
            nao_reconhecidas.append({"key": chave, "prompt": prompt,
                                     "profile": atual})
        else:
            ambiguas.append({"key": chave, "prompt": prompt,
                             "profile": atual, "candidatos": sorted(verdadeiros)})
    return {
        "total": len(linhas or []),
        "correcoes": correcoes,
        "ja_corretas": ja_ok,
        "nao_reconhecidas": nao_reconhecidas,
        "ambiguas": ambiguas,
    }


def apply_perfis(
    db: Any, perfis: Optional[list[str]] = None, *,
    backup_dir: Optional[pathlib.Path] = BACKUP_DIR,
) -> dict[str, Any]:
    """Reatribui `profile` nas linhas do plan. Snapshot antes; transação única."""
    plano = plan_perfis(db, perfis)
    correcoes = plano["correcoes"]
    if not correcoes:
        return {"corrigidas": 0, "snapshot": None, "plano": plano}

    snapshot: Optional[pathlib.Path] = None
    if backup_dir is not None:
        snapshot = _snapshot(
            backup_dir, "llm-cache-perfil",
            {
                "motivo": "coluna profile gravava o perfil fixo da instância",
                "correcoes": correcoes,
                "rollback": [
                    "UPDATE llm_cache SET profile = "
                    f"{_literal(c['profile'])} WHERE key = {_literal(c['key'])}"
                    for c in correcoes
                ],
            },
        )

    corrigidas = 0
    with db.transaction():
        for c in correcoes:
            n = db.execute(
                "UPDATE llm_cache SET profile = ? WHERE key = ?",
                (c["profile_correto"], c["key"]),
            )
            corrigidas += int(n)
            log.info(
                "Profile corrigido",
                prompt=c["prompt"][:60], de=c["profile"],
                para=c["profile_correto"], linhas=int(n),
            )
    return {"corrigidas": corrigidas,
            "snapshot": str(snapshot) if snapshot else None,
            "plano": plano}


# ---------------------------------------------------------------------------
# 2) Poda de devaneios
# ---------------------------------------------------------------------------

def _alvos_normalizados(prompts: tuple[str, ...] = PODA_PROMPTS) -> set[str]:
    return {normalize_prompt(p) for p in prompts}


def plan_poda(
    db: Any, prompts: tuple[str, ...] = PODA_PROMPTS,
) -> dict[str, Any]:
    """Linhas cacheadas com resposta devaneio — sem remover nada.

    `SELECT *` de propósito: o snapshot precisa das COLUNAS TODAS para o
    rollback (last_used_ts é NOT NULL sem default — um INSERT parcial não
    devolve a linha).
    """
    alvos = _alvos_normalizados(prompts)
    linhas = db.query("SELECT * FROM llm_cache")
    alvo_linhas: list[dict[str, Any]] = []
    for row in linhas or []:
        if normalize_prompt(str(row["prompt"] or "")) in alvos:
            alvo_linhas.append(row)
    return {"total": len(linhas or []), "podar": alvo_linhas}


def apply_poda(
    db: Any, prompts: tuple[str, ...] = PODA_PROMPTS, *,
    backup_dir: Optional[pathlib.Path] = BACKUP_DIR,
) -> dict[str, Any]:
    """Remove as linhas do plan (conteúdo inteiro no snapshot, para rollback)."""
    plano = plan_poda(db, prompts)
    alvos = plano["podar"]
    if not alvos:
        return {"podadas": 0, "snapshot": None, "plano": plano}

    snapshot: Optional[pathlib.Path] = None
    if backup_dir is not None:
        snapshot = _snapshot(
            backup_dir, "llm-cache-poda",
            {
                "motivo": "podar respostas devaneio (auditoria 08/10)",
                "linhas": alvos,
                "rollback": _insert_rollback(alvos),
            },
        )

    podadas = 0
    with db.transaction():
        for r in alvos:
            n = db.execute("DELETE FROM llm_cache WHERE key = ?", (r["key"],))
            podadas += int(n)
            log.info("Resposta devaneio podada", prompt=str(r["prompt"])[:60])
    return {"podadas": podadas,
            "snapshot": str(snapshot) if snapshot else None,
            "plano": plano}


def _literal(valor: Any) -> str:
    """Literal SQL de um valor para o SQL de rollback do snapshot."""
    if valor is None:
        return "NULL"
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return repr(valor)
    texto = str(valor).replace("'", "''")
    return f"'{texto}'"


def _insert_rollback(linhas: list[dict[str, Any]]) -> list[str]:
    """INSERTs que devolvem exatamente as linhas removidas (todas as colunas)."""
    sqls: list[str] = []
    for linha in linhas:
        colunas = ", ".join(sorted(linha))
        valores = ", ".join(_literal(linha[c]) for c in sorted(linha))
        sqls.append(
            f"INSERT INTO llm_cache ({colunas}) VALUES ({valores})"
        )
    return sqls


# ---------------------------------------------------------------------------
# Auxiliar — snapshot de rollback (mesmo padrão de migrate_history_owner)
# ---------------------------------------------------------------------------

def _snapshot(backup_dir: pathlib.Path, prefix: str, corpo: dict[str, Any]) -> pathlib.Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    caminho = backup_dir / f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}.bak"
    caminho.write_text(
        json.dumps({"quando": time.strftime("%Y-%m-%d %H:%M:%S"), **corpo},
                   ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return caminho


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _mostra(consulta: dict[str, Any], rotulo: str) -> None:
    print(f"[{rotulo}] linhas: {consulta['total']}")
    if "correcoes" in consulta:
        print(f"  profile: {len(consulta['correcoes'])} a corrigir | "
              f"{consulta['ja_corretas']} já certo | "
              f"{len(consulta['nao_reconhecidas'])} chave não reconhecida | "
              f"{len(consulta['ambiguas'])} ambígua")
        for c in consulta["correcoes"][:10]:
            print(f"    {c['prompt'][:52]!r}: {c['profile']} → {c['profile_correto']}")
        for c in consulta["nao_reconhecidas"][:5]:
            print(f"    (não reconhecida) {c['prompt'][:52]!r} = {c['profile']}")
    if "podar" in consulta:
        print(f"  poda: {len(consulta['podar'])} resposta devaneio")
        for r in consulta["podar"]:
            resp = re.sub(r"\s+", " ", str(r["response"] or ""))[:70]
            print(f"    {str(r['prompt'])[:52]!r} → {resp!r}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Saneia llm_cache: coluna profile + poda de devaneios."
    )
    parser.add_argument("--so", choices=("perfis", "poda"), default=None,
                        help="restaura UMA das duas cirurgias (default: as duas)")
    parser.add_argument("--apply", action="store_true",
                        help="executa de verdade (sem isso é só dry-run)")
    args = parser.parse_args(argv)

    from runtime.launcher import env
    from storage import Database

    db = Database(dsn=env("OD_DB_URL", ""), pool_size=2)
    try:
        if args.so in (None, "perfis"):
            _mostra(plan_perfis(db), "perfis")
        if args.so in (None, "poda"):
            _mostra(plan_poda(db), "poda")
        if not args.apply:
            print("\n(dry-run — rode com --apply para alterar o banco)")
            return 0

        if args.so in (None, "perfis"):
            rel = apply_perfis(db)
            print(f"\nprofile corrigido: {rel['corrigidas']} | snapshot: {rel['snapshot']}")
        if args.so in (None, "poda"):
            rel = apply_poda(db)
            print(f"respostas podadas: {rel['podadas']} | snapshot: {rel['snapshot']}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
