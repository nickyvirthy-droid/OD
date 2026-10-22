"""
OMEGA DRAKON • TESTES
tests/test_vault_env_mirror.py — espelho do .env para o cofre.

O espelho já gravou DESCRICÕES no campo de senha (allowlist CREDENCIAIS
confundida com valores do .env — causa raiz do "erro: admin_token com
senha = descrição" reportado pelo dono em 22/10). Estes testes prendem
o contrato: o que vai pro campo senha é SEMPRE o valor lido do .env;
a descrição da allowlist vive só na nota; a verificação compara contra
o .env (nunca contra a própria descrição).

Rode: pytest tests/test_vault_env_mirror.py
"""

from __future__ import annotations

from typing import Any

import vault_env_mirror as espelho


class FakeCliente:
    """Cliente de mentira: guarda em dict e responde obter/listar."""

    def __init__(self, itens: dict[str, str] | None = None) -> None:
        self.itens: dict[str, str] = dict(itens or {})
        self.guardados: list[dict[str, Any]] = []

    def guardar(
        self,
        nome: str,
        password: str,
        *,
        username: str = "",
        nota: str = "",
        uris: Any = None,
    ) -> dict[str, Any]:
        self.guardados.append(
            {"nome": nome, "password": password, "username": username, "nota": nota}
        )
        self.itens[nome] = password
        return {"id": "x", "nome": nome, "criado": nome not in self.itens}

    def obter(self, nome: str) -> dict[str, Any]:
        if nome not in self.itens:
            raise espelho.VaultError("item_nao_encontrado", nome)
        return {"password": self.itens[nome]}

    def listar(self) -> list[dict[str, Any]]:
        return [{"id": "x", "nome": n, "tipo": 1} for n in sorted(self.itens)]


def _env(tmp_path, conteudo: str):
    arquivo = tmp_path / ".env"
    arquivo.write_text(conteudo, encoding="utf-8")
    return arquivo


def _prepara(tmp_path, monkeypatch, env: str, credenciais: dict[str, str],
             itens: dict[str, str] | None = None) -> FakeCliente:
    _env(tmp_path, env)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(espelho, "CREDENCIAIS", dict(credenciais))
    cliente = FakeCliente(itens)
    monkeypatch.setattr(espelho, "client_padrao", lambda: cliente)
    return cliente


class TestEspelhoGravaValorDoEnv:
    def test_senha_e_o_valor_do_env_e_nao_a_descricao(self, tmp_path, monkeypatch,
                                                      capsys) -> None:
        """REGRESSÃO do bug 22/10: guardar recebe o .env, não a allowlist."""
        cliente = _prepara(
            tmp_path,
            monkeypatch,
            "SEGREDO_DEMO=valor-real-do-env\n",
            {"SEGREDO_DEMO": "descricao caprichada da chave."},
        )
        rc = espelho.main([])
        assert rc == 0, capsys.readouterr().out
        assert cliente.guardados, "nada foi gravado"
        assert cliente.guardados[0]["password"] == "valor-real-do-env"
        assert cliente.guardados[0]["password"] != "descricao caprichada da chave."

    def test_descricao_vive_na_nota(self, tmp_path, monkeypatch, capsys) -> None:
        cliente = _prepara(
            tmp_path,
            monkeypatch,
            "SEGREDO_DEMO=valor-real-do-env\n",
            {"SEGREDO_DEMO": "descricao caprichada da chave."},
        )
        rc = espelho.main([])
        assert rc == 0, capsys.readouterr().out
        nota = cliente.guardados[0]["nota"]
        assert "descricao caprichada da chave." in nota

    def test_verificacao_compara_contra_o_env(self, tmp_path, monkeypatch,
                                              capsys) -> None:
        """Cofre com descrição != .env com valor → DIVERGENTE (rc 1)."""
        _prepara(
            tmp_path,
            monkeypatch,
            "SEGREDO_DEMO=valor-real-do-env\n",
            {"SEGREDO_DEMO": "descricao caprichada da chave."},
            itens={"SEGREDO_DEMO": "descricao caprichada da chave."},
        )
        rc = espelho.main(["--check"])
        assert rc == 1, capsys.readouterr().out
        assert "DIVERGENTE" in capsys.readouterr().out

    def test_check_confere_quando_cofre_tem_o_valor(self, tmp_path, monkeypatch,
                                                    capsys) -> None:
        _prepara(
            tmp_path,
            monkeypatch,
            "SEGREDO_DEMO=valor-real-do-env\n",
            {"SEGREDO_DEMO": "descricao caprichada da chave."},
            itens={"SEGREDO_DEMO": "valor-real-do-env"},
        )
        rc = espelho.main(["--check"])
        assert rc == 0, capsys.readouterr().out


class TestEspelhoApoios:
    def test_username_vem_de_outra_chave_do_env(self, tmp_path, monkeypatch,
                                                capsys) -> None:
        cliente = _prepara(
            tmp_path,
            monkeypatch,
            "OD_MQTT_PASSWORD=pw-mqtt\nOD_MQTT_USERNAME=usuario-mqtt\n",
            {"OD_MQTT_PASSWORD": "senha do broker MQTT."},
        )
        monkeypatch.setattr(espelho, "USERNAME_DE", {"OD_MQTT_PASSWORD": "OD_MQTT_USERNAME"})
        rc = espelho.main([])
        assert rc == 0, capsys.readouterr().out
        assert cliente.guardados[0]["username"] == "usuario-mqtt"

    def test_chave_secret_fora_da_allowlist_gera_aviso(self, tmp_path, monkeypatch,
                                                       capsys) -> None:
        _prepara(
            tmp_path,
            monkeypatch,
            "SEGREDO_DEMO=valor\nNOVA_CHAVE_API_KEY=outra\n",
            {"SEGREDO_DEMO": "descricao."},
            itens={"SEGREDO_DEMO": "valor"},
        )
        rc = espelho.main(["--check"])
        saida = capsys.readouterr().out
        assert "NOVA_CHAVE_API_KEY" in saida and "allowlist" in saida
        assert rc == 0  # aviso não derruba a rodada

    def test_chave_da_allowlist_ausente_no_env_avisa(self, tmp_path, monkeypatch,
                                                     capsys) -> None:
        _prepara(tmp_path, monkeypatch, "SEGREDO_DEMO=valor\n",
                 {"SEGREDO_DEMO": "d.", "CHAVE_QUE_FALTA": "d2."})
        rc = espelho.main(["--check"])
        assert "CHAVE_QUE_FALTA" in capsys.readouterr().out


__all__ = [
    "TestEspelhoGravaValorDoEnv",
    "TestEspelhoApoios",
]
