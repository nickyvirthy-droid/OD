# Queda de energia — religar sozinho e avisar no Telegram

**Máquina:** Nicky (Dell OptiPlex 3040, BIOS 1.20.1, `nicky-server`).
**Estado em 21/11/2026:** o ajuste de BIOS **ainda não está confirmado**; o
aviso de boot no Telegram está implementado (ver §2).

## 1. Religar sozinho (BIOS AC Recovery) — passo físico

O ajuste **não pode ser feito por software neste modelo**. Tentativas feitas
em 21/11:

- `modprobe dell-wmi-sysman` → `No such device`. O kernel só expõe atributos
  de BIOS (`/sys/class/firmware-attributes`) em máquinas **WMI-ACPI**, e o
  OptiPlex 3040 é anterior a essa geração.
- Dell Command | Configure (`cctk --acpower=on`) depende do mesmo WMI-ACPI;
  sem ele não enxerga `--acpower`.
- Não existe variável de firmware/efivars para "AC Recovery" neste Dell.

Então é preciso alguém na frente da máquina:

1. Ligar/reiniciar o Nicky e apertar **F2** na tela da Dell até abrir o
   **BIOS Setup**.
2. Ir em **Power Management** → **AC Recovery**.
3. Escolher **Power On** (não `Power Off`, não `Last State`).
   - `Power On`: sempre liga quando a tomada volta — o que queremos.
   - `Last State`: só religa se estava ligado quando caiu; se a queda
     aconteceu durante um desligamento, fica desligado.
4. **Apply** / **Exit** (F10) e confirmar a gravação.
5. Teste real: com o servidor ocioso, cortar a energia na tomada/breaker por
   ~30 s e devolver. Ele deve começar a ligar sozinho, sem apertar botão.
   (Com nobreak, o teste é tirar a saída do nobreak, não a tomada da parede.)
6. Depois do boot, conferir a mensagem no Telegram (§2).

## 2. Avisar no Telegram quando voltar de uma queda

Implementado em `core/queda_energia.py` + `integrations/notifier.py`.

O alerta de boot que já existia (`restart`, um disparo por boot) agora
distingue queda de reinício comum:

- olha o journal do **boot anterior**: desligamento limpo termina com
  `Journal stopped`; queda/travamento/reset não deixa esse registro;
- só considera "queda" se o boot atual tem **menos de 30 min** — um
  `systemctl restart od-core` dias depois não repete o aviso;
- a mensagem informa quanto tempo o servidor ficou fora, calculado entre a
  última linha do boot anterior e o início do boot atual;
- sem journal legível, o alerta volta ao texto antigo ("Sistema foi
  reiniciado") em vez de inventar causa.

Exemplo de mensagem após uma queda de 1 h:

> Sistema voltou após queda de energia — ficou fora cerca de 1 h. O
> desligamento anterior não foi registrado (energia cortada, travamento ou
> reset).

O envio usa o sink de Telegram do notificador (bot de monitoramento,
`OD_TELEGRAM_MONITOR_*`), o mesmo dos outros alertas do sistema. Se o
`od-core` não subir (por exemplo, AC Recovery desligado), não há alerta —
por isso o passo do BIOS é o que garante o retorno.

## 3. Conferir depois

```bash
# o journal do boot anterior terminou limpo?
journalctl -b -1 -n 3 --no-pager
# quanto tempo esta máquina está no ar?
cat /proc/uptime
# unidades no ar
systemctl --user is-active od-core
```
