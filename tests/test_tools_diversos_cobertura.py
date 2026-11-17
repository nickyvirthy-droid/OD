#!/usr/bin/env python3
"""
OMEGA DRAKON • TESTS
Módulo: tests/test_tools_diversos_cobertura.py
Descrição: cobertura das três ferramentas de baixo uso na suíte —
           - tools/monitor/io_probe.py: sonda de latência do F3, com o
             urlopen substituído por dublê (nenhuma requisição real);
           - tools/baixar_resto_lista.py: lote do resto da playlist, com
             radio_link inteiro injetado (nenhum download, nenhum comando
             de sistema, log/RAIZ em tmp_path);
           - tools/gerar_ecossistema.py: gerador das 5 páginas, com a
             escrita redirecionada para tmp_path (o site/ real intocado).
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - docs/ANALISE_SISTEMA_TODO.md §F3 (async I/O)
  - tools/monitor/io_probe.py · tools/baixar_resto_lista.py
  - tools/gerar_ecossistema.py

Garantia de segurança: nada aqui fala com a rede nem escreve fora de
tmp_path — urlopen, extrair_entradas, rodar_pipeline, trava_pipeline,
notificar_dono e Path.write_text (no bloco __main__) são dublês.
"""

from __future__ import annotations

import json
import os
import re
import runpy
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from integrations import radio_link as rl
from tools import baixar_resto_lista as brl
from tools import gerar_ecossistema as ge
from tools.monitor import io_probe

# ---------------------------------------------------------------------------
#  io_probe — sonda de latência do od-core (F3)
# ---------------------------------------------------------------------------


class _Resposta:
    """Dublê de resposta do urlopen: contexto, status e corpo."""

    def __init__(self, corpo: bytes, status: int = 200) -> None:
        self._corpo = corpo
        self.status = status

    def read(self) -> bytes:
        return self._corpo

    def __enter__(self) -> "_Resposta":
        return self

    def __exit__(self, *_exc) -> bool:
        return False


def _urlopen_falso(
    corpo: bytes = b'{"ok": true}',
    status: int = 200,
    falha: BaseException | None = None,
    chamadas: list | None = None,
):
    """Fábrica de urlopen dublê: registra a chamada e devolve corpo/status."""

    def _urlopen(req, timeout=None):
        if chamadas is not None:
            chamadas.append((req, timeout))
        if falha is not None:
            raise falha
        return _Resposta(corpo, status)

    return _urlopen


def _falso_uma_requisicao(
    chamadas: list, codigo: int = 200, saudavel: bool = True, ms: float = 2.0
):
    """Dublê de _uma_requisicao que registra url/chave/timeout e devolve ms."""

    def _falsa(url: str, api_key: str, timeout: float) -> tuple[float, int, bool]:
        chamadas.append({"url": url, "api_key": api_key, "timeout": timeout})
        return (ms, codigo, saudavel)

    return _falsa


class TestUrlsplitPath:
    def test_extrai_o_path_do_alvo(self) -> None:
        """Rótulo curto é o path da URL."""
        assert io_probe.urlsplit_path("http://127.0.0.1:8000/health") == "/health"

    def test_url_sem_path_vira_barra(self) -> None:
        assert io_probe.urlsplit_path("http://127.0.0.1:8000") == "/"

    def test_url_invalida_nao_quebra_a_sonda(self) -> None:
        """IPv6 malformado levanta ValueError interno → rótulo vazio."""
        assert io_probe.urlsplit_path("http://[::1") == ""


class TestPercentil:
    def test_lista_vazia_zera(self) -> None:
        assert io_probe._percentil([], 95) == 0.0

    def test_percentil_de_lista_desordenada(self) -> None:
        """Ordena antes de cortar e usa índice arredondado."""
        assert io_probe._percentil([30.0, 10.0, 20.0], 95) == 30.0
        assert io_probe._percentil([30.0, 10.0, 20.0], 50) == 20.0


class TestUmaRequisicao:
    def test_sucesso_manda_chave_e_devolve_saudavel(
        self, monkeypatch
    ) -> None:
        chamadas: list = []
        monkeypatch.setattr(
            io_probe.urllib.request,
            "urlopen",
            _urlopen_falso(b'{"ok": true}', chamadas=chamadas),
        )
        ms, codigo, saudavel = io_probe._uma_requisicao(
            "http://127.0.0.1:9/health", "chave-123", 3.5
        )
        assert ms >= 0 and codigo == 200 and saudavel is True
        req, timeout = chamadas[0]
        assert req.get_method() == "GET"
        assert dict(req.header_items()).get("X-api-key") == "chave-123"
        assert timeout == 3.5

    def test_sem_chave_nao_manda_header(self, monkeypatch) -> None:
        chamadas: list = []
        monkeypatch.setattr(
            io_probe.urllib.request, "urlopen", _urlopen_falso(chamadas=chamadas)
        )
        _ms, codigo, _saudavel = io_probe._uma_requisicao(
            "http://127.0.0.1:9/health", "", 1.0
        )
        assert codigo == 200
        assert "X-api-key" not in dict(chamadas[0][0].header_items())

    def test_erro_http_vira_o_codigo_do_erro(self, monkeypatch) -> None:
        """HTTPError (429) não é exceção da sonda: vira código + corpo."""
        monkeypatch.setattr(
            io_probe.urllib.request,
            "urlopen",
            _urlopen_falso(
                falha=HTTPError(
                    "http://127.0.0.1:9/health",
                    429,
                    "lento demais",
                    {},
                    BytesIO(b'{"ok": false}'),
                )
            ),
        )
        ms, codigo, saudavel = io_probe._uma_requisicao(
            "http://127.0.0.1:9/health", "", 1.0
        )
        assert ms >= 0 and codigo == 429 and saudavel is False

    def test_falha_de_rede_vira_codigo_zero(self, monkeypatch) -> None:
        """Sem servidor a sonda reporta código 0 em vez de levantar."""
        monkeypatch.setattr(
            io_probe.urllib.request,
            "urlopen",
            _urlopen_falso(falha=OSError("sem rede")),
        )
        ms, codigo, saudavel = io_probe._uma_requisicao(
            "http://127.0.0.1:9/health", "", 1.0
        )
        assert ms >= 0 and codigo == 0 and saudavel is False

    def test_corpo_sem_json_nao_e_saudavel(self, monkeypatch) -> None:
        monkeypatch.setattr(
            io_probe.urllib.request,
            "urlopen",
            _urlopen_falso(b"<html>erro</html>"),
        )
        ms, codigo, saudavel = io_probe._uma_requisicao(
            "http://127.0.0.1:9/health", "", 1.0
        )
        assert ms >= 0 and codigo == 200 and saudavel is False


class TestSerie:
    def test_agrega_codigos_e_latencias(self, monkeypatch) -> None:
        """Contagem por código e p50/p95/max saem da sequência medida."""
        chamadas: list = []
        monkeypatch.setattr(
            io_probe, "_uma_requisicao",
            _falso_uma_requisicao(chamadas, codigo=200),
        )
        resumo = io_probe.serie("http://127.0.0.1:9/health", "", 5, 1.0)
        assert resumo["n"] == 5
        assert resumo["codigos"] == {200: 5}
        assert resumo["p50_ms"] == 2.0 and resumo["p95_ms"] == 2.0
        assert resumo["max_ms"] == 2.0 and len(chamadas) == 5

    def test_codigos_diferentes_sao_contados_a_parte(self, monkeypatch) -> None:
        fila = [200, 200, 500, 500, 200]

        def _falsa(url, api_key, timeout):
            return (1.5, fila.pop(0), True)

        monkeypatch.setattr(io_probe, "_uma_requisicao", _falsa)
        resumo = io_probe.serie("http://127.0.0.1:9/health", "", 5, 1.0)
        assert resumo["codigos"] == {200: 3, 500: 2}
        assert resumo["p50_ms"] == 1.5

    def test_intervalo_dorme_entre_requisicoes(self, monkeypatch) -> None:
        """--intervalo respeita o rate limit: um sleep por requisição."""
        chamadas: list = []
        dormidas: list = []
        monkeypatch.setattr(
            io_probe, "_uma_requisicao", _falso_uma_requisicao(chamadas)
        )
        monkeypatch.setattr(io_probe.time, "sleep", dormidas.append)
        io_probe.serie("http://127.0.0.1:9/health", "", 3, 1.0, intervalo=0.5)
        assert dormidas == [0.5, 0.5, 0.5]


class TestConcorrente:
    def test_mede_em_threads_e_devolve_rps(self, monkeypatch) -> None:
        chamadas: list = []
        monkeypatch.setattr(
            io_probe, "_uma_requisicao", _falso_uma_requisicao(chamadas, ms=1.0)
        )
        resumo = io_probe.concorrente(
            "http://127.0.0.1:9/health", "", 6, 3, 1.0
        )
        assert resumo["n"] == 6 and resumo["threads"] == 3
        assert resumo["codigos"] == {200: 6}
        assert resumo["p50_ms"] == 1.0 and resumo["max_ms"] == 1.0
        assert resumo["rps"] > 0
        assert len(chamadas) == 6


class TestResumo:
    def test_sem_amostras_zera_tudo(self) -> None:
        resumo = io_probe._resumo([], {})
        assert resumo == {"n": 0, "p50_ms": 0.0, "p95_ms": 0.0,
                          "max_ms": 0.0, "codigos": {}}

    def test_medianas_de_amostras_conhecidas(self) -> None:
        resumo = io_probe._resumo([1.0, 2.0, 3.0, 4.0], {200: 4})
        assert resumo["n"] == 4
        assert resumo["p50_ms"] == 2.5  # mediana de 1..4
        assert resumo["p95_ms"] == 4.0 and resumo["max_ms"] == 4.0


class TestChaveApiDeArquivo:
    def test_lê_a_chave_do_env_com_aspas(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        env.write_text(
            '# comentário\nOUTRA_CHAVE=x\nOD_API_KEY="abc123"\n', encoding="utf-8"
        )
        assert io_probe._chave_api_de_arquivo(str(env)) == "abc123"

    def test_env_sem_a_chave_devolve_vazio(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        env.write_text("GEMINI_API_KEY=xyz\n", encoding="utf-8")
        assert io_probe._chave_api_de_arquivo(str(env)) == ""

    def test_arquivo_inexistente_nao_quebra(self, tmp_path: Path) -> None:
        """O serviço do monitor não pode morrer por .env ausente."""
        assert io_probe._chave_api_de_arquivo(str(tmp_path / "nao-existe.env")) == ""


class TestCustoDeLoop:
    def test_mede_n_criacoes_de_event_loop(self) -> None:
        medido = io_probe.custo_de_loop(n=3)
        assert medido["loops"] == 3
        assert medido["por_loop_us"] >= 0


class TestMainDaSonda:
    """main() com argv fake e _uma_requisicao dublê — sempre em tmp_path."""

    def test_json_serie_sem_rede_e_grava_subdiretorio_novo(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        chamadas: list = []
        monkeypatch.setattr(
            io_probe, "_uma_requisicao", _falso_uma_requisicao(chamadas)
        )
        env = tmp_path / ".env"
        env.write_text('OD_API_KEY="segredo-do-dono"\n', encoding="utf-8")
        destino = tmp_path / "monitor" / "io.json"  # subdir ainda não existe
        rc = io_probe.main([
            "--url", "http://127.0.0.1:9/health",
            "--api-key-file", str(env),
            "--series", "2",
            "--concurrentes", "0",
            "--gravar", str(destino),
            "--json",
        ])
        assert rc == 0
        dados = json.loads(capsys.readouterr().out)
        assert dados["serie"]["n"] == 2
        assert dados["concorrente"] == {}  # --concurrentes 0 desliga
        assert len(chamadas) == 2
        assert {c["api_key"] for c in chamadas} == {"segredo-do-dono"}
        gravado = json.loads(destino.read_text(encoding="utf-8"))
        assert gravado["versao"] == 1
        assert gravado["alvos"]["/health"]["serie"]["n"] == 2
        assert not list(destino.parent.glob("*.tmp"))  # gravação atômica

    def test_saida_humana_com_concorrentes_e_chave_direta(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        chamadas: list = []
        monkeypatch.setattr(
            io_probe, "_uma_requisicao", _falso_uma_requisicao(chamadas)
        )
        rc = io_probe.main([
            "--url", "http://127.0.0.1:9/health",
            "--api-key", "chave-direta",
            "--series", "1",
            "--concurrentes", "4",
            "--threads", "2",
        ])
        assert rc == 0
        saida = capsys.readouterr().out
        assert "GET http://127.0.0.1:9/health" in saida
        assert "série" in saida and "p50=" in saida
        assert "concorrente" in saida and "req/s" in saida
        assert len(chamadas) == 5  # 1 série + 4 concorrentes
        assert {c["api_key"] for c in chamadas} == {"chave-direta"}

    def test_grava_com_rotulo_explicito_e_preserva_o_alvo_anterior(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        chamadas: list = []
        monkeypatch.setattr(
            io_probe, "_uma_requisicao", _falso_uma_requisicao(chamadas)
        )
        destino = tmp_path / "io.json"
        destino.write_text(
            json.dumps({"versao": 1, "alvos": {"site": {"url": "http://x/"}}}),
            encoding="utf-8",
        )
        rc = io_probe.main([
            "--url", "http://127.0.0.1:9/health",
            "--series", "1",
            "--concurrentes", "0",
            "--gravar", str(destino),
            "--rotulo", "health-dono",
        ])
        assert rc == 0
        saida = capsys.readouterr().out
        assert "gravado:" in saida and "health-dono" in saida
        assert "concorrente desligada" in saida
        dados = json.loads(destino.read_text(encoding="utf-8"))
        assert set(dados["alvos"]) == {"site", "health-dono"}  # merge preservou
        assert dados["alvos"]["health-dono"]["url"] == "http://127.0.0.1:9/health"

    def test_url_invalida_usa_rotulo_alvo_e_regrava_json_corrompido(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        chamadas: list = []
        monkeypatch.setattr(
            io_probe, "_uma_requisicao", _falso_uma_requisicao(chamadas)
        )
        destino = tmp_path / "io.json"
        destino.write_text("{corrompido", encoding="utf-8")
        rc = io_probe.main([
            "--url", "http://[::1",
            "--series", "1",
            "--concurrentes", "0",
            "--gravar", str(destino),
            "--json",
        ])
        assert rc == 0
        dados = json.loads(capsys.readouterr().out)
        assert dados["url"] == "http://[::1"
        gravado = json.loads(destino.read_text(encoding="utf-8"))
        # urlsplit falhou → rótulo "alvo"; o lixo anterior foi regravado
        assert list(gravado["alvos"]) == ["alvo"]
        assert gravado["alvos"]["alvo"]["url"] == "http://[::1"
        assert not list(chamadas[i]["url"] for i in range(0))  # sem requisição real


# ---------------------------------------------------------------------------
#  baixar_resto_lista — lote do resto da playlist (pipeline injetado)
# ---------------------------------------------------------------------------

#: Acervo de partida: as duas faixas abaixo já existem (nada é baixado).
ACERVO_JA_BAIXADO = {
    "a": {"caminho": "/m/1.mp3", "artista": "Legiao Urbana", "titulo": "Faixa 1"},
    "b": {"caminho": "/m/2.mp3", "artista": "Legiao Urbana", "titulo": "Faixa 2"},
}


def _lista_do_dono(n_pendentes: int, com_uma_repetida: bool) -> list[dict]:
    """Lista fake do Legião: 1 repetida (se pedido) + N pendentes."""
    entradas: list[dict] = []
    if com_uma_repetida:
        entradas.append({
            "url": "https://example.test/repetida",
            "title": "Legiao Urbana - Faixa 1 (Clipe Oficial)",
        })
    # pendentes numeradas A PARTIR DE 2 quando há repetida: senão a
    # "Faixa 1" da lista casa por título com a repetida/acervo e some
    # na dedup (_parece_repetida), quebrando a contagem do lote.
    inicio = 2 if com_uma_repetida else 1
    entradas += [
        {"url": f"https://example.test/faixa{i}",
         "title": f"Legiao Urbana - Faixa {i}"}
        for i in range(inicio, inicio + n_pendentes)
    ]
    return entradas


@pytest.fixture()
def cenario_baixar(tmp_path: Path, monkeypatch):
    """RAIZ/LOG/PLAYLIST do script em tmp + dublês do radio_link.

    Nada de rede, pipeline ou notificação real; o `carrega_env` grava no
    processo chaves de um .env fake, então o os.environ é restaurado ao
    final (a suíte não pode herdar nada dele).
    """
    snapshot = dict(os.environ)
    raiz = tmp_path / "raiz"
    raiz.mkdir()
    (raiz / ".env").write_text(
        "# comentário com =\n"
        "\n"
        "SEM_IGUAL\n"
        'OD_TESTE_BRL="valor com aspas"\n'
        "OD_TESTE_BRL_SEM_AS='solo'\n"
        "OD_TESTE_BRL_EXISTE=do_env\n",
        encoding="utf-8",
    )
    for chave in ("OD_TESTE_BRL", "OD_TESTE_BRL_SEM_AS", "OD_TESTE_BRL_EXISTE"):
        os.environ.pop(chave, None)

    monkeypatch.setattr(brl, "RAIZ", raiz)
    monkeypatch.setattr(brl, "LOG", tmp_path / "logs" / "lista.log")
    monkeypatch.setattr(brl, "PLAYLIST", "https://example.test/playlist?list=FAKE")

    avisos: list[str] = []
    estado: dict = {
        "entradas": [], "acervo": {}, "codigos": [], "falha": None,
        "lotes": [], "travas": 0, "playlist": None,
    }

    def extrair(_playlist: str) -> list[dict]:
        estado["playlist"] = _playlist
        return list(estado["entradas"])

    def musicas(_banco) -> dict:
        return dict(estado["acervo"])

    def rodar(urls, timeout=None) -> int:
        estado["lotes"].append({"urls": list(urls), "timeout": timeout})
        if estado["falha"] is not None:
            falha, estado["falha"] = estado["falha"], None
            raise falha
        codigo = estado["codigos"].pop(0) if estado["codigos"] else 0
        for url in urls:
            estado["acervo"][url] = {
                "caminho": url, "artista": "Legiao Urbana",
                "titulo": f"nova {len(estado['acervo'])}",
            }
        return codigo

    @contextmanager
    def trava():
        estado["travas"] += 1
        yield

    monkeypatch.setattr(rl, "extrair_entradas", extrair)
    monkeypatch.setattr(rl, "_musicas_do_acervo", musicas)
    monkeypatch.setattr(rl, "rodar_pipeline", rodar)
    monkeypatch.setattr(rl, "trava_pipeline", trava)
    monkeypatch.setattr(rl, "notificar_dono", avisos.append)

    yield SimpleNamespace(raiz=raiz, avisos=avisos, estado=estado)

    os.environ.clear()
    os.environ.update(snapshot)


def _preparar(cenario, entradas, acervo=None, codigos=None, falha=None) -> None:
    """Carrega o cenário fake no estado compartilhado do fixture."""
    cenario.estado["entradas"] = entradas
    cenario.estado["acervo"] = dict(acervo or {})
    cenario.estado["codigos"] = list(codigos or [])
    cenario.estado["falha"] = falha


class TestCarregaEnv:
    def test_lê_o_dot_env_e_preserva_o_ja_definido(
        self, cenario_baixar, monkeypatch
    ) -> None:
        monkeypatch.setenv("OD_TESTE_BRL_EXISTE", "nao_muda")
        brl.carrega_env()
        assert os.environ["OD_TESTE_BRL"] == "valor com aspas"
        assert os.environ["OD_TESTE_BRL_SEM_AS"] == "solo"
        # setdefault nunca sobrescreve o que o processo já tem
        assert os.environ["OD_TESTE_BRL_EXISTE"] == "nao_muda"

    def test_sem_dot_env_propaga_o_erro(self, tmp_path: Path, monkeypatch) -> None:
        """Sem .env o script falha alto (não segue com chave vazia)."""
        vazio = tmp_path / "sem-env"
        vazio.mkdir()
        monkeypatch.setattr(brl, "RAIZ", vazio)
        with pytest.raises(FileNotFoundError):
            brl.carrega_env()


class TestRegistra:
    def test_carimbo_de_tempo_e_acumulo_no_log(self, cenario_baixar) -> None:
        brl.LOG.parent.mkdir(parents=True, exist_ok=True)
        brl.registra("primeira linha")
        brl.registra("segunda linha")
        linhas = brl.LOG.read_text(encoding="utf-8").splitlines()
        assert len(linhas) == 2
        assert re.match(
            r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \| primeira linha$", linhas[0]
        )
        assert linhas[1].endswith("| segunda linha")


class TestMainDoRestoDaLista:
    def test_lista_vazia_avisa_e_para_sem_baixar(self, cenario_baixar) -> None:
        _preparar(cenario_baixar, entradas=[])
        rc = brl.main()
        assert rc == 1
        assert cenario_baixar.avisos == [
            "Lista do Legiao: extracao vazia, nada a fazer."
        ]
        # nenhum lote, nenhuma trava, playlist fake passou pela extração
        assert cenario_baixar.estado["lotes"] == []
        assert cenario_baixar.estado["travas"] == 0
        assert (
            cenario_baixar.estado["playlist"]
            == "https://example.test/playlist?list=FAKE"
        )
        log = brl.LOG.read_text(encoding="utf-8")
        assert "=== inicio: resto da lista do Legiao Urbana ===" in log
        assert "entradas na lista: 0" in log

    def test_tudo_repetido_nao_roda_nenhum_lote(self, cenario_baixar) -> None:
        _preparar(
            cenario_baixar,
            entradas=_lista_do_dono(2, com_uma_repetida=False),
            acervo=ACERVO_JA_BAIXADO,
        )
        rc = brl.main()
        assert rc == 0
        assert cenario_baixar.avisos == [
            "Legiao Urbana: 0 faixa(s) a baixar (2 ja estavam no acervo)."
            " Lotes de 0."
        ]
        assert cenario_baixar.estado["lotes"] == []
        log = brl.LOG.read_text(encoding="utf-8")
        assert "ja no acervo (puladas): 2 | a baixar: 0" in log
        assert "nada novo; fim" in log

    def test_pendentes_vao_em_lotes_e_acervo_cresce(
        self, cenario_baixar
    ) -> None:
        """12 pendentes + 1 repetida → lotes de 10 e 2; acervo 1 → 13."""
        _preparar(
            cenario_baixar,
            entradas=_lista_do_dono(12, com_uma_repetida=True),
            acervo={"rep": {"caminho": "/m/rep.mp3", "artista": "Legiao Urbana",
                            "titulo": "Faixa 1"}},
        )
        rc = brl.main()
        assert rc == 0
        estado = cenario_baixar.estado
        assert [len(l["urls"]) for l in estado["lotes"]] == [10, 2]
        assert estado["travas"] == 2
        t10, t2 = rl.timeout_do_lote(10), rl.timeout_do_lote(2)
        assert estado["lotes"][0]["timeout"] == t10
        assert estado["lotes"][1]["timeout"] == t2
        assert cenario_baixar.avisos[0] == (
            "Legiao Urbana: 12 faixa(s) a baixar (1 ja estavam no acervo)."
            " Lotes de 10."
        )
        assert cenario_baixar.avisos[1] == (
            "Legiao Urbana (resto da lista) concluido sem falhas: 2 lote(s),"
            " acervo agora com 13 faixas."
            " Detalhe: logs/radio_link_lista_legiao_v2.log"
        )
        log = brl.LOG.read_text(encoding="utf-8")
        linhas = [
            "ja no acervo (puladas): 1 | a baixar: 12",
            "lote 1: faixas 1-10 (timeout %ds)" % t10,
            "lote 1 codigo=0 | acervo agora 11 (+10)",
            "lote 2: faixas 11-12 (timeout %ds)" % t2,
            "lote 2 codigo=0 | acervo agora 13 (+2)",
            "=== fim: 2 lote(s), 0 com falha, acervo 13 ===",
        ]
        posicoes = [log.index(l) for l in linhas]
        assert posicoes == sorted(posicoes)  # ordem cronológica no log

    def test_lote_que_falha_nao_derruba_o_seguinte(
        self, cenario_baixar
    ) -> None:
        _preparar(
            cenario_baixar,
            entradas=_lista_do_dono(12, com_uma_repetida=False),
            falha=RuntimeError("pipeline quebrou"),
        )
        rc = brl.main()
        assert rc == 1  # houve falha, mas o lote 2 rodou
        assert len(cenario_baixar.estado["lotes"]) == 2
        assert cenario_baixar.estado["travas"] == 2
        assert cenario_baixar.avisos[1].startswith(
            "Legiao Urbana (resto da lista) concluido com falhas: 2 lote(s),"
            " acervo agora com 2 faixas."
        )
        log = brl.LOG.read_text(encoding="utf-8")
        assert "lote 1 FALHOU: RuntimeError: pipeline quebrou" in log
        assert "lote 2 codigo=0 | acervo agora 2 (+2)" in log
        assert "=== fim: 2 lote(s), 1 com falha, acervo 2 ===" in log

    def test_codigo_diferente_de_zero_conta_como_falha(
        self, cenario_baixar
    ) -> None:
        _preparar(
            cenario_baixar,
            entradas=_lista_do_dono(1, com_uma_repetida=False),
            codigos=[3],
        )
        rc = brl.main()
        assert rc == 1
        assert cenario_baixar.avisos[1].startswith(
            "Legiao Urbana (resto da lista) concluido com falhas: 1 lote(s),"
            " acervo agora com 1 faixas."
        )
        log = brl.LOG.read_text(encoding="utf-8")
        assert "lote 1 codigo=3 | acervo agora 1 (+1)" in log
        assert "=== fim: 1 lote(s), 1 com falha, acervo 1 ===" in log


# ---------------------------------------------------------------------------
#  gerar_ecossistema — gerador das 5 páginas do Ecossistema
# ---------------------------------------------------------------------------


class TestGerarEcossistema:
    def test_template_comum_para_as_cinco_paginas(self) -> None:
        """Uma entrada por frente, todas com título/conteúdo próprios."""
        assert len(ge.PAGINAS) == 5
        nomes = [p[0] for p in ge.PAGINAS]
        assert len(set(nomes)) == 5
        assert all(nome.endswith(".html") for nome in nomes)
        assert ge.SITE.name == "site"
        assert '<div class="nav-panel" id="navPanel">' in ge.NAV
        assert 'id="toTop"' in ge.RODAPE
        for _nome, titulo, kicker, h1, tagline, corpo in ge.PAGINAS:
            assert titulo and kicker and h1 and tagline
            assert corpo.lstrip().startswith("<section>")
            assert "</section>" in corpo

    def test_main_grava_as_cinco_paginas_com_nav_e_rodape(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        site = tmp_path / "site"
        site.mkdir()  # o gerador não cria o diretório (site/ existe no repo)
        monkeypatch.setattr(ge, "SITE", site)
        assert ge.main() == 0
        assert sorted(p.name for p in site.glob("*.html")) == sorted(
            p[0] for p in ge.PAGINAS
        )
        assert "5 páginas geradas" in capsys.readouterr().out
        for nome, titulo, kicker, h1, tagline, _corpo in ge.PAGINAS:
            html = (site / nome).read_text(encoding="utf-8")
            assert f"<title>{titulo}</title>" in html
            assert f"<h1>{h1}</h1>" in html
            assert f'<div class="tagline">{tagline}</div>' in html
            # nav e rodapé idênticos ao template comum (a regra do dono)
            assert ge.NAV in html and ge.RODAPE in html
            assert f'content="{kicker} — Omega Drakon. {tagline}."' in html

    def test_geracao_e_idempotente(self, tmp_path: Path, monkeypatch) -> None:
        site = tmp_path / "site"
        site.mkdir()
        monkeypatch.setattr(ge, "SITE", site)
        ge.main()
        antes = {p.name: p.read_bytes() for p in site.glob("*.html")}
        ge.main()
        depois = {p.name: p.read_bytes() for p in site.glob("*.html")}
        assert depois == antes and len(depois) == 5

    def test_bloco_de_script_redireciona_a_escrita_para_tmp(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """`python tools/gerar_ecossistema.py` roda SEM tocar no site real."""
        site_real = Path(ge.SITE)
        antes = {p.name: p.stat().st_mtime_ns for p in site_real.glob("*.html")}
        escrita_original = Path.write_text

        def para_tmp(self, data, encoding=None, errors=None, newline=None):
            alvo = tmp_path / self.name if site_real in self.parents else self
            return escrita_original(
                alvo, data, encoding=encoding, errors=errors, newline=newline
            )

        monkeypatch.setattr(Path, "write_text", para_tmp)
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_path(str(Path(ge.__file__)), run_name="__main__")
        assert excinfo.value.code == 0
        assert len(list(tmp_path.glob("*.html"))) == 5
        assert "5 páginas geradas" in capsys.readouterr().out
        depois = {p.name: p.stat().st_mtime_ns for p in site_real.glob("*.html")}
        assert depois == antes  # site/ real intocado
