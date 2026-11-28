#!/usr/bin/env python3
"""Inventário de arquivos do OmegaDrakon (Fase 1: somente leitura).

Mede, sem mover nem apagar nada:

- tamanho / nº de arquivos / idade por pasta (raiz, 1º e 2º nível);
- arquivos soltos na raiz, vazios e nomes com espaço;
- **duplicatas por hash** (só grupos com mesmo tamanho são hasheados);
- **catálogo de compactados** (zip/tar/7z/rar) com a contagem de entradas e
  busca de termo na listagem interna, sem extrair.

Saídas: relatório Markdown (`docs/INVENTARIO_ARQUIVOS.md` por padrão), JSON
(`--json`) ou busca pontual (`--buscar TERMO`).

Uso:
    python3 tools/inventario_arquivos.py
    python3 tools/inventario_arquivos.py --json
    python3 tools/inventario_arquivos.py --buscar nicky
    python3 tools/inventario_arquivos.py --incluir-build   # entra em app/build

A Fase 2 (mover / arquivar / apagar) é decisão do dono, item por item — este
script nunca escreve fora da saída de relatório.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path

RAIZ_PADRAO = Path(__file__).resolve().parent.parent
SAIDA_PADRAO = Path("docs/INVENTARIO_ARQUIVOS.md")

# Pastas que nunca entram na conta: versionamento, ambiente virtual, caches.
EXCLUIR_SEMPRE = {
    ".git",
    ".venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".aider.tags.cache.v4",
    "__pycache__",
    "node_modules",
}

# Artefatos de build: barulho recuperável; ficam fora a menos que --incluir-build.
EXCLUIR_BUILD = {
    "app/build",
    "app/.dart_tool",
    "app/android/.gradle",
    ".dart_tool",
    ".gradle",
    "build",
}

EXT_COMPACTADOS = {
    ".zip": "zip",
    ".tar": "tar",
    ".tar.gz": "tar",
    ".tgz": "tar",
    ".tar.bz2": "tar",
    ".tbz2": "tar",
    ".tar.xz": "tar",
    ".txz": "tar",
    ".gz": "gz",
    ".7z": "7z",
    ".rar": "rar",
}

TAMANHO_MAX_HASH = 200 * 1024 * 1024  # 200 MB por arquivo


def _dentro(rel: str, alvos: set[str]) -> bool:
    return any(rel == a or rel.startswith(a + "/") for a in alvos)


def _tipo_compactado(nome: str) -> str | None:
    minusculo = nome.lower()
    if minusculo.endswith(".tar.gz"):
        return "tar"
    if minusculo.endswith(".tar.bz2") or minusculo.endswith(".tar.xz"):
        return "tar"
    return EXT_COMPACTADOS.get(Path(minusculo).suffix)


def _sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def listar_arquivos(
    raiz: Path,
    *,
    incluir_build: bool = False,
    excluir_extras: set[str] | None = None,
) -> list[Path]:
    """Todos os arquivos regulares dentro da raiz, respeitando as exclusões."""
    excluir = set(EXCLUIR_SEMPRE)
    if not incluir_build:
        excluir |= EXCLUIR_BUILD
    excluir |= excluir_extras or set()

    achados: list[Path] = []
    for atual, dirs, arquivos in os.walk(raiz):
        rel = Path(atual).relative_to(raiz).as_posix()
        rel = "" if rel == "." else rel
        dirs[:] = [
            d for d in dirs if not _dentro(f"{rel}/{d}".lstrip("/"), excluir)
        ]
        for nome in arquivos:
            caminho = Path(atual) / nome
            if caminho.is_symlink() or not caminho.is_file():
                continue
            achados.append(caminho)
    return achados


def resumir_pasta(
    raiz: Path, arquivos: list[Path], profundidade: int = 1
) -> list[dict]:
    """Agrega tamanho/itens/idade por pasta até a profundidade pedida."""
    grupos: dict[str, dict] = {}
    for caminho in arquivos:
        partes = caminho.relative_to(raiz).parts
        if len(partes) <= profundidade:
            chave = partes[0] if len(partes) > 1 else "(raiz)"
        else:
            chave = "/".join(partes[:profundidade])
        g = grupos.setdefault(
            chave,
            {"pasta": chave, "bytes": 0, "arquivos": 0, "mais_novo": 0.0, "mais_antigo": None},
        )
        try:
            st = caminho.stat()
        except OSError:
            continue
        g["bytes"] += st.st_size
        g["arquivos"] += 1
        g["mais_novo"] = max(g["mais_novo"], st.st_mtime)
        g["mais_antigo"] = st.st_mtime if g["mais_antigo"] is None else min(
            g["mais_antigo"], st.st_mtime
        )
    return sorted(grupos.values(), key=lambda g: g["bytes"], reverse=True)


def achar_duplicatas(arquivos: list[Path], raiz: Path) -> tuple[list[dict], dict]:
    """Duplicatas por conteúdo: agrupa por tamanho e confirma com SHA-256."""
    por_tamanho: dict[int, list[Path]] = {}
    for caminho in arquivos:
        try:
            tamanho = caminho.stat().st_size
        except OSError:
            continue
        if tamanho == 0 or tamanho > TAMANHO_MAX_HASH:
            continue
        por_tamanho.setdefault(tamanho, []).append(caminho)

    grupos: list[dict] = []
    metricas = {"arquivos_hasheados": 0, "grupos": 0, "bytes_desperdicados": 0}
    for tamanho, candidatos in por_tamanho.items():
        if len(candidatos) < 2:
            continue
        por_hash: dict[str, list[Path]] = {}
        for caminho in candidatos:
            try:
                digest = _sha256(caminho)
            except OSError:
                continue
            metricas["arquivos_hasheados"] += 1
            por_hash.setdefault(digest, []).append(caminho)
        for digest, iguais in por_hash.items():
            if len(iguais) < 2:
                continue
            desperdicio = tamanho * (len(iguais) - 1)
            grupos.append(
                {
                    "sha256": digest,
                    "bytes": tamanho,
                    "arquivos": sorted(
                        c.relative_to(raiz).as_posix() for c in iguais
                    ),
                    "desperdicio": desperdicio,
                }
            )
            metricas["grupos"] += 1
            metricas["bytes_desperdicados"] += desperdicio
    grupos.sort(key=lambda g: g["desperdicio"], reverse=True)
    return grupos, metricas


def _entradas_compactado(caminho: Path, tipo: str) -> list[str] | None:
    """Listagem interna do compactado; None quando não dá para ler."""
    try:
        if tipo == "zip":
            with zipfile.ZipFile(caminho) as z:
                return z.namelist()
        if tipo == "tar":
            with tarfile.open(caminho, "r:*") as t:
                return [m.name for m in t.getmembers()]
    except (tarfile.TarError, zipfile.BadZipFile, OSError):
        return None

    ferramenta = shutil.which("7z") or shutil.which("7za")
    if tipo == "rar" and shutil.which("unrar"):
        ferramenta = "unrar"
    if not ferramenta:
        return None
    comando = (
        [ferramenta, "lb", str(caminho)]
        if ferramenta == "unrar"
        else [ferramenta, "l", "-ba", "-slt", str(caminho)]
    )
    try:
        saida = subprocess.run(
            comando, capture_output=True, text=True, timeout=120, check=False
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    nomes = []
    for linha in saida.splitlines():
        linha = linha.strip()
        if not linha:
            continue
        if linha.startswith("Path = "):
            nomes.append(linha.split("=", 1)[1].strip())
        elif ferramenta == "unrar":
            nomes.append(linha)
    return nomes or None


def catalogar_compactados(
    arquivos: list[Path], raiz: Path
) -> list[dict]:
    catalogo = []
    for caminho in arquivos:
        tipo = _tipo_compactado(caminho.name)
        if tipo is None:
            continue
        if tipo == "gz":
            # gzip de arquivo único (ex.: dump .sql.gz): 1 entrada, nome sem .gz
            entradas = [caminho.name[:-3] if caminho.name.endswith(".gz") else caminho.name]
        else:
            entradas = _entradas_compactado(caminho, tipo)
        try:
            st = caminho.stat()
        except OSError:
            continue
        catalogo.append(
            {
                "arquivo": caminho.relative_to(raiz).as_posix(),
                "tipo": tipo,
                "bytes": st.st_size,
                "mtime": st.st_mtime,
                "entradas": len(entradas) if entradas is not None else None,
                "listagem": entradas,
            }
        )
    catalogo.sort(key=lambda c: c["bytes"], reverse=True)
    return catalogo


def buscar_nos_compactados(catalogo: list[dict], termo: str) -> list[dict]:
    alvo = termo.lower()
    achados = []
    for item in catalogo:
        nomes = item.get("listagem") or []
        casam = [n for n in nomes if alvo in n.lower()]
        if casam:
            achados.append(
                {
                    "arquivo": item["arquivo"],
                    "ocorrencias": len(casam),
                    "exemplos": casam[:10],
                }
            )
    return achados


def montar_inventario(
    raiz: Path, *, incluir_build: bool = False, busca: str | None = None
) -> dict:
    arquivos = listar_arquivos(raiz, incluir_build=incluir_build)
    duplicatas, metricas_hash = achar_duplicatas(arquivos, raiz)
    catalogo = catalogar_compactados(arquivos, raiz)
    total = sum(c.stat().st_size for c in arquivos if c.exists())
    soltos = sorted(
        c.name for c in arquivos if c.parent == raiz
    )
    vazios = [
        c.relative_to(raiz).as_posix() for c in arquivos if c.stat().st_size == 0
    ]
    com_espaco = [
        c.relative_to(raiz).as_posix()
        for c in arquivos
        if any(" " in parte for parte in c.relative_to(raiz).parts)
    ]
    inventario = {
        "gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "raiz": str(raiz),
        "incluir_build": incluir_build,
        "totais": {
            "arquivos": len(arquivos),
            "bytes": total,
            "compactados": len(catalogo),
        },
        "nivel1": resumir_pasta(raiz, arquivos, 1),
        "nivel2": resumir_pasta(raiz, arquivos, 2),
        "raiz_soltos": soltos,
        "vazios": vazios,
        "com_espaco": com_espaco,
        "duplicatas": duplicatas[:50],
        "duplicatas_total_grupos": len(duplicatas),
        "metricas_hash": metricas_hash,
        "compactados": [
            {k: v for k, v in item.items() if k != "listagem"}
            for item in catalogo
        ],
    }
    if busca is not None:
        inventario["busca"] = buscar_nos_compactados(catalogo, busca)
    return inventario


def _humano(bytes_: int) -> str:
    valor = float(bytes_)
    for unidade in ("B", "KB", "MB", "GB", "TB"):
        if valor < 1024 or unidade == "TB":
            if unidade == "B":
                return f"{int(valor)} B"
            return f"{valor:.1f} {unidade}".replace(".", ",")
        valor /= 1024
    return f"{valor:.1f} TB".replace(".", ",")


def _data(ts: float | None) -> str:
    if not ts:
        return "—"
    return time.strftime("%d/%m/%Y", time.localtime(ts))


def gerar_markdown(inv: dict, busca: str | None = None) -> str:
    linhas: list[str] = []
    add = linhas.append
    add("# Inventário de arquivos do OmegaDrakon (Fase 1)")
    add("")
    add(f"Gerado em **{inv['gerado_em']}** por `tools/inventario_arquivos.py` "
        "(somente leitura — nada foi movido ou apagado).")
    add("")
    add(f"- Raiz: `{inv['raiz']}`")
    add(f"- Artefatos de build ({'incluídos' if inv['incluir_build'] else 'excluídos'}): "
        "`app/build`, `app/.dart_tool`, `.dart_tool`, `build`")
    add("- Excluídos sempre: `.git`, `.venv`, caches (`__pycache__`, `.pytest_cache`, "
        "`node_modules`, …)")
    add("")
    add("## Totais")
    add("")
    add("| Arquivos | Tamanho | Compactados |")
    add("|---:|---:|---:|")
    add(f"| {inv['totais']['arquivos']:,} | {_humano(inv['totais']['bytes'])} | "
        f"{inv['totais']['compactados']} |".replace(",", "."))
    add("")

    add("## Por pasta (1º nível)")
    add("")
    add("| Pasta | Tamanho | Arquivos | Mais novo |")
    add("|---|---:|---:|---|")
    for g in inv["nivel1"]:
        add(f"| `{g['pasta']}` | {_humano(g['bytes'])} | {g['arquivos']} | "
            f"{_data(g['mais_novo'])} |")
    add("")

    add("## Detalhe (2º nível, maiores primeiro)")
    add("")
    add("| Pasta | Tamanho | Arquivos | Mais novo | Mais antigo |")
    add("|---|---:|---:|---|---|")
    for g in inv["nivel2"][:40]:
        add(f"| `{g['pasta']}` | {_humano(g['bytes'])} | {g['arquivos']} | "
            f"{_data(g['mais_novo'])} | {_data(g['mais_antigo'])} |")
    add("")

    add("## Duplicatas por hash (SHA-256)")
    add("")
    m = inv["metricas_hash"]
    add(f"- Arquivos hasheados: **{m['arquivos_hasheados']}** "
        f"(só grupos com mesmo tamanho; arquivos acima de 200 MB ficam de fora)")
    add(f"- Grupos duplicados: **{inv['duplicatas_total_grupos']}**")
    add(f"- Espaço recuperável: **{_humano(m['bytes_desperdicados'])}**")
    add("")
    if inv["duplicatas"]:
        add("| Tamanho cada | Cópias | Desperdício | Arquivos |")
        add("|---:|---:|---:|---|")
        for g in inv["duplicatas"][:20]:
            arquivos = "<br>".join(f"`{a}`" for a in g["arquivos"][:4])
            if len(g["arquivos"]) > 4:
                arquivos += f"<br>… +{len(g['arquivos']) - 4}"
            add(f"| {_humano(g['bytes'])} | {len(g['arquivos'])} | "
                f"{_humano(g['desperdicio'])} | {arquivos} |")
        if inv["duplicatas_total_grupos"] > len(inv["duplicatas"][:20]):
            add("")
            add(f"_Mostrando 20 de {inv['duplicatas_total_grupos']} grupos._")
    else:
        add("_Nenhuma duplicata encontrada._")
    add("")

    add("## Compactados (catálogo)")
    add("")
    add("| Arquivo | Tipo | Tamanho | Entradas | Data |")
    add("|---|---|---:|---:|---|")
    for c in inv["compactados"]:
        entradas = c["entradas"] if c["entradas"] is not None else "não lido"
        add(f"| `{c['arquivo']}` | {c['tipo']} | {_humano(c['bytes'])} | "
            f"{entradas} | {_data(c['mtime'])} |")
    add("")
    add("Para procurar um termo dentro dos compactados sem extrair:")
    add("")
    add("```")
    add("python3 tools/inventario_arquivos.py --buscar nicky")
    add("```")
    add("")

    if busca is not None:
        add(f"## Busca por \"{busca}\" nos compactados")
        add("")
        achados = inv.get("busca") or []
        if not achados:
            add("_Nenhuma ocorrência na listagem interna._")
        else:
            for a in achados:
                add(f"- `{a['arquivo']}` — {a['ocorrencias']} ocorrência(s)")
                for exemplo in a["exemplos"]:
                    add(f"  - `{exemplo}`")
        add("")

    add("## Pontos de arrumação que já aparecem")
    add("")
    add(f"- Arquivos soltos na raiz: **{len(inv['raiz_soltos'])}** — "
        + (", ".join(f"`{n}`" for n in inv["raiz_soltos"]) or "nenhum"))
    add(f"- Arquivos vazios: **{len(inv['vazios'])}** — "
        + (", ".join(f"`{n}`" for n in inv["vazios"][:10]) or "nenhum"))
    add(f"- Nomes com espaço (até 1º nível): **{len(inv['com_espaco'])}**")
    add("")
    add("## Próximo passo (Fase 2 — decisão do dono)")
    add("")
    add("A Fase 2 (manter / mover / arquivar / lixo) é feita por lote, com a lista "
        "na mão e aprovação item por item — este inventário não move nada.")
    return "\n".join(linhas) + "\n"


def _principal(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raiz", default=str(RAIZ_PADRAO))
    parser.add_argument("--saida", default=str(SAIDA_PADRAO))
    parser.add_argument("--incluir-build", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--buscar", default=None)
    args = parser.parse_args(argv)

    raiz = Path(args.raiz).resolve()
    inv = montar_inventario(
        raiz, incluir_build=args.incluir_build, busca=args.buscar
    )

    if args.json:
        print(json.dumps(inv, ensure_ascii=False, indent=2))
        return 0

    saida = Path(args.saida)
    if not saida.is_absolute():
        saida = raiz / saida
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(gerar_markdown(inv, busca=args.buscar), encoding="utf-8")
    print(f"inventário escrito em {saida}")
    print(
        f"{inv['totais']['arquivos']} arquivos · "
        f"{_humano(inv['totais']['bytes'])} · "
        f"{inv['duplicatas_total_grupos']} grupos duplicados "
        f"({_humano(inv['metricas_hash']['bytes_desperdicados'])}) · "
        f"{inv['totais']['compactados']} compactados"
    )
    return 0


if __name__ == "__main__":
    sys.exit(_principal())
