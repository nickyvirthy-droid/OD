"""Testes da lista paralela da letra — `integrations/radio_traducao.py`.

Pedido do dono (17/11/2026): "letra de musica internacional poderia ter uma
lista paralela com a tradução". O módulo traduz a letra do ar pela cadeia de
LLM do OD, com cache por (artista, título, hash da letra); nada de rede nos
testes — o provider é injetado.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integrations import radio_traducao as rt

LETRA = (
    "Hello darkness, my old friend\n"
    "I've come to talk with you again\n"
    "Because a vision softly creeping\n"
    "Left its seeds while I was sleeping"
)


class _Provider:
    """Dublê de provider de LLM: registra as chamadas e devolve o roteiro."""

    name = "fake"

    def __init__(self, respostas: list[object]) -> None:
        self.respostas = list(respostas)
        self.prompts: list[str] = []

    async def generate(self, prompt: str, **options: object) -> str:
        self.prompts.append(prompt)
        if not self.respostas:
            return ""
        item = self.respostas.pop(0)
        if isinstance(item, Exception):
            raise item
        return str(item)


def _traduzir(tmp_path: Path, letra: str = LETRA, *respostas: object) -> tuple[dict, _Provider, Path]:
    provider = _Provider(list(respostas))
    cache = tmp_path / "traducao.json"
    saida = rt.montar_traducao(
        "Simon & Garfunkel", "The Sound of Silence", letra,
        cache_arq=cache, provedores=[provider],
    )
    return saida, provider, cache


# ---------------------------------------------------------------------------
#  Contrato básico
# ---------------------------------------------------------------------------

def test_sem_letra_nao_chama_provider(tmp_path: Path) -> None:
    saida, provider, _ = _traduzir(tmp_path, "", "nada")
    assert saida == {"ok": False, "motivo": "sem_letra"}
    assert provider.prompts == []


def test_sem_titulo_nao_chama_provider(tmp_path: Path) -> None:
    provider = _Provider(["x"])
    saida = rt.montar_traducao("", "", LETRA, cache_arq=tmp_path / "c.json",
                               provedores=[provider])
    assert saida == {"ok": False, "motivo": "sem_letra"}
    assert provider.prompts == []


def test_letra_longa_nem_tenta(tmp_path: Path) -> None:
    saida, provider, _ = _traduzir(tmp_path, "a" * (rt.LIMITE_LETRA + 1), "x")
    assert saida == {"ok": False, "motivo": "letra_longa"}
    assert provider.prompts == []


def test_traducao_ok_grava_cache(tmp_path: Path) -> None:
    saida, provider, cache = _traduzir(tmp_path, LETRA, "Olá escuridão, minha velha amiga")
    assert saida == {"ok": True, "texto": "Olá escuridão, minha velha amiga",
                     "cache": False}
    assert len(provider.prompts) == 1
    dados = json.loads(cache.read_text(encoding="utf-8"))
    chave = rt.chave_do_cache("Simon & Garfunkel", "The Sound of Silence", LETRA)
    assert dados[chave]["texto"] == "Olá escuridão, minha velha amiga"
    assert dados[chave]["provedor"] == "fake"


def test_segunda_chamada_vem_do_cache_sem_provider(tmp_path: Path) -> None:
    _, _, cache = _traduzir(tmp_path, LETRA, "traduzida")
    provider = _Provider(["não deveria ser chamado"])
    saida = rt.montar_traducao("Simon & Garfunkel", "The Sound of Silence", LETRA,
                               cache_arq=cache, provedores=[provider])
    assert saida == {"ok": True, "texto": "traduzida", "cache": True}
    assert provider.prompts == []


def test_letra_diferente_invalida_a_traducao(tmp_path: Path) -> None:
    _, _, cache = _traduzir(tmp_path, LETRA, "traduzida")
    provider = _Provider(["outra versão"])
    saida = rt.montar_traducao("Simon & Garfunkel", "The Sound of Silence",
                               LETRA + "\n(extra)", cache_arq=cache,
                               provedores=[provider])
    assert saida["ok"] is True and saida["cache"] is False
    assert saida["texto"] == "outra versão"
    assert len(provider.prompts) == 1


# ---------------------------------------------------------------------------
#  Português não precisa de tradução
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("marca", ["JA_PT", "já_pt", "JA PT", "  JA_PT.  ", "ja_em_portugues"])
def test_letra_ja_em_portugues_nao_vira_traducao(marca: str, tmp_path: Path) -> None:
    saida, _, cache = _traduzir(tmp_path, LETRA, marca)
    assert saida == {"ok": False, "motivo": "ja_em_portugues"}
    dados = json.loads(cache.read_text(encoding="utf-8"))
    chave = rt.chave_do_cache("Simon & Garfunkel", "The Sound of Silence", LETRA)
    assert dados[chave]["motivo"] == "ja_em_portugues"


def test_ja_pt_fica_no_cache_sem_chamar_de_novo(tmp_path: Path) -> None:
    _, _, cache = _traduzir(tmp_path, LETRA, "JA_PT")
    provider = _Provider(["nada"])
    saida = rt.montar_traducao("Simon & Garfunkel", "The Sound of Silence", LETRA,
                               cache_arq=cache, provedores=[provider])
    assert saida == {"ok": False, "motivo": "ja_em_portugues"}
    assert provider.prompts == []


def test_traducao_de_texto_normal_em_ingles_nao_e_confundida_com_ja_pt(
    tmp_path: Path,
) -> None:
    saida, _, _ = _traduzir(tmp_path, LETRA, "Hello, darkness, minha velha amiga.")
    assert saida["ok"] is True


# ---------------------------------------------------------------------------
#  Cadeia de fallback e falhas
# ---------------------------------------------------------------------------

def test_provider_que_falha_cai_para_o_proximo(tmp_path: Path) -> None:
    ruim = _Provider([RuntimeError("cota estourada")])
    bom = _Provider(["tradução boa"])
    saida = rt.montar_traducao("A", "B", LETRA, cache_arq=tmp_path / "c.json",
                               provedores=[ruim, bom])
    assert saida == {"ok": True, "texto": "tradução boa", "cache": False}
    assert len(ruim.prompts) == 1 and len(bom.prompts) == 1


def test_resposta_vazia_cai_para_o_proximo(tmp_path: Path) -> None:
    vazio = _Provider([""])
    bom = _Provider(["tradução"])
    saida = rt.montar_traducao("A", "B", LETRA, cache_arq=tmp_path / "c.json",
                               provedores=[vazio, bom])
    assert saida["ok"] is True


def test_todos_falham_devolve_indisponivel_e_cacheia_negativo(tmp_path: Path) -> None:
    cache = tmp_path / "c.json"
    falha = _Provider([RuntimeError("boom")])
    saida = rt.montar_traducao("Simon & Garfunkel", "The Sound of Silence", LETRA,
                               cache_arq=cache, provedores=[falha], agora=1000.0)
    assert saida == {"ok": False, "motivo": "indisponivel"}
    assert len(falha.prompts) == 1

    # dentro dos 10 min: não martela a cota
    outro = _Provider(["nunca chamado"])
    saida = rt.montar_traducao("Simon & Garfunkel", "The Sound of Silence", LETRA,
                               cache_arq=cache, provedores=[outro],
                               agora=1000.0 + rt.TTL_FALHA_S - 1)
    assert saida == {"ok": False, "motivo": "indisponivel"}
    assert outro.prompts == []


def test_falha_expira_e_tenta_de_novo(tmp_path: Path) -> None:
    cache = tmp_path / "c.json"
    falha = _Provider([RuntimeError("boom")])
    rt.montar_traducao("Simon & Garfunkel", "The Sound of Silence", LETRA,
                       cache_arq=cache, provedores=[falha], agora=1000.0)
    provider = _Provider(["depois funcionou"])
    saida = rt.montar_traducao(
        "Simon & Garfunkel", "The Sound of Silence", LETRA,
        cache_arq=cache, provedores=[provider],
        agora=1000.0 + rt.TTL_FALHA_S + 1,   # passou a janela da falha
    )
    assert saida == {"ok": True, "texto": "depois funcionou", "cache": False}
    assert len(provider.prompts) == 1


def test_sem_provider_configurado_e_indisponivel(tmp_path: Path) -> None:
    saida = rt.montar_traducao("A", "B", LETRA, cache_arq=tmp_path / "c.json",
                               provedores=[])
    assert saida == {"ok": False, "motivo": "indisponivel"}


def test_cache_corrompido_nao_derruba(tmp_path: Path) -> None:
    cache = tmp_path / "c.json"
    cache.write_text("{isso não é json", encoding="utf-8")
    saida, provider, _ = _traduzir(tmp_path, LETRA, "tradução")
    assert saida["ok"] is True
    assert len(provider.prompts) == 1


def test_cache_ilegivel_nao_derruba(tmp_path: Path) -> None:
    cache = tmp_path / "c.json"
    cache.write_text("[]", encoding="utf-8")      # lista, não dict
    saida, _, _ = _traduzir(tmp_path, LETRA, "tradução")
    assert saida["ok"] is True


# ---------------------------------------------------------------------------
#  Prompt e cadeia
# ---------------------------------------------------------------------------

def test_prompt_leva_instrucao_musica_e_letra(tmp_path: Path) -> None:
    _, provider, _ = _traduzir(tmp_path, LETRA, "ok")
    prompt = provider.prompts[0]
    assert "português do Brasil" in prompt
    assert "JA_PT" in prompt
    assert "Simon & Garfunkel — The Sound of Silence" in prompt
    assert "Hello darkness" in prompt


def test_chave_do_cache_usa_artista_titulo_e_hash_da_letra() -> None:
    a = rt.chave_do_cache("Artista", "Título", "letra")
    b = rt.chave_do_cache("artista", "título ", "letra")
    c = rt.chave_do_cache("Artista", "Título", "letra nova")
    assert a == b
    assert a != c
    assert a.startswith("artista|título|")


def test_cadeia_respeita_a_ordem_configurada(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OD_TRADUCAO_PROVIDERS", "groq,local")
    monkeypatch.setenv("GROQ_API_KEY", "chave-de-teste")
    monkeypatch.setenv("OD_LLM_URL", "http://127.0.0.1:1")
    nomes = [p.name for p in rt._cadeia()]
    assert nomes == ["groq", "gemma-local"]


def test_cadeia_sem_chave_de_nuvem_so_fica_o_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OD_TRADUCAO_PROVIDERS", "gemini,groq,local")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("OD_LLM_URL", "http://127.0.0.1:1")
    nomes = [p.name for p in rt._cadeia()]
    assert nomes == ["gemma-local"]


def test_max_tokens_cabe_uma_letra_inteira() -> None:
    # letra de ~4 min ≈ 300 palavras ≈ 450 tokens; 1500 dá folga e não
    # deixa o modelo devolver metade da tradução.
    assert rt.MAX_TOKENS >= 1000
