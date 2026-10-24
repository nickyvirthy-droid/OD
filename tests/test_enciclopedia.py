"""
OMEGA DRAKON • TESTES
Módulo: tests/test_enciclopedia.py
Descrição: Etapa 4.6 do orquestrador — Wikipédia offline (Kiwix) como
           fallback quando o RAG local não acha nada (parking lot §5,
           ideia do dono em 21/10: "'define dia' → o chat responde que
           dia é uma duração de 24 horas").

           O cliente Kiwix é FALSO em todos os testes (nenhuma chamada de
           rede): a escolha do hit (overlap de título), o orçamento do
           bloco, a degradação honesta (erro = block "") e a posição no
           pipeline (SÓ com RAG vazio) são as partes com contrato.
"""
from __future__ import annotations

import pytest

from memory.enciclopedia import (
    CABECALHO_BLOCO,
    Enciclopedia,
    ResultadoEnciclopedia,
    _tokens_titulo,
)


# ---------------------------------------------------------------------------
# Cliente falso (sem rede)
# ---------------------------------------------------------------------------

class _ClienteFalso:
    """KiwixClient falso: hits programados, sem urllib."""

    def __init__(self, hits=None, artigos=None, *, acervos=None,
                 falhar_busca=None, falhar_leitura=None) -> None:
        self.hits = hits if hits is not None else []
        self.artigos = artigos or {}
        self.acervos = acervos if acervos is not None else [{
            "nome": "wikipedia_pt_all", "content_id": "wikipedia_pt_all_mini_2026-05",
            "idioma": "por", "titulo": "Wikipédia",
        }]
        self.falhar_busca = falhar_busca
        self.falhar_leitura = falhar_leitura
        self.buscas: list[str] = []
        self.livros: list[str] = []
        self.leituras: list[str] = []

    def status(self, *, timeout_s=None):
        if self.falhar_busca is not None:
            raise self.falhar_busca
        return {"acervos": self.acervos, "total_artigos": 0, "acessivel": True}

    def buscar(self, pattern, quantidade=5, *, timeout_s=None, livro=""):
        self.buscas.append(pattern)
        self.livros.append(livro)
        if self.falhar_busca is not None:
            raise self.falhar_busca
        return {"pattern": pattern, "resultados": self.hits[:quantidade]}

    def ler(self, caminho, max_chars=8000, *, timeout_s=None):
        self.leituras.append(caminho)
        if self.falhar_leitura is not None:
            raise self.falhar_leitura
        artigo = self.artigos.get(caminho)
        if artigo is None:
            raise KeyError(caminho)
        texto = artigo["texto"]
        truncado = len(texto) > max_chars
        if truncado:
            texto = texto[:max_chars].rstrip() + " …[cortado]"
        return {
            "titulo": artigo.get("titulo", ""),
            "texto": texto,
            "caminho": caminho,
            "bytes": 0,
            "truncado": truncado,
        }


def _enc(cliente, **kw) -> Enciclopedia:
    return Enciclopedia(fabrica_cliente=lambda: cliente, **kw)


# ---------------------------------------------------------------------------
# Tokens de título (normalizador do overlap)
# ---------------------------------------------------------------------------

class TestTokensTitulo:
    def test_minusculas_e_acentos(self):
        assert _tokens_titulo("Fotossíntese") == {"fotossíntese"}

    def test_stopwords_de_titulo_nao_contam(self):
        # "Day" tem 3 letras; tokens com <= 2 chars ficam de fora.
        assert _tokens_titulo("O Dia") == {"dia"}


# ---------------------------------------------------------------------------
# Consulta — termos, escolha do hit e bloco
# ---------------------------------------------------------------------------

class TestConsulta:
    def test_saudacao_nao_consulta(self):
        """Sem termos de conteúdo não há consulta (saudação/comando)."""
        cliente = _ClienteFalso()
        r = _enc(cliente).consult("oi")
        assert r.block == "" and cliente.buscas == []

    def test_consulta_usa_termos_sem_stopwords(self):
        cliente = _ClienteFalso(hits=[{
            "titulo": "Dia", "caminho": "pt/Dia", "trecho": "", "palavras": 100,
        }], artigos={"pt/Dia": {"titulo": "Dia", "texto": "Unidade de tempo de 24 horas."}})
        r = _enc(cliente).consult("o que é um dia?")
        assert cliente.buscas == ["dia"]
        assert r.consulta_final == "dia"

    def test_busca_no_livro_pt_primeiro(self):
        """Com 2 ZIMs de idiomas distintos a busca é por livro (400 misto)."""
        cliente = _ClienteFalso(hits=[{
            "titulo": "Dia", "caminho": "pt/Dia", "trecho": "", "palavras": 100,
        }], artigos={"pt/Dia": {"titulo": "Dia", "texto": "24 horas."}})
        _enc(cliente).consult("define dia")
        assert cliente.livros == ["wikipedia_pt_all_mini_2026-05"]

    def test_cascata_pt_sem_hit_vai_para_o_en(self):
        """PT sem hit com overlap → reserva no acervo EN (mini tem menos)."""
        acervos = [
            {"nome": "wikipedia_pt_all", "content_id": "wikipedia_pt_all_mini_2026-05",
             "idioma": "por"},
            {"nome": "wikipedia_en_all", "content_id": "wikipedia_en_all_mini",
             "idioma": "eng"},
        ]
        cliente = _ClienteFalso(
            acervos=acervos,
            artigos={"en/Black_hole": {
                "titulo": "Black hole", "texto": "Region of spacetime.",
            }},
        )
        cliente.hits_por_livro = {
            "wikipedia_pt_all_mini_2026-05": [],  # PT mini: termo sem artigo
            "wikipedia_en_all_mini": [{
                "titulo": "Black hole", "caminho": "en/Black_hole",
                "trecho": "", "palavras": 100,
            }],
        }
        cliente.buscar = lambda pattern, quantidade=5, *, timeout_s=None, livro="": (
            cliente.buscas.append(pattern) or cliente.livros.append(livro) or {
                "pattern": pattern,
                "resultados": cliente.hits_por_livro.get(livro, [])[:quantidade],
            }
        )
        r = _enc(cliente).consult("black hole")
        assert cliente.livros == [
            "wikipedia_pt_all_mini_2026-05", "wikipedia_en_all_mini",
        ]
        assert r.titulo == "Black hole"

    def test_catalogo_indisponivel_busca_sem_filtro(self):
        """Catálogo fora: busca global (comportamento antigo) — não exceção."""
        cliente = _ClienteFalso(
            hits=[{"titulo": "Dia", "caminho": "pt/Dia", "trecho": "",
                   "palavras": 100}],
            artigos={"pt/Dia": {"titulo": "Dia", "texto": "24 horas."}},
            falhar_busca=None,
        )
        cliente.status = lambda *, timeout_s=None: (_ for _ in ()).throw(
            RuntimeError("catálogo fora")
        )
        r = _enc(cliente).consult("define dia")
        assert cliente.livros == [""]  # sem books.name
        assert r.titulo == "Dia"

    def test_bloco_tem_cabecalho_titulo_e_texto(self):
        cliente = _ClienteFalso(hits=[{
            "titulo": "Dia", "caminho": "pt/Dia", "trecho": "", "palavras": 100,
        }], artigos={"pt/Dia": {"titulo": "Dia", "texto": "Duração de 24 horas."}})
        r = _enc(cliente).consult("define dia")
        assert CABECALHO_BLOCO in r.block
        assert "[Dia] Duração de 24 horas." in r.block
        assert r.titulo == "Dia" and r.caminho == "pt/Dia"
        assert r.chars == len(r.block) and not r.truncado

    def test_maior_overlap_de_titulo_vence_ranking_do_kiwix(self):
        """O ranking cru é fraco ("day" → "Day After Day antes de Day)."""
        hits = [
            {"titulo": "Day After Day", "caminho": "en/Day_After_Day",
             "trecho": "", "palavras": 10},
            {"titulo": "Day", "caminho": "en/Day", "trecho": "", "palavras": 10},
        ]
        cliente = _ClienteFalso(hits=hits, artigos={
            "en/Day": {"titulo": "Day", "texto": "Period of 24 hours."},
        })
        r = _enc(cliente).consult("day")
        # 1ª leitura = tentativa de título direto no PT (404 no stub);
        # 2ª = o hit de maior overlap escolhido na busca EN.
        assert cliente.leituras[-1] == "en/Day"
        assert r.titulo == "Day"

    def test_sem_overlap_de_titulo_nada_e_injetado(self):
        """Artigo errado pior que silêncio: piso de overlap de título."""
        hits = [{"titulo": "Día tras día (album)", "caminho": "en/X",
                 "trecho": "", "palavras": 10}]
        cliente = _ClienteFalso(hits=hits)
        r = _enc(cliente).consult("gravidade")
        assert r.block == "" and r.titulo == ""
        # A única leitura é a tentativa de título direto (404 → stub KeyError);
        # o hit sem overlap NUNCA é lido.
        assert cliente.leituras == ["wikipedia_pt_all_mini_2026-05/Gravidade"]
        assert r.descartados_sem_overlap == 1 and r.candidatos == 1

    def test_truncamento_declarado(self):
        cliente = _ClienteFalso(hits=[{
            "titulo": "Dia", "caminho": "pt/Dia", "trecho": "", "palavras": 100,
        }], artigos={"pt/Dia": {"titulo": "Dia", "texto": "x" * 5000}})
        r = _enc(cliente, max_chars=300).consult("dia de 24 horas")
        assert r.truncado and r.block.endswith("…[cortado]")
        assert len(r.block) < 450


# ---------------------------------------------------------------------------
# Degradação honesta — erro vira block "", nunca exceção
# ---------------------------------------------------------------------------

class TestDegradacao:
    class _ErroKiwix(Exception):
        codigo = "kiwix_indisponivel"

    def test_busca_falha_devolve_vazio_com_erro(self):
        cliente = _ClienteFalso(falhar_busca=self._ErroKiwix("fora"))
        r = _enc(cliente).consult("define dia")
        assert r.block == "" and r.erro == "kiwix_indisponivel"

    def test_leitura_falha_devolve_vazio_com_erro(self):
        cliente = _ClienteFalso(
            hits=[{"titulo": "Dia", "caminho": "pt/Dia", "trecho": "",
                   "palavras": 10}],
            falhar_leitura=self._ErroKiwix("fora"),
        )
        r = _enc(cliente).consult("define dia")
        assert r.block == "" and r.erro == "kiwix_indisponivel"

    def test_resultado_padrao_e_dataclass_limpa(self):
        r = ResultadoEnciclopedia()
        assert r.block == "" and r.erro == "" and r.chars == 0


# ---------------------------------------------------------------------------
# Orquestrador — etapa 4.6 (posição: SÓ com RAG vazio)
# ---------------------------------------------------------------------------

class _ProviderCaptura:
    def __init__(self, reply: str = "resposta") -> None:
        self.name = "captura"
        self.prompts: list[str] = []

    async def generate(self, prompt: str, **kw):
        self.prompts.append(prompt)
        return "resposta do modelo"

    async def generate_stream(self, prompt: str, **kw):
        self.prompts.append(prompt)
        for parte in ("resposta ", "do modelo"):
            yield parte


class _EncFalsa:
    def __init__(self, block: str = "", erro: str = "", explodir=False) -> None:
        self.block = block
        self.erro = erro
        self.explodir = explodir
        self.consultas: list[str] = []

    def consult(self, pergunta: str) -> ResultadoEnciclopedia:
        self.consultas.append(pergunta)
        if self.explodir:
            raise RuntimeError("kiwix explodiu")
        return ResultadoEnciclopedia(
            consulta_original=pergunta, block=self.block, erro=self.erro
        )


def _orch(enc=None, rag=None):
    from core.orchestrator import Orchestrator

    return Orchestrator(
        providers=[_ProviderCaptura()], enciclopedia=enc, rag=rag
    )


class _RagFalso:
    """RAG stub: devolve o block programado e conta consultas."""

    def __init__(self, block: str = "") -> None:
        self._block = block
        self.consultas = 0

    def consult(self, pergunta, **kw):
        from memory.rag import ResultadoRAG

        self.consultas += 1
        return ResultadoRAG(consulta_original=pergunta, block=self._block)


class TestEtapa46Orquestrador:
    @pytest.mark.asyncio
    async def test_sem_enciclopedia_o_prompt_nao_muda(self):
        orch = _orch()
        r = await orch.process(
            "u1", "guardian", "o que é fotossíntese?",
            role="admin", persist=False,
        )
        assert "Wikipédia offline" not in r.prompt
        assert orch.metrics.snapshot()["enciclopedias"] == 0

    @pytest.mark.asyncio
    async def test_com_rag_vazio_a_enciclopedia_entra(self):
        enc = _EncFalsa(block=f"{CABECALHO_BLOCO}\n[Dia] 24 horas.")
        orch = _orch(enc=enc, rag=_RagFalso(block=""))
        r = await orch.process(
            "u2", "guardian", "define dia", role="admin", persist=False,
        )
        assert "Wikipédia offline" in r.prompt and "[Dia] 24 horas." in r.prompt
        m = orch.metrics.snapshot()
        assert m["enciclopedias"] == 1 and m["enciclopedia_blocos"] == 1

    @pytest.mark.asyncio
    async def test_com_rag_de_bloco_a_enciclopedia_fica_de_fora(self):
        """Memória interna > enciclopédia: duas fontes = alucinação."""
        enc = _EncFalsa(block="NÃO DEVERIA ESTAR AQUI")
        rag = _RagFalso(block="Acervo de referência (interno; …)")
        orch = _orch(enc=enc, rag=rag)
        r = await orch.process(
            "u3", "guardian", "o que é o orçamento?", role="admin",
            persist=False,
        )
        assert "NÃO DEVERIA ESTAR AQUI" not in r.prompt
        assert "Acervo de referência" in r.prompt
        assert enc.consultas == [] and rag.consultas == 1

    @pytest.mark.asyncio
    async def test_erro_da_enciclopedia_nao_derruba_o_chat(self):
        enc = _EncFalsa(explodir=True)
        orch = _orch(enc=enc)
        r = await orch.process(
            "u4", "guardian", "define dia", role="admin", persist=False,
        )
        assert r.route == "llm"
        assert "Wikipédia offline" not in r.prompt
        m = orch.metrics.snapshot()
        assert m["enciclopedias"] == 1 and m["enciclopedia_erros"] == 1

    @pytest.mark.asyncio
    async def test_bloco_vazio_conta_consulta_sem_bloco(self):
        enc = _EncFalsa(block="", erro="kiwix_indisponivel")
        orch = _orch(enc=enc)
        await orch.process(
            "u5", "guardian", "define dia", role="admin", persist=False,
        )
        m = orch.metrics.snapshot()
        assert m["enciclopedias"] == 1
        assert m["enciclopedia_blocos"] == 0 and m["enciclopedia_erros"] == 1

    @pytest.mark.asyncio
    async def test_stream_tambem_passa_pela_etapa_4_6(self):
        enc = _EncFalsa(block=f"{CABECALHO_BLOCO}\n[Gravity] gravidade.")
        orch = _orch(enc=enc, rag=_RagFalso(block=""))
        partes = []
        async for ev in orch.process_stream(
            "u6", "guardian", "o que é gravidade?", role="admin",
        ):
            if ev.get("type") == "done":
                partes.append(ev)
        assert partes and "Wikipédia offline" in orch._providers[0].prompts[-1]
        assert orch.metrics.snapshot()["enciclopedia_blocos"] == 1

    @pytest.mark.asyncio
    async def test_papel_user_tambem_recebe_bloco(self):
        """O acervo é PÚBLICO (Wikipédia) — diferente do RAG interno."""
        enc = _EncFalsa(block=f"{CABECALHO_BLOCO}\n[Dia] 24 horas.")
        orch = _orch(enc=enc, rag=_RagFalso(block=""))
        r = await orch.process(
            "u7", "guardian", "define dia", role="user", persist=False,
        )
        assert "Wikipédia offline" in r.prompt
