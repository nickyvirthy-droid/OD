# Conversa OmegaDrakon — 2026-09-29

Sessão: `conv-2026-09-11T12:45-omegadrakon-dev-status` · retomada com
"leia iniciar, houve falha na ultima vez" (~09:1x). Ambiente canônico de
testes: `.venv/bin/python` SEM `OD_TEST_POSTGRES_DSN`.

---

## 1. Retomada e resgate do lote órfão v1.8.1 (~09:1x–09:2x)

Pedido: "leia iniciar, houve falha na ultima vez. melhor fazer um resumo
antes de implementar para saber o que estava fazendo".

### Diagnóstico

- HEAD `7798f5c` == origin/master (sessão v1.8.0 registrada em 28/09);
  od-core no ar era o deploy v1.8.0 (PID 883071).
- Working tree com **lote órfão de 9 arquivos** (+582/−27, mtimes
  20:12–21:07 de 28/09 — DEPOIS da transcrição ~20:3x e do commit
  `6d68780`): a sessão anterior morreu no meio da implementação da
  pendência explícita da v1.8.0 — o **CONTROLE de luzes pelo chat**:
  - **Action nova `ha_light_control`** (catálogo 62 → 63, categoria
    iot=4, papel admin): liga/desliga UMA luz; confirmação de 2 passos
    (intenção pendente por user+luz+ação, TTL 120s em
    `_LIGHT_CONFIRMATIONS`, consumo só após execução bem-sucedida).
  - **core/intents.py**: `detect_confirmation` + `resolve_light_target`
    (nome falado → entity_id via `_HA_ENTITIES`) +
    `configure_ha_entities`.
  - **core/orchestrator.py**: o "sim" consulta
    `peek_pending_light_confirmation` e executa a MESMA luz/ação no
    fastpath determinístico (SEM LLM), nos dois caminhos
    (process/process_stream); negação do Registry vira resposta guiada
    `permissao_negada` (não cai no LLM, que podia alucinar confirmação).
  - **runtime/launcher.py**: `build_action_registry` carrega as
    entidades do HA (`configure_ha_entities`) e injeta `user_id` nos
    params de `ha_light_control`.
  - **+157 linhas de testes** em test_resposta_transparente.py;
    catálogo 62→63 fixado em 4 arquivos de teste.
- Resumo apresentado ao dono antes de qualquer mudança (pedido
  explícito). O dono escolheu **"Concluir tudo"** (bump, commit+push,
  deploy, prova viva, registro).

### Validação do lote em sandbox (regra 13, passo 1)

- Suíte completa: **2002 passed, 16 skipped** — o código estava pronto
  e verde; faltava apenas bump/commit/deploy/registro.

## 2. Bump 1.8.1 (PATCH) + versionCode 2021 (~09:2x)

- Política: completamento da capacidade do lar desenhada na 1.8.0 =
  PATCH (precedente 1.6.1). O app não muda de conteúdo, mas o
  versionCode sobe para **2021** (> 2020) para manter a linhagem
  monotônica da auto-atualização.
- Checklist completo: `.env` OD_VERSION=1.8.1 (sed — gitignored) ·
  `core/capabilities.py` fallback 1.8.1 · `app/pubspec.yaml`
  1.8.1+2021 · `integrations/api/server.py` `_APP_VERSION_CODE = 2021`
  (guarda de coerência da §7 de 28/09 fixa esta constante) ·
  `site/index.html` (2×: hero-badge e card do APK) ·
  `docs/CHANGELOG.md` seção [1.8.1] no topo · `docs/README_VERSAO.md`
  §1.8.1.
- Nota: o CHANGELOG recebeu a [1.8.1] no TOPO conforme a regra do
  próprio arquivo ("mais recente no topo") — a [1.7.0] estava
  desordenada acima da [1.8.0] (herda da gravação de 28/09); a [1.8.0]
  permanece onde está (não reordenado nesta sessão).

## 3. Validação com o bump

- Guardas de versão + arquivos tocados: **174 passed** (test_version_
  policy, test_actions_catalog, test_capabilities,
  test_resposta_transparente, test_orchestrator,
  test_orchestrator_action_registry).
- Suíte completa: **2002 passed, 16 skipped** (68s).

## 4. APK 1.8.1+2021 (~09:2x)

- APKs 1.8.0+2020 anteriores preservados em
  `backups/apk-v1.8.0+2020-20260929/`.
- `app/build_apk.sh` com ambiente do servidor (PATH ~/flutter/bin,
  JAVA_HOME ~/jdk, ANDROID_SDK_ROOT ~/android-sdk): full
  **52.937.991 B** (sha256 189462ea…) + arm64 **18.849.586 B** (sha256
  13d93ff8…) publicados em site/.
- aapt2: `versionCode='2021' versionName='1.8.1'` nos DOIS.
- App: flutter analyze **0 issues**; flutter test **96 passed, 2
  skipped**.

## 5. Commit e publicação (regra 7.1)

`218f174` feat(iot,intents): controle de luzes pelo chat —
ligar/desligar com confirmação de 2 passos (v1.8.1) — **16 arquivos
+651/−35** (o lote órfão + bump + CHANGELOG/README + session.json
inicial). Push: `7798f5c..218f174 master -> master`.

## 6. Deploy e prova viva 6/6 (~09:27)

Restart com a autorização permanente de 09-23: **PID 949403, active,
NRestarts=0** (09:27:53).

1. `/health` com chave → 200; `/app/version` público → `{1.8.1,
   version_code 2021, sha256 189462ea…}` — sha256 anunciado ==
   binário de site/; `/capabilities` → 1.8.1; WS :8001 → 426.
2. **Leitura**: "luzes acesas" → `fastpath:ha_lights` 💡 0 acesa(s) de
   6 (estado real do HA em ~11ms, ZERO LLM).
3. **Pedido**: "liga a luz da varanda" → 💡 "Confirmar: ligar 'Luz da
   Varanda' (agora: off)? Responda **sim** para executar — a
   confirmação vale por 2 minutos" (`fastpath:ha_light_control`,
   7.7ms).
4. **Confirmação**: "sim" → ✅ "Luz da Varanda: ligar executado (🟢
   estado agora: on)" — 449ms (chamada real ao HA), ZERO LLM.
5. **Estado + desligar**: "luzes acesas" → 1 acesa de 6 (Luz da
   Varanda com entity_id real switch.luz_da_varanda_sonoff_…);
   "desliga a luz da varanda" + "sim" → ✅ desligar executado (⚪ off)
   — lar de volta ao estado original.
6. **Gate de papel**: login do papel user (teste) + "liga a luz da
   cozinha" → 🔒 "Controle de luzes é só o dono do sistema — a sua
   conta não pode ligar/desligar dispositivos" (determinístico, sem
   LLM, 4.5ms).

- `/supervision` up, restarts 0, degraded [].
- Journal pós-deploy: 0 Traceback/ERROR. Os 2 registros [NICKY][CRIT]
  de 09:29 são o LOG DE NEGAÇÃO DE SEGURANÇA da própria prova do item
  6 (`action=ha_light_control | allowed=False | denied_by=permission |
  role=user`) — o gate funcionando como desenhado, não é erro.

## 7. Prova pelo celular: auto-atualização + controle de luzes no app (~09:35–09:44)

Pedido do dono: "Testar o controle de luzes pelo app no celular após a
auto-atualização para o 1.8.1+2021". Dono confirmou: **"funcionou"**.

- **Auto-atualização provada fim a fim pela 1ª vez desde a 1.7.0:** o
  app 1.8.0+2020 do celular recebeu o banner (2021 > 2020), baixou o
  APK (~53 MB), conferiu o SHA-256 e instalou o 1.8.1+2021 — sem site,
  sem cabo, sem loja.
- **Rastro no journal (user_id=alex, via=session — WS do app):**
  - 09:41:53 · ha_light_control · 531ms (execução real no HA)
  - 09:42:48 · ha_lights · 5ms (leitura "luzes acesas")
  - 09:43:12→16 · confirmação (6ms) + **ligar executado (454ms)**
  - 09:43:35→40 · confirmação (6.8ms) + **desligar executado (479ms)**
  - 09:43:50→58 · outro ciclo confirmação (6.2ms) + execução (1.472s)
  - Padrão 2 passos visível: chamadas rápidas (~5–15ms) = pedidos/
    confirmações no fastpath; chamadas de ~0,5s = service call real do
    HA. ZERO LLM em toda a sequência de luzes.
- **Estado final do lar:** 0 acesa(s) de 6 — o dono ligou e desligou e
  a casa voltou ao estado original (o ciclo fechou pelo próprio app).
- Servidor durante a prova: /health 200 · PID 949403 · NRestarts=0 ·
  journal 0 erros. Nada reiniciado nesta prova.

## Estado final

- **CONCLUÍDO E NO AR** — v1.8.1 implantada, provada no servidor (6/6)
  E NO CELULAR: auto-atualização 1.8.0+2020 → 1.8.1+2021 funcionando
  pela 1ª vez e CONTROLE de luzes operando pelo chat do app
  (confirmação de 2 passos + gate de papel). Ciclo ligar→desligar
  fechado pelo dono; lar no estado original.
- HEAD `218f174` == origin/master; árvore limpa (só os snapshots
  untracked de podas de cache conhecidos em backups/).
- O app 1.8.0+2020 do celular recebe o 1.8.1+2021 pela auto-atualização
  (versionCode maior; conteúdo do app é o mesmo).
- Pendência herdada encerrada: o "aguardando aprovação do dono" para o
  controle de luzes (registrado desde a v1.8.0) está resolvido — o dono
  aprovou ao escolher "Concluir tudo" nesta sessão.
- Confirmação do dono às ~09:4x: "funcionou" — prova no celular
  fechada (§7). PONTO ENCERRADO.

## 9. v1.9.1 — Coerência do lar: nunca responde por dispositivo errado (~10:3x–11:2x)

Pedido do dono: "leia as conversas, algumas respostas não condizem, se
vai colocar no cache pelo menos deve ser coerente, tipo da luz, não
posso pedir sala e ele responder cozinha, diga simplesmente que não
pode ou algo mais explicativo porem genérico".

### Diagnóstico (leitura das conversas REAIS de 29/09)

- **BUG-A (09:36)**: 'acenda a luz do corredor' + 'sim' → '✅ Luz da
  Varanda: desligar executado'. Journal: os turnos com resposta errada
  têm `route=llm` — o gemma IMITOU o formato determinístico
  ('💡 Confirmar'/'✅ executado') em turnos que não casaram intenção
  (o 'acenda' com erro de digitação não era reconhecido).
- **BUG-B (09:41)**: 'luzes acessas' → '💡 Confirmar: ligar Luzes
  Acessas (off)?' — entidade INVENTADA a partir do próprio comando.
- **Cache**: confirmações ('💡 Confirmar:…') e execuções ('✅ …
  executado') do lar ERAM cacheáveis — servidas depois como resposta
  de outra pergunta (incoerência eterna).

### Correções (todas determinísticas, sem LLM)

1. **Vocabulário a prova de digitação**: 'acenda' entra nos verbos de
   comando; 'acessas/acesso' entra nos padrões de estado → 'luzes
   acessas' vai para a LEITURA real (ha_lights).
2. **Coerência do 'sim'** (nova `confirm_texts_match_pending`): a
   confirmação que menciona OUTRO lugar ('sim, da sala' com pendente do
   corredor) NÃO executa — recusa genérica e honesta ('Essa confirmação
   não bate com o que você pediu antes'), sem LLM, e a intenção velha
   é descartada (o 'sim' seguinte não executa nada).
3. **Plural nunca inventa entidade**: 'liga as luzes (da sala)' →
   '💡 Não posso acionar várias luzes de uma vez — diga qual luz ou
   tomada' (resposta genérica pedida pelo dono).
4. **Cache coerente**: '💡 Confirmar:…' e '✅ … executado' NUNCA
   entram no cache LLM (`cache_failure_reason`); leitura do lar continua
   cacheável.

### Teste do teste

- **4/4 mutações detectadas e revertidas**: (M1) coerência do 'sim'
  desligada; (M2) caminhos do plural removidos; (M3) cache aceitando
  confirmação/execução; (M4) regex do 'sim' de volta ao strict
  (confirmação com lugar deixaria de ser detectada). 1ª rodada pegou
  2 mutações FRACAS (testes não distinguiam os caminhos) — endurecidos
  com 'liga as luzes da sala' e o caso real do corredor.
- +6 testes em TestCoerenciaDoLar (casos REAIS do dono).

### Validação, bump 1.9.1 (PATCH) e publicação

- Suíte: **2013 passed, 16 skipped** (+6).
- Checklist completo: .env 1.9.1, capabilities, pubspec **1.9.1+2023**,
  **_APP_VERSION_CODE=2023**, site 2×, CHANGELOG [1.9.1],
  README_VERSAO §1.9.1. APK rebuildado (aapt2 versionCode='2023'; full
  sha256 49dbba94…; arm64 19844d9e…; anteriores em
  backups/apk-v1.9.0+2022-20260929/).
- Commit: `0988021` fix(intents,core): coerência do lar (v1.9.1) — 10
  arquivos +403/−57; HEAD == origin/master.

### Deploy e prova viva (PID 966981, restart 11:17:51, NRestarts=0)

1. **BUG-B corrigido**: 'luzes acessas' → 💡 LEITURA real
   (fastpath:ha_lights) — nunca mais 'Confirmar: ligar Luzes Acessas'.
2. **Plural genérico**: 'liga as luzes da sala' → 'Não posso acionar
   várias luzes de uma vez' (determinístico; a 'Luz Sala' existe e está
   unavailable — o plural NÃO a aciona).
3. **BUG-A corrigido**: 'acenda a luz do corredor' → 'Confirmar: ligar
   Luz Corredor' + 'sim, da sala' → 🤔 'Essa confirmação não bate com o
   que você pediu antes' (ZERO LLM, nada executado) + 'sim' puro → não
   executa nada (intenção descartada).
4. **Fluxo normal preservado**: corredor + 'sim' puro → executa o
   CORREDOR; varanda ligar/desligar com 'sim' puro → executa a VARANDA.
5. **Cache**: 2ª 'luzes acessas' idêntica → served do cache como LEITURA
   (route=cache) — coerente; confirmações/execuções não entram mais.
6. /health 200; journal 0 Traceback/ERROR/CRIT; casa de volta ao estado
   original (0 luzes acesas além da tomada do servidor, que estava on).

Pendente: instalar o APK 1.9.1+2023 no celular (auto-atualização,
2023 > 2022).

## 8. v1.9.0 — Controle do lar expandido: tomadas com o mesmo padrão (~09:5x–10:2x)

Pedido do dono: "Estender o controle do lar para tomadas e outros
dispositivos do HA com o mesmo padrão de confirmação".

### Inventário ANTES do código (evidência, não suposição)

- HA do dono: **9 switches SONOFF** = 7 luzes + 2 tomadas
  ('note servidor Socket 1' — a tomada que ALIMENTA O SERVIDOR — e
  'Luz Oficina Socket 1', indisponível). **Sem** fan/climate/TV/
  cortina — o domínio `switch` já era a fronteira certa (o
  ha_light_control da 1.8.1 já aceitava switch; faltava vocabulário).

### Implementação

- **Action renomeada**: `ha_light_control` → `ha_device_control`
  (mesmas camadas: gate de papel + alvo específico obrigatório +
  confirmação de 2 passos TTL 120s; sem comando em lote).
- **Vocabulário novo** (comando): tomada(s), soquete(s), socket,
  dispositivo(s), aparelho, desconecta/desconecte/desplug,
  conecta/plug — tudo cai no controle com gate + confirmação.
- **Leitura de tomadas**: 'quais tomadas estão ligadas' → ha_lights.
- **Resolução de alvo**: stopwords cobrem tomada/soquete/socket —
  'desliga a tomada do servidor' → switch.note_servidor_socket_1.
- **Mensagens honestas**: 'Qual luz ou tomada?' e 'luzes e tomadas é
  só o dono' (formatter generalizado).

### Teste do teste (mutações, roteiro efêmero)

- **4/4 mutações detectadas e revertidas**: (M1) peek não acha a
  intenção pendente → confirmação nunca executa; (M2) ramo de negação
  do gate removido → negado cairia no LLM; (M3) vocabulário de tomada
  removido; (M4) TTL 120s → 1h. O roteiro (tools/actions/
  mutacoes_lar.py, efêmero) foi removido antes do commit.
- Nota: 1ª rodada teve M2 mal desenhada (injetava 'role' nos params —
  o gate é por papel no Registry, não por param) e PASSOU; redesenhada
  para remover o ramo de negação do orchestrator → pega.

### Validação e bump 1.9.0 (MINOR)

- Suíte: **2007 passed, 16 skipped** (+4 em TestControleTomadas,
  incluindo a tomada do servidor). mqtt test_start_stop_thread flaky
  no run completo — passa isolado e por classe (precedente 09-21).
- Checklist completo: .env, capabilities, pubspec **1.9.0+2022**,
  **_APP_VERSION_CODE=2022**, site 2×, CHANGELOG [1.9.0],
  README_VERSAO §1.9.0. APK rebuildado (aapt2 versionCode='2022';
  full sha256 10ea1e29…; arm64 479b0684…; anteriores em
  backups/apk-v1.8.1+2021-20260929/).
- Commit: `4bf239d` feat(iot,intents): controle do lar expandido a
  tomadas (v1.9.0) — 10 arquivos +270/−63; HEAD == origin/master.

### Deploy e prova viva 6/6 (PID 958615, NRestarts=0, restart 10:18:41)

1. `/app/version` → {1.9.0, code 2022, sha256 == binário}.
2. **Leitura**: 'quais tomadas estão ligadas' → fastpath:ha_lights
   (lista real: só a tomada do servidor estava off, Luz Cozinha on —
   o dono tinha acendido pelo app na prova de ~09:4x).
3. **Comando com apelido**: 'liga o soquete da oficina' → 💡 Confirmar
   ligar 'Luz Oficina Socket 1' (agora: unavailable) — resolução de
   nome funcionou; a indisponibilidade do HA aparece honesta.
4. **Gate de papel na tomada do servidor**: user → 🔒 negação
   determinística sem LLM (a 2 entradas [NICKY][CRIT] no journal são o
   LOG dessa negação — não é erro).
5. **Admin na mesma tomada** → 💡 'Confirmar: desligar note servidor
   Socket 1 (agora: off)?' — o 'sim' NÃO foi executado pela prova
   (derrubaria o próprio od-core); confirmação expira sozinha em 120s.
6. **Ciclo real de luz** (regressão do padrão): liga Luz Cozinha +
   'sim' → ✅ on; desliga + 'sim' → ✅ off — casa de volta a 0 acesas.

/health 200; journal 0 Traceback/ERROR. Pendente: instalar o APK
1.9.0+2022 no celular pela auto-atualização (2022 > 2021).

## 10. Prova no celular: auto-atualização para o 1.9.1+2023 (~13:0x–13:1x)

Pedido do dono: "Confirme no journal o rastro da auto-atualização do
celular para o 1.9.1+2023 e feche o ponto" (~13:07, após 'leia iniciar').

### Rastro no journal (PID 966981, desde o deploy 11:17:51)

- **13:00:31** — `Dispositivo registrado para push | token=d8Xhaf…crcY |
  platform=android`: o app foi aberto no celular (bootstrap de push; o log
  dispara a cada abertura, core/push.py).
- **13:03:13** — `Action executed | action=ha_lights` (4,4ms) para alex —
  leitura do lar já na versão nova.
- **13:04:28** — `Action executed | action=cpu_temp` (2,1ms).
- **13:05:04** — `Message processed | route=llm | llm=gemma-local` (21,6s).
- **0 Traceback/ERROR/CRIT** no período inteiro; NRestarts=0.
- `/app/version` no ar: {1.9.1, code 2023, sha256 49dbba94… == binário}.

### Limitação honesta do rastro

Por design (v1.7.0), `GET /app/version` e o download `/site/…apk` são
SILENCIOSOS — o download/instalação não deixam log no servidor. O rastro
de 13:00–13:05 (abertura + uso imediato sem novo login: token de sessão
persiste na reinstalação) é CONSISTENTE com o fluxo de auto-atualização;
a versão instalada foi CONFIRMADA PELO DONO no app: **"Está na 1.9.1"**.

### Estado final

- **PONTO FECHADO** — auto-atualização 1.9.0+2022 → 1.9.1+2023 operou no
  celular; app operando fim a fim (push + leitura do lar + temperatura +
  conversa LLM) sem erro no servidor.
- Sem pendência de APK; nota menor herdada: CHANGELOG [1.7.0]
  desordenada — reordenar numa sessão futura, se o dono quiser.

## 11. Verificação geral para fechar o dia (~13:1x–13:2x)

Pedido do dono: "Rodar a verificação geral do sistema para fechar o dia
(od-core, supervision, Funnel, banco, journal)".

### Serviços

- **od-core** active, PID 966981 (v1.9.1), desde 11:17:51, NRestarts=0.
- **od-llm** active · **omega-drakon** (user, bot @Nexus_Nicky_bot) active
  desde 22/09 · **od-control-bridge** (system, odrunner) active desde
  25/09, :8765 escutando.
- Portas: 8000 REST · 8001 WS · 1883 Mosquitto · 5432 Postgres · 8765
  Bridge — todas escutando.

### API

- `/health` com chave → ok/up, **9/9 checks up** (orchestrator, llm,
  audit, metrics, database, homeassistant, mqtt, loops, perception).
- `/supervision` → up, **restarts 0**, degraded [].

### Funnel (prova pública)

- `tailscale funnel status`: **Funnel on** — `/` → 127.0.0.1:8000 e
  `/ws` → 127.0.0.1:8001.
- De fora: `/health` 401 em 0,048s · `/ws` 426 em 0,034s ·
  `/app/version` {1.9.1, code 2023, sha256 == binário}.

### Banco (PostgreSQL, via camada do projeto)

- users 2 · sessions 28 (25 válidas) · conversation_messages 432 (alex
  350) · telegram_links 1 · llm_cache 50 → **45** após a poda.
- `/health` database up pós-poda; journal pós-poda 0 erros.

### Journal do dia

- 6 linhas [NICKY][CRIT] — TODAS negação de segurança do gate
  (allowed=False, denied_by=permission, role=user) das provas de 09:29,
  09:59 e 10:19. Falso positivo conhecido; **0 Traceback/ERROR reais**.

### Poda do cache: 5 entradas pré-guarda (autorizada pelo dono)

- Achado: dry_run do `/admin/cache/prune` → 5 candidatas
  "confirmação/execução do lar (estado de conversa)" — resíduo do PRÓPRIO
  dia (cacheadas entre ~09:36 e ~11:17, ANTES do deploy 1.9.1; a guarda
  nova impede entrada nova, mas as velhas continuam servíveis — incluir
  a 'Luzes Acessas' do BUG-B).
- Snapshot de rollback: `backups/cache-lar-pre-guarda-20260929.json`
  (5 entradas completas do Postgres, sha256 57103775466364b2…).
- Poda real → **removidas 5**; prova pós: dry_run varridas 0,
  candidatas 0. `/health` ok; 0 erros no journal. Nada reiniciado.

### Estado final do dia

- **DIA FECHADO — sistema verde.** v1.9.1 no ar e confirmada no celular
  (§10); cache 100% saudável e sem resíduo pré-guarda; HEAD f352f2e ==
  origin/master. Nada pendente.
