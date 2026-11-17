"""Stub inicial — mede o --missing baseline de integrations/api/server.py."""

from integrations.api import server as _server  # noqa: F401


def test_importa() -> None:
    assert _server.API_NAME
