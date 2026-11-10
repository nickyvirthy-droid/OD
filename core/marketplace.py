"""
OMEGA DRAKON • CORE
Módulo: core/marketplace.py
Descrição: Plugin Marketplace (E1) — catálogo público de plugins,
           descoberta, instalação verificada (Ed25519), reviews,
           sandbox de execução. Camada pública sobre o PluginManager
           + Supply Depot (assinaturas Ed25519, import/export).

Baseado em:
  - plugins/manager.py (PluginManager — carregamento local)
  - tools/supply_depot.py (Ed25519, export/import, validação)
  - tools/auto_extension/engine.py (sandbox de execução)
Arquiteto: Omega Drakon
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urljoin

from core.logger import get_logger
from tools.supply_depot import (
    SupplyDepot,
    _CRYPTO_DISPONIVEL,
    validar_codigo,
    _carregar_fn,
)

log = get_logger("omega.core.marketplace")

# --- Constantes -------------------------------------------------------------

MARKETPLACE_CATALOGO = Path("data/marketplace_catalogo.json")
MARKETPLACE_PLUGINS_DIR = Path("data/marketplace_plugins")
MARKETPLACE_CACHE_DIR = Path("data/marketplace_cache")
MARKETPLACE_REVIEWS_DIR = Path("data/marketplace_reviews")

SCHEMA_MANIFEST = "od.marketplace.manifest.v1"
MAX_PLUGIN_SIZE = 2 * 1024 * 1024  # 2 MB
MAX_DESCRICAO = 2000
MAX_NOME = 64
SEMANA_SEGUNDOS = 7 * 24 * 3600

_NOME_RE = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)*$")


# --- Modelo de dados --------------------------------------------------------


@dataclass
class PluginManifest:
    """Manifesto de um plugin no marketplace (JSON assinado Ed25519)."""

    schema: str = SCHEMA_MANIFEST
    id: str = ""                    # ex.: "util.calculadora"
    nome: str = ""                  # nome exibido
    versao: str = "1.0.0"
    descricao: str = ""
    autor: str = ""
    categoria: str = "utilidades"   # utilidades, seguranca, saude, ia, etc.
    tags: list[str] = field(default_factory=list)
    # Código-fonte (inline no manifesto para verificação de assinatura)
    codigo: str = ""
    # Entrypoint
    funcao: str = ""
    # Dependências (actions/plugin IDs necessários)
    depende: list[str] = field(default_factory=list)
    # Permissão mínima exigida para instalar
    permission: str = ""
    # Metadados de build
    build_ts: float = 0.0
    build_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "id": self.id,
            "nome": self.nome,
            "versao": self.versao,
            "descricao": self.descricao,
            "autor": self.autor,
            "categoria": self.categoria,
            "tags": self.tags,
            "codigo": self.codigo,
            "funcao": self.funcao,
            "depende": self.depende,
            "permission": self.permission,
            "build_ts": self.build_ts,
            "build_sha256": self.build_sha256,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PluginManifest":
        m = cls()
        for k, v in d.items():
            if hasattr(m, k):
                setattr(m, k, v)
        return m

    def calcular_sha256(self) -> str:
        """SHA256 do código (para build_sha256)."""
        return hashlib.sha256(self.codigo.encode("utf-8")).hexdigest()


@dataclass
class PluginReview:
    """Avaliação de um plugin (1-5 estrelas + texto)."""

    plugin_id: str
    usuario: str                    # username ou "anon"
    estrelas: int                   # 1-5
    texto: str = ""
    ts: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "usuario": self.usuario,
            "estrelas": self.estrelas,
            "texto": self.texto,
            "ts": self.ts,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PluginReview":
        r = cls(plugin_id="", usuario="", estrelas=0)
        for k, v in d.items():
            if hasattr(r, k):
                setattr(r, k, v)
        return r


@dataclass
class PluginMarketplaceEntry:
    """Entrada instalada do marketplace (cache local)."""

    manifest: PluginManifest
    instalado_em: float = 0.0
    caminho_local: str = ""          # onde o código foi salvo
    assinatura_valida: bool = False
    chave_publica: str = ""          # Ed25519 pública que assinou


# --- Catálogo do Marketplace ------------------------------------------------


class MarketplaceCatalogo:
    """Catálogo público de plugins (manifestações assinadas).

    O catálogo é um JSON com lista de manifestos. Cada manifesto deve
    ter assinatura Ed25519 válida. O catálogo pode ser atualizado
    via pull de um registry remoto ou push local.
    """

    def __init__(
        self,
        catalogo_path: Path = MARKETPLACE_CATALOGO,
        plugins_dir: Path = MARKETPLACE_PLUGINS_DIR,
        cache_dir: Path = MARKETPLACE_CACHE_DIR,
        reviews_dir: Path = MARKETPLACE_REVIEWS_DIR,
        supply_depot: Optional[SupplyDepot] = None,
    ) -> None:
        self.catalogo_path = Path(catalogo_path)
        self.plugins_dir = Path(plugins_dir)
        self.cache_dir = Path(cache_dir)
        self.reviews_dir = Path(reviews_dir)
        self._supply_depot = supply_depot
        self._lock = threading.RLock()
        self._catalogo: dict[str, PluginManifest] = {}
        self._assinaturas: dict[str, tuple[str, str]] = {}  # id -> (assinatura, chave_publica)
        self._carregar()

    def _carregar(self) -> None:
        """Carrega catálogo do disco (valida assinaturas)."""
        for d in (self.plugins_dir, self.cache_dir, self.reviews_dir):
            d.mkdir(parents=True, exist_ok=True)
        try:
            bruto = json.loads(self.catalogo_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._catalogo = {}
            self._assinaturas = {}
            return
        itens = bruto.get("plugins", [])
        for item in itens:
            if not isinstance(item, dict):
                continue
            manifest_dict = {k: v for k, v in item.items() if k not in ("assinatura", "chave_publica")}
            manifest = PluginManifest.from_dict(manifest_dict)
            assinatura = str(item.get("assinatura") or "").strip()
            chave_publica = str(item.get("chave_publica") or "").strip()
            if manifest.id and self._validar_manifest(manifest, assinatura, chave_publica):
                self._catalogo[manifest.id] = manifest
                self._assinaturas[manifest.id] = (assinatura, chave_publica)
        log.info("Marketplace catálogo carregado", plugins=len(self._catalogo))

    def _validar_manifest(
        self, manifest: PluginManifest, assinatura: str, chave_publica: str
    ) -> bool:
        """Valida assinatura Ed25519 do manifesto."""
        if not assinatura or not chave_publica:
            log.warn("Manifest sem assinatura", id=manifest.id)
            return False
        # Reconstrói payload SEM campos de assinatura
        payload_dict = manifest.to_dict()
        payload = json.dumps(payload_dict, ensure_ascii=False,
                             sort_keys=True, separators=(",", ":")).encode("utf-8")
        try:
            import base64
            from cryptography.hazmat.primitives.asymmetric import ed25519
            assinatura_bytes = base64.urlsafe_b64decode(assinatura + "==")
            publica_bytes = base64.urlsafe_b64decode(chave_publica + "==")
            publica = ed25519.Ed25519PublicKey.from_public_bytes(publica_bytes)
            publica.verify(assinatura_bytes, payload)
            return True
        except Exception as exc:
            log.warn("Assinatura inválida", id=manifest.id, erro=str(exc)[:200])
            return False

    def gravar(self) -> None:
        """Grava catálogo no disco (atômico)."""
        self.catalogo_path.parent.mkdir(parents=True, exist_ok=True)
        itens = []
        for manifest in self._catalogo.values():
            item = manifest.to_dict()
            assinatura, chave_publica = self._assinaturas.get(manifest.id, ("", ""))
            item["assinatura"] = assinatura
            item["chave_publica"] = chave_publica
            itens.append(item)
        payload = {"schema": SCHEMA_MANIFEST, "atualizado_em": time.time(),
                   "plugins": itens}
        tmp = self.catalogo_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(self.catalogo_path)

    def adicionar(self, manifest: PluginManifest, assinatura: str,
                  chave_publica: str) -> dict[str, Any]:
        """Adiciona/atualiza plugin no catálogo (valida assinatura)."""
        if not _NOME_RE.match(manifest.id or ""):
            return {"ok": False, "motivo": "id_invalido"}
        if len(manifest.codigo) > MAX_PLUGIN_SIZE:
            return {"ok": False, "motivo": "codigo_grande"}
        # Valida sintaxe + allowlist
        ok, motivo = validar_codigo(manifest.codigo)
        if not ok:
            return {"ok": False, "motivo": f"codigo_invalido: {motivo}"}
        # Valida assinatura
        if not self._validar_manifest(manifest, assinatura, chave_publica):
            return {"ok": False, "motivo": "assinatura_invalida"}
        with self._lock:
            self._catalogo[manifest.id] = manifest
            self._assinaturas[manifest.id] = (assinatura, chave_publica)
            self.gravar()
        log.info("Marketplace plugin adicionado", id=manifest.id,
                 versao=manifest.versao)
        return {"ok": True, "id": manifest.id, "versao": manifest.versao}

    def remover(self, plugin_id: str) -> dict[str, Any]:
        with self._lock:
            if plugin_id not in self._catalogo:
                return {"ok": False, "motivo": "nao_encontrado"}
            del self._catalogo[plugin_id]
            self._assinaturas.pop(plugin_id, None)
            self.gravar()
        return {"ok": True, "removido": plugin_id}

    def obter(self, plugin_id: str) -> Optional[PluginManifest]:
        return self._catalogo.get(plugin_id)

    def listar(self, *, categoria: str = "", tag: str = "",
               query: str = "") -> list[dict[str, Any]]:
        """Lista plugins com filtros."""
        res = []
        for m in self._catalogo.values():
            if categoria and m.categoria != categoria:
                continue
            if tag and tag not in m.tags:
                continue
            if query:
                q = query.lower()
                if q not in m.id.lower() and q not in m.nome.lower() \
                        and q not in m.descricao.lower():
                    continue
            d = m.to_dict()
            d["assinatura_valida"] = True
            res.append(d)
        return sorted(res, key=lambda x: x["nome"])

    def categorias(self) -> list[str]:
        return sorted({m.categoria for m in self._catalogo.values()})

    def tags(self) -> list[str]:
        t = set()
        for m in self._catalogo.values():
            t.update(m.tags)
        return sorted(t)


# --- Reviews -----------------------------------------------------------------


class ReviewsStore:
    """Armazém de avaliações (reviews) por plugin."""

    def __init__(self, reviews_dir: Path = MARKETPLACE_REVIEWS_DIR) -> None:
        self.reviews_dir = Path(reviews_dir)
        self.reviews_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, plugin_id: str) -> Path:
        return self.reviews_dir / f"{plugin_id}.json"

    def adicionar(self, review: PluginReview) -> dict[str, Any]:
        if not 1 <= review.estrelas <= 5:
            return {"ok": False, "motivo": "estrelas_invalidas"}
        if len(review.texto) > 2000:
            return {"ok": False, "motivo": "texto_grande"}
        with self._lock:
            reviews = self._carregar(review.plugin_id)
            # Remove review anterior do mesmo usuário (se houver)
            reviews = [r for r in reviews if r.usuario != review.usuario]
            reviews.append(review)
            self._gravar(review.plugin_id, reviews)
        return {"ok": True}

    def listar(self, plugin_id: str) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self._carregar(plugin_id)]

    def media(self, plugin_id: str) -> dict[str, Any]:
        reviews = self._carregar(plugin_id)
        if not reviews:
            return {"media": 0.0, "total": 0, "distribuicao": {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}}
        dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        soma = 0
        for r in reviews:
            dist[r.estrelas] = dist.get(r.estrelas, 0) + 1
            soma += r.estrelas
        return {"media": round(soma / len(reviews), 1), "total": len(reviews),
                "distribuicao": dist}

    def _carregar(self, plugin_id: str) -> list[PluginReview]:
        try:
            dados = json.loads(self._path(plugin_id).read_text(encoding="utf-8"))
            return [PluginReview.from_dict(r) for r in dados if isinstance(r, dict)]
        except (OSError, ValueError):
            return []

    def _gravar(self, plugin_id: str, reviews: list[PluginReview]) -> None:
        self._path(plugin_id).write_text(
            json.dumps([r.to_dict() for r in reviews], ensure_ascii=False, indent=1),
            encoding="utf-8"
        )


# --- Instalador --------------------------------------------------------------


class MarketplaceInstalador:
    """Instala plugins do marketplace no ambiente local (PluginManager + Supply Depot)."""

    def __init__(
        self,
        catalogo: MarketplaceCatalogo,
        plugins_dir: Path = MARKETPLACE_PLUGINS_DIR,
        supply_depot: Optional[SupplyDepot] = None,
        plugin_manager: Any = None,  # PluginManager opcional
    ) -> None:
        self.catalogo = catalogo
        self.plugins_dir = Path(plugins_dir)
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        self._supply_depot = supply_depot
        self._plugin_manager = plugin_manager
        self._instalados: dict[str, PluginMarketplaceEntry] = {}
        self._lock = threading.RLock()
        self._carregar_instalados()

    def _carregar_instalados(self) -> None:
        idx_path = self.plugins_dir / "index.json"
        try:
            dados = json.loads(idx_path.read_text(encoding="utf-8"))
            for item in dados.get("instalados", []):
                m = PluginManifest.from_dict(item["manifest"])
                entry = PluginMarketplaceEntry(
                    manifest=m,
                    instalado_em=item.get("instalado_em", 0),
                    caminho_local=item.get("caminho_local", ""),
                    assinatura_valida=item.get("assinatura_valida", False),
                    chave_publica=item.get("chave_publica", ""),
                )
                self._instalados[m.id] = entry
        except (OSError, ValueError):
            pass

    def _gravar_instalados(self) -> None:
        idx_path = self.plugins_dir / "index.json"
        itens = []
        for entry in self._instalados.values():
            itens.append({
                "manifest": entry.manifest.to_dict(),
                "instalado_em": entry.instalado_em,
                "caminho_local": entry.caminho_local,
                "assinatura_valida": entry.assinatura_valida,
                "chave_publica": entry.chave_publica,
            })
        idx_path.write_text(
            json.dumps({"instalados": itens}, ensure_ascii=False, indent=1),
            encoding="utf-8"
        )

    def instalar(self, plugin_id: str, *, forcar: bool = False) -> dict[str, Any]:
        """Instala plugin do marketplace.

        1. Verifica assinatura do manifesto
        2. Valida código (sintaxe + allowlist)
        3. Se Supply Depot disponível: usa instalar() do depot (pré-voo, rollback, custom)
        4. Se PluginManager disponível: carrega no runtime
        5. Salva cópia local + índice
        """
        manifest = self.catalogo.obter(plugin_id)
        if not manifest:
            return {"ok": False, "motivo": "plugin_nao_encontrado_no_catalogo"}
        assinatura, chave_publica = self.catalogo._assinaturas.get(plugin_id, ("", ""))
        if not self.catalogo._validar_manifest(manifest, assinatura, chave_publica):
            return {"ok": False, "motivo": "assinatura_invalida"}

        if plugin_id in self._instalados and not forcar:
            return {"ok": False, "motivo": "ja_instalado", "id": plugin_id}

        # Valida código
        ok, motivo = validar_codigo(manifest.codigo)
        if not ok:
            return {"ok": False, "motivo": f"codigo_invalido: {motivo}"}
        if _carregar_fn(manifest.codigo, manifest.funcao) is None:
            return {"ok": False, "motivo": "funcao_nao_encontrada"}

        # Instala via Supply Depot se disponível (melhor: pré-voo, rollback, custom)
        if self._supply_depot is not None:
            r = self._supply_depot.instalar(
                nome=manifest.id,
                codigo=manifest.codigo,
                versao=manifest.versao,
                descricao=manifest.descricao,
                categoria=manifest.categoria,
                params={},  # o manifesto não tem params schema - usa vazio
                permission=manifest.permission or f"plugin.{manifest.id}",
                origem="marketplace",
                confirmar=False,
            )
            if not r.get("ok"):
                return {"ok": False, "motivo": f"depot_falhou: {r.get('motivo')}"}
        else:
            # Fallback: salva arquivo local
            destino = self.plugins_dir / f"{manifest.id}.py"
            destino.write_text(manifest.codigo, encoding="utf-8")

        # Se PluginManager disponível, carrega no runtime
        if self._plugin_manager is not None:
            try:
                self._plugin_manager.load_source(destino if self._supply_depot is None
                                                 else self._supply_depot.codigos_dir / f"{manifest.id}.py")
            except Exception as exc:
                log.warn("PluginManager load falhou", plugin=plugin_id, erro=str(exc))

        # Registra como instalado
        entry = PluginMarketplaceEntry(
            manifest=manifest,
            instalado_em=time.time(),
            caminho_local=str(destino) if self._supply_depot is None
            else str(self._supply_depot.codigos_dir / f"{manifest.id}.py"),
            assinatura_valida=True,
            chave_publica=chave_publica,
        )
        with self._lock:
            self._instalados[plugin_id] = entry
            self._gravar_instalados()
        log.info("Marketplace plugin instalado", id=plugin_id, versao=manifest.versao)
        return {"ok": True, "id": plugin_id, "versao": manifest.versao}

    def desinstalar(self, plugin_id: str) -> dict[str, Any]:
        with self._lock:
            entry = self._instalados.pop(plugin_id, None)
        if not entry:
            return {"ok": False, "motivo": "nao_instalado"}
        # Desinstala do Supply Depot se lá
        if self._supply_depot is not None:
            self._supply_depot.remover(plugin_id)
        # Remove arquivo local se houver
        try:
            Path(entry.caminho_local).unlink(missing_ok=True)
        except Exception:
            pass
        # Desinstala do PluginManager
        if self._plugin_manager is not None:
            try:
                self._plugin_manager.unload(plugin_id)
            except Exception:
                pass
        self._gravar_instalados()
        return {"ok": True, "desinstalado": plugin_id}

    def listar_instalados(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "id": e.manifest.id,
                    "nome": e.manifest.nome,
                    "versao": e.manifest.versao,
                    "categoria": e.manifest.categoria,
                    "instalado_em": e.instalado_em,
                    "assinatura_valida": e.assinatura_valida,
                }
                for e in self._instalados.values()
            ]

    def atualizar(self, plugin_id: str) -> dict[str, Any]:
        """Atualiza para versão mais nova do catálogo (se houver)."""
        return self.instalar(plugin_id, forcar=True)


# --- Marketplace Service (API) ----------------------------------------------


class MarketplaceService:
    """Serviço unificado do Marketplace (catálogo + reviews + instalador)."""

    def __init__(
        self,
        catalogo: Optional[MarketplaceCatalogo] = None,
        reviews: Optional[ReviewsStore] = None,
        instalador: Optional[MarketplaceInstalador] = None,
        supply_depot: Optional[SupplyDepot] = None,
        plugin_manager: Any = None,
    ) -> None:
        self.catalogo = catalogo or MarketplaceCatalogo(supply_depot=supply_depot)
        self.reviews = reviews or ReviewsStore()
        self.instalador = instalador or MarketplaceInstalador(
            catalogo=self.catalogo,
            supply_depot=supply_depot,
            plugin_manager=plugin_manager,
        )

    # Catálogo
    def buscar(self, **kwargs) -> list[dict[str, Any]]:
        return self.catalogo.listar(**kwargs)

    def obter(self, plugin_id: str) -> Optional[dict[str, Any]]:
        m = self.catalogo.obter(plugin_id)
        return m.to_dict() if m else None

    def categorias(self) -> list[str]:
        return self.catalogo.categorias()

    def tags(self) -> list[str]:
        return self.catalogo.tags()

    # Reviews
    def reviews_listar(self, plugin_id: str) -> list[dict[str, Any]]:
        return self.reviews.listar(plugin_id)

    def reviews_media(self, plugin_id: str) -> dict[str, Any]:
        return self.reviews.media(plugin_id)

    def reviews_adicionar(self, review: PluginReview) -> dict[str, Any]:
        return self.reviews.adicionar(review)

    # Instalação
    def instalar(self, plugin_id: str, forcar: bool = False) -> dict[str, Any]:
        return self.instalador.instalar(plugin_id, forcar=forcar)

    def desinstalar(self, plugin_id: str) -> dict[str, Any]:
        return self.instalador.desinstalar(plugin_id)

    def listar_instalados(self) -> list[dict[str, Any]]:
        return self.instalador.listar_instalados()

    def atualizar(self, plugin_id: str) -> dict[str, Any]:
        return self.instalador.atualizar(plugin_id)

    # Admin (assinatura)
    def publicar(self, manifest: PluginManifest, assinatura: str,
                 chave_publica: str) -> dict[str, Any]:
        return self.catalogo.adicionar(manifest, assinatura, chave_publica)

    def remover_publicacao(self, plugin_id: str) -> dict[str, Any]:
        return self.catalogo.remover(plugin_id)

    # Stats
    def stats(self) -> dict[str, Any]:
        return {
            "catalogo": len(self.catalogo._catalogo),
            "instalados": len(self.instalador._instalados),
            "categorias": len(self.catalogo.categorias()),
            "tags": len(self.catalogo.tags()),
        }