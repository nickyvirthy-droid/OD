"""
OMEGA DRAKON • TESTES
Módulo: tests/test_supply_depot.py
Descrição: Parte F do Project NOMAD — Supply Depot (registro de
           ferramentas/skills do orquestrador). Cobre as três peças do
           catálogo do Nômade: pré-voo PURO (conflito, versão, tamanho),
           instalação atômica com ROLLBACK automático na falha, rollback
           manual por versão (síndico: pode ser desfeito), customização
           do dono que SOBREVIVE a atualização/restart, restauração no
           boot (ferramenta gerada não some mais), integração com o
           /gerar do Auto Extension (pré-voa antes de gastar LLM) e as
           5 rotas /admin/ferramentas + seção do painel + stats.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any, Optional

import pytest

from tools.auto_extension import AutoExtension
from tools.registry import ActionRegistry
from tools.supply_depot import (
    ATUALIZAR,
    BLOQUEAR,
    INSTALAR,
    LIMITE_CODIGO,
    SEM_ACAO,
    Ferramenta,
    SupplyDepot,
    normalizar_nome,
    preflight,
    proxima_versao,
)

# --- Fixtures de código (mesma fonte do auto_extension: validado antes) ------

CODE_V1 = '''
def soma(**params):
    a = params.get("a", 0)
    b = params.get("b", 0)
    return {"ok": True, "result": a + b}
'''

CODE_V2 = '''
def soma(**params):
    a = params.get("a", 0)
    b = params.get("b", 0)
    return {"ok": True, "result": a - b}
'''

CODE_MULT = '''
def multiplica(**params):
    a = params.get("a", 1)
    b = params.get("b", 1)
    return {"ok": True, "result": a * b}
'''

CODE_DANCA = '''
def danca(**params):
    return {"ok": True, "result": "passo"}
'''

CODE_DANCA_FENCE = '''```python
def danca(**params):
    return {"ok": True, "result": "passo"}
```'''

CODE_IMPORT_PROIBIDO = '''
import requests

def pegar(**params):
    return {"ok": True, "result": requests.get("http://x")}
'''

CODE_FUNCAO_ERRADA = '''
def outra(**params):
    return {"ok": True, "result": "?"}
'''


def _mk_depot(
    tmp_path: Path,
    *,
    registry: Optional[ActionRegistry] = None,
    espaco: Optional[int] = None,
) -> tuple[SupplyDepot, ActionRegistry]:
    """Depot real em tmp (relógio fixo; disco real salvo `espaco` inject)."""
    reg = registry if registry is not None else ActionRegistry()
    depot = SupplyDepot(
        registry=reg,
        catalogo_path=tmp_path / "ferramentas_catalogo.json",
        codigos_dir=tmp_path / "ferramentas",
        backup_dir=tmp_path / "ferramentas_backup",
        raiz=tmp_path,
        espaco_livre_fn=(lambda _p: espaco) if espaco is not None else None,
        clock=lambda: 1_700_000_000.0,
    )
    return depot, reg


def _entrada(versao: str = "1.0.0", *, ativa: bool = True,
             id_: str = "util.ferramenta") -> Ferramenta:
    return Ferramenta(id=id_, funcao=id_.rsplit(".", 1)[-1], versao=versao,
                      ativa=ativa)


# ===========================================================================
# 1. Pré-voo puro (função imutável — sem I/O, mesmo espírito do avaliar())
# ===========================================================================

class TestPreflight:
    """Tabela de ramificações: conflito × versão × tamanho, nesta ordem."""

    def _pf(self, **kw: Any):
        base: dict[str, Any] = dict(
            nome="util.ferramenta", versao_nova="1.0.0", codigo=CODE_V1,
            ja_no_registry=False, entrada=None, espaco_livre=10_000_000,
        )
        base.update(kw)
        return preflight(**base)

    # -- Nome ---------------------------------------------------------------

    def test_nova_ferramenta_instala(self) -> None:
        pre = self._pf()
        assert pre.acao == INSTALAR
        assert "instalar_nova" in pre.motivo and pre.conflito == ""

    def test_nome_vazio_bloqueia(self) -> None:
        pre = self._pf(nome="")
        assert pre.acao == BLOQUEAR and "nome_invalido" in pre.motivo

    def test_nome_hostil_nao_vira_path(self) -> None:
        # "../.." normalizado vira ".._.._..." — não casa o padrão de id
        # (precisa começar com letra/número/_) → bloqueado. Nenhum ponto
        # de corte vira caminho de arquivo fora de data/ferramentas/.
        pre = self._pf(nome="../../etc/passwd")
        assert pre.acao == BLOQUEAR and "nome_invalido" in pre.motivo

    def test_nome_com_espaco_normaliza_e_passa(self) -> None:
        pre = self._pf(nome="Minha Ferramenta")
        assert pre.acao == INSTALAR
        assert normalizar_nome("Minha Ferramenta!") == "minha_ferramenta_"

    # -- Tamanho -------------------------------------------------------------

    def test_codigo_acima_do_limite_bloqueia(self) -> None:
        pre = self._pf(codigo="x" * (LIMITE_CODIGO + 1))
        assert pre.acao == BLOQUEAR
        assert f"codigo_excede_{LIMITE_CODIGO}" in pre.motivo

    def test_codigo_no_limite_passa(self) -> None:
        # exatamente no limite é aceito (só acima é barrado)
        codigo = "x" * LIMITE_CODIGO
        pre = self._pf(codigo=codigo, espaco_livre=10_000_000)
        assert pre.acao == INSTALAR

    def test_sem_espaco_em_disco_bloqueia(self) -> None:
        pre = self._pf(espaco_livre=0)
        assert pre.acao == BLOQUEAR and "sem_espaco" in pre.motivo

    def test_margem_de_disco_10_por_cento(self) -> None:
        # bytes × 1,1 (MESMA margem da Parte E): na margem+1 passa,
        # um byte abaixo do necessário bloqueia.
        bytes_codigo = len(CODE_V1.encode())
        justo = int(bytes_codigo * 1.1)
        assert self._pf(espaco_livre=justo + 1).acao == INSTALAR
        assert self._pf(espaco_livre=justo - 1).acao == BLOQUEAR

    # -- Conflito ------------------------------------------------------------

    def test_no_registry_fora_do_depot_e_conflito(self) -> None:
        pre = self._pf(ja_no_registry=True, entrada=None)
        assert pre.acao == BLOQUEAR
        assert pre.conflito == "action_alheia"
        assert "já existe no registry" in pre.motivo

    def test_no_registry_e_do_depot_segue_para_versao(self) -> None:
        pre = self._pf(ja_no_registry=True, entrada=_entrada())
        assert pre.acao == SEM_ACAO  # mesma versão → só confirma

    # -- Versão ---------------------------------------------------------------

    def test_mesma_versao_e_sem_acao(self) -> None:
        pre = self._pf(entrada=_entrada("1.0.0"), versao_nova="1.0.0")
        assert pre.acao == SEM_ACAO and "ja_instalada" in pre.motivo

    def test_downgrade_bloqueado(self) -> None:
        pre = self._pf(entrada=_entrada("1.2.0"), versao_nova="1.1.9")
        assert pre.acao == BLOQUEAR and "downgrade_bloqueado" in pre.motivo

    def test_major_sem_confirmacao_bloqueia(self) -> None:
        pre = self._pf(entrada=_entrada("0.9.0"), versao_nova="1.0.0")
        assert pre.acao == BLOQUEAR
        assert "major_requer_confirmacao" in pre.motivo

    def test_major_com_confirmacao_atualiza(self) -> None:
        pre = self._pf(entrada=_entrada("0.9.0"), versao_nova="1.0.0",
                       confirmar=True)
        assert pre.acao == ATUALIZAR

    def test_minor_e_patch_atualizam_sem_confirmacao(self) -> None:
        assert self._pf(entrada=_entrada("1.0.0"),
                        versao_nova="1.1.0").acao == ATUALIZAR
        assert self._pf(entrada=_entrada("1.0.0"),
                        versao_nova="1.0.1").acao == ATUALIZAR

    def test_versao_nao_semver_nao_tem_bloqueio(self) -> None:
        # hash/label não é semver: downgrade e major não existem —
        # a atualização segue (o dono pediu).
        pre = self._pf(entrada=_entrada("build-42"), versao_nova="build-43")
        assert pre.acao == ATUALIZAR

    def test_reativacao_com_mesma_versao_instala(self) -> None:
        # ferramenta desinstalada (ativa=False) com a MESMA versão não é
        # "já instalada" — é reativação (precisa re-sair pro registry).
        pre = self._pf(entrada=_entrada("1.0.0", ativa=False),
                       versao_nova="1.0.0")
        assert pre.acao == INSTALAR and "reativacao" in pre.motivo

    # -- Formato ---------------------------------------------------------------

    def test_bytes_do_codigo_no_resultado(self) -> None:
        pre = self._pf()
        assert pre.bytes == len(CODE_V1.encode())

    def test_para_dict_com_os_quatro_campos(self) -> None:
        d = self._pf().para_dict()
        assert set(d) == {"acao", "motivo", "conflito", "bytes"}
        assert d["acao"] == INSTALAR and d["motivo"]


class TestNomeEVersao:
    def test_normalizar_regra_do_auto_extension(self) -> None:
        assert normalizar_nome("  Olá Mundo!! ") == "ol__mundo__"
        assert normalizar_nome("auto.calcular_imc") == "auto.calcular_imc"
        assert normalizar_nome("") == ""

    def test_proxima_versao_bump_de_patch(self) -> None:
        assert proxima_versao("1.2.3") == "1.2.4"
        assert proxima_versao("0.0.9") == "0.0.10"

    def test_proxima_versao_nao_semver_fica_igual(self) -> None:
        assert proxima_versao("build-42") == "build-42"
        assert proxima_versao("") == ""


# ===========================================================================
# 2. Instalação (pré-voo + validação + disco + registry)
# ===========================================================================

class TestInstalacao:
    def test_instala_grava_tudo_e_executa(self, tmp_path: Path) -> None:
        depot, reg = _mk_depot(tmp_path)
        r = depot.instalar(
            nome="util.soma", codigo=CODE_V1, versao="1.0.0",
            descricao="soma a+b", categoria="util", permission="util.soma",
            params={"required": ["a"], "properties": {}},
        )
        assert r["ok"] and r["acao"] == INSTALAR
        assert r["id"] == "util.soma" and r["versao"] == "1.0.0"
        # action viva e executável no registry
        action = reg.get("util.soma")
        assert action.version == "1.0.0" and action.source == "manual"
        assert action.description == "soma a+b"
        assert action.permission == "util.soma"
        assert action.handler(a=2, b=3) == {"ok": True, "result": 5}
        # disco: código + catálogo com manifesto (sha/bytes)
        assert (tmp_path / "ferramentas" / "util.soma.py").read_text() == CODE_V1
        entrada = json.loads(
            (tmp_path / "ferramentas_catalogo.json").read_text())["ferramentas"]
        assert entrada["util.soma"]["sha256"] == hashlib.sha256(
            CODE_V1.encode()).hexdigest()
        assert entrada["util.soma"]["bytes"] == len(CODE_V1.encode())
        assert entrada["util.soma"]["ativa"] is True
        assert entrada["util.soma"]["origem"] == "manual"

    def test_codigo_invalido_nao_grava_nada(self, tmp_path: Path) -> None:
        depot, reg = _mk_depot(tmp_path)
        r = depot.instalar(nome="util.ruim", codigo=CODE_IMPORT_PROIBIDO)
        assert r["ok"] is False and r["acao"] == "rejeitado"
        assert "import" in r["motivo"]
        assert not reg.has("util.ruim")
        assert depot.listar() == []
        assert not (tmp_path / "ferramentas").exists()
        assert not (tmp_path / "ferramentas_catalogo.json").exists()

    def test_funcao_ausente_no_codigo(self, tmp_path: Path) -> None:
        depot, reg = _mk_depot(tmp_path)
        r = depot.instalar(nome="util.x", codigo=CODE_FUNCAO_ERRADA)
        assert r["ok"] is False and r["acao"] == "rejeitado"
        assert "funcao_nao_encontrada" in r["motivo"]
        assert not reg.has("util.x")

    def test_preflight_de_conflito_antes_de_qualquer_gravacao(
        self, tmp_path: Path,
    ) -> None:
        reg = ActionRegistry()
        reg.register_action("util.pronto", handler=lambda **p: {"ok": True})
        depot, _ = _mk_depot(tmp_path, registry=reg)
        r = depot.instalar(nome="util.pronto", codigo=CODE_V1)
        assert r["ok"] is False and r["acao"] == BLOQUEAR
        assert r["conflito"] == "action_alheia"
        assert not (tmp_path / "ferramentas").exists()
        # a ferramenta alheia continua funcionando
        assert reg.get("util.pronto").handler() == {"ok": True}

    def test_sem_espaco_bloqueia_no_depot(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path, espaco=0)
        r = depot.instalar(nome="util.soma", codigo=CODE_V1)
        assert r["ok"] is False and r["acao"] == BLOQUEAR
        assert "sem_espaco" in r["motivo"]

    def test_instalacao_repetida_e_idempotente(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util.soma", codigo=CODE_V1, versao="1.0.0")
        r2 = depot.instalar(nome="util.soma", codigo=CODE_V1, versao="1.0.0")
        assert r2["ok"] and r2["acao"] == SEM_ACAO
        assert len(depot.listar()) == 1

    def test_nome_normalizado_no_depot(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        r = depot.instalar(nome="Minha Soma!!", codigo=CODE_V1, funcao="soma")
        assert r["ok"] and r["id"] == "minha_soma__"
        assert depot.obter("minha_soma__").funcao == "soma"

    def test_funcao_padrao_e_o_ultimo_segmento(self, tmp_path: Path) -> None:
        depot, reg = _mk_depot(tmp_path)
        depot.instalar(nome="util.soma", codigo=CODE_V1)
        assert reg.get("util.soma").handler(a=1, b=1)["result"] == 2


# ===========================================================================
# 3. Atualização + rollback automático (a troca falhou no meio)
# ===========================================================================

class TestAtualizacao:
    def test_atualizacao_cria_backup_e_troca(self, tmp_path: Path) -> None:
        depot, reg = _mk_depot(tmp_path)
        depot.instalar(nome="util.soma", codigo=CODE_V1, versao="1.0.0")
        r = depot.instalar(nome="util.soma", codigo=CODE_V2, versao="1.0.1",
                           descricao="subtrai agora")
        assert r["ok"] and r["acao"] == ATUALIZAR and r["historico"] == 1
        action = reg.get("util.soma")
        assert action.version == "1.0.1"
        assert action.handler(a=10, b=4) == {"ok": True, "result": 6}
        # disco: código novo + backup da versão antiga preservado
        assert (tmp_path / "ferramentas" / "util.soma.py").read_text() == CODE_V2
        backup = tmp_path / "ferramentas_backup" / "util.soma.v1.0.0.py"
        assert backup.read_text() == CODE_V1
        entrada = depot.obter("util.soma")
        assert entrada.anteriores[0]["versao"] == "1.0.0"
        assert entrada.anteriores[0]["arquivo_backup"] == \
            "util.soma.v1.0.0.py"
        assert entrada.criada_em == 1_700_000_000.0  # não zerou

    def test_custom_do_dono_sobrevive_a_atualizacao(
        self, tmp_path: Path,
    ) -> None:
        depot, reg = _mk_depot(tmp_path)
        depot.instalar(nome="util.soma", codigo=CODE_V1, versao="1.0.0")
        depot.customizar("util.soma", descricao="MINHA descrição")
        depot.instalar(nome="util.soma", codigo=CODE_V2, versao="1.0.1")
        # a nova versão entra COM a custom reaplicada na action
        assert reg.get("util.soma").description == "MINHA descrição"
        assert depot.obter("util.soma").custom["descricao"] == \
            "MINHA descrição"

    def test_major_sem_confirmacao_nao_atualiza(self, tmp_path: Path) -> None:
        depot, reg = _mk_depot(tmp_path)
        depot.instalar(nome="util.soma", codigo=CODE_V1, versao="0.9.0")
        r = depot.instalar(nome="util.soma", codigo=CODE_V2, versao="1.0.0")
        assert r["ok"] is False
        assert "major_requer_confirmacao" in r["motivo"]
        assert reg.get("util.soma").version == "0.9.0"      # não mexeu
        r = depot.instalar(nome="util.soma", codigo=CODE_V2, versao="1.0.0",
                           confirmar=True)
        assert r["ok"] and reg.get("util.soma").version == "1.0.0"

    def test_downgrade_nao_atualiza(self, tmp_path: Path) -> None:
        depot, reg = _mk_depot(tmp_path)
        depot.instalar(nome="util.soma", codigo=CODE_V1, versao="1.0.0")
        r = depot.instalar(nome="util.soma", codigo=CODE_V2, versao="0.9.0")
        assert r["ok"] is False and "downgrade_bloqueado" in r["motivo"]
        assert reg.get("util.soma").version == "1.0.0"

    def test_historico_limitado_a_cinco(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util.soma", codigo=CODE_V1, versao="1.0.0")
        for v in range(1, 8):   # 1.0.1 … 1.0.7 (7 atualizações)
            codigo = CODE_V2 if v % 2 else CODE_V1
            depot.instalar(nome="util.soma", codigo=codigo, versao=f"1.0.{v}")
        assert len(depot.obter("util.soma").anteriores) == 5  # MAX_HISTORICO

    def test_falha_no_registro_dispara_rollback_total(
        self, tmp_path: Path,
    ) -> None:
        depot, reg = _mk_depot(tmp_path)
        depot.instalar(nome="util.soma", codigo=CODE_V1, versao="1.0.0")
        # o PRIMEIRO registro da troca falha (o resto volta tudo)
        original = depot._registrar
        chamadas = {"n": 0}

        def quebra(entrada, fn):
            chamadas["n"] += 1
            if chamadas["n"] == 1:
                return False
            return original(entrada, fn)

        depot._registrar = quebra  # type: ignore[assignment]
        r = depot.instalar(nome="util.soma", codigo=CODE_V2, versao="1.0.1")
        assert r["ok"] is False and r["rollback"] is True
        assert "rollback:" in r["motivo"]
        # arquivo, catálogo e action no estado pré-troca
        assert (tmp_path / "ferramentas" / "util.soma.py").read_text() == CODE_V1
        assert depot.obter("util.soma").versao == "1.0.0"
        assert depot.obter("util.soma").anteriores == []
        assert reg.get("util.soma").version == "1.0.0"
        assert reg.get("util.soma").handler(a=2, b=3)["result"] == 5

    def test_falha_na_gravacao_do_catalogo_dispara_rollback(
        self, tmp_path: Path,
    ) -> None:
        depot, reg = _mk_depot(tmp_path)
        depot.instalar(nome="util.soma", codigo=CODE_V1, versao="1.0.0")
        original = depot._gravar_catalogo
        chamadas = {"n": 0}

        def gravar_quebrado():
            chamadas["n"] += 1
            if chamadas["n"] == 1:      # gravação do UPDATE falha
                raise OSError("disco cheio")
            return original()           # o do rollback (2ª) funciona

        depot._gravar_catalogo = gravar_quebrado  # type: ignore[assignment]
        r = depot.instalar(nome="util.soma", codigo=CODE_V2, versao="1.0.1")
        # 1ª chamada após o patch = gravação do UPDATE (falha) → rollback
        assert chamadas["n"] >= 1
        assert r["ok"] is False and r["rollback"] is True
        assert (tmp_path / "ferramentas" / "util.soma.py").read_text() == CODE_V1
        assert depot.obter("util.soma").versao == "1.0.0"
        assert reg.get("util.soma").handler(a=2, b=3)["result"] == 5
        # o catálogo persistido no disco é o de antes (não o quebrado)
        entrada = json.loads(
            (tmp_path / "ferramentas_catalogo.json").read_text())["ferramentas"]
        assert entrada["util.soma"]["versao"] == "1.0.0"

    def test_falha_no_primeiro_registro_de_instalacao_nova(
        self, tmp_path: Path,
    ) -> None:
        depot, reg = _mk_depot(tmp_path)
        depot._registrar = lambda *a, **k: False  # type: ignore[assignment]
        r = depot.instalar(nome="util.soma", codigo=CODE_V1)
        assert r["ok"] is False and r["rollback"] is True
        assert depot.listar() == []
        assert not reg.has("util.soma")
        assert not (tmp_path / "ferramentas" / "util.soma.py").exists()


# ===========================================================================
# 4. Rollback manual (e ele é desfazível)
# ===========================================================================

class TestRollbackManual:
    def _com_historico(self, tmp_path: Path, n_updates: int = 1):
        depot, reg = _mk_depot(tmp_path)
        depot.instalar(nome="util.soma", codigo=CODE_V1, versao="1.0.0")
        for v in range(1, n_updates + 1):
            codigo = CODE_V2 if v % 2 else CODE_V1
            depot.instalar(nome="util.soma", codigo=codigo, versao=f"1.0.{v}")
        return depot, reg

    def test_rollback_volta_para_a_versao_anterior(
        self, tmp_path: Path,
    ) -> None:
        depot, reg = self._com_historico(tmp_path, 1)   # 1.0.1 no ar
        r = depot.rollback("util.soma")
        assert r["ok"] and r["de"] == "1.0.1" and r["para"] == "1.0.0"
        assert reg.get("util.soma").version == "1.0.0"
        assert (tmp_path / "ferramentas" / "util.soma.py").read_text() == CODE_V1
        # V1 somava de novo
        assert reg.get("util.soma").handler(a=7, b=2)["result"] == 9
        assert depot.obter("util.soma").versao == "1.0.0"

    def test_rollback_e_desfazivel(self, tmp_path: Path) -> None:
        # rollback do rollback: a versão atual entra no histórico junto
        depot, reg = self._com_historico(tmp_path, 1)
        depot.rollback("util.soma")            # 1.0.1 → 1.0.0
        r = depot.rollback("util.soma")        # 1.0.0 → 1.0.1 (desfaz)
        assert r["ok"] and r["de"] == "1.0.0" and r["para"] == "1.0.1"
        assert reg.get("util.soma").version == "1.0.1"
        assert (tmp_path / "ferramentas" / "util.soma.py").read_text() == CODE_V2

    def test_rollback_para_versao_especifica(self, tmp_path: Path) -> None:
        depot, reg = self._com_historico(tmp_path, 2)   # hist: 1.0.0, 1.0.1
        r = depot.rollback("util.soma", versao="1.0.0")
        assert r["ok"] and r["de"] == "1.0.2" and r["para"] == "1.0.0"
        assert reg.get("util.soma").version == "1.0.0"

    def test_rollback_sem_historico(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util.soma", codigo=CODE_V1, versao="1.0.0")
        r = depot.rollback("util.soma")
        assert r["ok"] is False
        assert r["motivo"] == "sem_historico_de_versoes"

    def test_rollback_ferramenta_inexistente(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        r = depot.rollback("util.nada")
        assert r["ok"] is False and r["motivo"] == "ferramenta_inexistente"

    def test_rollback_versao_alvo_inexistente(self, tmp_path: Path) -> None:
        depot, _ = self._com_historico(tmp_path, 1)
        r = depot.rollback("util.soma", versao="9.9.9")
        assert r["ok"] is False
        assert r["motivo"].startswith("versao_nao_encontrada")

    def test_rollback_com_backup_sumido(self, tmp_path: Path) -> None:
        depot, _ = self._com_historico(tmp_path, 1)
        (tmp_path / "ferramentas_backup" / "util.soma.v1.0.0.py").unlink()
        r = depot.rollback("util.soma")
        assert r["ok"] is False
        assert r["motivo"].startswith("backup_ausente")
        # nada mudou
        assert depot.obter("util.soma").versao == "1.0.1"

    def test_rollback_restaura_custom_do_dono(self, tmp_path: Path) -> None:
        depot, reg = self._com_historico(tmp_path, 0)
        depot.customizar("util.soma", descricao="do dono")
        depot.instalar(nome="util.soma", codigo=CODE_V2, versao="1.0.1")
        depot.rollback("util.soma")
        assert reg.get("util.soma").description == "do dono"


# ===========================================================================
# 5. Customização (PUT do dono) e remoção
# ===========================================================================

class TestCustomizacao:
    def test_descricao_custom_reflete_na_action(self, tmp_path: Path) -> None:
        depot, reg = _mk_depot(tmp_path)
        depot.instalar(nome="util.soma", codigo=CODE_V1)
        r = depot.customizar("util.soma", descricao="descrição do dono")
        assert r["ok"] and r["ativa"] is True
        assert r["custom"]["descricao"] == "descrição do dono"
        assert reg.get("util.soma").description == "descrição do dono"

    def test_params_e_permission_customizados(self, tmp_path: Path) -> None:
        depot, reg = _mk_depot(tmp_path)
        depot.instalar(nome="util.soma", codigo=CODE_V1)
        params = {"required": [], "properties": {"a": {"type": "integer"}}}
        depot.customizar("util.soma", params=params, permission="dono")
        action = reg.get("util.soma")
        assert action.params == params and action.permission == "dono"

    def test_custom_sem_nada_alterar(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util.soma", codigo=CODE_V1)
        r = depot.customizar("util.soma")
        assert r["ok"] is False and r["motivo"] == "nada_para_alterar"

    def test_custom_params_nao_dict(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util.soma", codigo=CODE_V1)
        r = depot.customizar("util.soma", params="texto")
        assert r["ok"] is False and r["motivo"] == "params_invalido"

    def test_custom_ferramenta_inexistente(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        r = depot.customizar("util.nada", descricao="x")
        assert r["ok"] is False and r["motivo"] == "ferramenta_inexistente"

    def test_ativa_false_desinstala_e_true_reativa(
        self, tmp_path: Path,
    ) -> None:
        depot, reg = _mk_depot(tmp_path)
        depot.instalar(nome="util.soma", codigo=CODE_V1)
        r = depot.customizar("util.soma", ativa=False)
        assert r["ok"] and r["ativa"] is False
        assert not reg.has("util.soma")
        # não destrutivo: arquivo original fica + cópia no backup
        assert (tmp_path / "ferramentas" / "util.soma.py").exists()
        assert (tmp_path / "ferramentas_backup" /
                "util.soma.removido.v1.0.0.py").exists()
        r = depot.customizar("util.soma", ativa=True)
        assert r["ok"] and r["ativa"] is True
        assert reg.has("util.soma")


class TestRemocao:
    def test_remover_sai_do_registry_e_do_catalogo(
        self, tmp_path: Path,
    ) -> None:
        depot, reg = _mk_depot(tmp_path)
        depot.instalar(nome="util.soma", codigo=CODE_V1)
        r = depot.remover("util.soma")
        assert r["ok"] and r["removido"] == "util.soma"
        assert not reg.has("util.soma")
        assert depot.listar() == []
        entrada = json.loads(
            (tmp_path / "ferramentas_catalogo.json").read_text())["ferramentas"]
        assert "util.soma" not in entrada
        # código preservado no backup (nada destrutivo)
        assert (tmp_path / "ferramentas_backup" /
                "util.soma.removido.v1.0.0.py").read_text() == CODE_V1

    def test_remover_inexistente(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        r = depot.remover("util.nada")
        assert r["ok"] is False and r["motivo"] == "ferramenta_inexistente"

    def test_rollback_depois_de_remover(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util.soma", codigo=CODE_V1, versao="1.0.0")
        depot.instalar(nome="util.soma", codigo=CODE_V2, versao="1.0.1")
        depot.remover("util.soma")
        r = depot.rollback("util.soma")
        assert r["ok"] is False and r["motivo"] == "ferramenta_inexistente"


# ===========================================================================
# 6. Restauração no boot (o buraco do /gerar em memória)
# ===========================================================================

class TestBootRestore:
    def test_reinicia_e_restaura_tudo(self, tmp_path: Path) -> None:
        depot1, _ = _mk_depot(tmp_path)
        depot1.instalar(nome="util.soma", codigo=CODE_V1, descricao="uma")
        depot1.instalar(nome="util.multiplica", codigo=CODE_MULT,
                        versao="1.2.0", categoria="util")
        # "restart": novo registry + novo depot lendo os MESMOS arquivos
        reg2 = ActionRegistry()
        depot2, _ = _mk_depot(tmp_path, registry=reg2)
        estado = depot2.carregar()
        assert estado == {"carregadas": 2, "erros": 0}
        assert reg2.get("util.soma").handler(a=1, b=2)["result"] == 3
        assert reg2.get("util.multiplica").version == "1.2.0"
        assert reg2.get("util.soma").description == "uma"

    def test_custom_sobrevive_a_reinicializacao(self, tmp_path: Path) -> None:
        depot1, _ = _mk_depot(tmp_path)
        depot1.instalar(nome="util.soma", codigo=CODE_V1)
        depot1.customizar("util.soma", descricao="do dono, sempre")
        reg2 = ActionRegistry()
        depot2, _ = _mk_depot(tmp_path, registry=reg2)
        depot2.carregar()
        assert reg2.get("util.soma").description == "do dono, sempre"

    def test_codigo_corrompido_nao_derruba_o_resto(
        self, tmp_path: Path,
    ) -> None:
        depot1, _ = _mk_depot(tmp_path)
        depot1.instalar(nome="util.soma", codigo=CODE_V1)
        depot1.instalar(nome="util.multiplica", codigo=CODE_MULT)
        (tmp_path / "ferramentas" / "util.soma.py").unlink()
        reg2 = ActionRegistry()
        depot2, _ = _mk_depot(tmp_path, registry=reg2)
        estado = depot2.carregar()
        assert estado == {"carregadas": 1, "erros": 1}
        assert "util.soma" in depot2.ultimo_erro
        assert reg2.has("util.multiplica") and not reg2.has("util.soma")
        # e a saúde acusa a ferramenta fora (o dono vê no painel)
        saude = depot2.health_check()
        assert saude["ok"] is False
        assert saude["fora_do_registry"] == ["util.soma"]

    def test_inativa_nao_restaura_e_nao_conta_erro(
        self, tmp_path: Path,
    ) -> None:
        depot1, _ = _mk_depot(tmp_path)
        depot1.instalar(nome="util.soma", codigo=CODE_V1)
        depot1.customizar("util.soma", ativa=False)
        reg2 = ActionRegistry()
        depot2, _ = _mk_depot(tmp_path, registry=reg2)
        assert depot2.carregar() == {"carregadas": 0, "erros": 0}
        assert not reg2.has("util.soma")

    def test_reativada_no_boot_com_mesma_versao(self, tmp_path: Path) -> None:
        depot1, _ = _mk_depot(tmp_path)
        depot1.instalar(nome="util.soma", codigo=CODE_V1)
        depot1.customizar("util.soma", ativa=False)
        # o dono reativa instando de novo com a MESMA versão
        r = depot1.instalar(nome="util.soma", codigo=CODE_V1, versao="1.0.0")
        assert r["ok"] and r["acao"] == INSTALAR and "reativacao" in r["motivo"]
        assert depot1.obter("util.soma").ativa is True
        assert depot1._registry.has("util.soma")

    def test_catalogo_json_corrompio_comeca_vazio(self, tmp_path: Path) -> None:
        (tmp_path / "ferramentas_catalogo.json").write_text("{invalido")
        depot, reg = _mk_depot(tmp_path)
        assert depot.listar() == []
        assert depot.carregar() == {"carregadas": 0, "erros": 0}
        assert not reg.has("qualquer")

    def test_catalogo_ausente_nao_explode(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        assert depot.carregar() == {"carregadas": 0, "erros": 0}
        assert depot.resumo()["total"] == 0


# ===========================================================================
# 7. Resumo / saúde / dump (painel + health + stats)
# ===========================================================================

class TestResumoEDump:
    def test_resumo_contagens(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util.soma", codigo=CODE_V1, versao="1.0.0")
        depot.instalar(nome="util.soma", codigo=CODE_V2, versao="1.0.1")
        depot.instalar(nome="util.multiplica", codigo=CODE_MULT)
        resumo = depot.resumo()
        assert resumo["total"] == 2 and resumo["ativas"] == 2
        assert resumo["com_historico"] == 1
        assert resumo["origens"] == {"manual": 2}
        assert resumo["ultimo_erro"] == ""

    def test_health_ok_e_aceita_monitor(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util.soma", codigo=CODE_V1)
        # contrato check(monitor) do HealthMonitor (lição da Parte E)
        saude = depot.health_check(object())
        assert saude["ok"] is True
        assert "supply-depot" in saude["detail"]
        assert saude["fora_do_registry"] == []

    def test_health_detecta_desync_com_o_registry(
        self, tmp_path: Path,
    ) -> None:
        depot, reg = _mk_depot(tmp_path)
        depot.instalar(nome="util.soma", codigo=CODE_V1)
        reg.unregister("util.soma")   # alguém derrubou a action
        saude = depot.health_check()
        assert saude["ok"] is False
        assert saude["fora_do_registry"] == ["util.soma"]

    def test_health_ignora_inativas(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util.soma", codigo=CODE_V1)
        depot.remover("util.soma")
        saude = depot.health_check()
        assert saude["ok"] is True          # removida ≠ quebrada

    def test_listar_traz_estado_vivo(self, tmp_path: Path) -> None:
        depot, reg = _mk_depot(tmp_path)
        depot.instalar(nome="util.soma", codigo=CODE_V1)
        item = depot.listar()[0]
        assert item["no_registry"] is True and item["ativa"] is True
        reg.unregister("util.soma")
        assert depot.listar()[0]["no_registry"] is False

    def test_dump(self, tmp_path: Path) -> None:
        depot, _ = _mk_depot(tmp_path)
        depot.instalar(nome="util.soma", codigo=CODE_V1)
        dump = depot.dump()
        assert len(dump["ferramentas"]) == 1
        assert dump["resumo"]["total"] == 1


# ===========================================================================
# 8. Integração com o Auto Extension (/gerar)
# ===========================================================================

class FakeLLM:
    def __init__(self, code: str) -> None:
        self._code = code
        self.prompts: list[str] = []

    async def generate(self, prompt: str, **options: Any) -> str:
        self.prompts.append(prompt)
        return self._code


class TestIntegracaoAutoExtension:
    def test_gerar_persiste_no_depot(self, tmp_path: Path) -> None:
        depot, reg = _mk_depot(tmp_path)
        llm = FakeLLM(CODE_DANCA_FENCE)
        ext = AutoExtension(llm, reg, depot=depot)
        r = asyncio.run(ext.extend("danca", "ferramenta de dança"))
        assert r["status"] == "ok" and r["persistido"] is True
        assert r["versao"] == "1.0.0"
        assert any(f["id"] == "auto.danca" for f in depot.listar())
        assert (tmp_path / "ferramentas" / "auto.danca.py").exists()
        assert reg.get("auto.danca").source == "auto_extension"
        assert reg.get("auto.danca").handler()["result"] == "passo"
        # e o registro SAIU do estado só-em-memória: sobrevive a restart
        reg2 = ActionRegistry()
        depot2, _ = _mk_depot(tmp_path, registry=reg2)
        depot2.carregar()
        assert reg2.has("auto.danca")

    def test_conflito_bloqueia_antes_de_gastar_llm(
        self, tmp_path: Path,
    ) -> None:
        reg = ActionRegistry()
        reg.register_action("auto.existe", handler=lambda **p: {"ok": True})
        depot, _ = _mk_depot(tmp_path, registry=reg)
        llm = FakeLLM(CODE_DANCA_FENCE)
        ext = AutoExtension(llm, reg, depot=depot)
        r = asyncio.run(ext.extend("existe", "outra ferramenta"))
        # devolve CONFLITO honesto (antes: gerava, pulava o registro em
        # silêncio e dizia "ok")
        assert r["status"] == "conflict"
        assert "já existe no registry" in r["error"]
        assert llm.prompts == []            # NENHUM token gasto
        assert depot.listar() == []         # nada persistido

    def test_ja_instalada_sem_substituir_e_exists(
        self, tmp_path: Path,
    ) -> None:
        depot, reg = _mk_depot(tmp_path)
        depot.instalar(nome="auto.danca", codigo=CODE_DANCA, versao="1.0.0",
                       funcao="danca", origem="auto_extension")
        llm = FakeLLM(CODE_DANCA_FENCE)
        ext = AutoExtension(llm, reg, depot=depot)
        r = asyncio.run(ext.extend("danca", "gerar de novo"))
        assert r["status"] == "exists"
        assert "ja_instalada" in r["error"]
        assert llm.prompts == []

    def test_versao_maior_sem_substituir_e_blocked(
        self, tmp_path: Path,
    ) -> None:
        depot, reg = _mk_depot(tmp_path)
        depot.instalar(nome="auto.danca", codigo=CODE_DANCA, versao="1.0.1",
                       funcao="danca", origem="auto_extension")
        llm = FakeLLM(CODE_DANCA_FENCE)
        ext = AutoExtension(llm, reg, depot=depot)
        r = asyncio.run(ext.extend("danca", "gerar de novo"))
        assert r["status"] == "blocked"
        assert "downgrade_bloqueado" in r["error"]
        assert llm.prompts == []

    def test_substituir_dá_bump_e_historico(self, tmp_path: Path) -> None:
        depot, reg = _mk_depot(tmp_path)
        depot.instalar(nome="auto.danca", codigo=CODE_DANCA, versao="1.0.0",
                       funcao="danca", origem="auto_extension")
        llm = FakeLLM(CODE_DANCA_FENCE)
        ext = AutoExtension(llm, reg, depot=depot)
        r = asyncio.run(ext.extend("danca", "versão nova",
                                   substituir=True))
        assert r["status"] == "ok" and r["versao"] == "1.0.1"
        assert llm.prompts                    # chamou o LLM de verdade
        entrada = depot.obter("auto.danca")
        assert entrada.versao == "1.0.1"
        assert len(entrada.anteriores) == 1   # backup → rollback possível
        assert (tmp_path / "ferramentas_backup" /
                "auto.danca.v1.0.0.py").exists()

    def test_sem_depot_caminho_legado_continua(self, tmp_path: Path) -> None:
        # AutoExtension sem depot = caminho antigo intocado (compat)
        reg = ActionRegistry()
        llm = FakeLLM(CODE_DANCA_FENCE)
        ext = AutoExtension(llm, reg)         # depot=None
        r = asyncio.run(ext.extend("danca", "sem depot"))
        assert r["status"] == "ok"
        assert "persistido" not in r
        assert reg.has("auto.danca")


# ===========================================================================
# 9. Rotas /admin/ferramentas (API + painel + stats)
# ===========================================================================

def _request(port: int, method: str, path: str, *, api_key: str = "",
             body: Any = None) -> tuple[int, bytes]:
    """HTTP real contra o servidor de teste (molde de test_auto_update)."""
    import urllib.error
    import urllib.request

    url = f"http://127.0.0.1:{port}{path}"
    dados = json.dumps(body).encode() if body is not None else None
    hdrs = {"Content-Type": "application/json"} if dados else {}
    if api_key:
        hdrs["X-API-Key"] = api_key
    req = urllib.request.Request(url, data=dados, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _json_body(resposta: bytes) -> dict[str, Any]:
    return json.loads(resposta.decode() or "{}")


@pytest.fixture()
def serve():
    """Sobe APIServers sob demanda e derruba todos no fim."""
    from integrations.api import APIServer

    servers: list[Any] = []

    def _start(orch: Any = None, *, config: Any = None) -> Any:
        srv = APIServer(orch, config=config)
        srv.serve_background()
        servers.append(srv)
        return srv

    yield _start
    for srv in servers:
        try:
            srv.stop()
        except Exception:
            pass


@pytest.fixture()
def srv_depot(serve, tmp_path: Path):
    """APIServer com um SupplyDepot real injetado (relógio fixo)."""
    from integrations.api import APIConfig

    depot, reg = _mk_depot(tmp_path)
    cfg = APIConfig(port=0, rate_limit_max=0, api_key="segredo123",
                    auth_all=True, supply_depot=depot)
    return serve(None, config=cfg), depot, reg


class TestSupplyDepotRotas:
    def test_sem_credencial_leva_401(self, srv_depot) -> None:
        servidor, _, _ = srv_depot
        status, _ = _request(servidor.bound_port, "GET", "/admin/ferramentas")
        assert status == 401

    def test_sem_depot_503_em_todas(self, serve) -> None:
        from integrations.api import APIConfig
        servidor = serve(None, config=APIConfig(
            port=0, rate_limit_max=0, api_key="segredo123", auth_all=True))
        casos = (
            ("GET", "/admin/ferramentas", None),
            ("POST", "/admin/ferramentas", {}),
            ("PUT", "/admin/ferramentas/util.soma", {"descricao": "x"}),
            ("POST", "/admin/ferramentas/util.soma/rollback", None),
            ("DELETE", "/admin/ferramentas/util.soma", None),
        )
        for metodo, caminho, body in casos:
            status, corpo = _request(servidor.bound_port, metodo, caminho,
                                     api_key="segredo123", body=body)
            assert status == 503, caminho
            assert _json_body(corpo)["error"] == "supply_depot_indisponivel"

    def test_get_lista_vazia(self, srv_depot) -> None:
        servidor, _, _ = srv_depot
        status, corpo = _request(servidor.bound_port, "GET",
                                 "/admin/ferramentas", api_key="segredo123")
        data = _json_body(corpo)
        assert status == 200 and data["ok"] is True
        assert data["ferramentas"] == [] and data["total"] == 0

    def test_post_instala_201(self, srv_depot) -> None:
        servidor, depot, reg = srv_depot
        status, corpo = _request(
            servidor.bound_port, "POST", "/admin/ferramentas",
            api_key="segredo123",
            body={"nome": "util.soma", "codigo": CODE_V1, "versao": "1.0.0",
                  "descricao": "soma a+b", "categoria": "util"})
        data = _json_body(corpo)
        assert status == 201 and data["ok"] is True
        assert data["acao"] == INSTALAR and data["versao"] == "1.0.0"
        assert reg.get("util.soma").handler(a=2, b=3)["result"] == 5
        assert any(f["id"] == "util.soma" for f in depot.listar())

    def test_post_atualiza_200(self, srv_depot) -> None:
        servidor, _, reg = srv_depot
        _request(servidor.bound_port, "POST", "/admin/ferramentas",
                 api_key="segredo123",
                 body={"nome": "util.soma", "codigo": CODE_V1})
        status, corpo = _request(
            servidor.bound_port, "POST", "/admin/ferramentas",
            api_key="segredo123",
            body={"nome": "util.soma", "codigo": CODE_V2, "versao": "1.0.1"})
        data = _json_body(corpo)
        assert status == 200 and data["acao"] == ATUALIZAR
        assert data["historico"] == 1
        assert reg.get("util.soma").version == "1.0.1"

    def test_post_repetido_e_sem_acao_200(self, srv_depot) -> None:
        servidor, _, _ = srv_depot
        for _ in range(2):
            status, corpo = _request(
                servidor.bound_port, "POST", "/admin/ferramentas",
                api_key="segredo123",
                body={"nome": "util.soma", "codigo": CODE_V1})
        assert status == 200
        assert _json_body(corpo)["acao"] == SEM_ACAO

    def test_post_conflito_409(self, srv_depot) -> None:
        servidor, _, reg = srv_depot
        reg.register_action("util.pronto", handler=lambda **p: {"ok": True})
        status, corpo = _request(
            servidor.bound_port, "POST", "/admin/ferramentas",
            api_key="segredo123",
            body={"nome": "util.pronto", "codigo": CODE_V1})
        assert status == 409
        assert "conflito" in _json_body(corpo)["error"]

    def test_post_major_sem_confirmacao_409(self, srv_depot) -> None:
        servidor, _, _ = srv_depot
        _request(servidor.bound_port, "POST", "/admin/ferramentas",
                 api_key="segredo123",
                 body={"nome": "util.soma", "codigo": CODE_V1,
                       "versao": "0.9.0"})
        status, corpo = _request(
            servidor.bound_port, "POST", "/admin/ferramentas",
            api_key="segredo123",
            body={"nome": "util.soma", "codigo": CODE_V2, "versao": "1.0.0"})
        assert status == 409
        assert "major_requer_confirmacao" in _json_body(corpo)["error"]
        # o dono confirma pelo corpo: substituir=true
        status, _ = _request(
            servidor.bound_port, "POST", "/admin/ferramentas",
            api_key="segredo123",
            body={"nome": "util.soma", "codigo": CODE_V2, "versao": "1.0.0",
                  "substituir": True})
        assert status == 200

    def test_post_codigo_ruim_400(self, srv_depot) -> None:
        servidor, _, _ = srv_depot
        status, corpo = _request(
            servidor.bound_port, "POST", "/admin/ferramentas",
            api_key="segredo123",
            body={"nome": "util.ruim", "codigo": CODE_IMPORT_PROIBIDO})
        assert status == 400
        assert "import" in _json_body(corpo)["error"]

    def test_post_sem_nome_ou_codigo_400(self, srv_depot) -> None:
        servidor, _, _ = srv_depot
        status, corpo = _request(servidor.bound_port, "POST",
                                 "/admin/ferramentas", api_key="segredo123",
                                 body={"codigo": CODE_V1})
        assert status == 400
        assert _json_body(corpo)["error"] == "nome_obrigatorio"
        status, corpo = _request(servidor.bound_port, "POST",
                                 "/admin/ferramentas", api_key="segredo123",
                                 body={"nome": "util.soma"})
        assert status == 400
        assert _json_body(corpo)["error"] == "codigo_obrigatorio"

    def test_put_customiza_200(self, srv_depot) -> None:
        servidor, _, reg = srv_depot
        _request(servidor.bound_port, "POST", "/admin/ferramentas",
                 api_key="segredo123",
                 body={"nome": "util.soma", "codigo": CODE_V1})
        status, corpo = _request(
            servidor.bound_port, "PUT", "/admin/ferramentas/util.soma",
            api_key="segredo123", body={"descricao": "do dono"})
        data = _json_body(corpo)
        assert status == 200 and data["ok"] is True
        assert reg.get("util.soma").description == "do dono"

    def test_put_erros_404_400(self, srv_depot) -> None:
        servidor, _, _ = srv_depot
        status, corpo = _request(servidor.bound_port, "PUT",
                                 "/admin/ferramentas/util.nada",
                                 api_key="segredo123",
                                 body={"descricao": "x"})
        assert status == 404
        _request(servidor.bound_port, "POST", "/admin/ferramentas",
                 api_key="segredo123",
                 body={"nome": "util.soma", "codigo": CODE_V1})
        status, corpo = _request(servidor.bound_port, "PUT",
                                 "/admin/ferramentas/util.soma",
                                 api_key="segredo123", body={})
        assert status == 400
        assert _json_body(corpo)["error"] == "nada_para_alterar"
        status, corpo = _request(servidor.bound_port, "PUT",
                                 "/admin/ferramentas/util.soma",
                                 api_key="segredo123", body={"params": "x"})
        assert status == 400
        assert _json_body(corpo)["error"] == "params_invalido"

    def test_rollback_rota(self, srv_depot) -> None:
        servidor, _, reg = srv_depot
        _request(servidor.bound_port, "POST", "/admin/ferramentas",
                 api_key="segredo123",
                 body={"nome": "util.soma", "codigo": CODE_V1,
                       "versao": "1.0.0"})
        _request(servidor.bound_port, "POST", "/admin/ferramentas",
                 api_key="segredo123",
                 body={"nome": "util.soma", "codigo": CODE_V2,
                       "versao": "1.0.1"})
        status, corpo = _request(
            servidor.bound_port, "POST",
            "/admin/ferramentas/util.soma/rollback", api_key="segredo123")
        data = _json_body(corpo)
        assert status == 200 and data["de"] == "1.0.1" and data["para"] == "1.0.0"
        assert reg.get("util.soma").version == "1.0.0"

    def test_rollback_sem_historico_409_e_inexistente_404(
        self, srv_depot,
    ) -> None:
        servidor, _, _ = srv_depot
        _request(servidor.bound_port, "POST", "/admin/ferramentas",
                 api_key="segredo123",
                 body={"nome": "util.soma", "codigo": CODE_V1})
        status, corpo = _request(
            servidor.bound_port, "POST",
            "/admin/ferramentas/util.soma/rollback", api_key="segredo123")
        assert status == 409
        assert _json_body(corpo)["error"] == "sem_historico_de_versoes"
        status, corpo = _request(
            servidor.bound_port, "POST",
            "/admin/ferramentas/util.nada/rollback", api_key="segredo123")
        assert status == 404

    def test_delete_desinstala_200_e_depois_404(self, srv_depot) -> None:
        servidor, depot, reg = srv_depot
        _request(servidor.bound_port, "POST", "/admin/ferramentas",
                 api_key="segredo123",
                 body={"nome": "util.soma", "codigo": CODE_V1})
        status, corpo = _request(servidor.bound_port, "DELETE",
                                 "/admin/ferramentas/util.soma",
                                 api_key="segredo123")
        assert status == 200
        assert _json_body(corpo)["removido"] == "util.soma"
        assert not reg.has("util.soma") and depot.listar() == []
        status, _ = _request(servidor.bound_port, "DELETE",
                             "/admin/ferramentas/util.soma",
                             api_key="segredo123")
        assert status == 404

    def test_dashboard_stats_traz_ferramentas(self, srv_depot) -> None:
        servidor, _, _ = srv_depot
        _request(servidor.bound_port, "POST", "/admin/ferramentas",
                 api_key="segredo123",
                 body={"nome": "util.soma", "codigo": CODE_V1})
        status, corpo = _request(servidor.bound_port, "GET",
                                 "/dashboard/stats", api_key="segredo123")
        data = _json_body(corpo)
        assert status == 200
        ferramentas = data["ferramentas"]
        assert ferramentas["total"] == 1 and ferramentas["ativas"] == 1

    def test_painel_traz_a_secao(self, srv_depot) -> None:
        servidor, _, _ = srv_depot
        status, corpo = _request(servidor.bound_port, "GET", "/admin",
                                 api_key="segredo123")
        html = corpo.decode()
        assert status == 200
        assert "Ferramentas (Supply Depot)" in html
        assert "frLoad" in html and "/admin/ferramentas" in html
        assert "data/ferramentas_backup" in html
