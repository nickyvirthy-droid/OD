"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/google/calendar.py
Descrição: CalendarService — Google Agenda: leitura (calendários e
           próximos eventos) + ESCRITA (criar/apagar compromissos) do lote 2
           (escopo calendar.events, 2026-10-03).

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from integrations.google.client import CALENDAR_BASE, GoogleClient

__signature__ = "OD // CORE"

_EVENT_FIELDS = "items(id,summary,start,end,location,htmlLink,status,attendees(email))"


def _iso_z(when: datetime) -> str:
    return when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# Número por EXTENSO → dígito ('para as sete horas' → 'para as 7 horas';
# IDs 769-780 de 08/10). Vocabulário MESMO do core/intents.py
# ::_NUM_POR_EXTENSO — lados independentes, cada um com seu teste.
_EXTENSO_RE = re.compile(
    r"\b(vinte\s+e\s+tr[êe]s|vinte\s+e\s+duas?|vinte\s+e\s+uma|vinte|"
    r"dezenove|dezoito|dezessete|dezesseis|quinze|catorze|treze|doze|"
    r"onze|dez|nove|oito|sete|seis|cinco|quatro|tr[êe]s|duas|dois|uma|um)\b",
    re.IGNORECASE,
)
_EXTENSO_NUM = {
    "vinte e três": 23, "vinte e tres": 23, "vinte e duas": 22,
    "vinte e dois": 22, "vinte e uma": 21, "vinte e um": 21,
    "vinte": 20, "dezenove": 19, "dezoito": 18, "dezessete": 17,
    "dezesseis": 16, "quinze": 15, "catorze": 14, "treze": 13,
    "doze": 12, "onze": 11, "dez": 10, "nove": 9, "oito": 8,
    "sete": 7, "seis": 6, "cinco": 5, "quatro": 4, "três": 3,
    "tres": 3, "duas": 2, "dois": 2, "uma": 1, "um": 1,
}


def _extenso_em_digito(text: str) -> str:
    """'para as sete horas' → 'para as 7 horas' (só o QUANDO passa por aqui)."""
    return _EXTENSO_RE.sub(
        lambda m: str(_EXTENSO_NUM[re.sub(r"\s+", " ", m.group(0).lower())]),
        text,
    )


def parse_when(text: str, *, now: Optional[datetime] = None) -> Optional[dict[str, str]]:
    """'hoje'/'amanhã' [às HHh|às HH:MM] → start/end do evento.

    Também aceita a HORA SOLTA do dono, sem dia ('para as 6 horas',
    'às 15h', '14:30'): o dia assume HOJE e vira AMANHÃ quando a hora já
    passou — a frase sem 'hoje' NUNCA vira evento de dia inteiro (prova
    real de 08/10, IDs 747-752).

    Determinístico e conservador: fora dia/hora devolve None — a action
    responde com dica em vez de inventar data.
    """
    low = _extenso_em_digito((text or "").lower())
    base = now or datetime.now().astimezone()
    day = None
    if re.search(r"\bhoje\b", low):
        day = base.date()
    elif re.search(r"\bamanh[ãa]\b", low):
        day = base.date() + timedelta(days=1)
    if day is None:
        # Sem âncora de dia: só hora EXPLÍCITA vale ('às 6' / 'às 15h' /
        # '14:30' com DOIS-PONTOS). Número solto sem preposição ('daqui 2
        # horas'), data ('08.10') e versão ('1.19.4') não são um quando —
        # a pendência do create não pode ser sequestrada nem o título
        # vira horário (pego pela prova viva do deploy de 08/10).
        hora = re.search(
            r"[àa]s\s+(\d{1,2})(?:[:hH](\d{2}))?(?:\s*(?:horas?|h))?", low
        ) or re.search(r"\b(\d{1,2}):(\d{2})\b", low)
    else:
        hora = re.search(r"[àa]s\s+(\d{1,2})(?:[:hH](\d{2}))?", low)
        if not hora:
            # '5 horas de hoje' sem a preposição 'às' — o dono escreve dos dois
            # jeitos; sem este ramo o evento voltava a nascer DIA INTEIRO.
            hora = re.search(r"\b(\d{1,2})(?:[:hH.](\d{2}))?\s*(?:horas?|h)\b", low)
    if hora:
        hour, minute = int(hora.group(1)), int(hora.group(2) or 0)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        if day is None:
            start = datetime(base.year, base.month, base.day, hour, minute,
                             tzinfo=base.tzinfo)
            if start <= base:
                # hora já passou hoje → o dono quis o PRÓXIMO dia útil
                # dele (amarra o 'para as 6 horas' dito às 10h)
                start = start + timedelta(days=1)
        else:
            start = datetime(day.year, day.month, day.day, hour, minute,
                             tzinfo=base.tzinfo)
        end = start + timedelta(hours=1)
        return {"start": _iso_z(start), "end": _iso_z(end)}
    if day is None:
        return None
    return {
        "start": day.isoformat(),
        "end": (day + timedelta(days=1)).isoformat(),
    }


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

    def find_events_by_title(
        self, title: str, *, days: int = 60, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Eventos futuros com título EXATO (case-insensitive) — resolve o
        alvo falado do apagar sem arriscar apagar o errado."""
        data = self.list_events(days=days, limit=limit)
        wanted = (title or "").strip().casefold()
        return [
            e for e in data.get("events", [])
            if str(e.get("summary") or "").strip().casefold() == wanted
        ]

    def create_event(
        self,
        *,
        summary: str,
        when: dict[str, str],
        calendar_id: str = "primary",
    ) -> dict[str, Any]:
        """Cria UM compromisso (dia inteiro ou com hora)."""
        body: dict[str, Any] = {"summary": summary}
        if "T" in when.get("start", ""):
            body["start"] = {"dateTime": when["start"]}
            body["end"] = {"dateTime": when.get("end") or when["start"]}
        else:
            body["start"] = {"date": when["start"]}
            body["end"] = {"date": when.get("end") or when["start"]}
        data = self.client.request(
            "POST",
            f"{CALENDAR_BASE}/calendars/{calendar_id}/events",
            json_body=body,
            params={"fields": "id,summary,start,end,htmlLink"},
        )
        return self._summary(data if isinstance(data, dict) else {})

    def delete_event(
        self, event_id: str, *, calendar_id: str = "primary"
    ) -> dict[str, Any]:
        """Apaga UM compromisso pelo id."""
        self.client.request(
            "DELETE", f"{CALENDAR_BASE}/calendars/{calendar_id}/events/{event_id}"
        )
        return {"event_id": event_id, "deleted": True}

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
