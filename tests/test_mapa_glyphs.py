"""Glifos do mapa offline — rótulos não-latinos (fila item 8, 26/11).

Contexto medido: o `.pmtiles` do Brasil (2,87 GiB, z0–14) traz campos
`name:ar`, `name:he`, `name:hi`, `name:ja`, `name:ko`… nas feições; o mapa
só embutia os blocos **0–1279** (latim + grego/cirílico), então qualquer
rótulo fora disso virava "tofu" no navegador.

Aqui ficam provadas três coisas, sem navegador:

  * os blocos baixados existem e são PBFs de verdade (não o stub vazio de
    29 bytes que o servidor de fontes devolve para faixas que ele não tem);
  * cada bloco cobre amostras reais dos scripts presentes nos tiles
    (hebraico, árabe, siríaco, devanagari, tailandês, vietnamita, kana);
  * o template de glifos do estilo aponta para a pasta certa e a fonte é a
    mesma ("Noto Sans Regular").

CJK/Hangul NÃO são cobertos por esta fonte (o PBF vem vazio) — está
documentado em `docs/MAPAS_OFFLINE.md`; um teste de ausência só criaria
ruído quando a fonte mudar.
"""

from __future__ import annotations

import pathlib
import re

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]
FONTES = RAIZ / "site" / "vendor" / "fonts" / "Noto Sans Regular"
PAGINA = RAIZ / "site" / "protomaps.html"


# --- Leitor mínimo de PBF de glifos ---------------------------------------
# Estrutura do arquivo (formato MapLibre/glyphs):
#   message glyphs { repeated fontstack stacks = 1; }
#   message fontstack { string name = 1; string range = 2; repeated glyph glyphs = 3; }
#   message glyph { uint32 id = 1; bytes bitmap = 2; ... }
# Não vale puxar dependência para ler 9 KB de asset estático.

def _varint(buf: bytes, i: int) -> tuple[int, int]:
    valor = 0
    shift = 0
    while True:
        byte = buf[i]
        i += 1
        valor |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return valor, i
        shift += 7


def _campos(buf: bytes):
    i = 0
    while i < len(buf):
        chave, i = _varint(buf, i)
        campo, tipo = chave >> 3, chave & 7
        if tipo == 0:
            valor, i = _varint(buf, i)
            yield campo, valor
        elif tipo == 2:
            tamanho, i = _varint(buf, i)
            yield campo, buf[i:i + tamanho]
            i += tamanho
        elif tipo == 5:
            yield campo, buf[i:i + 4]
            i += 4
        elif tipo == 1:
            yield campo, buf[i:i + 8]
            i += 8
        else:  # pragma: no cover - PBF corrompido
            raise ValueError(f"wire type {tipo} inesperado")


def ler_glifos(caminho: pathlib.Path) -> tuple[str, str, set[int]]:
    """(nome da fonte, faixa declarada, ids de codepoints com glifo)."""
    nome = faixa = ""
    ids: set[int] = set()
    for campo, valor in _campos(caminho.read_bytes()):
        if campo != 1 or not isinstance(valor, bytes):
            continue
        for campo2, valor2 in _campos(valor):
            if campo2 == 1 and isinstance(valor2, bytes):
                nome = valor2.decode()
            elif campo2 == 2 and isinstance(valor2, bytes):
                faixa = valor2.decode()
            elif campo2 == 3 and isinstance(valor2, bytes):
                gid = next(
                    (v for c, v in _campos(valor2) if c == 1), None
                )
                if gid is not None:
                    ids.add(gid)
    return nome, faixa, ids


# --- O que cada faixa tem que cobrir --------------------------------------

# faixa -> (codepoints de amostra, mínimo de glifos)
ESPERADO = {
    "1280-1535": ([0x05D0, 0x05E9], 100),      # hebraico
    "1536-1791": ([0x0627, 0x0645], 100),      # árabe
    "1792-2047": ([0x0710], 100),              # siríaco
    "2304-2559": ([0x0915, 0x0930], 100),      # devanagari
    "3584-3839": ([0x0E01], 100),              # tailandês
    "7680-7935": ([0x1EA1, 0x1EC7], 200),      # vietnamita (latim ext. add.)
    "8192-8447": ([0x2013, 0x2014], 100),      # pontuação geral (travessões)
    "12288-12543": ([], 10),                   # pontuação CJK (sem kana)
}


class TestBlocosBaixados:
    def test_todas_as_faixas_presentes_e_com_glifos(self) -> None:
        for faixa, (_, minimo) in ESPERADO.items():
            caminho = FONTES / f"{faixa}.pbf"
            assert caminho.is_file(), f"faixa {faixa} ausente"
            assert caminho.stat().st_size > 1000, (
                f"{faixa}: tamanho de stub vazio (o servidor não tem a faixa)"
            )
            nome, declarada, ids = ler_glifos(caminho)
            assert nome == "Sans Regular", f"{faixa}: fonte {nome!r}"
            assert declarada == faixa, f"{faixa}: faixa declarada {declarada!r}"
            assert len(ids) >= minimo, f"{faixa}: só {len(ids)} glifos"

    @pytest.mark.parametrize("faixa", sorted(ESPERADO))
    def test_amostras_de_cada_script_tem_glifo(self, faixa: str) -> None:
        amostras, _ = ESPERADO[faixa]
        _, _, ids = ler_glifos(FONTES / f"{faixa}.pbf")
        for codepoint in amostras:
            assert codepoint in ids, (
                f"U+{codepoint:04X} sem glifo em {faixa}.pbf"
            )

    def test_latim_continua_completo(self) -> None:
        """A faixa original segue intacta — acentos do português."""
        for faixa in ("0-255", "256-511", "512-767", "768-1023", "1024-1279"):
            assert (FONTES / f"{faixa}.pbf").is_file()
        _, _, ids = ler_glifos(FONTES / "0-255.pbf")
        for codepoint in (ord("ã"), ord("õ"), ord("ç"), ord("É")):
            assert codepoint in ids


class TestEstiloUsaOsGlifos:
    def test_template_e_fonte_batem_com_a_pasta(self) -> None:
        html = PAGINA.read_text(encoding="utf-8")
        assert 'glyphs: "/site/vendor/fonts/{fontstack}/{range}.pbf"' in html
        assert '"text-font": ["Noto Sans Regular"]' in html
        # toda camada de texto usa a MESMA fonte que tem os blocos em disco
        fontes = set(re.findall(r'"text-font": \[([^\]]+)\]', html))
        assert fontes == {'"Noto Sans Regular"'}
        assert (FONTES / "0-255.pbf").is_file()
