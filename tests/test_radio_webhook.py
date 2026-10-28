"""
OMEGA DRAKON • TESTS
Módulo: tests/test_radio_webhook.py
Descrição: Testes do webhook do locutor da rádio Nicky (Etapa D, 27/10) —
           montagem da fala portada do legado (probabilidades, ordem e
           pronúncia), fontes externas (RSS G1 e wttr.in) com parsing
           testável sem rede, geração atômica do MP3 e caminhos de erro
           do processar(). Tudo determinístico: rng, relógio, notícia e
           clima injetados — nenhum teste toca rede ou Piper.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - analise/Nicky Locutor/nicky-locutor/main.py (montagem da fala)
  - integrations/radio_webhook.py (módulo sob teste)
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pytest

from integrations.radio import _CONTEUDO
from integrations.radio_webhook import (
    _primeira_noticia,
    _texto_clima,
    clima_wttr,
    limpar_pronuncia,
    montar_locucao,
    noticia_g1,
    processar,
)


# ===========================================================================
# Dublês (nenhum teste do arquivo toca rede, banco real ou Piper)
# ===========================================================================

class RNGFalso:
    """RNG com roteiro: consome a lista e devolve 1.0 quando acaba.

    1.0 > qualquer probabilidade do legado → a montagem cai no caminho
    "nada aconteceu" por padrão; os testes de ramo explicitam os valores.
    """

    def __init__(self, valores: Optional[list[float]] = None) -> None:
        self._valores = list(valores or [])
        self.chamadas = 0

    def random(self) -> float:
        self.chamadas += 1
        if self._valores:
            return self._valores.pop(0)
        return 1.0


class DBFalso:
    """Banco de frases mínimo: devolve a PRIMEIRA frase de cada família.

    Compatível com o que frase_aleatoria/frase_formatada usam (db.scalar).
    """

    def __init__(self, frases: Optional[dict[str, list[str]]] = None) -> None:
        self.frases = frases if frases is not None else dict(_CONTEUDO)

    def scalar(self, sql: str) -> Any:
        for tabela, lista in self.frases.items():
            if f"FROM {tabela}" in sql:
                return lista[0] if lista else None
        return None


class TTSFalso:
    """PiperTTS mínimo: async synthesize_locucao_to_file que grava bytes."""

    def __init__(self, *, ok: bool = True, grava: bool = True,
                 explode: bool = False) -> None:
        self.ok = ok
        self.grava = grava
        self.explode = explode
        self.voz: Optional[str] = None
        self.texto: Optional[str] = None

    async def synthesize_locucao_to_file(
        self, text: str, output_path: Any, profile: Optional[str] = None,
    ) -> bool:
        self.texto = text
        self.voz = profile
        if self.explode:
            raise RuntimeError("piper morreu")
        if self.ok and self.grava:
            Path(output_path).write_bytes(b"ID3-musica-falsa")
        return self.ok


AGORA_FIXO = datetime(2026, 10, 27, 21, 35, tzinfo=ZoneInfo("America/Sao_Paulo"))

PAYLOAD = {
    "now_playing": {
        "duration": 200,
        "elapsed": 42,
        "song": {
            "artist": "Tim Maia",
            "title": "Azul da Cor do Mar",
            "custom_fields": {},
        },
    },
    "playing_next": {"song": {"artist": "Jorge Ben", "title": "Take It Easy"}},
}


# ===========================================================================
# Utilitários de pronúncia e fontes
# ===========================================================================

class TestLimparPronuncia:
    """A rádio fala "com participação de", nunca soletra "feat"."""

    def test_feat_vira_participacao(self) -> None:
        assert limpar_pronuncia("Tim Maia feat. Jorge") == (
            "Tim maia  com participação de  jorge"
        )

    def test_ft_ponto(self) -> None:
        assert "com participação de" in limpar_pronuncia("Anitta ft. MC Poze")

    def test_e_comercial_vira_e(self) -> None:
        assert " e " in limpar_pronuncia("Marisa Monte & Carlinhos Brown")

    def test_x_vira_e(self) -> None:
        assert limpar_pronuncia("Nas x Puff Daddy") == (
            "Nas e puff daddy"
        )

    def test_sem_marcadores(self) -> None:
        assert limpar_pronuncia("Jorge Ben Jor") == "Jorge ben jor"

    def test_vazio_e_none(self) -> None:
        assert limpar_pronuncia("") == ""
        assert limpar_pronuncia(None) == ""


class TestFontes:
    """Parsing das fontes externas testado sem rede."""

    def test_primeira_noticia_rss(self) -> None:
        xml = (b"<?xml version='1.0'?><rss><channel>"
               b"<item><title>Tecnologia: Nova bateria dura 7 dias</title></item>"
               b"<item><title>Tecnologia: Outra manchete</title></item>"
               b"</channel></rss>")
        assert _primeira_noticia(xml) == "Nova bateria dura 7 dias"

    def test_primeira_noticia_sem_item(self) -> None:
        assert _primeira_noticia(b"<rss><channel></channel></rss>") == ""

    def test_primeira_noticia_xml_quebrado(self) -> None:
        assert _primeira_noticia(b"<<<nada aqui>>>") == ""

    def test_texto_clima(self) -> None:
        assert _texto_clima("+28°C") == "28°"

    def test_texto_clima_sem_sinal(self) -> None:
        assert _texto_clima("19°C") == "19°"

    @pytest.mark.parametrize("fn", [noticia_g1, clima_wttr])
    def test_fonte_com_rede_quebrada_devolve_vazio(self, fn, monkeypatch) -> None:
        """Sem rede (ou fonte fora do ar): "" — a locução segue sem o enfeite."""
        def _explode(*args: Any, **kwargs: Any) -> Any:
            raise OSError("sem rede no sandbox")

        monkeypatch.setattr("integrations.radio_webhook.urlopen", _explode)
        assert fn() == ""


# ===========================================================================
# Montagem da fala (ordem e probabilidades do legado)
# ===========================================================================

class TestMontarLocucao:
    """Cada ramo da montagem, com rng roteirizado e fontes injetadas."""

    def _montar(self, *, rng=None, payload=None, db=None, agora=AGORA_FIXO,
                noticia=lambda: "", clima=lambda: "") -> str:
        return montar_locucao(
            payload if payload is not None else PAYLOAD,
            db if db is not None else DBFalso(),
            rng=rng or RNGFalso(),
            agora=agora,
            noticia_fn=noticia,
            clima_fn=clima,
        )

    def test_caminho_base_frase_e_assinatura(self) -> None:
        """Sem sorteios: frase da música passada + assinatura fecha."""
        texto = self._montar()
        assert "Tim maia" in texto and "Azul da cor do mar" in texto
        assert texto.rstrip().endswith(_CONTEUDO["assinaturas"][0])

    def test_noticia_15_por_cento(self) -> None:
        """Ramo 1 (< 0.15): giro de notícias abre a fala."""
        texto = self._montar(rng=RNGFalso([0.10]),
                             noticia=lambda: "Nova bateria dura 7 dias")
        assert texto.startswith("Giro de notícias Nicky. Nova bateria")

    def test_noticia_falhou_nao_trava(self) -> None:
        """Fonte de notícia falhou: fala segue sem o giro (nada de None)."""
        texto = self._montar(rng=RNGFalso([0.10]), noticia=lambda: "")
        assert "Giro de notícias" not in texto
        assert "Tim maia" in texto

    def test_curiosidade_70_por_cento(self) -> None:
        """Ramo 3: curiosidade do custom_field entra com a intro do banco."""
        payload = {
            "now_playing": {
                "song": {"artist": "Jorge Ben",
                         "title": "Mas Que Nada",
                         "custom_fields": {
                             "curiosidade": "Foi gravada em 1963."}},
            },
        }
        texto = self._montar(rng=RNGFalso([0.50, 0.50]), payload=payload)
        assert "Foi gravada em 1963." in texto
        assert _CONTEUDO["intro_curiosidade"][0] in texto

    def test_hora_certa_com_minutos(self) -> None:
        """Ramo 4: agora + duração + 10 s falado por extenso."""
        texto = self._montar(rng=RNGFalso([0.50, 0.40]))
        assert "Agora, 21 horas e 38 minutos." in texto

    def test_hora_certa_em_ponto(self) -> None:
        """Correção do legado: "22 horas em ponto" (não "e em ponto")."""
        # 21:56:30 + (200 s da música + 10) = 22:00:00 → minuto zerado
        agora = datetime(2026, 10, 27, 21, 56, 30,
                         tzinfo=ZoneInfo("America/Sao_Paulo"))
        texto = self._montar(rng=RNGFalso([0.50, 0.40]), agora=agora)
        assert "Agora, 22 horas em ponto." in texto
        assert "e em ponto" not in texto

    def test_proxima_musica(self) -> None:
        """Ramo 5: próxima música anunciada com frase do banco."""
        texto = self._montar(rng=RNGFalso([0.50, 0.60, 0.40]))
        assert "Jorge ben" in texto and "Take it easy" in texto

    def test_clima_20_por_cento(self) -> None:
        """Ramo 6: clima entra quando sorteado e a fonte responde."""
        # [notícia, hora, próxima, clima] — cada ramo consome um sorteio
        texto = self._montar(rng=RNGFalso([0.50, 0.60, 0.90, 0.10]),
                             clima=lambda: "Faz agora 28° em Presidente Venceslau.")
        assert "Faz agora 28°" in texto

    def test_clima_falhou_assinatura_fecha(self) -> None:
        """Decisão registrada: fonte do clima falhou → assinatura fecha."""
        texto = self._montar(rng=RNGFalso([0.50, 0.60, 0.90, 0.10]),
                             clima=lambda: "")
        assert texto.rstrip().endswith(_CONTEUDO["assinaturas"][0])

    def test_frase_de_banco_vazia_nao_anexa_ponto(self) -> None:
        """Banco vazio: a rádio fala o que existe, sem "· · " no ar."""
        db = DBFalso({tabela: [] for tabela in _CONTEUDO})
        texto = self._montar(db=db, rng=RNGFalso([0.50, 0.60, 0.90, 0.10]),
                             clima=lambda: "Faz agora 28° em X.")
        assert ". ." not in texto
        assert texto.startswith("Faz agora")

    def test_payload_vazio_nao_quebra(self) -> None:
        """Webhook disparado sem música: monta com os defaults do legado."""
        texto = self._montar(payload={}, clima=lambda: "Faz agora 28° em X.")
        assert "Nicky" in texto and "Sucesso" in texto

    def test_campos_vazios_nao_viram_ponto_no_ar(self) -> None:
        """Payload real do AzuraCast traz artist/title COMO CHAVE VAZIA.

        `.get(k, d)` devolveria "" e a frase sairia "com .." no ar — o
        fallback é `or`, igual ao legado intuía (27/10, prova viva).
        """
        db = DBFalso({
            **{t: [] for t in _CONTEUDO},
            "frases_passado": ["Mais uma joia musical: {t}, com {a}."],
        })
        payload = {"now_playing": {"song": {"artist": "", "title": "Station offline"}}}
        texto = self._montar(payload=payload, db=db, clima=lambda: "")
        assert "Mais uma joia musical: Station offline, com Nicky." in texto
        assert ".." not in texto

        payload_titulo = {"now_playing": {"song": {"artist": "Tim Maia", "title": ""}}}
        texto_titulo = self._montar(payload=payload_titulo, db=db, clima=lambda: "")
        assert "Mais uma joia musical: Sucesso, com Tim maia." in texto_titulo

    def test_pronuncia_custom_field_vence(self) -> None:
        """custom_field pronuncia_artista > limpeza automática."""
        payload = {
            "now_playing": {"song": {
                "artist": "MC Poze do Rodo",
                "custom_fields": {"pronuncia_artista": "M C Poze"}}},
        }
        texto = self._montar(payload=payload, clima=lambda: "")
        assert "M C Poze" in texto


# ===========================================================================
# processar() — montagem + MP3 atômico + erros
# ===========================================================================

class TestProcessar:
    """O processador nunca lança e o destino só troca quando pronto."""

    def _processar(self, tmp_path: Path, *, tts=None, db=None, rng=None,
                   payload=None, noticia=lambda: "", clima=lambda: "") -> dict:
        destino = tmp_path / "locucoes" / "anuncio_musica.mp3"
        return processar(
            payload if payload is not None else PAYLOAD,
            tts=tts or TTSFalso(),
            db=db if db is not None else DBFalso(),
            destino=destino,
            voz="dii_pt-BR",
            rng=rng or RNGFalso(),
            agora=AGORA_FIXO,
            noticia_fn=noticia,
            clima_fn=clima,
        )

    def test_sucesso_grava_mp3_atomico(self, tmp_path: Path) -> None:
        tts = TTSFalso()
        destino = tmp_path / "locucoes" / "anuncio_musica.mp3"
        resultado = self._processar(tmp_path, tts=tts)
        assert resultado["status"] == "ok"
        assert destino.read_bytes() == b"ID3-musica-falsa"
        # sem sobra de tmp: a troca foi atômica
        assert not destino.with_name("anuncio_musica.tmp.mp3").exists()
        assert tts.voz == "dii_pt-BR"
        assert "Tim maia" in tts.texto

    def test_diretorio_criado_se_nao_existe(self, tmp_path: Path) -> None:
        destino = tmp_path / "nunca" / "vi" / "aqui" / "fala.mp3"
        resultado = processar(
            PAYLOAD, tts=TTSFalso(), db=DBFalso(), destino=destino,
            rng=RNGFalso(), noticia_fn=lambda: "", clima_fn=lambda: "",
        )
        assert resultado["status"] == "ok" and destino.is_file()

    def test_sintese_falhou_sem_arquivo(self, tmp_path: Path) -> None:
        destino = tmp_path / "fala.mp3"
        resultado = processar(
            PAYLOAD, tts=TTSFalso(ok=False), db=DBFalso(), destino=destino,
            rng=RNGFalso(), noticia_fn=lambda: "", clima_fn=lambda: "",
        )
        assert resultado == {"status": "erro", "message": "sintese_falhou"}
        assert not destino.exists()

    def test_tts_explodiu_vira_erro(self, tmp_path: Path) -> None:
        destino = tmp_path / "fala.mp3"
        resultado = processar(
            PAYLOAD, tts=TTSFalso(explode=True), db=DBFalso(), destino=destino,
            rng=RNGFalso(), noticia_fn=lambda: "", clima_fn=lambda: "",
        )
        assert resultado["status"] == "erro"
        assert "piper morreu" in resultado["message"]
        assert not destino.exists()

    def test_locucao_vazia_nao_chama_tts(self, tmp_path: Path) -> None:
        """Tudo falhou (sem frases, sem notícia, sem clima): nem sintetiza."""
        tts = TTSFalso()
        db = DBFalso({tabela: [] for tabela in _CONTEUDO})
        resultado = processar(
            PAYLOAD, tts=tts, db=db, destino=tmp_path / "fala.mp3",
            rng=RNGFalso(), noticia_fn=lambda: "", clima_fn=lambda: "",
        )
        assert resultado["status"] == "erro"
        assert tts.texto is None  # síntese nunca foi chamada

    def test_destino_antigo_sobrevive_a_falha(self, tmp_path: Path) -> None:
        """Falha de síntese não pode apagar o MP3 que está no ar."""
        destino = tmp_path / "fala.mp3"
        destino.write_bytes(b"versao-no-ar")
        resultado = processar(
            PAYLOAD, tts=TTSFalso(ok=False), db=DBFalso(), destino=destino,
            rng=RNGFalso(), noticia_fn=lambda: "", clima_fn=lambda: "",
        )
        assert resultado["status"] == "erro"
        assert destino.read_bytes() == b"versao-no-ar"
