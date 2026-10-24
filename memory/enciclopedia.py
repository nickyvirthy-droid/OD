"""
OMEGA DRAKON • MEMORY
Tecnologia que respira.
Módulo: memory/enciclopedia.py
Descrição: Wikipédia offline dentro do chat — a etapa "enciclopédia" do
           orquestrador (ideia do dono em 21/10, parking lot §5: *"'define
           dia' → o chat responde que dia é uma duração de 24 horas"*).

           - **Posição no pipeline:** DEPOIS do RAG local e SÓ quando o
             RAG local não achou nada (`block == ""`). A memória interna
             (docs/ + knowledge/ + iniciar/) é a primeira fonte — se ela
             respondeu, a enciclopédia fica de fora (duas fontes de
             verdade brigando no mesmo prompt é receita para alucinação).
           - **Consulta:** os termos de conteúdo da pergunta (o MESMO
             filtro `termos_da_consulta` do RAG — stopwords PT/EN fora)
             entram no `/search` do kiwix-serve; o hit escolhido é o de
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
from memory.rag import termos_da_consulta

log = get_logger("omega.memory.enciclopedia")

LIMITE_PADRAO_CHARS = 1200
TIMEOUT_BUSCA_S = 8.0
TIMEOUT_ARTIGO_S = 10.0
MINIMO_OVERLAP_TITULO = 1  # ao menos 1 termo da pergunta no título

CABECALHO_BLOCO = (
    "Wikipédia offline (referência externa — use apenas se for pertinente; "
    "se não for, responda normalmente):"
)

_TOKENS_TITULO = re.compile(r"[a-zà-ú0-9]+")

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


def _assunto_da_pergunta(pergunta: str) -> str:
    """Remove os verbos-guia iniciais (até 3, encadeáveis).

    'define dia' → 'dia'; 'o que é a fotossíntese?' → 'a fotossíntese?'
    (o termos_da_consulta seguinte já tira 'a' e '?').
    """
    texto = pergunta or ""
    for _ in range(3):
        novo = _PREFIXO_PERGUNTA.sub("", texto, count=1)
        if novo == texto:
            break
        texto = novo
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
        artigo, livro = self._titulo_direto(cliente, consulta)

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
        self, cliente: Any, consulta: str
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
            if (artigo.get("texto") or "").strip():
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
        acervos.sort(
            key=lambda a: 0 if str(a.get("idioma") or "").lower().startswith("pt")
            else 1
        )
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
            titulo_tokens = _tokens_titulo(str(hit.get("titulo") or ""))
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
