# Conversa OmegaDrakon — 2026-10-09

## 1. Retomada — "leia iniciar" (~11:0x)

- Checkpoint de 08/10 lido (v1.21.0+2048 no ar, PID 877441).
- **Lote órfão encontrado:** o canal de desenvolvimento (▶ Ativar) rodou
  às 10:31 com a ideia do dono do `txt.txt` — "ler os arquivos do Legado
  (`home/Alex/Legado`) + trocar o ícone do APP para o padrão Omega
  Drakon". A sessão CLI **falhou no relatório** (Freebuff exit=1 ·
  OpenCode estourou 600s · Kilo "Model not found" →
  `todas_as_clis_falharam` 10:41), **mas o trabalho foi feito** — o
  processo do OpenCode sobreviveu ao timeout e completou tudo: ícones,
  bump, docs e APKs publicados às 10:48.

## 2. O que o lote entregou (validado por mim)

- **Ícone Android novo (5 densidades)** — `ic_launcher.png` gerado do
  logo oficial `Logo da Omega Drakon.png` (1024×1024) de
  `/home/alex/Legado/OMEGA_DRAKON/01_NUCLEO_DA_MARCA/Simbolos_Oficiais/`
  via ImageMagick (48/72/96/144/192, RGBA). Ícone conferido visualmente:
  dragão metálico + "OMEGA DRAKON — SISTEMAS VIVOS E AUTÔNOMOS".
- **Bump PATCH 1.21.0 → 1.21.1+2049** completo no checklist:
  `.env` · capabilities fallback · `pubspec` · `_APP_VERSION_CODE=2049` ·
  `site 2x` · `CHANGELOG [1.21.1]` · `README_VERSAO §1.21.1`.

## 3. Bug crítico pegue na validação: arm64 com versionCode 4049

- O build feito pela CLI **não usou a flag
  `-Pforce-version-code-ignoring-abi=true`** do `app/build_apk.sh` → o
  APK arm64 saiu com `versionCode='4049'` (2049 + 2000 do split por
  ABI). Se o celular instalasse, entraria na linhagem 4xxx e a
  **auto-atualização morreria** (próximo 2050 < 4049 = downgrade
  recusado, "pacote inválido" — mesma classe do bug de 27/09).
- **Correção:** rebuild com `./app/build_apk.sh` (canônico) → os dois
  APKs com `versionCode='2049'` exato (aapt2). Full
  `13142a39…`(54.442.616 B) · arm64 `ca799123…` (19.468.879 B).

## 4. Validação

- Suíte do servidor: **2390 passed, 16 skipped** (86,9s).
- `flutter analyze`: **0 issues** · `flutter test`: **134 passed**.
- Árvore commitada e publicada: **a93d042** (HEAD == origin/master).

## 5. Deploy 1.21.1 (autorizado pelo dono via ask_user)

- Restart **11:18:59**, **PID 954778, NRestarts=0**.
- **Prova viva 6/6:** `/app/version` {1.21.1, 2049, sha256
  `13142a39…` == binário de site/} · `/capabilities` 1.21.1 · `/health`
  up · `/supervision` up restarts 0 degraded [] · WS :8001 → 426 ·
  journal **0 erros**.
- **Prova de fora (Funnel):** `/app/version` 200 com 1.21.1/2049 ·
  `/health` 401 em 0,034s · `/ws` 426 · download parcial do APK arm64 →
  HTTP 206 com magic bytes `PK` (ZIP íntegro).

## 6. Aviso ao dono (regra 14 — txt.txt)

- O caminho que ele escreveu, `home/Alex/Legado`, **não existe como
  escrito** (Linux é case-sensitive): o real é **`/home/alex/Legado`**
  (alex minúsculo). O trabalho usou o caminho real; aviso colocado no
  `txt.txt`.
- Pendência do dono: abrir o app para a auto-atualização
  1.21.0+2048 → 1.21.1+2049 (2049 > 2048) e conferir o ícone novo.

## 7. Re-verificação — "leia iniciar" de novo (~14:29)

- Sistema 100%: od-core **active, PID 954778, NRestarts=0** (desde
  11:18:59) · `/app/version` {1.21.1, 2049, sha256 `13142a39…` ==
  binário de site/} · `/health` up · HEAD **1768b00 == origin/master**.
- `txt.txt` sem mensagem nova do dono (resposta do sistema das 11:2x
  intacta). Único resíduo da árvore: backup untracked já conhecido
  (`backups/llm-cache-fakes-20261008-055830.json`).
- Nada pendente do sistema — sessão segue aguardando o próximo pedido
  do dono.

## 8. Re-verificação — "leia iniciar" de novo (~14:32)

- Nenhuma mudança desde a §7: od-core **active, PID 954778, NRestarts=0**
  (desde 11:18:59, ~3h11) · `/health` ok · `/app/version`
  {1.21.1, 2049, sha256 `13142a39…` == binário de site/} · HEAD
  **486f367 == origin/master**.
- `txt.txt` sem mensagem nova do dono (resposta 11:2x intacta); único
  resíduo da árvore segue sendo o backup untracked já conhecido.
- Sessão segue aguardando o próximo pedido do dono (pendência dele:
  abrir o app p/ auto-atualização 2048 → 2049 e conferir o ícone).

## 9. Lote do ecossistema — site institucional + fim do dragão (~15:0x)

- Dono confirmou o app ("está excelente") e pediu: (1) o **logo** no
  lugar do **dragão (🐉)** das mensagens e do site; (2) **refazer o
  site** com base no Legado — o antigo falava só do APP, que é uma
  parte do ecossistema; (3) Legado (`/home/alex/Legado`) vira regra;
  (4) análise profunda, didática e profissional para depois discutir
  implementação das frentes que ainda não existem.
- **Fontes consultadas:** Legado local (217 arquivos, 93 MB —
  `OMEGA_DRAKON/`, `Nicky Virthy/`, `Nicky/`, `NV/`, `Nexus/`) +
  consolidações canônicas do Google Drive (`OMEGADRAKON_SPEC.md`,
  `OMEGA_DRAKON_SOURCE_MAP.md`, `NICKY_VIRTHY_KNOWLEDGE.md`,
  `CONTROL_BRIDGE.md`). Drive não tem as raízes de projeto (só `OD` e
  `OmegaDrakon`) — o local é a fonte mais completa.
- **Entregas:** `docs/ANALISE_ECOSSISTEMA.md` (análise completa: 5
  frentes do ecossistema, linha do tempo, duplicações do Legado,
  15 divergências, próximos passos) · `site/index.html` REESCRITO como
  site institucional do ecossistema inteiro (Marca, Ecossistema,
  Sistemas, Produtos, Autenticidade, Histórico, Plêiade, Download,
  Sobre) na identidade oficial (`#0A0A0A`/`#0088FF`, Orbitron +
  Montserrat, logo real em `site/`) · fim do 🐉 em chat web, painéis,
  `/capabilities`, respostas de identidade e app · regra 16 no
  `RULES.md`.
- **Validação:** suíte do servidor **2390 passed, 16 skipped** ·
  `flutter analyze` **0 issues** · `flutter test` **134 passed** ·
  HTML validado (0 tags abertas, 0 âncoras quebradas, 0 🐉, assets OK).
- **Bump PATCH 1.21.2+2050** (checklist completo). APKs: build canônico
  `./app/build_apk.sh` → **versionCode='2050' exato** nos dois (aapt2;
  full `3ce16d5e…` 55.065.736 B · arm64 `715468d2…` 19.912.226 B).
  (Nota: os 2049 foram sobrescritos pelo build — sem backup desta vez.)

## 10. Deploy 1.21.2 — autorização permanente (~15:25)

- Dono autorizou o restart **e criou a regra 7.3**: "se estiver tudo
  verde, está sempre autorizado" — restart vira padrão quando a
  validação está verde (registro obrigatório continua).
- **Restart 15:25:13, PID 978552, NRestarts=0.** Prova viva **8/8**:
  `/app/version` {1.21.2, 2050, sha256 `3ce16d5e…` == binário} ·
  `/capabilities` 1.21.2 · 78 actions · `/health` up · `/supervision`
  restarts 0 · chat com 6 referências ao logo e **0 🐉** · journal 0
  erros. **Prova de fora (Funnel):** título novo, `/app/version`
  1.21.2/2050, 3 assets 200, 0 🐉.
- Fechamento: commit `cf36ed2` (== origin/master) · aviso no `txt.txt`
  (regra 14) · resumo no Telegram (regra 15) · regra 16 (Legado) e 7.3
  (restart verde) criadas.
- **Pendência do dono:** abrir o app (auto-atualização 2049 → 2050) e
  conferir o logo nas superfícies. **Próxima discussão:** as 15
  divergências de `docs/ANALISE_ECOSSISTEMA.md` (ID duplo,
  `/verificacao`, organização do Legado, rotação de segredos).

## 11. Item 1 da pauta — Legado organizado sem mover nada (~16:0x)

- Dono perguntou o motivo de mover e se perderia algo. Medi antes de
  responder: (1) das 8 "duplicações" suspeitas, só **2 são bit-idênticas**
  — as outras 6 são **versões diferentes** do mesmo documento (camadas de
  eras distintas); (2) 10 docs antigos citam caminhos já históricos
  (`~/nicky` etc.) e só 2 arquivos do repo citam caminhos do Legado.
- **Decisão do dono: NÃO mover, NÃO deduplicar.** Caminho adotado é puro
  aditivo: `Legado/00_MAPA_DO_LEGADO.md` (NOVO) — índice vivo vs histórico
  das 5 raízes, linha do tempo, onde vive o canônico hoje (marca, Git,
  Drive), mapa completo das duplicações (4 pares idênticos = únicos
  candidatos a remoção futura; grupos divergentes = história, não tocar),
  aviso permanente de segredos e as 4 regras de cuidado da pasta. Medição
  final incluiu ainda: `ativar venv.md` (3 versões, todas diferentes),
  `Servidor Dell(1)` e `ARCHITECTURE(1)` idênticos, prompts `NICKY_v040
  (2)`/`v070 (2)` divergentes e `regras_nexus 1` divergente.
- Regra 16 atualizada apontando o mapa como bússola do Legado.
- **Concluído sem mutação nenhuma no Legado** (só o arquivo novo). Próximo
  item da pauta: `/verificacao` (autenticidade pública).

## 12. Retomada do dono — site multipágina, segredos e o modelo da loja (~16:4x)

- **Site:** dono não achou ideal deixar tudo numa página só e quer o
  **Histórico em página própria**. ENTREGUE: `site/historico.html`
  completa (4 fases 2025→hoje com detalhe do Legado + os 4 projetos
  predecessor + fontes); `index.html` perdeu a timeline e ganhou teaser
  com link; nav e rodapé dos dois arquivos ligados.
- **Segredos:** pedido do dono — verificar se ainda funcionam; em
  produção, trocar só quando os testes finalizarem. **VERIFICADO:**
  bot antigo `@Nexus_Nicky_bot` **ATIVO** (getMe OK) e chave Gemini
  antiga **ATIVA** (HTTP 200). Rotação **adiada por decisão do dono** —
  pendência ativa na análise (item 15).
- **Item 2 — o modelo real da verificação saiu do dono:** banco de
  **todas as peças** expostas no site (loja); peças com ele = valor de
  venda; vendidas = dados do comprador; peça física leva **número de
  fabricação** (formato a decidir); a compra vem com **cartão + QR**; o
  comprador **registra no APP em seu nome** (com cadastro no sistema);
  **quem tem o QR é o dono**; ID de fabricação **pesquisável por
  qualquer um**; peças públicas (chaveiros etc.) são vendidas **sem QR**
  por não serem exclusivas. Iteração até o produto final.

## 13. Item 2 — Registro Mestre no ar (decisões a–e + etapas 1–3) (~17:0x–18:10)

**Decisões do dono (a–e), respondidas de uma vez:**
- **(a)** "id da peça deve ser pesquisável, a pessoa vai estar com a peça na
  mão e não o cartão QR, esse cartão é o de registro" → o ID vem GRAVADO na
  peça; o cartão QR é o de registro.
- **(b)** "mostra o username, não o nome real, assim todos podem saber que
  realmente tem dono e se quiserem podem conversar com ele" → consulta
  pública devolve o username; nome real nunca.
- **(c)** "quem comprar deve pedir o QR para registrar no proprio nome" →
  fluxo: venda → comprador registra → QR como prova de posse.
- **(d)** "o QR é o simbolo de propriedade, quem tem ele é o dono."
- **(e)** "siga a ordem de construção normal. primeiro banco...." → banco →
  admin → verificação → app → loja.

**Entregue (ordem normal):**
1. **Banco:** `core/registry.py` — `registry_items` (public_id canônico
   `OD-PROD-AAAA-NNNN` sequencial + `engraved_code` curto gravado, ambos
   pesquisáveis; status `estoque→vendida→registrada`, `registrada` exige
   dono; preço/notas privados).
2. **Admin:** `POST/GET /admin/registry` + `PUT /admin/registry/{id}` (só
   dono; 401/403 demais; 503 sem banco).
3. **Consulta pública:** `GET /registry/{codigo}` em `AUTH_EXEMPT_PATHS`
   (natureza de `/app/version`) — projeção sem id/price/notes, username só
   quando registrada; `runtime/launcher.build_registry(database)` liga o
   store (padrão do UserStore).
4. **Site:** `site/verificacao.html` (busca pelo ID gravado, selo
   autêntica/vendida/registrada, username do dono, aviso p/ ID
   desconhecido); home: card Verificação saiu de "Em breve" para no ar +
   link "Verificar peça" na nav.

**Validação:** suíte completa **2371 passed / 16 skipped** (98s) · flutter
analyze 0 · flutter test 134/2 · APKs rebuildados (JAVA_HOME=~/jdk,
ANDROID_HOME=~/android-sdk — flutter/java fora do PATH do shell; corrigido
com export) com **versionCode='2050' EXATO + versionName='1.22.0'** nos
dois (aapt2) — full 55.065.740 B `10d4b714…`, arm64 19.912.230 B
`3dd6574b…`. Bump MINOR 1.22.0 em todas as fontes vivas + CHANGELOG
`[1.22.0]` + README_VERSAO + divergência 13 fechada na análise.

**Deploy (regra 7.3):** commit **`5d45ada`** (push, HEAD==origin/master) →
restart **17:56:43, PID 996976, NRestarts=0**. Provas vivas:
- Local: `/app/version {1.22.0, 2050, sha 10d4b714… == binário}` ·
  `/capabilities 1.22.0 (78 actions, 42 caps)` · `/health up` ·
  `/supervision restarts 0` · `/registry/OD-PROD-2026-0001` → **404 JSON
  sem credencial** (rota pública de verdade) · `/admin/registry` 200
  `total 0` (boot log: "Registro Mestre de peças habilitado") · POST corpo
  inválido → 400 `nome_obrigatorio` · PUT inexistente → 404 · `/site`,
  `/site/verificacao.html`, `/site/historico.html` 200 · journal **0
  erros** · 0 🐉.
- Funnel: `/registry/…` → 404 JSON da API · `verificacao.html` 200 com
  título certo · `/app/version 1.22.0/2050` · 0 🐉.

**Registro:** session.json (novo lote `item_2_registro_mestre_2026_10_09` +
decisões a–e), este §13, txt.txt com bloco novo (regra 14), Telegram
(regra 15). **Registro Mestre vazio e limpo** (total 0 — nenhum item de
teste poluiu a produção; POST inválido só provou o handler).

**Próxima etapa do item 2:** fluxo do comprador no app (registro por QR no
próprio nome) + entrega do QR na compra + loja no site.

## 14. Item 2b — cadastro no painel admin + exemplos de teste (~18:2x–18:55)

**Pedido:** dono: "Ainda não tenho peça. crie um backend de cadastro para o
adm. pode cadastar alguns exeplos para teste."

**Entregue (v1.22.1):**
- **Painel `/admin` ganhou a seção "Registro Mestre (peças)"**: form de
  cadastro (nome, coleção, tipo exclusiva/pública, código gravado, preço,
  notas internas), tabela completa com status/dono/preço e ações **→ Vender**,
  **🔑 Registrar** (prompt do username — o público só vê o username) e
  **✕ Remover** (dupla confirmação).
- **API nova:** `DELETE /admin/registry/{public_id}` (só dono; 404 se não
  existe; some também da consulta pública) + `RegistryStore.delete()`.
- **Acabamento pego pela prova viva:** transições `vendida`/`registrada`
  agora carimbam `sold_at`/`registered_at` sozinhas (antes `null` no payload
  público); repetição não re-carimba (+1 teste).
- Guardas: rotas 56→57; `tests/test_registry.py` 14→18.

**Exemplos cadastrados no ar (4, todos marcados "(exemplo)"):**

| ID | Peça | Tipo | Status | Código gravado |
|---|---|---|---|---|
| OD-PROD-2026-0001 | Anel Abissal (exemplo) | exclusiva | estoque | NV-ABI-7F3A |
| OD-PROD-2026-0002 | Colar Draconis (exemplo) | exclusiva | vendida | NV-DRA-9C4E |
| OD-PROD-2026-0003 | Pendente Lumen Nox (exemplo) | exclusiva | registrada @exemplo_teste | NV-LUX-3B7D |
| OD-PROD-2026-0004 | Chaveiro OD (exemplo) | pública | estoque | NV-OD-5E8A |

**Validação:** suíte **2375 passed / 16 skipped** · flutter analyze 0 ·
flutter test 134/2 · APKs `1.22.1+2050` (aapt2: 2050 exato; full
55.065.736 B `863dc5b2…`, arm64 19.912.226 B `6d4b7a6d…`).

**Deploy (7.3):** commits `6ec8412` (painel+DELETE) e `c5a155b`
(timestamps), ambos publicados. Restarts 18:43:36 (PID 1004202) e ~18:50
(PID 1005975), NRestarts=0. **Provas:** `/app/version {1.22.1, 2050,
sha 863dc5b2… == binário}` · health ok · restarts 0 · `/admin` com a seção
(6 refs) · `/capabilities 1.22.1` · **4/4 códigos gravados consultam** (local
e Funnel) · registrada mostra `@exemplo_teste` · **preço/notas ausentes de
todo payload público** · timestamps carimbados · journal **0 erros** ·
0 🐉.

**Registro:** session.json (`item_2b_cadastro_admin_2026_10_09`), este §14,
txt.txt (regra 14) e Telegram (regra 15).

**Ajuste pronto para o dono:** os 4 exemplos são de teste e podem ser
removidos pelo botão ✕ do painel quando as peças reais chegarem.

---

## 15. Item 2c — verificação evoluída: sem hífen, foto e sala de bate-papo (~19:0x–20:10)

**Pedido do dono (txt/Telegram):** "verifica, funcionando. vamos melhorar. se
a pessoa digitar o codigo ou id sem - poderia achar mesmo assim. Uma coisa
excelente é ter a foto do produto, assim sabemos com certeza do que se trata
e outra coisa é fazer uma sala de bate-papo onde uma pessoa interesada na
peça pode conversar com o comprador e negociar a compra direta entre eles ou
simplesmente conversar e trocar ideias ou saber a qualidade do produto."

**Decisões minhas (sem interromper o dono):**
- Interlocutor da sala = quem tem a peça: estoque → dono do sistema (o
  próprio dono recebe no Telegram); registrada → @dono dela. Leitura
  pública (conversa sobre a peça, ethos do Registro Mestre); escrita só
  com conta (assina username). PM privada fica para depois, se pedir.
- Anti-spam do Telegram: 1 aviso a cada 2 min por peça; falha do Telegram
  nunca derruba o envio da mensagem (já gravada).
- Foto chega em base64 JSON e é reduzida no navegador (canvas ≤900 px) —
  o servidor fica "burro de propósito"; mime jpeg/png/webp, ≤6 MB.

**Entregas:**
1. `normalize_code()` no `RegistryStore.get()`: match exato primeiro
   (índice UNIQUE), varredura normalizada como fallback. `odprod20260001`,
   `nvabi7f3a`, com espaços (a rota agora faz `unquote` — o `%20` quebrava)
   → 200.
2. Foto: coluna `photo` (migrada via `_ensure_column` — `create_table` é
   IF NOT EXISTS), `POST /admin/registry/{id}/photo`,
   `GET /registry/{id}/photo` pública (cache 1h), payload com URL (nunca o
   nome do arquivo), remover peça apaga o arquivo.
3. Sala: tabela `registry_chat`, `GET /registry/{id}/chat?since=` pública,
   `POST` com conta (401 sem), verificação pública com sala + polling 4 s +
   link de login para anônimo.
4. Moderação + aviso: `DELETE /admin/registry/{id}/chat/{msg_id}` + botões
   💬/✕ no painel; `build_chat_notify()` costura o sink async do Telegram no
   loop principal via `run_coroutine_threadsafe`.

**Bump:** MINOR 1.23.0 (features) · versionCode 2050 mantido (app sem
mudança de código) · APKs rebuildados com versionName 1.23.0 (full
55.065.740 B `9d784cb1…`, arm64 19.912.230 B `798bafa8…`).

**Validação:** suíte **2389 pass / 16 skip** · rotas 57→62 ·
`test_registry.py` 18→33 · JS dos 3 HTMLs com `node --check` OK ·
deploy local + Funnel: busca sem hífen 200 (3 formatos), foto 0001
200 image/jpeg 23253 B, 0004 sem foto → null/404, chat ponta a ponta
(conta 201/username assina · sem conta 401 · moderação 200 · leitura
pública 2 mensagens), preço/notas ausentes (grep 0), `/app/version`
{1.23.0, 2050, sha == binário}, journal **0 erros**, 0 🐉.

**Demonstração viva na peça 0003:** conta temporária `fulano_teste`
perguntou sobre o pendente, o dono respondeu (username `alex` pela API
key), um "spam" de teste foi apagado pela moderação e a conta temporária
foi removida — a sala ficou com as 2 mensagens da conversa de exemplo.
Fotos-placeholder (ImageMagick) subidas nas peças 0001 e 0002; 0003 e
0004 ficaram sem foto de propósito (dois casos na demonstração).

**Registro:** session.json (`item_2c_melhorias_verificacao_2026_10_09`),
este §15, txt.txt (regra 14), Telegram (regra 15), commit `717131d`.

**Próximo do dono:** exercitar verificação/painel, cadastrar as peças
reais e remover os 4 exemplos com ✕. Etapa 4 do item 2 (QR + app + loja)
aguarda ordem.

---

## 16. Bug do dono — app sem versão no "Verificar Atualização" (~20:1x–20:45)

**Pedido do dono (Telegram):** "APP não mostra a versão atual ao clicar
Verificar Atualização."

**Diagnóstico (duas causas somadas):**
1. A mensagem do resultado (`_checkUpdate`) não trazia versão nenhuma:
   só "Você já está na versão mais recente." ou "Nova versão X
   disponível" — sem a instalada nem a publicada, sem números.
2. `versionCode` parado em **2050** desde a 1.22.0 (bumps com "app sem
   mudança de código"): o updater compara `versionCode >
   localVersionCode` e o celular do dono (2050, desde a 1.22.1) recebia
   "já atualizado" para SEMPRE — mesmo o servidor anunciando 1.23.0.

**Correções (v1.23.1+2051, commit `c939799`):**
- `odUpdateStatusMessage()` em `od_updater.dart` — função pura e
  testável; SEMPRE mostra publicada × instalada com os versionCodes
  (novo/estável/falha). Card: "App instalado: vX.Y.Z (código N)";
  `_checkUpdate` recarrega PackageInfo no clique.
- versionCode **2050 → 2051** + regra nova no checklist §5.3 da
  VERSIONAMENTO: TODO APK publicado leva versionCode novo, mesmo sem
  mudança de código — versionCode igual deixa o updater mudo.
- Banner do main.dart (aviso ao abrir) passa a funcionar de novo
  automaticamente (usa o mesmo `isNewer`).

**Guarda que funcionou:** a `test_version_policy.py` barrou DE PRIMEIRA
um `v1.24.0` hipotético que eu tinha escrito no meu próprio teste
("código rotulado com versão MAIOR que a vigente") — cenário reescrito
com versões reais (1.23.1 × 1.23.0).

**Validação:** suíte servidor **2389 pass / 16 skip** · policy 9 pass ·
app analyze 0 · app **138 pass / 2 skip** (+4 testes da mensagem) ·
aapt2 dos dois APKs `versionCode='2051' versionName='1.23.1'` ·
`/app/version` (local + Funnel) {1.23.1, 2051, sha == binário
`14c25317…`} · APK baixável pela Funnel (206) · badge 3× v1.23.1 ·
simulação fiel da lógica do app com o payload real (celular 2050 →
"Nova versão v1.23.1 (código 2051) (52 MB) disponível — você está na
v1.22.1 (código 2050).") · journal **0 erros**, 0 🐉.

**Registro:** session.json (`item_2d_app_versao_bug_2026_10_09`), este
§16, txt.txt (regra 14), Telegram (regra 15), commit `c939799`.

**Para o dono:** abrir o app → banner "Nova versão 1.23.1 disponível" →
Atualizar (baixa, confere o hash e instala). Depois, em Configurações →
Atualização, o "Verificar atualização" mostra as duas versões.
