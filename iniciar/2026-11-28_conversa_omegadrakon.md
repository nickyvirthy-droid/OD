# Conversa OmegaDrakon — 28/11/2026

## §1 — Retomada `leia iniciar` (28/11 15:29)

**Dono:** *"leia iniciar"* — pedido de retomada pelo checkpoint, sem mudança de
código.

**Autor da leitura/registro:** Freebuff (Buffy).

### O que foi lido (regras 3 e 24)

`iniciar/README.md`, `iniciar/RULES.md` (24 regras), `iniciar/session.json`
(topo `streaming_grafo_unificado_2026_11_26`, `retomada_leitura_iniciar_2026_11_26_14h42`,
`gate_zero_2026_11_26`), `iniciar/ATRIBUICOES.md`, `iniciar/2026-11-26_conversa_omegadrakon.md`
(§23–§27), `txt.txt` (vazio), `analise/` e `tools/brief_multi_ia.py`.

### Estado medido (`date -Is` = 2026-11-28T15:29:15-03:00)

- `HEAD == origin/master == 54c99ab` ("Registra prova viva do restart verde do
  streaming grafo"), árvore limpa.
- Versão **1.47.0+2085** (brief mult-IA).
- `od-core` **active (running)**, `MainPID 932556`, `NRestarts=0` (mesmo PID da
  prova viva de 26/11 17:25 — sem restart desde então).
- `GET /health` com `X-API-Key`: **ok=true · status up · 34 checks**,
  `transitorios: []`.
- `tx t.txt` **vazio**; `analise/` contém apenas `No Break/` (9 imagens) — a
  pasta `analise/Nicky Locutor/` citada como pauta em 26/11 **não está mais em
  `analise/`**; não foi movida nem apagada por mim. Registrado como está, sem
  adivinhar destino.

### Fila / pendências herdadas (do TODO)

Nada em andamento na árvore. Seguem abertos: decisões do dono do P2 (aplicar as
atualizações de SO, nobreak USB, 2º nó/LoRa, app por papel, OpenAI/I1,
Projeti), P3 sob demanda (cache de embedding no RAG, OTel/Grafana, eval no CI,
reteste da IA local) e o achado `xdg-desktop-portal[-gtk]` na sessão do usuário
(fora do `od-core`).

### Estado da entrega

Leitura + registro apenas: nenhum `.py` alterado, sem teste de código, sem
restart e sem bump (1.47.0+2085).

## §2 — Confirmação do dono: Nicky Locutor arquivada e updates do SO aplicados (28/11 15:45)

**Dono:** *"pasta Nicky Locutor decidimos arquivar, me disse que já havia
concluído a análise dela. Os updates acho que também já foram."*

**Autor da verificação/registro:** Freebuff (Buffy).

### Nicky Locutor — análise concluída e pasta arquivada (confirmado)

- **Análise concluída em 27/10.** Prova no próprio registro: entrada de 27/10 do
  `session.json` (*"Dono (27/10 ~16:55): '1' -> analise/Nicky Locutor/"*) e as
  etapas publicadas no `docs/CHANGELOG.md`: **B** — frases da rádio no banco do
  OD (~l. 4999); **D** — webhook do locutor no `od-core` (~l. 4972); **E** —
  rádio Nicky no ar com prova viva (~l. 4908). Commits `3ea0790`, `1b4dd88` e
  `7ccf955` ("estado final ENTREGUE da integração Nicky Locutor").
- **Pasta fora da caixa de entrada.** O dono renomeou `Nicky Locutor/` em
  28/10 08:16 (`Nicky Musicas/`) e 28/10 10:16 (`Nicky Radio/`); desde então
  nenhuma das duas está em `analise/`. Hoje `analise/` só tem `No Break/`.
  `find` no projeto não acha nenhuma pasta `*nicky*`/`*locutor*` (só
  `agents/nicky_virthy`, sem relação).
- **Correção de registro:** a frase "pauta do dono: `analise/Nicky Locutor/`"
  repetida em 26/11 (ATRIBUICOES e §27 da transcrição de 26/11) estava
  desatualizada desde 28/10. Fica corrigida aqui; o registro antigo não foi
  apagado.

### Updates do SO — aplicados em 26/11 (confirmado)

- `data/os_updater_estado.json`: ciclo **real** em 26/11 — `apt update` 02:10:37,
  `apt upgrade` **67 pacotes** 02:13:31, `autoremove` removendo o kernel
  `6.8.0-149`, `fwupdmgr update` com **"Successfully installed firmware"** (2
  firmwares) 02:13:47 e reboot agendado +5 min; a máquina reiniciou às
  **02:36:27** (`uptime -s`).
- **Agora:** `/health` ok=true (34 checks) com `os_updater`: `upgradable: 0`,
  `precisa_reboot: false`, `falhas_consecutivas: 0`, `sucessos_consecutivos: 3`,
  kernel `6.8.0-151-generic`. `apt list --upgradable` = **0**;
  `fwupdmgr get-updates` = **0 devices**; `/var/run/reboot-required` ausente.
- A única seção não-`ok` do ciclo foi o `fwupdmgr refresh` ("Idle… Metadata is
  up to date"), comportamento do fwupd, não falha de aplicação.
- Próxima execução automática do timer: **dom 29/11 03:17**.

### Estado

Verificação + registro apenas: nenhum `.py` alterado, sem teste, sem restart e
sem bump (`1.47.0+2085`).

## §3 — Novo tema: arquivos bagunçados e busca da pasta arquivada (28/11 15:58)

**Dono:** *"meus arquivos estão muito bagunçados, pode ser que ela apareça
novamente dentro de alguma pasta perdida ou um arquivo compactado. você vai me
ajudar nisso tudo."*

**Autor:** Freebuff (Buffy).

### Medido (dentro do projeto)

- `HEAD == origin/master == 3c5cbe1`, árvore limpa.
- Tamanhos: `app` 4,2G · `site` 3,0G · `backups` 1,6G · `voice` 694M · `data`
  675M · `assets` 103M · `logs` 47M · `analise` 14M.
- Compactados: `backups/auto-capturas/od-capturas-2026-11-20_0412.tar.gz`
  (590 MB), `od-capturas-2026-11-27_0405.tar.gz` (657 MB) e 5 `backups/auto/*.tar.gz`
  (1,3–1,9 MB).
- Raiz ainda tem 5 `.txt` soltos, dois **vazios** (`limitacoes.txt`,
  `pedido.txt`).

### Busca da Nicky Locutor

- `find` até 3 níveis por `*nicky*`/`*locutor*`: **nada** além de
  `agents/nicky_virthy` (sem relação).
- Listagem interna dos **7 tar.gz** de `backups/` filtrada por `nicky|locutor`:
  **zero ocorrências** — o material arquivado não está nos backups do projeto.
- Conclusão medida: ou está fora do repositório (home, HDs, `dados/`), ou num
  compactado que não vive em `backups/`. Varrer fora do projeto precisa de
  caminho autorizado pelo dono.

### Proposta (Fase 1, só leitura)

1. Inventário por pasta: tamanho, nº de itens, idade, **duplicatas por hash**.
2. Catálogo de compactados com a listagem interna pesquisável (para achar
   "nicky" dentro de zip/tar sem extrair).
3. Saída em `docs/INVENTARIO_ARQUIVOS.md` + índice de compactados.
4. Fase 2 (depois): destino por lote (manter/mover/arquivar/lixo) — só com
   aprovação do dono, item por item.

### Estado

Só medição inicial; nada do dono foi movido ou apagado; sem restart e sem bump
(`1.47.0+2085`).

## §4 — Fase 1 do inventário entregue (28/11 ~16:08)

**Dono:** *"Rodar a Fase 1 de organização: inventário por pasta com duplicatas
por hash e catálogo de compactados"*.

**Autor:** Freebuff (Buffy).

### Entregue

- `tools/inventario_arquivos.py` — somente leitura: resumo por pasta (1º/2º
  nível), soltos na raiz, vazios, nomes com espaço, **duplicatas por SHA-256**
  (pré-agrupadas por tamanho; limites de 200 MB por arquivo) e **catálogo de
  compactados** (zip/tar/gz/7z/rar) com **busca interna sem extrair**
  (`--buscar`), saídas Markdown/JSON.
- `tests/test_inventario_arquivos.py` — 11 casos (exclusões, duplicatas,
  catálogo, gzip de arquivo único, nomes com espaço, relatório, CLI). **11
  passed**.
- `docs/INVENTARIO_ARQUIVOS.md` — relatório real do projeto.

### Números medidos

- **5.233 arquivos · 6,1 GB · 23 compactados · 472 grupos duplicados ·
  278,7 MB recuperáveis.**
- `site` 3,0 GB · `backups` 1,5 GB · `voice` 693 MB · `data` 669 MB · `assets`
  100 MB · `logs` 46,6 MB · `analise` 13,8 MB.
- Artefatos de build (`app/build`, `.dart_tool`, `app/android/.gradle`) ficam
  fora por padrão (`--incluir-build` entra).
- **Busca `nicky` na listagem interna dos 23 compactados: zero ocorrências** —
  o material arquivado não está no projeto.

### Achados

1. **Cinco pastas são conteúdo de APK extraído com nome de arquivo**:
   `AndroidManifest.xml` (29M/338), `assets/AssetManifest.json` (52M/404),
   `assets/flutter_assets/version.json` (52M/404), `lib` (29M/338) e
   `lib/arm64-v8a/libapp.so` (29M/338) — ~**191 MB** de binários, duplicados
   entre si pelo hash.
2. `site/OmegaDrakon*.apk` são **byte-idênticos** aos de
   `backups/apk-v1.47.0-2085` (~95 MB duplicados).
3. `backups/apk-v1.44.0-2080` e `apk-v1.45.0-2081` têm APKs idênticos entre si.
4. **10 arquivos vazios**, incluindo `data/od.db` (0 byte) e
   `limitacoes.txt`/`pedido.txt`.
5. Raiz com **16 arquivos soltos**.

### Fase 2 (proposta, nada executado)

(a) remover as 5 pastas de APK extraído; (b) decidir a duplicata `site/` ×
`backups/apk`; (c) limpar vazios e `.txt` soltos; (d) autorizar varredura fora
do projeto (home/HDs) para localizar o arquivo da Nicky Locutor.

Sem restart e sem bump (`1.47.0+2085`).

## §5 — Fase 2a executada: pastas de APK extraído removidas (28/11 ~16:20)

**Dono:** *"Executar a Fase 2a: remover as cinco pastas de APK extraído depois
de confirmar que não são fonte"*.

**Autor:** Freebuff (Buffy).

### Confirmação feita ANTES de apagar

1. Conteúdo é 100% de APK extraído (`AndroidManifest.xml`, `classes.dex`,
   `resources.arsc`, `lib/arm64-v8a`, `assets/flutter_assets`, `.properties`,
   `.tflite`); nenhum `.py`/`.dart`/`.js`/`.html`/`.md` de fonte — só o
   `META-INF/NOTICE.md` do próprio APK.
2. `git ls-files` nesses caminhos: **vazio** (nada era rastreado).
3. `.gitignore` já ignorava `/AndroidManifest.xml/` e `/assets/` com o
   comentário "Build artifacts from APK extraction".
4. Nenhuma referência no código: o app usa `Image.asset('assets/logo.png')`,
   que resolve para **`app/assets/logo.png`** (presente, 377 KB, declarado no
   `app/pubspec.yaml`); a menção em `server.py` é só um comentário de proxy de
   ferramentas.

### Removido

- `AndroidManifest.xml/` — 29 MB, 338 arquivos.
- `assets/` — 103 MB, 808 arquivos (`AssetManifest.json/`,
  `flutter_assets/version.json/` e `version.json/` eram todos extrações).
- `lib/` — 29 MB, 338 arquivos (só `arm64-v8a/libapp.so/`).

### Efeito medido

| Depois | Antes |
|---|---|
| 3.749 arquivos | 5.233 |
| 6,0 GB | 6,1 GB |
| 38 grupos duplicados / 189,4 MB | 472 grupos / 278,7 MB |

`app/assets/logo.png` intacto; `tests/test_inventario_arquivos.py` 11 passed;
`git status` limpo (nada era rastreado). `docs/INVENTARIO_ARQUIVOS.md`
regenerado.

### Próximo

Duplicatas restantes conhecidas: `site/OmegaDrakon*.apk` ×
`backups/apk-v1.47.0-2085` (~95 MB) e `apk-v1.44.0-2080` × `apk-v1.45.0-2081`
(~95 MB) — item (b) da Fase 2, aguardando decisão do dono.
