"""
OMEGA DRAKON • INTEGRATIONS
Tecnologia que respira.
Módulo: integrations/calibre.py
Descrição: biblioteca de e-books do dono — Calibre Web interligado (3ª da
           análise "uma por vez" de FlatNotes/File Browser/Calibre, ordem
           do dono em 19/10: "configurar e interligar").

           Duas peças, um desenho:
           - **Fonte da verdade = Google Drive "Biblioteca" do dono**
             (22 pastas temáticas, 363 arquivos, 1,35 GB — apurado ao
             vivo 19/10). O espelho local (`core/biblioteca_drive.py`)
             traz para o disco; o `calibredb` (calibre 9.16 já instalado
             em /home/alex/opt — achado: o dono mesmo instalou em 08/10)
             monta a biblioteca real (metadata.db) que o Calibre Web lê.
           - **calibredb = CLI de verdade do sistema, com LEDGER nosso**:
             a primeira importação (19/10, `--automerge ignore`) provou ao
             vivo que o calibre DESCARTA em silêncio arquivos cujo título
             embutido (metadata do PDF) colide com livro já cadastrado —
             156 arquivos de conteúdo DIFERENTE ficaram fora ("The
             following books were not added as they already exist… see
             --duplicates"). A régua do dono não aceita livro escondido,
             então o contrato é nosso:
             · `.calibre_ledger.json` na inbox (caminho → tamanho) é o
               "já importado" — resync idempotente SEM dedup por título
               (re-rodar NÃO duplica registro);
             · só o que o ledger não viu vai no `add` com
               `-d --automerge new_record` — colisão de título vira
               registro PRÓPRIO (nada escondido, nada sobrescrito, nada
               apagado).
           - **OPDS = o contrato do leitor de e-book** (sondado ao vivo
             em 19/10): `/opds/` traz 15 seções de navegação;
             `/opds/search/<termo>` (e `?query=`) devolve TODOS os
             matches numa página só; download é
             `/opds/download/<id>/<fmt>/` com Basic Auth
             (OD_CALIBRE_USER + OD_CALIBRE_PASSWORD — a senha nunca
             aparece em log/erro/retorno); 401 = credencial recusada,
             feed fora de Atom vira `opds_xml_invalido`. Tudo em stdlib
             LAZY (`opds_status`, `opds_busca`), erros tipados `opds_*`.
           - O binário vem de OD_CALIBREDB (default /home/alex/opt/calibredb);
             se não existir, a importação degrada com erro tipado honesto
             (`calibre_ferramenta_ausente`) — nunca o boot.
           - Runner injetável (testes), timeout declarado, stdout SEM
             segredos (o calibredb não recebe senha nenhuma — a biblioteca
             é pasta local).

           O cliente OPDS do Calibre Web (leitura do catálogo: status,
           busca) vive neste mesmo módulo — contrato apurado ao vivo
           depois que a biblioteca é apontada no dbconfig.

Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Código associado:
  - core/biblioteca_drive.py (espelho Drive → inbox)
  - tools/actions/actions.py (actions calibre_*)
  - docker/tools-compose.yaml (od-calibre-web, bind duplo 8420)
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
from typing import Any, Callable, Iterable, Optional

from core.logger import get_logger

log = get_logger("omega.integrations.calibre")

CALIBREDB_PADRAO = "/home/alex/opt/calibredb"
BIBLIOTECA_PADRAO = "/home/alex/omegadrakon-tools/books"
INBOX_PADRAO = "/home/alex/omegadrakon-tools/biblioteca-drive"
LEDGER_NOME = ".calibre_ledger.json"
_TIMEOUT_IMPORT_S = 900.0  # lote de novos — margem folgada


class CalibreError(Exception):
    """Erro tipado e honesto da integração Calibre."""

    def __init__(self, codigo: str, mensagem: str) -> None:
        super().__init__(f"{codigo}: {mensagem}")
        self.codigo = codigo
        self.mensagem = mensagem


def _env(nome: str, padrao: str) -> str:
    return (os.environ.get(nome) or "").strip() or padrao


def caminhos_espelho() -> dict[str, str]:
    """Caminhos do espelho da biblioteca (env com default do servidor)."""
    return {
        "inbox": _env("OD_CALIBRE_INBOX", INBOX_PADRAO),
        "pasta_id": _env("OD_CALIBRE_PASTA_ID", ""),
    }


def _arquivos_da_inbox(inbox: pathlib.Path) -> list[pathlib.Path]:
    """Arquivos da árvore da inbox (pastas temáticas do dono).

    O ledger (`.calibre_ledger.json`) e sobras de download atômico
    (`.part`) NÃO são livros — ficam de fora do argv do calibredb.
    """
    return sorted(
        p
        for p in inbox.rglob("*")
        if p.is_file() and p.name != LEDGER_NOME and not p.name.endswith(".part")
    )


def carregar_ledger(inbox: pathlib.Path | str) -> dict[str, int]:
    """Ledger do inbox: {caminho_relativo: tamanho_bytes} já na biblioteca.

    Ausente/corrompido → vazio (a importação avisa com `ledger_novo`:
    sem saber o que já entrou, ela NÃO re-importa às cegas — reclama).
    """
    caminho = pathlib.Path(inbox) / LEDGER_NOME
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(dados, dict):
        return {}
    return {
        str(k): int(v)
        for k, v in dados.items()
        if isinstance(v, int | float) and int(v) >= 0
    }


def salvar_ledger(inbox: pathlib.Path | str, ledger: dict[str, int]) -> pathlib.Path:
    """Grava o ledger ATÔMICO (.part → replace) — interrupção nunca corrompe."""
    caminho = pathlib.Path(inbox) / LEDGER_NOME
    parcial = caminho.with_name(LEDGER_NOME + ".part")
    parcial.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(parcial, caminho)
    return caminho


def semear_ledger(inbox: pathlib.Path | str, caminhos: Iterable[str]) -> dict[str, int]:
    """Marca caminhos relativos como JÁ PRESENTES na biblioteca (migração).

    Usado na primeira corrida: arquivos cujo conteúdo já está no
    `/books` (gêmeo por tamanho, medido) entram no ledger sem passar
    pelo calibredb — a resync futura não duplica o que já existe.
    Tamanho vem do arquivo em disco (fonte da verdade do espelho).
    """
    raiz = pathlib.Path(inbox)
    ledger = carregar_ledger(raiz)
    semeados = 0
    for rel in caminhos:
        arquivo = raiz / rel
        if arquivo.is_file() and rel not in ledger:
            ledger[rel] = arquivo.stat().st_size
            semeados += 1
    if semeados:
        salvar_ledger(raiz, ledger)
    log.info("Ledger semeados", novos=semeados, total=len(ledger))
    return ledger


def importar_da_inbox(
    *,
    inbox: Optional[str] = None,
    biblioteca: Optional[str] = None,
    calibredb: Optional[str] = None,
    runner: Optional[Callable[..., Any]] = None,
    timeout_s: float = _TIMEOUT_IMPORT_S,
) -> dict[str, Any]:
    """Importa na biblioteca Calibre só o que o LEDGER ainda não viu.

    Contrato (decidido e provado ao vivo em 19/10):
    - **Ledger primeiro**: `novos = arquivos fora do ledger` (ou com
      tamanho mudado no Drive). Ledger ausente → NUNCA re-importa às
      cegas (`calibre_ledger_ausente`): 729 arquivos virariam 729
      registros duplicados — reclamar é o honesto.
    - **Lote único** `calibredb add -d --automerge new_record <novos>`:
      `-d` força entrada mesmo com título já cadastrado, `new_record`
      separa colisões DENTRO do lote. Nada escondido, nada sobrescrito,
      nada apagado (régua do dono).
    - **Ledger só cresce depois de rc == 0** (sucesso total do lote) —
      falha no meio não marca nada; a próxima rodada re-tenta tudo que
      faltou. Atômico (.part → replace).
    - `calibredb add` não é recursivo em pasta (flag do --help,
      confirmado ao vivo) — por isso o argv leva os arquivos.
    """
    exe = calibredb or _env("OD_CALIBREDB", CALIBREDB_PADRAO)
    raiz_inbox = pathlib.Path(inbox or _env("OD_CALIBRE_INBOX", INBOX_PADRAO))
    raiz_bib = pathlib.Path(biblioteca or _env("OD_CALIBRE_BIBLIOTECA", BIBLIOTECA_PADRAO))
    if not pathlib.Path(exe).exists():
        raise CalibreError(
            "calibre_ferramenta_ausente",
            f"calibredb não encontrado em {exe} — instale o calibre ou "
            "aponte OD_CALIBREDB.",
        )
    if not raiz_inbox.is_dir():
        raise CalibreError(
            "calibre_inbox_ausente",
            f"inbox espelhada não existe em {raiz_inbox} — rode o sync antes.",
        )
    arquivos = _arquivos_da_inbox(raiz_inbox)
    if not arquivos:
        return {
            "ok": True,
            "arquivos": 0,
            "novos": 0,
            "ja_no_ledger": 0,
            "adicionados": [],
            "nota": "inbox vazia — nada a importar (sync ainda não baixou?).",
        }

    ledger = carregar_ledger(raiz_inbox)
    if not ledger:
        raise CalibreError(
            "calibre_ledger_ausente",
            f"ledger {LEDGER_NOME} ausente/vazio em {raiz_inbox} — importar "
            "sem saber o que já existe duplicaria a biblioteca inteira. "
            "Rode a semeadura (migração) ou aponte a inbox certa.",
        )
    novos: list[pathlib.Path] = []
    ja_no_ledger = 0
    for arquivo in arquivos:
        rel = str(arquivo.relative_to(raiz_inbox))
        tam = arquivo.stat().st_size
        if ledger.get(rel) == tam:
            ja_no_ledger += 1
        else:
            novos.append(arquivo)
    if not novos:
        return {
            "ok": True,
            "arquivos": len(arquivos),
            "novos": 0,
            "ja_no_ledger": ja_no_ledger,
            "adicionados": [],
            "nota": "ledger em dia — nada novo desde a última importação.",
        }

    biblioteca_real = raiz_bib
    biblioteca_real.mkdir(parents=True, exist_ok=True)
    cmd = [
        exe,
        "add",
        "--with-library",
        str(biblioteca_real),
        "-d",
        "--automerge",
        "new_record",
        *[str(p) for p in novos],
    ]
    execucao = runner or subprocess.run
    try:
        proc = execucao(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env={**os.environ, "HOME": os.environ.get("HOME", "/home/alex")},
        )
    except subprocess.TimeoutExpired as exc:
        raise CalibreError(
            "calibre_import_timeout",
            f"calibredb não terminou em {timeout_s:.0f}s ({exc}).",
        ) from exc
    saida = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        rabo = " | ".join(s.strip() for s in saida.strip().splitlines()[-3:])
        raise CalibreError(
            "calibre_import_falhou",
            f"calibredb devolveu rc={proc.returncode}: {rabo or 'sem saída'}",
        )
    id_list: list[int] = []
    for bloco in re.findall(r"Added book ids?:\s*([0-9, ]+)", saida):
        id_list.extend(int(x) for x in bloco.replace(" ", "").split(",") if x)

    # rc == 0: só AGORA o ledger cresce (para os novos; os pré-existentes
    # já estavam marcados). Tamanho do disco = valor gravado.
    for arquivo in novos:
        ledger[str(arquivo.relative_to(raiz_inbox))] = arquivo.stat().st_size
    salvar_ledger(raiz_inbox, ledger)

    log.info(
        "Importação da biblioteca do dono",
        arquivos=len(arquivos),
        novos=len(novos),
        adicionados=len(id_list),
        ledger_total=len(ledger),
    )
    return {
        "ok": True,
        "arquivos": len(arquivos),
        "novos": len(novos),
        "ja_no_ledger": ja_no_ledger,
        "adicionados": id_list,
        "biblioteca": str(biblioteca_real),
    }


# ---------------------------------------------------------------------------
# OPDS — o que o leitor de e-book do dono realmente enxerga
# ---------------------------------------------------------------------------

_ATOM = {"a": "http://www.w3.org/2005/Atom"}


def _opds_cfg() -> tuple[str, str, str]:
    """(base_url, usuario, senha) do Calibre Web — só do .env.

    A senha sai daqui apenas para o header Authorization; nunca entra em
    log, mensagem de erro ou retorno de action (régua do dono).
    """
    base = (_env("OD_CALIBRE_URL", "") or "").rstrip("/")
    usuario = _env("OD_CALIBRE_USER", "admin") or "admin"
    senha = _env("OD_CALIBRE_PASSWORD", "")
    if not base or not senha:
        raise CalibreError(
            "opds_config_ausente",
            "OD_CALIBRE_URL/OD_CALIBRE_PASSWORD vazios no .env — sem "
            "endereço/credencial o OPDS não é alcançável.",
        )
    return base, usuario, senha


def _opds_get(caminho: str, *, timeout: float = 12.0) -> tuple[int, bytes]:
    """GET autenticado no OPDS. Erros tipados: `opds_auth` (401),
    `opds_http` (outro status), `opds_indisponivel` (rede/timeout)."""
    import base64
    import urllib.error
    import urllib.request

    base, usuario, senha = _opds_cfg()
    req = urllib.request.Request(base + caminho)
    cred = base64.b64encode(f"{usuario}:{senha}".encode("utf-8")).decode("ascii")
    req.add_header("Authorization", "Basic " + cred)
    try:
        resposta = urllib.request.urlopen(req, timeout=timeout)
        return int(resposta.status), resposta.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise CalibreError(
                "opds_auth",
                f"Calibre Web recusou as credenciais (401) em {caminho} — "
                "conferir OD_CALIBRE_USER/OD_CALIBRE_PASSWORD no .env.",
            ) from exc
        raise CalibreError(
            "opds_http", f"OPDS devolveu HTTP {exc.code} em {caminho}."
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CalibreError(
            "opds_indisponivel",
            f"Calibre Web não respondeu em {base}{caminho}: {exc}.",
        ) from exc


def _opds_feed(corpo: bytes) -> Any:
    """Bytes -> Element Atom. Fora de Atom vira `opds_xml_invalido`."""
    import xml.etree.ElementTree as ET

    try:
        return ET.fromstring(corpo)
    except ET.ParseError as exc:
        raise CalibreError(
            "opds_xml_invalido", f"Resposta do OPDS não é Atom válido: {exc}."
        ) from exc


def _extrair_entradas(feed: Any, *, base: str) -> tuple[list[dict[str, Any]], bool]:
    """Entradas Atom -> dicts usáveis + flag `tem_mais` (link rel=next).

    Contrato vivo (sonda 19/10): livro traz links de acquisition com
    href `/opds/download/<id>/<fmt>/` (absolutizado com a base);
    navegação (raiz) não tem acquisition — fica de fora aqui.
    """
    entradas: list[dict[str, Any]] = []
    for entry in feed.findall("a:entry", _ATOM):
        titulo = (entry.findtext("a:title", "", _ATOM) or "").strip()
        autor = (entry.findtext("a:author/a:name", "", _ATOM) or "").strip()
        formatos: dict[str, str] = {}
        book_id: Optional[int] = None
        for link in entry.findall("a:link", _ATOM):
            rel = link.get("rel") or ""
            href = link.get("href") or ""
            if "acquisition" not in rel or "/download/" not in href:
                continue
            # /opds/download/<id>/<fmt> -> ["/opds/download", "<id>", "<fmt>"]
            partes = href.rstrip("/").rsplit("/", 2)
            if len(partes) == 3 and partes[0].endswith("/download"):
                try:
                    book_id = int(partes[1])
                except ValueError:
                    book_id = None
                formatos[partes[2].lower()] = base + href
        if not formatos:
            continue  # entrada de navegação, não é livro
        entradas.append(
            {
                "id": book_id,
                "titulo": titulo or "(sem título)",
                "autor": autor or "Desconhecido",
                "formatos": sorted(formatos),
                "baixar": formatos,
            }
        )
    tem_mais = any(
        (link.get("rel") or "") == "next" for link in feed.findall("a:link", _ATOM)
    )
    return entradas, tem_mais


def _inventario_local() -> dict[str, Any]:
    """Inventário exato sem rede: metadata.db (leitura) + ledger da inbox.

    Parte quebrada vira nota honesta — o resto da resposta continua de pé.
    """
    import sqlite3

    bib = pathlib.Path(_env("OD_CALIBRE_BIBLIOTECA", BIBLIOTECA_PADRAO))
    inbox = pathlib.Path(_env("OD_CALIBRE_INBOX", INBOX_PADRAO))
    out: dict[str, Any] = {}
    db = bib / "metadata.db"
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            out["livros"] = int(con.execute("SELECT COUNT(*) FROM books").fetchone()[0])
            out["formatos"] = {
                fmt: int(n)
                for fmt, n in con.execute(
                    "SELECT format, COUNT(*) FROM data GROUP BY format "
                    "ORDER BY 2 DESC"
                )
            }
        finally:
            con.close()
    except (OSError, sqlite3.Error) as exc:
        out["livros"] = None
        out["nota_biblioteca"] = f"metadata.db ilegível em {db}: {exc}"
    try:
        arquivos = _arquivos_da_inbox(inbox)
        ledger = carregar_ledger(inbox)
        out["espelho"] = len(arquivos)
        if not ledger:
            out["pendentes"] = None
            out["nota_ledger"] = (
                f"ledger {LEDGER_NOME} ausente em {inbox} — pendências "
                "desconhecidas (sem semeadura, resync recusa)"
            )
        else:
            out["pendentes"] = sum(
                1
                for p in arquivos
                if ledger.get(str(p.relative_to(inbox))) != p.stat().st_size
            )
    except OSError as exc:
        out["espelho"] = None
        out["nota_espelho"] = f"espelho ilegível em {inbox}: {exc}"
    return out


def opds_status(*, timeout: float = 12.0) -> dict[str, Any]:
    """Sonda o OPDS ao vivo (a visão do leitor) + inventário exato local.

    - `opds`: HTTP real da tailnet em `/opds/` + nº de seções (prova de
      contrato — a sonda de 19/10 mostrou 15).
    - `biblioteca`: contagem exata do metadata.db, formatos, arquivos no
      espelho e PENDENTES de importar (Drive/espelho vs ledger).
    Qualquer falha de rede/auth/XML sobe como `CalibreError` tipada — a
    action converte em {ok: False, error, message}.
    """
    base, _usuario, _senha = _opds_cfg()
    status, corpo = _opds_get("/opds/", timeout=timeout)
    feed = _opds_feed(corpo)
    subsecoes = len(feed.findall("a:entry", _ATOM))
    if subsecoes == 0:
        raise CalibreError(
            "opds_xml_invalido",
            "OPDS respondeu mas a raiz não tem seções — feed fora do contrato.",
        )
    return {
        "ok": True,
        "tool": "calibre",
        "opds": {"http": status, "base": base, "subsecoes": subsecoes},
        "biblioteca": _inventario_local(),
    }


def opds_busca(
    termo: str, *, limite: int = 10, timeout: float = 12.0
) -> dict[str, Any]:
    """Busca livros no feed OPDS real (título/autor) com links prontos.

    `/opds/search/<termo>` (url-encode — contrato vivo: espaço vira %20,
    termo sem match devolve 200 com 0 entradas, senha errada 401).
    `encontrados` é o total do feed (a busca não pagina); `limite` só
    corta o que volta (máx. 25).
    """
    from urllib.parse import quote

    termo_limpo = (termo or "").strip()
    if not termo_limpo:
        raise CalibreError(
            "calibre_busca_termo_vazio",
            'Busca sem termo — informe título/autor (ex.: "Direito Penal").',
        )
    base, _usuario, _senha = _opds_cfg()
    status, corpo = _opds_get("/opds/search/" + quote(termo_limpo), timeout=timeout)
    feed = _opds_feed(corpo)
    entradas, tem_mais = _extrair_entradas(feed, base=base)
    maximo = max(1, min(int(limite or 10), 25))
    selecionados = entradas[:maximo]
    return {
        "ok": True,
        "tool": "calibre",
        "termo": termo_limpo,
        "encontrados": len(entradas),
        "mostrados": len(selecionados),
        "mais_disponiveis": tem_mais,
        "resultados": selecionados,
        "http": status,
    }
