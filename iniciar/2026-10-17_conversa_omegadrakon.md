# Conversa 2026-10-17 — OmegaDrakon

## §1 — Ferramentas Nômade: a régua do dono ("só interessa se o sistema puder usar") + avaliação conjunta das 9

Dono (~09:00): **"essas ferramentas só têm interesse para mim se o
sistema puder usar-las"** — reenquadrou o assunto: ferramenta que o
sistema não chama é só mais uma aba no navegador. Ao medir o código,
o diagnóstico confirmou ele: hoje o sistema só faz **ping de saúde +
liga/desliga** (`nomad_tools_*` = compose up/down/logs/restart) —
**uso funcional: zero**.

Pedido seguinte do dono: **"me explique o que faz cada ferramenta e se
vale a pena ter ela no sistema, vamos decidir juntos, não quero nada
parado, essas três primeiras já conheço e vão continuar. depois você
vai interligar com o sistema"** → mapa medido antes de decidir
(memória viva via `docker stats`, conteúdo real via volumes, imagem
via `docker images`):

| Ferramenta | O que faz | RAM | Conteúdo medido | API pro sistema | Decisão do dono |
|---|---|---|---|---|---|
| **Vaultwarden** | cofre de senhas Bitwarden-compatível | 23 MB | 480 KB (só a conta dele) | sim (API completa) | **FICA — 1º a interligar** (cofre do sistema) |
| **Stirling PDF** | junta/divide/OCR/comprime/converte PDF | 303 MB | **2,8 GB já processados** | sim (REST completo) | **FICA — 2º** (pipeline de documentos) |
| **Kiwix** | Wikipédia offline servida no navegador | 4 MB | **14 GB de ZIM** | sim (busca) | **FICA — 3º** (consulta offline do assistente) |
| **CyberChef** | bancada de decodificação (base64/hash/cifra) | 1,8 MB | só página web | **não** (imagem é web estática) | FICA (ferramenta do dono, custo ~0) |
| **IT Tools** | utilitários de TI (UUID, hash, QR…) | 1,9 MB | só página web | **não** (client-side) | FICA (ferramenta do dono, custo ~0) |
| **FlatNotes** | caderno de notas markdown | 17 MB | **vazio (20 KB)** | sim (REST) | **análise a fundo no futuro, um por vez** |
| **File Browser** | gerenciador de arquivos na web | 14 MB | **vazio (48 KB)** | sim, mas sistema já tem disco | **análise a fundo no futuro, um por vez** |
| **Calibre Web** | biblioteca/leitor de e-books | 29 MB | **biblioteca vazia (0 livros), imagem 1,15 GB** | sim (limitado) | **análise a fundo no futuro, um por vez** |
| **Homebox** | inventário do que a casa possui (QR) | 46 MB | **praticamente vazio (1,9 MB)** | sim (REST), mas nunca usado | **SAI — "sair também" (aprovado)** |

Decisões registradas nesta troca (perguntas ao dono com a ferramenta de
escolha): (1) saída de FlatNotes/File Browser/Calibre → **"vamos
analisar eles mais a fundo no futuro, vamos um por vez. comece pelos
três primeiros"** (ou seja: ficam no ar agora, sem decisão de remover);
(2) Homebox → **"Sair também"**; (3) ordem de interligação → **seguir a
ordem sugerida: Vaultwarden → Stirling → Kiwix, uma entrega de cada
vez**. Critério geral gravado: **nada parado** e **ferramenta só
interessa se o sistema puder usá-la**.

Pauta nova foi para o §5 do TODO: análise a fundo (uma por vez) de
FlatNotes, File Browser e Calibre Web.

## §2 — Entrega: Homebox fora do ar — stack Nômade agora com 8 (v1.34.1+2066)

Execução da decisão (1º passo, antes das interligações — item fechado
para não deixar nada pela metade).

| Peça | O que mudou |
|---|---|
| `docker/tools-compose.yaml` | bloco do Homebox **comentado com instrução de reativação** (descomentar + `HBOX_AUTH_API_KEY_PEPPER` no `.env` + `compose up -d`); `docker compose config` valida **8 serviços** |
| `core/nomad_tools.py` | `FERRAMENTAS_NOMAD` 9 → **8** (sem `homebox`) — sonda, cache TTL, notifier e `/health` cobrem só as ativas; decisão (17/10) documentada no módulo |
| `tools/actions/actions.py` | `_NOMAD_SERVICES`/`_NOMAD_PORTS` sem `homebox` — todas as `nomad_*` orquestram só o que está no ar |
| `core/capabilities.py` | capability `nomad-tools` = "8 containers Docker" + descrição cita a saída (dados preservados, compose comentado); fallback de versão 1.34.1 |
| `integrations/api/server.py` | label do painel "Stack Nômade — ferramentas ativas" **sem contagem fixa** (não desatualiza mais); `_APP_VERSION_CODE` **2066** |
| `integrations/notifier.py` + `runtime/launcher.py` | docstrings/contagens 9 → 8 — alerta `tool:homebox` deixa de existir **por construção** (não foi silenciado) |
| Operação Docker | `docker stop/rm od-homebox` + `docker rmi` da imagem (**−198 MB**); dados intactos em `/home/alex/omegadrakon-tools/homebox` (banco 1,9 MB) |
| `tests/test_nomad_tools.py` | contagens e sets 9 → 8, **2 asserções negativas** (`homebox` não volta ao catálogo nem ao `/health` sem decisão nova), sonda de conexão recusada trocou homebox → filebrowser |
| `tests/test_nomad_tools_actions.py` | constantes 8 + `tailscale up` 8 |

**Mutações 3/3 capturadas** (reversões bit-exatas com backup em
`/tmp/opencode/mut1341/`): (1) homebox re-adicionado ao catálogo →
**10 testes falham**; (2) homebox re-adicionado às actions → **3
falham**; (3) porta duplicada filebrowser 8410→8090 → **2 falham**.

**Bump PATCH 1.34.1 + 2066 (política 9/9):** `.env`, `capabilities`
(fallback), `pubspec`, `_APP_VERSION_CODE`, site ×4, CHANGELOG
`[1.34.1]`, README_VERSAO `[1.34.1]`, ANALISE (tabela de prova). APKs
rebuildados pelo `app/build_apk.sh` — **aapt2: versionCode 2066 /
versionName 1.34.1 nos dois**, sha256 do arm64 publicado
(`9aa8409a…`) == anunciado no `/app/version`.

**Suíte final: 3105 passed / 16 skipped · gate 90,93%** (política de
versão e RAG verdes) · `flutter analyze` **0 issues**.

**Deploy:** `systemctl --user restart od-core` → **PID 725852,
NRestarts=0** (17/10 09:45). **Provas vivas:**

- `/health` **up · 21 checks · 8/8 ferramentas · `tool_homebox` ausente**
- `/dashboard/stats` → `nomad_tools: {"total": 8, "up": 8, "fora": []}`
- `/app/version` → **1.34.1 / 2066** · journal **0 erros / 0 menções a homebox**
- **8 containers `od-*`** no ar · compose valida 8 serviços · dados do Homebox no disco

**Commit:** código `d251ba3`; registros no commit seguinte. Estado:
v1.34.1+2066 no ar; stack = 8; fila de interligação começando pelo
Vaultwarden (cofre do sistema).

## §3 — Homebox volta com uso definido + entrega: cofre do sistema (v1.35.0+2067)

**Discussão do Homebox (pedido do dono: "nada sai ou entra sem utilidade").**
Apresentei o que só ele faz (inventário do que a casa **possui** — cômodo,
garantia, nº de série, QR — espelho oposto do Registro Mestre, que é o que a
casa **produz**), os 3 cenários de utilidade real (frente FAB operando;
garantias da casa; eu respondendo "o que tenho em X" via `homebox_*`) e a
apuração da saída (vazio em 5 dias, 1,9 MB de banco, 45 MB RAM, ninguém
sentiu falta). **Resposta do dono à pergunta direta: "Voltar agora com uso
definido"** — volta com o foco aprovado no exemplo (inventário/garantias da
casa), **já integrado com `homebox_*`**, numa próxima entrega (registro no
TODO §1 linha 8 + §5). Se quiser outro foco, é só dizer.

**"Prossiga com o cofre" — 1ª das 3 interligações entregue (v1.35.0+2067):**

- **Conta de serviço criada** `od-sistema@omegadrakon.dev` pelo fluxo de
  registro com crypto oficial (action `nomad_vaultwarden_setup`): signups
  abertos por ~20 s, conta criada, **fechados e verificados no mesmo ato**
  (rede de segurança automática mesmo em falha). A conta e a master **do
  dono nunca entram no circuito**.
- **`integrations/vault.py`**: `VaultClient` + fábrica LAZY (cofre fora do
  ar degrada a ação, **nunca o boot**); senha só via `--passwordenv` (env);
  JSON de item só por **stdin base64** (nunca argv); sessão em memória com
  renovação única; erros tipados honestos.
- **4 actions** `vault_status/vault_list/vault_get/vault_set` (categoria
  `vault`, só admin): lista devolve **só títulos**, segredo só em `vault_get`,
  `vault_set` atualiza sem duplicar. Catálogo **89 → 93**; capability
  `vault-cofre` ATIVA.
- **Achado de campo minado (apuração viva):** a prova de escrita derrubou o
  pin provisório **2026.8** — todos os 2026.x (2026.8 e 2026.10, em Node 18
  **e** 22) **crasham decifrando cifras do Vaultwarden 1.36** com item no
  cofre (`invalid type: JsValue … expected a string`); o drill de 15/10 só
  testara **cofre vazio**. Combo final: **bw 2025.12.1 + Node 22 +
  `BITWARDENCLI_APPDATA_DIR` próprio** (`~/.local/opt` e
  `~/.local/share/bitwarden-cli`, zero dependência em `/tmp`); TODO da
  dívida atualizado com os **dois** bloqueios dos 2026.x.
- **Testes:** `tests/test_vault.py` novo (33) · **suíte 3138 passed / 16
  skipped, gate 90,90%** · `flutter analyze` 0 · **mutações 4/4** bit-exatas.
  Política 9/9: 2067/1.35.0 em `.env`/capabilities/pubspec/`_APP_VERSION_CODE`/
  site×4/CHANGELOG/README_VERSAO/ANALISE; aapt2 confere nos dois APKs.

**Deploy:** `systemctl --user restart od-core` → **PID 840230,
NRestarts=0** (17/10 11:46). **Provas vivas:**

- `/health` **up · 21 checks · fora=nenhum · tools 8/8** · `/dashboard/stats`
  `nomad_tools total=8 up=8 fora=[]`
- `/actions` **93** com as 4 `vault_*` · `/app/version` **1.35.0 / 2067**
  (sha `753c59af…` == APK publicado) · journal **0 erros**
- **E2E no cofre real pelo wrapper de produção:** status (conta de serviço,
  `locked`, alcança=true) → `vault_set` **criado** → `vault_list` **só
  id/nome/tipo** → `vault_get` (case-insensitive, senha **confere**) →
  `vault_set` de novo **atualiza sem duplicar** → `apagar` → **cofre `[]`**.
  Ciclo `create/edit/delete` provado também direto no CLI; **conta do dono
  intocada**.

**Commit:** código e registros nos dois commits da entrega. Estado:
v1.35.0+2067 no ar; cofre ligado (vazio de propósito — popular é do dono);
fila da interligação: **2º Stirling PDF → 3º Kiwix**; Homebox volta na
sequência com uso definido.

## §4 — Entrega: Stirling PDF interligado (2ª das 3) + as 12 senhas do .env no cofre (v1.36.0+2068)

**Ordem do dono (17/10):** *"coloque todas as senhas do .env no cofre e
começa a implantação da 2ª opção da fila, stirling"* — dois trabalhos numa
entrega só, na fila aprovada por ele (Vaultwarden ✅ → **Stirling** →
Kiwix → Homebox com uso definido).

**1) Espelho `.env` → cofre.** `vault_env_mirror.py` (raiz): allowlist
**explícita das 12 credenciais** (se nascer segredo novo fora dela, o
script **avisa** em vez de deixar passar), `OD_MQTT_PASSWORD` pareado ao
username, nota por chave (`TELEGRAM_BOT_LEGADO_TOKEN` = **rotação §8.5
pendente**; `OD_VAULT_MASTER` = auto-referência cifrada com nota de que o
bootstrap é só o `.env`). Conferência por `get`+comparação que **só
imprime nome + confere/ERRO** — nenhum valor em log ou transcrição.
Resultado: **12/12 conferem, cofre com 12 itens**. Regras do desenho: o
`.env` **nada perdeu** (é cópia, não remoção) e o **boot nunca depende do
cofre**.

**2) Stirling vira ações do sistema.** Antes de escrever código, o
contrato foi apurado **ao vivo**: `GET /v1/api-docs` do s-pdf 2.13.1
(OpenAPI 3.0.3, **255 rotas** — descoberta: a spec fica em `/v1/api-docs`;
o `/v3/api-docs` devolve o SPA) + chamadas reais (merge →
`application/pdf` síncrono; page-count → `{"pageCount":2}`). Da spec vieram
as regras gravadas: campos **obrigatórios sempre enviados por nós**, e
**mágica `%PDF`/`PK` antes de gravar** — resposta ruim (200 com HTML)
nunca vira arquivo; saída existente só com `substituir=True` (**nada
apagado por acidente**, a mesma régua do dono).

Entrega: `integrations/stirling.py` (**stdlib puro** — `urllib` +
multipart manual no padrão do projeto, zero dependência nova; 11 erros
tipados honestos; **LAZY** — ferramenta fora do ar degrada a ação, nunca
o boot), 4 actions `stirling_status` / `stirling_merge` /
`stirling_split` / `stirling_compress` (categoria `stirling`, só admin),
capability **`stirling-pdf`**, catálogo **93 → 97**.

**Validação.** `tests/test_stirling.py` novo: **49 testes** (módulo 97%).
Suíte final: **3187 passed / 16 skipped · gate 90,96%** (+49). Mutações
**4/4** capturadas, restauração bit-exata por sha256 — com lição honesta:
um `.pyc` temporário com **mtime+size idênticos** ao fonte mascarou a
restauração na suíte intermediária; cache invalidado e suíte final verde.
`flutter analyze` 0 · aapt2 **2068/1.36.0** nos dois APKs.

**Deploy e provas vivas (PID 914141, NRestarts=0).** A 1ª subida levou
179s por **re-sincronia RAG one-time** (`atualizados=442` chunks alterados
nesta entrega; padrão histórico confirmado — 16/10 13:50→13:54 com 654;
boots com 0 levam 1–3s; não é regressão). No ar: `/health` **21 checks,
tools 8/8** · `/actions` **97** com as 4 · `/app/version`
**1.36.0/2068** (sha `b4a7247d…` == APK publicado) · journal **0 erros**.
**E2E do pipeline real** (pelo `/executa` de produção): status
(**2.13.1 UP**) → merge de 2 PDFs (**1234 B**, sha conferido) →
**page-count = 2** direto no container → repetição sem `substituir` →
**`stirling_saida_ocupada` + arquivo intacto** → split do merged (**ZIP
com 2 peças**) → compress **177072 → 5444 B (−96,9%)** com antes/depois
honestos.

**Commit:** código 9d69299; registros no commit seguinte. Estado:
v1.36.0+2068 no ar; fila **1ª ✅ 2ª ✅ → 3ª Kiwix**; rotação §8.5 pendente
(com o valor antigo já arquivado no cofre).

## §5 — Pedido do dono: RAG fora do boot (v1.36.1+2068→2069)

**Pergunta do dono:** *"quanto ao RAG, porque no boot, ele não pode
entrar depois e rodar em paralelo"*. Resposta com código na mão: **pode
— e a partir de agora é assim.** Mas antes de concordar só de boca,
apuramos o culpado real do boot de 179s: **não era o embedding** (provider
hash, milissegundos) — era o `VectorStore` **reescrevendo o JSON inteiro
a cada remoção**: `delete` unitário × 442 chunks substituídos numa edição
grande = **O(n²) de I/O** (~0,4s/chunk — fecha com os boots históricos:
654 chunks → 4min; 0 chunks → 1–3s). O próprio comentário do `rag.py` já
denunciava o O(n²) do `add` unitário; o `delete` tinha ficado para trás.

**Dois consertos, um por cima do outro:**
1. **Lote** — `delete_many` novo (uma persistência no fim, JSON e DB),
   espelhando o `add_many`; `sync()` agora apaga substituídos+órfãos de
   uma vez.
2. **Background** — `build_rag()` padrão novo: `store.load()` serve o
   índice já gravado e o boot **segue**; a re-sincronia roda em thread
   daemon e passa a valer quando termina. Janela honesta: consultas antes
   do fim do sync devolvem `""` (o mesmo caminho de "sem corpus", que já
   existia) e voltam sozinhas. `OD_RAG_SYNC_BACKGROUND=0` = caminho
   síncrono antigo (fail-safe). Falha na thread → estado `falhou` +
   warn, nunca derruba o core. Estado visível: `sync_status()` /
   `dump()` (`pendente/sincronizando/pronto/falhou`).

**Validação:** +11 testes (lote com spy em `_persist`, estados, duplo
start, janela com volta, falha → `falhou`) · suíte **3198 passed / 16
skipped · gate 90,96%** · `flutter analyze` 0 · aapt2 **2069/1.36.1**.

**Prova viva (PID 976302, NRestarts=0):** **porta 8000 aberta em 3s**
(antes 179s) — journal: `Database Layer` → `RAG ligado | sync em
background` (despacho em thread **antes** do boot terminar) → `API REST
no ar`; sync de fundo fechou em **+2,0s** (o lote deixou o sync tão
barato que terminou antes da API — a ordenação "API antes do sync" só
apareceria com sync maior; a garantia é estrutural e coberta por teste).
`/health` 21 checks · `/actions` 97 · `/app/version` **1.36.1/2069**
(sha `1a623b1bbc96…` == APK) · journal 0 erros.

**Commit:** código `dda31ec`; registros no commit seguinte. Estado:
v1.36.1+2069 no ar (boot 3s); **fase 3 aprovada — Kiwix**; reconhecimento
feito: `od-kiwix` 3.8.1 no ar em `127.0.0.1:8090` com a Wikipédia
en_all_mini, API HTTP é HTML (contrato a fechar na entrega).
