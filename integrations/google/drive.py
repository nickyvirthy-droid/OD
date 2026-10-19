"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/google/drive.py
Descrição: DriveService — Google Drive: leitura (listar/buscar arquivos,
           metadados e conteúdo de texto) + ESCRITA (criar/editar/apagar)
           do lote 2 (escopo drive, 2026-10-03).

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import json
import os
import pathlib
import uuid
from typing import Any, Optional

from integrations.google.client import DRIVE_BASE, GoogleClient
from integrations.google.transport import GoogleError

__signature__ = "OD // CORE"

# Campos pedidos (reduz tráfego e estabiliza o contrato com o chat).
_FIELDS = "id,name,mimeType,modifiedTime,size,webViewLink,owners(displayName)"

# Exportação de arquivos nativos do Google (Docs/Sheets/Slides) como texto.
_EXPORTS: dict[str, str] = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}
_MAX_TEXT_BYTES = 200_000
# Teto por arquivo no download binário: o transporte devolve o corpo em
# memória. A biblioteca do dono (Drive "Biblioteca", apurado 19/10) tem
# arquivos de até ~130 MB — 512 MB dá folga com folga e evita que um
# arquivo gigante por acidente estoure o processo do od-core.
_MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024


class DriveService:
    """Operações de leitura do Drive sobre um GoogleClient."""

    def __init__(self, client: GoogleClient) -> None:
        self.client = client

    def list_files(self, *, query: str = "", limit: int = 20) -> dict[str, Any]:
        """Lista/busca arquivos (ordem: modificado recentemente primeiro)."""
        page_size = max(1, min(int(limit or 20), 100))
        params: dict[str, Any] = {
            "pageSize": page_size,
            "fields": f"files({_FIELDS})",
            "orderBy": "modifiedTime desc",
        }
        if query:
            params["q"] = query
        data = self.client.get(f"{DRIVE_BASE}/files", params=params)
        files = data.get("files", []) if isinstance(data, dict) else []
        return {
            "files": [self._summary(f) for f in files],
            "count": len(files),
        }

    def get_file(self, file_id: str) -> dict[str, Any]:
        """Metadados de um arquivo pelo id."""
        data = self.client.get(
            f"{DRIVE_BASE}/files/{file_id}", params={"fields": _FIELDS}
        )
        return self._summary(data if isinstance(data, dict) else {})

    def read_text(
        self, file_id: str, *, max_bytes: int = _MAX_TEXT_BYTES
    ) -> dict[str, Any]:
        """Lê o conteúdo textual: exporta nativos do Google, baixa os demais."""
        meta = self.get_file(file_id)
        mime = str(meta.get("mime_type") or "")
        if mime.startswith("application/vnd.google-apps"):
            export_mime = _EXPORTS.get(mime, "text/plain")
            raw = self.client.request_raw(
                "GET",
                f"{DRIVE_BASE}/files/{file_id}/export",
                params={"mimeType": export_mime},
                accept=export_mime,
            )
        else:
            raw = self.client.request_raw(
                "GET",
                f"{DRIVE_BASE}/files/{file_id}",
                params={"alt": "media"},
                accept="text/plain, */*",
            )
        limit = max(1, int(max_bytes))
        text = raw[:limit].decode("utf-8", errors="replace")
        return {
            "file_id": file_id,
            "name": meta.get("name"),
            "mime_type": mime,
            "text": text,
            "bytes": len(raw),
            "truncated": len(raw) > limit,
        }

    def download_file(
        self,
        file_id: str,
        destino: "pathlib.Path",
        *,
        tamanho_esperado: Optional[int] = None,
        pular_se_mesmo_tamanho: bool = True,
        max_bytes: int = _MAX_DOWNLOAD_BYTES,
    ) -> dict[str, Any]:
        """Baixa um arquivo BINÁRIO do Drive para o disco (atômico).

        Diferença para `read_text`: o corpo vai para o disco em `.part` e
        só vira o destino final no `os.replace` — download interrompido
        nunca deixa arquivo pela metade com nome de pronto (mesma régua
        do backup/tar da casa). Se o destino já existe com o MESMO tamanho
        reportado pelo Drive, o download é pulado (semântica de sync —
        o espelho da biblioteca do dono roda toda vez sem rebaixar 1,35 GB).
        `max_bytes` é o teto honesto por arquivo: o transporte carrega o
        corpo em memória (limitação declarada; a biblioteca do dono tem
        arquivos de até ~130 MB).
        """
        meta = self.get_file(file_id)
        alvo = pathlib.Path(destino)
        alvo.parent.mkdir(parents=True, exist_ok=True)
        tamanho_meta = int(meta.get("size") or 0) or None
        if (
            pular_se_mesmo_tamanho
            and tamanho_esperado is not None
            and alvo.is_file()
            and alvo.stat().st_size == int(tamanho_esperado)
        ):
            return {
                "file_id": file_id,
                "destino": str(alvo),
                "bytes": alvo.stat().st_size,
                "pulado": True,
            }
        if tamanho_meta is not None and tamanho_meta > max_bytes:
            raise GoogleError(
                f"download_recusado: {meta.get('name')} tem {tamanho_meta} B "
                f"(teto {max_bytes} B) — corpo em memória, arquivo grande demais"
            )
        raw = self.client.request_raw(
            "GET",
            f"{DRIVE_BASE}/files/{file_id}",
            params={"alt": "media"},
            accept="*/*",
        )
        if tamanho_meta is not None and len(raw) != tamanho_meta:
            raise GoogleError(
                f"download_incompleto: {meta.get('name')} esperado "
                f"{tamanho_meta} B, veio {len(raw)} B"
            )
        parcial = alvo.with_name(alvo.name + ".part")
        parcial.write_bytes(raw)
        os.replace(parcial, alvo)
        return {
            "file_id": file_id,
            "destino": str(alvo),
            "bytes": len(raw),
            "pulado": False,
        }

    # -- Escrita (lote 2, 2026-10-03 — escopo `drive`) --------------------

    def find_by_name(self, name: str) -> list[dict[str, Any]]:
        """Arquivos NÃO lixeira com nome EXATO (para resolver alvo falado)."""
        safe = (name or "").replace("\\", "\\\\").replace("'", "\\'")
        data = self.client.get(
            f"{DRIVE_BASE}/files",
            params={
                "q": f"name = '{safe}' and trashed = false",
                "fields": f"files({_FIELDS})",
                "pageSize": 10,
            },
        )
        return [self._summary(f) for f in (data.get("files") or [])]

    def create_file(
        self, name: str, content: str = "", *, mime_type: str = "text/plain"
    ) -> dict[str, Any]:
        """Cria arquivo de texto (upload multipart/related)."""
        boundary = f"od{uuid.uuid4().hex}"
        meta = json.dumps({"name": name}, ensure_ascii=False).encode("utf-8")
        body = (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
            .encode("utf-8")
            + meta
            + f"\r\n--{boundary}\r\nContent-Type: {mime_type}\r\n\r\n".encode("utf-8")
            + (content or "").encode("utf-8")
            + f"\r\n--{boundary}--\r\n".encode("utf-8")
        )
        data = self.client.request_body(
            "POST",
            f"{DRIVE_BASE}/files",
            body=body,
            content_type=f"multipart/related; boundary={boundary}",
            params={"uploadType": "multipart", "fields": _FIELDS},
        )
        return self._summary(data if isinstance(data, dict) else {})

    def update_content(self, file_id: str, content: str) -> dict[str, Any]:
        """Substitui o CONTEÚDO de um arquivo de texto (upload de mídia).

        Arquivos Nativos do Google (Docs/Sheets) não aceitam mídia direta —
        quem detecta é a action (resolve o nome e vê o mimeType) e responde
        honesto; aqui um erro do Google sobe como GoogleError.
        """
        data = self.client.request_body(
            "PUT",
            f"{DRIVE_BASE}/files/{file_id}",
            body=(content or "").encode("utf-8"),
            content_type="text/plain; charset=utf-8",
            params={"uploadType": "media"},
        )
        return {"file_id": file_id, **self._summary(data if isinstance(data, dict) else {})}

    def delete_file(self, file_id: str) -> dict[str, Any]:
        """Apaga o arquivo (para a lixeira/definitivo conforme a API)."""
        self.client.request("DELETE", f"{DRIVE_BASE}/files/{file_id}")
        return {"file_id": file_id, "deleted": True}

    @staticmethod
    def _summary(raw: dict[str, Any]) -> dict[str, Any]:
        owners = raw.get("owners") or []
        owner = ""
        if owners and isinstance(owners[0], dict):
            owner = str(owners[0].get("displayName") or "")
        return {
            "id": raw.get("id", ""),
            "name": raw.get("name", ""),
            "mime_type": raw.get("mimeType", ""),
            "modified_time": raw.get("modifiedTime", ""),
            "size": raw.get("size"),
            "web_view_link": raw.get("webViewLink", ""),
            "owner": owner,
        }
