"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: core/biblioteca_drive.py
Descrição: espelho da biblioteca do dono — pasta "Biblioteca" do Google
           Drive (22 pastas temáticas, 363 arquivos, 1,35 GB — apurado
           ao vivo em 19/10) — para o disco local, de onde o Calibre Web
           serve e o `calibredb` monta a biblioteca real (metadata.db).

           O Drive é a FONTE DA VERDADE do dono (o hábito dele é colocar
           livro lá); o disco é espelho. Sync incremental por tamanho:
           arquivo local com o mesmo tamanho reportado pelo Drive é pulado
           (rodar todo dia não rebaixa 1,35 GB). Download atômico
           (.part → os.replace) — interrupção nunca deixa arquivo pela
           metade com nome de pronto.

           - Nunca derruba quem chama: erro por arquivo é CONTIDO e volta
             na lista `erros` com o caminho — o resto do sync segue.
           - Nome de arquivo vindo do Drive é saneado ("/" vira "_"):
             nome externo NUNCA decide caminho no nosso disco.
           - Pasta com exatamente 100 itens gera AVISO honesto: o cliente
             Drive da casa pagina em 100 (pageSize) e esta camada ainda não
             persegue cursor — truncar em silêncio seria mentira.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Código associado:
  - integrations/google/drive.py (download_file — binário, atômico)
  - tools/actions/actions.py (action calibre_resync)
  - docker/tools-compose.yaml (Calibre Web lê /books, espelho em
    omegadrakon-tools/biblioteca-drive)
"""

from __future__ import annotations

import pathlib
import time
from typing import Any, Optional

from core.logger import get_logger

log = get_logger("omega.core.biblioteca_drive")

# Nome da pasta no Drive do dono (raiz) — resolvida por nome porque o id
# do Drive antigo (formato pré-2012) é estável mas opaco; o nome é a
# intenção dele. OD_CALIBRE_PASTA_ID cobre quando quiser apontar outra.
NOME_PASTA = "Biblioteca"
_TAMANHO_PAGINA_DRIVE = 100


def _seguro(nome: str) -> str:
    """Nome vindo do Drive sem path traversal: nada de '/' ou '..'."""
    limpo = (nome or "").replace("/", "_").replace("\\", "_").replace("..", "_")
    return limpo.strip() or "sem-nome"


def resolver_pasta(drive: Any, pasta_id: Optional[str] = None) -> dict[str, Any]:
    """Acha a pasta da biblioteca na raiz do Drive (por id ou por nome)."""
    if pasta_id:
        meta = drive.get_file(pasta_id)
        if "folder" not in str(meta.get("mime_type") or ""):
            return {"ok": False, "erro": f"pasta_id {pasta_id} não é pasta"}
        return {"ok": True, "id": pasta_id, "nome": meta.get("name")}
    rascunho = drive.list_files(
        query=(
            "mimeType = 'application/vnd.google-apps.folder' "
            "and trashed = false and 'root' in parents"
        ),
        limit=50,
    )
    for item in rascunho.get("files", []):
        if item.get("name") == NOME_PASTA:
            return {"ok": True, "id": item.get("id"), "nome": NOME_PASTA}
    return {
        "ok": False,
        "erro": f'pasta "{NOME_PASTA}" não encontrada na raiz do Drive',
    }


def sincronizar(
    destino: pathlib.Path | str,
    *,
    drive: Any,
    pasta_id: Optional[str] = None,
    max_arquivo_bytes: int = 512 * 1024 * 1024,
) -> dict[str, Any]:
    """Espelha a pasta da biblioteca do Drive para `destino` (recursivo).

    Devolve stats honestas: `baixados`, `pulados` (mesmo tamanho),
    `bytes` (baixados NESTA rodada), `erros` (contidos, com caminho) e
    `avisos` (ex.: pasta de 100 itens — página cheia, paginação pendente).
    """
    inicio = time.monotonic()
    alvo = pathlib.Path(destino)
    stats: dict[str, Any] = {
        "ok": False,
        "destino": str(alvo),
        "pastas": 0,
        "arquivos": 0,
        "baixados": 0,
        "pulados": 0,
        "bytes": 0,
        "erros": [],
        "avisos": [],
    }
    acha = resolver_pasta(drive, pasta_id)
    if not acha.get("ok"):
        stats["erro"] = acha.get("erro")
        stats["duracao_s"] = round(time.monotonic() - inicio, 1)
        return stats
    stats["pasta"] = acha["nome"]
    raiz = drive.list_files(
        query=f"trashed = false and '{acha['id']}' in parents",
        limit=_TAMANHO_PAGINA_DRIVE,
    )
    if len(raiz.get("files", [])) >= _TAMANHO_PAGINA_DRIVE:
        stats["avisos"].append(
            "pasta raiz com página cheia (100) — itens após o 100º podem "
            "estar fora (paginação do Drive não perseguida ainda)"
        )

    def _caminhar(pasta_id: str, rel: pathlib.Path) -> None:
        itens = drive.list_files(
            query=f"trashed = false and '{pasta_id}' in parents",
            limit=_TAMANHO_PAGINA_DRIVE,
        ).get("files", [])
        if len(itens) >= _TAMANHO_PAGINA_DRIVE:
            stats["avisos"].append(f"{rel}: página cheia (100 itens)")
        for item in itens:
            nome = _seguro(item.get("name") or "")
            if "folder" in str(item.get("mime_type") or ""):
                stats["pastas"] += 1
                _caminhar(item["id"], rel / nome)
                continue
            stats["arquivos"] += 1
            alvo_arq = alvo / rel / nome
            try:
                r = drive.download_file(
                    item["id"],
                    alvo_arq,
                    tamanho_esperado=item.get("size"),
                    max_bytes=max_arquivo_bytes,
                )
            except Exception as exc:  # noqa: BLE001 — contido por arquivo
                stats["erros"].append({"arquivo": str(rel / nome), "erro": str(exc)})
                continue
            if r.get("pulado"):
                stats["pulados"] += 1
            else:
                stats["baixados"] += 1
                stats["bytes"] += int(r.get("bytes") or 0)

    alvo.mkdir(parents=True, exist_ok=True)
    _caminhar(acha["id"], pathlib.Path())
    stats["ok"] = not stats["erros"]
    stats["duracao_s"] = round(time.monotonic() - inicio, 1)
    log.info(
        "Sync da biblioteca do dono",
        destino=str(alvo),
        pastas=stats["pastas"],
        arquivos=stats["arquivos"],
        baixados=stats["baixados"],
        pulados=stats["pulados"],
        erros=len(stats["erros"]),
    )
    return stats
