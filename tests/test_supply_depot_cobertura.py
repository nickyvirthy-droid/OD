"""OMEGA DRAKON • TESTES
Módulo: tests/test_supply_depot_cobertura.py
Descrição: fechamento da dívida de cobertura de tools/supply_depot.py
           (16/11) — paralelo a tests/test_supply_depot.py, que NÃO é
           tocado. Cobre o que nunca rodou: export com histórico
           ausente, TODAS as validações do import (transacional),
           diff de catálogos, assinatura Ed25519, ferramentas nativas,
           semver estrito, templates, teste unitário gerado,
           staging/review (roundtrip que estava QUEBRADO: o código era
           gravado em ferramentas/ mas lido de ferramentas_staging/ —
           corrigido em 16/11 junto) e bordas de carregar/customizar/
           rollback.
Arquiteto: Alex Projeti
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tools import supply_depot as sd_mod
from tools.registry import ActionRegistry
from tools.supply_depot import (
    ED25519_SCHEMA,
    EXPORT_SCHEMA,
    Ferramenta,
    SupplyDepot,
    _carregar_fn,
    _float_ou_none,
)

# --- Códigos válidos (mesmo gate do AutoExtension: sem import) ---------------

CODE_DEMO = "def demo(**params):\n    return {'ok': True, 'result': 'demo'}\n"
CODE_V2 = "def demo(**params):\n    return {'ok': True, 'result': 'v2'}\n"
CODE_Y = "def y(**params):\n    return {'ok': True}\n"
CODE_Y2 = "def y(**params):\n    return {'ok': True, 'v': 2}\n"
CODE_Z = "def z(**params):\n    return {'ok': True, 'result': 'z'}\n"


def _mk_depot(
    tmp_path: Path,
    *,
    registry: ActionRegistry | None = None,
    max_codigo: int = 8000,
    espaco: int | None = None,
) -> tuple[SupplyDepot, ActionRegistry]:
    """Depot real em tmp (relógio fixo) — mesmo padrão do teste base."""
    reg = registry if registry is not None else ActionRegistry()
    depot = SupplyDepot(
        registry=reg,
        catalogo_path=tmp_path / "ferramentas_catalogo.json",
        codigos_dir=tmp_path / "ferramentas",
        backup_dir=tmp_path / "ferramentas_backup",
        raiz=tmp_path,
        clock=lambda: 1_700_000_000.0,
        max_codigo=max_codigo,
        espaco_livre_fn=(lambda _p: espaco) if espaco is not None else None,
    )
    return depot, reg


def _hist(tmp_path: Path) -> tuple[SupplyDepot, str]:
    """Depot com util.demo v1→v1.1 (1 versão no histórico) + nome do backup."""
    depot, _ = _mk_depot(tmp_path)
    depot.instalar(nome="util.demo", codigo=CODE_DEMO, versao="1.0.0")
    depot.instalar(nome="util.demo", codigo=CODE_V2, versao="1.1.0")
    entrada = depot.obter("util.demo")
    assert entrada is not None and entrada.anteriores
    return depot, str(entrada.anteriores[-1]["arquivo_backup"])


def _bundle(*itens: dict[str, Any], schema: str = EXPORT_SCHEMA) -> dict[str, Any]:
    return {"schema": schema, "gerado_em": 1_700_000_000.0,
            "ferramentas": list(itens)}


# ===========================================================================
# 1. exportar — código/backup ausente não derruba o backup (1134-1149)
# ===========================================================================

class TestExportarCobertura:
    def test_codigo_ausente_sai_com_erro_no_bundle(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        assert depot.instalar(nome="util.demo", codigo=CODE_DEMO)["ok"]
        (tmp_path / "ferramentas" / "util.demo.py").unlink()

        bundle = depot.exportar()
        assert bundle["schema"] == EXPORT_SCHEMA
        assert bundle["gerado_em"] == 1_700_000_000.0
        assert bundle["ferramentas"][0]["codigo"] == ""
        assert "util.demo: codigo_atual_ausente" in bundle["erros"]

    def test_historico_exportado_com_backup_apagado(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util.demo", codigo=CODE_DEMO, versao="1.0.0")
        depot.instalar(nome="util.demo", codigo=CODE_V2, versao="1.1.0")
        entrada = depot.obter("util.demo")
        assert entrada is not None and entrada.anteriores
        nome = entrada.anteriores[-1]["arquivo_backup"]
        (tmp_path / "ferramentas_backup" / nome).unlink()

        bundle = depot.exportar()
        ferramenta = bundle["ferramentas"][0]
        assert ferramenta["anteriores"][0]["codigo"] == ""
        assert any(nome in e and "ausente" in e for e in bundle["erros"])

    def test_historico_exportado_com_backup_intacto(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util.demo", codigo=CODE_DEMO, versao="1.0.0")
        depot.instalar(nome="util.demo", codigo=CODE_V2, versao="1.1.0")

        bundle = depot.exportar()
        hist = bundle["ferramentas"][0]["anteriores"]
        assert len(hist) == 1
        assert hist[0]["codigo"] == CODE_DEMO
        assert bundle["erros"] == []


# ===========================================================================
# 2. importar — guardas + TODAS as validações de _preparar_importacao
# ===========================================================================

_CASOS_ITEM: list[tuple[Any, str]] = [
    # (item, trecho esperado em erros[0])
    (42, "nao_e_objeto"),
    ({"id": ""}, "id_invalido"),
    ({"id": "Util.Ferramenta", "codigo": CODE_Y}, "id_invalido"),
    ({"id": "a..b", "codigo": CODE_Y}, "id_invalido"),
    ({"id": "z" * 100, "codigo": CODE_Y}, "id_invalido"),
    ({"id": "util.y", "funcao": "f" * 101, "codigo": CODE_Y}, "funcao_invalida"),
    ({"id": "util.y", "versao": "9" * 101, "codigo": CODE_Y}, "versao_invalida"),
    ({"id": "util.y", "codigo": None}, "codigo_obrigatorio"),
    ({"id": "util.y", "codigo": "x" * 8001}, "codigo_excede_8000"),
    ({"id": "util.y", "codigo": "import requests\ndef y(): pass"},
     "codigo_rejeitado"),
    ({"id": "util.y", "codigo": "def outra(): pass"}, "funcao_ausente"),
    ({"id": "util.y", "codigo": CODE_Y, "sha256": "0" * 64}, "sha256_divergente"),
    ({"id": "util.y", "codigo": CODE_Y, "params": []}, "params_invalido"),
    ({"id": "util.y", "codigo": CODE_Y, "custom": "x"}, "custom_invalido"),
    ({"id": "util.y", "codigo": CODE_Y, "ativa": "sim"}, "ativa_invalida"),
    ({"id": "util.y", "codigo": CODE_Y, "descricao": 123}, "descricao_invalido"),
    ({"id": "util.y", "codigo": CODE_Y, "descricao": "d" * 2001}, "descricao_grande"),
    ({"id": "util.y", "codigo": CODE_Y, "categoria": 9}, "categoria_invalido"),
    ({"id": "util.y", "codigo": CODE_Y, "categoria": "c" * 101}, "categoria_grande"),
    ({"id": "util.y", "codigo": CODE_Y, "permission": 9}, "permission_invalido"),
    ({"id": "util.y", "codigo": CODE_Y, "permission": "p" * 201}, "permission_grande"),
    ({"id": "util.y", "codigo": CODE_Y, "origem": 9}, "origem_invalido"),
    ({"id": "util.y", "codigo": CODE_Y, "origem": "o" * 101}, "origem_grande"),
    ({"id": "util.y", "codigo": CODE_Y, "anteriores": "nao"},
     "anteriores_invalidos"),
    ({"id": "util.y", "codigo": CODE_Y, "anteriores": None}, "ok"),
]


class TestImportarValidacoes:
    @pytest.mark.parametrize("item, esperado", _CASOS_ITEM,
                             ids=[str(c[0])[:40] for c in _CASOS_ITEM])
    def test_cada_validacao_de_item(self, tmp_path: Path,
                                    item: Any,
                                    esperado: str) -> None:
        depot, _ = _mk_depot(tmp_path)
        r = depot.importar(_bundle(item))
        if esperado == "ok":
            # anteriores=None vira lista vazia: item válido é importado
            assert r["ok"] is True and r["total"] == 1
            return
        assert r["ok"] is False
        assert r["motivo"] == "importacao_invalida"
        assert any(esperado in e for e in r["erros"])

    def test_item_duplicado(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        r = depot.importar(_bundle(
            {"id": "util.y", "codigo": CODE_Y},
            {"id": "util.y", "codigo": CODE_Y2},
        ))
        assert r["ok"] is False
        assert any("id_duplicado" in e for e in r["erros"])

    def test_conflito_action_alheia(self, tmp_path: Path,
                                    monkeypatch: pytest.MonkeyPatch) -> None:
        depot, reg = _mk_depot(tmp_path)
        original_has = reg.has
        monkeypatch.setattr(
            reg, "has",
            lambda i: i == "util.alheia" or original_has(i),
        )
        r = depot.importar(_bundle({"id": "util.alheia", "codigo": CODE_Y}))
        assert r["ok"] is False
        assert any("conflito_action_alheia" in e for e in r["erros"])

    def test_ferramentas_nao_e_lista(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        r = depot.importar({"schema": EXPORT_SCHEMA, "ferramentas": {}})
        assert r == {"ok": False, "motivo": "ferramentas_invalidas"}

    def test_ferramentas_demais(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        itens = [{"id": f"util.t{i}"} for i in range(201)]
        r = depot.importar(_bundle(*itens))
        assert r["ok"] is False
        assert r["motivo"].startswith("ferramentas_demais")

    def test_modo_invalido(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        r = depot.importar(_bundle(), modo="apagar")
        assert r == {"ok": False, "motivo": "modo_invalido"}

    def test_substituir_ped_confirmacao(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util1.demo", codigo=CODE_DEMO)
        r = depot.importar(_bundle({"id": "util.y", "codigo": CODE_Y}))
        assert r["ok"] is False
        assert r["motivo"] == "confirmacao_necessaria"
        assert r["total_atual"] == 1
        assert r["total_importado"] == 1

    def test_limite_de_bytes_para_no_meio(self, tmp_path: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
        """Transação: estourou o limite → erro declarado, o próximo item
        NUNCA é validado e nada é escrito no disco."""
        monkeypatch.setattr(sd_mod, "LIMITE_IMPORT_BYTES", 10)
        depot, _ = _mk_depot(tmp_path)
        r = depot.importar(_bundle(
            {"id": "util.y", "codigo": CODE_Y},
            {"id": 42},  # jamais alcançado: o limite estourou no 1º
        ))
        assert r["ok"] is False
        assert r["motivo"] == "importacao_invalida"
        assert r["erros"] == ["importacao_grande: limite de bytes excedido"]
        assert depot.obter("util.y") is None  # transação não escreveu nada

    def test_bundle_nao_e_dict(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        r = depot.importar("nao_e_bundle")
        assert r == {"ok": False, "motivo": "bundle_invalido"}

    def test_schema_desconhecido(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        r = depot.importar(_bundle(schema="od.fora_de_este_mundo.v9"))
        assert r["ok"] is False
        assert r["motivo"].startswith("schema_invalido")


# ===========================================================================
# 3. _validar_historico_import — cada motivo de rejeição (1170-1196)
# ===========================================================================

_CASOS_HIST: list[tuple[dict[str, Any], str]] = [
    ([42], "historico_nao_e_objeto"),
    ([{"versao": ""}], "historico_versao_invalida"),
    ([{"versao": "1.0.0", "funcao": "f" * 101}], "historico_funcao_invalida"),
    ([{"versao": "1.0.0", "codigo": ""}], "historico_sem_codigo"),
    ([{"versao": "1.0.0", "codigo": "x" * 8001}], "historico_codigo_grande"),
    ([{"versao": "1.0.0", "codigo": "import requests"}],
     "historico_codigo_rejeitado"),
    ([{"versao": "1.0.0", "codigo": "def outra(): pass"}],
     "historico_funcao_ausente"),
    ([{"versao": "1.0.0", "codigo": CODE_Y, "sha256": "0" * 64}],
     "historico_sha256_divergente"),
    ([{"versao": "1.0.0", "codigo": CODE_Y, "arquivo_backup": "hostil.py"}],
     "historico_arquivo_invalido"),
    ([{"versao": "1.0.0", "codigo": CODE_Y, "arquivo_backup": "util.y.dup.py"},
      {"versao": "1.0.1", "codigo": CODE_Y, "arquivo_backup": "util.y.dup.py"}],
     "historico_arquivo_duplicado"),
    ([{"versao": "1.0.0", "codigo": CODE_Y}], "ok"),
]


class TestHistoricoImport:
    @pytest.mark.parametrize("hist, esperado", _CASOS_HIST,
                             ids=[str(c[0])[:40] for c in _CASOS_HIST])
    def test_cada_motivo(self, tmp_path: Path, hist: list[Any],
                         esperado: str) -> None:
        depot, _ = _mk_depot(tmp_path)
        r = depot.importar(_bundle(
            {"id": "util.y", "codigo": CODE_Y, "anteriores": list(hist)}))
        if esperado == "ok":
            assert r["ok"] is True
            assert r["historico"] == 1
            assert r["backups"] == 1
            entrada = depot.obter("util.y")
            assert entrada is not None
            meta = entrada.anteriores[0]
            assert meta["sha256"] == __import__("hashlib").sha256(
                CODE_Y.encode()).hexdigest()
            assert meta["bytes"] == len(CODE_Y.encode())
            return
        assert r["ok"] is False
        assert any(esperado in e for e in r["erros"])


# ===========================================================================
# 4. importar — aplicação, mescla e rollback transacional
# ===========================================================================

class TestImportarAplicacao:
    def test_substituir_limpa_e_instala(self, tmp_path: Path) -> None:
        depot, reg = _mk_depot(tmp_path)
        depot.instalar(nome="util1.demo", codigo=CODE_DEMO)
        r = depot.importar(_bundle({"id": "util.y", "codigo": CODE_Y}),
                           modo="substituir", confirmar=True)
        assert r["ok"] is True
        assert (r["adicionados"], r["removidos"], r["total"]) == (1, 1, 1)
        assert depot.obter("util1.demo") is None
        assert not reg.has("util1.demo")
        assert reg.has("util.y")

    def test_mesclar_preserva_o_fora_do_bundle(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util1.demo", codigo=CODE_DEMO, versao="1.0.0")
        origem, origem_reg = _mk_depot(tmp_path / "origem")
        origem.instalar(nome="util1.demo", codigo=CODE_V2, versao="1.1.0")
        origem.instalar(nome="util.y", codigo=CODE_Y)

        r = depot.importar(origem.exportar(), modo="mesclar")
        assert r["ok"] is True
        assert (r["adicionados"], r["atualizados"], r["removidos"]) == (1, 1, 0)
        assert r["total"] == 2
        assert depot.obter("util1.demo").versao == "1.1.0"
        assert depot.obter("util.y") is not None

    def test_falha_no_registro_rola_tudo_para_tras(self, tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
        depot, reg = _mk_depot(tmp_path)
        depot.instalar(nome="util1.demo", codigo=CODE_DEMO)
        monkeypatch.setattr(depot, "_registrar", lambda *a, **k: False)

        r = depot.importar(_bundle({"id": "util.y", "codigo": CODE_Y}),
                           modo="substituir", confirmar=True)
        assert r["ok"] is False
        assert r["rollback"] is True
        assert r["motivo"].startswith("rollback:")
        # NADA se perde: o catálogo de antes continua íntegro
        assert depot.obter("util1.demo") is not None
        assert depot.obter("util.y") is None
        assert not reg.has("util.y")

    def test_roundtrip_exportar_importar(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util.demo", codigo=CODE_DEMO, versao="1.0.0")
        depot.instalar(nome="util.demo", codigo=CODE_V2, versao="1.1.0")
        bundle = depot.exportar()

        destino, reg_destino = _mk_depot(tmp_path / "destino")
        r = destino.importar(bundle, modo="substituir", confirmar=True)
        assert r["ok"] is True
        assert r["total"] == 1
        assert r["historico"] == 1
        assert r["backups"] == 1
        assert destino.obter("util.demo").versao == "1.1.0"
        assert reg_destino.has("util.demo")


# ===========================================================================
# 5. diff de catálogos + diff visual (1458-1524)
# ===========================================================================

class TestDiffCatalogos:
    def _dois_depots(self, tmp_path: Path):
        a, _ = _mk_depot(tmp_path / "a")
        a.instalar(nome="util1.demo", codigo=CODE_DEMO, versao="1.0.0")
        a.instalar(nome="util2.demo", codigo=CODE_DEMO, versao="1.0.0")
        b, _ = _mk_depot(tmp_path / "b")
        b.instalar(nome="util2.demo", codigo=CODE_V2, versao="2.0.0")
        b.instalar(nome="util.y", codigo=CODE_Y, versao="1.0.0")
        return a, b

    def test_diff_entre_depots(self, tmp_path: Path) -> None:
        a, b = self._dois_depots(tmp_path)
        d = a.diff_catalogos(b)
        assert [x["id"] for x in d["adicionado"]] == ["util.y"]
        assert [x["id"] for x in d["removido"]] == ["util1.demo"]
        assert len(d["atualizado"]) == 1
        atual = d["atualizado"][0]
        assert atual["id"] == "util2.demo"
        assert atual["versao_antiga"] == "1.0.0"
        assert atual["versao_nova"] == "2.0.0"
        assert "versao" in atual["diff_campos"]
        assert d["igual"] == []
        assert d["resumo"] == {"adicionados": 1, "removidos": 1,
                               "atualizados": 1, "iguais": 0}

    def test_diff_idempotente_e_com_dict(self, tmp_path: Path) -> None:
        a, b = self._dois_depots(tmp_path)
        d = a.diff_catalogos(a)
        assert d["resumo"]["iguais"] == 2
        assert d["atualizado"] == []

        como_dict = {k: v.para_dict() for k, v in b._catalogo.items()}
        como_dict["util.lixo"] = "nao_e_dict"  # filtrado
        d2 = a.diff_catalogos(como_dict)
        assert d2["resumo"]["adicionados"] == 1   # util.y
        assert d2["resumo"]["atualizados"] == 1   # util2.demo
        assert d2["resumo"]["removidos"] == 1     # util1.demo

    def test_diff_com_none_devolve_vazio(self, tmp_path: Path) -> None:
        a, _ = _mk_depot(tmp_path)
        d = a.diff_catalogos(None)
        assert d["resumo"] == {"adicionados": 0, "removidos": 0,
                               "atualizados": 0, "iguais": 0}

    def test_diff_visual_renderiza_e_omite_quando_igual(
        self, tmp_path: Path
    ) -> None:
        a, b = self._dois_depots(tmp_path)
        texto = a.diff_visual(b)
        assert "+ util.y" in texto
        assert "- util1.demo" in texto
        assert "~ util2.demo 1.0.0→2.0.0" in texto

        identico = a.diff_visual(a)
        assert "(catálogos idênticos)" in identico


# ===========================================================================
# 6. assinatura Ed25519 de bundles (1534-1621)
# ===========================================================================

class TestAssinaturaEd25519:
    def test_gerar_assinar_verificar(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        par = SupplyDepot.gerar_par_chaves_ed25519()
        assert set(par) == {"privada", "publica"}

        original = _bundle({"id": "util.y", "codigo": CODE_Y})
        assinado = depot.assinar_bundle(original, par["privada"])
        assert "assinatura" not in original  # não muta in-place
        assert assinado["schema_assinatura"] == ED25519_SCHEMA
        assert assinado["chave_publica"] == par["publica"]
        assert SupplyDepot.verificar_assinatura_bundle(assinado) == (
            True, "assinatura_valida")

    def test_sem_assinatura_ou_chave(self) -> None:
        assert SupplyDepot.verificar_assinatura_bundle({}) == (
            False, "assinatura_ou_chave_ausente")

    def test_base64_invalido(self) -> None:
        # "a" (1 caractere) lança binascii.Error — verificado empírico
        assert SupplyDepot.verificar_assinatura_bundle(
            {"assinatura": "a", "chave_publica": "b"}) == (
            False, "base64_invalido")

    def test_conteudo_trocado_falha_na_verificacao(
        self, tmp_path: Path
    ) -> None:
        depot, _ = _mk_depot(tmp_path)
        par = SupplyDepot.gerar_par_chaves_ed25519()
        assinado = depot.assinar_bundle(_bundle({"id": "util.y",
                                                 "codigo": CODE_Y}),
                                        par["privada"])
        adulterado = dict(assinado)
        adulterado["ferramentas"] = [{"id": "util.z"}]
        assert SupplyDepot.verificar_assinatura_bundle(adulterado) == (
            False, "assinatura_invalida")

    def test_criptografia_indisponivel(self, tmp_path: Path,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sd_mod, "_CRYPTO_DISPONIVEL", False)
        depot, _ = _mk_depot(tmp_path)
        with pytest.raises(RuntimeError):
            SupplyDepot.gerar_par_chaves_ed25519()
        with pytest.raises(RuntimeError):
            depot.assinar_bundle({}, "chave")
        assert SupplyDepot.verificar_assinatura_bundle({}) == (
            False, "cryptography_nao_instalado")


# ===========================================================================
# 7. ferramentas nativas + semver estrito (1632-1690)
# ===========================================================================

class TestFerramentasNativas:
    def test_listar_ordenado_com_metadados(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        itens = depot.listar_ferramentas_nativas()
        ids = [i["id"] for i in itens]
        assert ids == sorted(ids)
        assert ids == sorted(sd_mod.FERRAMENTAS_NATIVAS)
        for item in itens:
            assert {"id", "descricao", "params", "permission",
                    "categoria"} <= set(item)

    def test_instalar_nativa(self, tmp_path: Path) -> None:
        depot, reg = _mk_depot(tmp_path)
        r = depot.instalar_nativa("auto.hash_texto")
        assert r["ok"] is True
        assert reg.has("auto.hash_texto")
        entrada = depot.obter("auto.hash_texto")
        assert entrada is not None
        assert entrada.origem == "nativa"
        assert entrada.versao == "1.0.0"

    def test_nativa_desconhecida(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        r = depot.instalar_nativa("auto.nao_existe")
        assert r["ok"] is False
        assert r["motivo"].startswith("ferramenta_nativa_desconhecida")


class TestSemverEstrito:
    @pytest.mark.parametrize("versao, esperado", [
        (123, False),
        ("", False),
        ("1.2", False),
        ("v1.2.3", False),
        ("1.2.3-rc1", False),
        ("1.2.3+build", False),
        ("01.2.3", False),
        ("1.02.3", False),
        ("1.2.3.", False),
        ("1.2.3", True),
        (" 1.2.3 ", True),
    ])
    def test_tabela(self, versao: Any, esperado: bool) -> None:
        ok, motivo = SupplyDepot.validar_semver_estrito(versao)
        assert ok is esperado
        assert motivo  # sempre há motivo (contrato da casa)


# ===========================================================================
# 8. templates + teste unitário gerado (1696-1811)
# ===========================================================================

class TestTemplates:
    def test_listar_templates(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        itens = depot.listar_templates()
        ids = [i["id"] for i in itens]
        assert ids == sorted(sd_mod.TEMPLATES_FERRAMENTAS)
        for item in itens:
            assert {"id", "descricao", "params_exemplo"} <= set(item)

    def test_template_desconhecido(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        r = depot.gerar_codigo_de_template("nao_existe", "util.x")
        assert r["ok"] is False
        assert r["motivo"].startswith("template_desconhecido")

    def test_nome_invalido(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        r = depot.gerar_codigo_de_template("calculadora_simples", "")
        assert r["ok"] is False
        assert r["motivo"].startswith("nome_invalido")

    def test_gera_codigo_valido(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        r = depot.gerar_codigo_de_template(
            "processador_texto", "util.processar",
            descricao="Processa texto", params={"required": ["texto"]})
        assert r["ok"] is True
        assert r["id"] == "util.processar"
        assert r["funcao"] == "processar"
        assert "def processar(" in r["codigo"]
        assert r["params_gerados"] == {"required": ["texto"]}
        assert r["descricao"] == "Processa texto"
        ok, motivo = sd_mod.validar_codigo(r["codigo"])
        assert ok, motivo

    def test_descricao_padrao_sem_prefixo_template(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        r = depot.gerar_codigo_de_template("calculadora_simples", "util.calc")
        assert r["ok"] is True
        assert not r["descricao"].startswith("Template:")
        assert r["params_gerados"] == sd_mod.TEMPLATES_FERRAMENTAS[
            "calculadora_simples"]["params_exemplo"]


class TestGerarTesteUnitario:
    def test_com_params_do_template(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        # "soma" aparece no corpo do template de calculadora
        r = depot.gerar_teste_unitario("util.soma", CODE_DEMO)
        assert r["ok"] is True
        assert r["funcao"] == "soma"
        assert "test_soma_caso_feliz" in r["codigo_teste"]
        assert "if True:" in r["codigo_teste"]
        assert r["caminho_sugerido"] == "tests/test_util.soma.py"
        compile(r["codigo_teste"], "<teste>", "exec")  # compila de verdade

    def test_sem_template_relacionado(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        r = depot.gerar_teste_unitario("util.abc", CODE_DEMO)
        assert r["ok"] is True
        assert "if False:" in r["codigo_teste"]
        compile(r["codigo_teste"], "<teste>", "exec")

    def test_funcao_explícita(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        r = depot.gerar_teste_unitario("util.x", CODE_DEMO, funcao="demo")
        assert r["ok"] is True
        assert r["funcao"] == "demo"
        assert "_carregar_fn(CODE, \"demo\")" in r["codigo_teste"]

    def test_funcao_com_espaco_quebra_o_gerado(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        r = depot.gerar_teste_unitario("util.x", CODE_DEMO,
                                       funcao="com espaço")
        assert r["ok"] is False
        assert r["motivo"].startswith("teste_gerado_com_syntax_error")


# ===========================================================================
# 9. staging / review — roundtrip que estava quebrado (1827-1942)
# ===========================================================================

class TestStaging:
    def _staging_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "ferramentas_staging"

    def test_roundtrip_salvar_listar_instalar(self, tmp_path: Path) -> None:
        """O roundtrip completo: era `codigo_ausente_no_staging` para
        SEMPRE antes da correção de 16/11 (código gravado em
        ferramentas/ mas lido de ferramentas_staging/)."""
        depot, reg = _mk_depot(tmp_path)
        r = depot.staging_salvar(
            "util.demo", CODE_DEMO, metadados={"descricao": "demo"})
        assert r["ok"] is True
        assert r["staging"] is True
        # código E metadados JUNTOS na área de staging
        assert (self._staging_dir(tmp_path) / "util.demo.py").exists()
        assert len(depot.staging_listar()) == 1

        inst = depot.staging_instalar("util.demo")
        assert inst["ok"] is True
        assert reg.has("util.demo")
        assert depot.obter("util.demo") is not None
        # staging limpo depois da instalação
        assert depot.staging_listar() == []
        assert not (self._staging_dir(tmp_path) / "util.demo.py").exists()

    def test_salvar_validações(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        assert depot.staging_salvar("", CODE_DEMO)["motivo"].startswith(
            "nome_invalido")
        assert depot.staging_salvar("util.x", "import requests")[
            "motivo"].startswith("codigo_invalido")
        r = depot.staging_salvar("util.x", CODE_DEMO)  # def demo ≠ util.x
        assert r["motivo"].startswith("funcao_nao_encontrada")

    def test_salvar_com_funcao_dos_metadados(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        r = depot.staging_salvar("util.qualquer", CODE_DEMO,
                                 metadados={"funcao": "demo",
                                            "versao": "2.0.0"})
        assert r["ok"] is True
        meta = depot.staging_listar()[0]
        assert meta["funcao"] == "demo"
        assert meta["versao"] == "2.0.0"

    def test_listar_sem_dir_e_com_meta_corrompida(
        self, tmp_path: Path
    ) -> None:
        depot, _ = _mk_depot(tmp_path)
        assert depot.staging_listar() == []
        staging = self._staging_dir(tmp_path)
        staging.mkdir()
        (staging / "quebrada.meta.json").write_text("{lixo",
                                                    encoding="utf-8")
        assert depot.staging_listar() == []  # corrompida é ignorada

    def test_remover(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.staging_salvar("util.demo", CODE_DEMO)
        r = depot.staging_remover("util.demo")
        assert r["ok"] is True
        assert sorted(r["removidos"]) == ["util.demo.meta.json",
                                          "util.demo.py"]
        assert depot.staging_listar() == []
        # segunda remoção: nada lá, devolve lista vazia
        assert depot.staging_remover("util.demo")["removidos"] == []

    def test_instalar_sem_staging(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        r = depot.staging_instalar("util.nao")
        assert r == {"ok": False, "motivo": "nao_esta_no_staging"}

    def test_instalar_com_meta_corrompida(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        staging = self._staging_dir(tmp_path)
        staging.mkdir()
        (staging / "util.x.meta.json").write_text("{lixo",
                                                  encoding="utf-8")
        r = depot.staging_instalar("util.x")
        assert r["ok"] is False
        assert r["motivo"].startswith("meta_invalida")

    def test_instalar_sem_codigo(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        staging = self._staging_dir(tmp_path)
        staging.mkdir()
        (staging / "util.x.meta.json").write_text(
            '{"id": "util.x", "versao": "1.0.0"}', encoding="utf-8")
        r = depot.staging_instalar("util.x")
        assert r == {"ok": False, "motivo": "codigo_ausente_no_staging"}


# ===========================================================================
# 10. carregar / customizar / rollback — bordas (923, 1001-1071)
# ===========================================================================

class TestCarregarBorda:
    def test_codigo_ausente(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util.demo", codigo=CODE_DEMO)
        (tmp_path / "ferramentas" / "util.demo.py").unlink()
        r = depot.carregar()
        assert r == {"carregadas": 0, "erros": 1}
        assert depot.ultimo_erro == "util.demo: código ausente"

    def test_codigo_invalido(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util.demo", codigo=CODE_DEMO)
        (tmp_path / "ferramentas" / "util.demo.py").write_text(
            "def (", encoding="utf-8")
        r = depot.carregar()
        assert r == {"carregadas": 0, "erros": 1}
        assert depot.ultimo_erro.startswith("util.demo:")

    def test_registro_recusado(self, tmp_path: Path,
                               monkeypatch: pytest.MonkeyPatch) -> None:
        # boot de verdade: manifesto carregado, registry VAZIO
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util.demo", codigo=CODE_DEMO)
        monkeypatch.setattr(depot, "_registrar", lambda *a, **k: False)
        r = depot.carregar()
        assert r == {"carregadas": 0, "erros": 1}
        assert depot.ultimo_erro == "util.demo: registro recusado"


class TestCustomizarBorda:
    def test_codigo_ausente_em_disco(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util.demo", codigo=CODE_DEMO)
        (tmp_path / "ferramentas" / "util.demo.py").unlink()
        r = depot.customizar("util.demo", descricao="nova")
        assert r == {"ok": False, "motivo": "codigo_ausente_em_disco"}

    def test_funcao_nao_encontrada(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util.demo", codigo=CODE_DEMO)
        (tmp_path / "ferramentas" / "util.demo.py").write_text(
            "def outra(**params):\n    return {'ok': True}\n",
            encoding="utf-8")
        r = depot.customizar("util.demo", descricao="nova")
        assert r == {"ok": False, "motivo": "funcao_nao_encontrada"}

    def test_registro_recusado(self, tmp_path: Path,
                               monkeypatch: pytest.MonkeyPatch) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util.demo", codigo=CODE_DEMO)
        monkeypatch.setattr(depot, "_registrar", lambda *a, **k: False)
        r = depot.customizar("util.demo", descricao="nova")
        assert r == {"ok": False, "motivo": "registro_no_registry_falhou"}


class TestRollbackBorda:
    def _com_historico(self, tmp_path: Path) -> tuple[SupplyDepot, str]:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util.demo", codigo=CODE_DEMO, versao="1.0.0")
        depot.instalar(nome="util.demo", codigo=CODE_V2, versao="1.1.0")
        entrada = depot.obter("util.demo")
        assert entrada is not None and entrada.anteriores
        return depot, entrada.anteriores[-1]["arquivo_backup"]

    def test_backup_sem_funcao_alvo(self, tmp_path: Path) -> None:
        depot, nome_backup = self._com_historico(tmp_path)
        (tmp_path / "ferramentas_backup" / nome_backup).write_text(
            "def (", encoding="utf-8")
        r = depot.rollback("util.demo")
        assert r == {"ok": False,
                     "motivo": "funcao_nao_encontrada_no_backup"}

    def test_rollback_completo_e_desfazivel(self, tmp_path: Path) -> None:
        depot, reg = _mk_depot(tmp_path)
        depot.instalar(nome="util.demo", codigo=CODE_DEMO, versao="1.0.0")
        depot.instalar(nome="util.demo", codigo=CODE_V2, versao="1.1.0")

        r = depot.rollback("util.demo")
        assert r["ok"] is True
        assert (r["de"], r["para"]) == ("1.1.0", "1.0.0")
        assert depot.obter("util.demo").versao == "1.0.0"
        action = reg.get("util.demo")
        assert getattr(action, "version", "") == "1.0.0"
        # a 1.1.0 vira histórico: rollback pode ser desfeito
        assert depot.obter("util.demo").anteriores[-1]["versao"] == "1.1.0"


# ===========================================================================
# 11. auxiliares internas (386, 507, 651, 720, 739)
# ===========================================================================

class TestAuxiliaresInternas:
    @pytest.mark.parametrize("valor, esperado", [
        (None, None),
        ("abc", None),
        (123, 123.0),
        ("12.5", 12.5),
        (7, 7.0),
    ])
    def test_float_ou_none(self, valor: Any, esperado: float | None) -> None:
        assert _float_ou_none(valor) == esperado

    @pytest.mark.parametrize("codigo, funcao", [
        ("def (", "x"),          # sintaxe quebrada
        ("x = 5", "x"),          # não é chamável
        ("def x(): pass", "y"),  # função com outro nome
    ])
    def test_carregar_fn_devolve_none(self, codigo: str,
                                      funcao: str) -> None:
        assert _carregar_fn(codigo, funcao) is None

    def test_carregar_fn_devolve_funcao(self) -> None:
        fn = _carregar_fn(CODE_DEMO, "demo")
        assert callable(fn)
        assert fn() == {"ok": True, "result": "demo"}

    def test_snapshot_com_io_de_falha(self, tmp_path: Path,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
        alvo = tmp_path / "qualquer.json"
        alvo.write_text("{}", encoding="utf-8")

        def _explode(self, *args, **kwargs):
            raise OSError("disco em falha")

        monkeypatch.setattr(Path, "read_bytes", _explode)
        snap = SupplyDepot._snapshot_arquivos({alvo})
        assert snap == {alvo: None}

    def test_registro_valido_com_get_explosivo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        depot, reg = _mk_depot(tmp_path)

        def _explode(*args, **kwargs):
            raise RuntimeError("registry preso")

        monkeypatch.setattr(reg, "get", _explode)
        assert depot._registro_valido("util.x", "1.0.0") is False

    def test_registrar_quando_register_recusa(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """register False → desregistra o que havia e devolve False
        (nunca deixar o registry com ação velha presa)."""
        depot, reg = _mk_depot(tmp_path)
        depot.instalar(nome="util.demo", codigo=CODE_DEMO)
        entrada = depot.obter("util.demo")
        assert entrada is not None

        removidos: list[str] = []
        monkeypatch.setattr(reg, "register", lambda *a, **k: False)
        monkeypatch.setattr(reg, "has", lambda i: True)
        monkeypatch.setattr(reg, "unregister",
                            lambda i: removidos.append(i))
        fn = _carregar_fn(CODE_DEMO, "demo")
        assert depot._registrar(entrada, fn) is False
        # 1º unregister: tira a action velha antes de tentar registrar;
        # 2º: o registro foi recusado e a tentativa é desfeita (defesa)
        assert removidos == ["util.demo", "util.demo"]


# ===========================================================================
# 12. preflight — ramos puros restantes (432-467)
# ===========================================================================

def _ent(versao: str = "1.0.0", *, ativa: bool = True) -> Ferramenta:
    return Ferramenta(id="util.x", funcao="x", versao=versao, ativa=ativa)


_CASOS_PREFLIGHT: list[tuple[dict[str, Any], str, str]] = [
    ({"nome": "a..b"}, sd_mod.BLOQUEAR, "nome_invalido"),
    ({"codigo": "x" * 8001}, sd_mod.BLOQUEAR, "codigo_excede"),
    ({"espaco_livre": 0}, sd_mod.BLOQUEAR, "sem_espaco"),
    ({"ja_no_registry": True}, sd_mod.BLOQUEAR, "conflito"),
    ({"entrada": _ent(ativa=False)}, sd_mod.INSTALAR, "reativacao"),
    ({"entrada": _ent("1.0.0")}, sd_mod.SEM_ACAO, "ja_instalada"),
    ({"entrada": _ent("2.0.0"), "versao_nova": "1.0.0"}, sd_mod.BLOQUEAR,
     "downgrade_bloqueado"),
    ({"entrada": _ent("1.0.0"), "versao_nova": "2.0.0"}, sd_mod.BLOQUEAR,
     "major_requer_confirmacao"),
    ({"entrada": _ent("1.0.0"), "versao_nova": "2.0.0", "confirmar": True},
     sd_mod.ATUALIZAR, "atualizacao_disponivel"),
    ({"entrada": _ent("1.0.0"), "versao_nova": "1.1.0"}, sd_mod.ATUALIZAR,
     "atualizacao_disponivel"),
    ({}, sd_mod.INSTALAR, "instalar_nova"),
]


class TestPreflightSegundaLeva:
    @pytest.mark.parametrize("mods, acao, motivo", _CASOS_PREFLIGHT,
                             ids=[str(c[0])[:44] for c in _CASOS_PREFLIGHT])
    def test_ramos(self, mods: dict[str, Any], acao: str,
                   motivo: str) -> None:
        base: dict[str, Any] = {
            "nome": "util.x", "versao_nova": "1.0.0", "codigo": CODE_DEMO,
            "ja_no_registry": False, "entrada": None, "espaco_livre": 10**9,
        }
        base.update(mods)
        pre = sd_mod.preflight(**base)
        assert pre.acao == acao
        assert pre.motivo.startswith(motivo)


# ===========================================================================
# 13. instalar — bloqueios, rejeição e rollback em memória (770-884)
# ===========================================================================

class TestInstalarBordas:
    def test_downgrade_bloqueado(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util.demo", codigo=CODE_DEMO, versao="2.0.0")
        r = depot.instalar(nome="util.demo", codigo=CODE_DEMO, versao="1.0.0")
        assert r["ok"] is False
        assert r["acao"] == sd_mod.BLOQUEAR
        assert r["motivo"].startswith("downgrade_bloqueado")

    def test_mesma_versao_e_sem_acao(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util.demo", codigo=CODE_DEMO, versao="1.0.0")
        r = depot.instalar(nome="util.demo", codigo=CODE_DEMO, versao="1.0.0")
        assert r["ok"] is True
        assert r["acao"] == sd_mod.SEM_ACAO
        assert "ja_instalada" in r["motivo"]

    def test_codigo_rejeitado(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        r = depot.instalar(nome="util.x", codigo="import requests")
        assert r["ok"] is False
        assert r["acao"] == "rejeitado"

    def test_funcao_nao_encontrada(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        # código válido, mas define `demo` e o id pede `x`
        r = depot.instalar(nome="util.x", codigo=CODE_DEMO)
        assert r["ok"] is False
        assert r["acao"] == "rejeitado"
        assert r["motivo"].startswith("funcao_nao_encontrada")

    def test_update_com_falha_no_registro_rola_para_tras(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util.demo", codigo=CODE_DEMO, versao="1.0.0")
        monkeypatch.setattr(depot, "_registrar", lambda *a, **k: False)
        r = depot.instalar(nome="util.demo", codigo=CODE_V2, versao="1.1.0")
        assert r["ok"] is False
        assert r["rollback"] is True
        assert r["motivo"].startswith("rollback:")
        # estado pré-troca restaurado: versão, catálogo E arquivo em disco
        assert depot.obter("util.demo").versao == "1.0.0"
        arquivo = tmp_path / "ferramentas" / "util.demo.py"
        assert arquivo.read_text(encoding="utf-8") == CODE_DEMO

    def test_instala_nova_com_falha_some_com_o_arquivo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        depot, _ = _mk_depot(tmp_path)
        monkeypatch.setattr(depot, "_registrar", lambda *a, **k: False)
        r = depot.instalar(nome="util.y", codigo=CODE_Y)
        assert r["ok"] is False
        assert r["rollback"] is True
        assert depot.obter("util.y") is None
        assert not (tmp_path / "ferramentas" / "util.y.py").exists()


# ===========================================================================
# 14. rollback manual — guardas e falha no meio (898-953)
# ===========================================================================

class TestRollbackSegundaLeva:
    def test_ferramenta_inexistente(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        assert depot.rollback("util.nada") == {
            "ok": False, "motivo": "ferramenta_inexistente"}

    def test_sem_historico(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util.demo", codigo=CODE_DEMO)
        assert depot.rollback("util.demo") == {
            "ok": False, "motivo": "sem_historico_de_versoes"}

    def test_versao_nao_encontrada(self, tmp_path: Path) -> None:
        depot, _ = _hist(tmp_path)
        r = depot.rollback("util.demo", "9.9.9")
        assert r == {"ok": False, "motivo": "versao_nao_encontrada: 9.9.9"}

    def test_backup_apagado(self, tmp_path: Path) -> None:
        depot, nome_backup = _hist(tmp_path)
        (tmp_path / "ferramentas_backup" / nome_backup).unlink()
        r = depot.rollback("util.demo")
        assert r["ok"] is False
        assert r["motivo"].startswith("backup_ausente")

    def test_falha_no_registro_durante_rollback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        depot, _ = _hist(tmp_path)
        monkeypatch.setattr(depot, "_registrar", lambda *a, **k: False)
        r = depot.rollback("util.demo")
        assert r["ok"] is False
        assert r["rollback"] is True
        assert r["motivo"].startswith("rollback: registro_no_registry_falhou")
        # snapshot restaurado: continua na 1.1.0 (o rollback não aconteceu)
        assert depot.obter("util.demo").versao == "1.1.0"


# ===========================================================================
# 15. customizar — ramos restantes + remover completo (979-1040)
# ===========================================================================

class TestCustomizarSegundaLeva:
    def test_inexistente(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        assert depot.customizar("util.nada", descricao="x") == {
            "ok": False, "motivo": "ferramenta_inexistente"}

    def test_nada_para_alterar(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util.demo", codigo=CODE_DEMO)
        r = depot.customizar("util.demo")
        assert r == {"ok": False, "motivo": "nada_para_alterar"}

    def test_params_invalido(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util.demo", codigo=CODE_DEMO)
        r = depot.customizar("util.demo", params=["nao", "e", "dict"])
        assert r == {"ok": False, "motivo": "params_invalido"}

    def test_sucesso_com_permission_e_params(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util.demo", codigo=CODE_DEMO)
        r = depot.customizar("util.demo", descricao="Nova descrição",
                             params={"required": ["a"]},
                             permission="admin.ferramentas")
        assert r["ok"] is True
        assert r["ativa"] is True
        assert r["custom"]["descricao"] == "Nova descrição"
        entrada = depot.obter("util.demo")
        assert entrada.custom["params"] == {"required": ["a"]}
        assert entrada.custom["permission"] == "admin.ferramentas"

    def test_desinstalar_e_reativar(self, tmp_path: Path) -> None:
        depot, reg = _mk_depot(tmp_path)
        depot.instalar(nome="util.demo", codigo=CODE_DEMO)
        r = depot.customizar("util.demo", ativa=False)
        assert r["ok"] is True and r["ativa"] is False
        assert not reg.has("util.demo")
        # some do registry mas o CÓDIGO é preservado no backup
        backup = (tmp_path / "ferramentas_backup" /
                  "util.demo.removido.v1.0.0.py")
        assert backup.exists()
        assert depot.obter("util.demo").ativa is False

        r2 = depot.customizar("util.demo", ativa=True)
        assert r2["ok"] is True and r2["ativa"] is True
        assert reg.has("util.demo")


class TestRemover:
    def test_remover_completo(self, tmp_path: Path) -> None:
        depot, reg = _mk_depot(tmp_path)
        depot.instalar(nome="util.demo", codigo=CODE_DEMO)
        r = depot.remover("util.demo")
        assert r == {"ok": True, "removido": "util.demo"}
        assert depot.obter("util.demo") is None
        assert not reg.has("util.demo")
        backup = (tmp_path / "ferramentas_backup" /
                  "util.demo.removido.v1.0.0.py")
        assert backup.read_text(encoding="utf-8") == CODE_DEMO

    def test_remover_inexistente(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        assert depot.remover("util.nada") == {
            "ok": False, "motivo": "ferramenta_inexistente"}

    def test_remover_sem_codigo_em_disco(self, tmp_path: Path) -> None:
        depot, reg = _mk_depot(tmp_path)
        depot.instalar(nome="util.demo", codigo=CODE_DEMO)
        (tmp_path / "ferramentas" / "util.demo.py").unlink()
        r = depot.remover("util.demo")
        assert r["ok"] is True
        assert not reg.has("util.demo")
        assert not (tmp_path / "ferramentas_backup" /
                    "util.demo.removido.v1.0.0.py").exists()


# ===========================================================================
# 16. carregar no boot — sucesso, inativas e função ausente (1053-1071)
# ===========================================================================

class TestCarregarBoot:
    def test_boot_registra_ativas_e_pula_inativas(
        self, tmp_path: Path
    ) -> None:
        depot_a, _ = _mk_depot(tmp_path)
        depot_a.instalar(nome="util1.demo", codigo=CODE_DEMO)
        depot_a.instalar(nome="util.y", codigo=CODE_Y)
        depot_a.customizar("util.y", ativa=False)
        # boot de verdade: mesmo disco, registry VAZIO
        depot_b, _ = _mk_depot(tmp_path)
        r = depot_b.carregar()
        assert r == {"carregadas": 1, "erros": 0}
        assert depot_b._catalogo["util.y"].ativa is False

    def test_boot_com_funcao_ausente(self, tmp_path: Path) -> None:
        depot_a, _ = _mk_depot(tmp_path)
        depot_a.instalar(nome="util.y", codigo=CODE_Y)
        # o disco mudou depois do boot: arquivo define `demo`, não `y`
        (tmp_path / "ferramentas" / "util.y.py").write_text(
            CODE_DEMO, encoding="utf-8")
        depot_b, _ = _mk_depot(tmp_path)
        r = depot_b.carregar()
        assert r == {"carregadas": 0, "erros": 1}
        assert depot_b.ultimo_erro == "util.y: função ausente"


# ===========================================================================
# 17. visibilidade — listar/resumo/health/dump (1081-1110, 1948)
# ===========================================================================

class TestVisibilidade:
    def test_listar_com_flag_no_registry(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util1.demo", codigo=CODE_DEMO)
        depot.instalar(nome="util.y", codigo=CODE_Y)
        depot.customizar("util.y", ativa=False)
        itens = depot.listar()
        assert [i["id"] for i in itens] == ["util.y", "util1.demo"]
        assert itens[1]["no_registry"] is True
        assert itens[0]["no_registry"] is False

    def test_resumo(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util1.demo", codigo=CODE_DEMO, versao="1.0.0")
        depot.instalar(nome="util.y", codigo=CODE_Y, versao="1.0.0")
        depot.instalar(nome="util1.demo", codigo=CODE_V2, versao="1.1.0")
        res = depot.resumo()
        assert res["total"] == 2
        assert res["ativas"] == 2
        assert res["com_historico"] == 1
        assert sum(res["origens"].values()) == 2
        assert "ultimo_erro" in res

    def test_health_check_ok_e_quebrada(self, tmp_path: Path) -> None:
        depot, reg = _mk_depot(tmp_path)
        depot.instalar(nome="util1.demo", codigo=CODE_DEMO)
        depot.instalar(nome="util.y", codigo=CODE_Y)
        assert depot.health_check()["ok"] is True
        reg.unregister("util.y")  # action sumiu, catálogo continua
        r = depot.health_check()
        assert r["ok"] is False
        assert "1" in r["detail"]

    def test_dump(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util.y", codigo=CODE_Y)
        d = depot.dump()
        assert [i["id"] for i in d["ferramentas"]] == ["util.y"]
        assert d["resumo"]["total"] == 1


# ===========================================================================
# 18. versão do catálogo + env de histórico (269-275, 488-492)
# ===========================================================================

class TestVersaoEHistorico:
    @pytest.mark.parametrize("atual, esperado", [
        ("1.2.3", "1.2.4"),
        ("0.0.0", "0.0.1"),
        ("abc", "abc"),
        ("1.2", "1.2"),
        ("", ""),
    ])
    def test_proxima_versao(self, atual: str, esperado: str) -> None:
        assert sd_mod.proxima_versao(atual) == esperado

    @pytest.mark.parametrize("valor, esperado", [
        ("abc", sd_mod.MAX_HISTORICO),
        ("9999", sd_mod.MAX_HISTORICO_TETO),
        ("0", 0),
        ("7", 7),
    ])
    def test_max_historico_env(self, valor: str, esperado: int,
                               monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OD_SUPPLY_DEPOT_MAX_HISTORY", valor)
        assert sd_mod.max_historico() == esperado


# ===========================================================================
# 19. manifesto em memória + espaço injetado (564, 576-587)
# ===========================================================================

class TestCatalogoMemoria:
    def test_espaco_injetado(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path, espaco=555)
        assert depot._espaco() == 555

    def test_le_manifesto_existente(self, tmp_path: Path) -> None:
        depot_a, _ = _mk_depot(tmp_path)
        depot_a.instalar(nome="util.y", codigo=CODE_Y)
        depot_b, _ = _mk_depot(tmp_path)  # restart: mesmo manifesto
        entrada = depot_b.obter("util.y")
        assert entrada is not None
        assert entrada.funcao == "y"

    def test_manifesto_corrompido_vira_catalogo_vazio(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "ferramentas_catalogo.json").write_text(
            "{lixo", encoding="utf-8")
        depot, _ = _mk_depot(tmp_path)
        assert depot._catalogo == {}


# ===========================================================================
# 20. handler da action + template com limite mínimo (728-729, 1733)
# ===========================================================================

class TestHandlerETemplate:
    def test_handler_executa_e_devolve(self, tmp_path: Path) -> None:
        depot, reg = _mk_depot(tmp_path)
        depot.instalar(nome="util.demo", codigo=CODE_DEMO)
        action = reg.get("util.demo")
        assert action.handler() == {"ok": True, "result": "demo"}

    def test_template_com_max_codigo_minimo(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path, max_codigo=10)
        r = depot.gerar_codigo_de_template("calculadora_simples", "util.calc")
        assert r["ok"] is False
        assert r["motivo"].startswith("template_gera_codigo_invalido")


# ===========================================================================
# 21. export com item de histórico corrompido (1138)
# ===========================================================================

def test_export_ignora_historico_nao_dict(tmp_path: Path) -> None:
    depot, _ = _mk_depot(tmp_path)
    depot.instalar(nome="util.demo", codigo=CODE_DEMO, versao="1.0.0")
    depot.instalar(nome="util.demo", codigo=CODE_V2, versao="1.1.0")
    entrada = depot.obter("util.demo")
    assert entrada is not None
    entrada.anteriores.append(42)  # corrupção defensiva no manifesto
    bundle = depot.exportar()
    assert len(bundle["ferramentas"][0]["anteriores"]) == 1


# ===========================================================================
# 22. importar — item inativo + rollback no meio com 2 itens
#        (1414-1415, 1421, 1428-1429)
# ===========================================================================

class TestImportarInativaERollback:
    def test_mesclar_marca_inativa_e_desregistra(self, tmp_path: Path) -> None:
        depot, reg = _mk_depot(tmp_path)
        depot.instalar(nome="util1.demo", codigo=CODE_DEMO)
        r = depot.importar(_bundle(
            {"id": "util1.demo", "codigo": CODE_DEMO, "ativa": False}),
            modo="mesclar")
        assert r["ok"] is True
        entrada = depot.obter("util1.demo")
        assert entrada is not None and entrada.ativa is False
        assert not reg.has("util1.demo")

    def test_rollback_no_meio_com_dois_itens(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        depot, reg = _mk_depot(tmp_path)
        depot.instalar(nome="util1.demo", codigo=CODE_DEMO)
        depot.instalar(nome="util2.y", codigo=CODE_Y)
        # anomalia que este ramo defensivo existe para consertar:
        # no manifesto está INATIVA, mas a action ainda está no registry
        depot._catalogo["util2.y"].ativa = False

        real_register = reg.register
        chamadas = {"n": 0}

        def _register(action, *args, **kwargs):
            chamadas["n"] += 1
            if chamadas["n"] == 2:  # 2ª tentativa (util.z) é recusada
                return False
            return real_register(action, *args, **kwargs)

        monkeypatch.setattr(reg, "register", _register)

        r = depot.importar(_bundle(
            {"id": "util.y", "codigo": CODE_Y},   # 1ª: registra de verdade
            {"id": "util.z", "codigo": CODE_Z},   # 2ª: False → raise
        ), modo="mesclar")

        assert r["ok"] is False
        assert r["rollback"] is True
        assert r["motivo"].startswith("rollback: registro_no_registry_falhou")
        # catálogo de volta ao estado pré-importação
        assert depot.obter("util1.demo") is not None
        assert depot.obter("util.y") is None
        assert depot.obter("util.z") is None
        assert depot._catalogo["util2.y"].ativa is False  # anomalia restaurada
        # e o registry também: nada da importação ficou para trás
        assert not reg.has("util.y")
        assert not reg.has("util.z")
