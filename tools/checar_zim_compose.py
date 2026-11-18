#!/usr/bin/env python3
"""
OMEGA DRAKON • SYSTEMS
Ferramenta: tools/checar_zim_compose.py
Descrição: Guarda do ACERVO OFFLINE — todo ZIM no disco precisa estar no
           `command` do kiwix em `docker/tools-compose.yaml`.

           O kiwix-serve NÃO aceita glob: cada ZIM é um argumento posicional.
           Um ZIM novo baixado no diretório montado fica invisível para a
           busca até alguém lembrar de editar o compose e recriar o container
           — exatamente o buraco do P0 nº 3 da revisão de 17/11 (14 ZIMs /
           40,3 GB sem guarda).

           Duas checagens, nas duas direções:
             - ZIM citado no compose e AUSENTE no disco (container pode subir
               com `--skipInvalid` e simplesmente não servir o acervo);
             - ZIM presente no disco e FORA do compose (não aparece na busca).

           Uso:
             python3 tools/checar_zim_compose.py            # relatório + exit
             python3 tools/checar_zim_compose.py --json

           Exit 0 = alinhado; 1 = divergência (o CI e o teste usam isso).
           Sem PyYAML de propósito: o parse é do bloco `kiwix:` do compose,
           que é pequeno e estável.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projetti
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Optional

RAIZ = Path(__file__).resolve().parent.parent
COMPOSE_PADRAO = RAIZ / "docker" / "tools-compose.yaml"

_RE_ZIM = re.compile(r'"(/[^"]+\.zim)"')
_RE_VOLUME = re.compile(r"-\s+(/[^\s:]+?):(/(?:data|frio)):ro")


def bloco_kiwix(compose: str) -> str:
    """Texto do serviço `kiwix:` (até o próximo serviço no mesmo nível)."""
    linhas = compose.splitlines()
    inicio = None
    for i, linha in enumerate(linhas):
        if re.match(r"^\s{2}kiwix:\s*$", linha):
            inicio = i
            break
    if inicio is None:
        return ""
    fim = len(linhas)
    for j in range(inicio + 1, len(linhas)):
        if re.match(r"^\s{2}[A-Za-z0-9_-]+:\s*$", linhas[j]):
            fim = j
            break
    return "\n".join(linhas[inicio:fim])


def ler_compose(caminho: Path = COMPOSE_PADRAO) -> tuple[dict[str, Path], list[str]]:
    """(mapa container_dir → host_dir, caminhos de ZIM citados no command)."""
    texto = caminho.read_text(encoding="utf-8")
    bloco = bloco_kiwix(texto)
    volumes = {cont: Path(host) for host, cont in _RE_VOLUME.findall(bloco)}
    citados = _RE_ZIM.findall(bloco)
    return volumes, citados


def _zims_no_disco(diretorio: Path) -> set[str]:
    try:
        return {p.name for p in diretorio.glob("*.zim")}
    except OSError:
        return set()


def comparar(
    volumes: dict[str, Path],
    citados: list[str],
    listar=_zims_no_disco,
) -> dict[str, list[str]]:
    """Divergências nas duas direções. Listas vazias = acervo alinhado."""
    citados_ausentes: list[str] = []
    sem_montagem: list[str] = []
    fora_do_compose: list[str] = []

    citados_por_container: dict[str, set[str]] = {c: set() for c in volumes}
    for caminho in citados:
        base, _, nome = caminho.rpartition("/")
        host = volumes.get(base)
        if host is None:
            sem_montagem.append(caminho)
            continue
        citados_por_container.setdefault(base, set()).add(nome)
        if not (host / nome).exists():
            citados_ausentes.append(caminho)

    for container, host in volumes.items():
        no_disco = listar(host)
        for nome in sorted(no_disco - citados_por_container.get(container, set())):
            fora_do_compose.append(f"{container}/{nome}")

    return {
        "citados_ausentes_no_disco": citados_ausentes,
        "citados_sem_montagem": sem_montagem,
        "no_disco_fora_do_compose": fora_do_compose,
    }


def verificar(caminho: Path = COMPOSE_PADRAO) -> dict[str, list[str]]:
    volumes, citados = ler_compose(caminho)
    return comparar(volumes, citados)


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    resultado = verificar()
    divergencias = sum(len(v) for v in resultado.values())
    if "--json" in argv:
        print(json.dumps({"ok": divergencias == 0, **resultado},
                         ensure_ascii=False, indent=2))
    else:
        if divergencias == 0:
            print("✅ Acervo offline alinhado: todo ZIM do disco está no compose "
                  "e todo ZIM do compose existe no disco.")
        else:
            print("⛔ Acervo offline DIVERGENTE (o kiwix-serve não aceita glob):")
            rotulos = {
                "citados_ausentes_no_disco": "citado no compose e ausente no disco",
                "citados_sem_montagem": "citado em diretório não montado",
                "no_disco_fora_do_compose": "no disco e FORA do compose (invisível na busca)",
            }
            for chave, itens in resultado.items():
                for item in itens:
                    print(f"  - {item}  ({rotulos[chave]})")
            print("\nCorrija docker/tools-compose.yaml e recrie: "
                  "docker compose -f docker/tools-compose.yaml up -d kiwix")
    return 0 if divergencias == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
