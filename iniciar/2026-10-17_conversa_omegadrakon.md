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
