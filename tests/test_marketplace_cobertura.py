"""OMEGA DRAKON • TESTES
Módulo: tests/test_marketplace_cobertura.py
Descrição: fechamento da dívida de cobertura de core/marketplace.py
           (arquivo novo desde o gate verde de 02/11) — paralelo aos
           testes de rota em tests/test_api.py, que NÃO é tocado.
           Cobre o que nunca rodou: roundtrip do manifesto/review,
           catálogo assinado Ed25519 (carregar, gravar, filtros),
           armazém de reviews (validação, substituição, média), instalador
           (fallback local, Supply Depot real, PluginManager com e sem
           falha, desinstalação) e as delegações do MarketplaceService.
           Rede bloqueada em todos os testes (fixture autouse); escrita
           sempre em tmp_path; nenhum comando de sistema.
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from core.marketplace import (
    MAX_PLUGIN_SIZE,
    SCHEMA_MANIFEST,
    MarketplaceCatalogo,
    MarketplaceInstalador,
    MarketplaceService,
    PluginManifest,
    PluginMarketplaceEntry,
    PluginReview,
    ReviewsStore,
)
from tools.registry import ActionRegistry
from tools.supply_depot import SupplyDepot

# --- Códigos válidos (mesmo gate do AutoExtension: sem import proibido) -----

CODE_DEMO = "def demo(**params):\n    return {'ok': True, 'result': 'demo'}\n"
CODE_IMPORT_PROIBIDO = "import pathlib\n\ndef demo(**params):\n    return {}\n"
CODE_SINTAXE_QUEBRADA = "def demo(:"
CODE_FUNCAO_OUTRA = "def outro(**params):\n    return {'ok': True}\n"


# --- Fixtures e helpers ------------------------------------------------------


@pytest.fixture(autouse=True)
def rede_bloqueada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proíbe qualquer chamada de rede durante os testes do marketplace."""

    def _proibido(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("rede bloqueada em teste de marketplace")

    monkeypatch.setattr("urllib.request.urlopen", _proibido)
    monkeypatch.setattr("urllib.request.build_opener", _proibido)


def _dirs(tmp_path: Path) -> dict[str, Path]:
    """Caminhos do marketplace, todos dentro de tmp_path."""
    return {
        "catalogo_path": tmp_path / "marketplace_catalogo.json",
        "plugins_dir": tmp_path / "marketplace_plugins",
        "cache_dir": tmp_path / "marketplace_cache",
        "reviews_dir": tmp_path / "marketplace_reviews",
    }


def _catalogo(tmp_path: Path, **extras: Any) -> MarketplaceCatalogo:
    """Catálogo novo apontando só para tmp_path."""
    return MarketplaceCatalogo(**_dirs(tmp_path), **extras)


def _manifest(**campos: Any) -> PluginManifest:
    """Manifesto padrão (id assinável pelo _NOME_RE) sobrescrevível."""
    base: dict[str, Any] = {
        "id": "util.demo",
        "nome": "Demo",
        "versao": "1.0.0",
        "descricao": "Plugin demo de utilidades",
        "autor": "alex",
        "categoria": "utilidades",
        "tags": ["demo", "util"],
        "codigo": CODE_DEMO,
        "funcao": "demo",
        "depende": [],
        "permission": "plugin.util.demo",
        "build_ts": 1.0,
        "build_sha256": "",
    }
    base.update(campos)
    return PluginManifest(**base)


def _par_chaves() -> dict[str, str]:
    """Par Ed25519 real (cryptography instalado no venv)."""
    return SupplyDepot.gerar_par_chaves_ed25519()


def _assinar(manifest: PluginManifest, privada: str) -> tuple[str, str]:
    """Assina o payload canônico exatamente como _validar_manifest lê.

    Mesma primitiva do SupplyDepot (Ed25519 + base64url sem padding),
    só que aplicada direto ao dict do manifesto.
    """
    privada_bytes = base64.urlsafe_b64decode(privada + "==")
    chave = ed25519.Ed25519PrivateKey.from_private_bytes(privada_bytes)
    payload = json.dumps(manifest.to_dict(), ensure_ascii=False,
                         sort_keys=True, separators=(",", ":")).encode("utf-8")
    assinatura = base64.urlsafe_b64encode(chave.sign(payload)).decode() \
        .rstrip("=")
    publica = chave.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    chave_publica = base64.urlsafe_b64encode(publica).decode().rstrip("=")
    return assinatura, chave_publica


def _publicar(cat: MarketplaceCatalogo, manifest: PluginManifest,
              privada: str) -> tuple[str, str]:
    """Assina e adiciona ao catálogo; devolve (assinatura, chave_publica)."""
    assinatura, chave = _assinar(manifest, privada)
    res = cat.adicionar(manifest, assinatura, chave)
    assert res["ok"], res
    return assinatura, chave


def _item_assinado(manifest: PluginManifest, privada: str) -> dict[str, Any]:
    """Item de catálogo em disco: manifesto + assinatura + chave pública."""
    assinatura, chave = _assinar(manifest, privada)
    item = manifest.to_dict()
    item["assinatura"] = assinatura
    item["chave_publica"] = chave
    return item


def _escreve_catalogo(caminho: Path, itens: list[Any]) -> None:
    """Grava um catálogo em disco com os itens crus (assinados ou não)."""
    caminho.write_text(
        json.dumps({"schema": SCHEMA_MANIFEST, "plugins": itens},
                   ensure_ascii=False),
        encoding="utf-8",
    )


def _depot(tmp_path: Path) -> tuple[SupplyDepot, ActionRegistry]:
    """Supply Depot real em tmp (relógio fixo) — padrão do teste base."""
    reg = ActionRegistry()
    depot = SupplyDepot(
        registry=reg,
        catalogo_path=tmp_path / "depot_catalogo.json",
        codigos_dir=tmp_path / "depot_codigos",
        backup_dir=tmp_path / "depot_backup",
        raiz=tmp_path,
        clock=lambda: 1_700_000_000.0,
    )
    return depot, reg


class _GerenciadorFalso:
    """PluginManager dublê: registra chamadas e pode falhar sob demanda."""

    def __init__(self, *, falha_load: bool = False,
                 falha_unload: bool = False) -> None:
        self.carregados: list[str] = []
        self.descarregados: list[str] = []
        self.falha_load = falha_load
        self.falha_unload = falha_unload

    def load_source(self, caminho: Any) -> None:
        if self.falha_load:
            raise RuntimeError("load_source quebrou")
        self.carregados.append(str(caminho))

    def unload(self, plugin_id: str) -> None:
        if self.falha_unload:
            raise RuntimeError("unload quebrou")
        self.descarregados.append(plugin_id)


class _DepotRecusador:
    """Supply Depot dublê que sempre recusa (caminho depot_falhou)."""

    def __init__(self, tmp_path: Path, motivo: str = "recusado_pelo_depot") -> None:
        self.codigos_dir = tmp_path / "depot_recusador"
        self.motivo = motivo
        self.chamadas: list[dict[str, Any]] = []

    def instalar(self, **campos: Any) -> dict[str, Any]:
        self.chamadas.append(campos)
        return {"ok": False, "motivo": self.motivo}

    def remover(self, id_ferramenta: str) -> dict[str, Any]:
        return {"ok": True, "removido": id_ferramenta}


# ===========================================================================
# 1. Modelo de dados — manifesto, review, entrada instalada
# ===========================================================================


class TestModelos:
    def test_manifesto_roundtrip_ignora_chave_desconhecida(self) -> None:
        """to_dict/from_dict preservam os campos e ignoram chaves alheias."""
        m = _manifest(build_sha256="abc")
        d = m.to_dict()
        assert d["id"] == "util.demo"
        assert d["codigo"] == CODE_DEMO
        assert set(d) == {
            "schema", "id", "nome", "versao", "descricao", "autor",
            "categoria", "tags", "codigo", "funcao", "depende",
            "permission", "build_ts", "build_sha256",
        }
        d["chave_extranea"] = "nao_deve_entrar"
        restaurado = PluginManifest.from_dict(d)
        assert restaurado.id == "util.demo"
        assert restaurado.build_sha256 == "abc"
        assert not hasattr(restaurado, "chave_extranea")

    def test_manifesto_calcula_sha256_do_codigo(self) -> None:
        m = _manifest()
        assert m.calcular_sha256() == hashlib.sha256(
            CODE_DEMO.encode("utf-8")).hexdigest()

    def test_review_roundtrip_com_padroes(self) -> None:
        r = PluginReview(plugin_id="util.demo", usuario="ana", estrelas=5,
                         texto="ótimo", ts=10.0)
        d = r.to_dict()
        assert d == {"plugin_id": "util.demo", "usuario": "ana",
                     "estrelas": 5, "texto": "ótimo", "ts": 10.0}
        d["inexistente"] = 1
        volta = PluginReview.from_dict(d)
        assert volta.usuario == "ana"
        assert not hasattr(volta, "inexistente")
        # from_dict de dicionário parcial usa os defaults do dataclass
        parcial = PluginReview.from_dict({"plugin_id": "x.y", "estrelas": 3})
        assert parcial.usuario == ""
        assert parcial.ts == 0.0

    def test_entrada_instalada_tem_defaults(self) -> None:
        entry = PluginMarketplaceEntry(manifest=_manifest())
        assert entry.instalado_em == 0.0
        assert entry.caminho_local == ""
        assert entry.assinatura_valida is False
        assert entry.chave_publica == ""


# ===========================================================================
# 2. MarketplaceCatalogo — carregamento e validação de assinatura
# ===========================================================================


class TestCarregamentoCatalogo:
    def test_sem_arquivo_inicia_vazio_e_cria_diretorios(
        self, tmp_path: Path
    ) -> None:
        cat = _catalogo(tmp_path)
        assert cat._catalogo == {}
        assert cat._assinaturas == {}
        dirs = _dirs(tmp_path)
        assert dirs["plugins_dir"].is_dir()
        assert dirs["cache_dir"].is_dir()
        assert dirs["reviews_dir"].is_dir()

    def test_json_invalido_vira_catalogo_vazio(self, tmp_path: Path) -> None:
        dirs = _dirs(tmp_path)
        dirs["catalogo_path"].write_text("{isso nao é json", encoding="utf-8")
        cat = _catalogo(tmp_path)
        assert cat._catalogo == {}
        assert cat.listar() == []

    def test_catalogo_carrega_apenas_itens_validos(self, tmp_path: Path) -> None:
        """Só entra no catálogo manifesto com id e assinatura Ed25519 válida."""
        chaves = _par_chaves()
        m1 = _manifest(id="util.alpha", nome="Alpha")
        m2 = _manifest(id="seg.beta", nome="Beta", categoria="seguranca")
        m_ruim = _manifest(id="util.ruim", nome="Ruim")
        ass_ruima, chave_ruima = _assinar(
            _manifest(id="util.outro", nome="Outro"), chaves["privada"])
        itens: list[Any] = [
            _item_assinado(m1, chaves["privada"]),
            _item_assinado(m2, chaves["privada"]),
            # assinatura de OUTRO payload → não confere
            {**m_ruim.to_dict(), "assinatura": ass_ruima,
             "chave_publica": chave_ruima},
            # sem assinatura/chave
            _manifest(id="util.sem_ass", nome="SemAss").to_dict(),
            # sem id → ignorado
            {**_manifest(id="", nome="SemId").to_dict(),
             "assinatura": "x", "chave_publica": "y"},
            # item que nem é objeto → ignorado
            "nao_sou_um_dict",
            42,
        ]
        _escreve_catalogo(_dirs(tmp_path)["catalogo_path"], itens)

        cat = _catalogo(tmp_path)
        assert sorted(cat._catalogo) == ["seg.beta", "util.alpha"]
        assert set(cat._assinaturas) == {"seg.beta", "util.alpha"}
        assert cat.obter("util.alpha").nome == "Alpha"
        assert cat.obter("util.nada") is None

    def test_manifest_sem_assinatura_e_chave_rejeitado(
        self, tmp_path: Path
    ) -> None:
        cat = _catalogo(tmp_path)
        m = _manifest()
        assert cat._validar_manifest(m, "", "chave_qualquer") is False
        assert cat._validar_manifest(m, "assinatura_qualquer", "") is False

    def test_assinatura_com_base64_invalido_rejeitada(
        self, tmp_path: Path
    ) -> None:
        cat = _catalogo(tmp_path)
        assert cat._validar_manifest(_manifest(), "!!!nao_base64!!!",
                                     "tambem_ruim") is False

    def test_assinatura_de_outro_conteudo_rejeitada(
        self, tmp_path: Path
    ) -> None:
        chaves = _par_chaves()
        cat = _catalogo(tmp_path)
        ass_de_outro, chave = _assinar(
            _manifest(id="util.outra", nome="Outra"), chaves["privada"])
        assert cat._validar_manifest(_manifest(), ass_de_outro, chave) is False
        # e a mesma assinatura sobre o MESMO payload é aceita
        certa, chave_certa = _assinar(_manifest(), chaves["privada"])
        assert cat._validar_manifest(_manifest(), certa, chave_certa) is True


# ===========================================================================
# 3. MarketplaceCatalogo — adicionar/remover/gravar
# ===========================================================================


class TestAdicionarRemover:
    @pytest.mark.parametrize("id_ruim", [
        "UPPER.Case", "a..b", "meu plugin", "", "util.com-espaço",
    ])
    def test_adicionar_rejeita_id_invalido(self, tmp_path: Path,
                                           id_ruim: str) -> None:
        cat = _catalogo(tmp_path)
        chaves = _par_chaves()
        m = _manifest(id=id_ruim)
        ass, chave = _assinar(m, chaves["privada"])
        res = cat.adicionar(m, ass, chave)
        assert res == {"ok": False, "motivo": "id_invalido"}
        assert cat._catalogo == {}

    def test_adicionar_rejeita_codigo_grande(self, tmp_path: Path) -> None:
        cat = _catalogo(tmp_path)
        chaves = _par_chaves()
        m = _manifest(codigo="x" * (MAX_PLUGIN_SIZE + 1))
        ass, chave = _assinar(m, chaves["privada"])
        res = cat.adicionar(m, ass, chave)
        assert res == {"ok": False, "motivo": "codigo_grande"}

    @pytest.mark.parametrize("codigo,trecho", [
        (CODE_IMPORT_PROIBIDO, "import:pathlib"),
        (CODE_SINTAXE_QUEBRADA, "syntax:"),
    ])
    def test_adicionar_rejeita_codigo_invalido(self, tmp_path: Path,
                                               codigo: str, trecho: str) -> None:
        cat = _catalogo(tmp_path)
        chaves = _par_chaves()
        m = _manifest(codigo=codigo)
        ass, chave = _assinar(m, chaves["privada"])
        res = cat.adicionar(m, ass, chave)
        assert res["ok"] is False
        assert res["motivo"].startswith("codigo_invalido:")
        assert trecho in res["motivo"]

    def test_adicionar_rejeita_assinatura_invalida(self, tmp_path: Path) -> None:
        cat = _catalogo(tmp_path)
        res = cat.adicionar(_manifest(), "assinatura_falsa", "chave_falsa")
        assert res == {"ok": False, "motivo": "assinatura_invalida"}
        assert cat._catalogo == {}

    def test_adicionar_grava_e_recarrega_do_disco(self, tmp_path: Path) -> None:
        """Roundtrip: adicionar grava (atómico) e novo catálogo relê válido."""
        chaves = _par_chaves()
        cat = _catalogo(tmp_path)
        m = _manifest()
        _publicar(cat, m, chaves["privada"])

        caminho = _dirs(tmp_path)["catalogo_path"]
        assert caminho.is_file()
        assert not caminho.with_suffix(".tmp").exists()  # gravação atômica
        bruto = json.loads(caminho.read_text(encoding="utf-8"))
        assert bruto["schema"] == SCHEMA_MANIFEST
        assert bruto["plugins"][0]["assinatura"]
        assert bruto["plugins"][0]["chave_publica"]

        recarregado = _catalogo(tmp_path)
        assert "util.demo" in recarregado._catalogo
        assert recarregado.obter("util.demo").codigo == CODE_DEMO
        assert recarregado._assinaturas["util.demo"][1] == chaves["publica"]

    def test_remover_do_catalogo_e_persiste(self, tmp_path: Path) -> None:
        chaves = _par_chaves()
        cat = _catalogo(tmp_path)
        _publicar(cat, _manifest(), chaves["privada"])

        res = cat.remover("util.demo")
        assert res == {"ok": True, "removido": "util.demo"}
        assert cat.obter("util.demo") is None
        assert cat._assinaturas == {}
        assert _catalogo(tmp_path).obter("util.demo") is None

        assert cat.remover("util.nada") == {"ok": False,
                                            "motivo": "nao_encontrado"}


# ===========================================================================
# 4. MarketplaceCatalogo — filtros, categorias e tags
# ===========================================================================


def _catalogo_com_tres(tmp_path: Path) -> MarketplaceCatalogo:
    chaves = _par_chaves()
    cat = _catalogo(tmp_path)
    _publicar(cat, _manifest(id="util.ave", nome="Ave",
                             descricao="voa alto",
                             tags=["util", "ave"]), chaves["privada"])
    _publicar(cat, _manifest(id="seg.gato", nome="Gato",
                             categoria="seguranca", descricao="vigia a casa",
                             tags=["util", "gato"]), chaves["privada"])
    _publicar(cat, _manifest(id="util.zebra", nome="Zebra",
                             descricao="listras na savana",
                             tags=["zebra"]), chaves["privada"])
    return cat


class TestFiltrosCatalogo:
    def test_listar_sem_filtro_ordina_por_nome(self, tmp_path: Path) -> None:
        cat = _catalogo_com_tres(tmp_path)
        res = cat.listar()
        assert [r["nome"] for r in res] == ["Ave", "Gato", "Zebra"]
        assert all(r["assinatura_valida"] is True for r in res)
        assert res[0]["id"] == "util.ave"

    def test_listar_por_categoria(self, tmp_path: Path) -> None:
        cat = _catalogo_com_tres(tmp_path)
        assert [r["nome"] for r in cat.listar(categoria="utilidades")] == [
            "Ave", "Zebra"]
        assert cat.listar(categoria="ia") == []

    def test_listar_por_tag(self, tmp_path: Path) -> None:
        cat = _catalogo_com_tres(tmp_path)
        assert [r["nome"] for r in cat.listar(tag="util")] == ["Ave", "Gato"]
        assert cat.listar(tag="inexistente") == []

    def test_listar_por_query_em_id_nome_e_descricao(self, tmp_path: Path) -> None:
        cat = _catalogo_com_tres(tmp_path)
        assert [r["nome"] for r in cat.listar(query="gato")] == ["Gato"]
        assert [r["nome"] for r in cat.listar(query="GATO")] == ["Gato"]
        assert [r["nome"] for r in cat.listar(query="listras")] == ["Zebra"]
        assert cat.listar(query="nada_disso") == []

    def test_categorias_e_tags_unicas_e_ordenadas(self, tmp_path: Path) -> None:
        cat = _catalogo_com_tres(tmp_path)
        assert cat.categorias() == ["seguranca", "utilidades"]
        assert cat.tags() == ["ave", "gato", "util", "zebra"]
        # catálogo vazio → listas vazias
        assert _catalogo(tmp_path / "outro").categorias() == []
        assert _catalogo(tmp_path / "outro").tags() == []


# ===========================================================================
# 5. ReviewsStore — validação, substituição e média
# ===========================================================================


class TestReviewsStore:
    def _store(self, tmp_path: Path) -> ReviewsStore:
        return ReviewsStore(_dirs(tmp_path)["reviews_dir"])

    def test_adicionar_e_listar(self, tmp_path: Path) -> None:
        store = self._store(tmp_path)
        assert store.adicionar(PluginReview(
            plugin_id="util.demo", usuario="ana", estrelas=5,
            texto="excelente", ts=1.0)) == {"ok": True}
        assert store.adicionar(PluginReview(
            plugin_id="util.demo", usuario="bruno", estrelas=3,
            texto="ok", ts=2.0)) == {"ok": True}
        res = store.listar("util.demo")
        assert len(res) == 2
        assert {r["usuario"] for r in res} == {"ana", "bruno"}
        assert res[0]["estrelas"] == 5
        # arquivo existe no disco com as reviews
        caminho = _dirs(tmp_path)["reviews_dir"] / "util.demo.json"
        assert len(json.loads(caminho.read_text(encoding="utf-8"))) == 2

    def test_substitui_review_do_mesmo_usuario(self, tmp_path: Path) -> None:
        store = self._store(tmp_path)
        store.adicionar(PluginReview(plugin_id="util.demo", usuario="ana",
                                     estrelas=1, texto="ruim"))
        store.adicionar(PluginReview(plugin_id="util.demo", usuario="ana",
                                     estrelas=5, texto="mudou de ideia"))
        res = store.listar("util.demo")
        assert len(res) == 1
        assert res[0]["estrelas"] == 5

    @pytest.mark.parametrize("estrelas", [0, 6, -1])
    def test_estrelas_invalidas(self, tmp_path: Path, estrelas: int) -> None:
        store = self._store(tmp_path)
        res = store.adicionar(PluginReview(plugin_id="util.demo",
                                           usuario="ana", estrelas=estrelas))
        assert res == {"ok": False, "motivo": "estrelas_invalidas"}
        assert store.listar("util.demo") == []

    def test_texto_grande_rejeitado(self, tmp_path: Path) -> None:
        store = self._store(tmp_path)
        res = store.adicionar(PluginReview(plugin_id="util.demo",
                                           usuario="ana", estrelas=4,
                                           texto="x" * 2001))
        assert res == {"ok": False, "motivo": "texto_grande"}

    def test_media_sem_reviews(self, tmp_path: Path) -> None:
        store = self._store(tmp_path)
        assert store.media("util.demo") == {
            "media": 0.0, "total": 0,
            "distribuicao": {1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
        }

    def test_media_com_distribuicao(self, tmp_path: Path) -> None:
        store = self._store(tmp_path)
        store.adicionar(PluginReview(plugin_id="util.demo", usuario="ana",
                                     estrelas=5))
        store.adicionar(PluginReview(plugin_id="util.demo", usuario="bruno",
                                     estrelas=3))
        res = store.media("util.demo")
        assert res["media"] == 4.0
        assert res["total"] == 2
        assert res["distribuicao"] == {1: 0, 2: 0, 3: 1, 4: 0, 5: 1}

    def test_arquivo_corrompido_retorna_vazio(self, tmp_path: Path) -> None:
        store = self._store(tmp_path)
        (_dirs(tmp_path)["reviews_dir"] / "util.demo.json").write_text(
            "isso nao é json", encoding="utf-8")
        assert store.listar("util.demo") == []
        assert store.media("util.demo")["total"] == 0

    def test_itens_nao_dict_sao_ignorados(self, tmp_path: Path) -> None:
        store = self._store(tmp_path)
        (_dirs(tmp_path)["reviews_dir"] / "util.demo.json").write_text(
            json.dumps(["lixo", 42,
                        {"plugin_id": "util.demo", "usuario": "ana",
                         "estrelas": 4}]),
            encoding="utf-8")
        res = store.listar("util.demo")
        assert len(res) == 1
        assert res[0]["estrelas"] == 4
        assert store.media("util.demo")["total"] == 1


# ===========================================================================
# 6. MarketplaceInstalador — índice, instalação e desinstalação
# ===========================================================================


class TestInstalador:
    def _instalador(self, tmp_path: Path, cat: MarketplaceCatalogo | None = None,
                    **extras: Any) -> MarketplaceInstalador:
        return MarketplaceInstalador(
            catalogo=cat or _catalogo(tmp_path),
            plugins_dir=_dirs(tmp_path)["plugins_dir"],
            **extras,
        )

    def test_indice_ausente_e_corrompido_nao_quebram(self, tmp_path: Path) -> None:
        inst = self._instalador(tmp_path)
        assert inst._instalados == {}

        (_dirs(tmp_path)["plugins_dir"] / "index.json").write_text(
            "{lixo total", encoding="utf-8")
        inst2 = self._instalador(tmp_path)
        assert inst2._instalados == {}

    def test_indice_gravado_e_recarregado(self, tmp_path: Path) -> None:
        chaves = _par_chaves()
        cat = _catalogo(tmp_path)
        _publicar(cat, _manifest(), chaves["privada"])
        inst = self._instalador(tmp_path, cat)
        assert inst.instalar("util.demo")["ok"]

        idx = _dirs(tmp_path)["plugins_dir"] / "index.json"
        bruto = json.loads(idx.read_text(encoding="utf-8"))
        assert bruto["instalados"][0]["manifest"]["id"] == "util.demo"
        assert bruto["instalados"][0]["assinatura_valida"] is True

        recarregado = self._instalador(tmp_path, cat)
        assert "util.demo" in recarregado._instalados
        assert recarregado._instalados["util.demo"].chave_publica == \
            chaves["publica"]

    def test_instalar_fora_do_catalogo(self, tmp_path: Path) -> None:
        inst = self._instalador(tmp_path)
        res = inst.instalar("util.nao_existe")
        assert res == {"ok": False,
                       "motivo": "plugin_nao_encontrado_no_catalogo"}

    def test_instalar_com_assinatura_invalida(self, tmp_path: Path) -> None:
        """Manifesto no catálogo sem assinatura válida não instala."""
        cat = _catalogo(tmp_path)
        cat._catalogo["util.demo"] = _manifest()  # sem _assinaturas
        inst = self._instalador(tmp_path, cat)
        res = inst.instalar("util.demo")
        assert res == {"ok": False, "motivo": "assinatura_invalida"}

    def test_instalar_ja_instalado_e_depois_forcar(self, tmp_path: Path) -> None:
        chaves = _par_chaves()
        cat = _catalogo(tmp_path)
        _publicar(cat, _manifest(), chaves["privada"])
        inst = self._instalador(tmp_path, cat)

        assert inst.instalar("util.demo")["ok"]
        res = inst.instalar("util.demo")
        assert res == {"ok": False, "motivo": "ja_instalado",
                       "id": "util.demo"}
        # com forcar=True reinstala sem reclamar
        assert inst.instalar("util.demo", forcar=True)["ok"]
        assert len(inst.listar_instalados()) == 1

    def test_instalar_rejeita_codigo_invalido(self, tmp_path: Path) -> None:
        """Catálogo em disco pode ter código assinado mas proibido — o
        instalador tem o próprio gate de validação (adicionar não deixa
        entrar, então injetamos direto, como um JSON externo faria)."""
        chaves = _par_chaves()
        cat = _catalogo(tmp_path)
        m = _manifest(codigo=CODE_IMPORT_PROIBIDO)
        assinatura, chave = _assinar(m, chaves["privada"])
        cat._catalogo[m.id] = m
        cat._assinaturas[m.id] = (assinatura, chave)

        inst = self._instalador(tmp_path, cat)
        res = inst.instalar("util.demo")
        assert res["ok"] is False
        assert res["motivo"].startswith("codigo_invalido:")

    def test_instalar_sem_funcao_no_codigo(self, tmp_path: Path) -> None:
        chaves = _par_chaves()
        cat = _catalogo(tmp_path)
        m = _manifest(funcao="funcao_que_nao_existe")
        _publicar(cat, m, chaves["privada"])
        inst = self._instalador(tmp_path, cat)
        res = inst.instalar("util.demo")
        assert res == {"ok": False, "motivo": "funcao_nao_encontrada"}

    def test_instalar_sem_depot_salva_copia_local(self, tmp_path: Path) -> None:
        chaves = _par_chaves()
        cat = _catalogo(tmp_path)
        _publicar(cat, _manifest(), chaves["privada"])
        inst = self._instalador(tmp_path, cat)

        res = inst.instalar("util.demo")
        assert res == {"ok": True, "id": "util.demo", "versao": "1.0.0"}
        destino = _dirs(tmp_path)["plugins_dir"] / "util.demo.py"
        assert destino.read_text(encoding="utf-8") == CODE_DEMO
        assert inst._instalados["util.demo"].caminho_local == str(destino)
        assert inst._instalados["util.demo"].assinatura_valida is True

        lista = inst.listar_instalados()
        assert len(lista) == 1
        assert lista[0]["id"] == "util.demo"
        assert lista[0]["nome"] == "Demo"
        assert lista[0]["versao"] == "1.0.0"
        assert lista[0]["categoria"] == "utilidades"
        assert lista[0]["assinatura_valida"] is True
        assert lista[0]["instalado_em"] > 0

    def test_instalar_sem_depot_com_plugin_manager(self, tmp_path: Path) -> None:
        chaves = _par_chaves()
        cat = _catalogo(tmp_path)
        _publicar(cat, _manifest(), chaves["privada"])
        pm = _GerenciadorFalso()
        inst = self._instalador(tmp_path, cat, plugin_manager=pm)

        assert inst.instalar("util.demo")["ok"]
        destino = _dirs(tmp_path)["plugins_dir"] / "util.demo.py"
        assert pm.carregados == [str(destino)]
        assert destino.exists()

    def test_instalar_com_depot_real(self, tmp_path: Path) -> None:
        chaves = _par_chaves()
        cat = _catalogo(tmp_path)
        _publicar(cat, _manifest(), chaves["privada"])
        depot, reg = _depot(tmp_path)
        inst = self._instalador(tmp_path, cat, supply_depot=depot)

        res = inst.instalar("util.demo")
        assert res["ok"] is True and res["versao"] == "1.0.0"
        arquivo = depot.codigos_dir / "util.demo.py"
        assert arquivo.read_text(encoding="utf-8") == CODE_DEMO
        assert reg.has("util.demo")
        entry = inst._instalados["util.demo"]
        assert entry.caminho_local == str(arquivo)
        assert entry.chave_publica == chaves["publica"]

    def test_instalar_com_depot_e_plugin_manager(self, tmp_path: Path) -> None:
        chaves = _par_chaves()
        cat = _catalogo(tmp_path)
        _publicar(cat, _manifest(), chaves["privada"])
        depot, _ = _depot(tmp_path)
        pm = _GerenciadorFalso()
        inst = self._instalador(tmp_path, cat, supply_depot=depot,
                                plugin_manager=pm)

        assert inst.instalar("util.demo")["ok"]
        esperado = depot.codigos_dir / "util.demo.py"
        assert pm.carregados == [str(esperado)]
        assert esperado.exists()

    def test_instalar_com_plugin_manager_falhando_nao_quebra(
        self, tmp_path: Path
    ) -> None:
        chaves = _par_chaves()
        cat = _catalogo(tmp_path)
        _publicar(cat, _manifest(), chaves["privada"])
        pm = _GerenciadorFalso(falha_load=True)
        inst = self._instalador(tmp_path, cat, plugin_manager=pm)

        res = inst.instalar("util.demo")
        assert res["ok"] is True
        assert pm.carregados == []  # falhou, mas a instalação seguiu
        assert "util.demo" in inst._instalados

    def test_instalar_quando_depot_recusa(self, tmp_path: Path) -> None:
        chaves = _par_chaves()
        cat = _catalogo(tmp_path)
        _publicar(cat, _manifest(), chaves["privada"])
        depot = _DepotRecusador(tmp_path, motivo="sem_espaco")
        inst = self._instalador(tmp_path, cat, supply_depot=depot)

        res = inst.instalar("util.demo")
        assert res == {"ok": False, "motivo": "depot_falhou: sem_espaco"}
        assert depot.chamadas and depot.chamadas[0]["nome"] == "util.demo"
        assert depot.chamadas[0]["origem"] == "marketplace"
        assert inst._instalados == {}

    def test_atualizar_bloqueada_por_major_no_depot(self, tmp_path: Path) -> None:
        """Major novo exige confirmar → depot bloqueia → depot_falhou."""
        chaves = _par_chaves()
        cat = _catalogo(tmp_path)
        _publicar(cat, _manifest(versao="1.0.0"), chaves["privada"])
        depot, _ = _depot(tmp_path)
        inst = self._instalador(tmp_path, cat, supply_depot=depot)
        assert inst.instalar("util.demo")["ok"]

        m2 = _manifest(versao="2.0.0")
        _publicar(cat, m2, chaves["privada"])
        res = inst.atualizar("util.demo")
        assert res["ok"] is False
        assert res["motivo"].startswith("depot_falhou:")
        assert "major_requer_confirmacao" in res["motivo"]

    def test_atualizar_sem_depot_atualiza_versao(self, tmp_path: Path) -> None:
        chaves = _par_chaves()
        cat = _catalogo(tmp_path)
        _publicar(cat, _manifest(versao="1.0.0"), chaves["privada"])
        inst = self._instalador(tmp_path, cat)
        assert inst.instalar("util.demo")["versao"] == "1.0.0"

        _publicar(cat, _manifest(versao="1.1.0"), chaves["privada"])
        res = inst.atualizar("util.demo")
        assert res["ok"] is True
        assert res["versao"] == "1.1.0"
        assert inst.listar_instalados()[0]["versao"] == "1.1.0"

    def test_desinstalar_sem_depot(self, tmp_path: Path) -> None:
        chaves = _par_chaves()
        cat = _catalogo(tmp_path)
        _publicar(cat, _manifest(), chaves["privada"])
        inst = self._instalador(tmp_path, cat)
        inst.instalar("util.demo")
        destino = _dirs(tmp_path)["plugins_dir"] / "util.demo.py"

        res = inst.desinstalar("util.demo")
        assert res == {"ok": True, "desinstalado": "util.demo"}
        assert not destino.exists()
        assert inst._instalados == {}
        assert inst.listar_instalados() == []
        # índice regravado sem a entrada
        bruto = json.loads((destino.parent / "index.json").read_text(
            encoding="utf-8"))
        assert bruto["instalados"] == []

    def test_desinstalar_nao_instalado(self, tmp_path: Path) -> None:
        inst = self._instalador(tmp_path)
        assert inst.desinstalar("util.nada") == {"ok": False,
                                                 "motivo": "nao_instalado"}

    def test_desinstalar_com_depot_real(self, tmp_path: Path) -> None:
        chaves = _par_chaves()
        cat = _catalogo(tmp_path)
        _publicar(cat, _manifest(), chaves["privada"])
        depot, reg = _depot(tmp_path)
        inst = self._instalador(tmp_path, cat, supply_depot=depot)
        inst.instalar("util.demo")
        assert reg.has("util.demo")

        res = inst.desinstalar("util.demo")
        assert res == {"ok": True, "desinstalado": "util.demo"}
        assert not (depot.codigos_dir / "util.demo.py").exists()
        assert not reg.has("util.demo")
        assert inst._instalados == {}

    def test_desinstalar_com_caminho_vazio_e_unload_quebrando(
        self, tmp_path: Path
    ) -> None:
        """unlink de caminho vazio e unload com exceção não derrubam."""
        chaves = _par_chaves()
        cat = _catalogo(tmp_path)
        _publicar(cat, _manifest(), chaves["privada"])
        pm = _GerenciadorFalso(falha_unload=True)
        inst = self._instalador(tmp_path, cat, plugin_manager=pm)
        inst.instalar("util.demo")

        inst._instalados["util.demo"].caminho_local = ""
        res = inst.desinstalar("util.demo")
        assert res == {"ok": True, "desinstalado": "util.demo"}
        assert inst._instalados == {}
        assert pm.descarregados == []  # unload falhou e foi engolido


# ===========================================================================
# 7. MarketplaceService — delegações e construtor padrão
# ===========================================================================


class TestMarketplaceService:
    def test_construtor_padrao_usa_data_relativo_ao_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sem argumentos, o serviço monta catálogo/reviews/instalador
        padrão em data/ — resolvido relativo ao CWD (levado para tmp)."""
        monkeypatch.chdir(tmp_path)
        svc = MarketplaceService()
        assert (tmp_path / "data" / "marketplace_plugins").is_dir()
        assert (tmp_path / "data" / "marketplace_reviews").is_dir()
        assert svc.stats() == {"catalogo": 0, "instalados": 0,
                               "categorias": 0, "tags": 0}

    def test_delegacoes_completas(self, tmp_path: Path) -> None:
        chaves = _par_chaves()
        dirs = _dirs(tmp_path)
        cat = MarketplaceCatalogo(**dirs)
        rev = ReviewsStore(dirs["reviews_dir"])
        inst = MarketplaceInstalador(catalogo=cat,
                                     plugins_dir=dirs["plugins_dir"])
        svc = MarketplaceService(catalogo=cat, reviews=rev, instalador=inst)

        # publicar + buscar + obter
        assinatura, chave = _assinar(_manifest(), chaves["privada"])
        assert svc.publicar(_manifest(), assinatura, chave)["ok"]
        assert [r["id"] for r in svc.buscar()] == ["util.demo"]
        assert svc.obter("util.demo")["nome"] == "Demo"
        assert svc.obter("util.nada") is None
        assert svc.categorias() == ["utilidades"]
        assert svc.tags() == ["demo", "util"]

        # reviews
        assert svc.reviews_adicionar(PluginReview(
            plugin_id="util.demo", usuario="ana", estrelas=4)) == {"ok": True}
        assert svc.reviews_listar("util.demo")[0]["usuario"] == "ana"
        assert svc.reviews_media("util.demo")["media"] == 4.0

        # instalar / listar / atualizar / desinstalar
        assert svc.instalar("util.demo")["ok"]
        assert len(svc.listar_instalados()) == 1
        assert svc.atualizar("util.demo")["ok"]
        assert svc.desinstalar("util.demo")["ok"]
        assert svc.listar_instalados() == []

        # stats com catálogo publicado e sem instalados
        assert svc.stats() == {"catalogo": 1, "instalados": 0,
                               "categorias": 1, "tags": 2}
        assert svc.remover_publicacao("util.demo") == {"ok": True,
                                                       "removido": "util.demo"}
        assert svc.stats()["catalogo"] == 0

    def test_service_com_instalador_padrao(self, tmp_path: Path,
                                           monkeypatch: pytest.MonkeyPatch
                                           ) -> None:
        """Instalador default (sem depot) montado pelo próprio serviço."""
        monkeypatch.chdir(tmp_path)
        dirs = _dirs(tmp_path)
        cat = MarketplaceCatalogo(**dirs)
        svc = MarketplaceService(catalogo=cat,
                                 reviews=ReviewsStore(dirs["reviews_dir"]))
        assert (tmp_path / "data" / "marketplace_plugins").is_dir()
        assert svc.listar_instalados() == []
        assert svc.instalar("util.nada")["motivo"] == \
            "plugin_nao_encontrado_no_catalogo"
