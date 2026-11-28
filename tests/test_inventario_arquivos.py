"""Testes da Fase 1 de organização (tools/inventario_arquivos.py)."""

from __future__ import annotations

import tarfile
import zipfile

import pytest

from tools import inventario_arquivos as inv


def _montar_arvore(raiz):
    (raiz / "app" / "build" / "saida").mkdir(parents=True)
    (raiz / "app" / "lib").mkdir(parents=True)
    (raiz / ".venv" / "lib").mkdir(parents=True)
    (raiz / "backups").mkdir()

    (raiz / "app" / "lib" / "main.dart").write_text("void main() {}\n")
    (raiz / "app" / "build" / "saida" / "od.apk").write_bytes(b"apk" * 100)
    (raiz / ".venv" / "lib" / "segredo.py").write_text("x = 1\n")

    (raiz / "backups" / "copia-1.txt").write_text("conteudo repetido\n")
    (raiz / "backups" / "copia-2.txt").write_text("conteudo repetido\n")
    (raiz / "backups" / "diferente.txt").write_text("conteudo diferent\n")
    (raiz / "vazio.txt").write_text("")

    with tarfile.open(raiz / "backups" / "acervo.tar.gz", "w:gz") as t:
        arquivo = raiz / "backups" / "copia-1.txt"
        t.add(arquivo, arcname="Nicky Locutor/voz.txt")
    with zipfile.ZipFile(raiz / "backups" / "pacote.zip", "w") as z:
        z.writestr("Prompt_Nicky_Musicas.txt", "m3u")


def test_listar_arquivos_respeita_exclusoes(tmp_path):
    _montar_arvore(tmp_path)

    nomes = sorted(
        c.relative_to(tmp_path).as_posix()
        for c in inv.listar_arquivos(tmp_path)
    )

    assert "app/lib/main.dart" in nomes
    assert not any(n.startswith(".venv/") for n in nomes)
    assert not any(n.startswith("app/build/") for n in nomes)


def test_listar_arquivos_com_build(tmp_path):
    _montar_arvore(tmp_path)

    nomes = {
        c.relative_to(tmp_path).as_posix()
        for c in inv.listar_arquivos(tmp_path, incluir_build=True)
    }

    assert "app/build/saida/od.apk" in nomes
    assert not any(n.startswith(".venv/") for n in nomes)


def test_achar_duplicatas_por_hash(tmp_path):
    _montar_arvore(tmp_path)
    arquivos = inv.listar_arquivos(tmp_path)

    grupos, metricas = inv.achar_duplicatas(arquivos, tmp_path)

    iguais = [g for g in grupos if len(g["arquivos"]) == 2]
    assert len(iguais) == 1
    assert sorted(iguais[0]["arquivos"]) == [
        "backups/copia-1.txt",
        "backups/copia-2.txt",
    ]
    assert iguais[0]["desperdicio"] == len("conteudo repetido\n")
    assert metricas["grupos"] == len(grupos)
    # mesmo tamanho, conteúdo diferente: não é duplicata
    assert not any("diferente.txt" in g["arquivos"] for g in grupos)
    # arquivo vazio não entra na conta
    assert not any("vazio.txt" in g["arquivos"] for g in grupos)


def test_catalogar_compactados_conta_entradas(tmp_path):
    _montar_arvore(tmp_path)

    catalogo = inv.catalogar_compactados(inv.listar_arquivos(tmp_path), tmp_path)
    por_nome = {c["arquivo"]: c for c in catalogo}

    assert set(por_nome) == {"backups/acervo.tar.gz", "backups/pacote.zip"}
    assert por_nome["backups/acervo.tar.gz"]["entradas"] == 1
    assert por_nome["backups/acervo.tar.gz"]["tipo"] == "tar"
    assert por_nome["backups/pacote.zip"]["entradas"] == 1


def test_buscar_nos_compactados_sem_extrair(tmp_path):
    _montar_arvore(tmp_path)
    catalogo = inv.catalogar_compactados(inv.listar_arquivos(tmp_path), tmp_path)

    achados = inv.buscar_nos_compactados(catalogo, "NICKY")

    arquivos = {a["arquivo"]: a for a in achados}
    assert set(arquivos) == {"backups/acervo.tar.gz", "backups/pacote.zip"}
    assert arquivos["backups/acervo.tar.gz"]["exemplos"] == ["Nicky Locutor/voz.txt"]
    assert inv.buscar_nos_compactados(catalogo, "inexistente") == []


def test_gzip_de_arquivo_unico_vira_uma_entrada(tmp_path):
    import gzip

    (tmp_path / "dump.sql.gz").write_bytes(gzip.compress(b"CREATE TABLE t();"))

    catalogo = inv.catalogar_compactados(inv.listar_arquivos(tmp_path), tmp_path)

    assert len(catalogo) == 1
    assert catalogo[0]["tipo"] == "gz"
    assert catalogo[0]["entradas"] == 1
    assert catalogo[0]["listagem"] == ["dump.sql"]


def test_nome_com_espaco_inclui_pastas(tmp_path):
    pasta = tmp_path / "Nicky Locutor"
    pasta.mkdir()
    (pasta / "voz.txt").write_text("oi\n")

    inventario = inv.montar_inventario(tmp_path)

    assert inventario["com_espaco"] == ["Nicky Locutor/voz.txt"]


def test_montar_inventario_agrega_e_monta_relatorio(tmp_path):
    _montar_arvore(tmp_path)

    inventario = inv.montar_inventario(tmp_path)
    texto = inv.gerar_markdown(inventario)

    assert inventario["totais"]["compactados"] == 2
    assert inventario["totais"]["arquivos"] == len(inv.listar_arquivos(tmp_path))
    assert "vazio.txt" in inventario["vazios"]
    assert "## Duplicatas por hash" in texto
    assert "backups/copia-1.txt" in texto
    assert "python3 tools/inventario_arquivos.py --buscar nicky" in texto
    assert "Arquivos vazios: **1**" in texto


def test_busca_aparece_no_relatorio(tmp_path):
    _montar_arvore(tmp_path)
    inventario = inv.montar_inventario(tmp_path)
    catalogo = inv.catalogar_compactados(inv.listar_arquivos(tmp_path), tmp_path)
    inventario["busca"] = inv.buscar_nos_compactados(catalogo, "locutor")

    texto = inv.gerar_markdown(inventario, busca="locutor")

    assert '## Busca por "locutor" nos compactados' in texto
    assert "`backups/acervo.tar.gz` — 1 ocorrência(s)" in texto


def test_principal_escreve_relatorio(tmp_path, monkeypatch):
    _montar_arvore(tmp_path)
    monkeypatch.chdir(tmp_path)

    codigo = inv._principal(["--raiz", str(tmp_path), "--saida", "docs/inv.md"])

    assert codigo == 0
    escrito = (tmp_path / "docs" / "inv.md").read_text(encoding="utf-8")
    assert "# Inventário de arquivos do OmegaDrakon" in escrito
    assert "backups/acervo.tar.gz" in escrito


def test_principal_json_e_busca(tmp_path, caplog):
    _montar_arvore(tmp_path)
    import json

    monkeypatch_stdout = []

    def _fake_print(*args, **kwargs):
        monkeypatch_stdout.append(" ".join(str(a) for a in args))

    import builtins

    original = builtins.print
    builtins.print = _fake_print
    try:
        codigo = inv._principal(["--raiz", str(tmp_path), "--json", "--buscar", "nicky"])
    finally:
        builtins.print = original

    assert codigo == 0
    dados = json.loads("\n".join(monkeypatch_stdout))
    assert dados["busca"][0]["arquivo"] == "backups/acervo.tar.gz"
