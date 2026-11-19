#!/usr/bin/env python3
"""Mede a cascata de CLIs de IA do `orquestrador.py` — ordem por resultado.

Por que existe (ordem do dono, 19/11/2026): *"a mais confiável no momento é
freebuff, acho que ela deveria ser a primeira. seguida por Kilo e AGY, depois
poderia verificar todas e colocar em ordem de melhor resultado para o pior"*.

O que faz: roda **cada** CLI de `orquestrador.CLIS` com o MESMO prompt curto
(não-interativo, sem tocar no repositório), mede tempo/exit e classifica:

  - ``ok``       — exit 0 e resposta contendo o marcador pedido;
  - ``vazio``    — exit 0 sem resposta utilizável;
  - ``falha``    — exit != 0 (cota, chave, gateway, modelo) — fail-fast;
  - ``timeout``  — não terminou no prazo (a CLI fica presa, TUI etc.).

O Freebuff não está em ``CLIS`` (wrapper 0.2.36 só tem ``login``/``doctor``;
prompt por stdin sobe a TUI). Ele é medido à parte, com prazo curto, para que
o resultado fique registrado em vez de virar lembrança.

Uso:
    python3 tools/medir_cascata_ias.py                 # prompt padrão
    python3 tools/medir_cascata_ias.py --timeout 90
    python3 tools/medir_cascata_ias.py --json logs/medicao_cascata_ias.json

O JSON é o insumo do ordenamento: melhor = ``ok`` mais rápido; depois
``vazio``, ``falha`` e ``timeout`` (estes dois últimos ordenados pelo tempo
até a resposta, porque fail-fast também é qualidade).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import orquestrador  # noqa: E402

#: Prompt do teste: curto, verificável e SEM ferramenta (não toca arquivo).
PROMPT_PADRAO = "Responda apenas com a palavra: ok"

#: Marcador que a resposta precisa conter para contar como acerto.
MARCADOR_PADRAO = "ok"


def _classificar(saida: str | None, segundos: float, timeout_s: int) -> str:
    if saida is None:
        return "timeout" if segundos >= timeout_s * 0.9 else "falha"
    if MARCADOR_PADRAO.casefold() in saida.casefold():
        return "ok"
    return "vazio"


def medir_cli(spec: "orquestrador.CliSpec", prompt: str, timeout_s: int) -> dict:
    inicio = time.monotonic()
    saida = orquestrador.executar_cli(spec, prompt, timeout_s=timeout_s)
    segundos = round(time.monotonic() - inicio, 2)
    resultado = _classificar(saida, segundos, timeout_s)
    return {
        "nome": spec.nome,
        "binario": spec.comando_base()[0],
        "resultado": resultado,
        "segundos": segundos,
        "resposta": (saida or "").strip()[:200],
    }


def medir_freebuff(prompt: str, timeout_s: int) -> dict:
    """Freebuff à parte: sem modo não-interativo, o esperado é TUI/timeout.

    Roda em diretório temporário e com stdin fechado; ``timeout`` mata o grupo
    para não deixar a TUI pendurada.
    """
    binario = shutil.which("freebuff") or ""
    if not binario:
        return {"nome": "Freebuff", "binario": "freebuff", "resultado": "ausente",
                "segundos": 0.0, "resposta": ""}
    inicio = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="od-fb-") as tmp:
        try:
            proc = subprocess.run(
                [binario],
                input=prompt + "\n",
                cwd=tmp,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout_s,
                start_new_session=True,
            )
            segundos = round(time.monotonic() - inicio, 2)
            texto = (proc.stdout or "").strip()
            resultado = ("ok" if proc.returncode == 0
                         and MARCADOR_PADRAO.casefold() in texto.casefold()
                         else "falha")
        except subprocess.TimeoutExpired:
            segundos = round(time.monotonic() - inicio, 2)
            texto = ""
            resultado = "timeout"
    return {"nome": "Freebuff", "binario": "freebuff", "resultado": resultado,
            "segundos": segundos, "resposta": texto[:200]}


#: Peso de cada resultado na ordenação (menor = melhor).
_PESO = {"ok": 0, "vazio": 1, "falha": 2, "timeout": 3, "ausente": 4}


def ordenar(resultados: list[dict]) -> list[dict]:
    """Melhor resultado primeiro; empate no peso → menor tempo."""
    return sorted(
        resultados,
        key=lambda r: (_PESO.get(r["resultado"], 9), r["segundos"], r["nome"]),
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prompt", default=PROMPT_PADRAO)
    ap.add_argument("--timeout", type=int, default=120,
                    help="prazo por CLI (s); Freebuff usa o mesmo prazo")
    ap.add_argument("--json", default="", help="grava o resultado medido aqui")
    ap.add_argument("--sem-freebuff", action="store_true",
                    help="pula o Freebuff (TUI conhecida)")
    args = ap.parse_args(argv)

    resultados: list[dict] = []
    for spec in orquestrador.CLIS:
        print(f"[medindo] {spec.nome}…", flush=True)
        resultados.append(medir_cli(spec, args.prompt, args.timeout))
        r = resultados[-1]
        print(f"  → {r['resultado']} em {r['segundos']}s", flush=True)

    if not args.sem_freebuff:
        print("[medindo] Freebuff (sem headless; prazo curto)…", flush=True)
        resultados.append(medir_freebuff(args.prompt, min(args.timeout, 20)))
        print(f"  → {resultados[-1]['resultado']} em "
              f"{resultados[-1]['segundos']}s", flush=True)

    ordenados = ordenar(resultados)
    print("\n| # | CLI | resultado | s |")
    print("|---|-----|-----------|---|")
    for i, r in enumerate(ordenados, 1):
        print(f"| {i} | {r['nome']} | {r['resultado']} | {r['segundos']} |")

    if args.json:
        destino = Path(args.json)
        if not destino.is_absolute():
            destino = RAIZ / destino
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps({
            "medido_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "prompt": args.prompt,
            "timeout_s": args.timeout,
            "ordem_medida": [r["nome"] for r in ordenados],
            "resultados": ordenados,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON: {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
