"""
OMEGA DRAKON • TESTES
Tecnologia que respira.
Módulo: tests/test_biblioteca_drive.py
Descrição: espelho da biblioteca do dono (Google Drive "Biblioteca" →
           disco) — resolução da pasta, sync recursivo incremental,
           saneamento de nome, erro contido por arquivo e aviso de página
           cheia. Drive falso no MESMO formato do DriveService real
           (resumo _summary: id/name/mime_type/size).

Decisão do dono (19/10): Calibre Web "configurar e interligar"; os livros
estão no Google Drive dele (22 pastas temáticas, 363 arquivos, 1,35 GB).
"""

from __future__ import annotations

from typing import Any

from core.biblioteca_drive import resolver_pasta, sincronizar


class FakeDrive:
    """DriveService falso: mesma interface usada pelo sync.

    Cada nó tem id ÚNICO atribuído na construção (`p-<nome>` para pasta,
    `a-<nome>` para arquivo) — o lookup é um passeio por id, sem mágica.
    """

    def __init__(self, raiz: dict[str, Any]) -> None:
        self.raiz = raiz
        self.downloads: list[str] = []
        self.falhar: set[str] = set()

    # -- helpers de construção ------------------------------------------
    @staticmethod
    def pasta(nome: str, filhos: list | None = None) -> dict[str, Any]:
        return {"kind": "folder", "id": f"p-{nome}", "name": nome, "children": filhos or []}

    @staticmethod
    def arquivo(nome: str, tamanho: int = 10) -> dict[str, Any]:
        return {"kind": "file", "id": f"a-{nome}", "name": nome, "size": str(tamanho)}

    # -- interface do DriveService --------------------------------------
    def get_file(self, file_id: str) -> dict[str, Any]:
        no = self._achar(self.raiz, file_id)
        if no is None:
            return {"id": file_id, "name": "", "mime_type": ""}
        return {
            "id": file_id,
            "name": no["name"],
            "mime_type": (
                "application/vnd.google-apps.folder"
                if no["kind"] == "folder"
                else "application/pdf"
            ),
            "size": no.get("size"),
        }

    def list_files(self, *, query: str = "", limit: int = 20) -> dict[str, Any]:
        import re

        m = re.search(r"'([^']+)' in parents", query)
        if not m or m.group(1) == "root":
            pai = self.raiz
        else:
            pai = self._achar(self.raiz, m.group(1))
        itens = (pai or {}).get("children", [])
        filhos = [
            {
                "id": item["id"],
                "name": item["name"],
                "mime_type": (
                    "application/vnd.google-apps.folder"
                    if item["kind"] == "folder"
                    else "application/pdf"
                ),
                "size": item.get("size"),
            }
            for item in itens
        ]
        return {"files": filhos[:limit], "count": min(len(filhos), limit)}

    def download_file(self, file_id: str, destino, *, tamanho_esperado=None, **kw):
        import pathlib

        if file_id in self.falhar:
            raise RuntimeError("falha de rede simulada")
        no = self._achar(self.raiz, file_id)
        assert no is not None, f"download de id desconhecido: {file_id}"
        alvo = pathlib.Path(destino)
        if (
            tamanho_esperado is not None
            and alvo.is_file()
            and alvo.stat().st_size == int(tamanho_esperado)
        ):
            return {  # pulado: NÃO conta como download
                "file_id": file_id,
                "destino": str(alvo),
                "bytes": alvo.stat().st_size,
                "pulado": True,
            }
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_bytes(b"x" * int(no["size"]))
        self.downloads.append(file_id)
        return {
            "file_id": file_id,
            "destino": str(alvo),
            "bytes": int(no["size"]),
            "pulado": False,
        }

    # -- navegação interna ----------------------------------------------
    @staticmethod
    def _achar(no: dict[str, Any], file_id: str) -> dict[str, Any] | None:
        for filho in no.get("children", []):
            if filho["id"] == file_id:
                return filho
            if filho["kind"] == "folder":
                achado = FakeDrive._achar(filho, file_id)
                if achado is not None:
                    return achado
        return None


def _biblioteca_padrao() -> FakeDrive:
    """Raiz = Drive do dono; 'Biblioteca' com 2 pastas temáticas."""
    return FakeDrive(
        FakeDrive.pasta(
            "raiz",
            [
                FakeDrive.pasta(
                    "Biblioteca",
                    [
                        FakeDrive.pasta("Direito", [FakeDrive.arquivo("constituicao.pdf", 30)]),
                        FakeDrive.pasta("Hacker", [FakeDrive.arquivo("manual.txt", 5)]),
                        FakeDrive.arquivo("avulso.epub", 20),
                    ],
                ),
                FakeDrive.pasta("OmegaDrakon", [FakeDrive.arquivo("spec.md", 1)]),
            ],
        )
    )


class TestResolverPasta:
    def test_acha_por_nome_na_raiz(self) -> None:
        r = resolver_pasta(_biblioteca_padrao())
        assert r["ok"] and r["nome"] == "Biblioteca"

    def test_id_explicito_valida_que_e_pasta(self) -> None:
        drive = _biblioteca_padrao()
        id_bib = drive.list_files(query="'root' in parents")["files"][0]["id"]
        r = resolver_pasta(drive, pasta_id=id_bib)
        assert r["ok"] and r["id"] == id_bib

    def test_id_que_nao_e_pasta_recusa(self) -> None:
        drive = _biblioteca_padrao()
        r = resolver_pasta(drive, pasta_id="p-Biblioteca")
        assert r["ok"]
        r2 = resolver_pasta(drive, pasta_id="a-avulso.epub")
        assert not r2["ok"] and "não é pasta" in r2["erro"]

    def test_sem_biblioteca_erro_honesto(self) -> None:
        drive = FakeDrive(FakeDrive.pasta("raiz", [FakeDrive.pasta("Outra", [])]))
        r = resolver_pasta(drive)
        assert not r["ok"] and "Biblioteca" in r["erro"]


class TestSincronizar:
    def test_espelha_recursivo_e_saneia_nome(self, tmp_path) -> None:
        drive = _biblioteca_padrao()
        r = sincronizar(tmp_path, drive=drive)
        assert r["ok"] and r["pastas"] == 2 and r["arquivos"] == 3
        assert (tmp_path / "Direito" / "constituicao.pdf").is_file()
        assert (tmp_path / "Hacker" / "manual.txt").is_file()
        assert (tmp_path / "avulso.epub").is_file()
        # a pasta OmegaDrakon do dono NÃO entra (só a Biblioteca)
        assert not (tmp_path / "OmegaDrakon").exists()
        assert r["bytes"] == 30 + 5 + 20

    def test_segunda_rodada_pula_tudo(self, tmp_path) -> None:
        drive = _biblioteca_padrao()
        sincronizar(tmp_path, drive=drive)
        downloads_primeira = len(drive.downloads)
        r2 = sincronizar(tmp_path, drive=drive)
        assert r2["ok"] and r2["pulados"] == 3 and r2["baixados"] == 0
        assert len(drive.downloads) == downloads_primeira  # nada novo baixado

    def test_erro_por_arquivo_e_contido(self, tmp_path) -> None:
        drive = _biblioteca_padrao()
        drive.falhar.add("a-manual.txt")
        r = sincronizar(tmp_path, drive=drive)
        assert not r["ok"] and len(r["erros"]) == 1
        assert "manual.txt" in r["erros"][0]["arquivo"]
        # os outros dois arquivos foram baixados apesar da falha
        assert (tmp_path / "Direito" / "constituicao.pdf").is_file()

    def test_pasta_com_pagina_cheia_gera_aviso(self, tmp_path) -> None:
        drive = FakeDrive(
            FakeDrive.pasta(
                "raiz",
                [
                    FakeDrive.pasta(
                        "Biblioteca",
                        [FakeDrive.arquivo(f"livro{i:03d}.pdf", 1) for i in range(100)],
                    )
                ],
            )
        )
        r = sincronizar(tmp_path, drive=drive)
        assert r["ok"] and any("página cheia" in a for a in r["avisos"])

    def test_nome_com_barra_nao_escapa_do_destino(self, tmp_path) -> None:
        from core.biblioteca_drive import _seguro

        drive = FakeDrive(
            FakeDrive.pasta(
                "raiz",
                [FakeDrive.pasta("Biblioteca", [FakeDrive.arquivo("../../etc/passwd.pdf", 3)])],
            )
        )
        destino = tmp_path / "biblia"
        r = sincronizar(destino, drive=drive)
        assert r["ok"]
        # o nome vindo do Drive é saneado e o arquivo vive DENTRO do destino
        assert (destino / _seguro("../../etc/passwd.pdf")).is_file()
        assert not (tmp_path / "etc").exists()
        assert not list(tmp_path.glob("etc*"))
