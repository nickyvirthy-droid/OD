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
