"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/google/gmail.py
Descrição: GmailService — Gmail: leitura (listar/buscar mensagens, ler uma
           mensagem e listar rótulos) + ESCRITA (enviar/para lixeira) do
           lote 2 (escopos gmail.modify + gmail.send, 2026-10-03).

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import base64
from typing import Any, Optional

from integrations.google.client import GMAIL_BASE, GoogleClient

__signature__ = "OD // CORE"

_MAX_BODY_CHARS = 20_000


def _header(headers: list[dict[str, Any]], name: str) -> str:
    wanted = name.lower()
    for h in headers:
        if str(h.get("name", "")).lower() == wanted:
            return str(h.get("value", ""))
    return ""


def _decode_body(payload: dict[str, Any]) -> str:
    """Extrai o texto de um payload do Gmail (text/plain de preferência)."""
    mime = str(payload.get("mimeType", ""))
    body = payload.get("body") or {}
    data = body.get("data")
    parts = payload.get("parts") or []
    if mime == "text/plain" and data:
        try:
            return base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="replace")
        except (ValueError, TypeError):
            return ""
    for part in parts:
        if isinstance(part, dict):
            text = _decode_body(part)
            if text:
                return text
    if data and mime.startswith("text/"):
        try:
            return base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="replace")
        except (ValueError, TypeError):
            return ""
    return ""


class GmailService:
    """Operações de leitura do Gmail sobre um GoogleClient."""

    def __init__(self, client: GoogleClient) -> None:
        self.client = client

    def list_messages(
        self, *, query: str = "", limit: int = 10
    ) -> dict[str, Any]:
        """Lista mensagens (com resumo de From/Subject/Date via metadata)."""
        page = max(1, min(int(limit or 10), 50))
        params: dict[str, Any] = {"maxResults": page}
        if query:
            params["q"] = query
        data = self.client.get(f"{GMAIL_BASE}/users/me/messages", params=params)
        ids = data.get("messages", []) if isinstance(data, dict) else []
        messages: list[dict[str, Any]] = []
        for entry in ids[:page]:
            mid = entry.get("id") if isinstance(entry, dict) else None
            if not mid:
                continue
            try:
                raw = self.client.get(
                    f"{GMAIL_BASE}/users/me/messages/{mid}",
                    params={
                        "format": "metadata",
                        "metadataHeaders": ["From", "Subject", "Date"],
                    },
                )
                messages.append(self._summary(raw))
            except Exception:  # noqa: BLE001 — uma mensagem ruim não derruba a lista
                messages.append(
                    {"id": mid, "from": "", "subject": "", "date": "", "snippet": ""}
                )
        return {
            "messages": messages,
            "count": len(messages),
            "estimate": data.get("resultSizeEstimate") if isinstance(data, dict) else None,
        }

    def get_message(self, message_id: str) -> dict[str, Any]:
        """Lê uma mensagem (cabeçalhos + corpo textual)."""
        raw = self.client.get(
            f"{GMAIL_BASE}/users/me/messages/{message_id}", params={"format": "full"}
        )
        payload = raw.get("payload") or {} if isinstance(raw, dict) else {}
        headers = payload.get("headers") or []
        body = _decode_body(payload)
        if len(body) > _MAX_BODY_CHARS:
            body = body[:_MAX_BODY_CHARS] + "…"
        summary = self._summary(raw)
        summary.update({"body": body, "label_ids": raw.get("labelIds", []) if isinstance(raw, dict) else []})
        return summary

    # -- Escrita (lote 2, 2026-10-03) --------------------------------------

    def send_message(self, *, to: str, subject: str, body: str) -> dict[str, Any]:
        """Envia UM e-mail (MIME RFC5322 via EmailMessage, raw base64url)."""
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body or "")
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii").rstrip("=")
        data = self.client.request(
            "POST",
            f"{GMAIL_BASE}/users/me/messages/send",
            json_body={"raw": raw},
        )
        return {
            "id": data.get("id", "") if isinstance(data, dict) else "",
            "thread_id": data.get("threadId", "") if isinstance(data, dict) else "",
            "to": to,
            "subject": subject,
        }

    def trash_message(self, message_id: str) -> dict[str, Any]:
        """Move UMA mensagem para a lixeira (gmail.modify)."""
        data = self.client.request(
            "POST", f"{GMAIL_BASE}/users/me/messages/{message_id}/trash"
        )
        labels = data.get("labelIds", []) if isinstance(data, dict) else []
        return {
            "id": data.get("id", message_id) if isinstance(data, dict) else message_id,
            "trashed": "TRASH" in labels,
        }

    def list_labels(self) -> dict[str, Any]:
        data = self.client.get(f"{GMAIL_BASE}/users/me/labels")
        labels = data.get("labels", []) if isinstance(data, dict) else []
        return {
            "labels": [
                {
                    "id": l.get("id", ""),
                    "name": l.get("name", ""),
                    "type": l.get("type", ""),
                }
                for l in labels
            ],
            "count": len(labels),
        }

    @staticmethod
    def _summary(raw: dict[str, Any]) -> dict[str, Any]:
        payload = (raw.get("payload") or {}) if isinstance(raw, dict) else {}
        headers = payload.get("headers") or []
        return {
            "id": raw.get("id", "") if isinstance(raw, dict) else "",
            "thread_id": raw.get("threadId", "") if isinstance(raw, dict) else "",
            "from": _header(headers, "From"),
            "subject": _header(headers, "Subject"),
            "date": _header(headers, "Date"),
            "snippet": raw.get("snippet", "") if isinstance(raw, dict) else "",
        }
