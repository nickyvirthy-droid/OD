# AUDITORIA DE USO — o que roda sem ninguém do outro lado (28/11/2026)

> **Pergunta do dono:** *"se uma coisa não está sendo usada ela precisa estar
> funcionando? a primeira ideia que me veio na cabeça é a rádio tocando sem
> ouvintes, deve ter mais coisas."*
>
> **Método:** medição só-leitura no servidor (`systemctl`, `docker ps/stats/
> logs --since 48h`, `ss`, `ps`, `journalctl`, API pública do Azuracast).
> Nada foi parado, removido ou reconfigurado.

## A resposta curta

**Não.** "Estar funcionando" não é objetivo — é custo. Um componente sem uso tem
três destinos honestos: **usar** (dar a ele um consumidor), **estacionar**
(parar e deixar o comando de subir documentado) ou **remover**. O que não se
justifica é pagar CPU, RAM e superfície de porta 24 h por dia para um serviço
que ninguém consulta — nem o contrário: apagar uma capacidade que só é usada em
emergência (o LLM local é o "sem internet").

Por isso a classificação abaixo separa três coisas que parecem iguais:

| Classe | Exemplo | Precisa estar funcionando? |
|---|---|---|
| **Suplente** | `llama-server` local | **Sim** — o valor é justamente funcionar quando o resto falta. Mas precisa ser **provado** de tempos em tempos, senão é fé. |
| **Serviço de ouvintes** | Azuracast / liquidsoap | **Não**, se não há ouvinte: aí é só custo. |
| **Infra ociosa** | os 8 containers de ferramentas | **Não** enquanto ninguém usa; estacionar é mais barato que manter aquecido. |

## O que foi medido (48 h, até 28/11 ~17:30)

| Componente | Rodando? | Evidência de uso | Custo | Veredito |
|---|---|---|---|---|
| **Azuracast + liquidsoap** (rádio "Nicky") | sim, 2 dias | API `nowplaying`: **listeners current = 0**; nenhuma linha de ouvinte em 48 h | **8,7 % de CPU contínuo** (encode 192 kbps MP3) + container | **O caso mais claro:** toca para ninguém. Usar de verdade ou desligar. |
| **od-core** (o próprio assistente) | sim, 23 h de uptime | **2 mensagens em 48 h**, ambas `action_intent` em 26/11 17:20/17:24 | ~300 MB RSS | Não é "sem uso" por defeito — é o assistente esperando o dono. Manter. |
| **llama-server** (3B local) | sim | **0 chamadas** no período | 0,1 % CPU, ocioso | **Suplente:** manter, mas com prova periódica (hoje ninguém verifica se ainda sobe). |
| **od-homebox** | sim | 11.492 healthchecks vs 5.754 linhas — todas `GET /` e `/api/v1/status`; **banco sem escrita desde 26/11 05:35** | 21 MB | Inventário já cadastrado; uso é esporádico por natureza. Manter. |
| **od-flatnotes, od-it-tools, od-cyberchef** | sim | **2.877 linhas ≈ 1 healthcheck/minuto**; nenhuma outra rota | ~19 MB somados | **Ociosos.** Estacionar (subir sob demanda). |
| **od-kiwix** | sim | sem log de acesso; responde 200 | 3,4 MB | Barato, mas só é usado por action de admin. Estacionar ou manter com uso declarado. |
| **od-vaultwarden** | sim | **0 linhas em 48 h** | 11 MB | Se o cofre é usado pelo navegador, o log não prova — **confirmar com o dono** antes de mexer. |
| **od-calibre-web, od-filebrowser** | sim | **0 linhas em 48 h** | 45 MB | Idem: sem log de acesso não se afirma uso nem desuso. |
| **od-stirling-pdf** | sim | 298 linhas (healthcheck) | 391 MB | Peso alto para uso esporádico → candidato a subir sob demanda. |
| **od-io-probe.timer** | a cada 5 min | `data/io_monitor.json` é lido pelo `/health` (launcher) | desprezível | **Tem consumidor.** Manter. |
| **od-os-updater.timer** | semanal | rodou 26/11 (67 pacotes) | desprezível | Manter. |

### Limites desta medição (honestidade)

- **Log ausente ≠ uso zero.** Kiwix, Vaultwarden, Calibre e Filebrowser não
  registram acesso por padrão; "0 linhas" só prova que não houve erro/escrita,
  não que ninguém abriu. Os três com 2.877 linhas provam o contrário: eram
  healthchecks disfarçados de atividade.
- Contagem de CPU do liquidsoap é do `ps` (média desde o start), não instantânea.
- A rádio é a única em que o uso é medido **de dentro do próprio serviço**
  (`listeners.current = 0`) — por isso é a conclusão mais firme.

## Decisões que ficam abertas (do dono)

1. **Rádio:** desligar Azuracast e liquidsoap (libera ~8,7 % de CPU) **ou** dar
   uso real à estação. Enquanto ninguém ouve, ela é o exemplo perfeito de
   "funcionando sem precisar".
2. **Ferramentas ociosas** (flatnotes, it-tools, cyberchef, stirling): manter
   aquecidas, estacionar com `docker compose --profile`/subida sob demanda, ou
   remover? Estacionar é reversível e barato.
3. **Suplentes** (llama local, kiwix): manter funcionando, mas com **prova
   periódica** — um teste que sobe/consulta e falha alto, em vez de confiar no
   `Up 2 days`.
4. **Vaultwarden/Calibre/Filebrowser:** confirmar se são usados pelo navegador;
   sem isso, nenhuma mudança.

## Consequência para o TODO

Isto muda a ordem do que "falta implementar": não se implementa robustez para
um subsistema que ninguém consome. Os itens de código que restam ganham uma
pergunta prévia — **quem usa isso?** — e os que só fazem um serviço ocioso
"funcionar melhor" (ex.: otimizar a rádio, empilhar features na UI) descem de
prioridade até a decisão de uso acima.
