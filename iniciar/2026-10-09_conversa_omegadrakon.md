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
