# Conversa 2026-10-21 — OmegaDrakon

## §1 — Retomada de rotina ("leia iniciar", 21/10 ~14:20): sistema verde em v1.44.0+2080

Retomada pela regra 3 — li `iniciar/session.json`, `iniciar/RULES.md` e o
fim da transcrição anterior (`2026-10-20_conversa_omegadrakon.md` §18–§21).
Último ponto registrado: **20/10 ~21:40**, fecho da **v1.44.0+2080 —
Câmera QR no app** (commit `9322352`, v2 da Etapa 4 do Registro Mestre,
fila do TODO zerada).

Verificação feita com a fonte viva (não com o registro):

| Frente | Medição |
|---|---|
| Serviço | `od-core` active desde **20/10 20:39:29** (17h40), MainPID 968535, **NRestarts=0**, journal **2 `[ERROR]`** desde o boot (ambos 21/10 03:01/03:02 — DNS do Telegram durante blip de rede, ver abaixo) |
| Saúde | `/health` (com `X-API-Key`) **ok=true, 25 checks, nenhum fora** |
| Versão | `/app/version` **1.44.0 / 2080**, sha256 `aeb8566b…`, APK publicado 72.028.650 B (subiu de 55 MB — dependência da câmera) |
| Git | árvore **limpa**, HEAD `9322352` == `origin/master` (0 à frente / 0 atrás) |
| Backups | diário `od-2026-10-21_0310.tar.gz` (03:10) · **off-site do diário enviado 03:40** (1 parte, sha `a5c52232…`) · capturas semanal segue `16_1434` (próximo snapshot domingo 04:00) · disco **66%** (76G livres) |
| Canais do dono | `txt.txt` **sem mensagem nova** (nossa entrega da câmera QR, 20/10 ~21:40) · `analise/` **inalterado** (2 capturas do Sistema Órion de 16/10 sem instrução + `fotos-adicionais/` com as 4) |
| Ferramentas | `nomad_tools` **9/9, nenhuma fora** · notifier `ticks=1064, errors=2, problems=24, alerts_emitted=6, alerts_blocked=13` |

Fatos novos transitórios (todos dentro do esperado, sem ação):

- **Blip de rede na madrugada (03:01–03:02):** os 2 `[ERROR]` do boot são
  `Sink falhou | Telegram API indisponível: Temporary failure in name
  resolution` — o mesmo blip de DNS registrado nos boots anteriores.
  Na mesma janela: 1 alerta `router:down` (ping ao 192.168.0.1 falhou),
  1 `health:degraded` (1 check fora = backup, durante o próprio blip) e
  **100 dos WARNs "Transporte indisponível"** do polling do bot de chat
  (bot.py:500 — `TransportError` transitório). Tudo se recuperou sozinho.
- `router:down` adicional em 20/10 21:46, 05:26 e 06:37 — mesmo blip
  intermitente do gateway registrado desde 15/10; o roteador responde
  agora.
- WARNs "Transporte indisponível" fora do pico: ~1/hora entre 10h e 14h
  (mesma ordem de grandeza dos 18 das 20h39→meia-noite de ontem; são
  1.142 em setembro — intermitência antiga de rede/long-polling, não
  regressão). `getMe` dos 3 bots **vivos agora** (@Nicky_Virthy_bot OK).

Estado: **SISTEMA ESTÁVEL E NO AR — v1.44.0+2080**, fila do TODO zerada,
nada em andamento; aguardando ordem do dono (próximas registradas:
exemplo exato do tema §3.8, off-site de capturas segue o ciclo semanal).

## §2 — Reboot do roteador tirado da janela dos backups (21/10 ~14:30–15:50)

**Pedido do dono:** *"o problema do roteador vamos resolver agora. ele está
configurado para reiniciar às 3:00, justamente no horário dos backups. o
sistema pode pegar o controle dele, te passo a senha pelo txt. existe um
aplicativo que faz isso, tether, mas não sei você consegue clonar ou
controlar ele"* — e, quando apontei que o `txt.txt` não tinha linha nova
dele, ele corrigiu: *"a senha já está lá, deveria ter lido de primeira"*
razão: li o arquivo na reverificação e tratei só a nossa entrega como
conteúdo.

**Apuração (antes de tocar no roteador):**

- **Fingerprint:** 192.168.0.1 responde interface **TP-Link** (UI `tpos`,
  firmware `c80_1.14.0`, `/cgi-bin/luci` = 403 — não é OpenWrt); o dono
  informou **Archer C6** (bate com a tela após login).
- **A hipótese dele, provada por um sinal:** no histórico do
  `router_monitor` (751 downs no log + rotação), o down de **21/10 03:00:20
  teve `latency_ms=5`** — falha **instantânea** (host unreachable), a
  **única** de todo o histórico; todos os outros são **timeout de 2009–2012
  ms** (ping perdido). Reboot derruba o gateway na hora; perda de pacote
  espera o timeout. Exatamente o que ele descreveu.
- **Honestidade registrada:** os outros ~10–20 min/dia de "down" espalhados
  (05:25, 05:50, 06:00… o dia inteiro, pico 09h–12h) **não são** o roteador
  caindo — são 1 ping perdido isolado, causa provável o **adaptador WiFi
  USB do servidor** (`wlx000f0037acf0`). Trocar o agendamento elimina o
  incidente das 3:00 (DNS + backup + off-site na mesma janela), **não** esses
  espalhados — diagnóstico separado se ele quiser (cabo resolve).
- **Tether:** não dá pra clonar o app (conta TP-Link do celular dele) e
  **não precisa** — a interface local expõe o mesmo "Reboot Schedule", e é
  por lá que o controle foi feito.

**Leitura do estado atual (SÓ LEITURA, via chromium headless em
`/tmp/opencode/pwvenv` — ferramenta da casa, fora do repo):** login real na
UI (`#reboot` → "Programação de Reinicialização") = **ATIVADA · 03:00 ·
Todos os dias**; Hora Atual do roteador 15:35 = fuso -03 correto (a UI
avisa para conferir o fuso antes de usar a função). Teste do combo "Repetir"
(Todas as semanas → aparece campo de dia) feito **sem salvar** (recarreguei;
o botão GRAVAR é o único que grava).

**Escolha do dono (pergunta objetiva):** **semanal, domingo 05:00**
(recomendado) — frente ao diário 05:00 e ao desligamento total.

**Aplicação (2 tentativas que NÃO gravaram nada + a certa):**

1. `fill()` direto no campo de hora **falhou por construção**: os campos da
   UI são `combobox-text` **readOnly** (spinner); o locator em campo
   readonly travou 20 s e o script foi derrubado por timeout de shell
   (EPIPE no driver) — **estado conferido logo depois: 03:00/diário
   intacto, nada gravado**.
2. JS puro setando `value` não era o caminho (não dispara o widget) e o
   filtro não achou os campos — falhou **antes** do GRAVAR.
3. **Caminho certo = os combos reais:** abrir o combo pelo wrapper do campo
   readonly e clicar na **opção visível** (o mesmo mecanismo que os testes
   de leitura já mostravam): hora `03→05` · Repetir `Todos os dias→Todas
   as semanas` · dia `Segunda-feira→Domingo` · **GRAVAR**.

**PROVA (reabrir do zero e reler):** `{"texts": ["05", "00", "Todas as
semanas", "Domingo"], "ativo": true}` — **PASSOU**, screenshot em
`/tmp/opencode/reboot_prova.png`. Próximo reboot: **domingo 25/10 05:00** —
longe do backup diário (03:00), do off-site (03:40) e das capturas
(domingo 04:00).

**Senha:** consumida do `txt.txt` e **apagada do arquivo na hora**
(protocolo dos tokens); gravada como `ROUTER_ADMIN_PASSWORD` no `.env`
(gitignorado, `check-ignore` confirmado) + **allowlist +1** em
`vault_env_mirror.py` com a nota da pauta. **Espelho do cofre: 19/19
gravado+conferiu** (cofre agora com 19 itens). Nenhum valor impresso no
chat nem nos logs (scripts leem por env).

**Validação:** gate oficial **3546 passed / 16 skipped / 0 falha · 90,69%**
(mudança só na allowlist de um script operacional; `test_vault` 33/33) —
**sem restart** (nenhuma peça em runtime lê a chave nova).

**Estado:** **APLICADO E PROVADO.** Canais: CHANGELOG §1.44.0 (subseção
"sem bump") · `session.json` · `txt.txt` · Telegram. Scripts de
reconhecimento/leitura/aplicação em `/tmp/opencode/` (fora do repo — a
ferramenta registrada de manipulação da UI do roteador).
