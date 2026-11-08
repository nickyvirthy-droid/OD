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

## §6 — Reinício do `od-core` com o `/health` novo (13:50–14:00)

**Pedido:** *"Reinicie o od-core para o novo /health entrar em vigor"* — ordem
explícita de deploy (regra 7.1).

- Gate antes do restart: `pytest tests/ -q` → **4181 passed, 16 skipped** (188 s).
- `systemctl --user restart od-core` → pid **2460220**.
- Depois: `/health` → **25/25 `up`**; `journalctl --user -u od-core` sem `[ERROR]`.
- A mensagem nova de HD plugada sem mount passou a valer (fim do "PENDENTE" do §4).

## §7 — MT7601U como reserva de Wi-Fi e conferência do 2,4 GHz (13:00–14:10)

**Pedidos:** *"Configure o MT7601U como reserva Wi-Fi no netplan"* e
*"Verifique no roteador se o 2,4 GHz está desligado"*.

### 2,4 GHz no roteador: **ligado**

Archer C6, UI aberta com `tools/monitor/vigia_rich.py` (Playwright), rota
`#networkMap`: **17 clientes** — 1 por cabo, **13 em 2,4 GHz**, 2 em 5 GHz.
WAN PPPoE, IP de internet `100.64.165.225` (CGNAT). Ou seja: a banda está no ar;
o dongle é que não a escuta.

### Netplan: arquivo novo, `50-cloud-init.yaml` intocado

Decisão: **não** editar `50-cloud-init.yaml` (o cloud-init pode regenerá-lo e
derrubar o boot com a rede quebrada). A reserva virou
`/etc/netplan/61-wifi-reserva.yaml` (root:root 600):

```yaml
network:
  version: 2
  wifis:
    wlx00e2b0101555:            # MT7601U 148f:7601
      dhcp4: false
      addresses: [192.168.0.251/24]
      access-points:
        "Drakon": {password: <PSK copiada do 50-cloud-init>}
      routes:
        - to: default
          via: 192.168.0.1
          metric: 700
```

IP `.251` de propósito: o `.250` é do dongle ausente e voltaria a colidir.
Métrica **700**: com 600 o netplan recusa o conjunto
(`Conflicting default route declarations for IPv4 (table: main, metric: 600)`)
porque o Wi-Fi principal já usa 600.

### O que passou e o que não passou

| Passo | Resultado |
|---|---|
| `netplan generate` (com o 50 restaurado) | **rc=0** — sintaxe e conjunto válidos |
| `netplan apply` | **rc≠0**: `A dependency job for netplan-wpa-wlx000f0037acf0.service failed` |
| Config do `.251` gerada | **sim**: `/run/systemd/network/10-netplan-wlx00e2b0101555.network` |
| `wpa_supplicant` do MT7601U | **rodando** com a config nova (`scanning`) |
| Associação / IP | **não**: `no-carrier (configuring)`, `ip -br addr` sem endereço |
| Escuta de beacons | `wpa_cli scan` OK e, após 10 s, **0 redes** (nem a `Drakon`) |
| Rede cabeada | intacta: `enp2s0` `.205`, default `metric 100`, `/health` 25/25 |

O erro do `apply` **não é desta troca**: é a unit do dongle `.250`, que o netplan
ainda gera a partir do `50-cloud-init.yaml` desde que ele sumiu (01/10). Todo
`netplan apply` falha assim desde então — inclusive antes de eu escrever o 61.
A config nova entra mesmo com o rc≠0 (prova: os arquivos em `/run/systemd/network`
e o `wpa_supplicant` do `.251` em execução).

### Veredito honesto

A reserva está **configurada**, mas o MT7601U **não ouve nenhum AP** — com o
2,4 GHz ligado e 13 clientes nele. Somado ao `WARNING … lin2dBd` (calibração
TSSI) e ao `usb 1-5: reset` no boot, a leitura é **adaptador surdo**, não senha
nem banda. A reserva passa a valer no dia em que houver um rádio que escute: o
dongle `.250` de volta (plug-and-play, o 50 já o configura) ou um adaptador novo
(aí muda só o nome da interface no 61).

### Segurança e limpeza

- Backup: `/etc/netplan/50-cloud-init.yaml.bak-2026-11-08`; `diff` confirma que o
  arquivo em uso está **idêntico** ao backup.
- Temporários com a PSK (`/tmp/61-wifi-reserva.yaml`, `/tmp/50-cloud-init.yaml`)
  e os scripts de roteador (`/tmp/wifi_router*.py`) **apagados**.

## §8 — Dongle trocado: a reserva Wi-Fi entrou no ar (14:20–14:35)

**Pedido:** *"troquei o dongle"*. Medição antes de tocar em nada:

| Fato | Evidência |
|---|---|
| O USB plugado agora é o **`.250`** | `lsusb` 148f:7601, interface `wlx000f0037acf0` (00:0f:00:37:ac:f0); kernel: `mt7601u … renamed from wlan0` às 14:21:05 |
| O dongle anterior (00:e2:b0:10:15:55) saiu | interface `wlx00e2b0101555` não existe mais |
| O `61-wifi-reserva.yaml` virou config órfã | apontava para o MAC que saiu — geraria a mesma falha de dependência |

Ação: `61-wifi-reserva.yaml` → `61-wifi-reserva.yaml.bak-2026-11-08` (netplan só lê `*.yaml`),
`netplan generate` rc=0 e **`netplan apply` rc=0** — o erro de unit que existia desde
01/10 desapareceu junto com a volta do dispositivo esperado.

### Prova viva

| Item | Resultado |
|---|---|
| Associação | `wpa_state=COMPLETED`, `ssid=Drakon`, `key_mgmt=WPA2-PSK` |
| IP | `192.168.0.250/24` (o mesmo que o `50-cloud-init.yaml` já definia) |
| Tráfego pela reserva | `ping -I wlx000f0037acf0 192.168.0.1` → **3/3, 0% perda**, 1,0 ms |
| Sinal | link 65 Mbps, **frequência 2437 (canal 6)** |
| Rotas | cabo `metric 100` (principal) e Wi-Fi `metric 600` (reserva), como projetado |
| `/health` | **25/25 `up`**; cabeada segue `.205`; Tailscale ok |

### Sobre o dongle que saiu (resposta ao dono)

Ele **não** estava configurado no netplan quando eu o diagnostiquei (só passou a
estar às 13:51, no `61`), mas **depois de configurado ele continuou vendo 0 redes**
— dois scans, 15 s e 10 s forçados, com a interface UP e o `wpa_supplicant` rodando.
Hoje o AP está no **canal 6**, que qualquer MT7601U enxerga, o que derruba a
hipótese de "banda/região". O adaptador atual é **o mesmo modelo** (148f:7601), no
mesmo driver e no mesmo caminho de config, e associou de primeira: o que mudou
foi o hardware, não a configuração.

Ressalva honesta: eu **preferi** a opção de recolocar o `.250` porque ela era
plug-and-play (o `50-cloud-init` já o configurava) — foi conveniência minha, não
medição. O que sustentava o diagnóstico era o scan vazio, e isso não mudou com
a config no lugar.

## §9 — Config de Wi-Fi de reserva guardada no repo, com instalador (14:40–15:00)

**Pedido:** *"Guarde a configuração de Wi-Fi no repo com instalador, para a reserva
sobreviver a uma reinstalação do servidor"*.

**Problema real:** a reserva só existia no `/etc/netplan/50-cloud-init.yaml`, que
o cloud-init gera. Numa reinstalação (ou regeração) o host volta a ter apenas o
cabo — foi exatamente o buraco entre 01/10 e 08/11.

| Peça | O que faz |
|---|---|
| `runtime/netplan/70-wifi-reserva.yaml` | `Drakon` em `wlx000f0037acf0`, `192.168.0.250/24`, rota default métrica 600; senha como **marcador**, nunca no git |
| `runtime/netplan/install.sh` | deriva a interface do MAC, resolve a senha (`--psk` > `$OD_WIFI_PSK` > a que já está no host), instala `0600 root`, roda `netplan generate` e confere o `.network`; `--mac` para dongle trocado, `--aplicar` para ativar |

### Medições que definiram o desenho

- `netplan generate` com a **mesma interface em dois arquivos** → **rc=0**, um único
  `10-netplan-wlx000f0037acf0.network` mesclado. Por isso o 70 pode conviver com o
  50 sem quebrar nada.
- `match: {macaddress: …}` em wifi → **erro**: `networkd backend does not support
  wifi with match:, only by interface name`. O nome da interface vem do MAC
  (`wlx` + MAC sem `:`), e o instalador aceita `--mac` para recalcular.
- Permissão: `netplan generate` reclama de arquivo "too open" — o instalador grava
  `0600 root` (mesmo padrão dos outros arquivos do host).

### Prova (sandbox com cópia dos netplan reais)

| Caso | Resultado |
|---|---|
| Instalação normal | rc=0; `Address=192.168.0.250/24 Metric=600`; arquivo `600 root`; marcador substituído |
| Sem senha disponível | **rc=1** e nada instalado (só o aviso de como passar `--psk`) |
| `--mac 00:11:22:33:44:55` | interface `wlx001122334455` |
| Senha com espaço, `&` e aspas | YAML válido — a substituição é em python/json, não em `sed` (sed trataria `&` como sintaxe) |

Host **não** foi alterado: segue com o `50-cloud-init.yaml` ativo e `netplan generate`
rc=0; o 70 entra no dia da reinstalação (ou por vontade do dono, com `--aplicar`).

### Defeito meu, pego no teste

A primeira versão do instalador, com `--prefixo` (modo sandbox), gravava em
`/etc/netplan` **de verdade** — instalou o 70 no host durante o teste. Corrigido:
`DESTINO` passou a ser `$PREFIXO/etc/netplan/…`; o arquivo instalado por engano foi
removido e o `netplan generate` do host rodou rc=0 depois, só com os arquivos
originais.

## §10 — O 70-wifi-reserva instalado no host e a reserva de pé (15:05–15:15)

**Pedido:** *"Instale o 70-wifi-reserva no host com o instalador e confirme que a
reserva continua de pé"*.

`sudo bash runtime/netplan/install.sh --aplicar` → **rc=0**:

```
✅ /etc/netplan/70-wifi-reserva.yaml instalado (interface wlx000f0037acf0, SSID Drakon)
• netplan generate OK: Address=192.168.0.250/24 Metric=600
• atenção: wlx000f0037acf0 também está definida em 50-cloud-init.yaml — o netplan mescla
```

A senha foi resolvida do próprio host (nenhuma linha com ela na saída).

### Estado depois do `apply`

| Item | Resultado |
|---|---|
| Arquivo no host | `600 root:root /etc/netplan/70-wifi-reserva.yaml` |
| Interface | `wlx000f0037acf0 UP 192.168.0.250/24` (+ IPv6) |
| Associação | `wpa_state=COMPLETED`, `ssid=Drakon`, `ip_address=192.168.0.250` |
| Tráfego | `ping -I wlx000f0037acf0 192.168.0.1` → **3/3, 0% perda** (~3,7 ms) |
| Rotas | `default … enp2s0 metric 100` (principal) + `default … wlx… metric 600` (reserva) |
| Mesclagem | `.network` gerado tem **um** bloco `Address`/`Metric`; `wpa-wlx000f0037acf0.conf` tem **um** `network={…}` — as duas definições (50 e 70) não duplicaram nada |
| Resto | `enp2s0 .205`, `/health` **25/25**, Tailscale `nicky-server` ok |

**Limite registrado:** a reserva agora depende de o `70` e o `50` continuarem com
os mesmos dados (IP, métrica e senha). Se o cloud-init regerar o 50 com valores
diferentes, o netplan mescla e a cópia do repo (70) é a que deve mandar — o
instalador avisa sobre a coexistência, e a saída é remover o bloco de wifi do 50
ou rodar o instalador de novo para alinhar.
