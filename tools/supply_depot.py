"""OMEGA DRAKON • TOOLS
Módulo: tools/supply_depot.py — Parte F do Project NOMAD

Registro de ferramentas/skills estilo Supply Depot — evoluindo o
catálogo de tools do orquestrador com as três peças que faltavam:

  1. PRÉ-VOO (pre-flight) antes de instalar/atualizar: CONFLITO (o nome
     já existe? é do depot ou de outra fonte?), VERSÃO (semver: igual →
     nada a fazer, menor → downgrade bloqueado, major → exige
     confirmação explícita do dono) e TAMANHO (código acima do limite
     do auto-extension e espaço em disco com a MESMA margem de 1,1 da
     Parte E). Função pura `preflight()` — mesmas injeções do
     `avaliar()` de core/auto_update.py: o caminho é testável sem I/O.
  2. ROLLBACK: atualizar é backup → troca → validação; qualquer falha
     no meio restaura o arquivo, o catálogo E a action anterior
     (rollback automático, reportado). Histórico manual por versão
     (`anteriores`, limitado) com o arquivo antigo preservado em
     data/ferramentas_backup/.
  3. CUSTOMIZAÇÃO PRESERVADA: o dono sobrescreve descrição/params/
     permission em `custom` — e a customização SOBREVIVE a qualquer
     atualização (é reaplicada no registro de cada versão nova).

Fecho também o buraco do Auto Extension: hoje `/gerar` só existia em
memória (reiniciou o core e a ferramenta sumia) e devolvia "ok" mesmo
quando o registro foi pulado por conflito. Agora: pré-VOO ANTES do LLM
(conflito honesto, sem gastar token), persistência em
data/ferramentas_catalogo.json + data/ferramentas/<id>.py e restauração
no boot (`carregar()`).

Padrões da casa reutilizados:
  - `_parse_semver` de core/auto_update.py (mesma comparação da Parte E);
  - `AutoExtension.validate_code` (sintaxe + allowlist de imports);
  - escrita atômica tmp→rename de core/downloads.py;
  - margem de disco MARGEM_DISCO = 1,10 (Parte E).

Baseado em:
  - docs/ANALISE_PROJECT_NOMAD.md (Parte F + §3 item 7 do Nômade)
  - tools/registry.py (Action/ActionRegistry — o catálogo vivo)
  - tools/auto_extension/engine.py (o /gerar)
Arquiteto: Omega Drakon
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from core.logger import get_logger

log = get_logger("omega.tools.supply_depot")

# --- Constantes -------------------------------------------------------------

LIMITE_CODIGO = 8000          # chars — mesma guarda do AutoExtension
MARGEM_DISCO = 1.10           # 10% de folga (igual à Parte E)
MAX_HISTORICO = 5             # versões anteriores guardadas por ferramenta
MAX_NOME = 64                 # id da action não vira nome infinito

CATALOGO_PADRAO = Path("data/ferramentas_catalogo.json")
CODIGOS_PADRAO = Path("data/ferramentas")
BACKUP_PADRAO = Path("data/ferramentas_backup")

# Ações do pré-voo
INSTALAR = "instalar"
ATUALIZAR = "atualizar"
SEM_ACAO = "sem_acao"
BLOQUEAR = "bloquear"

# Origens
ORIGEM_AUTO = "auto_extension"
ORIGEM_MANUAL = "manual"

_NOME_RE = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)*$")


def _curto(texto: Any) -> str:
    """Mensagem compacta para log/estado (mesmo espírito da Parte E)."""
    s = " ".join(str(texto).split())
    return s if len(s) <= 200 else s[:199] + "…"


def normalizar_nome(nome: str) -> str:
    """Regra do AutoExtension: lower + só a-z 0-9 _ . — nunca vazio."""
    bruto = (nome or "").strip().lower()
    return re.sub(r"[^a-z0-9_.]", "_", bruto)


# --- Modelo de dados --------------------------------------------------------


@dataclass
class Ferramenta:
    """Entrada persistida do catálogo (o "item do Supply Depot")."""

    id: str                       # nome da action (ex.: "auto.calcular_imc")
    funcao: str                   # função alvo dentro do código
    versao: str = "1.0.0"
    origem: str = ORIGEM_MANUAL
    descricao: str = ""
    categoria: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    permission: str = ""
    # Sobrescritas do dono — SOBREVIVEM a atualização (Parte F).
    custom: dict[str, Any] = field(default_factory=dict)
    sha256: str = ""
    bytes: int = 0
    arquivo: str = ""             # relativo a data/ferramentas/
    ativa: bool = True
    # Versões anteriores p/ rollback: dicts completos de Ferramenta
    # (o código de cada uma fica no backup com "arquivo_backup").
    anteriores: list[dict[str, Any]] = field(default_factory=list)
    arquivo_backup: str = ""      # arquivo desta versão no backup (se houver)
    criada_em: Optional[float] = None
    atualizada_em: Optional[float] = None

    def para_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "funcao": self.funcao, "versao": self.versao,
            "origem": self.origem, "descricao": self.descricao,
            "categoria": self.categoria, "params": self.params,
            "permission": self.permission, "custom": self.custom,
            "sha256": self.sha256, "bytes": self.bytes,
            "arquivo": self.arquivo, "ativa": self.ativa,
            "anteriores": self.anteriores,
            "arquivo_backup": self.arquivo_backup,
            "criada_em": self.criada_em, "atualizada_em": self.atualizada_em,
        }

    @classmethod
    def de_dict(cls, d: dict[str, Any]) -> "Ferramenta":
        f = cls(id=str(d.get("id", "")), funcao=str(d.get("funcao", "") or ""))
        for chave in ("versao", "origem", "descricao", "categoria",
                      "permission", "sha256", "arquivo", "arquivo_backup"):
            valor = d.get(chave)
            if valor:
                setattr(f, chave, str(valor))
        for chave in ("params", "custom"):
            valor = d.get(chave)
            if isinstance(valor, dict):
                setattr(f, chave, valor)
        f.bytes = int(d.get("bytes", 0) or 0)
        f.ativa = bool(d.get("ativa", True))
        hist = d.get("anteriores")
        f.anteriores = [x for x in hist if isinstance(x, dict)] if isinstance(hist, list) else []
        f.criada_em = _float_ou_none(d.get("criada_em"))
        f.atualizada_em = _float_ou_none(d.get("atualizada_em"))
        return f


def _float_ou_none(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


@dataclass
class Preflight:
    """Resultado do pré-voo — SEMPRE com ação + motivo (contrato da casa)."""

    acao: str          # instalar | atualizar | sem_acao | bloquear
    motivo: str
    conflito: str = ""  # "" | action_alheia
    bytes: int = 0

    def para_dict(self) -> dict[str, Any]:
        return {"acao": self.acao, "motivo": self.motivo,
                "conflito": self.conflito, "bytes": self.bytes}


def preflight(
    *,
    nome: str,
    versao_nova: str,
    codigo: str,
    ja_no_registry: bool,
    entrada: Optional[Ferramenta],
    espaco_livre: int,
    confirmar: bool = False,
    max_codigo: int = LIMITE_CODIGO,
) -> Preflight:
    """Pré-voo PURO — conflito, versão e tamanho, nesta ordem.

    Nenhum I/O: registry, catálogo e disco entram como dados (mesma
    filosofia do `avaliar()` da Parte E). Camadas:

      1. nome canônico válido
      2. tamanho do código (limite do auto-extension)
      3. espaço em disco (bytes × 1,1)
      4. CONFLITO: no registry mas fora do depot → bloqueia (não
         substituímos ferramenta que não é nossa)
      5. VERSÃO: reativação aceita; igual → sem_acao; menor → downgrade
         bloqueado; major → exige `confirmar` (confirmação do dono,
         item 4 do §2.2 do Nômade); resto → atualizar
    """
    bytes_codigo = len((codigo or "").encode("utf-8"))
    id_ok = normalizar_nome(nome)
    if not id_ok or not _NOME_RE.match(id_ok):
        return Preflight(BLOQUEAR, f"nome_invalido: {nome!r}", bytes=bytes_codigo)
    if len(codigo or "") > max_codigo:
        return Preflight(BLOQUEAR,
                         f"codigo_excede_{max_codigo} ({len(codigo or '')} chars)",
                         bytes=bytes_codigo)
    if bytes_codigo * MARGEM_DISCO > espaco_livre:
        return Preflight(BLOQUEAR,
                         f"sem_espaco (precisa ~{bytes_codigo} B com margem, "
                         f"livre {espaco_livre} B)",
                         bytes=bytes_codigo)

    if entrada is None and ja_no_registry:
        return Preflight(BLOQUEAR,
                         f"conflito: action '{id_ok}' já existe no registry "
                         "e não é do depot",
                         conflito="action_alheia", bytes=bytes_codigo)

    if entrada is not None:
        if not entrada.ativa:
            return Preflight(INSTALAR,
                             f"reativacao de '{id_ok}' (estava desinstalada)",
                             bytes=bytes_codigo)
        if versao_nova == entrada.versao:
            return Preflight(SEM_ACAO,
                             f"ja_instalada (versão {entrada.versao})",
                             bytes=bytes_codigo)
        semver_nova = _semver(versao_nova)
        semver_atual = _semver(entrada.versao)
        if semver_nova and semver_atual and semver_nova < semver_atual:
            return Preflight(BLOQUEAR,
                             f"downgrade_bloqueado ({entrada.versao} → "
                             f"{versao_nova})",
                             bytes=bytes_codigo)
        if (semver_nova and semver_atual
                and semver_nova[0] > semver_atual[0] and not confirmar):
            return Preflight(BLOQUEAR,
                             f"major_requer_confirmacao ({entrada.versao} → "
                             f"{versao_nova})",
                             bytes=bytes_codigo)
        return Preflight(ATUALIZAR,
                         f"atualizacao_disponivel: {entrada.versao} → "
                         f"{versao_nova}",
                         bytes=bytes_codigo)

    return Preflight(INSTALAR, f"instalar_nova (v{versao_nova})",
                     bytes=bytes_codigo)


def _semver(v: str) -> Optional[tuple[int, int, int]]:
    """Reusa a mesma leitura da Parte E (X.Y.Z canônico ou None)."""
    from core.auto_update import _parse_semver
    return _parse_semver(v)


def proxima_versao(atual: str) -> str:
    """Bump de patch (1.2.3 → 1.2.4). Versão não-semver fica como está."""
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", (atual or "").strip())
    if not m:
        return atual
    a, b, c = (int(x) for x in m.groups())
    return f"{a}.{b}.{c + 1}"


# --- Execução segura do código ---------------------------------------------


def _carregar_fn(codigo: str, funcao: str) -> Optional[Callable[..., Any]]:
    """Executa o código em namespace vazio e devolve a função alvo.

    Só roda DEPOIS de validate_code (sintaxe + allowlist) — o mesmo
    contrato do `_exec_tool` do AutoExtension.
    """
    namespace: dict[str, Any] = {}
    try:
        exec(compile(codigo, f"<supply_depot:{funcao}>", "exec"), namespace)
    except Exception as exc:
        log.warn("Código da ferramenta não executou", erro=_curto(exc))
        return None
    fn = namespace.get(funcao)
    return fn if callable(fn) else None


def validar_codigo(codigo: str, max_codigo: int = LIMITE_CODIGO) -> tuple[bool, str]:
    """Sintaxe + allowlist de imports — MESMO gate do auto-extension.

    Import lazy para não criar ciclo (engine importa o depot no wiring).
    """
    from tools.auto_extension.engine import AutoExtension
    return AutoExtension.validate_code(codigo, max_code_len=max_codigo)


# --- Supply Depot -----------------------------------------------------------


class SupplyDepot:
    """Catálogo persistente de ferramentas com pré-voo e rollback.

    O registry (tools/registry.py) continua sendo o catálogo VIVO das
    actions — aqui ficam o manifesto em disco, o histórico de versões e
    as regras de entrada/saída. `carregar()` no boot re-registra tudo
    (com a customização do dono reaplicada): ferramenta gerada não some
    mais quando o core reinicia.
    """

    def __init__(
        self,
        *,
        registry: Any,
        catalogo_path: Path = CATALOGO_PADRAO,
        codigos_dir: Path = CODIGOS_PADRAO,
        backup_dir: Path = BACKUP_PADRAO,
        raiz: Optional[Path] = None,
        espaco_livre_fn: Optional[Callable[[Path], int]] = None,
        clock: Callable[[], float] = time.time,
        max_codigo: int = LIMITE_CODIGO,
    ) -> None:
        self._registry = registry
        self.catalogo_path = Path(catalogo_path)
        self.codigos_dir = Path(codigos_dir)
        self.backup_dir = Path(backup_dir)
        self._raiz = Path(raiz) if raiz else self.catalogo_path.parent
        self._espaco_fn = espaco_livre_fn
        self._clock = clock
        self.max_codigo = max_codigo
        self._catalogo: dict[str, Ferramenta] = {}
        self.ultimo_erro: str = ""
        self._carregar_catalogo_em_memoria()

    # -- Disco ---------------------------------------------------------------

    def _espaco(self) -> int:
        if self._espaco_fn is not None:
            return self._espaco_fn(self._raiz)
        try:
            self._raiz.mkdir(parents=True, exist_ok=True)
            import shutil as _sh
            return _sh.disk_usage(self._raiz).free
        except Exception:  # pragma: no cover — disco sem medição
            return 0

    def _carregar_catalogo_em_memoria(self) -> None:
        """Lê o manifesto (JSON atômico). Erro = catálogo vazio + warn."""
        try:
            bruto = json.loads(self.catalogo_path.read_text(encoding="utf-8"))
            itens = bruto.get("ferramentas", {})
            self._catalogo = {
                str(k): Ferramenta.de_dict({"id": k, **v})
                for k, v in itens.items()
                if isinstance(v, dict)
            }
        except FileNotFoundError:
            self._catalogo = {}
        except Exception as exc:
            log.warn("Catálogo de ferramentas ilegível — começando vazio",
                     arquivo=str(self.catalogo_path), erro=_curto(exc))
            self._catalogo = {}

    def _gravar_catalogo(self) -> None:
        """Escrita atômica (tmp → rename), padrão da casa."""
        self.catalogo_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.catalogo_path.with_suffix(".tmp")
        payload = {
            "_comentario": (
                "Catálogo de ferramentas (Parte F — Supply Depot). Editado "
                "pelas rotas /admin/ferramentas e pelo /gerar; não edite à "
                "mão durante o serviço (o core regrava). 'custom' são as "
                "sobrescritas do dono — sobrevivem a atualizações."
            ),
            "ferramentas": {k: v.para_dict() for k, v in self._catalogo.items()},
        }
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(tmp, self.catalogo_path)

    def _caminho_codigo(self, arquivo: str) -> Path:
        """Travado no diretório de códigos (sem .. nem absoluto)."""
        caminho = (self.codigos_dir / arquivo).resolve()
        caminho.relative_to(self.codigos_dir.resolve())
        return caminho

    def _ler_codigo(self, entrada: Ferramenta) -> Optional[str]:
        try:
            return self._caminho_codigo(entrada.arquivo).read_text(
                encoding="utf-8")
        except Exception as exc:
            log.warn("Código da ferramenta ausente", id=entrada.id,
                     erro=_curto(exc))
            return None

    def _gravar_codigo(self, id_ferramenta: str, codigo: str) -> str:
        """Grava data/ferramentas/<id>.py (atômico) e devolve o nome."""
        self.codigos_dir.mkdir(parents=True, exist_ok=True)
        arquivo = f"{id_ferramenta}.py"
        destino = self._caminho_codigo(arquivo)
        tmp = destino.with_suffix(".py.tmp")
        tmp.write_text(codigo, encoding="utf-8")
        os.replace(tmp, destino)
        return arquivo

    # -- Consulta ---------------------------------------------------------------

    def obter(self, id_ferramenta: str) -> Optional[Ferramenta]:
        """Entrada do catálogo (para o AutoExtension calcular versão)."""
        return self._catalogo.get(normalizar_nome(id_ferramenta))

    # -- Pré-voo ---------------------------------------------------------------

    def preflight(self, nome: str, versao_nova: str, codigo: str,
                  *, confirmar: bool = False) -> Preflight:
        """Pré-voo com os dados VIVOS (catálogo + registry + disco)."""
        id_f = normalizar_nome(nome)
        return preflight(
            nome=id_f,
            versao_nova=versao_nova,
            codigo=codigo,
            ja_no_registry=bool(self._registry.has(id_f)),
            entrada=self._catalogo.get(id_f),
            espaco_livre=self._espaco(),
            confirmar=confirmar,
            max_codigo=self.max_codigo,
        )

    # -- Registro no ActionRegistry --------------------------------------------

    def _registrar(self, entrada: Ferramenta,
                   fn: Callable[..., Any]) -> bool:
        """(Re)registra a action COM a customização do dono reaplicada."""
        from tools.registry import Action

        custom = entrada.custom or {}
        if self._registry.has(entrada.id):
            self._registry.unregister(entrada.id)
        action = Action(
            name=entrada.id,
            handler=self._envolver(fn),
            description=str(custom.get("descricao") or entrada.descricao),
            category=entrada.categoria,
            params=custom.get("params") or entrada.params or
                   {"required": [], "properties": {}},
            permission=str(custom.get("permission") or entrada.permission),
            version=entrada.versao,
            source=entrada.origem,
        )
        registrado = bool(self._registry.register(action))
        if not registrado:
            # Devolve o que havia antes (se havia) — nunca deixar sem action.
            if self._registry.has(entrada.id):
                self._registry.unregister(entrada.id)
        return registrado

    @staticmethod
    def _envolver(fn: Callable[..., Any]) -> Callable[..., Any]:
        """Handler que engole exceção (contrato do auto-extension)."""
        def handler(**params: Any) -> Any:
            try:
                return fn(**params)
            except Exception as exc:  # pragma: no cover — runtime da tool
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return handler

    def _registro_valido(self, id_ferramenta: str,
                         versao: str) -> bool:
        """A action no registry é a versão que esperamos?"""
        try:
            action = self._registry.get(id_ferramenta)
        except Exception:
            return False
        return getattr(action, "version", "") == versao

    # -- Instalar / atualizar ----------------------------------------------------

    def instalar(
        self,
        *,
        nome: str,
        codigo: str,
        versao: str = "1.0.0",
        descricao: str = "",
        categoria: str = "",
        params: Optional[dict[str, Any]] = None,
        permission: str = "",
        origem: str = ORIGEM_MANUAL,
        confirmar: bool = False,
        funcao: str = "",
    ) -> dict[str, Any]:
        """Pré-voo → validação → backup → troca → registro (ou rollback).

        Retorno sempre com `ok` + `acao` (do pré-voo) + `motivo`; quando
        a aplicação falha no meio, `rollback=True` e o estado anterior
        (arquivo, catálogo e action) volta inteiro.
        """
        id_f = normalizar_nome(nome)
        versao = (versao or "1.0.0").strip() or "1.0.0"
        funcao = funcao or (id_f.rsplit(".", 1)[-1] if id_f else "")
        pre = self.preflight(id_f, versao, codigo, confirmar=confirmar)
        if pre.acao == BLOQUEAR:
            log.warn("Supply Depot: pré-voo bloqueou", id=id_f,
                     motivo=pre.motivo)
            return {"ok": False, "id": id_f, **pre.para_dict()}
        if pre.acao == SEM_ACAO:
            return {"ok": True, "id": id_f, **pre.para_dict(),
                    "versao": self._catalogo[id_f].versao
                    if id_f in self._catalogo else versao}

        ok, motivo = validar_codigo(codigo, self.max_codigo)
        if not ok:
            return {"ok": False, "acao": "rejeitado", "motivo": motivo,
                    "bytes": pre.bytes}
        fn = _carregar_fn(codigo, funcao)
        if fn is None:
            return {"ok": False, "acao": "rejeitado",
                    "motivo": f"funcao_nao_encontrada: {funcao}",
                    "bytes": pre.bytes}

        agora = self._clock()
        entrada_antiga = self._catalogo.get(id_f)
        custom = dict(entrada_antiga.custom) if entrada_antiga else {}

        # Snapshot de rollback em MEMÓRIA (ferramentas são ≤ 8 KB):
        # restaurar é barato e não depende de disco.
        catalogo_snapshot = copy.deepcopy(self._catalogo)
        codigo_antigo = (self._ler_codigo(entrada_antiga)
                         if entrada_antiga else None)

        nova = Ferramenta(
            id=id_f, funcao=funcao, versao=versao, origem=origem,
            descricao=descricao, categoria=categoria,
            params=params or {}, permission=permission,
            custom=custom,  # customização do dono sobrevive (Parte F)
            sha256=hashlib.sha256(codigo.encode("utf-8")).hexdigest(),
            bytes=len(codigo.encode("utf-8")),
            ativa=True,
            criada_em=(entrada_antiga.criada_em if entrada_antiga else agora),
            atualizada_em=agora,
        )

        registrado_versao_anterior = (
            entrada_antiga is not None and self._registry.has(id_f)
            and self._registro_valido(id_f, entrada_antiga.versao)
        )

        try:
            # 1. Backup da versão atual (código no dir de backup + histórico).
            #    Reativação (entrada inativa) preserva o histórico existente.
            if entrada_antiga is not None:
                nova.anteriores = list(entrada_antiga.anteriores)
                if entrada_antiga.ativa and codigo_antigo is not None:
                    self.backup_dir.mkdir(parents=True, exist_ok=True)
                    nome_backup = f"{id_f}.v{entrada_antiga.versao}.py"
                    (self.backup_dir / nome_backup).write_text(
                        codigo_antigo, encoding="utf-8")
                    entrada_dict = entrada_antiga.para_dict()
                    entrada_dict["arquivo_backup"] = nome_backup
                    nova.anteriores.append(entrada_dict)
                    nova.anteriores = nova.anteriores[-MAX_HISTORICO:]
                nova.arquivo_backup = ""
            # 2. Código novo (atômico) + 3. catálogo (atômico).
            nova.arquivo = self._gravar_codigo(id_f, codigo)
            self._catalogo[id_f] = nova
            self._gravar_catalogo()
            # 4. Troca da action no registry.
            if not self._registrar(nova, fn):
                raise RuntimeError("registro_no_registry_falhou")
        except Exception as exc:
            self._rollback_memoria(catalogo_snapshot, codigo_antigo, id_f,
                                   entrada_antiga, registrado_versao_anterior)
            log.error("Supply Depot: falha no meio — rollback executado",
                      id=id_f, erro=_curto(exc))
            return {"ok": False, "id": id_f, "acao": pre.acao,
                    "rollback": True, "bytes": pre.bytes,
                    "motivo": f"rollback: {_curto(exc)}"}

        log.info(f"Supply Depot: ferramenta {pre.acao}", id=id_f,
                 versao=versao, origem=origem,
                 backups=len(nova.anteriores))
        return {"ok": True, "id": id_f, **pre.para_dict(), "versao": versao,
                "sha256": nova.sha256, "historico": len(nova.anteriores)}

    def _rollback_memoria(
        self,
        catalogo_snapshot: dict[str, Ferramenta],
        codigo_antigo: Optional[str],
        id_ferramenta: str,
        entrada_antiga: Optional[Ferramenta],
        restaurar_action: bool,
    ) -> None:
        """Restaura arquivo + catálogo + action para o estado pré-troca."""
        self._catalogo = catalogo_snapshot
        try:
            if codigo_antigo is not None and entrada_antiga is not None:
                self.codigos_dir.mkdir(parents=True, exist_ok=True)
                destino = self._caminho_codigo(entrada_antiga.arquivo)
                destino.write_text(codigo_antigo, encoding="utf-8")
            elif entrada_antiga is None:
                # Instala nova que falhou: some com o arquivo recém-criado.
                try:
                    self._caminho_codigo(f"{id_ferramenta}.py").unlink(
                        missing_ok=True)
                except Exception:  # pragma: no cover
                    pass
            self._gravar_catalogo()
        except Exception as exc:  # pragma: no cover — disco quebrando
            log.error("Rollback parcial", erro=_curto(exc))
        if restaurar_action and entrada_antiga is not None:
            codigo = self._ler_codigo(entrada_antiga)
            if codigo is not None:
                fn = _carregar_fn(codigo, entrada_antiga.funcao)
                if fn is not None:
                    self._registrar(entrada_antiga, fn)

    # -- Rollback manual --------------------------------------------------------

    def rollback(self, id_ferramenta: str,
                 versao: Optional[str] = None) -> dict[str, Any]:
        """Volta para a versão anterior (ou a `versao` pedida).

        Simétrico ao update: a versão ATUAL também entra no histórico,
        então um rollback pode ser desfeito (rollback do rollback).
        """
        id_f = normalizar_nome(id_ferramenta)
        entrada = self._catalogo.get(id_f)
        if entrada is None:
            return {"ok": False, "motivo": "ferramenta_inexistente"}
        if not entrada.anteriores:
            return {"ok": False, "motivo": "sem_historico_de_versoes"}
        alvo = None
        if versao:
            alvo = next((a for a in entrada.anteriores
                         if a.get("versao") == versao), None)
            if alvo is None:
                return {"ok": False, "motivo": f"versao_nao_encontrada: {versao}"}
        else:
            alvo = entrada.anteriores[-1]

        nome_backup = str(alvo.get("arquivo_backup") or "")
        try:
            caminho_backup = (self.backup_dir / nome_backup).resolve()
            caminho_backup.relative_to(self.backup_dir.resolve())
            codigo_alvo = caminho_backup.read_text(encoding="utf-8")
        except Exception as exc:
            return {"ok": False, "motivo": f"backup_ausente: {_curto(exc)}"}

        alvo_dict = {k: v for k, v in alvo.items() if k != "arquivo_backup"}
        entrada_alvo = Ferramenta.de_dict(alvo_dict)
        entrada_alvo.arquivo_backup = ""
        fn = _carregar_fn(codigo_alvo, entrada_alvo.funcao)
        if fn is None:
            return {"ok": False, "motivo": "funcao_nao_encontrada_no_backup"}

        # A versão atual vira histórico (rollback desfazível) e o alvo sai.
        catalogo_snapshot = copy.deepcopy(self._catalogo)
        codigo_atual = self._ler_codigo(entrada)
        atual_dict = entrada.para_dict()
        atual_dict["arquivo_backup"] = ""
        try:
            # O backup do código atual (garante arquivo físico p/ re-update).
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            nome_atual = f"{id_f}.v{entrada.versao}.py"
            if codigo_atual is not None:
                (self.backup_dir / nome_atual).write_text(codigo_atual,
                                                          encoding="utf-8")
                atual_dict["arquivo_backup"] = nome_atual
            restantes = [a for a in entrada.anteriores if a is not alvo]
            nova_hist = restantes + [atual_dict]
            entrada_alvo.anteriores = nova_hist[-MAX_HISTORICO:]
            entrada_alvo.criada_em = entrada.criada_em
            entrada_alvo.atualizada_em = self._clock()
            entrada_alvo.arquivo = self._gravar_codigo(id_f, codigo_alvo)
            self._catalogo[id_f] = entrada_alvo
            self._gravar_catalogo()
            if not self._registrar(entrada_alvo, fn):
                raise RuntimeError("registro_no_registry_falhou")
        except Exception as exc:
            self._rollback_memoria(catalogo_snapshot, codigo_atual, id_f,
                                   entrada, True)
            return {"ok": False, "rollback": True,
                    "motivo": f"rollback: {_curto(exc)}"}
        log.info("Supply Depot: rollback aplicado", id=id_f,
                 de=entrada.versao, para=entrada_alvo.versao)
        return {"ok": True, "id": id_f, "de": entrada.versao,
                "para": entrada_alvo.versao}

    # -- Customização / remoção ----------------------------------------------------

    def customizar(
        self,
        id_ferramenta: str,
        *,
        descricao: Any = None,
        params: Any = None,
        permission: Any = None,
        ativa: Any = None,
    ) -> dict[str, Any]:
        """Sobrescritas do dono — sobrevivem a update e a rollback.

        `ativa=False` desinstala (some do registry, arquivo fica no
        backup); `ativa=True` reativa (precisa do arquivo em disco).
        """
        id_f = normalizar_nome(id_ferramenta)
        entrada = self._catalogo.get(id_f)
        if entrada is None:
            return {"ok": False, "motivo": "ferramenta_inexistente"}
        mudou = False
        if descricao is not None:
            entrada.custom["descricao"] = str(descricao)
            mudou = True
        if params is not None:
            if not isinstance(params, dict):
                return {"ok": False, "motivo": "params_invalido"}
            entrada.custom["params"] = params
            mudou = True
        if permission is not None:
            entrada.custom["permission"] = str(permission)
            mudou = True
        if ativa is not None:
            entrada.ativa = bool(ativa)
            mudou = True
        if not mudou:
            return {"ok": False, "motivo": "nada_para_alterar"}

        if entrada.ativa:
            codigo = self._ler_codigo(entrada)
            if codigo is None:
                return {"ok": False, "motivo": "codigo_ausente_em_disco"}
            fn = _carregar_fn(codigo, entrada.funcao)
            if fn is None:
                return {"ok": False, "motivo": "funcao_nao_encontrada"}
            if not self._registrar(entrada, fn):
                return {"ok": False, "motivo": "registro_no_registry_falhou"}
        elif self._registry.has(id_f):
            # Desinstalação: some do registry, arquivo vai p/ backup.
            self._registry.unregister(id_f)
            codigo = self._ler_codigo(entrada)
            if codigo is not None:
                self.backup_dir.mkdir(parents=True, exist_ok=True)
                (self.backup_dir / f"{id_f}.removido.v{entrada.versao}.py"
                 ).write_text(codigo, encoding="utf-8")
        entrada.atualizada_em = self._clock()
        self._gravar_catalogo()
        log.info("Supply Depot: ferramenta atualizada pelo dono", id=id_f,
                 ativa=entrada.ativa, custom=sorted(entrada.custom))
        return {"ok": True, "id": id_f, "ativa": entrada.ativa,
                "custom": dict(entrada.custom)}

    def remover(self, id_ferramenta: str) -> dict[str, Any]:
        """Desinstala: sai do registry e do catálogo; arquivo preservado
        no backup (`<id>.removido.v<versao>.py`) — não destruímos código."""
        id_f = normalizar_nome(id_ferramenta)
        entrada = self._catalogo.get(id_f)
        if entrada is None:
            return {"ok": False, "motivo": "ferramenta_inexistente"}
        codigo = self._ler_codigo(entrada)
        if codigo is not None:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            (self.backup_dir / f"{id_f}.removido.v{entrada.versao}.py"
             ).write_text(codigo, encoding="utf-8")
        if self._registry.has(id_f):
            self._registry.unregister(id_f)
        del self._catalogo[id_f]
        self._gravar_catalogo()
        log.info("Supply Depot: ferramenta desinstalada", id=id_f,
                 versao=entrada.versao)
        return {"ok": True, "removido": id_f}

    # -- Boot -----------------------------------------------------------------

    def carregar(self) -> dict[str, int]:
        """Restaura o catálogo no boot: valida e registra as ativas.

        Ferramenta com código corrompido não derruba nada: fica fora do
        registry com warn (o dono vê no painel — `sem_registry`).
        """
        carregadas, erros = 0, 0
        for id_f, entrada in sorted(self._catalogo.items()):
            if not entrada.ativa:
                continue
            codigo = self._ler_codigo(entrada)
            if codigo is None:
                erros += 1
                self.ultimo_erro = f"{id_f}: código ausente"
                continue
            ok, motivo = validar_codigo(codigo, self.max_codigo)
            fn = _carregar_fn(codigo, entrada.funcao) if ok else None
            if fn is None:
                erros += 1
                self.ultimo_erro = f"{id_f}: {motivo if not ok else 'função ausente'}"
                log.warn("Supply Depot: ferramenta não restaurada no boot",
                         id=id_f, motivo=self.ultimo_erro)
                continue
            if self._registrar(entrada, fn):
                carregadas += 1
            else:
                erros += 1
                self.ultimo_erro = f"{id_f}: registro recusado"
        if carregadas or erros:
            log.info("Supply Depot restaurado no boot", carregadas=carregadas,
                     erros=erros, catalogo=len(self._catalogo))
        return {"carregadas": carregadas, "erros": erros}

    # -- Visibilidade -------------------------------------------------------------

    def listar(self) -> list[dict[str, Any]]:
        """Entradas do catálogo + flag `no_registry` (estado vivo)."""
        itens = []
        for id_f, entrada in sorted(self._catalogo.items()):
            d = entrada.para_dict()
            d["no_registry"] = bool(self._registry.has(id_f))
            itens.append(d)
        return itens

    def resumo(self) -> dict[str, Any]:
        """Bloco do /dashboard/stats."""
        itens = list(self._catalogo.values())
        origens: dict[str, int] = {}
        for e in itens:
            origens[e.origem] = origens.get(e.origem, 0) + 1
        return {
            "total": len(itens),
            "ativas": sum(1 for e in itens if e.ativa),
            "com_historico": sum(1 for e in itens if e.anteriores),
            "origens": origens,
            "ultimo_erro": self.ultimo_erro,
        }

    def health_check(self, _monitor: Any = None) -> dict[str, Any]:
        """Check do HealthMonitor (não-crítico) — contrato
        `check(monitor)` de observability/health.py (lição da Parte E)."""
        itens = list(self._catalogo.values())
        quebradas = [
            e.id for e in itens
            if e.ativa and not self._registry.has(e.id)
        ]
        return {
            "ok": not quebradas,
            "detail": (f"supply-depot: {len(quebradas)} ferramenta(s) fora "
                       "do registry" if quebradas
                       else f"supply-depot: {len(itens)} no catálogo"),
            "fora_do_registry": quebradas,
        }

    def dump(self) -> dict[str, Any]:
        return {"ferramentas": self.listar(), "resumo": self.resumo()}
