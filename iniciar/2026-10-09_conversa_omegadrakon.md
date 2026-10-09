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
