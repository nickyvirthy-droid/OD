"""
OMEGA DRAKON • UTILITÁRIO OPERACIONAL
Tecnologia que respira.
Módulo: vault_env_mirror.py
Descrição: Espelha as credenciais do `.env` para o cofre do sistema
           (Vaultwarden, conta de serviço) — pedido do dono em 17/10/2026
           ("coloque todas as senhas do .env no cofre").

           Regras firmadas:
           - O `.env` CONTINUA a fonte de bootstrap (regra da entrega
             v1.35.0: o boot do od-core nunca depende do cofre). Este
             script COPIA, nunca remove — nada sai do .env.
           - Nenhum valor de segredo é impresso, logado ou commitado:
             a verificação compara em memória e imprime só o NOME da
             chave + "confere"/"ERRO".
           - Reexecutável (idempotente): mesmo nome = mesmo item, o
             `guardar` do VaultClient atualiza sem duplicar. Rode de
             novo após qualquer mudança no .env (ex.: rotação §8.5).
           - Lista de credenciais EXPLÍCITA (allowlist): se um dia
             nascer uma chave nova com cara de segredo no .env e não
             estiver aqui, o script avisa em vez de deixar passar.

Uso:
    .venv/bin/python vault_env_mirror.py           # grava + verifica
    .venv/bin/python vault_env_mirror.py --check   # só verifica

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - integrations/vault.py (VaultClient.guardar/obter/listar)
  - .env (credenciais do sistema — fora do git)
  - CHANGELOG [1.35.0] (cofre do sistema interligado)
"""

from __future__ import annotations

import re
import sys
from typing import Any

from integrations.vault import VaultError, client_padrao

# ---------------------------------------------------------------------------
# Credenciais do .env que SÃO segredo (allowlist explícita + notas)
# ---------------------------------------------------------------------------

CREDENCIAIS: dict[str, str] = {
    "TELEGRAM_BOT_TOKEN": "Bot token (Telegram do sistema).",
    "OD_API_KEY": "API key da REST do od-core (header X-API-Key).",
    "OD_DB_URL": "URL de conexão PostgreSQL da Database Layer (contém a senha).",
    "GEMINI_API_KEY": "Chave de API do Google Gemini.",
    "OPENAI_API_KEY": "Chave de API da OpenAI.",
    "OPENAI_API_KEY2": "Segunda chave de API da OpenAI.",
    "GROQ_API_KEY": "Chave de API da Groq.",
    "OD_MQTT_PASSWORD": "Senha do usuário MQTT (username via OD_MQTT_USERNAME).",
    "TELEGRAM_BOT_LEGADO_TOKEN": (
        "ATENÇÃO: token vazado do bot legado — rotação §8.5 PENDENTE do dono."
    ),
    "OD_TELEGRAM_USUARIOS_TOKEN": (
        "Bot @Nexus_Nicky_bot — papel 'usuários' (💬 chat das peças, "
        "🔑 registro de posse; divisão de bots do dono, 20/10)."
    ),
    "OD_TELEGRAM_MONITOR_TOKEN": (
        "Bot @nicky_monitor_bot — papel 'monitor' (notifier, presença, "
        "face, resumo do orquestrador; divisão de bots do dono, 20/10)."
    ),
    "HBOX_AUTH_API_KEY_PEPPER": "Pepper do Homebox (HBOX_AUTH_API_KEY_PEPPER).",
    "HBOX_API_KEY": (
        "API key estática do Homebox (inventário do dono; Bearer, sem "
        "expiração; criada na reativação de 17/10 — v1.38.0)."
    ),
    "HBOX_API_PASSWORD": (
        "Senha da conta do sistema omega-drakon@omegadrakon.local do "
        "Homebox (só para administração; o sistema usa a API key)."
    ),
    "ADMIN_TOKEN": "ADMIN_TOKEN do painel do Vaultwarden.",
    "OD_FILEBROWSER_PASSWORD": (
        "Senha do admin do File Browser (caixa de arquivos do dono; "
        "rotacionada pelo sistema em 18/10 — o admin/admin nunca "
        "funcionou; v1.41.0)."
    ),
    "OD_CALIBRE_PASSWORD": (
        "Senha do admin do Calibre Web (biblioteca de e-books do dono; "
        "a admin/admin123 documentada no compose estava VIVA — trocada "
        "pelo sistema em 19/10)."
    ),
    "OD_VAULT_MASTER": (
        "Master da conta de serviço od-sistema — auto-referência do cofre "
        "(fica cifrada aqui; o bootstrap continua no .env)."
    ),
}

# username pareado (valor de OUTRA chave do .env)
USERNAME_DE: dict[str, str] = {"OD_MQTT_PASSWORD": "OD_MQTT_USERNAME"}

NOTA_PADRAO = (
    "Espelho do .env (17/10/2026, v1.38.0 — +2 chaves do Homebox) — o .env "
    "continua sendo a fonte de bootstrap e o boot nunca depende do cofre. "
    "Não apagar sem decisão do dono."
)

# Padrão de nome que EM GERAL indica segredo — usado só para AVISAR sobre
# chave nova fora da allowlist (fail-safe futuro, nunca adivinha).
_RE_SEGREDO = re.compile(r"TOKEN|SECRET|PASSWORD|PASSWD|PEPPER|_API_KEY$|^API_KEY", re.I)

# Chaves com nome de segredo que NÃO são credencial (identificador/flag).
_NAO_E_SEGREDO = {
    "OD_TELEGRAM_ADMINS",  # chat ids (660518870), identificador
}


def ler_env(caminho: str = ".env") -> dict[str, str]:
    """Chave=valor do .env (sem comentários)."""
    valores: dict[str, str] = {}
    with open(caminho, encoding="utf-8", errors="replace") as fh:
        for linha in fh:
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            chave, _, valor = linha.partition("=")
            valores[chave.strip()] = valor.strip().strip('"').strip("'")
    return valores


def _username_de(chave: str, valores: dict[str, str]) -> str:
    origem = USERNAME_DE.get(chave, "")
    return valores.get(origem, "") if origem else ""


def main(argv: list[str]) -> int:
    so_check = "--check" in argv
    valores = ler_env()

    # Avisos: segredo potencial fora da allowlist / allowlist sem valor
    avisos: list[str] = []
    for chave in valores:
        if chave in _NAO_E_SEGREDO or chave in CREDENCIAIS:
            continue
        if _RE_SEGREDO.search(chave):
            avisos.append(
                f"AVISO: {chave} parece segredo e NÃO está na allowlist — "
                "adicione em CREDENCIAIS se for credencial."
            )
    alvo = {k: v for k, v in CREDENCIAIS.items() if valores.get(k)}
    for chave in CREDENCIAIS:
        if not valores.get(chave):
            avisos.append(f"AVISO: {chave} ausente/vazio no .env — item não tratado.")

    for aviso in avisos:
        print(aviso)
    if not alvo:
        print("Nada a espelhar (nenhuma credencial da allowlist no .env).")
        return 1

    cliente = client_padrao()
    if cliente is None:
        print("Cofre não configurado: OD_VAULT_SERVER/EMAIL/MASTER faltam no .env.")
        return 1

    gravados = 0
    conferem = 0
    falhas: list[str] = []
    for chave in sorted(alvo):
        valor = alvo[chave]
        nota = f"{NOTA_PADRAO} {CREDENCIAIS[chave]}"
        try:
            if so_check:
                item = cliente.obter(chave)
                confere = item.get("password") == valor
                acao = "conferiu" if confere else "DIVERGENTE"
            else:
                cliente.guardar(
                    chave,
                    valor,
                    username=_username_de(chave, valores),
                    nota=nota,
                )
                item = cliente.obter(chave)
                confere = item.get("password") == valor
                acao = "gravado+conferiu" if confere else "gravado+DIVERGENTE"
                gravados += 1
        except VaultError as exc:
            print(f"{chave:30s} FALHA [{exc.codigo}]")
            falhas.append(chave)
            continue
        print(f"{chave:30s} {acao}")
        if confere:
            conferem += 1
        else:
            falhas.append(chave)

    try:
        itens = cliente.listar()
    except VaultError as exc:
        print(f"listar falhou [{exc.codigo}]: {exc.mensagem}")
        itens = []

    print(
        f"\nResumo: {conferem}/{len(alvo)} conferem · "
        f"{'gravados' if not so_check else 'checados'}={gravados if not so_check else len(alvo)} · "
        f"cofre={len(itens)} itens"
    )
    print("Títulos: " + ", ".join(i["nome"] for i in itens))
    if falhas:
        print("FALHAS: " + ", ".join(falhas))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
