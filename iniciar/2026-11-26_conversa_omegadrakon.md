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
