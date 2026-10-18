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

## §6 — Fase 3 aprovada: Kiwix interligado (v1.37.0+2069→2070) — FILA FECHADA

**Ordem do dono:** *"aprovado fase 3"* — última da fila de ferramentas
(Vaultwarden ✅ → Stirling ✅ → **Kiwix**), pelo critério dele: *"essas
ferramentas só têm interesse para mim se o sistema puder usa-las"*.

**Contrato-antes-de-código (sondagem viva no `od-kiwix`, 3.8.1,
`127.0.0.1:8090`, Wikipédia `wikipedia_en_all_mini` 12,5 GB):** a API é
**HTML/XML puro — sem JSON** nesta versão (`/suggestions` vazio,
`/search` ignorou `Accept: application/json`; achado: `/A/<título>` só
redireciona para `/content/...`). Contratos reais mapeados:
`/catalog/v2/entries` (Atom/OPDS: id/título/idioma/artigos/mídias),
`/search?pattern=` (HTML: título+caminho+trecho+palavras por hit),
`/content/<zim>/<path>` (200 = artigo, 404 = inexistente).

**Entrega:** `integrations/kiwix.py` **novo** (stdlib puro — `urllib` +
`html.parser` + `ElementTree`; zero dependência nova): `KiwixClient`
somente **leitura** (ZIM `:ro`), caminho invalidado contra `..`,
truncamento **declarado**, **busca vazia = resposta honesta**
(`ok=True, resultados=[]`), 6 erros tipados (`kiwix_indisponivel`,
`kiwix_timeout`, `kiwix_falhou`, `kiwix_parametro_invalido`,
`kiwix_artigo_nao_encontrado`, `kiwix_resposta_invalida`), fábrica
**LAZY** (`OD_KIWIX_URL`). Actions: `kiwix_status` / `kiwix_busca` /
`kiwix_leitura` (categoria `kiwix`, só admin) — catálogo **97 → 100**;
capability **`kiwix-offline` ATIVA**; bump 9/9 **1.37.0+2070**.

**Validação:** `tests/test_kiwix.py` novo (**39 testes**, fixtures
fiéis às capturas vivas de hoje — Atom, HTML com `&isin;`/`&Omega;`,
artigo com script/style); suíte **3238 passed / 16 skipped · gate
91,04%**; `flutter analyze` 0; aapt2 **2070/1.37.0**. Correção no
caminho: `get_logger` (não `make_audit_nicky`) para o logger do módulo.

**Provas vivas (PID 1003253, NRestarts=0, boot 4s, 0 erros):** E2E real
pelo `/executa` de produção — `kiwix_status` (**18.095.848 artigos**,
eng) → `kiwix_busca("omega")` (3 hits com trecho; 1º com 207 palavras)
→ `kiwix_leitura` ("Omega function", 199 chars limpos, `truncado=False`)
→ 404 honesto → busca vazia como resposta. **TODAS AS PROVAS
PASSARAM.** Detalhe lindo no journal: o dump do orchestrator capturou
`docs: 0` ao lado de `sync: pronto` com **744 chunks atualizados** —
leitura rasgada que **só existe com o sync e o boot correndo em
paralelo** (o batch da v1.36.1 fechou 744 substituições em ~3s; no
código antigo seriam ~300s de bloqueio).

**Commit:** código + registros nos commits do dia. **Estado:
v1.37.0+2070 no ar — fila do dono FECHADA** (Vaultwarden ✅ Stirling ✅
Kiwix ✅); próximo capítulo: Homebox com uso definido.

---

## §7 — O dono define o uso do Homebox: o sistema cadastra as peças dele (v1.37.0→1.38.0+2071) — FILA FECHADA DE VEZ

**Dono (17/10, 15h12):** *"o uso do homebox é para voce me ajudar a cadastrar
as ferramentas e peças que possuo, por exemplo tenho um raspbarry 4 e um
modulo esp-01s dht22, então sabendo disso voce pode sugerir a montagem de
uma estação meteorologica e falar as peças que possuo e as que preciso..."*

Uso definido = 4ª e última da fila entra no mesmo ciclo. Diferença de
todas as anteriores: **escrita** — o sistema não só consulta, ele
**cadastra** (e a régua "nada apagado" vale: nenhuma ação de exclusão).

**Reativação sem perder nada:** o Homebox tinha sido desligado em 17/10
(§2 — "nada parado"), com o banco preservado em
`omegadrakon-tools/homebox/homebox.db` (0 usuários — pristine). Bloco
descomentado no compose, container de volta no ar, e a conta do sistema
(`omega-drakon@omegadrakon.local`, senha de 32 chars gerada, nunca
impressa) + **API key estática** criadas na reativação. Conta órfã de um
bootstrap interrompido (senha se perdeu com o processo) removida do
SQLite via `chown` temporário pelo próprio container — sem sudo, sem
app de terceiros. Cofre: allowlist +2 (`HBOX_API_KEY`,
`HBOX_API_PASSWORD`) e espelho rodando — **14/14 conferem**.

**Contrato apurado ao vivo ANTES de codificar** (a casa cobra): o
container serve **swagger próprio** em `/swagger/doc.json` (67 rotas,
Swagger 2.0) e a tag `v0.26.2` do fork tem o `routes.go` público —
descobertas que mudaram o projeto: (1) o inventário é **`/v1/entities`**
(NÃO `/items` — meu primeiro sondeo deu 404 em tudo); (2) **auth**: a
session token do login **NÃO** vale como `Authorization: Bearer` (o
middleware lê o **cookie** `hb.auth.token`) — já a **API key** vale
exatamente como Bearer (e não como cookie); o caminho do sistema é a key
estática, sem expiração; (3) **PUT substitui o objeto** (`name`
obrigatório; o resto vira zero) e **PATCH é parcial de verdade** (só 5
campos) — notas/descrição/preço passam por GET+merge+PUT.

**Três defeitos achados pelo E2E vivo e corrigidos com teste:**
`PUT` com `parentId:""` → **HTTP 500 "Unknown Error"** do fork (opcionais
agora só entram quando presentes — teste de regressão); id fora de UUID →
API devolve **400 "invalid route key"**, não 404 (validação antes da
chamada, com dica "use o id de homebox_busca"; UUID inexistente → 404
honesto); tags inexistentes são criadas **com declaração** na resposta
(`tipo_criado`/`tags_criadas`) — o `listar`, por ser filtro, não cria.

**Entrega (v1.38.0+2071):** `integrations/homebox.py` (stdlib puro, LAZY,
7 erros tipados) + 6 actions — `homebox_status` / `homebox_busca` /
`homebox_listar` / `homebox_detalhar` / `homebox_criar` /
`homebox_atualizar` (categoria `homebox`, só admin) — catálogo **100 →
106**; capability **`homebox-inventario` ATIVA**; bump 9/9; APKs
publicados (aapt2 2071/1.38.0, sha `25f212d6…`).

**Validação:** `tests/test_homebox.py` novo (**52 testes**, fixtures fiéis
ao swagger/capturas de hoje); suíte **3290 passed / 16 skipped · gate
91,07%**.

**Provas vivas (restart NRestarts=0, 0 erros):** E2E real pelo
`/executa` (**20 provas**) — e o mais importante: **o sistema cadastrou
as peças REAIS do dono**: `homebox_criar` "Raspberry Pi 4" (tipo
`Placa de desenvolvimento` criado+declarado, tags `eletronica`+`computador`)
e "ESP-01S com DHT22" (tipo `Módulo sensor` criado+declarado, tag
`sensor`) → buscas 1 hit cada → lista as 2 peças → detalhe →
**atualização** com a nota *"candidato a estação meteorológica"* (PUT
completo — provou a correção do 500) → 404 honesto → totais coerentes.
O E2E tem guarda anti-duplicação: reruns verificam sem cadastrar de novo.

**Commit:** 372d874 (entrega) + registros. **Estado: v1.38.0+2071 no ar
— FILA DE FERRAMENTAS FECHADA DE VEZ** (Vaultwarden ✅ Stirling ✅
Kiwix ✅ Homebox ✅); inventário do dono operacional e já populado com
as 2 peças que ele citou.

---

## §8 — O dono fecha pendências: as capturas do Sistema Órion viram o formato do painel e do site (v1.38.0→1.39.0+2072)

O dono abriu a rodada de fechamento: *"existem mais pendencias, vamos
fechar antes de colocar novidades"*. Reconhecimento feito antes de
mexer: HDs montados (`/home/alex/dados` + `/mnt/Arquivos`), `3D/` do
repo vazia (a pasta DELE é `/home/alex/3D` — 1,2 GB de STLs pagos,
fora do git, 0 `.stl` rastreados), repo `origin` **PÚBLICO** no GitHub
(histórico antes de `3ed13cc` com segredos do compose). Duas decisões
do dono: **repo → "privar + rotacionar"** (aprovado) e **`3D/` jamais
deletada** — linha vermelha gravada no topo do TODO.

As 2 capturas do **Sistema Órion** (PMESP) depositadas sem instrução
ganharam uso: *"a captura do orion é uma ideia de como a tela ficaria,
gostei do formato usado por eles"* — e ao ver a decomposição do
formato (herói de saudação, KPIs com selo de ícone, mini-painéis
vivos, barra colapsável), aprovou **painel + site**.

Entregue no **v1.39.0+2072**: herói no `/admin` (símbolo oficial,
versão + pill ONLINE do `/health`, saudação por período **com o nome
do dono**, relógio GMT-3 vivo, chips build/uptime/stack, card de
Saúde) + 4 KPIs (actions/stack/checks/uptime) das **mesmas fontes das
seções**; site com **chip vivo** (`/app/version` + `/health` públicos
via `od-nav.js` comportamento 4 — ponto cinza até a resposta) e
**números reais** (106 · 3.290 · 9). Identidade OD preservada, dragão
proscrito (a guarda da v1.21.2 pegou o herói novo na suíte —
obedeceu). No caminho, dois defeitos corrigidos: **monitor 8→9**
(Homebox reativado não voltou ao catálogo — stats dizia 8/8 com 9
serviços no ar) e capabilities/site com dados velhos.

Validação: suíte **3292/16 · gate 91,09%**; E2E vivo **32 provas, 0
falhas**; deploy NRestarts=0, journal limpo. Tema residual NÃO foi
tocado (protocolo da linha: exemplo exato do dono antes de mexer —
reiterado). **Commit: 4072c42** (entrega) + registros. Estado:
**v1.39.0+2072 no ar**; Órion fechado; repo (privar+rotacionar),
snapshots, rotação técnica e FlatNotes são os próximos da rodada.

## §9 — O dono manda levar o cabeçalho ao dashboard de todos: formato Órion vira fonte única (v1.39.0→1.39.1+2073)

**Dono (19h05):** *"não entendo porque chamou de heroi, mas ficou
bom. como esse painel não causa qualquer problema ao sistema e
também coloca ele no topo do dashboard para todos os usuários."*

**Sistema:** o nome explicado — "herói" é o termo de design para o
banner grande do topo de uma página (o cartão de abertura, tipo
pôster de filme); pode chamar de cabeçalho. Ordem entendida: levar
o MESMO cabeçalho ao `/dashboard` de todo usuário — **só o formato
viaja**, o administrativo continua atrás do papel admin.

Entregue no **v1.39.1+2073**:

- **`/dashboard` (todos os logados)**: herói (saudação com o
  **próprio nome** de quem entrou via `/auth/me` do dashboard, pill
  ONLINE/DEGRADADO do `/health`, data por extenso, **relógio GMT-3
  vivo**, chips uptime/stack, card Saúde) + os **mesmos 4 KPIs**
  (actions · stack · checks · uptime), antes de "Uso da conta".
- **Refatoração de fonte única** (a duplicação já custou uma
  divergência de paleta quando o tema era por página): o CSS/JS do
  formato saíram do HTML do `/admin` e viraram
  `_FORMATO_ORION_CSS`/`_FORMATO_ORION_JS` (IIFE `window.odFormato`),
  injetados pelo `_com_tema` — **uma fonte, três páginas**,
  idempotência por marca `od-formato-orion`; `/admin` repassa o
  `loadSystem` no refresh, `/dashboard` busca sozinho (health +
  stats + actions com a sessão do localStorage), `/chat` recebe a
  injeção **inócua** (sem `#odOla` o JS sai cedo, markup não existe).
- **Honestidade preservada**: `/dashboard/stats` 403 para usuário
  comum vira "—" (nunca verde de mentira); dragão segue proscrito
  (guarda da v1.21.2 verde); tema NÃO tocado (protocolo §3.8).
- Bump 9/9 (`.env` 1.39.1 fonte real, capabilities fallback,
  `_APP_VERSION_CODE` 2073, pubspec, site badge+card, CHANGELOG
  [1.39.1], README_VERSAO §, ANALISE linha, TODO situação,
  txt.txt reescrito).

Validação: suíte **3293 passed / 16 skipped · gate 91,08%** (+1
teste `test_dashboard_no_formato_orion_para_todos`); **E2E vivo
`/tmp/opencode/e2e_orion1391.py`: 37 provas, 0 falhas** (versão
1.39.1/2073 sha `7f26cb42…`, dashboard com herói+KPIs e script
único, marca da fonte única nas 3 páginas, `/chat` limpo, `/admin`
sem resíduo do JS antigo); deploy **NRestarts=0**, journal limpo;
APKs 1.39.1+2073 publicados em `site/`. **Commit: 2e23cea**
(entrega) + registros. Estado: **v1.39.1+2073 no ar**; segue a
rodada de pendências (rotação dos segredos do histórico →
snapshots p/ HD → FlatNotes → rotação técnica).

## §10 — Dono reporta dois defeitos das entregas do dia: herói sem CSS e rate_limited nas páginas (v1.39.1→1.39.2+2074)

**Dono (19h25):** *"o que quer dizer rate_limited quando tento abrir
as paginas, tenho que atualizar para sumir isso e abrir a pagina"* —
e em seguida: *"o herói não aparece mais como banner, esta como texto
comum no site"*.

**Diagnóstico (sem chute, no vivo):** os dois blocos `<style>` do
`/dashboard` servido **não tinham `.od-hero`**; a marca
`od-formato-orion` que passou no E2E veio do **JS** (comentário). Causa
raiz: no `_com_tema`, a injeção do JS roda antes da guarda do CSS, e o
guarda (`if "od-formato-orion" not in html`) via a marca que o próprio
JS carregava — **o CSS nunca foi injetado** em página alguma desde o
deploy da v1.39.1 (markup pelado = "texto comum"). O E2E e o teste
checavam a *marca*, não as *regras* `.od-hero {` — olho cego meu. O
`rate_limited`: limitador de 30 req/min por IP isentava só `/admin*`;
abrir `/dashboard` custa ~10 requests (HTML, ícones, auth, dados, chip
do herói) — duas aberturas rápidas estouravam a janela. Agravante: o
`/health` roda os **22 checks ao vivo** (9 probes docker, sem cache) e
os chips o chamam em toda abertura.

Entregue no **v1.39.2+2074**:
- **CSS de volta**: marcas separadas por injeção
  (`od-formato-orion-css`/`-js`), cada guarda vigiando a própria; CSS
  antes do JS (ordem do tema). Testes agora travam as **regras**
  `.od-hero {`/`.od-kpis {` (não mais a marca) — o olho cego virou
  guarda.
- **Navegar nunca cai no limiter**: GET de shells de página (`/`,
  `/chat`, `/dashboard`), `/site/*` e `/app/version` fora do
  contador; `/health`, `/message`, `/executa` e `/auth/*` (brute-force)
  **seguem contados** — o limite de 30/min não afrouxou, parou de
  contar o pedido do documento.
- **`/health` com cache de 8s**: rajadas de abertura compartilham uma
  rodada dos 22 probes; agregado nunca com mais de 8s de idade.
- **`/admin` sem busca dupla**: bandeira `odFormatoGerenciado` lida no
  DOMContentLoaded — o herói é alimentado pelo `loadSystem` (−3
  requests/abertura).

Validação: suíte **3295 passed / 16 skipped · gate 91,08%** (+2
testes: `test_navegar_nunca_cai_no_limiter`,
`test_health_tem_cache_curto_para_rajadas`); **E2E vivo
`/tmp/opencode/e2e_orion1392.py`: 21 provas, 0 falhas** — regras
`.od-hero` no `<style>` das duas páginas, marcas separadas, bandeira
só no `/admin`, **35 aberturas de página em rajada com o limite real:
zero 429**, health 22 checks, stats 9/9, `/actions` 106, site
v1.39.2/2074; deploy NRestarts=0, journal limpo; APKs 1.39.2+2074
publicados (sha `7b200c56…`). **Commit: d27e230** (entrega) +
registros. Estado: **v1.39.2+2074 no ar**; os dois defeitos do dia
mortos e enterrados com guarda; segue a rodada de pendências
(rotação dos segredos do histórico → snapshots p/ HD → FlatNotes).

---

## §11 — Rotação dos segredos (17/10, tarde/noite)

Pedido do dono: *"certo vamos rotacionar os segredos"* — ação direta da
decisão aprovada "Privar + rotacionar" (repo público).

**Inventário do dano (antes de mexer em algo):**
- `.env` **nunca** foi rastreado (verificado no histórico todo);
- o único exposto real foi `docker/tools-compose.yaml` até o commit
  `3ed13cc` (15/10): **ADMIN_TOKEN** (painel do Vaultwarden) e
  **HBOX_AUTH_API_KEY_PEPPER**;
- resto da varredura: só arquivos `.example` (placeholders) — nenhum
  outro segredo viveu no git.

**Rotação executada (sem bump de versão — infra pura, precedente do
espelho do cofre; nenhum valor impresso em lugar nenhum):**

| Segredo | Feito | Prova |
|---|---|---|
| `ADMIN_TOKEN` | valor novo + container recriado | `/admin` do Vaultwarden responde 200 na 8480; token novo sincroniza ao cofre pelo espelho |
| `HBOX_AUTH_API_KEY_PEPPER` | valor novo + container recriado | mensagem do binário: rotacionar invalida só as keys |
| `HBOX_API_KEY` | **regenerada** (a antiga morreu com o pepper) | Bearer verificado ao vivo: 2 entidades no inventário, nada apagado |
| `HBOX_API_PASSWORD` | redefinida (a do `.env` **nunca** casou com o banco — argon2id sem pepper) | login `POST /api/v1/users/login` → 200 |
| `OD_API_KEY` | valor novo | nova → 200 em `/actions` e `/health`; **antiga → 401** (invalidação provada) |
| Senha Postgres | `ALTER ROLE` (a role altera a própria senha) | `SELECT 1` com a senha nova; check `database` up |
| `OD_MQTT_PASSWORD` | valor novo no `.env` (od-core já reiniciado com ele) | **falta o broker** — arquivo root (`/etc/mosquitto/passwd`): comando do dono abaixo |

**Perfis técnicos apurados no caminho (gravados em
`integrations/homebox.py`, comentários):**
- login do Homebox espera campo **`username`** (mandar `email` → 401
  enganoso; o log do container denuncia "username or password is empty");
- o login devolve **4 cookies** e `/users/self/*` exige TODOS (só
  `hb.auth.token` → 401);
- senha argon2id **sem pepper** (m=65536, t=3, p=2); o pepper é de API
  keys apenas;
- banco root-owned: redefinição de senha sem sudo = copiar p/ /tmp,
  UPDATE + `wal_checkpoint(TRUNCATE)`, trocar de volta com container
  parado (inventário intacto).
- Achado extra: a senha antiga do Postgres tinha caractere especial — o
  regex da URL engoliu parte dela na gravação; consertado reescrevendo a
  `OD_DB_URL` limpa (user:senha@host/banco preservados).

**Passo que ficou com o dono (sudo, ~10 segundos):**
```
sudo mosquitto_passwd -b /etc/mosquitto/passwd \
  "$(grep '^OD_MQTT_USERNAME=' /home/alex/OmegaDrakon/.env | cut -d= -f2-)" \
  "$(< /tmp/opencode/.mqtt_senha)"
sudo systemctl restart mosquitto
```
(depois disso o od-core reconecta sozinho; se não em 1 min, eu reinicio
ele. Homeassistant **não** usa MQTT — conferido no `.storage` e nos
yamls. Se o ESP-01S tiver MQTT gravado, vai precisar de regravado — o
dono foi avisado.)

**Verificação pós-rotação:** od-core active, NRestarts=0;
`/app/version` 1.39.2/2074; health 22 checks — **todos up exceto
`mqtt` degraded** (esperado: broker ainda com a senha antiga); stats
9/9, `/actions` 106, site anunciando v1.39.2; E2E vivo: única falha é a
prova "tudo verde" (mqtt), que fecha sozinha após o passo do sudo;
stack completa de pé (homebox e vaultwarden recriados, healthy).

**Espelho .env → cofre:** executado no fim — **14/14 gravado+conferiu**
(ADMIN_TOKEN, HBOX_API_KEY, HBOX_API_PASSWORD, HBOX pepper, OD_API_KEY,
OD_DB_URL, OD_MQTT_PASSWORD, OD_VAULT_MASTER, chaves LLM, os 2 bots).
Todos os valores rotacionados estão no cofre do dono; os arquivos
temporários com valores foram apagados (sobrou só
`/tmp/opencode/.mqtt_senha` para o comando do sudo, a apagar depois).

**Fecho (mesma noite):** o dono rodou os dois comandos do sudo (o
`mosquitto_passwd` avisou só sobre o grupo do arquivo — informativo,
versões futuras do mosquitto vão exigir `chown root:root`; documentado,
não atrapalha hoje) e o broker reiniciou às **20:47:37**. Resultado:
**mqtt up** ("conectado" — o od-core reconectou sozinho com a senha
nova), **health 22/22 verde, status up** e **E2E vivo: 21 provas, 0
falhas** (a prova "tudo verde" que era a única pendente fechou).
`/tmp/opencode/.mqtt_senha` apagada. **Rotação total: 100% cumprida —
nenhum segredo do histórico ou técnico vivo.**

## §12 — O sistema ganha snapshot completo nas duas HDs externas (v1.39.2→1.39.3+2075)

**Contexto:** pendência do dono desde 16/10 — *"2 snapshots p/ HD
externo"* —, e no mesmo dia 17/10 ele mesmo preparou o terreno:
unificou o `fstab` das duas HDs (UUID + `noatime` + `nofail` nas
duas, `chown alex`), comprovou gravação sem admin e confirmou
`FSTAB_OK`. Com as duas montadas em `/home/alex/dados` (Mídias, 916 G)
e `/mnt/Arquivos` (Arquivos, 120 G), o snapshot entrou.

**Decisão de desenho (fechada antes do código):**
- **Um serviço por HD, nunca um só** — o `nofail` no fstab significa
  que o dono pode desplugar qualquer uma a qualquer momento. Janela,
  estado, contagem de falhas, alerta no celular e check de saúde são
  **por alvo** (`hd_midias`, `hd_arquivos`); a desconectada degrada
  honestamente no `/health` ("HD desconectada") e a outra não sofre.
  A desconexão entra pela camada `alvo_ausente` (`os.path.ismount`).
- **Snapshot-DIR com rsync `--link-dest`, não tar** — por alvo, um
  diretório datado (`snapshot_od-2026-10-17_2306/`) + retenção **7
  diários + 8 semanais**; a 2ª rodada hardlinka os arquivos inalterados
  (custo ~zero) e restore é "copiar de volta". A retenção reusa
  `calcular_retencao` de `core/backup.py` com **sufixo vazio** —
  adição retrocompatível, o tar do backup de estado ficou intocado.
- **Interface par-a-par com `BackupService`** plugada no
  `build_backups()` do launcher: loops supervisionados, health,
  stats e cards vieram genéricos — zero fiação nova.
- **Fontes, com `/home/alex/3D` PRIMEIRO** (linha vermelha do dono —
  STLs pagos, 1,2 GB): o repo inteiro (com `.git` e `data/captures`),
  `omegadrakon-tools`, `/srv/omegadrakon` e `/etc/fstab`.
  Exclusões justificadas: `.venv`, `backups/`, `data/vector_memory`,
  zim do Kiwix (14 G), `heap_dumps` (2,8 G do OOM), lixo de build —
  e o padrão rsync **passa como veio** (com `/` ancora em qualquer
  nível; forçar âncora nos exclusos matava lixo geral — bug achado
  por teste, não em produção).
- **SQLite volátil** (`homebox.db`, Vaultwarden `db.sqlite3`) sai do
  rsync e entra pelo **backup API do sqlite3**. Bug fatal pego em
  teste: caminho absoluto em `destino / origem` faz o `/` vencer no
  pathlib → o "destino" virava o próprio banco → backup nele mesmo
  **trava para sempre** (fix: reconstruir o relativo parte a parte).

**Três defeitos meus pegos no caminho (todos com teste):**
1. `ConfigHD.de_env()` sem o parâmetro `fontes=` — em produção as
   fontes não viajavam do build (só os defaults do ambiente);
2. o `destino / origem` absoluto do SQLite (o trava-infinito acima);
3. `bytes_transferidos` quebrava com **locale**: o rsync do serviço
   roda em `LANG=en_US.UTF-8` e formata `5,268,052,376` — a regex
   `\d+` capturava só "5". Teste agora usa payload de 5000 bytes
   (o de 8 escondia o bug por não gerar separador de milhar).
   Além disso, `estado["ultimo_bytes"]` passou a guardar o **tamanho
   real do artefato** (o card do painel mostrava 622 KB no lugar de
   5 GB — "bytes movidos na rodada" fica só no `info.json`).

**Ilegíveis sem sudo:** 5 arquivos do `.storage` do Home Assistant
(root:root 600 — o HA regrava como root; chown seria whack-a-mole) e
o rsync 3.2.7 não tem `--skip-bad-files` (é ≥3.4, medido). Solução:
varredura prévia `_achar_ilegiveis` (`os.access`) que exclui por
caminho e emite **recibo** no `info.json` (`ilegiveis`/
`ilegiveis_total`) + `ultimo_ilegiveis` no estado + WARN no journal.
`rc=23` (parcial) nunca mais derruba o snapshot; erro inesperado
novo ainda grita.

**Entrega:** bump **v1.39.3+2075** 9/9 (`.env`, capabilities,
pubspec, server, site ×3 + testes **3.329**, `test_api.py`,
CHANGELOG, README_VERSAO, ANALISE — doutrina "número real no commit":
o site foi ajustado duas vezes até bater com a suíte de verdade).
APK **1.39.3+2075** buildado (`build_apk.sh` com PATH/JDK/SDK) e
publicado; `aapt2` confirma `versionCode='2075' versionName='1.39.3'`.

**Provas vivas (pós-deploy, mesma noite):**
- **1ª rodada real**: `snapshot_od-2026-10-17_2245` nas **duas** HDs
  — **5.268.052.376 bytes** cada, 69,7 s / 88,6 s; `/home/alex/3D`
  inteiro lá dentro (345 itens, 1,2 GB) e `data/captures` junto; o
  `info.json` carrega git `4593e97` + od_version 1.39.3 + recibo dos
  5 ilegíveis.
- **2ª rodada com o código final**: `snapshot_od-2026-10-17_2306` em
  **4,2 s / 5,0 s** — `--link-dest` provado ao vivo: mesmo **inode**
  em `.stl` inalterado (23069050/23069050) e custo incremental de
  **31 MB** no `du` (o primeiro snapshot custa 5,0 G; o segundo, só
  o que mudou). `bytes_transferidos` real = 8.750.583 (>1000 — o
  parse de locale funcionou).
- `/health` **24/24 up** (2 checks novos com detalhe honesto:
  "snapshot_od-2026-10-17_2306, 4.91 GB, há 0.1 h");
  `/dashboard/stats` com **4 chaves** em `backup`; `/app/version`
  **1.39.3/2075**; **E2E vivo: 35 provas, 0 falhas** (as regressões
  do v1.39.2 — CSS do herói + rate_limited — seguem no script como
  guarda permanente).
- Achei e corrigi um bug **do meu E2E** no caminho: a comparação de
  hardlinks saía entre **discos diferentes** (uma snapshot por raiz)
  — o sistema estava perfeito, o script é que comparava o errado.

**Suíte final: 3329 passed / 16 skipped / 0 falha, gate 95,57% ≥ 90.**
`od-core` reiniciado com o código final; estado dos perfis zerado na
mão só para forçar o catch-up da prova (amanhã, 03:40, roda sozinho).
**Fila do snapshot: FECHADA.** Próxima da série de ferramentas do
dono: FlatNotes.

## §13 — FlatNotes analisado, dono manda "ligar": caderno interligado (v1.39.3→1.40.0+2076) — 18/10, madrugada

**Análise entregue (17/10 noite → 18/10), à espera da decisão:** FlatNotes
é um caderno em Markdown **sem banco de dados** (cada nota = um `.md`
numa pasta plana), com busca full-text, tags, wikilinks e REST API —
`dullage/flatnotes` na porta **8200**, `auth=none` (só Tailscale, nunca
no Funnel), bind `omegadrakon-tools/flatnotes` que **já viaja nos
snapshots** desde a v1.39.3. Conta honesta: 13,5 MB de RAM, sem login
= sem segredo novo no `.env`. Como o sistema usaria: actions no padrão
Stirling/Kiwix (status/anota/busca), RAG sobre as notas adiado.

**Ordem do dono: "ligar."** — escopo aprovado exatamente como propus:
2 actions + check de saúde + patch v5.5.5 + testes.

**Execução (18/10, madrugada):**

- **Contrato vivo ANTES de codificar** (regra da casa): `openapi.json`
  do próprio container + round-trip completo — criar → **409 no
  título repetido** → buscar (`term=` e `term=*`) → ler (200/404) →
  apagar minha nota de teste (caderno voltou a `[]`). Depois do patch,
  **revalidado na v5.5.5**: rotas idênticas, mesmos códigos.
- **`integrations/flatnotes.py`** (molde do Kiwix): transporte
  injetável, fábrica lazy `OD_FLATNOTES_URL`, 7 erros tipados
  honestos. **409 = `flatnotes_ja_existe`** com a saída na mensagem;
  `sobrescrever=false` por padrão — atualizar exige flag, vai pelo
  `PATCH` e vem **declarado** (`sobrescrito=true`). Destaques HTML da
  busca → **texto limpo** (regex + `html.unescape`; o `<b>` do
  flatnotes não é o `<b>` do Telegram). `[]` honesto; título com `/`
  recusado (vira caminho `.md`).
- **3 actions** `flatnotes_status/anota/busca` (categoria
  `flatnotes`, só admin — nasce admin pela `permission=nome`, lista
  `user` intocada). **Nenhuma action apaga**: `DELETE` fora do
  catálogo e um teste trava a régua. Check de saúde: `tool_flatnotes`
  já existia no monitor de 9/9.
- **Patch**: compose `v5.5.4` → **`v5.5.5`** (só refresh de deps do
  upstream), container recriado no ar.
- **Bump 9/9** para **v1.40.0+2076**: `.env`, fallback do
  capabilities, pubspec, `_APP_VERSION_CODE`, site (versão ×3, **109
  Actions**, **3.369 Testes**), CHANGELOG, README_VERSAO, ANALISE,
  TODO (situação nova + tabela + §5). APK buildado
  (`JAVA_HOME=/home/alex/jdk`) e publicado: `aapt` **versionCode=2076
  versionName=1.40.0**, sha do `/app/version` idêntico ao arquivo.

**Provas vivas (pós-deploy, round-trip REAL pelo `/executa`):**
`flatnotes_status` **0 notas** → `flatnotes_anota` criou a nota-marcador
**"Interligação do sistema"** no caderno do dono → `flatnotes_busca`
**1 hit** com trecho limpo ("já cobertos pelos snapshots das 2 HDs") →
status **1 nota** + `ultima_modificada` → repetir o título devolveu o
**409 honesto** com a saída na mensagem. `/actions` **109** (as 3
`flatnotes_*` no catálogo), `/health` **24/24** (`tool_flatnotes` up,
2,4 ms), `nomad_tools` **9/9**, journal **0 erros**,
`/app/version` **1.40.0/2076**. **E2E vivo: 41 provas, 0 falhas**
(+6 novas; as regressões do 1.39.2 e as do snapshot seguem como guarda).

**Bug do caminho:** a guarda `test_nenhuma_referencia_a_versao_futura`
acusou meus `v5.5.5` em prosa de código — a casa nunca usa o prefixo
`v` para versão de terceiros em `.py` (kiwix-serve 3.8.1, s-pdf 2.13.1);
reescrito sem o `v`, tag exata fica no compose (que a guarda não lê).
Também: `headers=None` explícito no `Request` do urllib estoura (pego
pelo teste do transporte) e `limite=0` caía no `or` falsy.

**Suíte final: 3369 passed / 16 skipped / 0 falha · gate 95,59%.**
Registros: `session.json` chave `flatnotes_interligado_2026_10_18`,
CHANGELOG/README_VERSAO/ANALISE/TODO atualizados, `txt.txt`
reescreto, Telegram da regra 15 enviado.

**Próxima da série (ordem do dono, "uma por vez"): File Browser (2ª)**
— hoje com login admin/admin ainda a trocar; depois Calibre Web (3ª).
