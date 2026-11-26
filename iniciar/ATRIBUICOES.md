# ATRIBUIÇÕES — quem fez o quê no OmegaDrakon

> **Regra 23 (`iniciar/RULES.md`).** O dono constrói o OD com várias IAs, quase
> sempre em ferramentas gratuitas cujos créditos acabam antes do fim do
> serviço. Este é o **livro-caixa compartilhado**: toda entrega registra
> (a) autor, (b) arquivos criados/modificados e (c) intenção + estado.
> Ordem: mais recente no topo. Nada de adivinhação: origem desconhecida é
> registrada como desconhecida.

---

## 26/11/2026 — Streaming no grafo unificado ao caminho direto

**Autor:** Antigravity (Gemini 4 Hydrogen) — pedido do dono (*"1"*, resolver a
divergência de streaming grafo × caminho direto).

### Modificados

- `core/orchestrator.py` — extraídos `_executar_stream_llm()` (compartilhado
  entre caminho direto e grafo) e `_estado_de_tool_results()` (compartilhado
  entre `_executar_grafo` e `_process_stream_grafo`); `_process_stream_grafo`
  agora roda `grafo.astream()` com `asyncio.Queue` para streaming real
  token-a-token, remove dupla contagem de métricas e `_post_process`
  duplicado, e emite `{"type": "error", "message": "rate_limited" | ...}` e
  `_record_terminal`/`_finish` em paridade com o caminho direto.
- `tests/test_orchestrator_graph_integration.py` — nova classe
  `TestStreamingGrafoParidade` (7 casos cobrindo `OD_ORCHESTRATOR_GRAPH=0` e `1`).
- `docs/ANALISE_SISTEMA_TODO.md` (checkbox marcado `[x]`), `docs/CHANGELOG.md`,
  `iniciar/session.json`, `iniciar/2026-11-26_conversa_omegadrakon.md` (§26),
  `iniciar/ATRIBUICOES.md` (esta entrada) e `txt.txt`.

### Intenção e estado

- **Intenção:** alinhar o streaming em produção (`OD_ORCHESTRATOR_GRAPH=1`) ao
  contrato do caminho direto e do app (`app/lib/services/od_ws.dart`).
- **Pronto/validado:** suíte completa **5820 passed, 16 skipped, 0 falhas**
  (`248.51s`) e gate do RAG híbrido **4433 chunks · 8/8 · 0/8 · 6/6 · 2/2**
  (exit `0`).
- **Estado:** sem bump (`1.47.0+2085`, servidor apenas; APK já trata `type:
  "error"` / `rate_limited`). Seguindo para commit/push e restart verde do
  `od-core` (regra 7.3).

---

## 26/11/2026 — Validação e publicação do lote "Gate em zero" + retomada

**Autor:** Antigravity (Gemini 4 Hydrogen) — pedido do dono (*"leia iniciar"* e
*"1"* para validar e fechar commit/push do lote `gate_zero_2026_11_26` deixado
na árvore por Freebuff (Buffy)).

### Modificados (só registro da retomada e validação)

- `iniciar/session.json`, `iniciar/2026-11-26_conversa_omegadrakon.md` (§25),
  `iniciar/ATRIBUICOES.md` (esta entrada) e `txt.txt`.
- Mantidas integralmente as alterações do lote `gate_zero_2026_11_26` em
  `tests/conftest.py`, `tests/test_verificar_restauracao_pg.py`,
  `docs/CHANGELOG.md` e `docs/ANALISE_SISTEMA_TODO.md`.

### Intenção e estado

- **Intenção:** validar em definitivo a suíte completa e o gate do RAG sobre o
  lote pendente na árvore antes de commitar e publicar em `origin/master`.
- **Pronto/validado:**
  - Suíte completa (`.venv/bin/python -m pytest -q`): **5813 passed, 16 skipped,
    0 falhas** (18 warnings, em 257,62 s).
  - Gate do RAG híbrido (`.venv/bin/python tools/medir_rag_hibrido.py`): 4427
    chunks; relevantes `8/8 -> 8/8`, irrelevantes `0/8 -> 0/8`, paráfrases
    `6/6 -> 6/6`, estruturais `2/2 -> 2/2` (exit 0).
- **Estado:** nenhum `.py` de produção alterado — sem restart e sem bump
  (`1.47.0+2085`). Commit e `git push origin master` feitos; resumo enviado ao
  Telegram (regra 15).

---

## 26/11/2026 — Gate em zero: os 2 `test_websocket` deixam de falhar por ordem

**Autor:** Freebuff (Buffy) — pedido do dono (*"a, fechar o gate"*, escolha (a)
da retomada da manhã).

### Modificados (só testes e documentação)

- `tests/test_verificar_restauracao_pg.py` — `test_producao_passa_a_guarda_no_main`
  neutraliza o `load_dotenv` com `monkeypatch` (era o teste que vazava).
- `tests/conftest.py` — constante `VARS_RUNTIME` + fixture autouse
  `_runtime_sempre_limpo` (apaga `OD_ORCHESTRATOR_GRAPH`, `OD_CHAT_PROVIDERS` e
  `OD_IA_ORDEM` no início de **cada** teste; o `pop` do import cobria só o
  começo da suíte).
- `docs/CHANGELOG.md` — seção "Gate em zero" com causa raiz, correção e prova.
- `docs/ANALISE_SISTEMA_TODO.md` — checkbox do `test_websocket` **fechado** com
  a evidência; checkbox **novo**: contrato de streaming grafo × caminho direto.
- `iniciar/2026-11-26_conversa_omegadrakon.md` (§24), `iniciar/session.json`,
  `iniciar/ATRIBUICOES.md` (esta entrada), `txt.txt`.

### Intenção e estado

- **Intenção:** o gate não fechava `0` por causa de 2 falhas por ordem; a
  hipótese do TODO ("estado global que vaza") era genérica — a causa tinha que
  ser **medida**, não chutada.
- **Causa raiz (medida):** plugin que comparava o ambiente antes/depois de
  **cada teste** acusou um único vazador:
  `tests/test_verificar_restauracao_pg.py::test_producao_passa_a_guarda_no_main`
  chama `runtime.verificar_restauracao_pg.main()` em processo e, sem
  `TELEGRAM_*` no ambiente, esse `main()` roda `load_dotenv(.env)` — derramando
  `OD_ORCHESTRATOR_GRAPH=1` + `OD_CHAT_PROVIDERS` + `OD_IA_ORDEM` no
  `os.environ`. Com o grafo ligado, `process_stream` sai pelo
  `_process_stream_grafo`, que rende o rate limit como `done` (não `error`) e a
  resposta em um token só: exatamente o que os 2 testes do caminho direto
  negavam.
- **Pronto/validado:** gate completo **5772 passed / 19 skipped / 0 falha**
  (244 s) contra 5770/19/**2** antes; o mesmo plugin acusou **0 vazamentos**;
  gate do RAG híbrido **8/8 · 0/8 · 6/6 · 2/2** (exit 0), medido antes e
  depois do texto novo no CHANGELOG; diff revisado (46 linhas, tudo em `tests/`
  e docs).
- **Estado:** **nenhum `.py` de produção alterado** — sem restart e sem bump
  (`1.47.0+2085`).
- **Achado registrado (não corrigido por conta própria):** em produção
  (`OD_ORCHESTRATOR_GRAPH=1`) o streaming sai do grafo, com token único e rate
  limit como `done`; o app só traduz `rate_limited` no `case 'error'`. Virou
  checkbox no §4 do TODO para o dono decidir.

---

## 26/11/2026 — Retomada "leia iniciar": fila 1–11 fechada e estado medido

**Autor:** Freebuff (Buffy) — pedido do dono (*"leia iniciar"*).

### Criados

- `iniciar/2026-11-26_conversa_omegadrakon.md` §23 — transcrição do turno.

### Modificados

- `iniciar/session.json` — checkpoint `retomada_leitura_iniciar_2026_11_26_11h`
  (topo) com o estado medido.
- `docs/ANALISE_SISTEMA_TODO.md` — checkbox novo no §4: falha recorrente de
  `xdg-desktop-portal[-gtk]` na sessão do usuário (fora do `od-core`).
- `iniciar/ATRIBUICOES.md` (esta entrada) e `txt.txt`.

### Intenção e estado

- **Intenção:** cumprir as regras 3 e 4 (ler antes de assumir contexto e
  registrar a troca) e dizer onde a sessão está depois de o dono fechar a
  manhã com o monitor de CPU/RAM.
- **Medido (`date -Is` = 2026-11-26T11:01:09-03:00):** `HEAD == origin/master
  == b5d418a`, árvore limpa; `1.47.0+2085`; `od-core` active MainPID **488071**
  desde **10:29:20** (restart verde do monitor de CPU/RAM), `NRestarts=0`,
  journal `-p err` **0**; `/health` **ok=true · 34 checks**, nenhum fora de
  `up`; boot **02:36:27**, kernel **6.8.0-151**, **sem reboot pendente**;
  `os_updater` **0 pacotes / 0 firmwares / 0 falhas** e `od-os-updater.timer`
  enabled+active (próxima execução **dom 29/11 03:17**).
- **Fila:** **11 de 11** itens fechados (tabela do §4). P0 1–4 e P1 5–8 ✅;
  P2 (9–13) aguarda **decisão/compra** do dono; P3 restam itens "quando houver
  demanda".
- **Achados:** (1) os horários dos checkpoints anteriores de hoje (~12:4x) não
  batem com o relógio da máquina (11:01, confirmado pelo uptime) — causa não
  determinada, registrada sem inventar, e o registro passa a usar hora medida;
  (2) `xdg-desktop-portal[-gtk]` falhando desde 10:32 na sessão do usuário —
  fora do alcance do `od-core`, virou checkbox.
- **Estado:** nada alterado em código; sem restart e sem bump (`1.47.0+2085`).
  Resumo enviado ao Telegram (regra 15).
- **Pela metade / próximo passo:** não há item 12 na fila. Próximos candidatos
  já anotados no TODO: gate em 0 (`test_websocket` por ordem), cache de
  embedding de documento no RAG, ou decisões do P2.

---

## 26/11/2026 — Comparador: custo de máquina medido nas chamadas

**Autor:** Freebuff (Buffy) — pedido do dono (*"Implemente o monitor de CPU/RAM
durante as chamadas do comparador no painel"*).

### Modificados

- `core/comparador_modelos.py` — `_ColetorHardware` (leitura de `/proc/stat` e
  `/proc/meminfo` a cada 250 ms durante cada chamada; resumo com média/pico
  de CPU, RAM usada, delta de RAM, % da RAM do servidor, núcleos, amostras).
  Sem `/proc`, `hardware` é `None` sem quebrar a comparação.
- `integrations/api/server.py` — `cmpHw()` pura + o custo sob o nome de cada
  modelo no painel, e a nota de que o número é do servidor inteiro.
- `tests/test_comparador_modelos.py` — 3 casos novos (chamada lenta,
  falha/timeout, ausência de `/proc`) e o harness node cobrindo `cmpHw`.
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (monitor de CPU/RAM ✅,
  VRAM virou pendência própria com motivo), `iniciar/2026-11-26_conversa_omegadrakon.md`
  (§22), `iniciar/session.json`, `txt.txt`.

### Intenção e estado

O comparador já media latência; faltava o custo de máquina. Agora a medição
acontece durante a chamada e aparece no cartão do painel. Provado ao vivo
(groq 10,9% de CPU e +0 MB; gemini 12,4% e +8,1 MB; rodada com o local
33,7–36,4% e +55,9 MB), gate completo 5811/16/2 (as 2 falhas antigas de
`test_websocket`) e RAG 8/8 · 0/8 · 6/6. Restart verde. `1.47.0+2085`.

Lacuna declarada: CPU/RAM são do servidor inteiro (as chamadas correm em
paralelo e a máquina é compartilhada); VRAM não existe nesta máquina.

---

## 26/11/2026 — Checkbox do comparador separado (TODO)

**Autor:** Freebuff (Buffy) — pedido do dono (*"Corrija o checkbox desatualizado
do comparador na linha 972 do TODO"*).

- `docs/ANALISE_SISTEMA_TODO.md`: “Comparador de modelos lado a lado + monitor de
  hardware” foi partido em **dois** itens — o comparador **✅ 26/11** (arquivos,
  rotas, painel, timeouts e tempos da prova viva) e o **monitor de CPU/RAM/VRAM
  por modelo** como pendência própria, com o motivo de ainda não ter sido feito.
- `iniciar/2026-11-26_conversa_omegadrakon.md` (§21), `iniciar/session.json`,
  `txt.txt`.

Só documentação: nenhum `.py` alterado, sem teste e sem restart; `1.47.0+2085`.

---

## 26/11/2026 — Espelho offline: restauração real provada (fila item 10)

**Autor:** Freebuff (Buffy) — pedido do dono (*"Siga para o item 10 da fila:
espelho com restauração real"*).

### Criados

- `docs/ESPELHO_RESTAURACAO.md` — dossiê com os comandos e os números da
  prova (venv limpo, gate, container offline, MANIFEST, limites).

### Modificados

- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (item 10 da fila, P2 nº
  19 e o checkbox da seção Continuidade), `iniciar/2026-11-26_conversa_omegadrakon.md`
  (§20), `iniciar/session.json`, `txt.txt`.
- **Fora do repositório (mídia do dono):** `/home/alex/dados/od-mirror/`
  recebeu o `requirements-dev.txt` que faltava (com linha nova no `MANIFEST`,
  agora 134/134) e a seção do teste de 26/11 no `README.md`.

### Intenção e estado

Transformar a prova antiga (resolução de dependências) em boot de verdade:
venv limpo só com wheels do espelho rodou o gate completo (5807/17/2, as 2
falhas já existentes no HEAD) e o `postgres:16-alpine` saiu do tar espelhado e
respondeu com `--network none`. Achado: o `requirements-dev.txt` era citado no
README mas não estava no acervo — corrigido. Nenhum `.py` do projeto alterado,
sem restart. `1.47.0+2085`.

---

## 26/11/2026 — Modo colapso: verificação ao vivo (fila item 9)

**Autor:** Freebuff (Buffy) — pedido do dono (*"Siga para o item 9 da fila:
modo colapso declarado"*).

### Criados

- nenhum arquivo novo.

### Modificados

- `docs/CHANGELOG.md` — seção da prova viva (sem bump).
- `docs/ANALISE_SISTEMA_TODO.md` — item 9 da fila ✅ e o checkbox da seção
  Continuidade fechados com a evidência.
- `iniciar/2026-11-26_conversa_omegadrakon.md` (§19), `iniciar/session.json`,
  `txt.txt`.

### Intenção e estado

O recurso já existia desde 21/11; faltava provar no processo vivo que ele
bloqueia as nuvens e avisa. Provado e revertido (liga → groq/gemini pulados,
resposta local com prefixo, `/health` degraded; desliga → up). Nenhum código
alterado, sem restart. `1.47.0+2085`. Limite: sem card próprio no painel.

---

## 26/11/2026 — Mapas offline: glifos não-latinos embutidos (fila item 8)

**Autor:** Freebuff (Buffy) — pedido do dono (*"Siga para o item 8 da fila:
mapas offline próximos do inventário"*).

### Criados

- `docs/MAPAS_OFFLINE.md` — números do `.pmtiles`, scripts medidos nos tiles,
  tabela de glifos, limites (CJK/hangul, z15) e critério para reabrir.
- `tests/test_mapa_glyphs.py` — 11 casos com leitor PBF próprio.
- 8 faixas de glifos em `site/vendor/fonts/Noto Sans Regular/` (+648 KB):
  1280–1535, 1536–1791, 1792–2047, 2304–2559, 3584–3839, 7680–7935,
  8192–8447 e 12288–12543.

### Modificados

- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (item 8 da fila ✅,
  P2 nº 17 e o checkbox dos mapas), `iniciar/2026-11-26_conversa_omegadrakon.md`
  (§18), `iniciar/session.json`, `txt.txt`.

### Intenção e estado

Fechar o “rótulo não-latino” com medição em vez de achismo: os campos
`name:*` existem nos tiles, os glifos que a fonte realmente tem foram
embutidos e o que a fonte não tem (CJK/hangul) ficou nomeado como limite,
tal como o z15. Sem mudança de estilo (o mapa segue mostrando `name`), sem
restart. `1.47.0+2085`.

---

## 26/11/2026 — Projeti fechado: referência do Orion + trilha de APK (fila item 7)

**Autor:** Freebuff (Buffy) — pedido do dono (*"Siga para o item 7 da fila:
Projeti (google-services.json, APK de 51 MB × backups, leitura do Orion)"*).

### Criados

- `docs/PROJETI_REFERENCIA.md` — estado dos 4 sub-itens, formato real da
  escala do Orion (exemplos sintéticos, sem dado pessoal), decisão de não
  portar o RPA e o achado da trilha de backups do APK.
- `backups/apk-v1.47.0-2085/` — par publicado (completo + arm64) arquivado e
  conferido com `aapt` (completo `4fa3bb88…`, arm64 `e096d1fd…`).

### Modificados

- `docs/VERSIONAMENTO.md` — §5 ganhou o passo 9 (arquivar e conferir o
  `versionCode` com `aapt`).
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (5 checkboxes do
  Projeti e item 7 da fila ✅), `iniciar/2026-11-26_conversa_omegadrakon.md`
  (§17), `iniciar/session.json`, `txt.txt`.

### Intenção e estado

Fechar o item 7 sem tocar no que exige aprovação: os originais de Projeti já
estão fora do servidor, então “apagar duplicata” virou decisão do dono sobre
um zip na HD dele. A conferência com `aapt` achou furo real na trilha de
backups (v1.44.0 ausente, 1.45.0 duplicado, 1.46.x/1.47.0 sem backup); o
1.47.0 foi arquivado e o checklist passou a exigir a conferência. Nenhum
`.py` alterado, sem restart. `1.47.0+2085`.

---

## 26/11/2026 — Referências do NV: security layer mapeada + DAG/scheduler (fila item 6)

**Autor:** Freebuff (Buffy) — pedido do dono (*"Siga para o item 6 da fila:
referência de DAG/scheduler e SECURITY_LAYER_ARCHITECTURE.md na frente NV"*).

### Criados

- `docs/SECURITY_LAYER_ARCHITECTURE.md` — contrato do NV v1.7.0 + mapeamento
  camada por camada no código vivo do OD + diferenças + 4 lacunas.

### Modificados

- `docs/NV_DAG_SCHEDULER_REFERENCE.md` — link cruzado para o doc novo.
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (fila item 6 ✅ e os
  dois checkboxes do NV), `iniciar/2026-11-26_conversa_omegadrakon.md` (§16),
  `iniciar/session.json`, `txt.txt`.

### Intenção e estado

Fechar o item 6 sem portar código: a metade DAG/scheduler já estava entregue
em 13/11; a da security layer só existia num arquivo fora do git. Agora a
intenção original e o que o OD já tem estão no mesmo lugar, com as lacunas
nomeadas. Nenhum .py tocado, sem restart. `1.47.0+2085`.

---

## 26/11/2026 — Comparador de modelos lado a lado no painel (fila item 5)

**Autor:** Freebuff (Buffy) — pedido do dono (*"continue"*, retomando a fila
combinada; o próximo item era o comparador de modelos).

### Criados

- `core/comparador_modelos.py` — mesmo prompt em 2–4 modelos da cadeia do
  chat, em paralelo, com latência e erro por modelo.
- `tests/test_comparador_modelos.py` — 19 casos (módulo, rotas e render node).

### Modificados

- `integrations/api/server.py` — rotas `GET /admin/comparador/modelos` e
  `POST /admin/comparador/comparar` + seção "Comparador de modelos" no
  `/admin` (`cmpCartoesHtml`, `cmpLoad`, `cmpComparar`).
- `tests/test_api.py` — espelho de rotas 146 → 148.
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (fila item 5 ✅),
  `iniciar/2026-11-26_conversa_omegadrakon.md` (§15), `iniciar/session.json`.

### Intenção e estado

Fechar a comparação ao vivo que o dono pedia ("usar a melhor IA" decidido por
observação, não por log de 05/11). Provado ao vivo com 3 modelos (groq
564,5 ms / gemini 2.625,4 ms / local 18.584,5 ms; parede 18,6 s = o mais
lento). `1.47.0+2085`. Limite: o visual não foi visto em navegador.

---

## 26/11/2026 — `/health` marca container subindo como `starting`

**Autor:** Freebuff (Buffy) — pedido do dono (*"Faça o /health marcar os checks
de container como transitórios nos primeiros minutos após o boot"*).

### Criados

- nenhum arquivo novo.

### Modificados

- `observability/health.py` — `STATUS_STARTING`, `CHECKS_TRANSITORIOS`
  (`mqtt`), `PREFIXO_TRANSITORIO` (`tool_`), `eh_check_transitorio()`,
  `segundos_desde_boot()`, `HealthMonitor(boot_window_s=…, boot_age=…)` com
  `na_janela_de_boot()`/`em_transitorio()`/`boot_window_s`; no `health()` o
  check transitório falhando sai `starting` + `transitorio: true` e não
  derruba o agregado, que ganhou a lista `transitorios`.
- `runtime/launcher.py` — `build_health()` liga a janela (padrão 300 s,
  `OD_HEALTH_JANELA_BOOT_S` sobrepõe, `0` desliga, valor inválido volta ao
  padrão).
- `integrations/notifier.py` — `_check_health` ignora item `transitorio`.
- `tests/conftest.py` — `OD_HEALTH_JANELA_BOOT_S=0` na suíte (nenhum teste
  depende do uptime da máquina).
- `tests/test_health.py` (5 casos), `tests/test_launcher_health_external.py`
  (3), `tests/test_notifier.py` (2).
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (checkbox + tarefa nova
  dos 2 testes de `test_websocket`), `iniciar/session.json`,
  `iniciar/2026-11-26_conversa_omegadrakon.md` (§14), `txt.txt`.

### Intenção e estado

**Intenção:** o `/health` é a fonte que app, painel, pós-reboot e notifier
lem — se ele chama de falha o que é container começando (boot de 26/11: 6
checks aos 22 s), o alarme falso se espalha por todas as camadas.

**Pronto e validado:** `starting` + `transitorio: true` sem esconder `ok:
false`; só `tool_*`/`mqtt`; falha real intacta; notifier não alarma; 10 casos
novos e **156 passed** na bateria tocada; `test_api` **215 passed**; restart
26/11 ~03:4x MainPID **61637**, `/health` ok=true 34 checks,
`transitorios: []`, journal `-p err` 0.

**Pela metade / próximo passo:** a janela está **fechada** agora (uptime >
5 min), então a prova viva do `starting` só acontece no próximo reboot — hoje
está coberta por teste com uptime injetado. O gate completo fecha **5778
passed / 16 skipped / 2 falhas**, e as 2 falham igual no HEAD sem esta mudança
(`test_websocket` ordem-dependente) — registrado no §4 do TODO.

## 26/11/2026 — Unit `od-pos-reboot` reinstalada com `TimeoutStartSec=360`

**Autor:** Freebuff (Buffy) — ordem do dono (*"Reinstale a unit od-pos-reboot
com o TimeoutStartSec=360 usando o sudo do .env e confirme com systemctl
show"*).

### Criados

- nenhum arquivo novo.

### Modificados

- `/etc/systemd/system/od-pos-reboot.service` (fora do git) — cópia do arquivo
  do repositório, `root:root`, 0644, `daemon-reload` feito.
- `docs/CHANGELOG.md`, `iniciar/session.json`,
  `iniciar/2026-11-26_conversa_omegadrakon.md` (§13), `txt.txt`.

### Intenção e estado

**Intenção:** fechar o pendente declarado na entrega anterior — a unit
instalada ainda tinha `TimeoutStartSec=300` e o limite podia cortar o
veredito no pior caso (180 s do core + 60 s dos containers + Telegram).

**Pronto e validado:** `systemctl show` antes → `TimeoutStartUSec=5min`,
`FragmentPath=/etc/systemd/system/od-pos-reboot.service`; depois →
**`TimeoutStartUSec=6min`**, `UnitFileState=enabled`, `NeedDaemonReload=no`;
`diff systemd/od-pos-reboot.service /etc/systemd/system/…` **vazio**. A senha
veio do `SUDO_PASSWORD` do `.env` por pipe (`sudo -S`), nunca impressa.

**Pela metade / limite:** não executei a unit para "provar" o arranque — ela é
oneshot de boot, roda o validador e mandaria uma segunda mensagem
("checagem manual") ao Telegram; a prova de execução real continua sendo a do
boot de 02:36 e a do próximo reboot.

## 26/11/2026 — Pós-reboot separa container subindo de falha real

**Autor:** Freebuff (Buffy) — pedido do dono (*"Faça o pós-reboot separar
containers ainda subindo de falha real antes de avisar no Telegram"*).

### Criados

- nenhum arquivo novo.

### Modificados

- `tools/validar_pos_reboot.py` — `eh_check_transitorio()` (`tool_*` + `mqtt`),
  `aguardar_transitorios()` (relê o `/health` a cada 5 s por até 60 s, **só**
  quando todos os falhando são transitórios), `_ler_health()` extraído,
  `coletar()` separa `reais_falhando` × `containers_pendentes`, relatório
  ganhou `containers: subiram em ~Ns` / `containers ainda fora do ar: …`.
- `systemd/od-pos-reboot.service` — `TimeoutStartSec` 300 → 360 s.
- `tests/test_validar_pos_reboot.py` — 4 casos novos (9 no arquivo).
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (checkbox fechado),
  `iniciar/session.json`, `iniciar/2026-11-26_conversa_omegadrakon.md` (§12),
  `txt.txt`.

### Intenção e estado

**Intenção:** o veredito do boot não pode chamar de falha o que é só container
começando (boot de 26/11: 6 checks `tool_*`/`mqtt` em `degraded` aos 22 s, todos
`up` logo depois) — mas também não pode esconder container que não subiu nem
atrasar o alarme de falha real.

**Pronto e validado:** janela de 60 s só para transitórios; falha real alarme
imediato; container que não sobe vira pendência explícita; `9 passed` (4 novos);
execução real `--sem-envio` → `/health up · 34 checks`, `exit=0`.

**Pela metade / próximo passo:** a prova no boot real depende do próximo
reboot (aqui a máquina está com 13 min de uptime); o caminho está coberto por
teste com `/health` simulado. **A unit instalada em `/etc/systemd/system`
continua com `TimeoutStartSec=300`** até o dono autorizar a reinstalação
(mudança de sistema exige ordem — regra 7).

## 26/11/2026 — Retomada "leia iniciar": reboot de 02:36 validado, item 11 fechado

**Autor:** Freebuff (Buffy) — pedido do dono (*"leia iniciar"*).

### Criados

- `iniciar/2026-11-26_conversa_omegadrakon.md` §11 — transcrição do turno.

### Modificados

- `iniciar/session.json` — checkpoint `retomada_leitura_iniciar_2026_11_26`
  (topo) com o estado medido do pós-reboot.
- `docs/CHANGELOG.md` — seção "Validação pós-reboot automática no Telegram"
  (o commit `006502c` não tinha entrada).
- `docs/ANALISE_SISTEMA_TODO.md` — fila item **11 ✅** com a prova do reboot;
  checkbox "Janela de aplicação do SO com prova de retorno" fechado; checkbox
  novo do alarme com container subindo (§4).
- `iniciar/ATRIBUICOES.md` (esta entrada) e `txt.txt`.

### Intenção e estado

- **Intenção:** cumprir as regras 3 e 4 (ler antes de assumir contexto e
  registrar a troca) e fechar o buraco de registro do commit `006502c`, que
  estava publicado sem `iniciar/`, CHANGELOG ou atribuição (regra 23).
- **Medido:** árvore limpa exceto o auto-registro do restart em `session.json`;
  `HEAD == origin/master == 006502c`; máquina **reiniciada 02:36** (uptime 4
  min no início do turno) com kernel **6.8.0-151-generic** e `reboot pendente:
  não`; `od-pos-reboot.service` **enabled**, rodou 20 s após o boot e mandou o
  veredito no Telegram (`🟢 Pós-reboot OK`, 5/5 serviços, 2/2 timers, `exit=0`,
  `data/pos_reboot.json` com `ok: true`); `/health` **ok=true com 34 checks**,
  nenhum fora de `up`; `od-core` MainPID 1219, `NRestarts=0`.
- **Estado:** nada alterado em código; sem restart e sem bump (leitura +
  registro). `tests/test_validar_pos_reboot.py` 5 passed.
- **Pela metade / próximo passo:** item 5 da fila (comparador de modelos lado a
  lado). Achado registrado: o pós-reboot alarmou `degraded` com os containers
  ainda subindo — checkbox no §4.

## 26/11/2026 — Validação pós-reboot automática no Telegram (origem não identificada)

**Autor:** **não identificado** (regra 23) — commit `006502c`, autor do commit
*Alex Projeti*, sem registro em `iniciar/`, CHANGELOG ou atribuição. Achado na
retomada de 26/11 ~02:45; nada foi adivinhado sobre quem escreveu.

### Criados (pelo commit, não por mim)

- `tools/validar_pos_reboot.py` — oneshot de boot: uptime, `/health` (espera
  180 s), 5 serviços, 2 timers, `/var/run/reboot-required`, kernel, 5 checks
  obrigatórios, estado em `data/pos_reboot.json` e Telegram.
- `systemd/od-pos-reboot.service` — `WantedBy=multi-user.target`, instalada e
  habilitada em `/etc/systemd/system`.
- `tests/test_validar_pos_reboot.py` — 5 casos (5 passed).

### Estado

**Provada no reboot real de 26/11 02:36:** `enabled`, rodou sozinha, `exit=0`,
Telegram enviado, kernel 6.8.0-151, `reboot pendente: não`. Só o **registro**
faltava — CHANGELOG, TODO e transcrição §11 escritos por mim neste turno.

## 26/11/2026 — Últimas seções do ciclo no painel do SO

**Autor:** Freebuff (Buffy) — ordem do dono (*"Mostre no painel do atualizador
as últimas seções do ciclo (apt, fwupdmgr, reboot) além do resumo numérico"*).

### Criados

- nenhum arquivo novo (transcrição §6).

### Modificados

- `integrations/api/server.py` — `id="so-secoes"` + `soSecoesHtml()` pura
  (tabela Quando · Seção · Resultado · Detalhe, mais recente primeiro, detalhe
  escapado), alimentada por `soLoad()`.
- `tests/test_painel_os_updater.py` — 3 casos novos (node das seções, container,
  "as 5 últimas do estado") → 12 no arquivo.
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (checkbox fechado),
  `iniciar/session.json`, `iniciar/2026-11-26_conversa_omegadrakon.md` (§6),
  `txt.txt`.

### Intenção e estado

**Pronto e validado:** status 200 com as 5 seções reais do estado; `/admin` com
container e função; 227 testes (api+painel); journal `-p err` 0; prova viva no
restart 02:10 (MainPID 2437040). Commit `c2f29b4`.

**Pela metade / próximo passo:** nada pendente desta entrega. Segue aberto só
o clique real do botão (aplica 67 pacotes + reboot) — decisão do dono.

## 26/11/2026 — Botão "Aplicar atualizações" no painel do SO

**Autor:** Freebuff (Buffy) — ordem do dono (*"Coloque um botão 'Aplicar
atualizações' no painel do atualizador de SO com confirmação dupla"*).

### Criados

- `systemd/od-os-updater-forcar.service` — oneshot root com `--forcar`
  (ignora o agendamento; é o que o botão dispara).
- `tests/test_painel_os_updater.py` — 9 casos.
- `/etc/sudoers.d/od-os-updater` (fora do git) — NOPASSWD **só** para
  `/usr/bin/systemctl start --no-block od-os-updater-forcar.service`;
  validado com `visudo -c`.

### Modificados

- `core/os_updater.py` — `iniciar_ciclo_forcado()`, `unidade_em_andamento()`,
  `status_painel()` e `UNIDADE_FORCAR`.
- `integrations/api/server.py` — seção "Atualizador de SO" no `/admin` (botão +
  duas confirmações, `soLoad`/`soAplicar`), rota `executar` → 202 via systemd
  (dry-run segue em processo), status barato e `_os_updater_or_503` sem 503.
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (checkbox fechado),
  `iniciar/session.json`, `iniciar/2026-11-26_conversa_omegadrakon.md` (§5),
  `txt.txt`.

### Intenção e estado

**Pronto e validado:** as 3 rotas deixaram de dar 503; status 200 com 67
pacotes/51 firmwares; dry-run 200; `/admin` com o botão e o aviso de reboot;
unit `inactive` (nada aplicado); sudo validado por `sudo -n -l` **sem
executar**; journal `-p err` 0. Testes: 224 (api + painel) + 53 (os_updater) +
3 (rota reboot). Commit `596066e`.

**Pela metade / próximo passo:** o botão **não foi disparado de verdade**
(aplicaria 67 pacotes e agendaria reboot) — fica para o dono decidir. Sem bump
(`1.47.0+2085`, servidor/painel).

## 26/11/2026 — Release 1.47.0 (APK com o card do atualizador de SO)

**Autor:** Freebuff (Buffy) — ordem do dono (*"Publique o APK com o card do
atualizador de SO, fazendo o bump SemVer e o checklist de release"*).

### Criados

- nenhum arquivo novo além dos APKs publicados em `site/` (não rastreados no
  git; `OmegaDrakon.apk` e `OmegaDrakon-arm64.apk`).

### Modificados

- Bump MINOR **1.46.1 → 1.47.0**, versionCode **2084 → 2085**: `.env`,
  `core/capabilities.py`, `app/pubspec.yaml`, `integrations/api/server.py`,
  `site/index.html`, `site/historico.html`, `docs/CHANGELOG.md`,
  `docs/README_VERSAO.md`.
- `core/os_updater.py` + `runtime/launcher.py` — sondagem de pacotes em thread
  própria (`aquecer_sondagem()` no boot) para não pesar na requisição.
- `tests/test_os_updater.py` — `test_sondagem_nao_bloqueia_a_requisicao` (53
  no arquivo).
- `iniciar/session.json`, `iniciar/2026-11-26_conversa_omegadrakon.md` (§4),
  `txt.txt`.

### Intenção e estado

**Pronto e validado:** APK 1.47.0/2085 publicado em `site/` (aapt confirma
versionName/versionCode), `/app/version` anuncia 1.47.0/2085 com o **mesmo
sha256** do binário; gate completo 5767 passed / 16 skipped / 0 falha; Flutter
analyze limpo e 267 passed. No caminho, um defeito real foi medido e corrigido
(`latencia` em degraded por `apt` dentro do `/health`, p95 356,7 ms → 53,1 ms)
e o `od-io-probe.timer` foi instalado. Commits `ba3d75d` e `604c2de`.

**Pela metade / próximo passo:** a máquina segue com **67 pacotes + 51
firmwares + reboot pendente** — aplicar agora é decisão do dono
(`sudo systemctl start od-os-updater.service`, agenda reboot +5 min).

## 26/11/2026 — Atualizador de SO visível no painel `/admin` e na aba Status

**Autor:** Freebuff (Buffy) — ordem do dono (*"Mostre o check os_updater no
painel /admin e na aba do app que já lê o /health"*).

### Criados

- `app/test/status_screen_test.dart` — 3 casos (números na tela, falha do
  ciclo, servidor antigo sem o bloco).

### Modificados

- `integrations/api/server.py` — bloco estruturado `os_updater` no `/health`
  (`_bloco_os_updater()`, fora do cache de 8s) e card "Sistema (SO)" em
  `visaoCards()`.
- `app/lib/screens/status_screen.dart` — card "Atualizador de SO" e checks
  `degraded` em laranja.
- `tests/test_api.py` — teste do bloco no `/health` + harness node do card.
- `docs/CHANGELOG.md`, `iniciar/session.json`,
  `iniciar/2026-11-26_conversa_omegadrakon.md` (§3), `txt.txt`.

### Intenção e estado

**Pronto e validado:** `/health` com bloco numérico ao vivo; painel com o card
"Sistema (SO)" (67 pac · 51 fw · reboot pendente); app com card próprio e
ícone de alerta para `degraded`. Python 306 passed na bateria tocada
(api/os_updater/health/launcher) e Flutter `analyze` limpo + 267 passed. Prova
viva no restart 00:57 (MainPID 2385376), journal `-p err` 0. Commit `7629334`.

**Pela metade / próximo passo:** o **APK não foi recompilado** — o card novo
só chega ao celular no próximo build com bump SemVer (deploy do app precisa de
ordem do dono). No app atual o check já aparece na lista genérica.

## 26/11/2026 — Estado do atualizador de SO no `/health`

**Autor:** Freebuff (Buffy) — ordem do dono (*"Coloque o estado do atualizador
de SO (reboot pendente, pacotes, falhas) como check no /health"*).

### Criados

- nenhum arquivo novo (transcrição §2 do dia).

### Modificados

- `core/os_updater.py` — `resumo_health()` + `_contar_pacotes_e_firmware()`
  (cache de 30 min; `apt list` medido em 0,54 s).
- `runtime/launcher.py` — `register_os_updater_health()` e chamada no
  `build_api_server()`.
- `tests/test_os_updater.py` — 3 testes novos (52 passed no arquivo).
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (checkbox do §4 fechado),
  `iniciar/session.json`, `iniciar/2026-11-26_conversa_omegadrakon.md` (§2),
  `txt.txt`.

### Intenção e estado

**Pronto e validado:** check `os_updater` **não-crítico** no `/health` com
`pacotes`, `firmwares`, `falhas` e `reboot_pendente`; prova viva após restart
(MainPID 2372820): `/health` 200 com **33 checks**, check em **3,7 ms**,
`degraded` com motivo "reboot pendente", journal `-p err` 0. Testes: 52 no
módulo + 39 em health/launcher. Commit `6dd0490`.

**Pela metade / próximo passo:** nada pendente desta entrega. Continua aberta
a decisão do dono sobre **aplicar** os 67 pacotes + 51 firmwares agora
(agenda reboot +5 min) — o check agora mostra isso no `/health`.

## 26/11/2026 — Timer do atualizador de SO instalado (`sudo` liberado)

**Autor:** Freebuff (Buffy) — ordem do dono (*"sudo está no env, pode ser usado
pelo OmegaDrakon"*), fechando o pendente de 25/11.

### Criados

- `iniciar/2026-11-26_conversa_omegadrakon.md` — transcrição do turno.

### Modificados

- `systemd/od-os-updater.service` — roda como root (com `User=alex` +
  `ProtectSystem=strict` o apt/dpkg não escreviam em 5 de 5 diretórios),
  `PrivateTmp=yes`, `DEBIAN_FRONTEND=noninteractive`,
  `EnvironmentFile=-.env`, `ExecStartPost` devolvendo o estado ao `alex`.
- `core/os_updater.py` — `notificar_telegram()` + `_env()`; `main()` passa o
  notificador; `_notificar` suprime envio em dry-run.
- `tests/test_os_updater.py` — 3 testes novos (canal ausente, envio real,
  dry-run sem envio); 49 passed.
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (checkbox fechado),
  `docs/ARCHITECTURE_v2.md` (linha dizia "06:00 diário"), `iniciar/session.json`,
  `txt.txt` (aviso ao dono).

### Intenção e estado

**Pronto e validado:** timer **enabled + active** (próxima execução dom 29/11
~03:16), `systemd-analyze verify` limpo, `--status` como root confirmando
67 upgradable / 51 firmwares / reboot pendente, canal Telegram provado nos dois
contextos (`CANAL_OK True`, `CANAL_NO_UNIT True`), 49 testes do módulo passando.
A ativação disparou o serviço uma vez (`Persistent=true` sem marcador):
respondeu `acao: aguardar`, nada instalado, nenhum reboot agendado.

**Pela metade / próximo passo:** **aplicar** as 67 atualizações + 51 firmwares
agora é decisão do dono, porque o ciclo agenda reboot em +5 min. Sem ordem, a
primeira aplicação real acontece sozinha no domingo 29/11 às ~03:16.

## 25/11/2026 — I2 (RAG híbrido) ligado com piso próprio medido

**Autor:** Freebuff (Buffy) — ordem do dono (*"Recalibre o piso do RAG híbrido
para ligar o I2 com evidência medida"*).

### Criados

- `tools/recalibrar_piso_hibrido.py` — medidor do piso: coleta os candidatos
  com a origem (denso × só-lexical), varre score × overlap (9.333 células) e
  imprime a faixa válida, o pior irrelevante e os resgates que sobrevivem;
  `--json`.

### Modificados

- `memory/rag.py` — `PISO_SCORE_LEXICAL = 0,47` (pior irrelevante + 0,023),
  `min_score_lexical` no construtor, piso aplicado ao candidato só-lexical por
  `doc_id`, métrica `descartados_lexicais`, `hibrido` ON por padrão e `dump()`
  expondo `hibrido`/`min_score_lexical`. Piso denso **intocado**.
- `runtime/launcher.py` — `top_k` do store 24 → `TOP_K_CANDIDATOS` (32).
- `tests/test_rag.py` — `TestCalibracaoHibrida` (8+8+6 nos dois modos + resgate
  do eval), default ligado/desligado explícito, env "0", piso só-lexical.
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (P1 nº 5 e checkbox),
  `docs/ARCHITECTURE_v2.md` (I2 ligado), `iniciar/session.json`,
  `iniciar/2026-11-25_conversa_omegadrakon.md` (§4 e §5).

### Intenção e estado

Trocar precisão por recall no escuro era o risco de 18/11; a medição mostrou
que o piso denso não separa e o piso só-lexical separa com margem. **Ligado**
com gate verde nos dois modos, sem bump (1.46.1+2084).

---

## 25/11/2026 — Atualizações do SO: ferramenta existente verificada

**Autor:** Freebuff (Buffy) — pergunta do dono (*"OD possui algum action ou
ferramenta para resolver isso, se não então crie"*).

### Medido (nada criado: já existe)

- `core/os_updater.py` + CLI + 3 rotas `/admin/os-updater/*` + units
  `systemd/od-os-updater.{service,timer}` + 19 testes.
- Status real: 56 pacotes, 51 firmwares, reboot pendente; última execução
  registrada (09/11) foi **dry-run**; timer **não instalado** (not-found) —
  a ação de instalar exige sudo e é do dono.

`iniciar/2026-11-25_conversa_omegadrakon.md` §5 registra os comandos.

---

## 25/11/2026 — Offsite do dump do Postgres: cópia provada + guarda por sha256

**Autor:** Freebuff (Buffy) — ordem do dono (*"Feche o offsite físico do backup
do Postgres fora da máquina"*).

### Criados

- `tools/checar_offsite_pg.py` — guarda do offsite: dump atual presente **e com
  o mesmo sha256** no snapshot mais novo de cada HD e dentro do tar que o
  `data/offsite_state.json` registra como enviado; `--json`; exit 1 só em
  divergência real.
- `tests/test_checar_offsite_pg.py` — 14 testes.

### Modificados

- `docs/CHANGELOG.md` — seção datada com as medições.
- `docs/ANALISE_SISTEMA_TODO.md` — P1 nº 7 e a checkbox do offsite fechados com
  evidência; sobra a mídia física fora do local (dono).
- `iniciar/session.json`, `iniciar/2026-11-25_conversa_omegadrakon.md` (§3),
  `iniciar/ATRIBUICOES.md`.

### Intenção e estado

- **Intenção:** o dump do Postgres já saía da máquina (HDs externas + canal do
  Telegram), mas ninguém provava que o arquivo que chegou é o que foi gerado —
  backup fora da máquina sem conferência é esperança.
- **Pronto/validado:** dump `od-2026-11-25_0250.sql.gz` com sha256
  `3bfaff1c…` idêntico na origem, nas **duas** HDs
  (`snapshot_od-2026-11-25_0346`/`0347`) e dentro do tar
  `od-2026-11-25_0301.tar.gz` enviado ao canal; **a cópia do HD restaura**
  (`testar_restauracao_pg.py`: 14 tabelas/604 linhas, 0,17 s); guarda
  `OFFSITE OK` (exit 0) e **14 passed**.
- **Limite declarado:** HDs na mesma casa e canal em nuvem; pendrive/SSD
  criptografado fora do local continua ação do dono.
- **Sem bump:** 1.46.1+2084.

---

## 25/11/2026 — Restart do `od-core`: reconhecimento de segurança do Vigia no ar

**Autor:** Freebuff (Buffy) — ordem do dono (*"Reinicie o od-core para ativar o
reconhecimento de segurança pelo chat, com registro e prova viva"*).

### Modificados

- `docs/CHANGELOG.md` — nota "No ar desde 25/11 14:27" na seção de 23/11.
- `iniciar/session.json` — checkpoint `restart_seguranca_no_ar_2026_11_25`
  (o auto-registro do serviço também gravou em `restarts_od_core`).
- `iniciar/2026-11-25_conversa_omegadrakon.md` — §2.
- `iniciar/ATRIBUICOES.md` — esta entrada.

### Intenção e estado

- **Intenção:** tirar do papel o comando que o dono pediu em 23/11 (reconhecer
  eventos de segurança pelo chat) — o código estava publicado desde 23/11 mas o
  processo era de 21/11.
- **Pronto/validado:** lote afetado **444 passed** (11,36 s) antes do restart;
  restart 14:27:34 com MainPID **1768401**, `NRestarts=0`, commit `229b5ba`;
  `/health` `ok=true` com **32 checks** (nenhum fora de `up`), journal `-p err`
  **0 entradas**; prova viva `POST /message "reconhece a segurança"` →
  `route=action_intent`, `fastpath:network_conhecer`, **29,1 ms**, sem LLM.
- **Pela metade:** nada deste lote. Limite declarado: a prova foi com fila
  vazia ("nada a reconhecer"); o ack com eventos reais foi provado em 23/11 e
  nos testes, não fabricado agora.
- **Sem bump:** 1.46.1+2084.

---

## 25/11/2026 — Retomada "leia iniciar": lote de 23/11 publicado, mas fora do ar

**Autor:** Freebuff (Buffy) — pedido do dono (*"leia iniciar"*).

### Criados

- `iniciar/2026-11-25_conversa_omegadrakon.md` (§1 — transcrição).

### Modificados

- `iniciar/session.json` — checkpoint `retomada_leitura_iniciar_2026_11_25`.
- `docs/ANALISE_SISTEMA_TODO.md` — §4: 3 sugestões deste turno como checkbox
  (regra 21).
- `iniciar/ATRIBUICOES.md`, transcrição de 25/11.

### Intenção e estado

- **Intenção:** cumprir as regras 3 e 4 (ler antes de assumir contexto e
  registrar a troca) e dizer onde a sessão está de fato.
- **Medido:** árvore limpa, `HEAD == origin/master == a909040`, `/health`
  `ok=true` com **32 checks** (nenhum fora de `up`), journal `-p err` desde
  23/11 com **0 entradas**, `/app/version` 1.46.1/2084, `od-core` MainPID
  **3986249** desde **21/11 05:38** — logo o lote de 23/11 (gate verde,
  publicado) **não está no processo**.
- **Estado:** nada alterado em código; sem restart e sem bump (leitura pura).
- **Pela metade (de outra autoria, herdado):** o restart do `od-core` para o
  comando de chat "reconhece a segurança" existir. Próximo passo exato:
  `systemctl --user restart od-core` + registro e prova viva.

---

## 23/11/2026 — Reconhecimento de eventos de segurança do Vigia via chat e action

**Autor:** Antigravity (Gemini 3.8 Flash High) — pedido do dono no `txt.txt`.

### Criados

- `iniciar/2026-11-23_conversa_omegadrakon.md` (§1 — transcrição).

### Modificados

- `tools/actions/actions.py` — `network_conhecer` aceita `alvo="seguranca"` (ou vazio quando apenas eventos de segurança estiverem pendentes) e chama `vigia.ack_seguranca()`; `network_bloquear` recusa com erro para segurança.
- `core/intents.py` — `_detect_vigia` reconhece termos de segurança ("reconhece a segurança", "reconhece os eventos de segurança", "limpar eventos de segurança", "pode parar de informar a segurança", "reconhece o ssh") e despacha para `("network_conhecer", {"alvo": "seguranca"})`.
- `integrations/notifier.py` — `_check_network` inclui instrução de reconhecimento ("Para reconhecer, responda no chat: 'reconhece a segurança'") no detalhe de `net:seguranca`.
- `tools/monitor/network_watchdog.py` — `ack_seguranca()` devolve `n: int`.
- `tests/test_intents.py` — testes de detecção de intenção e resposta para segurança em `TestVigiaResposta`.
- `tests/test_network_watchdog.py` — `TestNetworkConhecerSeguranca` (5 testes).
- `docs/CHANGELOG.md`, `iniciar/session.json`, `txt.txt`.

### Fechamento do gate — OpenCode (DeepSeek V4.1 Flash Free), 23/11 06:20

- `tests/conftest.py` — remove no import `OD_ORCHESTRATOR_GRAPH`,
  `OD_CHAT_PROVIDERS` e `OD_IA_ORDEM` herdados do ambiente da cascata (causa
  real das 52/53 falhas repetidas; nenhum defeito de código).
- `core/intents.py` — contexto de segurança fechado em
  segurança/sshd/invalid user; "limpar eventos do calendário" e frases
  genéricas não viram ack nem listagem.
- `tests/test_intents.py` — 6 testes negativos (`test_limpar_generico_nao_vira_vigia`).
- Gate completo: **5641 passed / 19 skipped / 0 falha** (241,82 s).
- Estado vivo: `pendentes_seguranca=[]`; `/health` ok=true; código novo ainda
  não está no processo (od-core de 21/11 05:38) — restart pendente de ordem.

### Intenção e estado

- **Intenção:** responder ao dono sobre o aviso `🟡 [WARN] network — 4 evento(s) de segurança pendente(s)` (erro de digitação ao tentar SSH como ALEX maiúsculo), cessar os avisos imediatamente limpando os 4 eventos com `ack_seguranca()`, e fechar a lacuna funcional permitindo reconhecer eventos de segurança diretamente pelo chat e pela action `network_conhecer` sem precisar de terminal.
- **Estado:** concluído, gate verde, árvore pronta para commit. Falta só o
  restart do `od-core` (autorização) para o comando de chat ficar vivo.

---

## 21/11/2026 — Verify token do webhook Meta

**Autor:** Freebuff (Buffy) — pedido do dono.

### Modificados

- `.env` (não versionado) — `OD_META_VERIFY_TOKEN` gerado (43 caracteres).
- `docs/META_CONEXAO.md` §7/§8 — estado das chaves e passo a passo do painel.
- `docs/ANALISE_SISTEMA_TODO.md` §9 — verify token marcado como pronto.
- `iniciar/`.

### Intenção e estado

- **Intenção:** deixar a verificação do webhook pronta e encurtar o que falta.
- **Estado:** `GET /webhook/meta` devolve o challenge com 200 local **e pelo
  Funnel**; token errado dá 403. Faltam `OD_META_TOKEN`, `OD_META_PHONE_ID`
  e `OD_META_APP_SECRET` (só a Meta emite); o POST segue 503 até lá.

---

## 21/11/2026 — Resumo do estado para o Meta AI

**Autor:** Freebuff (Buffy) — pedido do dono no `txt.txt`.

### Modificados

- `docs/RESUMO_PARA_META_AI.md` (novo) — índice dos docs + resumo do estado
  do sistema para colar no Meta AI.
- `docs/CHANGELOG.md`, `iniciar/`, `txt.txt` (não versionado).

### Intenção e estado

- **Intenção:** impedir que o Meta AI invente capacidades/pendências por não
  conhecer o estado real.
- **Estado:** pronto. Não havia arquivo equivalente; o `txt.txt` foi
  reescrito com o inventário dos 31 itens de `docs/`, a resposta sobre a
  fonte da verdade (não há uma única) e o caminho do resumo.

---

## 21/11/2026 — Retorno após queda de energia (aviso no Telegram + BIOS)

**Autor:** Freebuff (Buffy) — pedido do dono.

### Modificados

- `core/queda_energia.py` (novo) — detecta boot recente sem desligamento
  registrado e calcula o tempo fora do ar.
- `integrations/notifier.py` — alerta de boot passa a anunciar queda de
  energia com a duração, mantendo o texto antigo quando não há sinal.
- `tests/test_queda_energia.py` e `tests/test_notifier.py` — 11 testes novos.
- `docs/QUEDA_DE_ENERGIA.md`, `docs/CHANGELOG.md`, `iniciar/`.

### Intenção e estado

- **Intenção:** saber que o servidor voltou e por quanto tempo ficou fora.
- **Estado:** aviso implementado. O **AC Recovery do BIOS não é programável
  por software neste OptiPlex 3040** — o passo físico está documentado e
  pendente de alguém na frente da máquina.

---

## 21/11/2026 — Sondas públicas `/api/ping` e `/api/public/inventario`

**Autor:** Freebuff (Buffy) — pedido do dono no `txt.txt` de 21/11.

### Modificados

- `integrations/api/server.py` — duas rotas públicas (146 no total) e os
  handlers `api_ping` / `api_public_inventario`.
- `integrations/homebox.py` — `HomeboxClient.publico()` (só nome, local,
  categoria, quantidade).
- `tests/test_api.py` (contagem e 3 testes), `tests/test_homebox.py` (1
  teste), `docs/META_CONEXAO.md`, `docs/CHANGELOG.md`, `iniciar/`.

### Intenção e estado

- **Intenção:** sonda barata para monitor externo e vitrine do inventário
  sem expor série/preço.
- **Estado:** as duas respondem sem credencial; inventário com Homebox fora
  devolve 503 honesto; nenhuma rota existente mudou de comportamento.

---

## 21/11/2026 — Ideias do `txt.txt` no TODO + conexão com a Meta

**Autor:** Freebuff (Buffy) — pedido do dono no `txt.txt` de 21/11.

### Modificados

- `integrations/meta.py` (novo) — WhatsApp Cloud API: verificação do webhook,
  assinatura `X-Hub-Signature-256`, payload e envio pelo Graph.
- `integrations/api/server.py` — `GET/POST /webhook/meta` (144 rotas).
- `runtime/launcher.py` — handler montado só com credencial.
- `tests/test_meta.py` (novo, 25 testes), `tests/test_api.py` (contagem).
- `docs/META_CONEXAO.md` (novo), `docs/ANALISE_SISTEMA_TODO.md` (§9),
  `docs/CHANGELOG.md`, `iniciar/`.

### Intenção e estado

- **Intenção:** deixar a conexão pronta e dormente, para o dono só colar as
  credenciais no `.env` e apontar o webhook no painel da Meta.
- **Estado:** fail-closed (sem app secret não passa assinatura; sem
  credencial as rotas respondem 503/403); nada mais do sistema muda. As 4
  ideias do `txt.txt` estão na seção 9 do TODO com o que já existe e o que
  falta.
- **Limite:** não há API pública do Meta AI — a conversa é pelo WhatsApp; a
  foto→Homebox e o religar pós-queda dependem de trabalho e de BIOS.

---

## 21/11/2026 — Auto-registro do restart do `od-core` (regra 4)

**Autor:** Freebuff (Buffy) — item aberto do TODO desde 18/11.

### Modificados

- `core/registro_restart.py` (novo) — grava PID/commit/branch/horário/host/
  modo/usuário (e motivo opcional) em `iniciar/session.json`, chave
  `restarts_od_core` com os últimos 30.
- `runtime/launcher.py` — gancho no início do `main()`, só no modo `all`.
- `tests/test_registro_restart.py` (novo, 7 testes).
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`, `iniciar/` (§5).

### Intenção e estado

- **Intenção:** o registro do restart deixa de depender de quem reiniciou
  lembrar (regra 4) e passa a ser fato do serviço.
- **Estado:** append-only com `flock`, idempotente por PID, limite de 30,
  nunca corrompe JSON ilegível nem derruba o boot; desligável com
  `OD_REGISTRAR_RESTART=0`. Gate completo verde.
- **Limite:** o motivo só aparece quando `OD_RESTART_MOTIVO` é exportado; só o
  modo `all` registra.

---

## 21/11/2026 — Modo colapso declarado (P1 nº 6) + polkit do vigia liberado

**Autor:** Freebuff (Buffy) — pedido *"proximo do todo"*; correção do dono sobre
acesso root.

### Modificados

- `core/colapso.py` (novo) — estado persistido, contagem de falhas de nuvem,
  declaração manual/automática e sonda TCP para revogar.
- `core/orchestrator.py` — bloqueio de nuvem nos dois caminhos + prefixo de
  aviso na resposta.
- `runtime/launcher.py` — loop do monitor + check `colapso` no `/health`.
- `tools/actions/actions.py` — action `colapso` (`status|ligar|desligar`),
  catálogo **132**.
- `tests/test_colapso.py` (novo, 17 testes) + contagens de catálogo.
- `/etc/polkit-1/rules.d/49-od-energia.rules` (fora do repo) — regra que libera
  o desligamento do vigia de energia.
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`, `iniciar/` (§4).

### Intenção e estado

- **Intenção:** fechar o último P1 aberto — quando a nuvem cai, o OD responde
  só com a IA local e **diz isso**, em vez de improvisar em silêncio.
- **Estado:** `colapso` liga/desliga pelo chat, o orquestrador pula provedores
  de nuvem, a resposta sai prefixada e o `/health` degrada com o motivo;
  gate **5568 passed / 19 skipped / 0 falha**. `pkcheck` agora responde
  **rc=0**: o desligamento do vigia de energia está autorizado de verdade.
- **Correção registrada:** eu havia dito que não tinha senha/root; o
  `SUDO_PASSWORD` está no `.env` e foi usado para instalar a regra.
- **Limite:** o colapso automático não foi forçado contra a nuvem (cota); o
  manual foi provado em teste e a sonda mede internet, não cota.

---

## 21/11/2026 — Vigia de energia por inferência (aviso + desligamento gracioso)

**Autor:** Freebuff (Buffy) — pedido do dono, continuação do monitor sem USB.

### Modificados

- `core/energia.py` (novo) — `Detector` + `VigiaEnergia`, leitura de ARP/rota,
  âncoras com validade, estado persistido.
- `runtime/launcher.py` — loop supervisionado + check `energia` no `/health`.
- `runtime/setup/energia_polkit.sh` + `od-energia.rules` (novos) — liberar o
  desligamento com sudo, uma vez.
- `tools/actions/actions.py` — `energia_status` e `energia_cancelar`
  (catálogo **131**).
- `tests/test_energia.py` (novo, 21 testes) + contagens de catálogo.
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`, `iniciar/` (transcrição
  §3, `session.json`, este arquivo).

### Intenção e estado

- **Intenção:** ter aviso e desligamento gracioso mesmo sem telemetria do
  no-break — a queda é inferida pelo sumiço simultâneo dos aparelhos da LAN,
  com confirmação e carência para não desligar por susto.
- **Estado:** leitura real **15 âncoras / gateway visto / normal**; máquina de
  estados testada (suspeita → confirmada → desligando, cancelamento e volta);
  gate **5551 passed / 19 skipped / 0 falha**. `pkcheck` ainda **nega** o
  desligamento (falta a regra polkit) — o vigia avisa e não desliga.
- **Limite:** infere queda, não mede bateria; reboot de roteador se parece com
  queda (mitigado por 3 ciclos + 3 min + 8 min + aviso). Telemetria real virá
  do BMS RS485/CAN da Felicity.

---

## 21/11/2026 — Homebox em uso: inventário físico da Nicky (9 peças, 2 locais)

**Autor:** Freebuff (Buffy) — pedido do dono (*"colocar para funcionar"* +
*"o que temos guarde no homebox"*, com o `txt.txt` do plano solar).

### Modificados

- `integrations/homebox.py` — `locais()`, `_local_id()` e
  `local/fabricante/modelo/serie` em `criar`/`atualizar`.
- `tools/actions/actions.py` — mesmos parâmetros nas actions e **nova
  `homebox_locais`** (catálogo **129**).
- Testes de contagem de catálogo (6 arquivos) e 7 testes novos em
  `tests/test_homebox.py`.
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`, `iniciar/` (transcrição
  §2, `session.json`, este arquivo).

### Intenção e estado

- **Intenção:** tirar o Homebox do estado de teste e fazer dele o inventário
  real da parte física, com local, fabricante, modelo e série — para o dono e
  o OD planejarem a Fase Nicky (solar 12 V).
- **Estado:** **9 peças / 10 locais / R$ 1.743** cadastrados; locais
  "Nicky — Servidor" e "Energia — Fase 1"; bateria Felicity (comprada,
  entrega 23–24/11), no-break Attiv 1500 VA BI e PWM 30 A com as regras de
  ouro nas notas. Gate **5530 passed / 19 skipped / 0 falha**; `od-core`
  reiniciado com **129 actions**.
- **Correção:** o `txt.txt` diz que falta instalar o Home Assistant; ele já
  roda em Docker aqui — o próximo passo é configurar, não instalar.
- **Limites:** bateria ainda não chegou (dados da compra); Pi 4/ESP-01S sem
  série; preço do OptiPlex e do no-break não constam.

---

## 21/11/2026 — Acervo do Raul fechado, APK instalado e leitura de `analise/`

**Autor:** Freebuff (Buffy) — sessão de 21/11 ~01:45, pedido do dono (*"apk
instalado, pode fechar o acervo e leia a pasta analise"*).

### Modificados

- `docs/ANALISE_SISTEMA_TODO.md` — checkbox da playlist do Raul marcado como
  fechado com a prova; nota nova na pendência de energia com o que existe em
  `analise/No Break/`; checkbox novo para o dono decidir a quarentena de 38
  arquivos; linha do Vigia atualizada (APK instalado).
- `iniciar/session.json`, `iniciar/ATRIBUICOES.md` e
  `iniciar/2026-11-21_conversa_omegadrakon.md` (novo).

### Intenção e estado

- **Intenção:** encerrar o lote da playlist do Raul Seixas deixado aberto em
  18/11 e registrar a confirmação de instalação do APK 1.46.1+2084, além de
  ler a pasta `analise/`.
- **Estado do acervo:** unidade terminou em 18/11 23:38 (19/19 lotes
  `codigo=0`); hoje **502 mp3 = 502 linhas**, 0 caminho ausente, **0 duplicata
  exata** por sha256, `.m3u` regerados e **AzuraCast 504 = 502 + 2 locuções**;
  Raul **1 → 141 faixas**. Quarentena de 38 arquivos fora do acervo, nenhum
  idêntico — decisão do dono, nada apagado.
- **`analise/`:** só `No Break/` (9 imagens). Prints de 11/04 do Attiv 1200 VA
  e fotos de 28/04 de um **Attiv 1500 VA Bivolt** (HS BI.A0008555344, 1500 VA /
  750 W, 2 baterias 12 V 7 Ah). **Sem USB/serial** → não dá shutdown gracioso;
  a compra de um modelo com USB segue pendente.
- **Sem bump** (1.46.1+2084, agora instalado); nenhum código alterado.
- **Limite:** a instalação no celular é declaração do dono; a análise do
  no-break é das fotos + fichas públicas da Intelbras, não de inspeção física.

---

## 19/11/2026 — Release 1.46.1+2084: APK do Vigia da Rede (+ fix do push)

**Autor:** Freebuff (Buffy) — sessão de 19/11 ~17:00, ordem do dono ("gere o apk").

### Modificados

- `app/pubspec.yaml` — `1.46.1+2084`; `.env` `OD_VERSION=1.46.1` (não
  rastreado); `core/capabilities.py` (fallback); `integrations/api/server.py`
  (`_APP_VERSION_CODE = 2084`).
- `site/index.html` — badge/card em 1.46.1, tamanhos ~26/~70 MB, versionCode
  2084 e contagem 79; `site/historico.html` — 79 lançamentos, Era 9 com 13
  releases e a entrada de 19/11.
- `docs/CHANGELOG.md`, `docs/README_VERSAO.md`, `iniciar/session.json`,
  transcrição (§9).
- `site/OmegaDrakon.apk` e `site/OmegaDrakon-arm64.apk` regerados
  (`build_apk.sh`; `site/*.apk` é gitignored).

### Intenção e estado

- **Intenção:** entregar no celular o Vigia da Rede na tela do alerta junto
  com o fix do push. O build anterior saía com code 2083 (o já instalado) e a
  auto-atualização só instala code maior; daí o bump PATCH.
- **Estado:** `aapt2` `2084/1.46.1`; `/app/version` anuncia 2084 com `size`
  72.488.590 e sha `ac60b136…` igual ao arquivo; arm64 200 com 27.038.253 B;
  `od-core` MainPID 1837735, `NRestarts=0`, `/health` ok=true. Gate Python
  **5523 passed / 19 skipped / 0 falha**; `flutter test` **264 passed /
  2 skipped**; `flutter analyze` 0 issues.
- **Limite:** instalação no aparelho é manual e não foi feita nesta sessão.

---

## 19/11/2026 — Vigia da Rede no app: Reconhecer e Bloquear na tela do alerta

**Autor:** Freebuff (Buffy) — sessão de 19/11 ~16:50, ordem do dono.

### Modificados

- `app/lib/services/od_api.dart` — `listVigiaPendentes`, `conhecerDispositivo`,
  `bloquearDispositivo` (mesmas rotas `/admin/vigia*` do painel/chat) e o
  modelo `OdDispositivoPendente` (rótulo, estado, "visto há…", "desde").
- `app/lib/screens/dashboard_screen.dart` — card do Vigia no Painel
  (admin-only, best-effort), Reconhecer direto e Bloquear com confirmação;
  recarrega o card após a ação.
- `app/test/vigia_rede_test.dart` (novo) — 7 testes (REST + tela).
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (checkbox fechado),
  `iniciar/session.json` e transcrição (§8).

### Intenção e estado

- **Intenção:** o aviso de dispositivo desconhecido chegava no app sem os
  botões do lado; o dono tinha de trocar de tela. A ação agora fica onde o
  alerta aparece, com confirmação no bloqueio (operação de roteador).
- **Estado:** `flutter analyze` 0 issues; `flutter test` **264 passed /
  2 skipped**; gate Python **5523 passed / 19 skipped / 0 falha**. Sem bump e
  sem restart (mudança só no app). **APK pendente de ordem explícita do dono.**

---

## 19/11/2026 — Falha controlada do restore: aviso real no Telegram

**Autor:** Freebuff (Buffy) — sessão de 19/11 ~16:30, ordem do dono.

### Modificados

- `runtime/verificar_restauracao_pg.py` — `--dump` (dump específico) e `.env`
  em execução manual (o systemd já entrega o ambiente; `python -m` puro ficava
  sem canal).
- `tools/testar_restauracao_pg.py` — recusa dump ilegível **antes** de subir o
  cluster, com mensagem clara; gzip validado em streaming.
- `tests/test_restauracao_pg.py` — +2 testes (dump corrompido, repasse do
  `--dump`).
- `docs/CHANGELOG.md`, `iniciar/session.json` e transcrição (§7).

### Intenção e estado

- **Intenção:** exercitar de verdade o caminho de falha do verificador semanal
  (antes só coberto por teste injetado).
- **Estado:** **provado.** Dump corrompido de teste → `exit=1`, estado
  `ok=false` e **mensagem entregue no Telegram**; execução normal em seguida
  voltou ao verde em silêncio (`RESTORE OK · 14 tabelas`). Teste em `/tmp`
  removido, nenhum dump real tocado, timer intacto.
- **Pela metade:** nada em aberto aqui; o offsite físico do dump continua sendo
  outra perna da entrega.

---

## 19/11/2026 — Verificação semanal do restore com aviso no Telegram

**Autor:** Freebuff (Buffy) — sessão de 19/11 ~16:20, ordem do dono.

### Criados

- `runtime/verificar_restauracao_pg.py` — runner semanal: restaura em cluster
  temporário, grava `data/pg_restore_verificacao.json` e avisa no Telegram
  **só quando falha** (`--dry-run` para teste).
- `systemd/od-pg-restore.service` e `systemd/od-pg-restore.timer` — domingo
  03:30, `Persistent=true`, `PrivateTmp`, escrita restrita a `data/`.
- `tests/test_verificar_restauracao_pg.py` — 6 testes.

### Modificados

- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`, `iniciar/session.json`
  e transcrição de 19/11 (§6).

### Intenção e estado

- **Intenção:** transformar a prova manual da restauração em vigilância
  semanal; falha de backup não pode ser silêncio.
- **Estado:** **pronto e no ar.** Timer ativo (`NEXT Sun 2026-11-22 03:30`);
  execução real da unit **success/0** em 3,5 s, 14 tabelas/589 linhas, estado
  `ok=true`, zero resíduo em `/tmp`, sem mensagem no sucesso.
- **Pela metade:** o disparo real do Telegram em falha não foi exercido (não
  se manda alarme falso); o caminho está coberto por teste injetado. Offsite
  físico do dump segue pendente.

---

## 19/11/2026 — Backup do Postgres: restauração real provada (P1 nº 7)

**Autor:** Freebuff (Buffy) — sessão de 19/11 ~16:00, pedido `continue`.

### Criados

- `tools/testar_restauracao_pg.py` — sobe cluster PostgreSQL temporário em
  `/tmp`, restaura o dump mais recente e compara as linhas com os blocos
  `COPY` do próprio dump (sem tocar no banco `od`, sem superusuário).
- `tests/test_restauracao_pg.py` — 4 testes da contagem de linhas do dump.

### Modificados

- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (P1 nº 7 com a metade da
  restauração provada), `iniciar/session.json` e transcrição de 19/11 (§5).

### Intenção e estado

- **Intenção:** o dump diário existe desde 13/11 e nunca tinha sido restaurado;
  fechar o DoD "restauração testada" com evidência medida.
- **Estado:** **provado.** Dump de 19/11 02:50 (37.084 B): restore OK em
  **0,17 s**, **14 tabelas**, **589 linhas** iguais às do dump. Defeitos pegos
  no caminho: stdin do `psql` recebendo o descritor comprimido do gzip e
  stderr em latin-1.
- **Pela metade:** o **offsite físico** (cópia fora da máquina) continua
  pendente; e o verificador ainda é manual (sugerido timer semanal).

---

## 19/11/2026 — Cascata de IAs reordenada por medição (Freebuff, Kilo, Agy, resto)

**Autor:** Freebuff (Buffy) — sessão de 19/11 ~15:35, ordem do dono sobre a
ordem das IAs na cascata.

### Criados

- `tools/medir_cascata_ias.py` — roda o mesmo prompt em todas as CLIs de
  `orquestrador.CLIS`, mede tempo/resultado e ordena; `--json` grava o laudo.

### Modificados

- `orquestrador.py` — `KILO_MODELO` → `kilo/kilo-auto/free` (o antigo saiu do
  catálogo); Codex sem o conflito `-s workspace-write` + `--approve-for-me`;
  Gemini com `--skip-trust`; novo `ORDEM_CLIS_2026_11_19` com a ordem medida
  aplicada sobre `CLIS`; `CLI_SESSAO_OPCOES` na mesma ordem.
- `integrations/api/server.py` — `SESSAO_CLIS` espelhado e seletor de CLI do
  `/admin` gerado dele (`_opcoes_sessao_html()`), em vez de 3 opções fixas no
  HTML.
- `tests/test_orquestrador.py` — ordem esperada e contratos de Codex/Gemini/Kilo.
- `docs/IAS_DISPONIVEIS.md` (§2.1 + histórico), `docs/CHANGELOG.md`,
  `docs/ANALISE_SISTEMA_TODO.md`, `iniciar/session.json` e transcrição de 19/11.

### Intenção e estado

- **Intenção:** a ordem da cascata era histórica, não medida; e o topo pedido
  pelo dono (Freebuff) não é automatizável hoje. Medir, corrigir as
  invocações quebradas e ordenar por resultado real.
- **Estado:** **pronto, validado e no ar.** Kilo ok em 11,6 s (modelo novo),
  Agy ok em 10,65 s, OpenClaude 3,3 s e Cline 6,6 s; as demais falham por
  autenticação/cota e ficaram por fail-fast. Gate completo **5511 passed /
  19 skipped / 0 falha**; restart 15:51:22 MainPID **1720925** com `/admin`
  listando a ordem medida e `/health` ok=true 30 checks.
- **Limite:** afere disponibilidade/latência, não a qualidade do código; o
  Freebuff entra em 1º no dia em que expuser prompt não-interativo.

---

## 19/11/2026 — "Decisão de 24 h" vencida reaparecendo: o APP republicava a notificação

**Autor:** Freebuff (Buffy) — sessão de 19/11 ~15:30, relato do dono.

### Modificados

- `app/lib/services/push_service.dart` — `onMessageOpenedApp` e
  `getInitialMessage()` não chamam mais `show()`; só o foreground exibe.
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`, `iniciar/session.json`
  e transcrição de 19/11.

### Intenção e estado

- **Intenção:** o servidor já não reavisa (fix 18/11); o que reaparecia era a
  notificação antiga republicada a cada toque/abertura do app.
- **Estado:** **corrigido e validado** (`flutter analyze` 0 issues, `flutter
  test` 257 passed / 2 skipped). **Pela metade no dispositivo:** o APK
  publicado (1.46.0+2083) ainda tem o comportamento antigo; falta o próximo
  build (deploy do app exige ordem do dono).
- **Limite:** a mensagem já entregue não sai da bandeja retroativamente.

---

## 19/11/2026 — Vigia da Rede: alerta com status de conexão e resolução pelo chat/painel

**Autor:** **implementação de origem não identificada** — lote achado na árvore
na retomada "leia iniciar" de 19/11 ~14:55 (mtimes 13:39–14:14), sem registro.
**Fechamento por Freebuff (Buffy)** na ordem "assuma e feche" (19/11 ~15:10).

### Modificados (não commitados)

- `tools/monitor/network_watchdog.py` — `vizinhos_sem_ping()` e
  `pendentes_ricos()` (`nome`, `ultima_vez`, `conectado` na linha de estado).
- `integrations/notifier.py` — `formata_dispositivo()` pura; sem o campo novo
  não afirma status.
- `tools/actions/actions.py` — actions `network_conhecer` / `network_bloquear`
  (catálogo 126 → 128).
- `core/intents.py` — fast path "reconhece o 2" / "bloqueia o 2" com contexto
  de rede obrigatório.
- `core/orchestrator.py` — gate de papel das duas actions; `network_bloquear`
  como escrita sensível.
- `integrations/api/server.py` — `GET /admin/vigia`,
  `POST /admin/vigia/conhecer`, `POST /admin/vigia/bloquear` e seção no painel.
- `tests/` — `test_network_watchdog`, `test_notifier`, `test_intents`,
  `test_api`, `test_actions_catalog`, `test_capabilities`, `test_mcp_od`,
  `test_orchestrator`, `test_orchestrator_action_registry`.

### Intenção e estado

- **Intenção:** o alerta `net:dispositivo-novo` prometia "responda quando
  reconhecer (ou 'bloqueia o X')" sem canal nenhum (sem intent, rota ou
  botão) e sem dizer se o aparelho ainda está na rede.
- **Estado: FECHADO e no ar (19/11 15:15).** Autorização do dono ("assuma e
  feche"). Gate completo **5510 passed / 19 skipped / 0 falha** (228,43 s),
  depois de corrigir na causa o vermelho do `test_corpus_frases_dono.py`
  (apontava para o `txt.txt` efêmero, zerado hoje → origem passou para a
  transcrição de 17/11, sem afrouxar o assert). Commit `7ae65d8`; restart
  MainPID **1677502**, NRestarts=0, journal `-p err` 0, `/health` ok=true 30
  checks, `GET /admin/vigia` 200 (1 pendente real, `conectado=false`) e 401 sem
  credencial; fast path vivo: "reconhece o dispositivo" → `network_conhecer`,
  "bloqueia o 2" → `network_bloquear`, "quero reconhecer meu erro" → `None`.
- **Sem bump** (1.46.0+2083): servidor/painel, contrato do app intacto.

---

## 18/11/2026 — Faixas do Raul em "Desconhecido": artista descartado no download

**Autor:** Freebuff (Buffy) — sessão de 18/11 ~20:10, relato do dono ("o sistema
acha o nome da música mas não o cantor; muitas do Raul Seixas estão aparecendo
como desconhecido").

### Modificados (pipeline oficial, fora do repo)

- `/home/alex/dados/musicas/musica.py` — `artistas_da_info()` (novo: lê
  `artist`/`artists`/`creator`/`uploader`/`channel`, sem "- Topic"/VEVO);
  `extrair_playlist()` carrega `artistas`; `baixar_musica_individual()` usa
  `extract_info(download=True)`, grava `TPE1`/`TIT2` e renomeia
  `Artista - Título.mp3` antes do dedupe; `garantir_tags_basicas()` não quebra
  mais em mp3 sem header ID3.
- Backfill: 106 faixas re-tagueadas/renomeadas com evidência da lista
  (`logs/artista_backfill_2026-11-18.log`, rollback em
  `backups/acervo_antes_backfill_artista_20261118.db`).
- Registro: `docs/CHANGELOG.md`, `iniciar/2026-11-18_conversa_omegadrakon.md`
  §15, `iniciar/session.json` (`artista_desconhecido_raul_2026_11_18`).

### Intenção e estado

- **Intenção:** o artista existe na origem (canal do vídeo); o pipeline o
  jogava fora e a IA só repetia "Desconhecido". Capturar na fonte, sem IA,
  resolve downloads novos; o acervo já gravado precisa de backfill.
- **Estado:** corrigido e aplicado. Download real validado
  (`Raul Seixas - Metamorfose Ambulante.mp3`, `TPE1=Raul Seixas`); acervo com
  0 Desconhecido (fora um arquivo cujo título é literalmente "Desconhecido");
  AzuraCast com 108 faixas de Raul Seixas + 8 duetos.
- **Faixa sem título resolvida:** `Desconhecido - Desconhecido.mp3` era
  duplicata **exata** de `Raul Seixas - Metamorfose Ambulante.mp3` (mesmo MD5
  do PCM decodificado, mesma duração; log de 17/11 mostra a renomeação por IA
  trocando o nome). Movida para `revisar/duplicadas/` pela função do próprio
  pipeline — nada foi apagado.
- **Limite:** não há teste do repo para o `musica.py` (script externo, sem
  suíte); a verificação foi por execução real e consulta ao acervo/AzuraCast.

---

## 18/11/2026 — Bug do dono: "Decisão de 24 h" chegando com prazo vencido

**Autor:** Freebuff (Buffy) — sessão de 18/11 ~19:40, relato do dono ("app fica
me mandando mensagem: Decisão de 24 h - xxxxx, já passou do prazo, deveria não
aparecer").

### Modificados

- `integrations/radio_cantores.py` — `registrar_para_apagar()` ganhou
  `ao_abrir_janela=` (callback só na abertura de janela) e **reabre** a janela
  quando a faixa volta depois de `apagada` (vencida/negada).
- `integrations/radio_link.py` — aviso ao dono dentro de `ao_abrir_janela`
  (antes `_avisar` rodava a cada chamada).
- `integrations/radio_pro.py` — idem, via `notificar_dono`.
- `tests/test_radio_cantores.py` — 3 testes novos (abertura única, permitida
  não reavisa, vencida reabre uma janela só).
- `docs/CHANGELOG.md`, `iniciar/session.json`, transcrição §14.

### Intenção + estado

- **Intenção:** parar o spam de "Decisão de 24 h" de prazo já vencido (registro
  idempotente devolvido a cada novo pedido/download) **sem** abrir buraco no
  bloqueio: faixa que voltou ganha **uma** janela nova, não um aviso por toque.
- **Pronto/validado:** 310 passed nos testes de rádio (cantores/link/pro/
  cobertura/curadoria); **GATE COMPLETO 5468 passed / 19 skipped / 0 falha**
  (221 s). `od-core` reiniciado, `/health` `ok=true`.
- **Limites:** a mensagem antiga que já está no Telegram/app não é apagada
  (é histórico); o que para é o reenvio. Faixa vencida entre o prazo e a
  limpeza (≤ 60 s) ainda aparece no card até o timer rodar.
- **Sem bump:** 1.46.0+2083; commit `02a1a31` em `origin/master`; Telegram `4063` (regra 15).

---

## 18/11/2026 — P0 nº 4 fechado: `.gguf` 3B + runtime do llama.cpp no espelho

**Autor:** Freebuff (Buffy) — sessão de 18/11 ~18:50, pedido do dono ("Fechar o
P0 nº 4 copiando o .gguf do 3B e o binário do llama.cpp para o espelho com
MANIFEST").

### Criados (fora do repositório, HD USB)

- `/home/alex/dados/od-mirror/models/qwen2.5-coder-3b-instruct-q4_k_m.gguf`
  (2,0 GB; sha256 idêntico ao original).
- `/home/alex/dados/od-mirror/runtimes/llama/` — build 10786, 41 MB, **com as
  `.so`** (o binário sozinho não roda).

### Modificados (fora do repositório)

- `od-mirror/MANIFEST.txt` — 133 entradas (82 antigas + 51 novas).
- `od-mirror/README.md` — tabela + seção "Restaurar o LLM local".

### Modificados (no repositório)

- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (P0 nº 4 e checkbox),
  `iniciar/session.json`, transcrição §11.

### Intenção + estado

- **Intenção:** o "offline" do OD não podia depender de `/home/alex/llama.cpp`
  e `/opt/…/runtimes/llama` sobreviverem.
- **Pronto/validado:** `sha256sum -c` **51/51 OK**; **prova real** — o runtime
  copiado subiu de `/tmp` sem `LD_LIBRARY_PATH`, carregou o `.gguf` do espelho
  e respondeu `/v1/models` (`model loaded` + `listening`), depois encerrado.
- **Descoberta registrada:** o unit `od-llm.service` do repo cita gemma e está
  inactive; o 3B realmente servido foi confirmado no `/v1/models` vivo.
- **Limites:** só o 3B coder; symlinks `.so` fora do MANIFEST; `x86_64`.
- **Sem bump:** 1.46.0+2083; sem restart; nenhum código do serviço alterado.

---

## 18/11/2026 — P0 nº 3 fechado: guarda ZIM ↔ compose do acervo offline

**Autor:** Freebuff (Buffy) — sessão de 18/11 ~18:20, pedido do dono ("Fechar o
P0 nº 3 com um teste ZIM ↔ compose no acervo offline").

### Criados

- `tools/checar_zim_compose.py` — guarda nas duas direções, `--json`, exit 1
  com a correção.
- `tests/test_zim_compose.py` (11 testes).

### Modificados

- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (P0 nº 3 fechado),
  `iniciar/session.json`, transcrição §10.

### Intenção + estado

- **Intenção:** fechar o buraco de um ZIM novo ficar invisível para a busca
  por não estar no `command` do kiwix (e da referência morta no compose).
- **Pronto/validado:** **11 passed** no teste; acervo real **alinhado**
  (12 quentes + 2 frios); `test_zim_compose + test_kiwix + test_enciclopedia`
  **106 passed**; **GATE COMPLETO 5459 passed / 19 skipped / 0 falha**.
- **Limites declarados:** a guarda olha o topo dos diretórios montados (não
  subpastas) e não valida a integridade do ZIM — só presença/paridade.
- **Sem bump:** 1.46.0+2083; sem restart.

---

## 18/11/2026 — Medição: quanto do brief a CLI realmente usa

**Autor:** Freebuff (Buffy) — sessão de 18/11 ~17:50, pedido do dono ("Medir
quanto do brief a CLI realmente usa, comparando o prompt com o diff produzido").

### Criados

- Nenhum arquivo versionado (arquivo de prova `tools/PROVA_BRIEF.md` criado
  pela CLI e **removido** depois da medição).

### Modificados

- `docs/IAS_DISPONIVEIS.md` — linha nova no histórico de medições.
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (checkbox fechado),
  `iniciar/session.json`, transcrição §9.

### Intenção + estado

- **Intenção:** provar que o brief injetado no prompt das 13 CLIs é **lido e
  usado**, não só carregado.
- **Medido:** prompt **5083 chars**, brief **2624 (51,6%)**. Só-leitura: **4/4
  campos corretos em 7,8 s**, zero arquivo tocado. Com diff real: **3/3
  corretos em 35,2 s**, **1 arquivo novo**, **0 existente alterado** (git
  status só com o arquivo novo).
- **Limite declarado:** amostra de 1 CLI (OpenClaude) e 2 tarefas curtas; CLIs
  sem saldo (Interpreter/Codex/Aider) e a cascata completa não foram medidas
  nesta rodada.
- **Sem bump:** 1.46.0+2083; nenhum código alterado.

---

## 18/11/2026 — Trava no git, painel “IAs no projeto” e prova real da cascata

**Autor:** Freebuff (Buffy) — sessão de 18/11 ~17:00, três sugestões clicadas
pelo dono (hook de pré-commit, painel do estado das IAs, cascata com CLIs
reais) e a pergunta de como operar o orquestrador.

### Criados

- `tools/trava_reescrita.py` — fonte única da régua de reescrita maciça
  (`--staged` / `--worktree`, escapes configuráveis).
- `tools/instalar_hooks.sh` (+x) — instala o hook `pre-commit`.
- `tests/test_trava_reescrita.py` (13 testes).

### Modificados

- `orquestrador.py` — `_reescritas_em_massa` delega em
  `tools.trava_reescrita.verificar` (uma régua, dois pontos de guarda).
- `integrations/api/server.py` — `GET /admin/estado-ia` (ROUTES 138 → 139) e
  seção “IAs no projeto” no `/admin` (checkpoint, árvore suja, idade do
  registro, P0/P1).
- `tools/brief_multi_ia.py` — `estado_para_painel()`.
- `tests/test_api.py` — contagem de rotas e as duas listas esperadas.
- `docs/PROTOCOLO_MULTI_IA.md` (§6.1 — como o dono opera), `docs/CHANGELOG.md`,
  `docs/ANALISE_SISTEMA_TODO.md` (3 checkboxes fechados),
  `iniciar/session.json`.

### Intenção + estado

- **Intenção:** fechar o buraco da trava fora do orquestrador (hook instalado
  neste repositório), tornar visível o que a próxima IA encontra e provar a
  continuidade com binários de verdade.
- **Pronto/validado:** trava **13 passed** (inclui commit real bloqueado e
  commit normal passando); `test_api.py` **202 passed**; bloco multi-IA **140
  passed**; **prova real** Interpreter falhou em **11,4 s** e OpenClaude
  respondeu `OK` em **9,4 s**, sessão `concluido/implantado` em **20,9 s** sem
  alterar a árvore.
- **Pela metade (declarado):** medir quanto do brief a CLI realmente usa; a
  rota nova do painel só vale após restart do `od-core` (regra 7.3).
- **Sem bump:** 1.46.0+2083.

---

## 18/11/2026 — Convivência multi-IA (brief + trava + cascata até concluir) e corpus de frases reais

**Autor:** Freebuff (Buffy) — sessão de 18/11 ~16:10, ordens do dono: "faça"
(executar a próxima melhoria) e *"garanta que todas [as IAs] prossigam dentro
da mesma linha sem destruir o que existe (...) a próxima deve prosseguir e
assim sucessivamente até concluir"*.

### Criados

- `tools/brief_multi_ia.py` — brief único do estado real (versão, HEAD ×
  origin, árvore suja, checkpoint, atribuições, P0/P1, regras de convivência;
  `--json`).
- `docs/PROTOCOLO_MULTI_IA.md` — contrato entre as IAs.
- `tests/test_corpus_frases_dono.py` (32 testes) e `tests/test_multi_ia.py`
  (11 testes).
- `iniciar/2026-11-18_conversa_omegadrakon.md` §7 (transcrição).

### Modificados

- `orquestrador.py` — brief no prompt de toda CLI; `_reescritas_em_massa()`
  (trava: >70% das linhas de arquivo rastreado → falha sem commitar);
  cascata até concluir no gate vermelho; `_encerrar()` grava `detalhe`.
- `iniciar/RULES.md` — regra 24 (protocolo multi-IA).
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (P0 nº2 fechado),
  `iniciar/session.json`.

### Intenção + estado

- **Intenção:** o dia provou o risco — outra ferramenta regrediu o
  `orquestrador.py` (1654 → 251 linhas) sem registro e a suíte passou a
  quebrar na coleta. A resposta é estado explícito + regras iguais + travas
  automáticas, não confiança na memória de cada IA.
- **Lote órfão revertido** com a ordem do "faça": `orquestrador.py` de volta
  a 1654 linhas, `soma.py` removido, `test_orquestrador.py` **116 passed**.
- **Pronto/validado:** corpus **32 passed**; multi-IA + orquestrador **127
  passed**; **GATE COMPLETO 5435 passed / 19 skipped / 0 falha** (220,46 s).
- **Limite declarado:** as travas valem para sessões do `orquestrador
  --sessao`; IA que trabalha fora dele (esta, por exemplo) segue por
  regra/registro — o brief e o checklist do protocolo são o único cinto.
- **Sem bump:** 1.46.0+2083. Sem restart (o `od-core` não usa o orquestrador
  de CLIs).

---

## 18/11/2026 — Retomada "leia iniciar": restart de 15:01 já no ar, download do Raul no lote 4 e lote órfão do `orquestrador.py`

**Autor:** Freebuff (Buffy) — sessão de 18/11 ~15:50, a pedido do dono
("leia iniciar"). **Origem do lote órfão:** **NÃO IDENTIFICADA** (arquivo
reescrito às 15:19:11, sem registro em `iniciar/` nem no CHANGELOG).

### Criados

- Nenhum arquivo novo (só registro).

### Modificados

- `iniciar/session.json` — checkpoint
  `retomada_leitura_iniciar_2026_11_18_turno2`.
- `iniciar/2026-11-18_conversa_omegadrakon.md` — §6 (estado medido).
- `docs/ANALISE_SISTEMA_TODO.md` — checkboxes do §4 (sugestões não
  escolhidas deste turno).
- `iniciar/ATRIBUICOES.md` — esta entrada.

### Intenção + estado

- **Intenção:** cumprir as regras 3/4/23 (ler antes de assumir contexto,
  salvar a cada troca, atribuir) e responder ao `txt.txt` com medição.
- **Achado 1 — restart não registrado:** o serviço foi reiniciado às
  **15:01:19** (MainPID 220986, NRestarts=0) DEPOIS dos commits de 14:56:55;
  logo a **cascata 13**, o **fix do cgroup** e o **Query Router 101×485**
  já estão no ar — o "restart pendente" do checkpoint anterior está
  vencido. `/health` ok=true 30/30.
- **Achado 2 — lote órfão destruidor:** `orquestrador.py` na árvore foi
  regredido para a versão de **fila de 08/10** (251 linhas), com
  `load_dotenv()` no nível de módulo; `pytest tests/test_orquestrador.py`
  quebra na **coleta** (`ImportError: cannot import name 'CLIS'`). `soma.py`
  (32 B) apareceu na raiz. **Não revertido** (regra 7 exige ordem).
  Próximo passo exato: `git checkout -- orquestrador.py && rm soma.py`
  **com ordem do dono**.
- **Achado 3 — download do Raul:** unidade ativa desde 13:50, lote 3
  fechado (+10; acervo **382**, +28 desde 354), lote 4 de ~19 rodando.
- **Sem bump:** 1.46.0+2083. Nenhum código alterado nesta troca.

---

## 18/11/2026 — Cascata 10 → 13 CLIs: cota nunca é motivo de exclusão

**Autor:** OpenCode (agente, modelo MiMo-V2.6-Flash) — continuação do
serviço (18/11 ~17:00), ordem do dono ("cota nunca é motivo de exclusão… a
cota sempre acaba por isso esse número grande de IAs").

### Criados

- `tools/openclaude_headless.sh` (+x) — wrapper headless do OpenClaude:
  aplica o perfil portátil (`ai_settings.env`, `CLAUDE_CONFIG_DIR` etc.,
  mesmos exports do `start.sh`) e executa a engine `@gitlawb/openclaude`.

### Modificados

- `orquestrador.py` — campo novo `CliSpec.prompt_via_stdin` +
  `executar_cli()` enviando o prompt por `communicate(input=…)`; `CLIS`
  **10 → 13** (Cline posicional one-shot, OpenClaude `-p --yolo`,
  Interpreter `--stdin`); bloco de política reescrito com a régua do
  dono; `CLI_SESSAO_OPCOES` 10 → 13.
- `integrations/api/server.py` — `SESSAO_CLIS` 10 → 13 (contrato do
  painel).
- `tests/test_orquestrador.py` — contrato da cascata atualizado (13
  CLIs; freebuff única de fora e **só por modo**; testes novos de
  `prompt_via_stdin` e do wrapper).
- `docs/IAS_DISPONIVEIS.md` — conclusão 13/14; cota removida dos
  motivos de exclusão; histórico com a 2ª leva.

### Intenção + estado

Reavaliar as 4 exclusões sob a nova régua: cline, openclaude e
interpreter **tinham** one-shot (provado com prompt real — os dois
primeiros falham só por cota/saldo, que volta; openclaude respondeu e
criou arquivo, exit=0); freebuff continua fora por modo medido. Validado:
318 + 336 testes do bloco e **gate completo 5392 passed / 19 skipped /
0 failed**; `executar_cli(OpenClaude)` → `SAIDA: ok`. **Sem bump**
(1.46.0+2083); entra no ar no próximo restart do `od-core` (autorização
do dono pendente — regra 7.1).

---

## 18/11/2026 — Playlist do Raul Seixas: download em unidade própria + fix do cgroup

**Autor:** OpenCode (agente, modelo MiMo-V2.6-Flash) — ordem do dono
("Sim, baixar agora" + "Conserta agora também", 18/11).

### Criados

- `tools/baixar_resto_lista.py` — retoma QUALQUER playlist
  (`OD_LISTA_URL`, `OD_LISTA_NOME`, `OD_LISTA_LOG`; slug default).

### Modificados

- `integrations/radio_link.py` — `_unit_transitoria()` (novo):
  `iniciar_processamento()` passa a rodar o worker em unidade transitória
  `systemd-run --user --unit=od-radio-link-<id>` (irmão do od-core em
  `app.slice`), com fallback para o `Popen` + `start_new_session` antigo
  (`unit=""` desliga); e `_parece_repetida()` endurecido (casa o título
  sozinho — a Metamorfose Ambulante tinha entrado duplicada no acervo).
- `tests/test_radio_link.py` — 3 testes da unidade systemd.
- `tests/test_radio_cobertura.py` — teste novo da pré-checagem no
  sentido contrário (lista bare × acervo com artista).
- `tests/test_tools_diversos_cobertura.py` — expectativas + teste
  `test_nome_da_lista_e_configuravel` (37 passed).

### Intenção + estado

O worker morria com qualquer restart do od-core (mesmo cgroup). Agora o
download roda em unidade própria — `od-radio-lista-raul.service` **ativa**
desde 13:53, lote 1 fechou +10 (354 → 364), lote 2 rodando; 190 faixas ≈
19 lotes ≈ 10–13 h. A duplicata da Metamorfose foi removida (linha 789 →
`revisar/duplicadas/`, acervo 363). **Sem bump** (1.46.0+2083); o fix do
radio_link entra no ar no próximo restart do `od-core` (autorização
pendente) — a unidade do download já protegida desde agora.

---

## 18/11/2026 — Query Router: 101 × 485 features — vetor harmonizado

**Autor:** OpenCode (agente, modelo MiMo-V2.6-Flash) — continuação do
serviço (18/11 ~14:30), escolha do dono ("Voltar ao Query Router").

### Modificados

- `core/query_router.py` — `_harmonizar_dimensao()` (novo) + chamada em
  `classify()`: cauda do embedding completada com a média de treino do
  `StandardScaler` quando o ambiente não tem `sentence-transformers`
  (suíte: 101 → 485); fallback com um único aviso se o vetor for maior.
- `tests/test_query_router.py` — regressão (`use_embeddings=False`).
- `docs/CHANGELOG.md`, `iniciar/session.json`
  (`query_router_101x485_2026_11_18`), transcrição §3, esta entrada.

### Intenção e estado

- **Diagnóstico:** o aviso era só da **suíte** (journal da produção: 0
  ocorrências) — o `.venv` do serviço tem o pacote; o `python3` do
  sistema não. Sem ele, `embed()` falhava e o `predict` quebrava em toda
  chamada (router nunca classificava na suíte).
- **Pronto/validado:** `test_query_router.py` **20 passed**; prova real
  com o modelo de produção → `101 → 485` (1×) e classificações
  `direct`/`tool`/`hybrid`; **gate completo 5385 passed / 19 skipped / 0
  falha**.
- **Sem bump:** 1.46.0+2083. **Restart pendente de autorização** (regra
  7.1) — o fix entra no ar no próximo restart; a produção já se
  comporta igual com o código antigo.

---

## 18/11/2026 — Cascata do orquestrador: 2 → 10 IAs (ordem do dono)

**Autor:** OpenCode (agente, modelo MiMo-V2.6-Flash) — sessão de 18/11
~13:50, pedido do dono no chat ("usar todas as 14 IAs, não só as três
atuais"; confirmou "Sim: expandir a cascata").

### Criados

- `iniciar/2026-11-18_conversa_omegadrakon.md` **§2** (transcrição desta
  entrega).

### Modificados

- `orquestrador.py` — `CLIS` **2 → 10** (Gemini, Qwen, Claude, Crush, Agy,
  OpenClaw, Codex, Aider — cada flag de modo não-interativo medida no
  `--help` de 18/11; medição e as 4 exclusões em comentário no código);
  `OPENCODE_MODELO` trocado (o `nemotron-3-ultra-free` sumiu do catálogo —
  a primeira da cascata morria com model-not-found — → provado
  `opencode/deepseek-v4.1-flash-free`, exit=0); `CLI_SESSAO_OPCOES`
  2 → 10; help do `--cli`.
- `integrations/api/server.py` — `SESSAO_CLIS` 2 → 10 (seletor do painel).
- `tests/test_orquestrador.py` — contrato da cascata atualizado + 2
  testes novos (flags headless de cada CLI nova; exclusão das 4 só-TUI
  freebuff/cline/openclaude/interpreter; seletor do runner × servidor).
- `docs/CHANGELOG.md` — entrada "Cascata do orquestrador: 2 → 10 IAs".
- `docs/IAS_DISPONIVEIS.md` — conclusão das 14 atualizada (10 na cascata,
  4 fora com motivo) + linha no histórico de medições.
- `iniciar/session.json` (checkpoint `cascata_14_ias_2026_11_18`), esta
  entrada.

### Intenção e estado

- **Intenção:** cumprir a ordem do dono de usar as 14 IAs no orquestrador;
  a hipótese dele foi testada primeiro (o refactor da madrugada **não**
  fez isso — media 2 CLIs; os "3 atuais" são providers de LLM do chat,
  camada diferente das CLIs de código).
- **Medição antes de mexer:** `--help` das 14 (sem cota); 10 com one-shot
  entraram, 4 ficaram de fora com motivo documentado; `opencode models`
  para o catálogo de modelos.
- **Pronto/validado:** `test_orquestrador.py` **114 passed**;
  `test_api.py -k sessao` **21 passed**; **gate completo 5384 passed / 19
  skipped / 0 falha**; comando seco das 10 conferido.
- **Sem bump:** 1.46.0+2083. **Restart feito com autorização do dono às
  12:53** (MainPID 83842, NRestarts=0, `journal -p err` = 0, `/health`
  30/30) — `SESSAO_CLIS` novo valendo no painel.

---

## 18/11/2026 — Retomada "leia iniciar": gate vermelho do lote da madrugada diagnosticado e consertado

**Autor:** OpenCode (agente, modelo MiMo-V2.6-Flash) — sessão de 18/11 ~09:33,
a pedido do dono ("leia iniciar").
**Origem do lote trabalhado:** **Cline** (commits de autor "Nicky Virthy",
18/11 09:08–09:15, mensagem `implementa: ideia default`; sessão Cline
visível em `refs/cline/checkpoints/`, última checkpoint 09:29).

### Criados

- `iniciar/2026-11-18_conversa_omegadrakon.md` (§1 — esta retomada).

### Modificados

- `orquestrador.py` — **revertido para `96040ba`** (versão de 17/11). O
  refactor do Cline (2297 linhas) tinha: `load_dotenv()` no nível de módulo
  (linha 53, vazava **56 chaves** do `.env` no `os.environ` na **coleta**
  da suíte via `tests/test_orquestrador.py`) + 10 funções do modo sessão
  removidas (`ler_caixa`, `gravar_caixa`, `_batimento`, `_matar_grupo`…)
  + funções de fila adicionadas que o próprio docstring declara removidas.
  No commit anterior ao revert (antes da reversão) foi feito também o fix
  cirúrgico de `load_dotenv` em `main()` — subsumido pelo revert.
- `iniciar/session.json` (checkpoint de 18/11),
  `iniciar/ATRIBUICOES.md` (esta entrada), transcrição do dia.

### Intenção e estado

- **Intenção:** cumprir as regras 3/4/23 (ler, registrar, atribuir) e fechar
  o ciclo do gate vermelho encontrado (regra 13: causa raiz, correção e
  reexecução até não haver erros).
- **Diagnóstico:** gate completo **80 failed / 5302 passed / 19 skipped**,
  idêntico em 2 rodadas (`diff` = 0). Bissect progressivo (subconjuntos →
  `--ignore-glob` → um arquivo por vez) isolou o gatilho como a **coleta**
  de `tests/test_orquestrador.py`; prova direta do vazamento (56 chaves) e
  confirmação de que cada arquivo falhava só no conjunto.
- **Pronto/validado:** `import orquestrador` → 0 chaves vazadas; os 536
  testes das 8 classes afetadas rodados juntos → **536 passed**; **gate
  completo pós-revert: 5382 passed / 19 skipped / 0 falha** (212,33 s) —
  contra 80 failed / 5302 passed na abertura do turno.
- **Pela metade (declarado, da outra ferramenta):** o refactor do
  `orquestrador.py` ficou incompleto e sem registro (sem CHANGELOG, sem
  `iniciar/`); revertido. As entregas do Cline que **ficam**: `tools/od.sh`
  (menu de 14 CLIs), `docs/OD_MENU_CLIS.md`, entrada no CHANGELOG, remoção
  da regra `_CACHE_BAN_VERIFICACAO_FALSA` em `core/orchestrator.py`
  (edição de 17/11 21:24 commitada pelo lote) e os docs de 18/11.
- **Resíduos LIMPOS com ordem do dono** (~10:50, "encerrou por falta de
  crédito"): 171 `gerado_*.py` + `teste_orquestrador.py` (raiz) removidos;
  árvore com **0 não-rastreados**; gate pós-limpeza **5382 passed / 19
  skipped / 0 falha**; checkbox do TODO §4 marcado `[x]`.
- **Sem bump:** 1.46.0+2083. **Commits:** `2775d3b` (fix) + `4648271`
  (docs) em `origin/master`. **Restart verde (regra 7.3):** 10:37:13,
  MainPID 4133749, NRestarts=0, `journal -p err` = 0, `/health` ok=true
  30/30 up (mqtt transitório reconectou em 8 s). **Telegram:** ok=true
  msg_id=4053.

---

**Autor:** Freebuff (Buffy) — sessão de 17/11, a pedido do dono ("Revisar as
checkboxes abertas do TODO e priorizar as próximas entregas").

### Criados

- Nenhum arquivo novo.

### Modificados

- `docs/ANALISE_SISTEMA_TODO.md` — 5 checkboxes fechadas com evidência,
  duplicata de "Task Queue (Redis/RQ)" removida, item reescopado, texto órfão
  do `web_search` corrigido e a seção nova `📍 Revisão de 17/11/2026` (P0–P3).
- `iniciar/2026-11-17_conversa_omegadrakon.md` (§18), `iniciar/session.json`.

### Intenção e estado

- **Intenção:** o TODO já tinha 38 abertas, das quais várias já estavam
  entregues — revisar sem conferir código é o que gera "parece que nada anda".
- **Pronto/validado:** **32 abertas / 78 fechadas**; `tests/test_rag.py` 93
  passed (calibração lê `docs/`).
- **Prioridades:** P0 (llm_cache, corpus de frases reais, ZIM↔compose, gguf no
  espelho), P1 (I2 com medição, modo colapso, backup com restauração,
  comparador de modelos), P2 (compras/decisões do dono), P3 (infra/demanda).
- **Sem bump:** 1.46.0+2083; nenhum código alterado.

---

## 17/11/2026 — Curadoria do acervo no app Android (1.46.0+2083)

**Autor:** Freebuff (Buffy) — sessão de 17/11, a pedido do dono ("Fechar a
pendência da curadoria do acervo no app Android").

### Criados

- `app/lib/screens/curadoria_screen.dart` — tela de curadoria do acervo.
- `app/test/curadoria_api_test.dart` (10 testes) e
  `app/test/curadoria_screen_test.dart` (10 testes).

### Modificados

- `app/lib/services/od_api.dart` — `OdMusicaAcervo`, `OdParMusica`,
  `OdCuradoria` e 6 métodos REST da curadoria.
- `app/lib/screens/dashboard_screen.dart` — card "Curadoria do acervo" (admin)
  + `_abrirCuradoria()` por `Navigator.push`.
- Bump 1.46.0+2083: `.env` (gitignored), `core/capabilities.py`,
  `app/pubspec.yaml`, `integrations/api/server.py` (`_APP_VERSION_CODE`),
  `site/index.html`, `site/historico.html` (78 lançamentos / Era 9 = 12).
- `tests/conftest.py` — `OD_QUOTA_FILE` da suíte para temporário (isolamento
  da cota real que derrubou 2 testes do gate).
- `docs/CHANGELOG.md` ([1.46.0]), `docs/README_VERSAO.md` ([1.46.0]),
  `docs/ANALISE_SISTEMA_TODO.md` (checkbox fechado),
  `iniciar/2026-11-17_conversa_omegadrakon.md` (§17), `iniciar/session.json`.

### Intenção e estado

- **Intenção:** o dono não precisa mais abrir o navegador no celular para
  excluir/bloquear música e liberar faixas de cantores bloqueados.
- **Pronto/validado:** `flutter analyze` 0 issues, `flutter test` **257
  passed / 2 skipped**, gate Python **5374 passed / 19 skipped / 0 falha**;
  APK **1.46.0+2083** conferido por `aapt2` e publicado em `site/`.
- **Pela metade (deliberado):** sem prova visual no aparelho (máquina sem
  navegador/emulador); a tela é provada pelos 20 testes de widget/API.
- **Bump MINOR:** 1.45.1+2082 → **1.46.0+2083**.

---

## 17/11/2026 — Letra internacional com tradução em lista paralela no `/radio-pro`

**Autor:** Freebuff (Buffy) — sessão de 17/11, a pedido do dono ("Mostrar a
letra internacional com a tradução em lista paralela no /radio-pro").

### Criados

- `integrations/radio_traducao.py` — `montar_traducao()` pela cadeia de LLM do
  OD, cache com hash da letra, marca `JA_PT`.
- `tests/test_radio_traducao.py` — 25 testes.

### Modificados

- `integrations/api/server.py` — rota `GET /api/radio/pro/traducao` (ROUTES,
  `_ROUTE_SPECS`, `AUTH_EXEMPT_PATHS`) e o handler com o gate de sessão.
- `site/radio-pro.html` — card "Letra" em duas colunas + `pedeTraducao()` /
  `desenhaTraducao()`; descarta resposta de faixa que já trocou.
- `tests/test_radio_pro.py` — rota nova nos conjuntos + teste das colunas.
- `tests/test_api.py` — rotas 137 → **138**.
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (checkbox fechado),
  `iniciar/2026-11-17_conversa_omegadrakon.md` (§15), `iniciar/session.json`.

### Intenção e estado

- **Intenção:** o dono queria ler a letra internacional com a tradução ao lado;
  sem serviço pago e sem dependência nova — quem traduz é a cadeia do próprio
  OD.
- **Pronto/validado:** gate completo **5374 passed / 19 skipped / 0 falha**
  (218,8 s, exit 0); coleção 5391 contra 5365 do HEAD em worktree (delta exato
  de +26 testes); `node --check` OK; prova viva do Groq traduzindo "The Sound
  of Silence".
- **Limite declarado:** tradução é uma chamada de LLM por faixa (depois só
  cache); sem internet e sem llama-server no ar, a coluna simplesmente não
  aparece.
- **Sem bump:** 1.45.1+2082.

---

## 17/11/2026 — Curiosidade da música de volta no `/radio-pro`

**Autor:** Freebuff (Buffy) — sessão de 17/11, a pedido do dono ("Fazer o
/radio-pro mostrar a curiosidade da música atual").

### Criados

- Nenhum arquivo novo.

### Modificados

- `site/radio-pro.html` — `<div id="agoraCurio">` no card "Tocando agora" e
  `desenhaAgora()` pintando `t.curiosidade` (vazio quando não há).
- `tests/test_radio_pro.py` — `test_pagina_mostra_a_curiosidade_da_musica`.
- `docs/CHANGELOG.md` (entrada datada, sem bump),
  `docs/ANALISE_SISTEMA_TODO.md` (checkbox fechado),
  `iniciar/2026-11-17_conversa_omegadrakon.md` (§14), `iniciar/session.json`.

### Intenção e estado

- **Intenção:** o dado já existia na API (`tocando.curiosidade` de
  `radio_agora.curiosidade_da_musica()`, leitura do `acervo.db`); a página nova
  simplesmente nunca teve onde exibi-lo — 0 ocorrências de "curiosidade" no
  HTML, medido antes da correção.
- **Pronto/validado:** `test_radio_pro.py` 58 passed e rádio completo 216
  passed / 0 falha; sem restart (o HTML é servido do disco a cada requisição).
- **Sem bump:** 1.45.1+2082 (página web; APK e contrato do app intactos).

---

## 17/11/2026 — Retomada "leia iniciar": checkpoint relido e 2 pedidos novos do `txt.txt` registrados

**Autor:** Freebuff (Buffy) — sessão de 17/11, a pedido do dono ("leia
iniciar").

### Criados

- Nenhum arquivo novo.

### Modificados

- `iniciar/session.json` — checkpoint
  `retomada_leitura_iniciar_2026_11_17_turno3`.
- `iniciar/2026-11-17_conversa_omegadrakon.md` — §13 (estado encontrado,
  novidades do `txt.txt`, o que não foi feito).
- `docs/ANALISE_SISTEMA_TODO.md` — 2 checkboxes novos no §4 (curiosidade da
  música no `/radio-pro`; letra com tradução paralela).
- `iniciar/ATRIBUICOES.md` — esta entrada.

### Intenção e estado

- **Intenção:** cumprir a regra 3 (ler o checkpoint antes de retomar) e não
  deixar pedido do dono morar só no `txt.txt` (regra 20).
- **Estado encontrado:** árvore limpa, `HEAD == origin/master == e51b5f2`,
  `od-core` active (MainPID 2433306, NRestarts=0), gate mais recente 5388
  passed, versão 1.45.1+2082.
- **Achado medido:** `site/radio-pro.html` tem **0 ocorrências** de
  "curiosidade", embora `GET /api/radio/agora` já devolva
  `tocando.curiosidade` (de `radio_agora.py::curiosidade_da_musica()`) — falta
  a página exibir, o dado existe.
- **Pela metade (deliberado):** nenhum código alterado, sem gate e sem
  restart; os dois pedidos aguardam ordem do dono. Sem bump (1.45.1+2082).

---

## 17/11/2026 — Bloqueio de música vale no pedido por link do YouTube

**Autor:** Freebuff (Buffy) — sessão de 17/11, a pedido do dono
("Faça o radio_link.py recusar o download de música que está na lista de
bloqueadas").

### Criados

- Nenhum arquivo novo.

### Modificados

- `integrations/radio_link.py` — `_artista_e_titulo_do_link()`,
  `_bloqueada_no_link()`, filtro antes do download em `processar_pedido()`
  (novo parâmetro `musicas_bloqueadas`), filtro das bloqueadas em
  `_baixar_resto()` e conferência pós-download (nome escondido no link →
  `excluir_musica_do_acervo()` + pedido recusado).
- `site/radio-pro.html` — motivo `musica_bloqueada` traduzido.
- `tests/test_radio_link.py` — `TestMusicaBloqueadaNoLink` (7 testes).
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (checkbox fechado),
  `iniciar/2026-11-17_conversa_omegadrakon.md` (§6), `iniciar/session.json`.

### Intenção e estado

- **Intenção:** fazer o bloqueio individual do dono valer para o caminho que
  ele mais usa (pedido por link/playlist), e não só para o painel.
- **Pronto/validado:** gate completo **5355 passed / 16 skipped / 0 falha**
  (202,45 s, exit 0); sandbox provou bloqueada sem download, playlist mista
  baixando só a permitida, título com sufixo casando e lista ausente sem
  barrar nada.
- **Limite declarado:** a checagem pré-download é heurística (depende do que o
  link entrega); a rede de segurança é a conferência no acervo depois do
  download, que apaga a faixa e recusa o pedido.
- **Sem bump:** 1.45.0+2081.

---

## 17/11/2026 — Pedidos 2 e 3 na interface: rotas, painel /admin e página /radio-pro

**Autor:** Freebuff (Buffy) — sessão de 17/11, a pedido do dono
("Implemente as rotas de API, o painel e a página /radio-pro para excluir
música e gerenciar exceções de cantores").

### Criados

- `tests/test_radio_curadoria.py` — 28 testes (listas de pares, exceção
  vencendo o bloqueio, `excluir_musica_do_acervo`, as 6 rotas e as páginas).

### Modificados

- `integrations/api/server.py` — 6 rotas de curadoria (`GET
  /api/radio/musicas`, `POST /api/radio/musicas/excluir`,
  `POST|DELETE /api/radio/musicas/bloqueadas`, `POST|DELETE
  /api/radio/musicas/excecoes`), `_exige_admin_do_acervo`,
  `_par_artista_titulo`, `_listas_de_curadoria`, entradas em
  `AUTH_EXEMPT_PATHS` e no `_ROUTE_SPECS`, seção nova no `_ADMIN_PAGE_HTML`
  (HTML + JS) e `musCarregar` no `carregarTudo`.
- `site/radio-pro.html` — card "Curadoria do acervo" (só o dono vê) com
  buscar, excluir, bloquear/desbloquear e exceções.
- `tests/test_api.py` — contagem de rotas **130 → 136** e as 6 rotas nos
  conjuntos esperados (privado/público).
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`,
  `iniciar/2026-11-17_conversa_omegadrakon.md` (§5) e `iniciar/session.json`.

### Intenção e estado

- **Intenção:** fechar os pedidos 2 e 3 do `txt.txt` até o ponto onde o
  dono opera — até agora só existia a biblioteca.
- **Pronto/validado:** gate completo **5347 passed / 16 skipped / 0 falha**
  (205,23 s, exit 0); sandbox contra o acervo real **em leitura** (200
  faixas, `?q=raul` correto, CRUD em listas de `/tmp`, 404 de faixa
  inexistente); nenhuma música real apagada.
- **Pela metade (declarado):** `radio_link.py` ainda baixa faixa bloqueada
  pedida por link — o bloqueio só vale pelo painel/página. Checkbox criado
  no TODO §4 com o próximo passo exato.
- **Sem bump:** 1.45.0+2081.

---

## 17/11/2026 — Lote órfão validado e publicado: exclusão/bloqueio de músicas, exceções de cantores, reboot, staging e cobertura

**Autor do lote:** **ORIGEM NÃO IDENTIFICADA** (achado na árvore em 17/11,
sem commit, sem transcrição e sem entrada neste livro-caixa — regra 23).
**Validação, registro e publicação:** Freebuff (Buffy), a pedido do dono
("Rode o gate completo e commite o lote órfão").

### Criados

- Confirmados no commit (os 10 arquivos de cobertura já existiam na árvore):
  `tests/test_radio_cobertura.py`, `tests/test_actions_cobertura.py`,
  `tests/test_embed_hybrid_cobertura.py`,
  `tests/test_marketplace_cobertura.py`, `tests/test_os_updater.py`,
  `tests/test_rota_reboot_os_updater.py`,
  `tests/test_server_rotas_novas_cobertura.py`,
  `tests/test_supply_depot_cobertura.py`,
  `tests/test_tools_diversos_cobertura.py`, `tests/test_tools_telemetry.py`
  e `iniciar/2026-11-15_conversa_omegadrakon.md`.

### Modificados

- `integrations/radio_cantores.py` — listas `data/musicas_bloqueadas.txt` e
  `data/cantores_excecoes.txt`, `eh_excecao`/`adicionar_excecao`/
  `remover_excecao`/`linhas_excecoes`, `musica_bloqueada`/
  `adicionar_musica_bloqueada`/`remover_musica_bloqueada`/`linhas_bloqueadas`,
  `excluir_musica_do_acervo` e `indesejado(artista, titulo=)` consultando a
  exceção **antes** do bloqueio.
- `integrations/api/server.py` — `POST /admin/os-updater/reboot` usa
  `updater._reboot()`.
- `tools/supply_depot.py` — código gerado gravado no **staging** (conserta o
  `codigo_ausente_no_staging` do roundtrip).
- `app/lib/screens/tasks_screen.dart`, `app/test/tasks_api_test.dart`,
  `app/test/tasks_screen_test.dart` — payload `{}` válido + 5 testes.
- `tests/test_task_queue.py` — +8 testes de borda (`TestCoberturaDeBorda`).
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`, `iniciar/session.json`,
  `iniciar/2026-11-17_conversa_omegadrakon.md` (registro desta rodada).

### Intenção e estado

- **Intenção do lote:** fechar os pedidos 2 e 3 do `txt.txt` (excluir músicas
  que o dono não gosta; manter músicas escolhidas de cantores bloqueados), o
  reboot do OS updater pela API, o staging do `supply_depot`, o payload `{}`
  do app e a dívida de cobertura acumulada desde 02/11.
- **Validado:** gate Python completo **5319 passed / 16 skipped / 0 falha**
  (210,60 s, exit 0); `flutter analyze` sem issues; `flutter test`
  **228 passed / 2 skipped**.
- **Pela metade (declarado):** as **rotas de API, o painel `/admin` e o
  `/radio-pro`** da exclusão/exceções **não existem** — só a biblioteca. O
  dono não consegue operar pela interface ainda; próximo passo exato: criar
  `POST /admin/radio/musica/excluir`, rotas de exceções e os botões nas duas
  páginas.
- **Sem bump:** 1.45.0+2081.

---

## 17/11/2026 — Retomada "leia iniciar": lote órfão verde encontrado na árvore

**Autor:** Freebuff (Buffy) — sessão de 17/11, a pedido do dono ("leia
iniciar").

### Criados

- Nenhum arquivo novo nesta troca.

### Modificados

- `iniciar/2026-11-17_conversa_omegadrakon.md` — §3 (estado encontrado).
- `iniciar/session.json` — chave `retomada_leitura_iniciar_2026_11_17_turno2`.
- `iniciar/ATRIBUICOES.md` — esta entrada.

### Intenção e estado

- **Intenção:** atender à regra 3 (ler o checkpoint antes de retomar) e
  reportar com precisão onde a sessão está.
- **Achado:** a árvore está suja com um lote **posterior ao commit
  `fccb6bc`**, sem registro em `iniciar/`: `integrations/radio_cantores.py`
  (+256: exceções `data/cantores_excecoes.txt` e bloqueio individual
  `data/musicas_bloqueadas.txt`), `integrations/api/server.py` (reboot via
  `updater._reboot()`), `tools/supply_depot.py` (staging do código),
  `app/lib/screens/tasks_screen.dart` (payload `{}` válido) + 2 testes do
  app, `tests/test_task_queue.py` (+263), `docs/ANALISE_SISTEMA_TODO.md` e a
  transcrição de 15/11, mais 10 arquivos de teste de cobertura.
- **Autor do lote: ORIGEM NÃO IDENTIFICADA** (nada no livro-caixa nem na
  transcrição) — registrado como desconhecido, conforme regra 23.
- **Validado agora:** os 12 arquivos de teste do lote → **682 passed em
  8,82 s**. Falta o gate completo e o commit.
- **Pela metade:** os pedidos 2 e 3 do `txt.txt` têm só a camada de
  biblioteca; **não existem ainda** rotas de API, painel nem app para
  excluir música e gerenciar exceções de cantores.
- **Serviço:** `od-core` active, MainPID 2183349, NRestarts=0 (PID mudou em
  relação ao 3322791 de 15/11 — restart não anotado).
- **Nesta troca:** nenhum código alterado, só registro. Aguardando ordem do
  dono para (a) gate completo + commit do lote e (b) fechar as rotas da
  rádio. Sem bump (1.45.0+2081).

---

## 14/11/2026 — Itens 2–4 do backlog: criar tarefa, SSE e filtro por data (registro completado em 15/11)

**Autor:** OpenClaude (outro agente, sessão da noite de 14/11) — os commits
`da19eb3` (criar tarefa pelo painel/app), `eef553e` (SSE na aba Tarefas) e
`ce643a2` (filtro/paginação por data de conclusão) **não entraram no
livro-caixa nem na transcrição**; registro completado aqui por OpenCode em
15/11, a pedido do dono ("voce parou ontem. verifique o que mudou e
continue").

### Criados

- Nenhum arquivo novo.

### Modificados

- `integrations/api/server.py` — formulário de criação no bloco Tarefas
  (select do catálogo `GET /actions` + campo de payload JSON +
  `tqCriar` → `POST /admin/tasks`); rota de ordenação por `finished_ts`.
- `app/lib/services/od_api.dart` — `createTask()` (POST, 201) + SSE de
  `/admin/tasks/events` + `sort_by_finished`.
- `app/lib/screens/tasks_screen.dart` — diálogo "Enfileirar tarefa" (＋),
  stream SSE ao vivo e filtro por data de conclusão.
- `core/task_queue.py` — ordenação/filtro por `finished_ts`.
- `docs/ANALISE_SISTEMA_TODO.md` — itens 2–4 marcados [x].

### Intenção e estado

Intenção: fechar os itens 2, 3 e 4 do backlog §4. Estado verificado em
15/11 por OpenCode: flutter analyze limpo, **223 testes verdes** antes das
correções, lote Python `test_task_queue + test_api` **229 passed**, árvore
pushada e serviço ativo (MainPID 3322791, NRestarts=0). **Duas lacunas
detectadas e cobertas em 15/11:** (a) nenhum teste para
`createTask`/formulário — +5 testes escritos; (b) o diálogo rejeitava
payload vazio `{}` (ação sem parâmetros como `system_info` não passava,
embora a API aceite `payload or {}`) — corrigido.

---

## 14/11/2026 — Inversão da cadeia de IA (Groq → Gemini) e inventário do TODO/Caderno

**Autor:** OpenCode (agente, modelo MiMo-V2.6-Flash) — sessão de 14/11
~17:20, a pedido do dono ("inverta o chamado, coloque o Groq antes do
Gemini").

### Criados

- Nenhum arquivo novo.

### Modificados

- `.env` — `OD_CHAT_PROVIDERS=groq,gemini,local` (novo; é a variável que
  `runtime/launcher.py::build_llm_providers()` realmente lê) +
  `OD_IA_ORDEM` invertido (variável **dormante** — só o `musica.py` de
  `.od_sandbox/` a lia — trocada por consistência).
- `iniciar/2026-11-14_conversa_omegadrakon.md` — §21 (pedido + cadeia +
  inventários + aba Tarefas).
- `iniciar/session.json` — chave `inversao_cadeia_ia_2026_11_14`.
- `docs/CHANGELOG.md` — seção "Cadeia de IA invertida … (sem bump)".

### Intenção e estado

Intenção: honrar a ordem pedida — o Groq na frente porque a cota gratuita do
Gemini zera e abre disjuntor de 6 h. Estado: **verde** — restart 17:25
(MainPID 2967186, NRestarts=0), `/health` ok com 29 checks, journal
`ordem=['groq', 'gemini', 'gemma-local']` e mensagem ao vivo com
`llm_used=groq`. Também entregues nesta sessão (leitura pura): inventário
das **47 checkboxes abertas** do `docs/ANALISE_SISTEMA_TODO.md`, mapa das
**11 notas / 7 listas TODO** do Caderno (só TODO 3 = 17 abertos, TODO 5 = 2
e TODO 6 = 12 têm itens em aberto) e a explicação da aba **Tarefas**
(histórico da Task Queue, não o TODO). Nenhuma nota do Caderno foi
alterada.

---

## 14/11/2026 — Conserto do "menos inteligente": recusa, Query Router e papéis do OD

**Autor:** OpenCode (agente, modelo MiMo-V2.6-Flash) — sessão de 14/11
~16:10, a pedido do dono ("resolva o problema, faça o que for necessário").

### Criados

- Nenhum arquivo novo.

### Modificados

- `core/query_router.py` — `tokenizar_pt()`/`STOPWORDS_PT` de módulo (o
  tokenizer era método vinculado e derrubava o pickle) + `_dump_atomic`
  (tmp + `os.replace`).
- `core/orchestrator.py` — `_refusal_reason` só no início +
  `limpa_etiquetas_resposta()` em 7 pontos (em recusa, crua para o cache
  banir).
- `agents/nicky_virthy/personality.py` — linha do protocolo proíbe a
  etiqueta na resposta ao usuário.
- `tools/actions/actions.py` — action `role_list` (125 → 126);
  `core/intents.py` — detecção (com menção ao OD) e formatter;
  `core/security/permissions.py` — `role_list` para `user`/`familia`.
- Testes: `test_query_router.py` (persistência real — o antigo era cego),
  `test_resposta_transparente.py` (contrato novo + `limpa_etiquetas`),
  `test_intents.py` (`TestPapeisOD`), `test_security.py`,
  `test_actions_catalog.py` (handler) e contagens 125 → 126 em
  `test_actions_catalog/test_capabilities/test_mcp_od/test_orchestrator/
  test_orchestrator_action_registry`.
- Registro: `iniciar/session.json`, transcrição (§20), `docs/CHANGELOG.md`,
  `docs/ANALISE_SISTEMA_TODO.md` (3 checkboxes entregues).

### Intenção e estado

- **Intenção:** fechar os 3 diagnósticos da §18/§19 que faziam o OD parecer
  "menos inteligente": resposta errada sobre os próprios papéis (1 de 6),
  11 refazs/dia pelo detector de etiqueta e Query Router sem persistência.
- **Estado:** **gate completo 4700 passed / 16 skipped / 0 falha** (195 s);
  3 commits publicados (`868a3ad`, `809b7fc`, `3c134fb`); `od-core`
  reiniciado 17:03 (MainPID 2945652) com prova viva — `/health` ok=true
  (29 checks), "quais os tipos de usuários de OD" → `fastpath:role_list` em
  **28,9 ms**, mensagem LLM sem etiqueta e **0 refazs**, `Query Router model
  loaded` sem bootstrap.
- **Achado do gate:** o título da §18 colidiu no RAG com a irrelevante
  de aritmética (a pergunta sintética; nenhum grid recalibrava) — reescrito só o
  título nosso (citação do dono intacta), piso intocado (precedente 20/10).
- **Sem bump:** 1.45.0+2081 — correção de servidor, contrato do app intacto.

---

## 14/11/2026 — Retomada: publicação do lote da §16 e higiene do TODO

**Autor:** OpenCode (agente, modelo MiMo-V2.6-Flash) — sessão de 14/11 ~15:33,
a pedido do dono ("leia iniciar").

### Criados

- Nenhum arquivo novo.

### Modificados

- `docs/ANALISE_SISTEMA_TODO.md` — 2 checkboxes **entregues mas abertos**
  marcados com evidência: fila ligada com 1 worker + custo medido (§13) e
  métricas de retenção no `/health` (§15).
- `iniciar/session.json`, `iniciar/2026-11-14_conversa_omegadrakon.md` (§17),
  `iniciar/ATRIBUICOES.md` — registro desta retomada.
- **Publicou o lote órfão da §16** (autor: Freebuff/Buffy, feito e registrado
  mas nunca commitado): `integrations/api/server.py`,
  `tests/test_task_queue.py`, `docs/CHANGELOG.md`.

### Intenção e estado

- **Intenção:** a sessão anterior terminou antes de publicar a entrega da §16
  (métricas da fila no painel `/admin`) — risco de perda (regra 23). Fechar o
  ciclo: **validar → commitar → publicar** (regras 7.1/7.2).
- **Estado:** **gate completo 4684 passed / 16 skipped / 0 falha** com o lote
  na árvore; 2 commits em `origin/master`; prova viva (`/admin` com
  `#tq-resumo`, `/admin/tasks` e SSE com `queue`).
- **Sem bump / sem restart:** 1.45.0+2081; o `od-core` (15:07:44) já roda
  exatamente o código publicado.

---

## 14/11/2026 — Métricas da fila no painel /admin

**Autor:** Freebuff (Buffy) — sessão de 14/11, a pedido do dono.

### Modificados

- `integrations/api/server.py` — `queue` (snapshot) no `GET /admin/tasks` e
  no `snapshot` do SSE; linha `#tq-resumo` + `tqResumoFila()` na seção
  "Tarefas (Task Queue)".
- `tests/test_task_queue.py` — `test_lista_traz_o_snapshot_da_fila` + painel.
- `docs/CHANGELOG.md`, `iniciar/session.json`,
  `iniciar/2026-11-14_conversa_omegadrakon.md` (§16).

### Intenção e estado

- **Intenção:** os números do `/health` (14/11) também no painel, onde o dono
  já opera a fila.
- **Estado:** resumo no topo da seção (fila, executando, workers, dead letter,
  concluídas/teto, podadas, totais). Fila/execução contadas das tasks da
  tabela (SSE); disco vem do snapshot. Painel testado (27 testes na suíte).
- **Sem bump:** 1.45.0+2081.

---

## 14/11/2026 — Métricas da fila no /health

**Autor:** Freebuff (Buffy) — sessão de 14/11, a pedido do dono.

### Modificados

- `core/task_queue.py` — `snapshot()`, contador `pruned`, `_contar()`.
- `runtime/launcher.py` — `register_task_queue_health()` + chamada no
  `_run_api_forever`.
- `integrations/api/server.py` — bloco `task_queue` no `GET /health`.
- `tests/test_task_queue.py` — 5 testes novos.
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`, `iniciar/session.json`,
  `iniciar/2026-11-14_conversa_omegadrakon.md` (§15).

### Intenção e estado

- **Intenção:** a fila ligada em produção desde hoje só se enxergava por
  `/admin/tasks`; expor profundidade, workers, dead letter e retenção no
  agregado de saúde.
- **Estado:** bloco `task_queue` no `/health` (fora do cache de 8 s) +
  check não-crítico no HealthMonitor (workers parados/dead letter → degraded).
  `dead_letter` é o que está em disco; o acumulado segue em `metrics`.
- **Sem bump** (só servidor, contrato do app intacto): 1.45.0+2081.

---

## 14/11/2026 — Custo da fila com action de LLM longa

**Autor:** Freebuff (Buffy) — sessão de 14/11, a pedido do dono.

### Criados

- Nenhum arquivo versionado (harness de medição em `/tmp`, descartado).

### Modificados

- `docs/CHANGELOG.md` (subseção de custo com LLM na entrada da fila),
  `docs/ANALISE_SISTEMA_TODO.md`, `iniciar/session.json`,
  `iniciar/2026-11-14_conversa_omegadrakon.md` (§14).

### Intenção e estado

- **Intenção:** completar o quadro de custo com o cenário mais pesado — uma
  action que chama o LLM local pela fila.
- **Método:** o catálogo (125 actions) não tem action de LLM; medido com fila
  em sandbox (1 worker) cuja action faz a mesma chamada HTTP do orchestrator
  (`OpenAICompatProvider._post_chat`) no llama-server local
  (qwen2.5-coder-3b-q4, 4 threads).
- **Resultado:** task de 600 tokens → **105,36 s**, **312% de 1 core no
  llama-server** (333,2 s de CPU), RSS ~1,9 GB; o processo **da fila** gastou
  **0,23% de 1 core** na mesma janela. Custo é do modelo, não da fila.
- **Custo de 1 worker:** task curta atrás de uma LLM de 14,89 s esperou
  **14,49 s**; action longa serializa a fila (avaliar 2 workers/prioridade).
- **Ruído declarado:** repouso do `od-core` de 3,2% → 8,5% no intervalo era o
  TTS da rádio (rajadas de 10–29%/s), não a fila; RSS estável ~262 MB.

---

## 14/11/2026 — Task Queue LIGADA em produção (1 worker), custo medido e pool do RAG

**Autor:** Freebuff (Buffy) — sessão de 14/11, a pedido do dono.

### Criados

- Nenhum arquivo novo versionado (medição em `/tmp`, descartada).

### Modificados

- `runtime/launcher.py` — `build_api_server` repassa `task_queue` ao
  `APIConfig` (fix do 503 permanente, commit `459decb`).
- `tests/test_task_queue.py` — `test_build_api_server_repassa_a_fila`.
- `memory/rag.py` — `TOP_K_CANDIDATOS` 24 → **32** (medição do gate; piso
  0.399/0.036 intocado).
- `tests/test_rag.py` — fixture `rag_real` com `top_k=32` + nota da
  recalibração de 14/11.
- `.env` (gitignored) — `OD_TASK_QUEUE_ENABLED=1`, `OD_TASK_QUEUE_WORKERS=1`.
- `docs/CHANGELOG.md` (§Task Queue, com a medição e o achado do RAG),
  `docs/ANALISE_SISTEMA_TODO.md` (checkbox da fila fechado),
  `iniciar/session.json`, `iniciar/2026-11-14_conversa_omegadrakon.md` (§13).

### Intenção e estado

- **Intenção:** ligar a fila com 1 worker e medir o custo real de CPU/RAM,
  sem bump (servidor não mudou o APK nem o contrato do app).
- **Custo medido** (`/proc`, 1 s): ocioso ligado 3,20% CPU / 231,1 MB (mediana)
  contra 3,65% / 226,0 MB desligado (+5,1 MB); rajada de 50 tasks reais
  14,03% CPU, +0,1 MB, 68 ms/task (execução p50 0,7 ms); retry real com dead
  letter em 6,01 s. Máquina: 4190 MB livres, 4 vCPUs.
- **Achados:** (1) `GET /admin/tasks` respondia 503 com a fila ligada —
  `task_queue` não chegava ao `APIConfig`; (2) o gate do RAG caiu porque o
  chunk-alvo estava na 24ª posição do pool (medição → 32).
- **Estado entregue:** gate **4679 passed / 16 skipped / 0 falha**,
  `test_rag.py` 93/93, `od-core` (unidade de usuário) reiniciado com MainPID
  2752075, `/health` 28/28, `/admin/tasks` 200 com 0 tarefas, journal 0 erros.
- **Limitação:** o custo medido não cobre action de LLM longa (o custo ali é
  do modelo, não da fila).

---

## 14/11/2026 — Release v1.45.0+2081 (APK com a aba Tarefas)

**Autor:** Freebuff (Buffy) — sessão de 14/11, a pedido do dono.

### Criados

- Nenhum arquivo de código novo (bump + build + registro).

### Modificados

- `.env` → `OD_VERSION=1.45.0` (gitignored)
- `core/capabilities.py` — fallback congelado
- `app/pubspec.yaml` — `1.45.0+2081`
- `integrations/api/server.py` — `_APP_VERSION_CODE = 2081`
- `site/index.html` (badge, card, versionCode), `site/historico.html`
  (1.45.0 + contagens 76 releases/10 na era final)
- `docs/CHANGELOG.md` → seção `## [1.45.0]`; `docs/README_VERSAO.md` → §1.45.0
- `site/OmegaDrakon.apk` e `site/OmegaDrakon-arm64.apk` (gitignored) —
  recompilados por `app/build_apk.sh`

### Intenção e estado

- **Intenção:** publicar a aba Tarefas no aparelho do dono, com o bump SemVer
  e o checklist de release completo.
- **Pronto/validado:** APK com versionName **1.45.0** / versionCode **2081**
  (`aapt`), completo 72.143.782 B e arm64 26.906.437 B; `/app/version`
  anuncia o mesmo build **com o sha256 do binário publicado**; gates Python
  **4678/16/0** e Flutter **analyze 0 issues / 223 passed**; `od-core`
  reiniciado (MainPID 2699533, `/health` 28/28, 0 erros).
- **Pendência:** ligar a fila em produção (`OD_TASK_QUEUE_ENABLED=1`) segue
  sendo decisão do dono.

---

## 14/11/2026 — Task Queue no painel `/admin` e no app (histórico com status e resultado)

**Autor:** Freebuff (Buffy) — sessão de 14/11, a pedido do dono.

### Criados

- `app/lib/screens/tasks_screen.dart` (aba "Tarefas")
- `app/test/tasks_api_test.dart` (5 testes)
- `app/test/tasks_screen_test.dart` (5 testes)

### Modificados

- `integrations/api/server.py` — bloco "Tarefas (Task Queue)" no
  `_ADMIN_PAGE_HTML` + JS `tqLoad/tqSse/tqAcao/tqRender` (filtro, retry, apagar,
  aviso de 503) e ligação no `carregarTudo`.
- `app/lib/services/od_api.dart` — `listTasks`, `retryTask`, `deleteTask` e o
  modelo `OdTask`.
- `app/lib/main.dart` — import, `TasksScreen` na posição 6 e a 8ª aba (Config
  foi para 7 no modo avançado).
- `tests/test_task_queue.py` — teste do painel com a seção nova.
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`, `iniciar/session.json`,
  `iniciar/2026-11-14_conversa_omegadrakon.md` (§11).

### Intenção e estado

- **Intenção:** tornar o histórico da fila visível fora das rotas `/admin`,
  com status e resultado, e permitir retry/apagar sem curl.
- **Pronto/validado:** painel e app implementados; **Python 4678 passed / 16
  skipped**; **`flutter analyze` sem issues**; **`flutter test` 223 passed / 2
  skipped**; JS do painel passou `node --check` (pegou uma aspa errada antes da
  publicação).
- **Pela metade (deliberado):** o **APK não foi recompilado** (deploy do app
  exige bump + ordem); sem prova visual (não há navegador na máquina). Fila
  segue desligada em produção.

---

## 14/11/2026 — Task Queue: histórico de concluídas com poda automática

**Autor:** Freebuff (Buffy) — sessão de 14/11, a pedido do dono.

### Criados

- Nenhum arquivo novo (subdiretório `completed/` é criado em runtime).
- Harness `/tmp/od_tq_historico.py` (fora do repo, descartado após a prova).

### Modificados

- `core/task_queue.py` — `completed_dir`, `keep_completed`
  (`OD_TASK_QUEUE_KEEP_COMPLETED`, 200), `_persist_completed`,
  `_prune_completed` (no `start()` e ao concluir), `get_task`/`list_tasks`
  passam a ler o histórico.
- `integrations/api/server.py` — `DELETE /admin/tasks/{id}` agora apaga também
  o registro de concluída (`tq.completed_dir`).
- `tests/test_task_queue.py` — 18 → 20 testes.
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`, `iniciar/session.json`,
  `iniciar/2026-11-14_conversa_omegadrakon.md` (§10).

### Intenção e estado

- **Intenção:** fechar o buraco medido no turno anterior — a task concluída
  virava 404 e a listagem nunca mostrava `completed`.
- **Pronto/validado:** sandbox com API + registry + catálogo reais e
  `KEEP_COMPLETED=2`: 3 tasks reais → `GET` da recente 200 `completed` com
  `result=true`, `?status=completed` count=2, mais antiga podada (404). Gate
  **4677 passed / 16 skipped / 0 falha**.
- **Pela metade (deliberado):** a fila continua **desligada em produção**;
  mostrar o histórico no painel/app fica no TODO.

---

## 14/11/2026 — Task Queue provada em sandbox (task real, retry e dead letter)

**Autor:** Freebuff (Buffy) — sessão de 14/11, a pedido do dono.

### Criados

- `/tmp/od_tq_prova.py` (harness da prova — **fora do repo**, descartável)

### Modificados

- `core/task_queue.py` — `registry.execute(..., request_id=)` → `session_id=`.
  O registry real não aceita `request_id`; **toda** task morria com `TypeError`.
- `integrations/api/server.py` — `DELETE /admin/tasks/{id}` passou a apagar em
  `tq.dead_letter_dir` (antes usava o caminho global e deixava o arquivo).
- `tests/test_task_queue.py` — 16 → 18 testes (task real no registry real;
  DELETE do dead letter no `queue_dir` da instância).
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (checkbox novo do achado,
  item da fila atualizado), `iniciar/session.json` e
  `iniciar/2026-11-14_conversa_omegadrakon.md` (§9). Nenhuma regra alterada.

### Intenção e estado

- **Intenção:** ligar a fila num teste controlado, provar task real, medir
  retry e dead letter — e não confiar no gate, que usava um registry falso.
- **Pronto/validado:** gate **4675 passed / 16 skipped / 0 falha**; sandbox
  com API + registry + catálogo reais (completed 1,0 s; retry 1,0 s → 2,7 s →
  dead letter 6,5 s; DELETE remove o arquivo e o `GET` volta 404).
- **Pela metade (deliberado):** a fila **continua desligada em produção**
  (`OD_TASK_QUEUE_ENABLED=0`) — ligar é decisão do dono. Task concluída some
  da API (retenção de histórico a decidir) — checkbox no TODO.

---

## 14/11/2026 — Fechamento do lote de 13/11 (Task Queue, Semantic Cache, OpenAI, web_search, escopo, pg_dump)

**Autor:** Freebuff (Buffy) — sessão de 14/11.
**Origem do lote:** **NÃO IDENTIFICADA** — o código de 13/11 estava na árvore,
fora do git e sem registro. Foi encontrado na retomada de 14/11 e fechado por
Buffy (não presuma que o autor destas linhas seja o mesmo do lote).

### Criados

- `core/task_queue.py` (lote 13/11)
- `tests/test_task_queue.py` (Buffy — 16 testes; cobre também os defeitos
  abaixo)
- `runtime/pg_dump_diario.py`, `systemd/od-pg-dump.service`,
  `systemd/od-pg-dump.timer`, `tests/test_pg_dump_diario.py` (lote 13/11)
- `docs/ARCHITECTURE_v2.md`, `docs/NV_DAG_SCHEDULER_REFERENCE.md`,
  `pyproject.toml` (lote 13/11)
- `iniciar/ATRIBUICOES.md` (Buffy)

### Modificados

- `integrations/api/server.py` (lote 13/11) — Buffy removeu a **duplicata** de
  `_task_queue_or_503`, trocou `_query_param` (inexistente → 500) por
  `parse_qs` e fez o SSE emitir status **uma vez** por mudança.
- `runtime/launcher.py` (lote 13/11) — separado em dois commits por assunto
  (fila / IA) por Buffy.
- `core/llm.py` (lote 13/11) — `OpenAIProvider`; Buffy acrescentou o newline
  final que faltava.
- `core/security/scope.py` + `tests/test_scope_audit.py` (lote 13/11).
- `tools/actions/actions.py` + `tests/test_actions_catalog.py`,
  `tests/test_intents.py`, `tests/test_capabilities.py`, `tests/test_mcp_od.py`,
  `tests/test_orchestrator.py`, `tests/test_orchestrator_action_registry.py`,
  `tests/test_api.py` — contagens 123→125 e rotas 124→130 (Buffy).
- `iniciar/RULES.md` (regra 23), `iniciar/session.json`,
  `iniciar/2026-11-14_conversa_omegadrakon.md`,
  `docs/ANALISE_SISTEMA_TODO.md`, `docs/CHANGELOG.md` (Buffy).

### Intenção e estado

- **Intenção do lote:** fechar R1 (fila com retry/dead letter), ligar I1
  (Semantic Cache), trazer OpenAI para a cadeia, criar actions de pesquisa e de
  Mapa de Força, liberar `/tmp` no escopo e automatizar o dump do Postgres.
- **Estado ao ser encontrado:** `pg_dump` já vivo (timer instalado, 3 dumps);
  o resto **sem commit, sem teste e quebrado** — 14 falhas no gate (contagens
  fixas), fila executando a mesma task 2×, JSON de retry apagado, dead letter
  fora do diretório da instância, `GET /admin/tasks` em 500.
- **Estado entregue por Buffy (14/11):** tudo corrigido, `tests/test_task_queue.py`
  novo, **gate 4656 passed / 16 skipped / 0 falha**, commits por assunto,
  publicado em `origin/master` e `od-core` reiniciado com prova viva.
- **O que continua pendente (deliberadamente):** ligar a `web_search` à intenção
  "pesquise na internet…" (`core/intents.py` intocado); `OD_OPENAI_AUTO` só
  testa a existência da chave, não o crédito; `web_search` não está na lista do
  papel `user`; fila desligada por padrão (`OD_TASK_QUEUE_ENABLED=0`).

---

## Antes de 14/11/2026

O projeto não tinha este livro-caixa. O histórico anterior está em
`iniciar/session.json` e nas transcrições `iniciar/YYYY-MM-DD_conversa_omegadrakon.md`
(que registram pedido, feito, testes e decisões, mas **não** nomeiam o autor de
cada lote).

---

## 14/11/2026 — Cota dos providers de LLM visível/alertada no /health (TODO 681, sem bump)

**Autor:** OpenClaude — sessão de 14/11, a pedido do dono ("comece pelo que achar melhor… verifique sempre").

### Criados

- `tests/test_llm_quota_health.py` — 11 testes do check `llm_quota` e de `_limite_de`/`status_quota`.

### Modificados

- `core/resilience.py` — `status_quota()` nova (com `pct_used`); `_limite_de()` nova (env `OD_QUOTA_<PROVIDER>_LIMIT`); Groq provisório **500** em `_QUOTA_DEFAULTS` (cota real desconhecida — aprende no 429 real, ajustável via `OD_QUOTA_GROQ_LIMIT`); `_QUOTA_LOCK` `Lock` → **`RLock`** (deadlock `record_usage → get_quota` na mesma thread, achado pelos testes).
- `runtime/launcher.py` — check não-crítico `llm_quota` no `/health` (29 → 30 checks): todos os providers com `pct_used`, `degraded` acima de `OD_QUOTA_ALERTA_PCT` (padrão 80%) ou esgotado.
- `docs/ANALISE_SISTEMA_TODO.md` — checkbox 681 marcado [x] com nota de entrega.
- `docs/CHANGELOG.md` — entrada "sem bump" no topo (1.45.0/2081 mantido: só backend, sem app/APK/painel novo; sem toolchain Android na máquina e o app não mudou).
- `iniciar/session.json`, `iniciar/2026-11-14_conversa_omegadrakon.md` (§22).

### Intenção e estado

- **Intenção:** quando a cota de um provider esgota, a resposta caía silenciosamente para o modelo local 3B sem ninguém saber por quê — tornar a cota visível e alertada no `/health` (decisões do dono: todos os providers, alerta 80%, limite Groq provisório 500 aprendido no bloqueio real, só o /health).
- **Pronto/validado:** 66 testes passed (`test_llm_quota_health` + `test_resilience` + `test_health` + `test_launcher_health_external`); `py_compile` OK; od-core reiniciado verde (MainPID 3322791, NRestarts=0); `/health` HTTP 200 com 30 checks e `llm_quota up`: `gemini 0% (0/20); groq 0% (0/500); openai 0% (0/100)`; journal limpo. `data/llm_quota.json` ainda não existe (grava no primeiro uso real).
- **Pela metade (deliberado):** o limite real do Groq (500 é provisório) — será ajustado via `OD_QUOTA_GROQ_LIMIT` quando um 429 bloquear de verdade.

---

## 17/11/2026 — Leitura do iniciar e diagnóstico completo do txt.txt

**Autor:** Antigravity (Gemini 3.8 Flash) — sessão de 17/11, a pedido do dono ("leia inicar e txt").

### Criados

- `iniciar/2026-11-17_conversa_omegadrakon.md` (§1).

### Modificados

- `iniciar/session.json` — atualizado com checkpoint da retomada e diagnóstico dos 6 pontos do `txt.txt`.
- `iniciar/ATRIBUICOES.md` — esta entrada no livro-caixa.

### Intenção e estado

- **Intenção:** atender à ordem do dono de ler `iniciar/` e `txt.txt`, levantando com precisão os fatos sobre as músicas do Raul Seixas no acervo, desenhar a solução para exclusão de músicas indesejadas e exceções de cantores bloqueados, e realizar a análise do site GSN Offline e dos vídeos de resiliência digital (apps off-grid e Meshtastic LoRa).
- **Pronto/validado:** varredura completa do acervo real (`/home/alex/dados/musicas/acervo.db`), logs do pipeline, backups históricos e AzuraCast; análise técnica detalhada do site `gsnoffline.com` e extração de legendas/conteúdo dos dois vídeos do YouTube; transcrição do dia e checkpoint gravados.
- **Pela metade (deliberado):** implementação das rotas e filtros da rádio aguardando confirmação do dono sobre as opções propostas.

---

## 17/11/2026 — Investigação da lista de Raul Seixas (Pedido 11)

**Autor:** Antigravity (Gemini 3.8 Flash) — sessão de 17/11, a pedido do dono.

### Modificados

- `iniciar/2026-11-17_conversa_omegadrakon.md` (§2 adicionada).
- `iniciar/session.json` (checkpoint atualizado).

### Intenção e estado

- **Intenção:** descobrir por que apenas "Metamorfose Ambulante" foi baixada e onde foram parar as outras músicas da lista de Raul Seixas.
- **Achado / Causa Raiz:** comprovado via auditoria do banco `data/radio_pedidos.db` e do log `logs/radio_link_11.log`. O sanitizador `link_do_youtube()` em `integrations/radio_pro.py` possuía um bug: se a URL copiada pelo usuário fosse de reprodução (`/watch?v=...&list=...`), ele descartava o parâmetro `list` e salvava apenas o link do vídeo individual. Por isso o worker recebeu 1 faixa só e nunca chamou `_baixar_resto()`.
- **Pronto:** diagnóstico completo e reprodução do bug documentados.

---

## 17/11/2026 — Correção do link_do_youtube: preservação de playlists em URLs /watch e youtu.be

**Autor:** Antigravity (Gemini 3.8 Flash) — sessão de 17/11, a pedido do dono ("sim, corrija").

### Modificados

- `integrations/radio_pro.py` — `link_do_youtube`: preserva `list=` em URLs `/watch`, `/playlist` e `youtu.be` com `&v=...`.
- `integrations/radio_link.py` — `processar_pedido`: se a URL trouxer `&v=...`, move essa faixa para o topo (`entradas[0]`) para tocar primeiro, chamando `_baixar_resto()` para as demais.
- `tests/test_radio_link.py` — testes atualizados e teste novo `test_playlist_com_video_especifico_toca_ele_primeiro`.
- `docs/CHANGELOG.md` — entrada de 17/11 (sem bump) no topo.
- `iniciar/session.json` — checkpoint atualizado.

### Intenção e estado

- **Intenção:** resolver a causa raiz que impediu o download das outras faixas da lista de Raul Seixas; links com vídeo e lista juntos agora preservam a lista inteira.
- **Pronto/validado:** 170 testes de rádio passando (incluindo `test_radio_link` e `test_radio_cobertura`); 385 testes de rádio e API passando sem nenhuma falha.

---

## 17/11/2026 — Janela de decisão de 24 h (cantor ou música bloqueada) e excluir sem bloquear

**Autor:** Codebuff (Buffy) — sessão de 17/11, a pedido do dono: *"se a musica
for de um cantor bloqueado, vai me avisar e tenho 24 horas para decidir, se não
permitir ela é automaticamente apagada"*, *"o mesmo para certas musicas, as
vezes o cantor é permitido, mas uma musica especifica não"* e *"musicas
apagadas podem voltar a ser baixadas, posso apagar simplesmente por achar uma
versão melhor"*.

### Modificados

- `integrations/radio_cantores.py` — `HORAS_DECISAO` (24 h), prazo no
  registro, `decidir()`, `aviso_de_decisao()`, `pendentes()` com tempo
  restante, `limpar_tocados()` só apaga no vencimento, exclusão sem bloqueio.
- `integrations/radio_link.py` — pedido avulso não é recusado; aviso ao dono
  com prazo e quem pediu.
- `integrations/radio_pro.py` — catálogo também marca música bloqueada.
- `integrations/api/server.py` — `POST /api/radio/musicas/decisao`, `decisoes`
  no GET, exclusão com `bloquear=false`, bloco "Decisões pendentes (24 h)" no
  painel.
- `site/radio-pro.html` — mesmo bloco no card de curadoria; confirm de
  exclusão sem bloqueio.
- Testes: `tests/test_radio_cantores.py`, `tests/test_radio_curadoria.py`,
  `tests/test_radio_cobertura.py`, `tests/test_radio_link.py`,
  `tests/test_api.py` (rotas 136 → 137).
- Registro: `docs/CHANGELOG.md` (topo), `docs/ANALISE_SISTEMA_TODO.md`,
  `iniciar/2026-11-17_conversa_omegadrakon.md` (§6 corrigida + §7),
  `iniciar/session.json`.

### Intenção e estado

- **Intenção:** o ouvinte pode gostar de um cantor que o dono não gosta (e
  vice-versa, o cantor é permitido mas uma música não) — a faixa toca uma vez,
  o dono é avisado e decide em 24 h; sem decisão, sai sozinha. Excluir do
  acervo deixou de bloquear, para poder baixar uma versão melhor depois.
- **Pronto/validado:** gate completo **5370 passed / 16 skipped / 0 falha**
  (203,89 s, exit 0), `node --check` no painel e na página.

---

## 17/11/2026 — Decisões da rádio no app Android (1.45.1+2082)

**Autor:** Codebuff (Buffy) — sessão de 17/11, a pedido do dono: *"Mostrar as
decisões pendentes também no app Android"*.

### Modificados

- `app/lib/services/od_api.dart` — `OdDecisaoRadio`,
  `listRadioDecisoes()`, `decidirRadio()`.
- `app/lib/screens/dashboard_screen.dart` — card "Decisões pendentes (24 h)"
  no Painel (admin), com Permitir / Apagar já.
- `app/test/dashboard_radio_test.dart` — 9 testes novos.
- `app/pubspec.yaml` (1.45.1+2082), `.env` (OD_VERSION), fallback em
  `core/capabilities.py`, `integrations/api/server.py`
  (`_APP_VERSION_CODE`), `site/index.html`, `site/*.apk`.
- Registro: `docs/CHANGELOG.md` [1.45.1], `docs/README_VERSAO.md` [1.45.1],
  `iniciar/2026-11-17_conversa_omegadrakon.md` §8, `iniciar/session.json`.

### Intenção e estado

- **Intenção:** o dono decide a faixa em 24 h pelo celular, sem abrir o site.
- **Pronto/validado:** `flutter analyze` 0 issues · `flutter test` 237 passed
  / 2 skipped · gate Python 5370 passed · APKs 1.45.1+2082 publicados em
  `site/` (antigos em `backups/apk-v1.45.0-2081/`).

---

## 17/11/2026 — Push FCM ao entrar na decisão de 24 h

**Autor:** Codebuff (Buffy) — sessão de 17/11, a pedido do dono: *"Enviar
push FCM quando uma faixa entrar na janela de decisão de 24 h"*.

### Modificados

- `integrations/radio_cantores.py` — push na primeira marcação, com data
  `origem=radio-decisao`, e monta o serviço quando o processo não tem launcher.
- `tests/test_radio_cantores.py` — +5 testes (envio único/payload,
  idempotência, falha do FCM, serviço construído no subprocesso).
- Registro: `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`,
  `iniciar/2026-11-17_conversa_omegadrakon.md` §9, `iniciar/session.json`.

### Intenção e estado

- **Intenção:** o dono saber na hora, no celular, que tem 24 h para decidir.
- **Pronto/validado:** gate **5375 passed / 16 skipped / 0 falha**; push
  `enabled` com 1 aparelho e notificação de teste entregue após o restart.

---

## 17/11/2026 — Lembrete de push 2 h antes do prazo da decisão

**Autor:** Codebuff (Buffy) — sessão de 17/11, a pedido do dono: *"Enviar um
lembrete de push 2 horas antes do prazo vencer"*.

### Modificados

- `integrations/radio_cantores.py` — `HORAS_LEMBRETE`, lembrete dentro de
  `limpar_tocados()` (uma vez por faixa, `lembrete_em`) e a chave `lembretes`
  no retorno.
- `tests/test_radio_cantores.py` (+4) e `tests/test_radio_cobertura.py`
  (retorno com `lembretes`).
- Registro: `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`,
  `iniciar/2026-11-17_conversa_omegadrakon.md` §10, `iniciar/session.json`.

### Intenção e estado

- **Intenção:** avisar no celular quando o prazo está perto, para o dono não
  perder a faixa por esquecimento.
- **Pronto/validado:** gate **5379 passed / 16 skipped / 0 falha**.

---

## 17/11/2026 — Timer próprio da janela de decisão no core

**Autor:** Codebuff (Buffy) — sessão de 17/11, a pedido do dono: *"Mover a
checagem de lembretes e vencimentos para um timer periódico do core"*.

### Modificados

- `runtime/launcher.py` — `_run_radio_decisoes_forever` e o loop
  supervisionado `radio-decisoes` (60 s, `asyncio.to_thread`, erro contido).
- `tests/test_launcher_supervisor.py` — +3 testes do timer.
- Redação dos docs desta sessão: "campo `X`" → "chave `X`" (colisão com a
  calibração do RAG, corrigida na causa).
- Registro: `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`,
  `iniciar/2026-11-17_conversa_omegadrakon.md` §11, `iniciar/session.json`.

### Intenção e estado

- **Intenção:** lembrete e vencimento com relógio próprio, sem depender de a
  rádio trocar de faixa.
- **Pronto/validado:** gate **5382 passed / 16 skipped / 0 falha**; loop no ar
  após o restart.

---

## 17/11/2026 — Resumo diário das faixas apagadas pela janela

**Autor:** Codebuff (Buffy) — sessão de 17/11, a pedido do dono: *"Criar um
resumo diário das faixas apagadas automaticamente pela janela de 24 h"*.

### Modificados

- `integrations/radio_cantores.py` — `motivo_fim`/`apagada_em` no registro,
  `resumo_diario()` e `enviar_resumo_se_devido()` (uma vez por dia, hora
  configurável, estado em `data/`).
- `runtime/launcher.py` — o loop `radio-decisoes` chama o resumo.
- `tests/test_radio_cantores.py` (+6) e `tests/test_launcher_supervisor.py`
  (dublê com `enviar_resumo_se_devido`).
- Registro: `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`,
  `iniciar/2026-11-17_conversa_omegadrakon.md` §12, `iniciar/session.json`.

### Intenção e estado

- **Intenção:** fechar o dia com o que a janela apagou sem decisão do dono,
  em vez de deixar isso só no log.
- **Pronto/validado:** gate **5388 passed / 16 skipped / 0 falha**.

---

## 17/11/2026 — P0: cache de conversa não serve resposta inventada

**Autor:** Codebuff (Buffy) — sessão de 17/11, a pedido do dono: *"Fechar o
P0: impedir que o llm_cache sirva resposta inventada de conversa comum"*.

### Modificados

- `core/orchestrator.py` — `cache_serve_reason()` (guarda de leitura),
  `_resposta_do_cache()` (valida, apaga a entrada inválida e devolve MISS) nos
  dois pontos de leitura (stream e grafo, cache exato e semântico); prefixo
  `"⚠️ não executei nada"` em `_CACHE_BAN_PREFIXES`. **Não** foi banida a frase
  "Estado verificado." (é a assinatura da Guardian no prompt de personalidade)
  nem a resposta de modelo local — as duas regras foram testadas, medidas e
  retiradas (ver transcrição §19).
- `tests/test_orchestrator.py` — `TestCacheDeConversa` (7 testes).
- `tests/test_radio_cantores.py` — assertion do dia do resumo passou a usar a
  data **local** (ficava vermelha entre 21h e meia-noite local).
- Registro: `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (checkbox
  fechada), `iniciar/2026-11-17_conversa_omegadrakon.md` §19, `iniciar/session.json`.

### Intenção e estado

- **Intenção:** o cache era lido antes das guardas do turno; sem revalidar na
  leitura, resposta inventada (e entrada gravada antes de um ban novo) era
  servida para sempre.
- **Pronto/validado:** gate completo **5381 passed / 19 skipped / 0 falha**;
  `tests/test_orchestrator.py` + `tests/test_api.py` 277 passed. Cache vivo:
  4 de 144 entradas recusadas pelas guardas (invenção de agenda + avisos).
- **Sem bump:** correção de servidor, contrato do app intacto (1.46.0+2083).

## 2026-11-18 — Anti-falso-sucesso de rádio/volume no `llm_cache` (sem bump)

**Autor:** Buffy (Codebuff) — continuação do P0 nº 1 de 17/11.

### Arquivos

- `core/orchestrator.py` — `_FAKE_ACTION_RES` ampliado: participíos de
  mídia/casa na construção "… com sucesso" e `volume … para N%`.
- `tests/test_orchestrator.py` — teste novo
  `test_falso_sucesso_de_midia_e_casa_tambem_e_pego` (7 inventadas recusadas,
  7 respostas reais da rota aceitas).
- Registro: `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (P0 nº 1
  riscado como ENTREGUE; checkbox de mídia/casa fechado),
  `iniciar/2026-11-18_conversa_omegadrakon.md` §12, `iniciar/session.json`
  (`falso_sucesso_midia_2026_11_18`).

### Intenção e estado

- **Intenção:** a guarda de leitura do cache (17/11) reusava um
  anti-falso-sucesso que só conhecia agenda; invenções de rádio/volume
  passavam para o dono e para o cache.
- **Base:** a saída real de `intents._formata_radio` nunca usa "com sucesso"
  nem "volume definido para" — logo essas construções denunciam invenção.
- **Pronto/validado:** `tests/test_orchestrator.py` **76 passed**; cache vivo
  (145 entradas) recusa **3 novas**, todas invenções, e **0 legítimas**;
  `od-core` reiniciado (PID 459066), `/health` `ok=true`, journal limpo.
- **Limite:** estado sem "com sucesso" ("Radio ligada.") continua passando —
  pode ser leitura verdadeira.

## 2026-11-18 — I2 (Hybrid Search) fiado no RAG, medido e mantido OFF (sem bump)

**Autor:** Buffy (Codebuff) — P1 nº 5 do backlog.

### Arquivos

- `core/hybrid_search.py` — `tokenizar()` e `fundir_rrf()` em nível de módulo;
  `HybridRetriever` passou a usá-los (comportamento igual).
- `memory/vector.py` — propriedade pública `provider` (o candidato lexical
  precisa do MESMO provider da indexação para o cosseno ser comparável).
- `memory/rag.py` — `hibrido=` / `OD_RAG_HIBRIDO` (padrão `0`); `sync()` monta
  `BM25Index` sobre os mesmos chunks; `_consultar()` une os candidatos
  lexicais por `doc_id` com cosseno real; métrica `lexicais`.
- `tools/medir_rag_hibrido.py` (novo) — medidor reproduzível antes/depois.
- `tests/test_rag.py` — `TestHibrido` (5 testes).
- Registro: `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md`,
  `iniciar/2026-11-18_conversa_omegadrakon.md` §13, `iniciar/session.json`
  (`i2_rag_hibrido_2026_11_18`).

### Intenção e estado

- **Intenção:** o HashEmbedding não vê termo raro; o BM25 vê. O item pedia
  fiação **com** medição — e a medição é o que decide o default.
- **Medido (3815 chunks):** relevantes 8/8 → 8/8; paráfrases 6/6 → 6/6;
  **irrelevantes bloqueadas 8/8 → 6/8**. Ganho pontual: o chunk
  `[1.24.2] — EVAL DO ASSISTENTE` passou a entrar no bloco do golden de eval.
- **Causa da regressão:** candidato lexical com `overlap=1.0` só por conter o
  termo raro (ex.: "basquete" num chunk de release); o overlap-IDF foi
  calibrado para candidatos densos.
- **Decisão:** fiação pronta, **OFF por padrão**. Ligar exige recalibrar o
  piso com grid medido — não se afrouxa asserção para a novidade caber.
- **Efeito colateral:** o texto novo no corpus mexeu no IDF e derrubou o gate;
  corrigido reescrevendo o nosso texto ("invenções reais" → "invenções de
  fato"), sem tocar no piso.
- **Validado:** gate completo **5465 passed / 19 skipped / 0 falha**;
  `test_rag` 98 passed; `od-core` reiniciado, `/health` `ok=true`.

---

## 26/11/2026 — Recarga automática do painel do SO

**Autor:** Freebuff (Buffy) — ordem do dono (*"Faça o painel recarregar sozinho
o status do SO enquanto o ciclo estiver rodando, sem apertar Atualizar"*).

### Criados

- nenhum arquivo novo (transcrição §7).

### Modificados

- `integrations/api/server.py` — `SO_INTERVALO_MS`, `soDeveRecarregar` (pura),
  `soAgendarRecarga` (sem empilhar timers), gancho em `soLoad()`, aviso de
  conclusão, re-leitura em 1,5 s após o 202.
- `core/os_updater.py` — `unidade_em_andamento()` passa a contar `activating` e
  `reloading` (defeito medido: a unit arrancando já lia como parada).
- `tests/test_painel_os_updater.py` — 4 casos novos (node com timers falsos +
  estados do `is-active`) → 16 no arquivo.
- `docs/CHANGELOG.md`, `iniciar/session.json`,
  `iniciar/2026-11-26_conversa_omegadrakon.md` (§7), `txt.txt`.

### Intenção e estado

**Pronto e validado:** 302 testes (api+os_updater+health+painel); `/admin` 200
servindo as funções; status 200 com `em_andamento: False`; journal `-p err` 0;
prova viva no restart 02:32 (MainPID 2450715).

**Limitação:** sem navegador na máquina, o comportamento foi provado em teste
de unidade no node (timers falsos), não visualmente.

**Pela metade / próximo passo:** nada pendente. Segue aberto só o clique real
do botão (67 pacotes + 51 firmwares, reboot em +5 min) — decisão do dono.

---

## 26/11/2026 — Aviso no Telegram do desfecho do ciclo

**Autor:** Freebuff (Buffy) — ordem do dono (*"Faça o painel avisar no Telegram
quando um ciclo aplicado terminar ou falhar"*).

### Criados

- nenhum arquivo novo (transcrição §8).

### Modificados

- `core/os_updater.py` — `_notificar_resultado()` (❌ falha com as seções que
  quebraram / ⚠️ reboot / ✅ sem reboot), substituindo os dois avisos antigos;
  abertura marca "(pedido pelo painel)" no `--forcar`.
- `integrations/api/server.py` — texto da seção avisa que o desfecho chega no
  Telegram.
- `tests/test_os_updater.py` — 4 casos novos → 57 no arquivo.
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (checkbox do `OnFailure`),
  `iniciar/session.json`, `iniciar/2026-11-26_conversa_omegadrakon.md` (§8),
  `txt.txt`.

### Intenção e estado

**Pronto e validado:** 288 testes (api+painel+os_updater); `/admin` 200 com o
aviso; status 200; journal `-p err` 0; prova viva no restart 02:52
(MainPID 2457865).

**Limitação:** morte do processo antes do fim não notifica (sem `OnFailure`) —
anotado no §4 do TODO.

**Pela metade / próximo passo:** nada pendente. O clique real do botão segue
decisão do dono.

---

## 26/11/2026 — Fila 1–3: OnFailure, verificador de units, simulação

**Autor:** Freebuff (Buffy) — ordem do dono (*"sim. depois coloque em uma lista
de prioridades e vamos do primeiro ao ultimo"*).

### Criados

- `core/systemd_units.py` — verificador repo × systemd (cache 5 min).
- `tests/test_systemd_units.py` — 6 casos.
- `systemd/od-os-updater-falha.service` — aviso de falha (instalada).

### Modificados

- `core/os_updater.py` — `avisar_falha()`/`--avisar-falha` e
  `relatorio_simulacao()`/`--relatorio`.
- `systemd/od-os-updater.service`, `systemd/od-os-updater-forcar.service` —
  `OnFailure=`.
- `runtime/launcher.py` — `register_units_health()` (check `units_instaladas`).
- `tests/test_os_updater.py` — 6 casos novos → 63.
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (3 checkboxes + fila),
  `iniciar/session.json`, `iniciar/2026-11-26_conversa_omegadrakon.md` (§9),
  `txt.txt`.

### Intenção e estado

**Pronto e validado:** 318 testes no conjunto; `/health` com 34 checks e
`units_instaladas` up; `--avisar-falha` sem falso alarme; `--relatorio` legível.

**INCIDENTE (registrado):** durante a prova do OnFailure o ciclo **real**
`--forcar` rodou — 67 pacotes e 51 firmwares aplicados em 02:13, reboot
agendado e **cancelado** por mim (`shutdown -c`). Sem reboot; sistema
verificado e saudável; `/var/run/reboot-required` segue pendente à espera da
decisão do dono. Causa: drop-in de teste não lido pelo `daemon-reload`.

**Pela metade / próximo passo:** fila item 4 (guarda de offsite no verificador
semanal), depois 5 (comparador de modelos).

---

## 26/11/2026 — Fila item 4: guarda de off-site no verificador semanal

**Autor:** Freebuff (Buffy) — ordem do dono (*"Siga para o item 4 da fila:
guarda de offsite junto do verificador semanal"*).

### Criados

- nenhum arquivo novo (transcrição §10).

### Modificados

- `runtime/verificar_restauracao_pg.py` — `verificar_offsite()` chamando
  `tools/checar_offsite_pg.py --json`; alarme só em divergência; estado
  `offsite_ok`/`offsite`/`offsite_aviso_em`; `main()` liga a guarda.
- `tests/test_verificar_restauracao_pg.py` — 7 casos novos → 13.
- `docs/CHANGELOG.md`, `docs/ANALISE_SISTEMA_TODO.md` (checkbox + fila item 4),
  `iniciar/session.json`, `iniciar/2026-11-26_conversa_omegadrakon.md` (§10),
  `txt.txt`.

### Intenção e estado

**Pronto e validado:** 13 testes do runner; rodada real com restore OK e dump
com sha256 idêntico no canal e nas 2 HDs (`offsite_ok: true`, sem mensagem).

**Descartado de propósito:** uma primeira versão comparava nome/idade do
`offsite_state.json`; era um critério paralelo ao `checar_offsite_pg.py` já
existente — removida antes de commitar.

**Pela metade / próximo passo:** fila item 5 (comparador de modelos lado a lado).
