# Mapas offline — estado medido e limites (26/11)

> **Finalidade:** fechar o item 8 da fila (26/11) com números: o que o
> `.pmtiles` do Brasil entrega hoje, quais rótulos ele tem, quais glifos
> estão embutidos e por que CJK/Hangul e zoom 15 **não** entram sem demanda.
> **Página:** `/site/protomaps.html` (MapLibre + `pmtiles://`).
> **Data:** 2026-11-26 · fila de prioridades item 8.
> **Assinatura:** `OD // CORE`

---

## 1. O arquivo (`site/maps/brasil.pmtiles`, fora do git)

Lido do cabeçalho PMTiles v3 em 26/11:

| Campo | Valor |
|-------|-------|
| Tamanho | **3.079.554.972 B** (2,87 GiB) |
| Versão / tipo | PMTiles **v3**, tiles **MVT**, compressão **gzip**, clusterizado |
| Zoom | **0–14** |
| BBox | `(-74, -34, -32, 5.5)` — Brasil |
| Tiles endereçados | **4.842.245** (2.811.716 entradas, 2.497.612 conteúdos) |

O recorte foi extraído em 12/11 e fica **fora do git** (`.gitignore`:
`site/maps/*.pmtiles`). A página detecta o arquivo por um `GET` com
`Range: bytes=0-0` — o roteador responde 501 a `HEAD`, então `HEAD` não serve
como sonda (bug de 12/11 documentado no HTML).

## 2. Rótulos que existem nos tiles

Amostra de **200 MB** da seção de tiles (25.675 tiles descomprimidos),
contando caracteres acima de U+04FF no texto das feições:

| Bloco | Script | Ocorrências |
|-------|--------|-------------|
| U+1536–1791 | árabe | 175.848 |
| U+1280–1535 | hebraico | 169.215 |
| U+1792–2047 | siríaco/thaana | 147.075 |
| U+12288–12543 | pontuação CJK/kana | 22.022 |
| U+2304–2559 | devanagari (híndi/marata) | 16.882 |
| U+4E00+, U+B000+, U+C000+, U+D000+ | CJK e hangul | milhares |
| U+F800+, U+E000+ | uso privado | resíduo de fonte/planilha |

Exemplos reais que o tile carrega em campos `name:ja`/`name:ko`/`name:ar`:
"南極海", "남극해", "المحيط المتجمد الجنوبي". Eles existem porque o
basemap planetiler guarda `name:*` — **o estilo do OD, hoje, mostra só
`name` (português)**, por isso os glifos não-latinos não apareciam.

> A amostra decodifica o protobuf cru como UTF-8; os totais são ordem de
> grandeza, não contagem exata. O que importa: os scripts estão lá de fato
> (as cadeias acima são nomes coerentes, não ruído).

## 3. Glifos embutidos (o que mudou em 26/11)

Antes: só os blocos **0–1279** (latim, grego, cirílico) — 5 arquivos, ~500 KB.
Agora, também em `site/vendor/fonts/Noto Sans Regular/`:

| Faixa | Script | Tamanho | Glifos |
|-------|--------|---------|--------|
| 1280–1535 | hebraico | 84.434 B | 226 |
| 1536–1791 | árabe | 110.716 B | 255 |
| 1792–2047 | siríaco | 93.383 B | 237 |
| 2304–2559 | devanagari | 99.704 B | 224 |
| 3584–3839 | tailandês | 57.363 B | 170 |
| 7680–7935 | vietnamita (latim ext. add.) | 135.449 B | 256 |
| 8192–8447 | pontuação geral (travessão, aspas) | 64.220 B | 194 |
| 12288–12543 | pontuação CJK | 6.939 B | 23 |

Total novo: **648 KB** (8 arquivos). Fonte de origem: os mesmos assets
públicos da Protomaps (`basemaps-assets`) — provado pelo sha256 do
`0-255.pbf` já existente, idêntico ao servido lá. `tests/test_mapa_glyphs.py`
(11 casos) lê os PBFs e confere que cada script tem glifo de amostra.

## 4. Limites medidos (por que não fui além)

1. **CJK e hangul não existem nesta fonte.** O servidor devolve um PBF de
   **29 bytes** (stub vazio) para `19968-20223`, `20224-20479` e
   `44032-44287`; a faixa `12288-12543` tem só 23 glifos (pontuação), sem
   `あ`/`ア`. Kanji, hanzi e hangul continuariam "tofu" mesmo com o bloco
   baixado — precisariam de outra fontstack (Noto Sans CJK, dezenas de MB)
   **e** mudança de estilo. Não há demanda: os rótulos visíveis são `name`,
   em português.
2. **Zoom 15 não existe no arquivo** (`maxzoom=14`). Acima disso o MapLibre
   faz *overzoom* (a imagem estica, não quebra). Ir a 15 de verdade é uma
   **nova extração** do recorte — na prática ~4× os tiles do último zoom
   (ordem de +2,5–3 GB), sem ganho medido para o uso atual (nomes de rua e
   lugares já aparecem no z14).
3. **O estilo continua mostrando `name`.** Para exibir o nome local (ex.:
   japonês na Liberdade), a mudança é no `text-field` (`name:ja` etc.) — o
   glifo já está pronto para árabe/hebraico/devanagari/tailandês/vietnamita;
   para CJK/hangul, ver o item 1.

**Critério para reabrir:** o dono relatar rótulo faltando/embaralhado no mapa
(→ falta faixa de glifo) ou precisar de detalhe de quadra em área urbana
(→ z15). Sem um dos dois, o item fica fechado.

## 5. Como conferir

```bash
# glifos: presença + cobertura por script (sem navegador)
.venv/bin/python -m pytest tests/test_mapa_glyphs.py -q

# ao vivo (servidor no ar)
curl -s -o /dev/null -w '%{http_code} %{size_download}\n' \
  -H "X-API-Key: $(grep -m1 '^OD_API_KEY=' .env | cut -d= -f2-)" \
  'http://127.0.0.1:8000/site/vendor/fonts/Noto%20Sans%20Regular/1536-1791.pbf'
```

Medido em 26/11: `1280-1535` → 200 / 84.434 B; `1536-1791` → 200 / 110.716 B;
`7680-7935` → 200 / 135.449 B; página → 200.
