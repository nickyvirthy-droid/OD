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
