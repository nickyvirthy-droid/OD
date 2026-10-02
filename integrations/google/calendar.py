"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/google/calendar.py
Descrição: CalendarService — leitura da Google Agenda (calendários e
           próximos eventos). SOMENTE LEITURA (calendar.readonly); criar/
           apagar compromissos ficam para o 2º lote.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from integrations.google.client import CALENDAR_BASE, GoogleClient

__signature__ = "OD // CORE"

_EVENT_FIELDS = "items(id,summary,start,end,location,htmlLink,status,attendees(email))"


def _iso_z(when: datetime) -> str:
    return when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class CalendarService:
    """Operações de leitura da Agenda sobre um GoogleClient."""

    def __init__(self, client: GoogleClient) -> None:
        self.client = client

    def list_calendars(self) -> dict[str, Any]:
        data = self.client.get(
            f"{CALENDAR_BASE}/users/me/calendarList",
            params={"fields": "items(id,summary,primary,timeZone)"},
        )
        items = data.get("items", []) if isinstance(data, dict) else []
        return {
            "calendars": [
                {
                    "id": c.get("id", ""),
                    "summary": c.get("summary", ""),
                    "primary": bool(c.get("primary")),
                    "time_zone": c.get("timeZone", ""),
                }
                for c in items
            ],
            "count": len(items),
        }

    def list_events(
        self,
        *,
        calendar_id: str = "primary",
        days: int = 7,
        limit: int = 10,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Próximos eventos no intervalo [agora, agora+days]."""
        base = now or datetime.now(timezone.utc)
        window_days = max(1, min(int(days or 7), 60))
        page = max(1, min(int(limit or 10), 50))
        params = {
            "timeMin": _iso_z(base),
            "timeMax": _iso_z(base + timedelta(days=window_days)),
            "maxResults": page,
            "singleEvents": "true",
            "orderBy": "startTime",
            "fields": _EVENT_FIELDS,
        }
        data = self.client.get(
            f"{CALENDAR_BASE}/calendars/{calendar_id}/events", params=params
        )
        items = data.get("items", []) if isinstance(data, dict) else []
        return {
            "events": [self._summary(e) for e in items],
            "count": len(items),
            "days": window_days,
        }

    @staticmethod
    def _summary(raw: dict[str, Any]) -> dict[str, Any]:
        start = raw.get("start") or {}
        end = raw.get("end") or {}
        attendees = raw.get("attendees") or []
        return {
            "id": raw.get("id", ""),
            "summary": raw.get("summary", "(sem título)"),
            "start": start.get("dateTime") or start.get("date") or "",
            "end": end.get("dateTime") or end.get("date") or "",
            "all_day": "date" in start and "dateTime" not in start,
            "location": raw.get("location", ""),
            "link": raw.get("htmlLink", ""),
            "attendees": [a.get("email", "") for a in attendees if isinstance(a, dict)],
        }
