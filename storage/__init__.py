"""
OMEGA DRAKON • STORAGE
Tecnologia que respira.
Pacote: storage/
Descrição: Camada de persistência (Fase 7, item 7.5) — Database Layer em
           SQLite stdlib: pool de conexões, transações e repositórios.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Módulos:
  - database.py → Database (pool + execução + repositórios CRUD)
"""

from storage.database import (
    ConnectionPool,
    Database,
    DatabaseError,
    DatabaseMetrics,
    Repository,
)

__signature__ = "OD // CORE"
__all__ = [
    "Database",
    "ConnectionPool",
    "Repository",
    "DatabaseError",
    "DatabaseMetrics",
]