#!/usr/bin/env python3
"""
OMEGA DRAKON • TOOLS
Módulo: tools/monitor/io_probe.py
Descrição: Sonda de latência do od-core para a linha de base do F3 (async I/O).
           Mede /health em série e em concorrência (threads), além do custo de
           criar um event loop novo — que é o que cada requisição da API faz
           hoje via asyncio.run().
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - docs/ANALISE_SISTEMA_TODO.md §F3 (async I/O) e §5 (KPIs)
  - integrations/api/server.py (ThreadingHTTPServer + asyncio.run por request)

Architecture:
    O servidor é ThreadingHTTPServer: cada requisição roda numa thread e cria
    seu próprio loop com asyncio.run(). Não existe loop compartilhado para
    bloquear, então "bloquear o event loop" não é o risco real — o custo real
    é (a) latência sob concorrência e (b) criar loop por requisição. Esta
    sonda mede os dois para decidir, com número, se o F3 vale o risco.

Usage:
    KEY=$(grep -m1 '^OD_API_KEY=' .env | cut -d= -f2-)
    .venv/bin/python tools/monitor/io_probe.py --api-key "$KEY" --series 100
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

__signature__ = "OD // TOOLS"

# Onde o monitor periódico grava; o check `latencia` do /health lê daqui.
ARQUIVO_PADRAO = Path(__file__).resolve().parents[2] / "data" / "io_monitor.json"



def urlsplit_path(url: str) -> str:
    """Rótulo curto do alvo: o path da URL ("/site/", "/health")."""
    from urllib.parse import urlsplit

    try:
        return urlsplit(url).path or "/"
    except ValueError:
        return ""


def _percentil(valores: list[float], p: float) -> float:
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    idx = max(0, min(len(ordenados) - 1, int(round((p / 100.0) * (len(ordenados) - 1)))))
    return ordenados[idx]


def _uma_requisicao(url: str, api_key: str, timeout: float) -> tuple[float, int, bool]:
    inicio = time.perf_counter()
    req = urllib.request.Request(url, method="GET")
    if api_key:
        req.add_header("X-API-Key", api_key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            corpo = resp.read()
            codigo = resp.status
    except urllib.error.HTTPError as exc:
        corpo = exc.read()
        codigo = exc.code
    except Exception:
        return (time.perf_counter() - inicio) * 1000.0, 0, False
    try:
        saudavel = bool(json.loads(corpo).get("ok"))
    except Exception:
        saudavel = False
    return (time.perf_counter() - inicio) * 1000.0, codigo, saudavel


def serie(
    url: str, api_key: str, n: int, timeout: float, intervalo: float = 0.0
) -> dict:
    lat: list[float] = []
    codigos: dict[int, int] = {}
    for _ in range(n):
        ms, codigo, _saudavel = _uma_requisicao(url, api_key, timeout)
        lat.append(ms)
        codigos[codigo] = codigos.get(codigo, 0) + 1
        if intervalo > 0:
            time.sleep(intervalo)
    return _resumo(lat, codigos)


def concorrente(url: str, api_key: str, n: int, threads: int, timeout: float) -> dict:
    inicio = time.perf_counter()
    with ThreadPoolExecutor(max_workers=threads) as pool:
        resultados = list(pool.map(
            lambda _: _uma_requisicao(url, api_key, timeout), range(n)
        ))
    total_s = time.perf_counter() - inicio
    lat = [r[0] for r in resultados]
    codigos: dict[int, int] = {}
    for _ms, codigo, _s in resultados:
        codigos[codigo] = codigos.get(codigo, 0) + 1
    resumo = _resumo(lat, codigos)
    resumo["rps"] = round(n / total_s, 1) if total_s else 0.0
    resumo["threads"] = threads
    return resumo


def _resumo(lat: list[float], codigos: dict[int, int]) -> dict:
    return {
        "n": len(lat),
        "p50_ms": round(statistics.median(lat), 2) if lat else 0.0,
        "p95_ms": round(_percentil(lat, 95), 2),
        "max_ms": round(max(lat), 2) if lat else 0.0,
        "codigos": codigos,
    }


def _chave_api_de_arquivo(caminho: str) -> str:
    """Lê OD_API_KEY de um .env (o serviço do timer não herda shell)."""
    try:
        for linha in Path(caminho).read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if linha.startswith("OD_API_KEY="):
                return linha.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""


def gravar_resultado(
    caminho: Path, rotulo: str, url: str, serie_res: dict, conc_res: dict
) -> None:
    """Grava/atualiza o JSON do monitor de forma atômica.

    O mesmo arquivo é alimentado por mais de um alvo (o timer roda a sonda
    duas vezes): ler-modificar-escrever preserva os alvos anteriores, e o
    `ts`/`iso` sempre refletem a última execução (idade do arquivo = frescor).
    """
    caminho.parent.mkdir(parents=True, exist_ok=True)
    dados: dict = {"versao": 1, "alvos": {}}
    try:
        existente = json.loads(caminho.read_text(encoding="utf-8"))
        if isinstance(existente, dict) and isinstance(existente.get("alvos"), dict):
            dados["alvos"] = existente["alvos"]
    except (OSError, ValueError):
        pass
    agora = time.time()
    dados["ts"] = round(agora, 3)
    dados["iso"] = datetime.fromtimestamp(agora).astimezone().isoformat(timespec="seconds")
    dados["alvos"][rotulo] = {
        "url": url,
        "serie": serie_res,
        "concorrente": conc_res,
    }
    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    temporario.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporario, caminho)


def custo_de_loop(n: int = 200) -> dict:
    """Quanto custa criar+descartar um event loop (o que a API faz por request)."""

    async def _noop() -> None:
        return None

    inicio = time.perf_counter()
    for _ in range(n):
        asyncio.run(_noop())
    total_ns = (time.perf_counter() - inicio) / n * 1e9
    return {"loops": n, "por_loop_us": round(total_ns / 1000.0, 1)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Sonda de latência do od-core (F3)")
    p.add_argument("--url", default="http://127.0.0.1:8000/health")
    p.add_argument("--api-key", default="")
    p.add_argument(
        "--api-key-file", default="",
        help="lê OD_API_KEY de um .env (usado pelo serviço do monitor)",
    )
    p.add_argument(
        "--gravar", default="",
        help=f"grava/atualiza o JSON do monitor (padrão do timer: {ARQUIVO_PADRAO})",
    )
    p.add_argument("--rotulo", default="", help="nome do alvo no JSON (padrão: path)")
    p.add_argument("--series", type=int, default=100, help="requisições em série")
    p.add_argument(
        "--intervalo", type=float, default=0.0,
        help="segundos entre requisições da série (respeita o rate limit de 30/min)",
    )
    p.add_argument("--concurrentes", type=int, default=100, help="requisições concorrentes")
    p.add_argument("--threads", type=int, default=8)
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--json", action="store_true", help="saída só em JSON")
    args = p.parse_args(argv)

    api_key = args.api_key or (
        _chave_api_de_arquivo(args.api_key_file) if args.api_key_file else ""
    )
    serie_res = serie(args.url, api_key, args.series, args.timeout, args.intervalo)
    conc_res = concorrente(
        args.url, api_key, args.concurrentes, args.threads, args.timeout
    ) if args.concurrentes > 0 else {}
    resultado = {
        "url": args.url,
        "serie": serie_res,
        "concorrente": conc_res,
        "custo_loop": custo_de_loop(),
    }
    if args.gravar:
        destino = Path(args.gravar).expanduser()
        rotulo = args.rotulo or (urlsplit_path(args.url) or "alvo")
        gravar_resultado(destino, rotulo, args.url, serie_res, conc_res)
        if not args.json:
            print(f"gravado: {destino} (alvo={rotulo})")
    if args.json:
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
        return 0

    s, c, l = resultado["serie"], resultado["concorrente"], resultado["custo_loop"]
    print(f"GET {args.url}")
    print(f"  série       n={s['n']:<4} p50={s['p50_ms']:>7} ms  p95={s['p95_ms']:>7} ms  max={s['max_ms']:>7} ms  {s['codigos']}")
    if c:
        print(f"  concorrente n={c['n']:<4} p50={c['p50_ms']:>7} ms  p95={c['p95_ms']:>7} ms  max={c['max_ms']:>7} ms  {c['rps']} req/s  {c['codigos']}")
    else:
        print("  concorrente desligada (--concurrentes 0)")
    print(f"  asyncio.run() novo por chamada: {l['por_loop_us']} µs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
