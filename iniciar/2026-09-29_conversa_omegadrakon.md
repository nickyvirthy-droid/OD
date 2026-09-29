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
