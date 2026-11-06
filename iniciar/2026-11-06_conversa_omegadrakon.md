# Conversa OmegaDrakon — 06/11/2026

## §1 — "leia iniciar" (06/11 ~13:00)

Pedido: *"leia iniciar"* — retomada do zero, regra 3 (ler o checkpoint e os
arquivos recentes antes de assumir contexto). Checkpoint anterior:
`revisao_pendencias_2026_11_05` (05/11 22:30).

### 1. Estado do sistema

| Item | Medido hoje |
|---|---|
| Git | árvore limpa, `HEAD 34ea596` == `origin/master` |
| od-core | active desde 05/11 21:23:56, `MainPID 3145390`, `NRestarts=0` |
| `/health` | `ok=true`, 25/25 checks, nenhum fora |
| journal (desde o restart) | **0** `[ERROR]`/`[CRITICAL]` e **0** `[WARNING]` |
| app | 1.44.0 / 2080, sha `aeb8566b` (sem bump) |
| Acervo | 360 mp3 · `acervo.db` 360 linhas · max duração 690 s (`>1500 s` = 0) |
| AzuraCast | 362 = 360 faixas + 2 locuções (bate) · `.m3u` de 02:14 |
| Rádio | no ar: *Jota Quest — Dias Melhores* |

### 2. O lote do Legião terminou sozinho

`logs/radio_link_lista_legiao_v2.log`:

```
2026-11-06 02:14:41 | lote 10: acervo agora 360 (+9)
2026-11-06 02:14:41 | === fim: 10 lote(s), 0 com falha, acervo 360 ===
```

- 99 entradas → **98 baixadas** (262 → 360). Uma ficou de fora sem falha
  registrada (dedupe de título repetido), nenhum lote com erro.
- `.m3u` regerados e AzuraCast sincronizado no fim (02:14).
- O aviso de conclusão no Telegram é enviado pelo próprio runner.

### 3. Defeito: as 98 novas entraram "Desconhecido"

- `SELECT` no `acervo.db`: **98 linhas com `artista='Desconhecido'`** e
  `genero='Outros'` — todas as novas. Títulos limpos e curiosidade real.
- **Não é o pipeline quebrado.** Os títulos dessa playlist vêm do YouTube
  **sem o artista** (só o nome da música: "Tempo Perdido", "Eduardo e
  Mônica"). Medido hoje: pedindo ao Groq e ao local qwen o artista de
  "Tempo Perdido", **os dois respondem `Desconhecido`** (e o modelo local
  chegou a inventar que é versão do The Prodigy). A IA não serve como
  identificador de artista a partir do título.
- Consequência viva: a rádio toca **"Desconhecido - Tempo Perdido"**.
  98 arquivos com prefixo `Desconhecido - ` (60 em `acervo/Outros/`, o resto
  nos gêneros antigos).

### 4. A chave do Gemini morreu (medido, não suposto)

| Teste | Resultado |
|---|---|
| `generateContent` **com** `x-goog-api-key` (3×) | `400 API_KEY_INVALID` |
| `GET /v1beta/models` com a mesma chave (3×) | `400 API_KEY_INVALID` |
| chave obviamente inválida (`AIzaSyAAAA…`) | mesmo erro, mesmo texto |
| `GET /openai/v1/models` da Groq (mesma `.env`) | **200** |

Ontem (05/11) a mesma chave respondia 200 com header. Hoje **não autentica
em nenhuma das duas formas** — é chave revogada/expirada, não forma de
autenticação. O Groq continua bom e assume a cadeia (`OD_IA_ORDEM`), o local
é a última reserva. Sem ação minha: precisa de chave nova do dono.

### 5. Achado extra (não é desta leva)

Duas faixas infantis de Cocomelon no acervo desde **04/11 10:56** —
`Cocomelon - Wheels On The Bus` e `Fire Truck Song - … Cocomelon …`.
Uma delas apareceu como **próxima** na rádio agora. Candidatas a sair.

### 6. O que ficou na mesa do dono

1. **31 faixas de 7–10 min** (músicas únicas, não medley): apagar ou não.
2. **Tela da lista de cantores** no painel (`/admin`) — hoje é arquivo + API.
3. **Pedido por link** de artista indesejado: baixa antes de marcar.
4. **Forwards** `.250 → .205`; **rotação da senha WiFi**.
5. **Novas**: (a) chave Gemini nova **ou** rodar com
   `OD_IA_ORDEM=groq,local`; (b) carimbar `Legião Urbana` nas 98 (conferindo
   as de Renato Russo solo); (c) tirar as 2 da Cocomelon.

Nada disso foi executado: a sessão foi **só leitura**. Sem restart, sem bump,
sem tocar no acervo.
