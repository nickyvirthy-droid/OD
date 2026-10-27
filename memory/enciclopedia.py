"""
OMEGA DRAKON • MEMORY
Tecnologia que respira.
Módulo: memory/enciclopedia.py
Descrição: Wikipédia offline dentro do chat — a etapa "enciclopédia" do
           orquestrador (ideia do dono em 21/10, parking lot §5: *"'define
           dia' → o chat responde que dia é uma duração de 24 horas"*).

           - **Posição no pipeline (régua do dono, 26/10):** pergunta de
             FATO/definição (`eh_pergunta_de_fato`) consulta ESTA fonte
             ANTES do acervo da casa; o acervo só entra se a fonte não
             achar artigo. Fora de pergunta de fato vale a ordem antiga
             (memória interna > enciclopédia). Uma fonte por prompt —
             duas fontes de verdade brigando é receita para alucinação.
           - **Travas (medição viva 26/10):** (1) acervo PT é o primeiro
             a ser tentado — a ordem antiga comparava `"por"` com `"pt"` e
             o EN ganhava sempre, devolvendo desambiguação (`"Sol or SOL
             may refer to:"`) e até o artigo ERRADO ("Clorofila" = a
             banda mexicana, não o pigmento); (2) página de
             DESAMBIGUAÇÃO é recusada; (3) o título resolvido tem que
             CASAR com o assunto — ao menos 1 termo em comum E no
             máximo 1 token extra (ou 2 em comum); piso medido ao vivo
             em 27/10: *"o que é o sol, em uma frase?"* devolveu "O
             império no qual o sol nunca se põe" (1 em comum, 4 extras)
             e o piso de 1 overlap deixava passar. Sem artigo bom =
             `block ""` honesto (artigo errado pior que silêncio).
           - **Sem fonte:** quando nem esta fonte nem o acervo têm nada
             sobre a pergunta de fato, o orquestrador injeta a nota
             honesta (etapa 4.6b) em vez de deixar o modelo local
             inventar.
           - **Consulta:** o ASSUNTO da pergunta vai cru para o `/search`
             depois de 3 limpezas medidas (prefixo de verbo-guia,
             enquadramento wh/stopword/verbo à esquerda e instrução
             final "em uma frase") — *"quem descobriu a penicilina?"*
             busca `penicilina`, não a frase inteira (27/10). Os termos
             são os do MESMO
             filtro `termos_da_consulta` do RAG — stopwords PT/EN fora) —
             e o hit escolhido é o de
             **maior overlap de título** com os termos da pergunta (o
             ranking cru do kiwix é fraco — apurado ao vivo: "day" devolve
             "Day After Day" antes de "Day"), com piso honesto: sem overlap
             de título, NADA é injetado (artigo errado pior que nenhum).
           - **Idioma (apuração viva 24/10):** o acervo principal é a
             Wikipédia EN (`wikipedia_en_all_mini`); termos em pt casam
             pouco — por isso o ZIM PT (`wikipedia_pt_all_mini`, 1,99 M
             artigos) entrou no container od-kiwix (decisão do dono,
             24/10). O kiwix-serve busca nos DOIS acervos; o overlap de
             título decide qual artigo serve, independentemente do idioma.
           - **Orçamento:** o bloco é limitado a `max_chars` (default
             1200 chars ≈ 300 tokens) com truncamento DECLARADO
             (…[cortado]) — a mesma honestidade do `ler()` do cliente.
           - **Lazy e inofensivo por desenho:** o cliente Kiwix nasce na
             1ª consulta (`client_padrao()`); qualquer erro/timeout vira
             `block == ""` + warn — o chat responde normalmente sem
             enciclopédia, nunca com exceção no caminho do orquestrador.
           - **Papel:** o acervo é público (Wikipédia) — todos os papéis
             podem receber o bloco (diferente do RAG interno, que é
             admin). A(vis)ibilidade interna não entra aqui.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - integrations/kiwix.py (KiwixClient.buscar/ler + erros tipados)
  - memory/rag.py (termos_da_consulta — filtro de stopwords da casa)
  - core/orchestrator.py etapa 4.6 (chamada quando rag_block == "")

Decisões registradas (ver CHANGELOG):
  - Piso de overlap de TÍTULO (não de trecho): o kiwix-serve 3.8 devolve
    hit de página qualquer para qualquer termo; sem a trava, "define dia"
    injetaria "Día tras día (album)" — artigo errado pior que silêncio
  - Sem tradução automática pt→en: o ZIM PT cobre o português; traduzir
    com LLM custaria uma chamada por pergunta e alucinaria termos
  - A enciclopédia entra só com RAG vazio: memória interna > enciclopédia
    na ordem de verdade da casa
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Any, Callable, Optional

from core.logger import get_logger
from memory.rag import STOPWORDS_PT, termos_da_consulta

log = get_logger("omega.memory.enciclopedia")

LIMITE_PADRAO_CHARS = 1200
TIMEOUT_BUSCA_S = 8.0
TIMEOUT_ARTIGO_S = 10.0
MINIMO_OVERLAP_TITULO = 1  # ao menos 1 termo da pergunta no título

CABECALHO_BLOCO = (
    "Wikipédia offline (referência externa — use apenas se for pertinente; "
    "se não for, responda normalmente):"
)

# Etapa 4.6b — pergunta de FATO sem artigo em nenhuma das duas fontes:
# a nota honesta entra no prompt no lugar do silêncio (o modelo local
# inventava o fato — 6x na auditoria de 24/10). Um erro de fonte não é
# licença para alucinar.
NOTA_SEM_FONTE = (
    "Nota de fonte: não há artigo disponível sobre este assunto no acervo "
    "interno nem na Wikipédia offline (fonte ausente ou indisponível). "
    "Não apresente fato sem fonte como certo — diga honestamente que não "
    "há referência confiável disponível."
)

_TOKENS_TITULO = re.compile(r"[a-zà-ú0-9]+")

# Página de desambiguação não é resposta: "Sol or SOL may refer to: …"
# (EN) e "Clorofila (desambiguação)" (PT) listam SENTIDOS, não explicam
# o assunto — injetá-la no prompt devolve a lista no lugar da resposta
# (medição viva 26/10, quando o acervo EN era tentado primeiro).
_RE_DESAMBIGUACAO = re.compile(
    r"(?:\((?:desambiguação|desambiguacao|desambiguation|disambiguation)\)"
    r"|may refer to|pode referir[- ]se|podem referir[- ]se)",
    re.IGNORECASE,
)

# Prefixos de pergunta factual (verbos-guia): "define dia", "o que é a
# fotossíntese", "quem foi napoleão…". Sem esta limpeza "define" entrava
# como termo de BUSCA (não é stopword) e o ranking do kiwix procurava a
# palavra-verba em vez do assunto — medido na prova viva de 24/10:
#   "define dia" → busca "define dia" → "Dia sideral" (artigo errado)
#   com a limpeza → busca "dia" → artigo "Dia" direto pelo título.
_PREFIXO_PERGUNTA = re.compile(
    r"^\s*(?:"
    r"o que (?:é|e|era|foi|são|eram)|"
    r"quem (?:é|e|foi|era)|"
    r"onde (?:fica|está|estava|foi)|"
    r"quando (?:foi|nasceu|aconteceu)|"
    r"como (?:funciona|se faz|faz)|"
    r"qual (?:é|e|era|foi)|quais (?:são|eram)|"
    r"define|defina|explique|expliquem|significa|significam|"
    r"me fale de|fale de|me conta|conta sobre|sabe|curiosidades de|"
    r"a diferença entre|diferença entre"
    r")\s+",
    re.IGNORECASE,
)


# Aberturas interrogativas de FATO — cobrem o que o verbo-guia de
# _PREFIXO_PERGUNTA não alcança ("quem descobriu a penicilina?",
# "onde fica paris?", "o que acontece com…"). Quantidade/contagem
# ("quantas pessoas estão conectadas?") fica DE FORA de propósito:
# não é fato de enciclopédia, é dado do sistema (fastpath de rede).
_ABERTURA_FATO = re.compile(
    r"^\s*(?:o que\b|quem\b|onde\b|quando\b|qual\b|quais\b)",
    re.IGNORECASE,
)

# -- Enquadramento da pergunta (limpeza 27/10) ------------------------------
# Verbos-guia que descrevem a PERGUNTA, não o assunto: "quem DESCOBRIU a
# penicilina" → o assunto é a penicilina. Medido ao vivo 27/10: sem esta
# limpeza a busca era de 3 termos ("quem descobriu penicilina") e o
# kiwix-serve não achava o artigo "Penicilina" — a resposta saía do
# acervo da casa em vez da Wikipédia.
_VERBOS_GUIA: frozenset[str] = frozenset(
    """
    descobriu descobriram descobrem descobria
    inventou inventaram inventa inventava
    criou criaram cria criava
    fundou fundaram funda fundava
    projetou projetaram projeta
    desenvolveu desenvolveram desenvolve
    escreveu escreveram escreve
    compôs compuseram compõe
    causou causaram causa
    ganhou ganharam ganha
    venceu venceram vence
    nasceu nasceram nasce
    faleceu faleceram morreu morreram morre
    governou governaram governa
    reinou reinaram reina
    descreve descrevem descreveram
    representa representam significa significam
    existe existem existiu aconteceu aconteceram
    começou começaram terminou terminaram
    ficou ficaram fica
    está estava estavam estão
    """.split()
)

#: Palavra que NÃO abre assunto: stopword da casa + guia + "quem"
#: (o "quem" não está em STOPWORDS_PT e inflava a busca como termo).
_ENQUADRAMENTO: frozenset[str] = frozenset(STOPWORDS_PT) | _VERBOS_GUIA | {
    "quem"
}

_PONTUACAO = re.compile(r"[^\w]+")

#: Instrução no FINAL da frase — medida na prova viva de 27/10: \
#: "… em uma frase" / "… responda com uma frase" entravam como termos de
#: BUSCA ("sol responda frase") e o artigo certo nem era tentado.
_RE_INSTRUCAO_FINAL = re.compile(
    r"(?:(?:,\s*|\s+)responda\b[^!?]*"
    r"|,?\s*em\s+\d+\s+fras(?:e|es)"
    r"|,?\s*(?:com|em)\s+uma\s+frase"
    r")\s*[?!.]*\s*$",
    re.IGNORECASE,
)


def eh_pergunta_de_fato(pergunta: str) -> bool:
    """É pergunta de FATO/definição? (ordem das fontes, régua 26/10).

    `True` = a enciclopédia é consultada ANTES do acervo da casa (etapa
    4.6); `False` = vale a ordem antiga (memória interna > enciclopédia).
    Critério é a ABERTURA da frase: verbo-guia ("define dia", "o que é…")
    ou interrogativo factual ("quem descobriu…"). Saudação, comando e
    pedido de ação não casam — sem artigo, sem consulta.
    """
    texto = (pergunta or "").strip()
    if not texto:
        return False
    return bool(_PREFIXO_PERGUNTA.match(texto)) or bool(
        _ABERTURA_FATO.match(texto)
    )


def _eh_desambiguacao(titulo: str, texto: str = "") -> bool:
    """É página de desambiguação? (título OU abertura do corpo).

    Checagem barata e determinística: título com marcador, ou as
    primeiras 300 chars do corpo começando pela lista de sentidos.
    """
    if _RE_DESAMBIGUACAO.search(titulo or ""):
        return True
    inicio = (texto or "")[:300].casefold()
    return (
        "may refer to" in inicio
        or "pode referir" in inicio
        or "desambigu" in inicio
    )


def _eh_pt(idioma: Any) -> bool:
    """O acervo é português? `pt`, `pt-BR`… e `por` (ISO 639-2 — é o
    código que o catálogo do kiwix-serve devolve para o ZIM PT).
    """
    cod = str(idioma or "").strip().lower()
    return cod in ("pt", "por") or cod.startswith(("pt-", "pt_"))


def _corta_enquadramento(texto: str) -> str:
    """Come o enquadramento à esquerda: wh + stopwords + verbo-guia.

    'quem descobriu a penicilina?' → 'penicilina?'; 'como está o sistema'
    → 'o sistema'. Um verbo-guia só é comido se RESTAR conteúdo depois
    ('o que é a descoberta?' mantém 'descoberta' — lá o verbo É o
    assunto), senão a pergunta ficava sem consulta nenhuma.
    """
    palavras = texto.split()
    i = 0
    while i < len(palavras):
        nucleo = _PONTUACAO.sub("", palavras[i]).casefold()
        if not nucleo:
            i += 1
            continue
        if nucleo in _VERBOS_GUIA and not termos_da_consulta(
            " ".join(palavras[i + 1 :])
        ):
            break
        if nucleo in _ENQUADRAMENTO:
            i += 1
            continue
        break
    return " ".join(palavras[i:])


def _assunto_da_pergunta(pergunta: str) -> str:
    """O ASSUNTO — o que a busca do kiwix procura (e o que a trava de
    título é comparado).

    Três limpezas, todas medidas ao vivo (24-27/10):

    1. prefixo de verbo-guia, até 3 encadeáveis: 'define dia' → 'dia';
    2. enquadramento à esquerda (wh + stopwords + verbo-guia):
       'quem descobriu a penicilina?' → 'penicilina?';
    3. instrução no final: 'o que é o sol, em uma frase?' → 'o sol,'.

    (o `termos_da_consulta` seguinte tira pontuação e stopwords.)
    """
    texto = pergunta or ""
    for _ in range(3):
        novo = _PREFIXO_PERGUNTA.sub("", texto, count=1)
        if novo == texto:
            break
        texto = novo
    texto = _RE_INSTRUCAO_FINAL.sub("", _corta_enquadramento(texto))
    return texto.strip()


@dataclass(slots=True)
class ResultadoEnciclopedia:
    """Resultado de uma consulta — o block vai para o prompt (ou "")."""

    consulta_original: str = ""
    consulta_final: str = ""
    titulo: str = ""
    caminho: str = ""
    chars: int = 0
    truncado: bool = False
    block: str = ""
    candidatos: int = 0
    descartados_sem_overlap: int = 0
    recusados: int = 0  # desambiguação ou título fora do assunto
    erro: str = ""  # código tipado do Kiwix ("" = sem erro)


def _tokens_titulo(texto: str) -> set[str]:
    """Tokens de um título para o overlap (mesmo normalizador do floor)."""
    return {
        t for t in _TOKENS_TITULO.findall((texto or "").casefold()) if len(t) > 2
    }


class Enciclopedia:
    """Consulta ao Kiwix Serve para o prompt do chat (fallback do RAG).

    Attributes:
        fabrica_cliente: fábrica do KiwixClient (injetável p/ testes;
            default = integrations.kiwix.client_padrao, lazy).
        max_chars: orçamento do bloco de referência.
    """

    def __init__(
        self,
        *,
        fabrica_cliente: Optional[Callable[[], Any]] = None,
        max_chars: int = LIMITE_PADRAO_CHARS,
    ) -> None:
        self._fabrica = fabrica_cliente
        self.max_chars = max(200, int(max_chars))
        self._lock = threading.Lock()
        self._cache_livros: Optional[list[dict[str, Any]]] = None

    def _cliente(self) -> Any:
        if self._fabrica is not None:
            return self._fabrica()
        from integrations.kiwix import client_padrao

        return client_padrao()

    # -- Consulta ------------------------------------------------------------

    def consult(self, pergunta: str) -> ResultadoEnciclopedia:
        """Busca o artigo e monta o bloco de referência (ou "" — honesto).

        Qualquer falha (rede, parse, artigo vazio) devolve block == ""
        com `erro` tipado: o chat segue sem enciclopédia, nunca com
        exceção no caminho do orquestrador.
        """
        resultado = ResultadoEnciclopedia(consulta_original=pergunta or "")
        termos = termos_da_consulta(_assunto_da_pergunta(pergunta or ""))
        if not termos:
            # Saudação/comando não é pergunta factual — sem consulta.
            return resultado
        consulta = " ".join(termos)
        resultado.consulta_final = consulta

        try:
            cliente = self._cliente()
        except Exception as exc:  # noqa: BLE001 — degradação honesta
            resultado.erro = "kiwix_falhou"
            log.warn(
                "Enciclopédia: cliente indisponível",
                erro=f"{type(exc).__name__}: {exc}",
            )
            return resultado

        # 1ª tentativa: artigo canônico pelo TÍTULO direto (best-effort,
        # nunca lança). O ranking do /search é fraco — medido na prova
        # viva de 24/10: "dia" devolve "Sexta-feira" primeiro e o artigo
        # "Dia" nem aparece no top-8; /content/<livro>/<Título> serve o
        # artigo certo quando ele existe.
        artigo, livro = self._titulo_direto(cliente, consulta, resultado)

        if artigo is None:
            # 2ª tentativa: busca cascata (PT → EN) com overlap de título.
            try:
                busca, livro = self._buscar(cliente, consulta)
            except Exception as exc:  # noqa: BLE001 — degradação honesta
                codigo = getattr(exc, "codigo", "kiwix_falhou")
                resultado.erro = str(codigo)
                log.warn(
                    "Enciclopédia: busca falhou (chat segue sem bloco)",
                    consulta=consulta,
                    erro=f"{type(exc).__name__}: {exc}",
                )
                return resultado

            hits = list(busca.get("resultados") or [])
            resultado.candidatos = len(hits)
            escolhido = self._melhor_hit(consulta, hits, resultado)
            if escolhido is None:
                return resultado

            try:
                artigo = cliente.ler(
                    escolhido["caminho"],
                    max_chars=self.max_chars,
                    timeout_s=TIMEOUT_ARTIGO_S,
                )
            except Exception as exc:  # noqa: BLE001 — degradação honesta
                codigo = getattr(exc, "codigo", "kiwix_falhou")
                resultado.erro = str(codigo)
                log.warn(
                    "Enciclopédia: leitura falhou (chat segue sem bloco)",
                    caminho=escolhido.get("caminho", ""),
                    erro=f"{type(exc).__name__}: {exc}",
                )
                return resultado

        texto = (artigo.get("texto") or "").strip()
        if not texto:
            resultado.erro = "kiwix_resposta_invalida"
            return resultado

        titulo = (artigo.get("titulo") or consulta.title()).strip()

        # Travas finais (26/10) — valem para os DOIS caminhos (título
        # direto pode ser um redirect): sem artigo BOM, block "" honesto
        # (artigo errado pior que silêncio).
        if _eh_desambiguacao(titulo, texto):
            resultado.recusados += 1
            log.info("Enciclopédia: desambiguação recusada", titulo=titulo)
            return resultado
        assunto_tokens = _tokens_titulo(_assunto_da_pergunta(pergunta or ""))
        titulo_tokens = _tokens_titulo(titulo)
        if assunto_tokens:
            overlap = len(assunto_tokens & titulo_tokens)
            extras = len(titulo_tokens - assunto_tokens)
            # "Casa com o assunto": ao menos 1 termo em comum E no
            # máximo 1 token que não esteja no assunto (ou 2 em comum).
            # Piso de 1 overlap sozinho deixava passar "O império no
            # qual o sol nunca se põe" para "o que é o sol?" (27/10).
            if overlap == 0 or (extras > 1 and overlap < 2):
                resultado.recusados += 1
                log.info(
                    "Enciclopédia: título fora do assunto recusado",
                    titulo=titulo,
                    assunto=_assunto_da_pergunta(pergunta or ""),
                    overlap=overlap,
                    extras=extras,
                )
                return resultado

        truncado = bool(artigo.get("truncado"))
        resultado.titulo = titulo
        resultado.caminho = str(artigo.get("caminho") or "")
        resultado.truncado = truncado
        resultado.block = (
            f"{CABECALHO_BLOCO}\n"
            f"[{titulo}] {texto}"
        )
        resultado.chars = len(resultado.block)
        log.info(
            "Enciclopédia no prompt",
            titulo=titulo,
            chars=resultado.chars,
            truncado=truncado,
            candidatos=resultado.candidatos,
            livro=livro,
        )
        return resultado

    def _titulo_direto(
        self,
        cliente: Any,
        consulta: str,
        resultado: ResultadoEnciclopedia,
    ) -> tuple[Optional[dict[str, Any]], str]:
        """Tenta o artigo canônico pelo TÍTULO antes de buscar (best-effort).

        'dia' → /content/<livro>/Dia. 404 = não existe → tenta o próximo
        livro → (None, "") e a busca cascata assume. Qualquer outra falha
        também devolve (None, ""): a busca tem tratamento de erro próprio
        (um servidor fora avisa UMA vez, não N).
        """
        livros = self._livros(cliente)
        if not livros or not consulta:
            return None, ""
        # 'napoleão bonaparte' → 'Napoleão_Bonaparte' (títulos da wiki
        # são Title Case com underscores; exceções caem na busca).
        titulo = consulta.title().replace(" ", "_")
        for livro in livros:
            content_id = str(livro.get("content_id") or livro.get("nome") or "")
            if not content_id:
                continue
            try:
                artigo = cliente.ler(
                    f"{content_id}/{titulo}",
                    max_chars=self.max_chars,
                    timeout_s=TIMEOUT_ARTIGO_S,
                )
            except Exception:  # noqa: BLE001 — best-effort (404 = normal)
                continue
            texto_direto = (artigo.get("texto") or "").strip()
            if not texto_direto:
                continue
            if _eh_desambiguacao(str(artigo.get("titulo") or ""), texto_direto):
                # Lista de sentidos não responde a pergunta — passa
                # reto para o próximo acervo / busca cascata.
                resultado.recusados += 1
                log.info(
                    "Enciclopédia: desambiguação no título direto",
                    titulo=str(artigo.get("titulo") or titulo),
                    livro=content_id,
                )
                continue
            log.info(
                "Enciclopédia: artigo por título direto",
                titulo=str(artigo.get("titulo") or titulo),
                livro=content_id,
            )
            return artigo, content_id
        return None, ""

    # -- Cascata de acervos (PT primeiro, depois EN) -------------------------

    def _livros(self, cliente: Any) -> list[dict[str, Any]]:
        """Acervos em ordem de preferência: PT primeiro, depois os demais.

        Descobertos pelo catálogo (status) e CACHADOS por processo — o
        content-id só sai de lá (o <name> do feed não é o valor que o
        `books.name=` aceita, apurado ao vivo em 24/10). Se o catálogo
        falhar, lista vazia = busca sem filtro (comportamento antigo —
        serve quando há um ZIM só ou um único idioma).
        """
        with self._lock:
            if getattr(self, "_cache_livros", None) is not None:
                return self._cache_livros
        try:
            acervos = list((cliente.status(timeout_s=5.0) or {}).get("acervos") or [])
        except Exception as exc:  # noqa: BLE001 — degradação honesta
            log.warn(
                "Enciclopédia: catálogo indisponível (busca sem filtro)",
                erro=f"{type(exc).__name__}: {exc}",
            )
            # NÃO cachear a falha: kiwix-serve sempre tem ≥1 livro vivo;
            # cache negativo aqui seria permanente (sem filtro + 2 idiomas
            # = 400 para sempre). Reprove no próximo turno.
            return []
        # PT primeiro (o chat fala pt-BR). O catálogo devolve "por"
        # (ISO 639-2) e a ordem antiga comparava com "pt" — "por" empatava
        # com "eng" e a ordem do catálogo (EN primeiro) vencia, devolvendo
        # desambiguação e artigo errado (apuração viva 26/10).
        acervos.sort(key=lambda a: 0 if _eh_pt(a.get("idioma")) else 1)
        with self._lock:
            self._cache_livros = acervos
        return acervos

    def _buscar(self, cliente: Any, consulta: str) -> tuple[dict[str, Any], str]:
        """Busca em cascata: um livro por vez (idiomas distintos somem 400).

        PT primeiro (o chat fala pt-BR), EN como reserva (mini PT tem
        1,99 M de artigos vs 18 M do EN). O PRIMEIRO livro que devolve
        hit com overlap de título vence — sem hit em nenhum, devolve a
        última busca vazia (block "" honesto).
        """
        livros = self._livros(cliente)
        ultima: dict[str, Any] = {"pattern": consulta, "resultados": []}
        ultimo_livro = ""
        if not livros:
            # Sem catálogo: busca global (ok com 1 ZIM / 1 idioma).
            return cliente.buscar(consulta, quantidade=8, timeout_s=TIMEOUT_BUSCA_S), ""
        for livro in livros:
            content_id = str(livro.get("content_id") or livro.get("nome") or "")
            if not content_id:
                continue
            busca = cliente.buscar(
                consulta,
                quantidade=8,
                timeout_s=TIMEOUT_BUSCA_S,
                livro=content_id,
            )
            ultima, ultimo_livro = busca, content_id
            hits = list(busca.get("resultados") or [])
            if hits:
                termos = set(termos_da_consulta(consulta))
                if any(
                    termos & _tokens_titulo(str(h.get("titulo") or ""))
                    for h in hits
                ):
                    return busca, content_id
        return ultima, ultimo_livro

    # -- Escolha do hit ------------------------------------------------------

    @staticmethod
    def _melhor_hit(
        consulta: str,
        hits: list[dict[str, Any]],
        resultado: ResultadoEnciclopedia,
    ) -> Optional[dict[str, Any]]:
        """Hit de MAIOR overlap de título com os termos da pergunta.

        O ranking cru do kiwix-serve devolve páginas tangenciais (apurado
        ao vivo: "day" → "Day After Day" antes de "Day"); o overlap de
        título é a trava honesta — sem ao menos 1 termo em comum, nada é
        injetado (artigo errado pior que silêncio). Empate de overlap:
        vence o título MAIS PRECISO (menos tokens extras — "Day" ganha
        de "Day After Day").
        """
        termos = set(termos_da_consulta(consulta))
        melhor: Optional[dict[str, Any]] = None
        melhor_chave: Optional[tuple[int, int]] = None
        for hit in hits:
            titulo_hit = str(hit.get("titulo") or "")
            if _eh_desambiguacao(titulo_hit):
                # Sentidos listados = resposta nenhuma; o próximo hit
                # com overlap é melhor (trava 2, 26/10).
                resultado.recusados += 1
                continue
            titulo_tokens = _tokens_titulo(titulo_hit)
            overlap = len(termos & titulo_tokens)
            extras = len(titulo_tokens - termos)  # tokens fora da pergunta
            chave = (overlap, -extras)  # maior overlap; empate → menos extras
            if overlap <= 0:
                continue
            if melhor_chave is None or chave > melhor_chave:
                melhor_chave = chave
                melhor = hit
        if melhor is None or melhor_chave is None:
            resultado.descartados_sem_overlap = len(hits)
            return None
        return melhor
