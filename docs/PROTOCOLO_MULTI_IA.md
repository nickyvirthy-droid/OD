# PROTOCOLO MULTI-IA — como várias IAs constroem o mesmo OD

> **Ordem do dono (18/11/2026):** *"agora temos um número muito grande de IAs
> trabalhando sobre OD. garanta que todas prossigam dentro da mesma linha sem
> destruir o que existe e mantendo a coerência e melhoria do projeto, mesmo que
> uma pare no meio do caminho por cota ou outra razão a próxima deve prosseguir
> e assim sucessivamente até concluir."*
>
> Este documento é o contrato entre elas. Vale para **qualquer** IA: Freebuff,
> OpenCode, Cline, Claude, Gemini, Codex, Aider, Qwen, Crush, OpenClaw,
> OpenClaude, Interpreter, Kilo — e as que ainda vierem. A regra normativa vive
> em `iniciar/RULES.md` (regra 24).

## 1. O problema que isto resolve

O dono usa ferramentas gratuitas e os créditos **acabam no meio do serviço**.
Isso produz, com frequência:

- lotes pela metade, sem registro (regra 23);
- AIs diferentes puxando direções diferentes (cada uma "acha" o que é prioridade);
- e o pior: **uma IA reescrevendo por cima do trabalho de outra**. Caso real de
  18/11: `orquestrador.py` regredido de 1654 para 251 linhas (a versão de fila
  removida em 08/10), sem uma linha de registro, quebrando a coleta da suíte.

A resposta não é confiar na memória de cada IA — é ter **estado explícito,
regras iguais e travas automáticas**.

## 2. Ao ENTRAR (todo turno, toda IA)

1. Ler o **brief único** reproduzível:
   ```bash
   python3 tools/brief_multi_ia.py
   ```
   Ele traz versão, `HEAD` × `origin/master`, árvore suja, checkpoint vigente
   (`iniciar/session.json`), últimas atribuições e as prioridades P0/P1.
   O `orquestrador.py` injeta esse mesmo brief no prompt de **cada CLI da
   cascata** — ninguém começa sem ele.
2. Ler `iniciar/RULES.md` (24 regras) e o topo de `iniciar/ATRIBUICOES.md`.
3. Se a árvore estiver suja com trabalho que **não é seu**, isso é trabalho
   parcial de outra IA: **continue dele**, nunca reverta.

## 3. Ao TRABALHAR (regras de convivência)

| # | Regra | Por quê |
|---|-------|---------|
| 1 | **Editar cirurgicamente.** Nunca reescrever um arquivo inteiro por cima do que existe. | Foi assim que o `orquestrador.py` foi destruído em 18/11. |
| 2 | **Reescrita maciça é bloqueada:** arquivo rastreado que perde mais de 70% das linhas (>= 100 linhas antes) faz a sessão falhar **sem commitar** (`arquivo_reescrito_em_massa`). | Se a reescrita é legítima, peça `[AUTORIZACAO]` ao dono — decisão dele, não da IA. |
| 3 | **Não reverter o trabalho de outra IA.** Origem desconhecida = registrar como desconhecida (regra 23). | Reverter destrói horas de cota que não voltam. |
| 4 | **Atribuição no mesmo passo:** autor, arquivos criados/modificados, intenção + estado (pronto / pela metade / próximo passo exato) em `iniciar/ATRIBUICOES.md` **e** `iniciar/session.json` **e** transcrição do dia. | É o que permite a próxima IA continuar sem adivinhar. |
| 5 | **Registro durável fora do `txt.txt`** (regra 20): o que importa vai para `docs/CHANGELOG.md`/README da área, Telegram e `iniciar/`. | O `txt.txt` é conversa e é apagado. |
| 6 | **Uma fonte por assunto:** estado da sessão = `session.json`; fila de trabalho = `docs/ANALISE_SISTEMA_TODO.md`; quem fez o quê = `ATRIBUICOES.md`; regras = `RULES.md`; IAs = `docs/IAS_DISPONIVEIS.md`. | Duas fontes = duas verdades. |
| 7 | **Validar antes de publicar** (regra 13): suíte/gate verde e diff revisado. Proibido desativar teste, enfraquecer asserção ou engolir erro para "passar". | Publicar vermelho transfere o problema para a próxima IA. |
| 8 | **Sem bump fora do deploy** (regra 12) e **sem deploy/restart/destruição sem ordem** (regra 7). | Custo e risco ficam com quem tem o contexto. |

## 4. Ao SAIR — inclusive quando a cota acaba

Obrigatório **antes** de encerrar, com qualquer motivo:

1. Deixar o trabalho parcial **na árvore** (não apagar, não `git checkout --`).
2. Registrar o **próximo passo exato** em `iniciar/ATRIBUICOES.md` e no
   checkpoint de `iniciar/session.json` (`em_aberto` / `pendente`).
3. Se houver commit: `HEAD == origin/master` (regra 7.1/7.2).

Formato mínimo do checkpoint:

```json
"<assunto>_<data>": {
  "pedido": "o que o dono pediu, com as palavras dele",
  "estado_encontrado": "o que foi medido no repositório/serviço",
  "em_aberto": "o próximo passo exato, com arquivo e comando",
  "autor": "ferramenta/modelo (regra 23)",
  "updated_at": "AAAA-MM-DDTHH:MM:SS-03:00"
}
```

## 5. A cascata: a próxima IA continua até concluir

`orquestrador.py --sessao` percorre as 13 CLIs (`CLIS`) e, desde 18/11:

- **CLI sem cota/sem binário** devolve `None` → a próxima assume **no mesmo
  turno**, com o mesmo prompt e o brief;
- **gate vermelho** deixa de encerrar a sessão: a próxima CLI recebe no
  histórico o resumo do vermelho + "preserve o que já existe e conserte a
  causa", e valida de novo — até concluir ou acabarem as CLIs;
- **reescrita maciça** interrompe a sessão antes de commitar (trava acima).

Quando todas falharem, o estado final é `falhou / testes_vermelhos` (ou
`todas_as_clis_falharam`) com o motivo na caixa, no estado e no Telegram — o
dono vê exatamente onde parou.

## 6. Enquanto uma IA espera a próxima

Não há necessidade de ninguém "tomar posse": a fonte da verdade é o repositório
+ `iniciar/`. Basta que cada IA, ao entrar, leia o brief e, ao sair, registre o
ponto. O que **não** é permitido é: apagar trabalho alheio, inventar estado,
publicar vermelho ou sair sem deixar o próximo passo.

## 6.1 Como o DONO opera (o caminho normal)

Sim — para o uso do dia a dia é só isso:

1. Escrever o pedido no **`txt.txt`** (raiz), com as palavras dele. É o canal
   de conversa e de ideia; não é arquivo de registro (regra 20).
2. Abrir o painel **`/admin`** e clicar em **▶ Ativar desenvolvimento**
   (`POST /admin/dev/sessao`). O `orquestrador.py --sessao` lê o `txt.txt`,
   monta o brief, roda a cascata de 13 CLIs, pausa na caixa quando a CLI pedir
   `[AUTORIZACAO]`, valida a suíte e commita (o push do fecho é automático).
3. Acompanhar na própria caixa do painel: análise, pergunta de autorização,
   validação e commit. No fim chega o resumo no Telegram.
4. Se uma CLI acabar a cota, nada precisa ser feito: a próxima continua do
   ponto atual. Se TODAS caírem, o motivo exato fica na caixa, no estado e no
   Telegram — aí é só escrever o próximo passo no `txt.txt` e ativar de novo.

O que **não** é obrigação sua: copiar texto entre janelas, escolher qual IA
usa, commitar ou reiniciar. O que continua sendo decisão sua: aprovar
`[AUTORIZACAO]`, escolher prioridade, autorizar deploy/restart e qualquer ação
destrutiva.

Para conferir o estado sem ativar nada, a seção **“IAs no projeto”** do
`/admin` mostra o checkpoint vigente, a árvore suja e há quanto tempo ninguém
registra (registro parado + árvore suja = lote órfão, em vermelho).

## 7. Como provar que está funcionando

- `python3 -m pytest tests/test_multi_ia.py -q` — brief, trava de reescrita e
  continuidade da cascata.
- `python3 -m pytest tests/test_corpus_frases_dono.py -q` — as frases reais do
  dono como linha de base das intenções (P0 nº 2).
- `python3 -m pytest tests/test_trava_reescrita.py -q` — a régua e o hook
  `pre-commit` (inclusive um commit real bloqueado e outro passando).
- `python3 tools/brief_multi_ia.py` — o estado que a próxima IA verá.
