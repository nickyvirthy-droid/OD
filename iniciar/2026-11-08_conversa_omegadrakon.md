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
