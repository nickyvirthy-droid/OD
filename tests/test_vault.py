"""
OMEGA DRAKON • TESTS
Módulo: tests/test_vault.py
Descrição: Testes do cofre do sistema (integrations/vault.py) e das
            actions vault_* — sessão do bw cacheada e retentada, senha
            nunca em argv, lista sem segredos, fábrica LAZY (boot não
            depende do cofre) e catálogo de 4 actions com permissão.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - integrations/vault.py (VaultClient + client_padrao, criado em 17/10)
  - tools/actions/actions.py (vault_status/list/get/set, categoria "vault")
  - bw 2025.12.1 + Node 22 real (E2E 17/10: login + unlock + ciclo
    create/edit/delete + list — os 2026.x crasham no parse de cifras do
    Vaultwarden 1.36 com item no cofre)
"""

from __future__ import annotations

import base64
import json
import subprocess
import types
from typing import Any

import pytest

from core.security import SecurityManager
from integrations import vault as vault_mod
from integrations.vault import VaultClient, VaultError, client_padrao, resetar_cliente
from tools.actions import CATALOG, build_registry
from tools.actions.actions import vault_get, vault_list, vault_set, vault_status

MASTER = "m" * 44
SESSAO = "k" * 88
SERVIDOR = "https://vault.teste:8443"

ITEM_BRUTO = {
    "id": "id-1",
    "name": "OD Prova",
    "type": 1,
    "login": {
        "username": "user1",
        "password": "segredo-123",
        "uris": [{"uri": "https://exemplo.teste"}],
    },
    "notes": "nota-1",
    "revisionDate": "2026-10-17T00:00:00.000Z",
}


# ---------------------------------------------------------------------------
# Runner falso roteirizado por subcomando (FIFO por subcomando)
# ---------------------------------------------------------------------------

class FakeRunner:
    """Responde `bw <subcmd> ...` conforme roteiro; registra argv/input/env."""

    def __init__(self, roteiro: dict[str, Any]) -> None:
        self.roteiro = {
            chave: list(valor) if isinstance(valor, list) else [valor]
            for chave, valor in roteiro.items()
        }
        self.calls: list[dict[str, Any]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> types.SimpleNamespace:
        self.calls.append(
            {
                "argv": list(argv),
                "input": kwargs.get("input"),
                "env": kwargs.get("env") or {},
            }
        )
        subcmd = argv[1] if len(argv) > 1 else ""
        fila = self.roteiro.get(subcmd)
        if not fila:
            raise AssertionError(f"bw {subcmd!r} não roteirizado (argv={argv})")
        resposta = fila.pop(0) if len(fila) > 1 else fila[0]
        if isinstance(resposta, BaseException):
            raise resposta
        rc, out, err = resposta
        return types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)

    def argvs(self, subcmd: str) -> list[list[str]]:
        return [c["argv"] for c in self.calls if len(c["argv"]) > 1 and c["argv"][1] == subcmd]

    def n(self, subcmd: str) -> int:
        return len(self.argvs(subcmd))


def fazer_cliente(roteiro: dict[str, Any], *, alcanca: bool = True) -> VaultClient:
    return VaultClient(
        bw_bin="/home/alex/.local/bin/bw",
        servidor=SERVIDOR,
        email="od-sistema@omegadrakon.dev",
        master=MASTER,
        runner=FakeRunner(roteiro),
        pinger=lambda _s: alcanca,
    )


def decodifica_stdin(call: dict[str, Any]) -> dict[str, Any]:
    bruto = base64.b64decode((call["input"] or "").strip().encode("ascii"))
    return json.loads(bruto.decode("utf-8"))


OK_CONFIG = (0, "", "")
OK_UNLOCK = (0, SESSAO + "\n", "")


# ===========================================================================
# VaultClient — sessão, erros tipados, operações
# ===========================================================================

class TestVaultClientSessao:
    """Destrava UMA vez, cacheia em memória, renova só quando expira."""

    def test_destrava_uma_vez_e_reusa_sessao(self) -> None:
        cli = fazer_cliente({
            "config": OK_CONFIG,
            "unlock": OK_UNLOCK,
            "list": (0, json.dumps([ITEM_BRUTO]), ""),
        })
        assert len(cli.listar()) == 1
        assert len(cli.listar()) == 1
        assert cli._runner.n("unlock") == 1
        assert cli._runner.n("config") == 1
        assert cli._runner.n("list") == 2

    def test_sessao_expirada_destrava_e_repete_uma_vez(self) -> None:
        cli = fazer_cliente({
            "config": OK_CONFIG,
            "unlock": OK_UNLOCK,
            "list": [
                (1, "", "Session expired."),
                (0, json.dumps([ITEM_BRUTO]), ""),
            ],
        })
        assert len(cli.listar()) == 1
        assert cli._runner.n("unlock") == 2  # destravou de novo, UMA vez

    def test_sessao_morta_persistente_vira_erro_honesto(self) -> None:
        cli = fazer_cliente({
            "config": OK_CONFIG,
            "unlock": OK_UNLOCK,
            "list": [(1, "", "Session expired."), (1, "", "Session expired.")],
        })
        with pytest.raises(VaultError) as exc:
            cli.listar()
        assert exc.value.codigo == "sessao_expirada"
        assert cli._runner.n("unlock") == 2  # nunca entra em loop

    def test_master_errada_e_tipada(self) -> None:
        cli = fazer_cliente({
            "config": OK_CONFIG,
            "unlock": (1, "", "Invalid master password."),
        })
        with pytest.raises(VaultError) as exc:
            cli.listar()
        assert exc.value.codigo == "vault_master_invalida"

    def test_bw_ausente_e_tipado(self) -> None:
        cli = fazer_cliente({
            "config": OK_CONFIG,
            "unlock": FileNotFoundError(2, "No such file"),
        })
        with pytest.raises(VaultError) as exc:
            cli.listar()
        assert exc.value.codigo == "bw_ausente"
        assert "OD_BW_BIN" in exc.value.mensagem

    def test_timeout_e_tipado(self) -> None:
        cli = fazer_cliente({
            "config": OK_CONFIG,
            "unlock": subprocess.TimeoutExpired(cmd=["bw"], timeout=30),
        })
        with pytest.raises(VaultError) as exc:
            cli.listar()
        assert exc.value.codigo == "vault_timeout"

    def test_rede_cauida_na_unlock_e_tipada(self) -> None:
        cli = fazer_cliente({
            "config": OK_CONFIG,
            "unlock": (1, "", "Unable to fetch ServerConfig: getaddrinfo failed"),
        })
        with pytest.raises(VaultError) as exc:
            cli.listar()
        assert exc.value.codigo == "vault_indisponivel"

    def test_config_server_aponta_para_od_vault_server(self) -> None:
        cli = fazer_cliente({
            "config": OK_CONFIG,
            "unlock": OK_UNLOCK,
            "list": (0, "[]", ""),
        })
        cli.listar()
        config = cli._runner.argvs("config")
        assert config[0][-1] == SERVIDOR

    def test_master_nunca_aparece_em_argv(self) -> None:
        cli = fazer_cliente({
            "config": OK_CONFIG,
            "unlock": OK_UNLOCK,
            "list": (0, json.dumps([ITEM_BRUTO]), ""),
            "get": (0, json.dumps(ITEM_BRUTO), ""),
            "create": (0, json.dumps({"id": "id-9"}), ""),
        })
        cli.listar()
        cli.obter("OD Prova")
        cli.guardar("novo", "senha-em-stdin", username="u")
        tudo = " ".join(" ".join(c["argv"]) for c in cli._runner.calls)
        assert MASTER not in tudo
        assert "senha-em-stdin" not in tudo


class TestVaultClientOperacoes:
    """listar/obter/guardar/apagar/status — contrato honesto e sem vazamento."""

    def test_listar_devolve_apenas_id_nome_tipo(self) -> None:
        cli = fazer_cliente({"config": OK_CONFIG, "unlock": OK_UNLOCK,
                             "list": (0, json.dumps([ITEM_BRUTO]), "")})
        itens = cli.listar()
        assert itens == [{"id": "id-1", "nome": "OD Prova", "tipo": 1}]
        assert "password" not in itens[0]
        assert "segredo-123" not in json.dumps(itens)

    def test_listar_saidas_nao_json_vira_bw_falhou(self) -> None:
        cli = fazer_cliente({"config": OK_CONFIG, "unlock": OK_UNLOCK,
                             "list": (0, "lixo", "")})
        with pytest.raises(VaultError) as exc:
            cli.listar()
        assert exc.value.codigo == "bw_falhou"

    def test_obter_case_insensitive_devolve_o_segredo(self) -> None:
        cli = fazer_cliente({
            "config": OK_CONFIG, "unlock": OK_UNLOCK,
            "list": (0, json.dumps([ITEM_BRUTO]), ""),
            "get": (0, json.dumps(ITEM_BRUTO), ""),
        })
        item = cli.obter("od prova")
        assert item["password"] == "segredo-123"
        assert item["username"] == "user1"
        assert item["nota"] == "nota-1"
        assert item["uris"] == ["https://exemplo.teste"]
        assert cli._runner.argvs("get")[0][-1] == "id-1"

    def test_obter_inexistente_e_tipado(self) -> None:
        cli = fazer_cliente({"config": OK_CONFIG, "unlock": OK_UNLOCK,
                             "list": (0, json.dumps([ITEM_BRUTO]), "")})
        with pytest.raises(VaultError) as exc:
            cli.obter("outra-coisa")
        assert exc.value.codigo == "item_nao_encontrado"

    def test_guardar_cria_via_stdin_base64(self) -> None:
        cli = fazer_cliente({
            "config": OK_CONFIG, "unlock": OK_UNLOCK,
            "list": (0, "[]", ""),
            "create": (0, json.dumps({"id": "id-novo"}), ""),
        })
        resultado = cli.guardar("Segredo Novo", "s3nh4", username="u", nota="n")
        assert resultado == {"id": "id-novo", "nome": "Segredo Novo", "criado": True}
        cria = cli._runner.calls[-1]
        assert cria["argv"][1] == "create"
        doc = decodifica_stdin(cria)
        assert doc["type"] == 1
        assert doc["login"]["password"] == "s3nh4"
        assert "s3nh4" not in " ".join(cria["argv"])

    def test_guardar_atualiza_preserva_campos_nao_informados(self) -> None:
        cli = fazer_cliente({
            "config": OK_CONFIG, "unlock": OK_UNLOCK,
            "list": (0, json.dumps([ITEM_BRUTO]), ""),
            "get": (0, json.dumps(ITEM_BRUTO), ""),
            "edit": (0, json.dumps(ITEM_BRUTO), ""),
        })
        resultado = cli.guardar("od prova", "pw-nova")
        assert resultado["criado"] is False
        assert resultado["id"] == "id-1"
        edicao = [c for c in cli._runner.calls if c["argv"][1] == "edit"][0]
        doc = decodifica_stdin(edicao)
        assert doc["login"]["password"] == "pw-nova"
        assert doc["login"]["username"] == "user1"  # preservado (username="") 
        assert doc["notes"] == "nota-1"  # preservado (nota="")
        assert edicao["argv"][-1] == "id-1"

    def test_guardar_campos_vazios_sao_recusados(self) -> None:
        cli = fazer_cliente({})
        with pytest.raises(VaultError) as exc1:
            cli.guardar("", "x")
        with pytest.raises(VaultError) as exc2:
            cli.guardar("nome", "")
        assert exc1.value.codigo == exc2.value.codigo == "item_invalido"
        assert cli._runner.calls == []  # nada rodou

    def test_apagar_e_apagar_inexistente(self) -> None:
        cli = fazer_cliente({
            "config": OK_CONFIG, "unlock": OK_UNLOCK,
            "list": (0, json.dumps([ITEM_BRUTO]), ""),
            "delete": (0, "", ""),
        })
        assert cli.apagar("od prova") == {"nome": "od prova", "apagado": True}
        assert cli._runner.argvs("delete")[0][-1] == "id-1"
        with pytest.raises(VaultError) as exc:
            cli.apagar("nao-existe")
        assert exc.value.codigo == "item_nao_encontrado"

    def test_status_com_e_sem_rede(self) -> None:
        bruto = json.dumps({"serverUrl": SERVIDOR, "status": "unlocked",
                            "userEmail": "od-sistema@omegadrakon.dev"})
        com_rede = fazer_cliente({"status": (0, bruto, "")}, alcanca=True)
        assert com_rede.status() == {
            "servidor": SERVIDOR,
            "estado": "unlocked",
            "email": "od-sistema@omegadrakon.dev",
            "alcanca": True,
        }
        sem_rede = fazer_cliente({"status": (0, bruto, "")}, alcanca=False)
        assert sem_rede.status()["alcanca"] is False

    def test_status_falha_e_bw_falhou(self) -> None:
        cli = fazer_cliente({"status": (1, "", "boom")})
        with pytest.raises(VaultError) as exc:
            cli.status()
        assert exc.value.codigo == "bw_falhou"


# ===========================================================================
# Fábrica LAZY — boot não depende do cofre
# ===========================================================================

@pytest.fixture(autouse=True)
def _sempre_limpo():
    resetar_cliente()
    yield
    resetar_cliente()


class TestFabricaLazy:
    def test_sem_config_retorna_none(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(vault_mod, "_ENV_PATH", tmp_path / ".env")
        for chave in ("OD_VAULT_SERVER", "OD_VAULT_EMAIL", "OD_VAULT_MASTER", "OD_BW_BIN"):
            monkeypatch.delenv(chave, raising=False)
        assert client_padrao() is None  # ação degrada, boot segue

    def test_com_config_cria_e_cacheia(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(vault_mod, "_ENV_PATH", tmp_path / ".env")
        monkeypatch.setenv("OD_VAULT_SERVER", SERVIDOR)
        monkeypatch.setenv("OD_VAULT_EMAIL", "od-sistema@omegadrakon.dev")
        monkeypatch.setenv("OD_VAULT_MASTER", MASTER)
        monkeypatch.setenv("OD_BW_BIN", "/x/bw")
        primeiro = client_padrao()
        assert isinstance(primeiro, VaultClient)
        assert primeiro.servidor == SERVIDOR
        assert client_padrao() is primeiro  # mesma sessão por processo

    def test_env_de_os_environ_lidera_sobre_env_file(self, tmp_path, monkeypatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("OD_X=do_arquivo\n", encoding="utf-8")
        monkeypatch.setattr(vault_mod, "_ENV_PATH", env_file)
        monkeypatch.setenv("OD_X", "do_processo")
        assert vault_mod._env("OD_X") == "do_processo"
        monkeypatch.delenv("OD_X")
        assert vault_mod._env("OD_X") == "do_arquivo"
        assert vault_mod._env("OD_NAO_EXISTE", "padrao") == "padrao"


# ===========================================================================
# Actions vault_* — contrato de saída e mapeamento de erro
# ===========================================================================

class _CofreFalso:
    def __init__(self) -> None:
        self.listado = [{"id": "id-1", "nome": "OD Prova", "tipo": 1}]

    def status(self) -> dict[str, Any]:
        return {"servidor": SERVIDOR, "estado": "unlocked",
                "email": "od-sistema@omegadrakon.dev", "alcanca": True}

    def listar(self) -> list[dict[str, Any]]:
        return list(self.listado)

    def obter(self, nome: str) -> dict[str, Any]:
        if nome != "OD Prova":
            raise VaultError("item_nao_encontrado", f"Item '{nome}' não está no cofre.")
        return {"id": "id-1", "nome": nome, "tipo": 1, "username": "u",
                "password": "s3gr3d0", "nota": "", "uris": [],
                "atualizado_em": ""}

    def guardar(self, nome: str, password: str, *, username: str = "",
                nota: str = "") -> dict[str, Any]:
        if not nome or not password:
            raise VaultError("item_invalido", "nome e password são obrigatórios.")
        return {"id": "id-2", "nome": nome, "criado": True}


def _com_fabrica(cliente: Any, monkeypatch) -> None:
    monkeypatch.setattr(vault_mod, "client_padrao", lambda: cliente)


class TestActionsVault:
    def test_status_ok(self, monkeypatch) -> None:
        _com_fabrica(_CofreFalso(), monkeypatch)
        r = vault_status()
        assert r["ok"] is True and r["estado"] == "unlocked" and r["alcanca"] is True

    def test_list_ok_sem_segredos(self, monkeypatch) -> None:
        _com_fabrica(_CofreFalso(), monkeypatch)
        r = vault_list()
        assert r["ok"] is True and r["total"] == 1
        assert r["itens"][0] == {"id": "id-1", "nome": "OD Prova", "tipo": 1}

    def test_get_ok_e_erro_mapeado(self, monkeypatch) -> None:
        _com_fabrica(_CofreFalso(), monkeypatch)
        ok = vault_get(name="OD Prova")
        assert ok["ok"] is True and ok["item"]["password"] == "s3gr3d0"
        falha = vault_get(name="outra")
        assert falha["ok"] is False
        assert falha["error"] == "item_nao_encontrado"
        assert "outra" in falha["message"]

    def test_set_ok_e_validacao(self, monkeypatch) -> None:
        _com_fabrica(_CofreFalso(), monkeypatch)
        ok = vault_set(name="Novo", password="p")
        assert ok["ok"] is True and ok["criado"] is True
        falha = vault_set(name="", password="p")
        assert falha["ok"] is False and falha["error"] == "item_invalido"

    @pytest.mark.parametrize("acao,kwargs", [
        (vault_status, {}),
        (vault_list, {}),
        (vault_get, {"name": "x"}),
        (vault_set, {"name": "x", "password": "y"}),
    ])
    def test_nao_configurado_degrada_a_action(self, acao, kwargs, monkeypatch) -> None:
        _com_fabrica(None, monkeypatch)
        r = acao(**kwargs)
        assert r["ok"] is False
        assert r["error"] == "vault_nao_configurado"
        assert "OD_VAULT_MASTER" in r["message"]


# ===========================================================================
# Catálogo — 4 actions, categoria vault, permissão
# ===========================================================================

VAULT_ACOES = {"vault_status", "vault_list", "vault_get", "vault_set"}


class TestCatalogoVault:
    def test_quatro_actions_na_categoria_vault(self) -> None:
        do_cofo = [s for s in CATALOG if s["category"] == "vault"]
        assert {s["name"] for s in do_cofo} == VAULT_ACOES
        assert len(do_cofo) == 4

    def test_schemas_exigem_nome_e_senha(self) -> None:
        por_nome = {s["name"]: s for s in CATALOG}
        assert por_nome["vault_get"]["params"].get("required") == ["name"]
        assert por_nome["vault_set"]["params"].get("required") == ["name", "password"]
        assert por_nome["vault_status"]["params"] == {}
        assert por_nome["vault_list"]["params"] == {}

    @pytest.mark.asyncio
    async def test_papel_user_negado_por_permissao(self) -> None:
        """Cofre é do admin: papel comum não alcança (nem lê, nem escreve)."""
        registry = build_registry(security=SecurityManager(mode="strict"))
        params = {
            "vault_status": {},
            "vault_list": {},
            "vault_get": {"name": "x"},
            "vault_set": {"name": "x", "password": "y"},
        }
        for nome in sorted(VAULT_ACOES):
            result = await registry.execute(nome, params=params[nome], role="user")
            assert result.status == "denied", nome
            assert result.denied_by == "permission", nome


__all__ = [
    "TestVaultClientSessao",
    "TestVaultClientOperacoes",
    "TestFabricaLazy",
    "TestActionsVault",
    "TestCatalogoVault",
]
