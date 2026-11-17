"""
OMEGA DRAKON • TESTS
Módulo: tests/test_actions_cobertura.py
Descrição: Cobertura dos caminhos de `tools/actions/actions.py` que ficaram
           sem teste desde 02/11 (o arquivo saltou de 352 para 1942 stmts sem
           a suíte acompanhar). Foco em ações "de leitura" puros: rede,
           filesystem e subprocess sempre com dublês (nenhum efeito externo).
           Entrega incremental — uma action por vez, sem tocar nos testes
           já existentes (test_action_registry, test_actions_catalog, ...).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Regra do gate: nenhum `# pragma: no cover`, nenhum skip artificial.
"""

from __future__ import annotations

import builtins
import io
import os
import signal
import urllib.request
from pathlib import Path

import pytest

import tools.actions.actions as act
from tools.actions.actions import (
    mapa_forca_consulta,
    radio_play,
    radio_stop,
    radio_volume,
    web_search,
)


# ---------------------------------------------------------------------------
# Dublês de rede — `web_search` faz import local de urllib.request, então
# remanejar o atributo no módulo cobre a chamada em tempo de execução.
# ---------------------------------------------------------------------------


class _Resposta:
    """Mínimo de `urllib` response: context manager + read()."""

    def __init__(self, html: str) -> None:
        self._html = html

    def __enter__(self) -> "_Resposta":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._html.encode("utf-8")


def _aponta_urlopen(
    monkeypatch: pytest.MonkeyPatch,
    *,
    html: str = "",
    erro: Exception | None = None,
    chamadas: dict | None = None,
) -> None:
    """Faz `urlopen` devolver `html` (ou levantar `erro`) e registra a chamada."""

    def fake_urlopen(req, timeout=None):  # noqa: ANN001 - assinatura do urllib
        if chamadas is not None:
            chamadas["url"] = req.full_url
            chamadas["timeout"] = timeout
        if erro is not None:
            raise erro
        return _Resposta(html)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)


_HTML_COM_RESULTADOS = """
<html><body>
<table>
<a rel="nofollow" href="https://exemplo.test/doc" class='result-link'>Python Docs</a>
<td>Documentação oficial da linguagem Python em português.</td>
<a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexemplo.test%2Fblog"
   class='result-link'>Blog Exemplo</a>
</table>
</body></html>
"""


# ===========================================================================
# 1. validação de entrada — `query_vazia` (antes de qualquer rede)
# ===========================================================================


class TestWebSearchEntrada:
    @pytest.mark.parametrize("consulta", ["", "   ", None])
    def test_query_vazia_nao_chama_rede(
        self, consulta: str | None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        chamadas: dict = {}
        _aponta_urlopen(monkeypatch, chamadas=chamadas)

        r = web_search(consulta)  # type: ignore[arg-type]

        assert r["ok"] is False
        assert r["error"] == "query_vazia"
        assert "pesquise sobre python" in r["message"]
        # validação barata: nada de rede para consulta vazia
        assert chamadas == {}


# ===========================================================================
# 2. degradação — a fonte caiu e a action NÃO inventa resultado
# ===========================================================================


class TestWebSearchDegrada:
    def test_fonte_indisponivel(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _aponta_urlopen(
            monkeypatch, erro=OSError("sem rota até o host")
        )

        r = web_search("python")

        assert r["ok"] is False
        assert r["error"] == "fonte_indisponivel"
        assert "não invento resultados" in r["message"]
        assert "results" not in r

    def test_timeout_tambem_degrada(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _aponta_urlopen(monkeypatch, erro=TimeoutError("espera estourou"))
        r = web_search("python")
        assert r["ok"] is False
        assert r["error"] == "fonte_indisponivel"


# ===========================================================================
# 3. caminho feliz — parse do HTML lite do DuckDuckGo
# ===========================================================================


class TestWebSearchParse:
    def test_extrai_titulo_url_e_snippet(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        chamadas: dict = {}
        _aponta_urlopen(
            monkeypatch, html=_HTML_COM_RESULTADOS, chamadas=chamadas
        )

        r = web_search("python tutorial", max_results=5)

        assert r["ok"] is True
        assert r["query"] == "python tutorial"
        assert r["source"] == "DuckDuckGo (HTML lite)"
        assert len(r["results"]) == 2
        primeiro, segundo = r["results"]
        assert primeiro["title"] == "Python Docs"
        assert primeiro["url"] == "https://exemplo.test/doc"
        assert isinstance(primeiro["snippet"], str)
        # a URL chega com o parâmetro de regionalização pt-BR
        assert "q=python+tutorial" in chamadas["url"]
        assert "kl=br-pt" in chamadas["url"]
        assert chamadas["timeout"] == 10.0

    def test_resolve_redirecionamento_uddg(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _aponta_urlopen(monkeypatch, html=_HTML_COM_RESULTADOS)

        r = web_search("python")

        urls = [x["url"] for x in r["results"]]
        # o href do DDG é um redirect: a URL real sai do parâmetro uddg
        assert "https://exemplo.test/blog" in urls
        assert not any("duckduckgo.com/l/" in u for u in urls)

    def test_max_results_corta_a_lista(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _aponta_urlopen(monkeypatch, html=_HTML_COM_RESULTADOS)

        r = web_search("python", max_results=1)

        assert len(r["results"]) == 1
        assert r["results"][0]["title"] == "Python Docs"

    def test_sem_resultados_na_pagina(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _aponta_urlopen(
            monkeypatch,
            html="<html><body><p>sem nenhum resultado aqui</p></body></html>",
        )

        r = web_search("zzz inexistente")

        assert r["ok"] is True
        assert r["results"] == []
        assert r["message"] == "Nenhum resultado encontrado."

    def test_consulta_e_normalizada(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        chamadas: dict = {}
        _aponta_urlopen(
            monkeypatch, html=_HTML_COM_RESULTADOS, chamadas=chamadas
        )

        r = web_search("   espaços nas pontas   ")

        assert r["query"] == "espaços nas pontas"
        assert "q=espa%C3%A7os" in chamadas["url"]


# ===========================================================================
# 4. snippet — o texto do `<td>` anterior ao resultado
# ===========================================================================


def test_snippet_e_limpo_de_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercita a limpeza de HTML do snippet (`re.sub` de tags).

    O contexto revertido é varrido de trás pra frente em busca do `<td>`
    anterior ao link; montamos o trecho literal que satisfaz o padrão.
    """
    magic = ">dt/<" + "A" * 24 + ">dt<"  # = `<td>AAAA...</td>` ao contrário
    html = (
        f"<html><body>{magic}"
        "<a rel=\"nofollow\" href=\"https://exemplo.test/x\" "
        "class='result-link'>Titulo</a>"
        "</body></html>"
    )
    _aponta_urlopen(monkeypatch, html=html)

    r = web_search("algo")

    assert r["ok"] is True
    assert len(r["results"]) == 1
    snippet = r["results"][0]["snippet"]
    assert snippet == "A" * 24
    assert "<" not in snippet and ">" not in snippet


# ===========================================================================
# 5. mapa_forca_consulta — Mapa de Força (dados sensíveis, leitura local)
#
#    ATENÇÃO: a action usa caminho RELATIVO (`data/refs_todo/Projeti/Cod`).
#    Todo teste aqui faz chdir para tmp_path e grava dados FICTÍCIOS —
#    a suíte jamais lê os arquivos reais de policiais do repositório.
# ===========================================================================

_CABECALHO_CSV = (
    "inicio,final,cmd,municipio,setor,sub,local,vtr,escala,mod,re,func,re2,func2\n"
)
_LINHA_CSV = (
    "06:00,18:00,COMANDANTE,Centro,1,2,Posto Central,VIATURA 101,"
    "diurna,normal,fulano,beltrano,cicrano,nerozinho\n"
)


@pytest.fixture()
def base_mapa(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Cria a árvore fake em tmp e entra nela (nunca os dados reais)."""
    base = tmp_path / "data" / "refs_todo" / "Projeti" / "Cod"
    base.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return base


class TestMapaForcaSemDados:
    def test_diretorio_ausente(self, tmp_path: Path,
                               monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)  # sem criar a árvore
        r = mapa_forca_consulta()
        assert r["ok"] is False
        assert r["error"] == "dados_nao_disponiveis"
        assert "data/refs_todo/Projeti/Cod/" in r["message"]

    def test_arquivo_corrompido_vira_erro_leitura(
        self, base_mapa: Path
    ) -> None:
        # um DIRETÓRIO no lugar do CSV faz o open() levantar → erro_leitura
        (base_mapa / "Mapa.csv").mkdir()
        r = mapa_forca_consulta(tipo="escalas")
        assert r["ok"] is False
        assert r["error"] == "erro_leitura"
        assert r["message"]


class TestMapaForcaCsv:
    def test_escalas_le_so_o_csv(self, base_mapa: Path) -> None:
        (base_mapa / "Mapa.csv").write_text(
            _CABECALHO_CSV + _LINHA_CSV, encoding="utf-8")

        r = mapa_forca_consulta(tipo="escalas")

        assert r["ok"] is True
        assert r["tipo"] == "escalas"
        assert r["count"] == 1
        item = r["resultados"][0]
        assert item["fonte"] == "Mapa.csv"
        assert item["vtr"] == "VIATURA 101"
        assert item["municipio"] == "Centro"
        # o aviso de dado sensível acompanha TODA consulta
        assert "não enviar para LLM externo" in r["aviso"]

    def test_filtro_casa_com_qualquer_coluna(self, base_mapa: Path) -> None:
        (base_mapa / "Mapa.csv").write_text(
            _CABECALHO_CSV + _LINHA_CSV, encoding="utf-8")

        assert mapa_forca_consulta(
            tipo="escalas", filtro="centro")["count"] == 1
        assert mapa_forca_consulta(
            tipo="escalas", filtro="viatura 101")["count"] == 1
        assert mapa_forca_consulta(
            tipo="escalas", filtro="nao_existe")["count"] == 0

    def test_limite_corta_no_meio_do_csv(self, base_mapa: Path) -> None:
        linhas = _CABECALHO_CSV + "".join(
            f"06:00,18:00,C,Municipio{i},1,2,Local,VIATURA {i},d,n,"
            f"a,b,c,d\n"
            for i in range(1, 6)
        )
        (base_mapa / "Mapa.csv").write_text(linhas, encoding="utf-8")

        r = mapa_forca_consulta(tipo="escalas", limite=2)

        assert r["count"] == 2
        assert len(r["resultados"]) == 2
        assert r["resultados"][0]["municipio"] == "Municipio1"


class TestMapaForcaTxt:
    def test_policiais_le_mapaforca_e_efetivo(
        self, base_mapa: Path
    ) -> None:
        (base_mapa / "MapaForca.txt").write_text(
            "VIATURA 101 [I-00001] [TPD:001] [POSTO_12345_NOME]\n"
            "SEMESPACO\n",  # token único → viatura vazia (ramo defensivo)
            encoding="utf-8",
        )
        (base_mapa / "efetivo.txt").write_text(
            "POSTO 12345 12345-6 NOME EXEMPLO\n", encoding="utf-8")

        r = mapa_forca_consulta(tipo="policiais")

        assert r["ok"] is True
        fontes = [x["fonte"] for x in r["resultados"]]
        assert fontes == ["MapaForca.txt", "MapaForca.txt", "efetivo.txt"]
        com_ids = r["resultados"][0]
        assert com_ids["viatura"] == "VIATURA"
        assert com_ids["ids"] == ["I-00001", "TPD:001", "POSTO_12345_NOME"]
        # linha sem espaço em branco: o `re.search` não acha viatura
        assert r["resultados"][1]["viatura"] == ""
        assert r["resultados"][2]["linha"] == "POSTO 12345 12345-6 NOME EXEMPLO"

    def test_disponiveis_le_mapaforcatudo_com_secao_e_status(
        self, base_mapa: Path
    ) -> None:
        (base_mapa / "MapaForcaTudo.txt").write_text(
            "608420000\n"
            "\n"  # linha em branco é pulada
            "101 DISPONÍVEL [I-00001]\n"
            "102 [I-00002]\n"  # sem status reconhecido → string vazia
            "LINHA SEM DIGITOS DE SECAO\n",
            encoding="utf-8",
        )

        r = mapa_forca_consulta(tipo="disponiveis")

        assert r["ok"] is True
        fontes = {x["fonte"] for x in r["resultados"]}
        assert fontes == {"MapaForcaTudo.txt"}
        disponivel = r["resultados"][0]
        assert disponivel["secao"] == "608420000"
        assert disponivel["status"] == "DISPONÍVEL"
        assert disponivel["viatura"] == "101"
        assert disponivel["ids"] == ["I-00001"]
        # status não casa com a lista de palavras → vazio
        assert r["resultados"][1]["status"] == ""
        # linha que não é seção nem viatura com status segue o fluxo
        assert r["resultados"][2]["status"] == ""

    def test_viaturas_acessa_as_tres_fontes_txt_e_csv(
        self, base_mapa: Path
    ) -> None:
        (base_mapa / "Mapa.csv").write_text(
            _CABECALHO_CSV + _LINHA_CSV, encoding="utf-8")
        (base_mapa / "MapaForca.txt").write_text(
            "VIATURA 101 [I-00001]\n", encoding="utf-8")
        (base_mapa / "MapaForcaTudo.txt").write_text(
            "608420000\n101 OP ESPECIAL [I-00001]\n", encoding="utf-8")

        r = mapa_forca_consulta(tipo="viaturas")

        fontes = {x["fonte"] for x in r["resultados"]}
        assert fontes == {"Mapa.csv", "MapaForca.txt", "MapaForcaTudo.txt"}
        assert any(x.get("status") == "OP ESPECIAL" for x in r["resultados"])

    def test_resumo_percorre_as_quatro_fontes(
        self, base_mapa: Path
    ) -> None:
        (base_mapa / "Mapa.csv").write_text(
            _CABECALHO_CSV + _LINHA_CSV, encoding="utf-8")
        (base_mapa / "MapaForca.txt").write_text(
            "VIATURA 101 [I-00001]\n", encoding="utf-8")
        (base_mapa / "MapaForcaTudo.txt").write_text(
            "608420000\n101 RESERVA [I-00001]\n", encoding="utf-8")
        (base_mapa / "efetivo.txt").write_text(
            "POSTO 12345 12345-6 NOME EXEMPLO\n", encoding="utf-8")

        r = mapa_forca_consulta(tipo="resumo")

        fontes = {x["fonte"] for x in r["resultados"]}
        assert fontes == {
            "Mapa.csv", "MapaForca.txt", "MapaForcaTudo.txt", "efetivo.txt"}
        assert r["count"] == 4

    def test_filtro_zera_tudo_e_o_limite_segura_as_fontes(
        self, base_mapa: Path
    ) -> None:
        (base_mapa / "Mapa.csv").write_text(
            _CABECALHO_CSV + _LINHA_CSV, encoding="utf-8")
        (base_mapa / "MapaForca.txt").write_text(
            "VIATURA 101 [I-00001]\n", encoding="utf-8")

        r = mapa_forca_consulta(
            tipo="resumo", filtro="nao_casa_com_nada", limite=50)

        assert r["ok"] is True
        assert r["count"] == 0
        assert r["resultados"] == []
        assert r["filtro"] == "nao_casa_com_nada"

    def test_fontes_ausentes_sao_puladas_em_vez_de_quebrar(
        self, base_mapa: Path
    ) -> None:
        # só o efetivo existe: as três primeiras fontes são puladas
        (base_mapa / "efetivo.txt").write_text(
            "POSTO 1 1-1 UNICO\n", encoding="utf-8")

        r = mapa_forca_consulta(tipo="resumo")

        assert r["ok"] is True
        assert [x["fonte"] for x in r["resultados"]] == ["efetivo.txt"]

    def test_limite_dispara_o_break_de_cada_fonte_txt(
        self, base_mapa: Path
    ) -> None:
        """Cada laço de leitura tem o seu próprio `break` no `limite`."""
        # 1) efetivo.txt (o MapaForca não existe → só ele roda)
        (base_mapa / "efetivo.txt").write_text(
            "POSTO 1 1-1 A\nPOSTO 2 2-2 B\n", encoding="utf-8")
        r = mapa_forca_consulta(tipo="policiais", limite=1)
        assert r["count"] == 1
        assert [x["fonte"] for x in r["resultados"]] == ["efetivo.txt"]

        # 2) MapaForca.txt (limite estoura aqui → o efetivo nem é lido)
        (base_mapa / "MapaForca.txt").write_text(
            "V 1 [I-1]\nV 2 [I-2]\n", encoding="utf-8")
        (base_mapa / "efetivo.txt").unlink()
        r = mapa_forca_consulta(tipo="policiais", limite=1)
        assert r["count"] == 1
        assert r["resultados"][0]["fonte"] == "MapaForca.txt"

        # 3) MapaForcaTudo.txt (linha de seção não conta como resultado)
        (base_mapa / "MapaForcaTudo.txt").write_text(
            "608420000\n101 DISPONÍVEL [I-1]\n102 RESERVA [I-2]\n",
            encoding="utf-8")
        (base_mapa / "MapaForca.txt").unlink()
        r = mapa_forca_consulta(tipo="disponiveis", limite=1)
        assert r["count"] == 1
        assert r["resultados"][0]["fonte"] == "MapaForcaTudo.txt"
        assert r["resultados"][0]["status"] == "DISPONÍVEL"


# ===========================================================================
# 6. cluster rádio — varredura do /proc, kill por grupo e volume via pactl
#
#    Nada de rádio real: /proc inventado em tmp, `os.kill*`, `subprocess`,
#    `pactl` e o Home Assistant sempre com dublê.
# ===========================================================================


def _monta_proc(root: Path, entradas: dict[str, dict[str, bytes]]) -> None:
    """Cria uma árvore /proc falsa: pid → arquivo → conteúdo."""
    for pid, arquivos in entradas.items():
        pasta = root / pid
        pasta.mkdir(parents=True, exist_ok=True)
        for nome, conteudo in arquivos.items():
            (pasta / nome).write_bytes(conteudo)


class TestRadioFfplayPids:
    def test_varre_o_proc_e_so_conta_os_nossos(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OD_RADIO_STREAM_URL", "http://alvo.test/s")
        proc = tmp_path / "proc"
        meu_pid = str(os.getpid())
        _monta_proc(proc, {
            # marcado com a nossa env → player nosso, mesmo em outro stream
            "100": {"cmdline": b"ffplay\x00http://outro.test/s\x00",
                    "environ": b"OD_RADIO_CHILD=1\x00"},
            # player antigo (sem marca) tocando o stream conhecido
            "101": {"cmdline": b"ffplay\x00http://alvo.test/s\x00",
                    "environ": b"HOME=/x\x00"},
            # ffplay de terceiros, sem marca e stream alheio → não conta
            "102": {"cmdline": b"ffplay\x00http://terceiro.test/s\x00",
                    "environ": b"HOME=/x\x00"},
            # não é ffplay
            "103": {"cmdline": b"python\x00-m\x00servidor\x00"},
            # ffplay nosso mas sem environ legível → salva pelo stream
            "104": {"cmdline": b"ffplay\x00http://alvo.test/s\x00"},
            # sem arquivo de cmdline → OSError → pulado
            "105": {},
            # cmdline vazia → pulada
            "106": {"cmdline": b""},
            # o próprio processo nunca é player da rádio
            meu_pid: {"cmdline": b"ffplay\x00http://alvo.test/s\x00"},
        })
        (proc / "nao_numerico").mkdir()
        (proc / "nao_numerico" / "cmdline").write_bytes(b"ffplay\x00x\x00")

        pids = act._radio_ffplay_pids(str(proc))

        assert pids == [100, 101, 104]

    def test_proc_inexistente_devolve_vazio(
        self, tmp_path: Path
    ) -> None:
        assert act._radio_ffplay_pids(str(tmp_path / "nao_existe")) == []


class TestRadioPidVivo:
    @staticmethod
    def _finge_stat(
        monkeypatch: pytest.MonkeyPatch, stat: bytes | None
    ) -> None:
        """`/proc/<pid>/stat` falso; todo o resto continua sendo open() real."""
        real_open = builtins.open

        def fake_open(file, *args, **kwargs):  # noqa: ANN001
            if (
                isinstance(file, str)
                and file.startswith("/proc/")
                and file.endswith("/stat")
            ):
                if stat is None:
                    raise OSError("sem /proc para este pid")
                return io.BytesIO(stat)
            return real_open(file, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", fake_open)

    def test_zumbi_conta_como_morto(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # estado Z: o `os.kill(pid, 0)` ainda responde, mas não toca nada
        self._finge_stat(monkeypatch, b"4242 (ffplay) Z 1 2 3")
        assert act._radio_pid_vivo(4242) is False

    def test_processo_vivo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._finge_stat(monkeypatch, b"4242 (ffplay) S 1 2 3")
        monkeypatch.setattr(act.os, "kill", lambda pid, sinal: None)
        assert act._radio_pid_vivo(4242) is True

    def test_pid_morto(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._finge_stat(monkeypatch, None)

        def kill(pid, sinal):  # noqa: ANN001
            raise ProcessLookupError()

        monkeypatch.setattr(act.os, "kill", kill)
        assert act._radio_pid_vivo(4242) is False

    def test_sem_permissao_mas_esta_vivo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._finge_stat(monkeypatch, None)

        def kill(pid, sinal):  # noqa: ANN001
            raise PermissionError()

        monkeypatch.setattr(act.os, "kill", kill)
        assert act._radio_pid_vivo(4242) is True


class TestRadioTerminate:
    def test_mata_por_grupo_e_confirma(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        grupos: list[tuple[int, int]] = []
        monkeypatch.setattr(act.os, "getpgid", lambda pid: 777)
        monkeypatch.setattr(
            act.os, "killpg", lambda pgid, sinal: grupos.append((pgid, sinal)))
        # morreu logo após o SIGTERM
        monkeypatch.setattr(act, "_radio_pid_vivo", lambda pid: False)

        assert act._radio_terminate(4242) is True
        assert grupos == [(777, signal.SIGTERM)]

    def test_cai_para_kill_simples(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def getpgid(pid):  # noqa: ANN001
            raise ProcessLookupError()

        monkeypatch.setattr(act.os, "getpgid", getpgid)
        sinais: list[int] = []
        monkeypatch.setattr(
            act.os, "kill", lambda pid, sinal: sinais.append(sinal))
        monkeypatch.setattr(act, "_radio_pid_vivo", lambda pid: False)

        assert act._radio_terminate(4242) is True
        # só o SIGTERM foi preciso: o kill simples já resolveu
        assert sinais == [signal.SIGTERM]

    def test_sem_nenhum_sinal_devolve_o_estado(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def getpgid(pid):  # noqa: ANN001
            raise ProcessLookupError()

        def kill(pid, sinal):  # noqa: ANN001
            raise ProcessLookupError()

        monkeypatch.setattr(act.os, "getpgid", getpgid)
        monkeypatch.setattr(act.os, "kill", kill)

        monkeypatch.setattr(act, "_radio_pid_vivo", lambda pid: False)
        assert act._radio_terminate(4242) is True

        monkeypatch.setattr(act, "_radio_pid_vivo", lambda pid: True)
        assert act._radio_terminate(4242) is False

    def test_sigkill_segue_quando_o_term_nao_mata(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(act.os, "getpgid", lambda pid: 7)
        monkeypatch.setattr(act.os, "killpg", lambda pgid, sinal: None)
        monkeypatch.setattr(act.time, "sleep", lambda segundos: None)

        estado = {"n": 0}

        def vivo(pid):  # noqa: ANN001
            estado["n"] += 1
            return estado["n"] < 25  # sobrevive ao TERM, morre no KILL

        monkeypatch.setattr(act, "_radio_pid_vivo", vivo)

        assert act._radio_terminate(4242) is True
        assert estado["n"] >= 21  # 20 varreduras do TERM + a primeira do KILL

    def test_resiste_a_todos_os_sinais_e_devolve_falso(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nem SIGTERM nem SIGKILL derrubam → o `return` final é `False`."""
        monkeypatch.setattr(act.os, "getpgid", lambda pid: 7)
        monkeypatch.setattr(act.os, "killpg", lambda pgid, sinal: None)
        monkeypatch.setattr(act.time, "sleep", lambda segundos: None)
        monkeypatch.setattr(act, "_radio_pid_vivo", lambda pid: True)

        assert act._radio_terminate(4242) is False


@pytest.fixture()
def radio_limpo(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Singleton zerado + sem efeito externo (pactl, ffplay, HA, /proc)."""
    monkeypatch.setattr(act, "_RADIO_PROCESS", None)
    monkeypatch.setattr(act, "_run", lambda *a, **k: (0, "", ""))
    monkeypatch.setattr(act, "ha_device_control", lambda **k: {"ok": True})
    monkeypatch.setattr(act, "_radio_ffplay_pids", lambda *a, **k: [])
    return monkeypatch


class TestRadioPlay:
    def test_adopt_player_ja_no_ar(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        radio_limpo.setattr(act, "_radio_ffplay_pids",
                            lambda *a, **k: [300, 301])
        radio_limpo.setattr(act, "_radio_terminate", lambda pid: True)
        chamadas = {"popen": 0}

        def popen(*a, **k):  # noqa: ANN001
            chamadas["popen"] += 1

        radio_limpo.setattr(act.subprocess, "Popen", popen)

        r = radio_play()

        assert r["ok"] is True
        assert r["status"] == "tocando"
        assert r["pid"] == 300
        assert "já estava tocando" in r["hint"]
        assert "1 instância(s) duplicada(s)" in r["hint"]
        assert chamadas["popen"] == 0  # nunca abre um segundo áudio

    def test_inicia_ffplay_com_volume_ajustado(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        class _Proc:
            pid = 4242

            def poll(self):  # noqa: ANN201
                return None

        radio_limpo.setattr(act.subprocess, "Popen", lambda *a, **k: _Proc())

        r = radio_play(stream_url="http://alvo.test/s", volume=200)

        assert r["ok"] is True
        assert r["pid"] == 4242
        assert r["volume"] == 150  # clamp 0–150
        assert r["stream_url"] == "http://alvo.test/s"

    def test_ffplay_ausente_degrada(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        def popen(*a, **k):  # noqa: ANN001
            raise FileNotFoundError()

        radio_limpo.setattr(act.subprocess, "Popen", popen)

        r = radio_play()

        assert r["ok"] is False
        assert "ffplay não encontrado" in r["error"]

    def test_falha_generica_no_player(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        def popen(*a, **k):  # noqa: ANN001
            raise RuntimeError("sem placa de som")

        radio_limpo.setattr(act.subprocess, "Popen", popen)

        r = radio_play()

        assert r["ok"] is False
        assert "falha ao iniciar ffplay" in r["error"]

    def test_energia_falha_e_nao_inventa_tocagem(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        radio_limpo.setattr(
            act, "ha_device_control",
            lambda **k: {"ok": False, "error": "sem HA"})

        r = radio_play()

        assert r["ok"] is False
        assert "falha ao ligar energia" in r["error"]

    def test_energia_pediu_confirmacao_e_concedeu(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        respostas = [{"ok": False, "needs_confirmation": True}, {"ok": True}]
        radio_limpo.setattr(
            act, "ha_device_control", lambda **k: respostas.pop(0))

        class _Proc:
            pid = 7

            def poll(self):  # noqa: ANN201
                return None

        radio_limpo.setattr(act.subprocess, "Popen", lambda *a, **k: _Proc())

        r = radio_play()

        assert r["ok"] is True
        assert len(respostas) == 0  # a confirmação foi consumida

    def test_energia_confirmou_e_mesmo_assim_falhou(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        respostas = [
            {"ok": False, "needs_confirmation": True},
            {"ok": False, "error": "negado"},
        ]
        radio_limpo.setattr(
            act, "ha_device_control", lambda **k: respostas.pop(0))

        r = radio_play()

        assert r["ok"] is False
        assert "falha ao confirmar energia" in r["error"]

    def test_sem_auto_power_nem_toca_energia(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        chamadas: list[dict] = []
        radio_limpo.setattr(
            act, "ha_device_control",
            lambda **k: chamadas.append(k) or {"ok": True})

        class _Proc:
            pid = 9

            def poll(self):  # noqa: ANN201
                return None

        radio_limpo.setattr(act.subprocess, "Popen", lambda *a, **k: _Proc())

        r = radio_play(auto_power=False)

        assert r["ok"] is True
        assert chamadas == []


class TestRadioStop:
    def test_ja_estava_parado(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        r = radio_stop(auto_power=False)

        assert r["ok"] is True
        assert r["status"] == "parado"
        assert r["hint"] == "já estava parado"
        assert r["pids_encerrados"] == []

    def test_encerra_todas_as_instancias(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        radio_limpo.setattr(act, "_radio_ffplay_pids",
                            lambda *a, **k: [10, 11])
        radio_limpo.setattr(act, "_radio_terminate", lambda pid: True)

        class _Proc:
            def wait(self, timeout=None):  # noqa: ANN001, ANN201
                return 0

        radio_limpo.setattr(act, "_RADIO_PROCESS", _Proc())

        r = radio_stop(auto_power=False)

        assert r["pids_encerrados"] == [10, 11]
        assert "rádio parada" in r["hint"]
        assert "2 instâncias encerradas" in r["hint"]

    def test_player_que_resiste_aparece_no_hint(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        radio_limpo.setattr(act, "_radio_ffplay_pids", lambda *a, **k: [10])
        radio_limpo.setattr(act, "_radio_terminate", lambda pid: False)

        r = radio_stop(auto_power=False)

        assert r["pids_encerrados"] == []
        assert "1 player(s) resistiram" in r["hint"]
        assert "instâncias encerradas" not in r["hint"]

    def test_desliga_a_energia_da_caixa(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        chamadas: list[dict] = []
        radio_limpo.setattr(
            act, "ha_device_control",
            lambda **k: chamadas.append(k) or {"ok": True})

        r = radio_stop()

        assert len(chamadas) == 1
        assert chamadas[0]["on"] is False
        assert chamadas[0]["entity_id"] == "switch.note_servidor_socket_1"
        assert "energia da caixa desligada" in r["hint"]

    def test_energia_falha_a_rádio_para_mesmo_assim(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        radio_limpo.setattr(
            act, "ha_device_control",
            lambda **k: {"ok": False, "error": "sem HA"})

        r = radio_stop()

        assert r["ok"] is True  # parar a rádio não depende do HA
        assert "energia da caixa desligada" not in r["hint"]

    def test_energia_pediu_confirmacao(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        respostas = [{"ok": False, "needs_confirmation": True}, {"ok": True}]
        radio_limpo.setattr(
            act, "ha_device_control", lambda **k: respostas.pop(0))

        r = radio_stop()

        assert "energia da caixa desligada" in r["hint"]
        assert respostas == []

    def test_confirmacao_negada_nao_anuncia_desligamento(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        respostas = [
            {"ok": False, "needs_confirmation": True},
            {"ok": False, "error": "negado"},
        ]
        radio_limpo.setattr(
            act, "ha_device_control", lambda **k: respostas.pop(0))

        r = radio_stop()

        assert r["ok"] is True
        assert "energia da caixa desligada" not in r["hint"]

    def test_wait_do_player_quebra_e_o_stop_nao_quebra(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        """Zumbi que não sai do `wait` não pode derrubar o stop da rádio."""
        radio_limpo.setattr(act, "_radio_ffplay_pids",
                            lambda *a, **k: [10])
        radio_limpo.setattr(act, "_radio_terminate", lambda pid: True)

        class _Zumbi:
            def wait(self, timeout=None):  # noqa: ANN001, ANN201
                raise RuntimeError("processo zumbi")

        radio_limpo.setattr(act, "_RADIO_PROCESS", _Zumbi())

        r = radio_stop(auto_power=False)

        assert r["ok"] is True
        assert r["pids_encerrados"] == [10]


class TestRadioVolume:
    @staticmethod
    def _pactl(
        monkeypatch: pytest.MonkeyPatch,
        *,
        get_rc: int = 0,
        get_out: str = "Volume: front-left: 32768 /  50% / -18.06 dB",
        set_rc: int = 0,
        set_err: str = "",
    ) -> list[list[str]]:
        """Dublê do `pactl`: get devolve `get_out`, set acusa `set_rc`."""
        chamadas: list[list[str]] = []

        def fake_run(argv, *args, **kwargs):  # noqa: ANN001
            chamadas.append(list(argv))
            if argv[1] == "get-sink-volume":
                return get_rc, get_out, ""
            return set_rc, "", set_err

        monkeypatch.setattr(act, "_run", fake_run)
        return chamadas

    def test_volume_absoluto(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        chamadas = self._pactl(radio_limpo)

        r = radio_volume(80)

        assert r["ok"] is True
        assert r["volume"] == 80
        assert r["sink"] == "@DEFAULT_SINK@"
        assert r["pid"] is None  # nenhum player no ar
        assert chamadas[-1] == [
            "pactl", "set-sink-volume", "@DEFAULT_SINK@", "80%"]

    def test_volume_fora_da_faixa_e_ajustado(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        self._pactl(radio_limpo)

        assert radio_volume(999)["volume"] == 150
        assert radio_volume(-5)["volume"] == 0

    def test_up_e_down_relativos(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        self._pactl(radio_limpo)  # atual = 50%

        assert radio_volume("up")["volume"] == 60
        assert radio_volume("down")["volume"] == 40

    def test_up_bate_no_teto_e_down_no_piso(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        self._pactl(radio_limpo, get_out="front-left: 32768 /  145%")
        assert radio_volume("up")["volume"] == 150

        self._pactl(radio_limpo, get_out="front-left: 32768 /  5%")
        assert radio_volume("down")["volume"] == 0

    def test_string_desconhecida_mantem_o_atual(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        self._pactl(radio_limpo)

        assert radio_volume("banana")["volume"] == 50

    def test_get_falha_usa_o_default_de_50(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        self._pactl(radio_limpo, get_rc=1, get_out="")

        assert radio_volume("up")["volume"] == 60

    def test_output_sem_porcentagem_usa_o_default(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        self._pactl(radio_limpo, get_out="sem porcentagem aqui")

        assert radio_volume("down")["volume"] == 40

    def test_set_falha_degrada_sem_efeito(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        self._pactl(radio_limpo, set_rc=1, set_err="sem pulseaudio")

        r = radio_volume(80)

        assert r["ok"] is False
        assert "pactl falhou" in r["error"]

    def test_devolve_o_pid_do_player_vivo(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        self._pactl(radio_limpo)
        radio_limpo.setattr(act, "_radio_ffplay_pids",
                            lambda *a, **k: [777])

        assert radio_volume(80)["pid"] == 777


class TestRadioStatus:
    def test_parado(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        r = act.radio_status()

        assert r["ok"] is True
        assert r["status"] == "parado"
        assert r["stream_url"] == act._RADIO_STREAM_URL
        assert "pid" not in r

    def test_tocando_com_volume_do_sink(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        radio_limpo.setattr(act, "_radio_ffplay_pids",
                            lambda *a, **k: [55])
        radio_limpo.setattr(
            act, "_run",
            lambda *a, **k: (0, "Volume: front-left: 80%", ""))

        r = act.radio_status()

        assert r["status"] == "tocando"
        assert r["pid"] == 55
        assert r["volume_sink"] == "Volume: front-left: 80%"
        assert "instancias" not in r  # um player só: sem hint de duplicata

    def test_tocando_sem_volume_disponivel(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        radio_limpo.setattr(act, "_radio_ffplay_pids",
                            lambda *a, **k: [55])
        # pactl falha nos dois sinks tentados → a linha "Saída:" some
        radio_limpo.setattr(act, "_run", lambda *a, **k: (1, "", ""))

        r = act.radio_status()

        assert r["status"] == "tocando"
        assert "volume_sink" not in r

    def test_pactl_responde_vazio_nao_conta_como_volume(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        radio_limpo.setattr(act, "_radio_ffplay_pids",
                            lambda *a, **k: [55])
        radio_limpo.setattr(act, "_run", lambda *a, **k: (0, "   ", ""))

        r = act.radio_status()

        assert r["status"] == "tocando"
        assert "volume_sink" not in r

    def test_varias_instancias_avisam_no_hint(
        self, radio_limpo: pytest.MonkeyPatch
    ) -> None:
        radio_limpo.setattr(act, "_radio_ffplay_pids",
                            lambda *a, **k: [55, 56, 57])
        radio_limpo.setattr(act, "_run", lambda *a, **k: (0, "80%", ""))

        r = act.radio_status()

        assert r["instancias"] == [55, 56, 57]
        assert "3 players da rádio no ar" in r["hint"]
