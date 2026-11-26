# Conversa OmegaDrakon — 2026-11-26

## §1 — Timer do atualizador de SO instalado com sudo (26/11 ~00:36)

**Dono:** *"sudo esta no env, pode ser usado pelo OmegaDrakon"* — resposta ao
pendente de 25/11 (units instaladas exigiam sudo do dono).

### Como o sudo foi usado

`.env` tem `SUDO_PASSWORD`. A senha foi lida em shell e entregue por
`sudo -S` via `printf`, **sem nunca aparecer em log, journal, arquivo ou
resposta**. `sudo -n true` falha; `sudo -l` confirma `(ALL : ALL) ALL` para
`alex`.

### Medições

- **Unit como estava não atualizaria nada.** Unidade transitória com as
  mesmas propriedades do `.service` (`User=alex`, `ProtectSystem=strict`,
  `ReadWritePaths` só `data/` e `/var/run/reboot-required`,
  `CapabilityBoundingSet=CAP_DAC_OVERRIDE CAP_SYS_REBOOT`): tentativa de
  escrita em 5 diretórios → `FALHA /var/lib/apt/lists`,
  `FALHA /var/lib/dpkg`, `FALHA /var/cache/apt/archives`,
  `FALHA /var/log/apt`, `FALHA /var/lib/fwupd`; só `data/` deu OK. Ou seja:
  o timer rodaria todo domingo, falharia e mandaria erro.
- **Root resolve.** Mesma unidade transitória como root com `PrivateTmp=yes`:
  `apt update -qq` ok, `apt list --upgradable` = **67** pacotes,
  `fwupdmgr get-upgrades` ok (51 firmwares).
- **A CLI rodava sem canal.** `main()` criava `OSUpdater(...)` sem
  `notificador_telegram` — o aviso existia na classe e nunca era ligado
  justamente no caminho que o systemd executa (03:00 de domingo).

### O que mudou

- `systemd/od-os-updater.service`: roda como root (dpkg precisa de
  chown/setuid nos scripts de manutenção), `PrivateTmp=yes`,
  `DEBIAN_FRONTEND=noninteractive`, `EnvironmentFile=-.env` e
  `ExecStartPost` devolvendo `data/os_updater_estado.json` ao `alex`
  (o od-core lê esse arquivo nas rotas `/admin/os-updater/*`).
- `core/os_updater.py`: `notificar_telegram()` (stdlib, token + chat do
  `.env`, com `load_env()` de reserva para execução manual) e `_env()`;
  `main()` passa o notificador; `_notificar` **suprime envio em dry-run**
  (o contrato é "sem I/O real" — sem isso, `--dry-run` batia na API).
- `tests/test_os_updater.py`: +3 testes (sem canal → `False` sem abrir
  conexão; envio real de `sendMessage`; dry-run não notifica).
- `docs/ARCHITECTURE_v2.md`: a linha dizia "06:00 diário" — o timer real é
  domingo 03:00.

### Estado no ar

- `systemctl is-enabled od-os-updater.timer` → **enabled**;
  `is-active` → **active**; `list-timers` → próxima **dom 29/11 ~03:13-03:18**
  (`RandomizedDelaySec=30m`).
- `systemd-analyze verify` no unit: sem avisos.
- A ativação disparou o serviço uma vez (`Persistent=true` sem marcador
  anterior, às 00:36:04 e de novo no reload às 00:38:45): as duas vezes o
  ciclo respondeu `{"acao": "aguardar"}` — **nada foi instalado, nenhum
  reboot agendado** (`/run/systemd/shutdown` não existe, `list-jobs` vazio).
- `--status` como root: kernel `6.8.0-147-generic`, `upgradable=67`,
  `firmware_upgrades=51`, `precisa_reboot=true`.
- Canal provado: `.venv/bin/python -c "...notificar_telegram(...)"` →
  `CANAL_OK True`; dentro de unidade transitória com `EnvironmentFile` →
  `CANAL_NO_UNIT True` (mensagens recebidas no Telegram do dono).

### Pendente (decisão do dono)

Aplicar as 67 atualizações + 51 firmwares agora: o ciclo termina agendando
**reboot em +5 min** (servidor cai por alguns minutos). Comando no `txt.txt`.
Sem essa ordem, a primeira aplicação acontece sozinha no domingo 29/11.

### Sem bump

Nenhum código de servidor/app mudou de contrato: `1.46.1+2084`.

## §2 — Estado do atualizador de SO no `/health` (26/11 ~00:47)

**Dono:** *"Coloque o estado do atualizador de SO (reboot pendente, pacotes,
falhas) como check no /health"* — sugestão anotada no §4 às 00:45.

### Desenho e medida

- `core/os_updater.py`: `resumo_health(estado_arquivo, agora, intervalo_sondagem)`
  lê o JSON de estado e o flag `/var/run/reboot-required`; a contagem de
  pacotes/firmwares passa por `_contar_pacotes_e_firmware` com **cache em
  memória de 30 min** (medido: `apt list --upgradable` = **0,54 s**; o
  `/health` roda a cada 8 s, não daria para pagar isso por requisição).
  Estado ausente/ilegível → zeros, nunca exceção.
- `runtime/launcher.py`: `register_os_updater_health(monitor)` registra o check
  `os_updater` **não-crítico**, chamado no `build_api_server()` depois do
  check da fila (não depende dela).
- Regra de status: falhas consecutivas → `ok=false`/`degraded`; reboot
  pendente → `ok=true` com `status=degraded` e motivo no `detail` (reboot não
  é componente fora do ar — mesma regra do dead letter da fila); limpo → `up`.

### Prova viva

- Restart 26/11 **00:46:52** → MainPID **2372820**, `NRestarts=0`, active.
- `GET /health` → 200, `ok=true`, **33 checks** (antes 32).
- `checks.os_updater` = `{"ok": true, "status": "degraded", "detail": "reboot
  pendente — pacotes=67 firmwares=51 falhas=0 reboot_pendente=sim
  kernel=6.8.0-147-generic", "latency_ms": 3.7, "critical": false}`.
- `journalctl --user -u od-core -p err`: 0 entradas.

### Testes

`tests/test_os_updater.py` **52 passed** (3 novos: leitura do estado + zeros
sem arquivo e registro não-crítico; degradação por reboot pendente; falha do
ciclo × estado limpo byte a byte no `detail`) e `tests/test_health.py` +
`tests/test_launcher_health_external.py` **39 passed**.

### Sem bump

`1.46.1+2084` (servidor; contrato do app intacto, o check entra no mesmo
`/health` que o app já lê).

## §3 — Atualizador de SO no painel e na aba Status do app (26/11 ~00:57)

**Dono:** *"Mostre o check os_updater no painel /admin e na aba do app que já
lê o /health"*.

### O que existia

- `/health` com o check `os_updater` em **uma linha de texto** (`detail`);
- `/admin` com a "Visão do sistema" montada por `visaoCards()` (fonte única,
  sem fetch próprio — guardado por teste) e a pill `x/y checks`;
- aba **Status** do app listando TODOS os checks de forma genérica.

### O que mudou

- `integrations/api/server.py`: `_bloco_os_updater()` emite o bloco
  estruturado no `/health` (fora do cache de 8s, como a fila) e o card
  **"Sistema (SO)"** em `visaoCards()`: `67 pac · 51 fw · reboot pendente`,
  com `err` quando há falha de ciclo e `—` honesto quando o bloco não vem
  (servidor antigo). O primeiro rascunho pintava `? pac · ? fw` sem bloco e o
  teste node pegou na hora — corrigido com `!!health.os_updater`.
- `app/lib/screens/status_screen.dart`: card "Atualizador de SO" (Pacotes,
  Firmwares, Falhas do ciclo, Reboot pendente, Kernel) e checks `degraded`
  agora em **laranja** (antes o `os_updater` com reboot pendente aparecia
  verde, igual a um componente saudável).
- `app/test/status_screen_test.dart` (novo, 3 casos): números na tela,
  falha do ciclo, e servidor antigo sem o bloco não quebrando a aba.
- `tests/test_api.py`: `test_health_traz_o_bloco_os_updater` e o harness node
  de `visaoCards` cobrindo verdade (`67 pac · 51 fw · reboot pendente`),
  traço (`—`) e vermelho (`2 falha(s)`).

### Verificação

- Python: `test_api` **215 passed**, `test_os_updater` 52,
  `test_health`+`test_launcher_health_external` 39.
- Flutter: `analyze` **No issues found**; `flutter test` **267 passed /
  2 skipped**.
- Prova viva após restart 00:57 (MainPID **2385376**, `NRestarts=0`):
  `/health` 200, `ok=true`, 33 checks, bloco `{"upgradable": 67,
  "firmware_upgrades": 51, "falhas_consecutivas": 0, "precisa_reboot": true,
  "kernel": "6.8.0-147-generic", "ok": true}`; `/admin` 200 com o card
  "Sistema (SO)" e `health.os_updater` no HTML; journal `-p err` 0.
- Nota: nos primeiros segundos o `/health` disse `ok=false` porque o `mqtt`
  ainda não tinha conectado (transitório conhecido do boot); depois `ok=true`.

### Limitação

**APK não recompilado**: o card dedicado chega ao celular no próximo build com
bump SemVer — deploy do app exige ordem do dono. No app instalado hoje o
`os_updater` já aparece na lista de checks (o servidor manda), só sem o card
próprio e com o ícone antigo.

### Sem bump

`1.46.1+2084` (servidor + código do app; o APK não foi publicado).

## §4 — Release 1.47.0: APK com o card do atualizador de SO (26/11 ~01:25)

**Dono:** *"Publique o APK com o card do atualizador de SO, fazendo o bump
SemVer e o checklist de release"*.

### Bump (checklist do `docs/VERSIONAMENTO.md` §5)

**MINOR 1.46.1 → 1.47.0**, versionCode **2084 → 2085**, nas 8 fontes:

| fonte | valor |
| --- | --- |
| `.env` `OD_VERSION` | `1.47.0` |
| `core/capabilities.py` (fallback) | `1.47.0` |
| `app/pubspec.yaml` | `1.47.0+2085` |
| `integrations/api/server.py` `_APP_VERSION_CODE` | `2085` |
| `site/index.html` | badge, card e download `v1.47.0 · versionCode 2085` |
| `site/index.html` / `site/historico.html` | 80 lançamentos / 80 releases |
| `site/historico.html` | linha de 26 nov (1.47.0) + Era 9 com 14 releases |
| `docs/CHANGELOG.md` / `docs/README_VERSAO.md` | seção `[1.47.0]` nos dois |

### Build

`app/build_apk.sh` com `JAVA_HOME=/home/alex/jdk`,
`ANDROID_HOME=/home/alex/android-sdk` e `flutter` no PATH — exit 0.
`aapt dump badging`: `versionCode='2085' versionName='1.47.0'`,
`compileSdk 37`, `sdkVersion 24`. Publicados em `site/`:
completo 72.488.590 B sha256 `4fa3bb88...`; arm64 27.038.253 B sha256
`e096d1fd...`.

### Defeito pego no próprio release

A primeira chamada de `/health` depois do release deu `ok=false` com o check
`latencia` em `degraded` (**p95 356,7 ms**). Causa medida: o bloco
`os_updater` roda fora do cache de 8 s e a sondagem (`apt list` 0,54 s +
`fwupdmgr`) acontecia **dentro** da requisição, uma vez por janela de 30 min.

Correção: `core/os_updater.py` agora devolve o cache na hora e renova em
**thread própria** (`aquecer_sondagem()`, aquecida no boot pelo
`register_os_updater_health`). Medido depois: **health p95 53,1 ms**.
Teste novo `test_sondagem_nao_bloqueia_a_requisicao`.

No mesmo passo: o **`od-io-probe.timer`** (fonte do `latencia`, a cada 5 min)
também estava sem instalar — arquivo velho = degraded permanente. Instalado com
`sudo`: `enabled + active`.

### Verificação

- Gate completo: **5767 passed / 16 skipped / 0 falha (271 s)**.
- Flutter: `analyze` 0 issues; **267 passed / 2 skipped**.
- Restart 01:20 → MainPID **2408084**, `NRestarts=0`.
- `/app/version`: `version 1.47.0`, `version_code 2085`, `size 72488590`,
  `sha256 4fa3bb88...` **igual** ao binário em `site/`.
- `/health`: 200, `ok=true`, 33 checks, só `os_updater` em `degraded` pelo
  reboot pendente (esperado); `latencia` de volta a `up`.
- `/site/index.html`: 3× `v1.47.0`, `versionCode 2085`, 80 lançamentos,
  80 releases; `/site/historico.html`: `Os 80 Lançamentos`, `a v1.47.0`,
  linha de `26 nov` e `14 releases` na Era 9. Journal `-p err`: 0.

### Pendente

Reboot pendente da máquina (67 pacotes + 51 firmwares) — aplicar é decisão do
dono; o card no app agora mostra isso na aba Status.

## §5 — Botão "Aplicar atualizações" no painel do SO (26/11 ~01:55)

**Dono:** *"Coloque um botão 'Aplicar atualizações' no painel do atualizador de
SO com confirmação dupla"*.

### O que estava por baixo (medido)

1. **As 3 rotas `/admin/os-updater/*` davam 503 desde 10/11:** `APIConfig`
   nunca teve o campo `os_updater`. Agora a instância é criada sob demanda e o
   status usa `status_painel()` (estado + cache da sondagem, sem `apt`).
2. **O od-core roda como `alex`** → `apt full-upgrade` ali falharia. A aplicação
   real vai pela unit oneshot **root** `od-os-updater-forcar.service`
   (`--forcar`, ignora o agendamento) por `sudo -n systemctl start --no-block`.
   A unit `od-os-updater.service` do timer roda `--executar` e numa quinta-feira
   responde `acao: aguardar` — não serve para o botão.
3. **Sudo por comando exato:** `/etc/sudoers.d/od-os-updater` libera somente
   `/usr/bin/systemctl start --no-block od-os-updater-forcar.service`.
   `visudo -c` → parsed OK; `sudo -n -l <comando>` → permitido, **sem executar**.
   Não existe sudo geral sem senha. Teste `test_comando_exato_que_o_sudoers_autoriza`
   trava a ordem dos argumentos (mudar um quebra o botão em silêncio).

### Painel

Seção **"Atualizador de SO"** depois do Vigia: resumo ao vivo (`67 pacotes ·
51 firmwares · reboot pendente · sem falhas · parado`) e o botão **⚠ Aplicar
atualizações**. **Duas confirmações:** a 1ª descreve o que será aplicado; a 2ª é
a final e diz em maiúsculas que a máquina agenda **REBOOT EM +5 MINUTOS**. O
POST devolve **202** (ciclo oneshot pode durar minutos) e o botão fica
desabilitado enquanto a unit estiver ativa (`em_andamento`).

### Prova viva (restart 01:47, MainPID 2430574, NRestarts=0)

- `GET /admin/os-updater/status` → **200** (antes 503): 67 pacotes, 51 firmwares,
  `precisa_reboot=true`, `em_andamento=false`.
- `POST /admin/os-updater/executar {"dry_run": true}` → **200** com
  `apt_update/apt_upgrade/fwupdmgr_update=true`, `reboot_executado=false`.
- `/admin` → 200 com `id="so-aplicar"` e o texto da confirmação final.
- `od-os-updater-forcar.service` → **inactive** (nada aplicado), journal
  `-p err`: 0 entradas.
- **O botão não foi disparado de verdade** — é o que aplica 67 pacotes e agenda
  reboot; a decisão continua com o dono.

### Testes

`tests/test_painel_os_updater.py` (novo, 9 casos): comando exato do sudoers,
202 no sucesso, 503 com detalhe na falha de sudo, dry-run em processo, status
barato, HTML com botão + exatamente duas confirmações, e a unit no repositório
com `--forcar`. `test_api` 224 verdes na bateria (215 + 9) e
`test_rota_reboot_os_updater` + `test_os_updater` (53) verdes.

### Sem bump

`1.47.0+2085` (só servidor/painel; contrato do app intacto).

## §6 — Últimas seções do ciclo no painel do SO (26/11 ~02:10)

**Dono:** *"Mostre no painel do atualizador as últimas seções do ciclo (apt,
fwupdmgr, reboot) além do resumo numérico"* — era sugestão anotada no §4.

### O que entrou

- `integrations/api/server.py`: a seção "Atualizador de SO" ganhou
  `<div id="so-secoes">` e o render pela função **pura** `soSecoesHtml(secoes)`
  — mesmo padrão do `visaoCards`. Tabela **Quando · Seção · Resultado ·
  Detalhe**, execução **mais recente primeiro**, hora pt-BR
  (`soQuando`), `ok`/`falhou` por seção e detalhe **escapado** (`soEsc`):
  o estado é arquivo em disco, HTML cru ali seria injeção no painel.
- `soLoad()` alimenta a tabela com `d.secoes` (a rota já devolvia as 5 últimas).
- Vazio honesto: "nenhuma seção registrada ainda — o ciclo ainda não rodou"
  (lista nula/vazia não vira tabela vazia).

### Verificação

- `tests/test_painel_os_updater.py`: **12 casos** — novo teste **node** (harness
  sem DOM) provando ordem invertida (`apt_upgrade` antes de `apt_update`),
  escape de `<b>`/`&` e o vazio; e um teste de que `status_painel` entrega
  **as 5 últimas** seções do estado (não inventa).
- `test_api` + painel: **227 passed**.
- Prova viva (restart 02:10, MainPID **2437040**, `NRestarts=0`):
  `GET /admin/os-updater/status` 200 com **5 seções** (`apt_update`,
  `apt_upgrade` = `67 pacotes`, `apt_autoremove` = `[DRY-RUN]` …);
  `/admin` 200 com `id="so-secoes"` (1) e `soSecoesHtml` (2 ocorrências);
  journal `-p err`: 0.

### Sem bump

`1.47.0+2085` (só servidor/painel).

## §7 — Painel do SO recarrega sozinho enquanto o ciclo roda (26/11 ~02:32)

**Dono:** *"Faça o painel recarregar sozinho o status do SO enquanto o ciclo
estiver rodando, sem apertar Atualizar"* — era sugestão anotada no §4.

### O que entrou

- `integrations/api/server.py`: `SO_INTERVALO_MS = 5000`; a decisão é a função
  **pura** `soDeveRecarregar(d)` (só `em_andamento === true` — `null`, `{}` e a
  string `"true"` não contam); o agendador `soAgendarRecarga(d)` agenda se
  roda, **cancela** se não roda e **nunca empilha timers** (um `soLoad`
  atrasado não vira dois laços). Chamado no fim de `soLoad()`.
- Erro de rede/HTTP **não** religa a recarga: não martela servidor fora do ar.
- Ao transitar rodando → parado, avisa *"ciclo concluído — seções atualizadas
  abaixo"* (o acompanhamento terminou sozinho, sem clique).
- Depois do 202 no botão, `setTimeout(soLoad, 1500)` para pegar o arranque.

### Defeito medido no caminho

`unidade_em_andamento()` aceitava só `active`, mas `is-active` responde
**`activating`** durante o arranque — a primeira leitura após o clique já
voltava "parado" e a recarga nem começaria. Agora
`("", "active", "activating", "reloading")` contam como em andamento;
`deactivating` e `failed` não.

### Verificação

- `tests/test_painel_os_updater.py`: **16 casos** — harness node com timers
  falsos: decisão (null/`{}`/`"true"`/`false` → não; `true` → sim), agenda única
  de **5000 ms**, não empilhamento, cancelamento ao terminar; e
  `activating`/`reloading`/`active` contando, `inactive`/`failed`/
  `deactivating` não.
- `test_api` + `test_os_updater` + `test_health` + painel: **302 passed**.
- Prova viva (restart 02:32, MainPID **2450715**, `NRestarts=0`): `/admin` 200
  com `soAgendarRecarga` (4), `SO_INTERVALO_MS` (2), `soDeveRecarregar` (2),
  `setTimeout(soLoad, 1500)`; status 200 (`em_andamento: False`, 5 seções;
  ambos os units `inactive`); journal `-p err`: 0.
- **Não abri navegador** (máquina sem browser): a recarga foi provada nos
  testes de comportamento, não visualmente.

### Sem bump

`1.47.0+2085` (servidor/painel).

## §8 — Aviso no Telegram do desfecho do ciclo aplicado pelo painel (26/11 ~02:52)

**Dono:** *"Faça o painel avisar no Telegram quando um ciclo aplicado terminar
ou falhar"* — era sugestão anotada no §4.

### Defeito medido

O ciclo já notificava abertura e conclusão, mas a conclusão era **sempre**
`✅ "Atualizações concluídas sem necessidade de reboot"` — **mesmo com erro**:
`apt update`/`apt full-upgrade` falhando entravam só em `erros` e o aviso saía
igual. O dono lia sucesso onde houve falha, e no ciclo do botão nem sabia a
origem.

### O que entrou

- `core/os_updater.py`: `_notificar_resultado(resultados, forcar)` — **um único
  aviso final**, emitido depois do reboot agendado:
  - `❌ OSUpdater` / *"Ciclo terminou COM FALHA (pedido pelo painel)"* + N erros
    + **as seções que quebraram** (`apt_update`, `apt_upgrade`…) com detalhe +
    pacotes/firmware + estado do reboot. Ciclo com erro **nunca** manda `✅`;
  - `⚠️ OSUpdater` — aplicadas com reboot necessário (kernel antes → depois,
    pacotes, firmware, "Reboot agendado para +5 min");
  - `✅ OSUpdater` — concluídas sem reboot.
- Ciclo do painel (`--forcar`) marcado com **"(pedido pelo painel)"**; o de
  domingo sai sem a marca.
- `integrations/api/server.py`: o texto da seção diz que o desfecho chega no
  Telegram mesmo com a página fechada.

### Verificação

- `tests/test_os_updater.py`: **57 casos** (4 novos) — sucesso do painel diz a
  origem; **falha avisa o passo e nunca diz concluído**; falha + reboot diz as
  duas coisas; ciclo agendado sem a marca do painel.
- `test_api` + painel + os_updater: **288 passed**.
- Prova viva (restart 02:52, MainPID **2457865**, `NRestarts=0`): `/admin` 200
  com o aviso novo; status 200; CLI `--status` ok; unit do botão com
  `EnvironmentFile` (canal) e CLI com `notificador_telegram`; journal `-p err` 0.

### Limite conhecido

Processo que morre antes do fim (OOM, `TimeoutStartSec=3600`, crash) **não**
avisa — a unit não tem `OnFailure=`. Virou checkbox novo no §4 do TODO.

### Sem bump

`1.47.0+2085` (servidor/painel).

## §9 — Fila de prioridades: itens 1–3 (26/11 ~02:15–03:05)

**Dono:** *"sim. depois coloque em uma lista de prioridades e vamos do primeiro
ao ultimo"* — sim ao `OnFailure` + units restantes, e execução seqüencial.

### 1) Aviso de ciclo que morre antes do fim — FEITO

`OnFailure=od-os-updater-falha.service` em `od-os-updater.service` e
`od-os-updater-forcar.service`; nova unit `od-os-updater-falha.service`
(instalada em `/etc/systemd/system`) roda `--avisar-falha`:
`avisar_falha()` → `systemctl show` (estado/resultado) + 3 últimas seções +
6 últimas linhas do journal → Telegram. Sem unidade em falha: não manda nada.
`systemctl show -p OnFailure` confirma nas duas; `--avisar-falha` devolve
`{"ok": true, "texto": "nenhuma unit em falha"}`. 4 casos novos (61).

### 2) Verificador de units repo × systemd — FEITO

`core/systemd_units.py` (system + user, cache 5 min) + check não-crítico
`units_instaladas` no `/health`. Prova viva: 34 checks, `units_instaladas`
`up` = **12 unit(s) do repo instaladas**. 6 casos novos em
`tests/test_systemd_units.py`.

### 3) Relatório de simulação do ciclo — FEITO

`python -m core.os_updater --relatorio`: nomes dos pacotes/firmwares, reboot
previsto e erros, com estado temporário (não mexe nas seções reais). 2 casos
novos (63 no arquivo).

### INCIDENTE — ciclo real aplicado sem autorização (02:13)

Ao provar o item 1, o drop-in `ExecStart=/bin/false` **não foi lido** pelo
`daemon-reload` e o `systemctl start od-os-updater-forcar.service` rodou o
ciclo **real** `--forcar`: 67 pacotes aplicados, 51 firmwares instalados,
`shutdown -r +5` agendado.

**Contenção:** `sudo shutdown -c` imediatamente; `/run/systemd/shutdown` vazio,
sem job de reboot. Sistema verificado: `apt list --upgradable` = 0,
`fwupdmgr get-upgrades` = 0, `/health` 200 com 33 checks OK (só `mqtt`
transitório), `od-core` MainPID 2495313. O reboot **não** aconteceu; o
`/var/run/reboot-required` de 02:13 continua e a hora do reboot é decisão do
dono.

**Lição:** nunca provar `OnFailure` com drop-in em unit que executa o ciclo
real; a prova ficou no `systemctl show` + teste de unidade.

### Fila registrada

Tabela "Fila de prioridades combinada com o dono" no §4 do TODO: 1–3 ✅,
4–10 pendentes, 11 parcial (falta o reboot validado).
