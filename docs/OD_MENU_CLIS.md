# `od` — menu e sessão persistente de CLIs de código

> **Status:** vigente — 2026-11-18
> **Script:** `tools/od.sh` v1.2.0 (canônico, versionado neste repositório)
> **Atalho:** `~/bin/od` → symlink para `tools/od.sh`
> **Dependência do sistema:** `tmux` (3.4 nesta máquina)

`od` é o menu do **OmegaDrakon** para abrir CLIs de código. O nome anterior,
`oc`, vinha de *OpenCode* e foi aposentado para não confundir o comando do
sistema com uma CLI específica.

> **Colisão conhecida:** existe `/usr/bin/od` (octal dump, coreutils). Como
> `~/bin` vem antes no `PATH`, `od` agora executa este menu. Se algum script
> precisar do octal dump, use o caminho absoluto `/usr/bin/od`.

## 1. O que é

`od` abre CLIs de código dentro de uma **sessão tmux persistente**. Se o SSH
cair, a CLI continua rodando no servidor; rodar `od` de novo reconecta na
mesma janela, com scrollback.

Não é uma janela gráfica: o "window" do nome vem do **tmux** (uma janela por
CLI dentro da mesma sessão).

Sem argumentos, `od` mostra o menu com:

- as CLIs **instaladas** (numeradas, disponíveis para abrir);
- as CLIs **não instaladas** (com o comando de instalação);
- atalhos de shell, status, janelas, log, doctor e encerramento.

## 2. Uso

```bash
od                 # menu
od opencode        # abre uma CLI específica numa janela própria
od kilo
od openclaude
od status          # sessão viva + janelas
od lista           # nomes das janelas
od log kilo        # últimas 300 linhas da janela
od shell           # shell dentro da sessão
od doctor          # caminho/versão de cada CLI + o que falta instalar
od instalar claude # instrução de instalação
od reinicia kilo   # recria só a janela da CLI
od fecha kilo      # encerra só a janela
od sai             # desconecta sem matar (Ctrl-b d)
od mata            # encerra a sessão inteira
```

O menu usa o diretório atual como `cwd` da janela; `od <cli>` também.

## 3. CLIs detectadas nesta máquina (2026-11-18)

| Menu | Caminho | Versão | Como é aberta |
|---|---|---|---|
| OpenCode | `~/.npm-global/bin/opencode` | 2.3.2 | TUI |
| Kilo Code | `~/.npm-global/lib/node_modules/@kilocode/cli/bin/kilo` | 7.8.27 | TUI |
| Freebuff | `/usr/local/bin/freebuff` | 0.2.36 | TUI |
| Aider | `OmegaDrakon/.venv/bin/aider` | 0.86.2 | TUI |
| Antigravity (`agy`) | `~/.local/bin/agy` | 1.5.9 | TUI |
| OpenClaude (portátil) | `~/OpenClaude-Portable-main/start.sh` | engine 0.32.0 | `start.sh --offline` |
| OpenClaw | `/opt/omegadrakon/builders/openclaw/bin/openclaw` | 2026.7.1-2 | `openclaw chat` |
| Open Interpreter | `/opt/omegadrakon/builders/open-interpreter/.venv/bin/interpreter` | 0.4.3 | TUI |
| Claude Code | `~/.npm-global/bin/claude` | 2.1.327 | TUI |
| OpenAI Codex | `~/.npm-global/bin/codex` | 0.170.0 | TUI |
| Gemini CLI | `~/.npm-global/bin/gemini` | 0.68.0 | TUI |
| Qwen Code | `~/.npm-global/bin/qwen` | 0.28.0 | TUI |
| Crush | `~/.npm-global/bin/crush` | 0.101.0 | TUI |
| Cline | `~/.npm-global/bin/cline` | 3.0.74 | TUI |

> **Node:** as CLIs npm desta lista pedem Node >=20 (Claude/Codex >=22), mas o
> Node do sistema é 18.19.1 (EOL). Foi instalado um **Node 22.23.5 por
> usuário** em `~/.local/opt/node`; o `.bashrc` e o próprio `od` colocam esse
> `bin` à frente no `PATH`, e o `od` também atualiza o ambiente do servidor
> tmux (`tmux set-environment -g PATH`). O Node do sistema não foi alterado.

## 4. CLIs ausentes (hoje: nenhuma)

Inventário fechado em **14/14 disponíveis**. O prefixo global do npm desta
máquina é `/usr/local`, sem permissão de escrita; por isso qualquer instalação
futura deve usar `--prefix "$HOME/.npm-global"`.

| CLI | Pacote npm |
|---|---|
| Claude Code | `@anthropic-ai/claude-code` |
| OpenAI Codex | `@openai/codex` |
| Gemini CLI | `@google/gemini-cli` |
| Qwen Code | `@qwen-code/qwen-code` |
| Crush | `@charmland/crush` |
| Cline | `cline` |

O menu continua mostrando `od instalar <cli>` para qualquer uma que seja
removida; ao instalar de novo, a detecção (candidatos em
`$HOME/.npm-global/bin` + `PATH`) a recoloca sozinha em "disponível".

## 5. Variáveis de ambiente

| Variável | Efeito |
|---|---|
| `OD_SESSION` | nome da sessão tmux (padrão `clis`) |
| `OD_SHELL` | shell da janela `shell` |
| `OD_<CLI>_BIN` | força o binário (ex.: `OD_KILO_BIN=/caminho/kilo`) |
| `OD_OPENCLAUDE_DIR` | pasta do OpenClaude Portable |

## 6. Como adicionar outra CLI

1. Resolva o binário em `resolver_bin` (candidatos + `PATH`) e crie a variável
   `OD_<NOME>_BIN`.
2. Adicione o nome em `CLIS`, `rotulo`, `binario` e, se precisar de
   argumentos, em `comando_cli`.
3. Se estiver ausente, registre o pacote em `pacote_npm` para o menu mostrar a
   instrução.

## 7. Correções de 2026-11-18

- **Renomeado de `oc` para `od`:** o nome antigo vinha de OpenCode. Script
  agora em `tools/od.sh`, atalho `~/bin/od`, variáveis `OD_*`; o symlink
  `~/bin/oc` foi removido.
- **OpenCode:** a instalação anterior estava interrompida (pacotes de
  plataforma truncados + postinstall não rodado). Reinstalado com
  `npm install -g @opencode/cli@latest --prefix "$HOME/.npm-global"` →
  `opencode v2.3.2`.
- **OpenClaude Portable:** o switchboard salva a chave da NVIDIA em
  `OPENAI_API_KEY`, mas o engine exige `NVIDIA_API_KEY` ao usar
  `--provider nvidia-nim`. `start.sh` passou a exportar
  `NVIDIA_API_KEY="${NVIDIA_API_KEY:-$OPENAI_API_KEY}"`.
- **Claude Code:** instalado pelo menu (`od instalar claude` → npm com
  `--prefix "$HOME/.npm-global"`), versão 2.1.327.
- **Codex, Gemini, Qwen, Crush e Cline:** instalados no mesmo prefixo
  (versões 0.170.0, 0.68.0, 0.28.0, 0.101.0 e 3.0.74). O Gemini quebrava no
  Node 18 (`SyntaxError: Invalid regular expression flags`), resolvido com o
  Node 22 por usuário.
- **Inventário final:** `od doctor` → **14 instaladas, 0 ausentes**; todas
  abertas em janela tmux até a tela inicial (login/trust/onboarding).
