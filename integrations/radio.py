"""
OMEGA DRAKON • CORE
Tecnologia que respira.
Módulo: integrations/radio.py
Descrição: frases da locução da rádio Nicky (integração do legado Nicky
           Locutor, 27/10) — as 4 famílias de frases do webhook do
           AzuraCast (música passada, próxima, intro de curiosidade e
           assinaturas) vivem NO MESMO banco do OD (Postgres em produção,
           SQLite nos testes) em vez do MySQL CasaOS do original.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - analise/Nicky Locutor/nicky-locutor/setup_db.py (frases originais,
    mantidas literalmente — a voz da rádio é do legado)

Decisões registradas (ver CHANGELOG):
  - Banco único do OD (regra do dono 27/10: "use o banco que já temos"):
    `frases_passado`, `frases_proxima`, `intro_curiosidade` e
    `assinaturas` via storage.Database (pg8000 em produção)
  - `garantir_frases()` idempotente: cria as tabelas e só povoa as
    VAZIAS — re-rodar nunca duplica frase (o DELETE em massa do script
    original do legado apagaria frases do rádio no ar)
  - Nunca lança no caminho do webhook: erro de banco devolve lista vazia
    (a rádio toca sem vinheta em vez de parar)
"""

from __future__ import annotations

from typing import Any, Optional

from core.logger import get_logger

__signature__ = "OD // CORE"

log = get_logger("omega.integrations.radio")

TABELAS: tuple[str, ...] = (
    "frases_passado",
    "frases_proxima",
    "intro_curiosidade",
    "assinaturas",
)

#: As 4 famílias de frases da rádio Nicky — legado Nicky Locutor
#: (setup_db.py), literais. Placeholders: {a}/{t} = artista/título da
#: música passada; {a_n}/{t_n} = da próxima; intro entra colada na
#: curiosidade do AzuraCast.
FRASES_PASSADO: tuple[str, ...] = (
    "Você conferiu aqui na Nicky: {t}, com {a}.",
    "Essa foi {a}, interpretando o sucesso {t}.",
    "Na Nicky, você curtiu {t}, na voz de {a}.",
    "Acabamos de ouvir {a}, com {t}.",
    "Seguimos com o melhor da música. Você ouviu {t}, com {a}.",
    "Recordar é viver: {t}, na voz de {a}.",
    "Sucesso carimbado na Nicky: {t}, com {a}.",
    "Esta foi a obra de {a}, com o título {t}.",
    "Revivemos agora {t}, um grande momento de {a}.",
    "Som de qualidade na sua Nicky: {t}, com {a}.",
    "Você acompanhou a batida de {a}, em {t}.",
    "Aumentando o volume com {a} e seu sucesso {t}.",
    "Na sequência da Nicky, ouvimos {t}, com {a}.",
    "Essa marcou época! {t}, na voz de {a}.",
    "Você vibrou com {a}, ao som de {t}.",
    "Mais uma joia musical: {t}, com {a}.",
    "Tudo de bom na Nicky. Você ouviu {t}, com {a}.",
    "Energia pura com {a} e a faixa {t}.",
    "Direto da nossa playlist: {t}, com {a}.",
    "A Nicky apresentou: {t}, de {a}.",
    "Marcando presença no seu dia: {t}, com {a}.",
    "Clássico da programação: {t}, com {a}.",
    "Sentindo a música: {t}, na interpretação de {a}.",
    "O som que você ama: {t}, com {a}.",
    "Sempre bom ouvir {a} e o sucesso {t}.",
    "No ar, a vibração de {a} em {t}.",
    "Aqui na Nicky, a música não para. Você ouviu {t}, de {a}.",
    "Batida perfeita de {a} na canção {t}.",
    "Essa entrou para a história: {t}, com {a}.",
    "Sentimento e melodia com {a} e {t}.",
    "A trilha sonora da sua vida: {t}, com {a}.",
    "Inconfundível: {a} interpretando {t}.",
    "Simplesmente marcante: {t}, na voz de {a}.",
    "A gente adora esse som: {t}, com {a}.",
    "Garantia de sucesso: {a} e o hit {t}.",
    "Na Nicky, o som é diferenciado. Você ouviu {t}, de {a}.",
    "Classe e estilo com {a}, em {t}.",
    "A Nicky toca o que você gosta: {t}, com {a}.",
    "Um momento especial com {a} e {t}.",
    "Invasão musical com {t}, na voz de {a}.",
)

FRASES_PROXIMA: tuple[str, ...] = (
    " Em instantes tem {a_n} chegando com {t_n}.",
    " Não saia daí, logo mais ouviremos {t_n} na voz de {a_n}.",
    " Na sequência, preparamos {a_n} para você curtir {t_n}.",
    " Fique ligado, a próxima atração é {t_n}, com {a_n}.",
    " Vem aí: {a_n}, trazendo o sucesso {t_n}.",
    " Logo após, teremos {t_n} com {a_n} aqui na Nicky.",
    " Continue sintonizado, pois {a_n} já está na agulha com {t_n}.",
    " A seguir, mais um grande sucesso: {t_n}, com {a_n}.",
    " Não mude de estação, {a_n} chega já já com {t_n}.",
    " Preparados para a próxima? Vem aí {t_n}, na voz de {a_n}.",
)

INTROS_CURIOSIDADE: tuple[str, ...] = (
    "Você sabia? ",
    "Curiosidade sobre este sucesso: ",
    "Vale a pena destacar que ",
    "Uma nota sobre esse som: ",
    "A título de curiosidade: ",
    "Olha que interessante: ",
    "Para quem gosta de história: ",
    "Informação exclusiva sobre essa faixa: ",
)

ASSINATURAS: tuple[str, ...] = (
    "Nicky: A frequência que cria o seu mundo.",
    "Você está na Nicky, a rádio que entende seu estilo.",
    "Nicky, conectada com você em todos os momentos.",
    "A sua melhor companhia é aqui na Nicky.",
    "Sintonize na inovação. Sintonize na Nicky.",
    "O seu mundo gira em torno da nossa frequência. Nicky.",
)

#: Família -> frases (ordem = ordem de TABELAS).
_CONTEUDO: dict[str, tuple[str, ...]] = {
    "frases_passado": FRASES_PASSADO,
    "frases_proxima": FRASES_PROXIMA,
    "intro_curiosidade": INTROS_CURIOSIDADE,
    "assinaturas": ASSINATURAS,
}


def garantir_frases(db: Any) -> dict[str, int]:
    """Cria as 4 tabelas se não existirem e povoa só as VAZIAS.

    Idempotente por design: re-rodar devolve {tabela: 0} sem duplicar.
    Retorna contagem de linhas por tabela (independente de ter populado).
    """
    populadas: dict[str, int] = {}
    for tabela in TABELAS:
        db.create_table(tabela, {"id": "INTEGER PRIMARY KEY", "texto": "TEXT"})
        linhas = db.query(f"SELECT COUNT(*) AS n FROM {tabela}")[0]["n"]
        if not linhas:
            frases = _CONTEUDO[tabela]
            db.executemany(
                f"INSERT INTO {tabela} (texto) VALUES (?)",
                [(f,) for f in frases],
            )
            linhas = len(frases)
            log.info("Frases da rádio povoadas", tabela=tabela, linhas=linhas)
        populadas[tabela] = int(linhas)
    return populadas


def frase_aleatoria(db: Any, tabela: str) -> str:
    """Uma frase ao acaso da família ("" se banco indisponível/vazio).

    O webhook da rádio roda em cima desta função: qualquer falha de banco
    devolve "" e o locutor simplesmente não fala aquela parte — a rádio
    nunca para por causa de uma frase.
    """
    if tabela not in _CONTEUDO:
        log.warn("Tabela de frases desconhecida", tabela=tabela)
        return ""
    try:
        # RANDOM() é o idioma dos DOIS backends (SQLite e Postgres) — o
        # legado usava RAND() do MySQL; aqui cai sempre no mesmo nome.
        valor = db.scalar(f"SELECT texto FROM {tabela} ORDER BY RANDOM() LIMIT 1")
        return str(valor or "")
    except Exception as exc:  # pragma: no cover — banco fora do ar
        log.warn("Banco de frases indisponível", tabela=tabela, error=str(exc))
        return ""


class _Vazio(dict):
    """dict que devolve "" para placeholder não informado — o texto nunca
    vai para o ar com "{a}" cru na fala da rádio."""

    def __missing__(self, key: str) -> str:
        return ""


def frase_formatada(
    db: Any, tabela: str, **substituicoes: Optional[str]
) -> str:
    """Frase aleatória com os placeholders preenchidos.

    Placeholders ausentes na chamada viram "" (o legado estourava
    KeyError com música sem artista; a rádio fala a frase mesmo assim).
    """
    texto = frase_aleatoria(db, tabela)
    if not texto:
        return ""
    try:
        return texto.format_map(
            _Vazio({k: (v or "") for k, v in substituicoes.items()})
        )
    except (KeyError, IndexError, ValueError) as exc:
        log.warn("Placeholder não bateu", tabela=tabela, error=str(exc))
        return texto
