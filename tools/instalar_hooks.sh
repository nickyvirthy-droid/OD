#!/usr/bin/env bash
# Instala o hook pre-commit da TRAVA DE REESCRITA MACIÇA no repositório atual.
#
# Motivo (18/11): a trava nascida no orquestrador só valia para sessões
# `--sessao`; uma IA trabalhando fora dele podia commitar a regressão
# (caso real: orquestrador.py 1654 -> 251 linhas, sem registro).
#
# O hook é pequeno de propósito: toda a regra mora em
# `tools/trava_reescrita.py` (fonte única, usada também pelo orquestrador).
#
# Escape consciente: `OD_TRAVA_OFF=1 git commit ...` ou `git commit --no-verify`.
set -euo pipefail

repo="$(git rev-parse --show-toplevel)"
git_dir="$(git rev-parse --git-dir)"
hook="$git_dir/hooks/pre-commit"

mkdir -p "$git_dir/hooks"
if [ -e "$hook" ] && ! grep -q "trava_reescrita" "$hook" 2>/dev/null; then
  cp "$hook" "$hook.bak.$(date +%Y%m%d%H%M%S)"
  echo "hook anterior preservado em $hook.bak.*"
fi

# Caminho ABSOLUTO da ferramenta (a do projeto que instalou): faz o hook
# funcionar mesmo em repositório diferente do OmegaDrakon (testes, clones).
tool_abs="$(cd "$(dirname "$0")" && pwd)/trava_reescrita.py"
cat > "$hook" <<HOOK
#!/usr/bin/env bash
# Trava de reescrita maciça (OmegaDrakon) — regra 24.
# Regra em tools/trava_reescrita.py; escape: OD_TRAVA_OFF=1 ou --no-verify.
cd "\$(git rev-parse --show-toplevel)" 2>/dev/null || exit 0
if ! command -v python3 >/dev/null 2>&1; then
  echo "aviso: python3 ausente — trava de reescrita não verificada" >&2
  exit 0
fi
TOOL="$tool_abs"
[ -r "\$TOOL" ] || TOOL="tools/trava_reescrita.py"
[ -r "\$TOOL" ] || { echo "aviso: trava ausente (\$TOOL)" >&2; exit 0; }
exec python3 "\$TOOL" --staged
HOOK
chmod +x "$hook"
echo "hook instalado: $hook"
