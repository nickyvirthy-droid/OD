"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/google/drive.py
Descrição: DriveService — leitura do Google Drive (listar/buscar arquivos,
           metadados e conteúdo de texto). SOMENTE LEITURA (escopo
           drive.readonly); criar/editar/apagar ficam para o 2º lote.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

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
