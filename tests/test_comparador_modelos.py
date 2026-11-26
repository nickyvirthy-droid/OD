"""Comparador de modelos lado a lado (fila item 5, 26/11).

O que estava medido antes: "usar a melhor IA" era decidido por log e por um
benchmark de 05/11 — não havia como ver o MESMO prompt em duas IAs ao vivo.
Aqui ficam provados:

  * a cadeia real (`OD_CHAT_PROVIDERS`) é a fonte dos modelos oferecidos;
  * menos de 2 modelos é erro (não é comparação de nada);
  * os modelos rodam em PARALELO e cada um volta com a latência medida;
  * modelo que falha não derruba os outros — o erro é resultado;
  * timeout é teto POR MODELO (o local tem 240 s próprios);
  * o custo de máquina (CPU/RAM do servidor) é medido DURANTE cada chamada,
    com média/pico e delta de RAM, e sem `/proc` vira `None` sem quebrar;
  * as rotas do painel devolvem a lista e o resultado, e recusam pedido vazio;
  * o render puro dos cartões (node) escapa texto, mostra o vazio honesto e
    imprime o monitor de hardware.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from core import comparador_modelos as comp
from integrations.api.server import APIHandler, _ADMIN_PAGE_HTML


class _Provider:
    def __init__(self, nome: str, resposta: str = "ok", atraso: float = 0.0,
                 erro: Exception | None = None, modelo: str = "") -> None:
        self.name = nome
        self.model = modelo
        self._resposta = resposta
        self._atraso = atraso
        self._erro = erro
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self._atraso:
            await asyncio.sleep(self._atraso)
        if self._erro is not None:
            raise self._erro
        return self._resposta


def _cadeia() -> list[_Provider]:
    return [
        _Provider("gemini", "resposta do gemini", 0.06, modelo="gemini-3-flash"),
        _Provider("groq", "resposta do groq", 0.01),
        _Provider("gemma-local", "", erro=RuntimeError("llama-server fora")),
    ]


def _rodar(prompt: str = "Explique RAG em uma frase.", **kwargs):
    return asyncio.run(
        comp.comparar_async(prompt, providers=kwargs.pop("providers", _cadeia()), **kwargs)
    )


class TestListaDeModelos:
    def test_descreve_nome_e_modelo_da_cadeia(self) -> None:
        modelos = comp.modelos_disponiveis(_cadeia())
        assert [m["nome"] for m in modelos] == ["gemini", "groq", "gemma-local"]
        assert modelos[0]["modelo"] == "gemini-3-flash"
        assert modelos[1]["modelo"] == ""


class TestComparacao:
    def test_mesmo_prompt_em_paralelo_com_latencia(self) -> None:
        cadeia = _cadeia()
        r = _rodar(providers=cadeia)
        assert r["ok"] is True
        assert [m["nome"] for m in r["modelos"]] == ["gemini", "groq", "gemma-local"]
        # o MESMO prompt chegou em todos
        assert all(p.prompts == ["Explique RAG em uma frase."] for p in cadeia)
        # latências medidas por modelo (o gemini dormiu mais que o groq)
        gemini, groq = r["modelos"][0], r["modelos"][1]
        assert gemini["latencia_ms"] >= 50 and groq["latencia_ms"] >= 5
        assert gemini["latencia_ms"] > groq["latencia_ms"]
        assert gemini["resposta"] == "resposta do gemini"

    def test_paralelo_de_verdade_nao_soma_as_esperas(self) -> None:
        cadeia = [
            _Provider("a", "a", 0.15), _Provider("b", "b", 0.15),
        ]
        r = _rodar(providers=cadeia)
        soma = sum(m["latencia_ms"] for m in r["modelos"])
        # se fosse sequencial, o tempo de parede seria ~soma; em paralelo
        # o relógio de cada um corre junto (a soma passa de 300 ms, o
        # maior fica perto de 150 ms)
        assert max(m["latencia_ms"] for m in r["modelos"]) < soma * 0.75

    def test_falha_de_um_nao_derruba_os_outros(self) -> None:
        r = _rodar(providers=_cadeia())
        local = r["modelos"][2]
        assert local["ok"] is False
        assert "llama-server fora" in local["erro"]
        assert r["ok"] is True  # os outros dois responderam
        assert [m["resposta"] for m in r["modelos"][:2]] == [
            "resposta do gemini", "resposta do groq",
        ]

    def test_todos_falhando_devolve_ok_false(self) -> None:
        cadeia = [
            _Provider("a", erro=RuntimeError("caiu")),
            _Provider("b", "", modelo=""),
        ]
        r = _rodar(providers=cadeia)
        assert r["ok"] is False
        assert r["modelos"][1]["erro"] == "resposta vazia"
        assert r["modelos"][1]["ok"] is False

    def test_timeout_e_por_modelo(self) -> None:
        cadeia = [_Provider("lento", "x", 2.0), _Provider("rapido", "y")]
        r = _rodar(providers=cadeia, timeout_s=0.05)
        lento, rapido = r["modelos"]
        assert lento["ok"] is False and "tempo esgotado" in lento["erro"]
        assert rapido["ok"] is True and rapido["resposta"] == "y"

    def test_selecao_por_nome_preserva_a_ordem_da_cadeia(self) -> None:
        r = _rodar(providers=_cadeia(), nomes=["gemma-local", "gemini"])
        assert [m["nome"] for m in r["modelos"]] == ["gemma-local", "gemini"]


class TestMonitorDeHardware:
    def test_cpu_e_ram_medidas_durante_a_chamada(self) -> None:
        cadeia = [_Provider("lento", "x", 0.7), _Provider("rapido", "y", 0.02)]
        r = _rodar(providers=cadeia)
        lento, rapido = r["modelos"]
        hw = lento["hardware"]
        assert hw is not None
        assert 0.0 <= hw["cpu_pct_medio"] <= 100.0
        assert hw["cpu_pct_pico"] >= hw["cpu_pct_medio"]
        assert hw["amostras"] >= 2
        assert hw["ram_total_mb"] > 0 and hw["ram_usada_mb_pico"] > 0
        assert hw["ram_delta_mb_pico"] >= 0.0
        assert hw["nucleos"] >= 1 and hw["intervalo_ms"] == 250
        # chamada curta também tem medida (o delta da própria chamada)
        assert rapido["hardware"] is not None
        assert rapido["hardware"]["amostras"] >= 1

    def test_falha_e_timeout_tambem_levam_hardware(self) -> None:
        cadeia = [
            _Provider("quebrado", erro=RuntimeError("sem chave"), atraso=0.05),
            _Provider("lento", "x", 2.0),
        ]
        r = _rodar(providers=cadeia, timeout_s=0.2)
        assert all(m["hardware"] is not None for m in r["modelos"])
        assert r["modelos"][0]["erro"].startswith("RuntimeError")
        assert "tempo esgotado" in r["modelos"][1]["erro"]

    def test_sem_proc_hardware_e_none_e_comparacao_segue(self, monkeypatch) -> None:
        monkeypatch.setattr(comp, "_snapshot", lambda: None)
        r = _rodar(providers=_cadeia())
        assert r["ok"] is True
        assert [m["hardware"] for m in r["modelos"]] == [None, None, None]
        assert r["modelos"][0]["resposta"] == "resposta do gemini"


class TestPedidosInvalidos:
    def test_prompt_vazio(self) -> None:
        with pytest.raises(comp.ComparadorError, match="prompt vazio"):
            _rodar("   ")

    def test_prompt_longo_demais(self) -> None:
        with pytest.raises(comp.ComparadorError, match="acima de"):
            _rodar("x" * (comp.MAX_PROMPT + 1))

    def test_um_modelo_so_nao_e_comparacao(self) -> None:
        with pytest.raises(comp.ComparadorError, match="pelo menos 2"):
            _rodar(providers=_cadeia(), nomes=["gemini"])

    def test_modelo_desconhecido(self) -> None:
        with pytest.raises(comp.ComparadorError, match="indisponível"):
            _rodar(providers=_cadeia(), nomes=["gemini", "gpt-9"])

    def test_cadeia_com_menos_de_dois(self) -> None:
        with pytest.raises(comp.ComparadorError, match="menos de 2"):
            _rodar(providers=[_Provider("unico")])


class _RotaFalsa:
    """Self falso das rotas (mesmo padrão do painel do atualizador)."""

    def __init__(self, body: dict | None = None) -> None:
        self._body = body or {}
        self.chamadas: list[tuple[int, dict]] = []

    def _require_admin(self) -> None:
        pass

    def _has_body(self) -> bool:
        return bool(self._body)

    def _read_json(self) -> dict:
        return self._body

    def _json(self, status: int, payload: dict) -> None:
        self.chamadas.append((status, payload))


class TestRotas:
    def test_lista_modelos(self, monkeypatch) -> None:
        monkeypatch.setattr(
            comp, "modelos_disponiveis",
            lambda *a, **k: [{"nome": "gemini", "modelo": "g"}, {"nome": "groq", "modelo": ""}],
        )
        rota = _RotaFalsa()
        APIHandler.admin_comparador_modelos(rota)
        status, payload = rota.chamadas[0]
        assert status == 200 and payload["ok"] is True
        assert len(payload["modelos"]) == 2

    def test_comparar_recebe_lista_de_modelos(self, monkeypatch) -> None:
        capturado: dict = {}

        def fake(prompt, nomes=None, providers=None, timeout_s=90.0):
            capturado.update(prompt=prompt, nomes=nomes, timeout_s=timeout_s)
            return {"ok": True, "prompt": prompt, "modelos": [
                {"nome": "gemini", "ok": True, "resposta": "r", "latencia_ms": 10.0},
                {"nome": "groq", "ok": True, "resposta": "r", "latencia_ms": 20.0},
            ]}

        monkeypatch.setattr(comp, "comparar", fake)
        rota = _RotaFalsa(body={"prompt": "oi", "modelos": ["gemini", "groq"]})
        APIHandler.admin_comparador_comparar(rota)
        status, payload = rota.chamadas[0]
        assert status == 200 and payload["ok"] is True
        assert capturado == {"prompt": "oi", "nomes": ["gemini", "groq"], "timeout_s": 90.0}

    def test_aceita_modelos_em_texto_separado_por_virgula(self, monkeypatch) -> None:
        capturado: dict = {}
        monkeypatch.setattr(
            comp, "comparar",
            lambda prompt, nomes=None, providers=None, timeout_s=90.0:
                capturado.update(nomes=nomes) or {"ok": True, "modelos": []},
        )
        rota = _RotaFalsa(body={"prompt": "oi", "modelos": "gemini, groq"})
        APIHandler.admin_comparador_comparar(rota)
        assert capturado["nomes"] == ["gemini", "groq"]

    def test_pedido_invalido_devolve_400_com_detalhe(self, monkeypatch) -> None:
        monkeypatch.setattr(
            comp, "comparar",
            lambda *a, **k: (_ for _ in ()).throw(
                comp.ComparadorError("escolha pelo menos 2 modelos para comparar")
            ),
        )
        rota = _RotaFalsa(body={"prompt": "oi", "modelos": ["gemini"]})
        APIHandler.admin_comparador_comparar(rota)
        status, payload = rota.chamadas[0]
        assert status == 400 and payload["erro"] == "pedido_invalido"
        assert "pelo menos 2" in payload["detalhe"]

    def test_timeout_do_corpo_e_grampeado(self, monkeypatch) -> None:
        capturado: dict = {}
        monkeypatch.setattr(
            comp, "comparar",
            lambda prompt, nomes=None, providers=None, timeout_s=90.0:
                capturado.update(t=timeout_s) or {"ok": True, "modelos": []},
        )
        rota = _RotaFalsa(body={"prompt": "oi", "modelos": ["a", "b"], "timeout_s": 9999})
        APIHandler.admin_comparador_comparar(rota)
        assert capturado["t"] == 300.0


class TestPainel:
    def test_secao_e_rota_ligadas_no_html(self) -> None:
        assert "<h2>Comparador de modelos</h2>" in _ADMIN_PAGE_HTML
        assert 'id="cmp-prompt"' in _ADMIN_PAGE_HTML
        assert 'id="cmp-resultado"' in _ADMIN_PAGE_HTML
        assert "/admin/comparador/modelos" in _ADMIN_PAGE_HTML
        assert "/admin/comparador/comparar" in _ADMIN_PAGE_HTML
        assert "cmpLoad(); };" in _ADMIN_PAGE_HTML

    @staticmethod
    def _js() -> str:
        html = _ADMIN_PAGE_HTML
        return html[html.index("<script>") + len("<script>"):html.rindex("</script>")]

    _HARNESS = r"""
'use strict';
const fs = require('fs'), vm = require('vm');
const arquivo = process.argv[2];
function novoEl() {
  return { style: {}, dataset: {}, _attrs: {}, innerHTML: '', textContent: '',
    className: '', value: '', href: '', disabled: false,
    setAttribute(k, v) { this._attrs[k] = String(v); },
    addEventListener() {}, appendChild() {},
    classList: { toggle() {}, add() {}, remove() { return true; },
                 contains() { return false; } } };
}
const document = { getElementById() { return novoEl(); },
  querySelector() { return null; }, querySelectorAll() { return []; },
  createElement() { return novoEl(); }, addEventListener() {},
  documentElement: novoEl(), body: novoEl(), readyState: 'complete' };
const window = { confirm() { return true; }, alert() {}, scrollTo() {},
  matchMedia() { return { matches: true, addEventListener() {} }; } };
const localStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
const ctx = { document, window, localStorage, location: { href: '' },
  fetch: () => Promise.resolve({ ok: false, status: 401, json: async () => ({}) }),
  console, setInterval: () => 0, setTimeout: () => 0, clearTimeout: () => {} };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(arquivo, 'utf8'), ctx, { filename: arquivo });

console.log(JSON.stringify({
  vazio: ctx.cmpCartoesHtml([]),
  nulo: ctx.cmpCartoesHtml(null),
  hw: ctx.cmpHw({ cpu_pct_medio: 43.0, cpu_pct_pico: 61.5, ram_delta_mb_pico: 120.4,
    ram_pct_pico: 52.0, amostras: 2 }),
  hwNulo: ctx.cmpHw(null),
  hwVazio: ctx.cmpHw({}),
  cheio: ctx.cmpCartoesHtml([
    { nome: 'gemini', modelo: 'g-3', ok: true, resposta: '<b>oi</b> & tchau',
      latencia_ms: 1234.5,
      hardware: { cpu_pct_medio: 43.0, cpu_pct_pico: 61.5, ram_delta_mb_pico: 120.4,
        ram_pct_pico: 52.0, amostras: 2 } },
    { nome: 'groq', modelo: '', ok: false, erro: 'HTTP 429 <cota>', latencia_ms: 88 },
  ]),
}));
"""

    def test_cartoes_escapados_e_vazio_honesto(self, tmp_path: Path) -> None:
        node = shutil.which("node")
        if not node:  # pragma: no cover - máquina sem node
            return
        js = tmp_path / "admin_cmp.js"
        js.write_text(self._js(), encoding="utf-8")
        har = tmp_path / "har_cmp.js"
        har.write_text(self._HARNESS, encoding="utf-8")
        r = subprocess.run([node, str(har), str(js)], capture_output=True,
                           text=True, encoding="utf-8")
        assert r.returncode == 0, r.stderr[:800]
        d = json.loads(r.stdout.strip().splitlines()[-1])

        assert "nenhuma comparação ainda" in d["vazio"]
        assert "nenhuma comparação ainda" in d["nulo"]

        cheio = d["cheio"]
        # ordem: o primeiro modelo aparece antes do segundo
        assert cheio.index("gemini") < cheio.index("groq")
        # latência formatada (s acima de 1 s, ms abaixo)
        assert "1.23 s" in cheio and "88 ms" in cheio
        # resposta e erro escapados — nada de HTML cru do modelo no painel
        assert "&lt;b&gt;oi&lt;/b&gt; &amp; tchau" in cheio
        assert "<b>oi</b>" not in cheio
        assert "HTTP 429 &lt;cota&gt;" in cheio and "<cota>" not in cheio

        # monitor de hardware: formatação e ausência honesta
        assert "CPU 43.0%" in d["hw"] and "pico 61.5%" in d["hw"]
        assert "RAM +120 MB" in d["hw"] and "52% da RAM do servidor" in d["hw"]
        assert "2 amostras" in d["hw"]
        assert d["hwNulo"] == "" and d["hwVazio"] == ""
        # o cartão com hardware mostra o custo; o sem medição não inventa nada
        assert "CPU 43.0%" in cheio
        assert cheio.count("CPU ") == 1
