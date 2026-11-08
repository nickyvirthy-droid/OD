# 2026-11-08 — conversa OmegaDrakon

## §1 — HD Arquivos inacessível depois da troca de porta USB (~11:50–12:10)

**Pedido do dono:** *"troquei a hd de porta e não esta mais acessivel"* — e, na
sequência, *"o root esta no cofre"* (autorização para usar o `SUDO_PASSWORD`
do `.env` e resolver sem esperar comando manual).

### Medição (antes)

| Fato | Evidência |
|---|---|
| HD plugada e reconhecida | `lsblk`: `sdc1` 931,5G, ext4, label **Arquivos**, UUID `81225f7d-…` |
| Ponto de montagem SEM mount | `/dev/sdc1` sem `MOUNTPOINT`; `systemctl status mnt-Arquivos.mount` → **inactive (dead)** |
| Device node recriado em 06/11 19:25 | `ls -l /dev/sdc1` → 06/11 19:25 (hora em que a HD voltou em outra porta) |
| fstab correto (não é o problema) | `UUID=81225f7d-… /mnt/Arquivos ext4 defaults,noatime,nofail 0 2` |
| Ponto vazio (nada escondido) | `ls -A /mnt/Arquivos` → vazio |
| `/health` | `degraded`, 25 checks, só **`hd_arquivos`**: *"HD desconectada de /mnt/Arquivos"* |
| Último snapshot no alvo | `snapshot_od-2026-11-06_0354` (10,7 GB, 21 rodadas, 0 falhas) — desde então o loop pulava com `alvo_ausente` |
| Outra HD intacta | `hd_midias` (`sdb1` em `/home/alex/dados`), snapshot de 08/11 03:50 ok |

**Causa raiz:** a troca de porta USB derrubou o mount do `sdc1`. O `fstab` usa
UUID (porta não importa), mas **nada remonta sozinho em hotplug** — a unidade
`mnt-Arquivos.mount` ficou `dead` e o serviço de snapshot seguiu pulando com
motivo `alvo_ausente`, exatamente o comportamento desenhado no `core/hd_backup.py`
(`nofail` + log honesto + catch-up no tick seguinte).

### Por que não resolvi no primeiro instante

`alex` tem sudo **com** senha (NOPASSWD só `mariadb`/`nexus-router`); sem tty o
`sudo -S` e o `udisksctl` (+ polkit) recusaram (`NotAuthorizedCanObtain`).
Com a ordem do dono ("o root está no cofre"), usei o `SUDO_PASSWORD` do `.env`
lendo em memória, sem imprimir/ecoar/logar o valor em nenhum passo.

### Ação e prova viva

```
sudo systemctl start mnt-Arquivos.mount   # rc=0
```

- `mnt-Arquivos.mount` → **active (mounted)** desde 08/11 **11:59:39**.
- `df -h /mnt/Arquivos` → 916G, **763G usados, 107G livres (88%)**.
- Conteúdo preservado: `backup_od_2026-09-05`, `Imagens`, `lost+found`,
  `od_snapshots/` (snapshots até `snapshot_od-2026-11-06_0354`), `Temp`.
- Escrita testada (`touch` + `rm`) → OK.
- **Catch-up rodou sozinho** no tick das 12:06: `snapshot_od-2026-11-08_1206`,
  **10.530.977.256 bytes**, `falhas=0`, sem erro; no disco 9,9G (hardlinks).
- `/health` → **up, 25/25**, `hd_arquivos: ok (snapshot_od-2026-11-08_1206,
  9,81 GB, há 0.0 h)`.

### Pendência/ideia (não executada)

O problema volta se o dono mover o cabo de novo (o mount não é automático em
hotplug). Caminho de causa raiz, se ele quiser: `x-systemd.automount` (e
`x-systemd.device-timeout`) no fstab, ou regra udev de montagem — mudança em
`/etc/fstab` com root, feita fora do horário de uso da HD.

**Nada de código alterado; nenhum segredo impresso.**

## §2 — Montagem automática ao replugar (pedido seguinte, ~12:20–12:48)

**Pedido do dono:** *"Deixe o /mnt/Arquivos montando sozinho quando a HD for
replugada em outra porta"*.

### Solução escolhida

Regra udev no host, casada por **UUID** (não por porta) — o
`/etc/fstab` não foi tocado:

`/etc/udev/rules.d/99-mnt-arquivos.rules`

```
# HD "Arquivos" (ext4, UUID 81225f7d-9eff-4d9f-a51b-5ad8d0311ee7):
# monta /mnt/Arquivos sozinha quando a particao aparece, em qualquer porta USB.
# Ordem 99: depois do 60-persistent-storage, que e quem preenche ID_FS_UUID.
# Sem isso, trocar a HD de porta a deixa sem montagem ate alguem rodar
# "systemctl start mnt-Arquivos.mount" (o fstab ja esta correto, por UUID).
ACTION=="add", SUBSYSTEM=="block", ENV{ID_FS_UUID}=="81225f7d-9eff-4d9f-a51b-5ad8d0311ee7", RUN+="/usr/bin/systemctl start --no-block mnt-Arquivos.mount"
```

### Duas tentativas que falharam (e por quê)

1. **`ENV{SYSTEMD_WANTS}+="mnt-Arquivos.mount"` (arquivo `60-mnt-arquivos.rules`)** —
   regra não casava: `60-mnt-…` ordena **antes** de `60-persistent-storage.rules`,
   que é quem preenche `ID_FS_UUID` no evento. Além disso, o teste com evento
   reemitido (`udevadm trigger --action=add`) não acorda o systemd porque o unit
   `dev-…device` já está ativo — ele só reavalia a transição inactive→active,
   que só acontece num plug real.
2. **`RUN+="systemctl start"` ainda na ordem 60** — mesma causa (UUID ausente na
   hora da avaliação). Reordenar para **99** resolveu.

### Prova viva (teste repetido com a regra final)

```
sudo systemctl stop mnt-Arquivos.mount      # desmonta
sudo udevadm trigger --action=add --sysname-match=sdc1   # reemite o "plug"
→ /mnt/Arquivos montado de novo em ~2 s (duas execuções seguidas)
```

- `99-mnt-arquivos.rules` é o único arquivo em `/etc/udev/rules.d/` além do LVM.
- `udevadm test /sys/class/block/sdc1` lista o `RUN` da regra (casa).
- Após os testes: `mnt-Arquivos.mount` **active**, `df` 763G/107G, `/health`
  **up 25/25** (`hd_arquivos` ok, snapshot de 12:06), od-core sem restart.

### Limites

- Dispara quando a partição **aparece** (plug/boot). Se a HD já estiver plugada
  e o mount cair por outro motivo (erro de I/O, `umount` manual), continua
  precisando de `systemctl start` — a regra não fica vigiando.
- Sem mudança de código no repo; o `txt.txt` não foi usado.

## §3 — Regra udev no repo + HD Mídia (pedidos seguintes, ~13:00–13:20)

**Pedidos:** *"Guarde a regra udev no repo com script de instalação, para
sobreviver a uma reinstalação do servidor"* e *"Faça a HD Mídia também voltar
sozinha ao ser replugada"*.

- `runtime/udev/99-omega-hds.rules` — as duas regras (Arquivos `81225f7d…`
  → `mnt-Arquivos.mount`; Mídia `f2c818bc…` → `home-alex-dados.mount`), com o
  porquê da ordem 99 e do `RUN+=` no cabeçalho.
- `runtime/udev/install.sh` — `sudo bash runtime/udev/install.sh`: instala,
  recarrega o udev e confere cada UUID com `udevadm test`.

**Dois defeitos pegos na execução, ambos corrigidos no arquivo do repo:**

1. `udevadm test | grep -q` sob `set -o pipefail` morre por **SIGPIPE** e
   dava "a regra NÃO casou" com a regra certa. Agora a saída é capturada numa
   variável e o `grep` lê dali.
2. A conferência mostrava o disco/mount via `findmnt --source` do symlink
   (que não casa); passou a usar `readlink -f`.

**Prova viva da Mídia:** `systemctl stop home-alex-dados.mount` +
`udevadm trigger --action=add --sysname-match=sdb1` → **remontou sozinha em
~2 s**; `df` 786G livres, `/mnt/Arquivos` intacto (763G/107G).
Instalado no host como `/etc/udev/rules.d/99-omega-hds.rules` (a versão
antiga `99-mnt-arquivos.rules` foi removida para não duplicar a regra).

## §4 — `/health`: plugada sem mount ≠ desconectada (~13:20–13:35)

**Pedido:** *"Faça o /health diferenciar disco plugado sem mount de HD
realmente desconectada"*.

Em `core/hd_backup.py`: `FSTAB_PADRAO`, `dispositivo_do_alvo()` (lê o `What=`
do fstab do ponto, desescapando `\040`), `_dispositivo_presente_padrao()`
(UUID/LABEL/caminho do device existe?) e `unit_do_mount()`. O
`HDBackupService` ganhou `presente_fn=` injetável (mesmo molde do
`montado_fn`), então o teste não toca no host.

Mensagens agora:
- disco plugado e sem mount → *"HD plugada mas SEM montagem em /mnt/Arquivos
  (mount caiu; `systemctl start mnt-Arquivos.mount` resolve — o fstab está
  certo)"*;
- device ausente → a antiga *"HD desconectada"*;
- ponto fora do fstab → *"não dá para saber se a HD está plugada"*.

**Verificação:** `pytest tests/test_hd_backup.py -q` → **38 passed** (3 novos).
Checagem viva do parser: `/mnt/Arquivos` → `UUID=81225f7d…`/plugado=True;
`/home/alex/dados` → `UUID=f2c818bc…`/plugado=True.

**PENDENTE:** o `od-core` **não foi reiniciado** (regra 7.1: deploy/restart
exige ordem do dono). Até o restart, o `/health` em execução continua com a
mensagem antiga.

## §5 — Wi-Fi USB não responde (~13:00–13:15)

**Pedido:** *"plug wifi usb tambem parece não responder"*.

O que o host mostra:

| Fato | Evidência |
|---|---|
| O dongle **configurado** não está presente | `/etc/netplan/50-cloud-init.yaml` define `wlx000f0037acf0` com IP `.250`, SSID `Drakon` e rota default métrica 600 (reserva); nenhum USB com esse MAC desde 01/10 — `systemd` fica "Expecting device …wlx000f0037acf0" no boot |
| O dongle **plugado** é outro | `lsusb` → `148f:7601 Ralink MT7601U`, interface `wlx00e2b0101555`; fora do netplan, por isso `DOWN` |
| Driver carrega, mas com aviso | `mt7601u` registra o adaptador e o kernel emite `WARNING … lin2dBd` (calibração TSSI) no boot; `usb 1-5: reset` no mesmo instante |
| Não vê nenhuma rede | `wpa_supplicant` + `wpa_cli scan` por 15 s → **0 redes** (nem a `Drakon`) |
| Sem erro de energia/porta | nenhum `over-current`; topologia USB normal (porta 1-5 livre para ele) |

Leitura: o adaptador que o netplan espera está **desplugado (ou morto)** e o
que está na máquina é o segundo dongle — sem configuração e sem ouvir beacons.
A causa de "não ouvir" pode ser o adaptador (aviso de calibração) **ou** o
roteador estar só em 5 GHz (o MT7601U é 2,4 GHz) — não dá para separar sem
mexer no roteador ou trocar o dongle.

Estado: **aguardando decisão do dono** (recolocar o dongle `.250` ou eu
configurar o MT7601U no netplan usando a senha do `Drakon` já gravada no
50-cloud-init, rota métrica 600 como reserva). Nada foi alterado em rede; o
teste de scan foi desfeito (interface de volta a `DOWN`, `wpa_supplicant` de
teste encerrado).
