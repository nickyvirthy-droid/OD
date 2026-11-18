"""
OMEGA DRAKON • TESTS
Módulo: tests/test_corpus_frases_dono.py
Descrição: Corpus de FRASES REAIS do dono como teste de detecção de intenção.

           Aberto como P0 nº 2 da revisão de 17/11 (docs/ANALISE_SISTEMA_TODO.md):
           "os buracos de casamento só aparecem em uso (disco, papéis, rádio) e
           cada um custou um turno de conserto". As frases abaixo são cópias
           LITERAIS do que o dono digitou no chat — cada uma com o arquivo de
           `iniciar/` onde está registrada, para o corpus não virar invenção.

           Três guardas:
             1. `test_frase_esta_registrada` — a frase existe MESMO no arquivo
                de origem citado (impede frase inventada de entrar no corpus);
             2. `test_frase_real_casa_a_intencao` — a rota/ação esperada,
                medida no código atual (a linha de base do fast path);
             3. `test_conversa_nao_e_sequestrada` — conversa comum NÃO pode ser
                capturada por um fast path (o defeito oposto: responder ação
                para quem só cumprimentou).

           Como crescer: toda nova frase do dono que revelar um buraco entra
           aqui, verbatim, com a origem — é o que transforma "achismo" em
           regressão.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.intents import detect_action_intent
from core.orchestrator import detect_datetime_question

RAIZ = Path(__file__).resolve().parents[1]

#: (frase verbatim, ação esperada, arquivo de `iniciar/` onde ela está, params)
FRASES_REAIS: list[tuple[str, str, str, dict]] = [
    ("qual o uso de disco", "disk_usage",
     "iniciar/2026-11-14_conversa_omegadrakon.md", {}),
    ("quais os tipos de usuários de OD", "role_list",
     "iniciar/2026-11-14_conversa_omegadrakon.md", {}),
    ("quais portas estão abertas?", "listening_ports",
     "iniciar/2026-09-26_conversa_omegadrakon.md", {}),
    ("qual o ip do servidor?", "ip_address",
     "iniciar/2026-09-26_conversa_omegadrakon.md", {}),
    ("temperatura do servidor", "cpu_temp",
     "iniciar/2026-09-28_conversa_omegadrakon.md", {}),
    ("quanto esta o dolar hoje", "exchange_rate",
     "iniciar/2026-11-11_conversa_omegadrakon.md", {"moeda": "dolar"}),
    ("quanto está o dólar", "exchange_rate",
     "iniciar/2026-10-13_conversa_omegadrakon.md", {"moeda": "dólar"}),
    ("clima em campo grande hoje", "weather_city",
     "iniciar/2026-09-28_conversa_omegadrakon.md", {"city": "campo grande"}),
    ("temperatura em são paulo", "weather_city",
     "iniciar/2026-10-10_conversa_omegadrakon.md", {"city": "são paulo"}),
    ("quais tomadas estão ligadas", "ha_lights",
     "iniciar/2026-09-29_conversa_omegadrakon.md", {}),
    ("aumenta o volume", "radio_volume",
     "iniciar/2026-11-10_conversa_omegadrakon.md", {"volume": "up"}),
    ("abaixa o volume", "radio_volume",
     "iniciar/2026-11-10_conversa_omegadrakon.md", {"volume": "down"}),
    ("para a rádio", "radio_stop",
     "iniciar/2026-11-10_conversa_omegadrakon.md", {}),
]

#: Conversa comum — o fast path NÃO pode sequestrar (devolver None).
FRASES_CONVERSA: list[tuple[str, str]] = [
    ("bom dia", "iniciar/2026-11-14_conversa_omegadrakon.md"),
    # Pergunta de acompanhamento do próprio dono (txt.txt, 18/11): é
    # conversa/estado interno, não uma ação do catálogo.
    ("onde foi parar a lista de musicas do raul seixas", "txt.txt"),
]


@pytest.mark.parametrize("frase,acao,origem,params", FRASES_REAIS)
def test_frase_esta_registrada(frase: str, acao: str, origem: str, params: dict) -> None:
    """A frase do corpus existe LITERALMENTE na origem citada.

    O `txt.txt` é canal efêmero (regra 20): só aceita como origem quando a
    frase ainda está lá; o corpus durável aponta para `iniciar/`.
    """
    caminho = RAIZ / origem
    assert caminho.exists(), f"origem sumiu: {origem}"
    assert frase in caminho.read_text(encoding="utf-8", errors="ignore"), (
        f"frase não está registrada em {origem}: {frase!r}"
    )


@pytest.mark.parametrize("frase,acao,origem,params", FRASES_REAIS)
def test_frase_real_casa_a_intencao(
    frase: str, acao: str, origem: str, params: dict
) -> None:
    """Frase real do dono → ação do catálogo (a linha de base do fast path)."""
    resultado = detect_action_intent(frase)
    assert resultado is not None, f"caiu no LLM: {frase!r}"
    nome, recebidos = resultado
    assert nome == acao, f"{frase!r} virou {nome}, esperado {acao}"
    # Params semânticos: os que a action usa de verdade (slug/volume), não o
    # dicionário inteiro — entity_id do HA é resolvido depois.
    for chave, valor in params.items():
        assert recebidos.get(chave) == valor, (
            f"{frase!r}: {chave}={recebidos.get(chave)!r}, esperado {valor!r}"
        )


@pytest.mark.parametrize("frase,origem", FRASES_CONVERSA)
def test_frase_de_conversa_esta_registrada(frase: str, origem: str) -> None:
    caminho = RAIZ / origem
    assert caminho.exists(), f"origem sumiu: {origem}"
    assert frase in caminho.read_text(encoding="utf-8", errors="ignore")


@pytest.mark.parametrize("frase,origem", FRASES_CONVERSA)
def test_conversa_nao_e_sequestrada(frase: str, origem: str) -> None:
    """Conversa comum não pode virar ação: o dono só cumprimentou/perguntou."""
    assert detect_action_intent(frase) is None, (
        f"fast path sequestrou conversa: {frase!r}"
    )


class TestOutrosFastpaths:
    """As perguntas de hora/data têm etapa própria no pipeline (datetime),
    não no detector de ações — o corpus cobre as duas para não parecer
    buraco de intenção o que apenas mora em outro lugar."""

    def test_que_horas_sao_vai_para_datetime(self) -> None:
        # A etapa devolve a RESPOSTA pronta (ou None quando não é pergunta).
        resposta = detect_datetime_question("que horas são")
        assert resposta and "Agora são" in resposta

    def test_conversa_simples_nao_e_datetime(self) -> None:
        assert detect_datetime_question("bom dia") is None
