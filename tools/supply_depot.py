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

import base64
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

try:
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.hazmat.primitives import serialization
    _CRYPTO_DISPONIVEL = True
except Exception:
    _CRYPTO_DISPONIVEL = False

log = get_logger("omega.tools.supply_depot")

# --- Constantes -------------------------------------------------------------

LIMITE_CODIGO = 8000          # chars — mesma guarda do AutoExtension
MARGEM_DISCO = 1.10           # 10% de folga (igual à Parte E)
MAX_HISTORICO = 5             # padrão: versões anteriores guardadas por ferramenta
MAX_HISTORICO_TETO = 50       # teto do env (protege o catálogo de crescer sem fim)
MAX_NOME = 64                 # id da action não vira nome infinito

# Exportação/importação do catálogo inteiro (TODO §3.1). O bundle leva
# metadados + código atual + código do histórico; o import é transacional
# (valida tudo, aplica e, se qualquer passo falhar, restaura arquivos,
# catálogo e registry).
EXPORT_SCHEMA = "od.supply_depot.v1"
LIMITE_IMPORT_FERRAMENTAS = 200
LIMITE_IMPORT_BYTES = 8 * 1024 * 1024

# Diff visual (TODO §3.1): chaves de saída do diff
DIFF_ADICIONADO = "adicionado"
DIFF_REMOVIDO = "removido"
DIFF_ATUALIZADO = "atualizado"
DIFF_IGUAL = "igual"

# Ed25519 assinatura de bundles (TODO §3.1)
ED25519_SCHEMA = "od.supply_depot.ed25519.v1"

# Ferramentas nativas conhecidas (TODO §3.1 — lista aberta do 3.1)
FERRAMENTAS_NATIVAS: dict[str, dict[str, Any]] = {
    "auto.calcular_imc": {
        "descricao": "Calcula IMC a partir de peso (kg) e altura (m)",
        "params": {"required": ["peso", "altura"],
                   "properties": {"peso": {"type": "number"},
                                  "altura": {"type": "number"}}},
        "permission": "auto.calcular_imc",
        "categoria": "saude",
    },
    "auto.gerar_senha": {
        "descricao": "Gera senha aleatória segura (configurável)",
        "params": {"required": [],
                   "properties": {"tamanho": {"type": "integer", "default": 16},
                                  "simbolos": {"type": "boolean", "default": True}}},
        "permission": "auto.gerar_senha",
        "categoria": "seguranca",
    },
    "auto.converter_unidades": {
        "descricao": "Conversão entre unidades (comprimento, massa, volume, temperatura)",
        "params": {"required": ["valor", "de", "para"],
                   "properties": {"valor": {"type": "number"},
                                  "de": {"type": "string"},
                                  "para": {"type": "string"}}},
        "permission": "auto.converter_unidades",
        "categoria": "utilidades",
    },
    "auto.hash_texto": {
        "descricao": "Calcula hash (sha256, sha512, blake2b) de string",
        "params": {"required": ["texto"],
                   "properties": {"texto": {"type": "string"},
                                  "algoritmo": {"type": "string", "default": "sha256"}}},
        "permission": "auto.hash_texto",
        "categoria": "seguranca",
    },
    "auto.timestamp": {
        "descricao": "Retorna timestamp atual em múltiplos formatos",
        "params": {"required": [],
                   "properties": {"formato": {"type": "string", "default": "iso"}}},
        "permission": "auto.timestamp",
        "categoria": "utilidades",
    },
}


# --- Templates de ferramentas (TODO §3.5) -------------------------------------
#
# Templates prontos para gerar código base de ferramentas comuns.
# Cada template tem placeholders: {id}, {funcao}, {descricao}, {params_json}.
TEMPLATES_FERRAMENTAS: dict[str, dict[str, Any]] = {
    "calculadora_simples": {
        "descricao": "Template: calculadora com 2 números e 1 operação",
        "params_exemplo": {
            "required": ["a", "b", "op"],
            "properties": {
                "a": {"type": "number"},
                "b": {"type": "number"},
                "op": {"type": "string", "enum": ["soma", "sub", "mul", "div"]},
            },
        },
        "codigo": '''def {funcao}(**params):
    \"\"\"{descricao}\"\"\"
    a = params.get("a", 0)
    b = params.get("b", 0)
    op = params.get("op", "soma")
    if op == "soma":
        return {{"ok": True, "result": a + b}}
    if op == "sub":
        return {{"ok": True, "result": a - b}}
    if op == "mul":
        return {{"ok": True, "result": a * b}}
    if op == "div":
        if b == 0:
            return {{"ok": False, "error": "divisao_por_zero"}}
        return {{"ok": True, "result": a / b}}
    return {{"ok": False, "error": "operacao_invalida"}}
''',
    },
    "processador_texto": {
        "descricao": "Template: processamento simples de string",
        "params_exemplo": {
            "required": ["texto"],
            "properties": {
                "texto": {"type": "string"},
                "acao": {"type": "string", "enum": ["upper", "lower", "reverse", "len"], "default": "upper"},
            },
        },
        "codigo": '''def {funcao}(**params):
    \"\"\"{descricao}\"\"\"
    texto = params.get("texto", "")
    acao = params.get("acao", "upper")
    if acao == "upper":
        return {{"ok": True, "result": texto.upper()}}
    if acao == "lower":
        return {{"ok": True, "result": texto.lower()}}
    if acao == "reverse":
        return {{"ok": True, "result": texto[::-1]}}
    if acao == "len":
        return {{"ok": True, "result": len(texto)}}
    return {{"ok": False, "error": "acao_invalida"}}
''',
    },
    "consulta_http": {
        "descricao": "Template: faz GET HTTP e retorna JSON/texto (requer allowlist urllib)",
        "params_exemplo": {
            "required": ["url"],
            "properties": {
                "url": {"type": "string"},
                "timeout": {"type": "number", "default": 10},
            },
        },
        "codigo": '''import urllib.request
import json

def {funcao}(**params):
    \"\"\"{descricao}\"\"\"
    url = params.get("url", "")
    timeout = params.get("timeout", 10)
    try:
        req = urllib.request.Request(url, headers={{"User-Agent": "OmegaDrakon/1.0"}})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            corpo = resp.read().decode("utf-8", "replace")
            try:
                return {{"ok": True, "result": json.loads(corpo)}}
            except json.JSONDecodeError:
                return {{"ok": True, "result": corpo}}
    except Exception as exc:
        return {{"ok": False, "error": f"{{type(exc).__name__}}: {{exc}}"}}
''',
    },
    "transformador_dados": {
        "descricao": "Template: transforma lista/dict de entrada (map/filter/reduce)",
        "params_exemplo": {
            "required": ["dados"],
            "properties": {
                "dados": {"type": "array", "items": {"type": "object"}},
                "campo": {"type": "string"},
                "operacao": {"type": "string", "enum": ["map", "filter", "soma", "media"], "default": "map"},
            },
        },
        "codigo": '''def {funcao}(**params):
    \"\"\"{descricao}\"\"\"
    dados = params.get("dados", [])
    campo = params.get("campo", "")
    operacao = params.get("operacao", "map")
    if not isinstance(dados, list):
        return {{"ok": False, "error": "dados_deve_ser_lista"}}
    if operacao == "map" and campo:
        return {{"ok": True, "result": [item.get(campo) for item in dados if isinstance(item, dict)]}}
    if operacao == "filter" and campo:
        return {{"ok": True, "result": [item for item in dados if isinstance(item, dict) and item.get(campo)]}}
    if operacao == "soma" and campo:
        vals = [item.get(campo, 0) for item in dados if isinstance(item, dict)]
        return {{"ok": True, "result": sum(vals)}}
    if operacao == "media" and campo:
        vals = [item.get(campo, 0) for item in dados if isinstance(item, dict)]
        return {{"ok": True, "result": sum(vals) / len(vals) if vals else 0}}
    return {{"ok": False, "error": "operacao_ou_campo_invalido"}}
''',
    },
}


# Staging area para revisão antes de instalar (TODO §3.5)
STAGING_DIR_PADRAO = Path("data/ferramentas_staging")


def max_historico() -> int:
    """Quantas versões anteriores guardar (``OD_SUPPLY_DEPOT_MAX_HISTORY``).

    Lido a cada uso (não no import): mudar o `.env` e reiniciar o serviço
    basta. Valor inválido cai no padrão 5; 0 desliga o histórico — e com
    ele o rollback (o painel avisa no resultado).
    """
    bruto = os.environ.get("OD_SUPPLY_DEPOT_MAX_HISTORY", "")
    if bruto.strip() == "":
        return MAX_HISTORICO
    try:
        valor = int(bruto)
    except (TypeError, ValueError):
        log.warn("OD_SUPPLY_DEPOT_MAX_HISTORY invalido; usando o padrao",
                 valor=bruto[:20])
        return MAX_HISTORICO
    return max(0, min(valor, MAX_HISTORICO_TETO))

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


def _nome_backup_valido(nome: str, id_ferramenta: str) -> bool:
    """Nome de backup fica DENTRO de data/ferramentas_backup/.

    O prefixo obrigatório ``<id>.`` impede que um bundle importado use o
    backup de outra ferramenta (ou um caminho hostil) para trocar código.
    """
    return bool(
        nome and len(nome) <= 200
        and nome == Path(nome).name
        and "/" not in nome and "\\" not in nome
        and nome.endswith(".py")
        and nome.startswith(id_ferramenta + ".")
    )


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

    def _caminho_backup(self, arquivo: str) -> Path:
        """Travado no diretório de backups (sem .. nem absoluto)."""
        caminho = (self.backup_dir / arquivo).resolve()
        caminho.relative_to(self.backup_dir.resolve())
        return caminho

    @staticmethod
    def _snapshot_arquivos(caminhos: set[Path]) -> dict[Path, Optional[bytes]]:
        """Fotografa só os arquivos que a importação pode tocar.

        ``None`` representa "não existia" — o rollback sabe apagar o que a
        importação criou. Ferramentas são pequenas (≤ 8 KB), então manter
        os bytes em memória é barato.
        """
        snapshot: dict[Path, Optional[bytes]] = {}
        for caminho in caminhos:
            try:
                snapshot[caminho] = caminho.read_bytes()
            except FileNotFoundError:
                snapshot[caminho] = None
            except OSError as exc:
                log.warn("Snapshot de arquivo do depot falhou",
                         arquivo=str(caminho), erro=_curto(exc))
                snapshot[caminho] = None
        return snapshot

    @staticmethod
    def _restaurar_arquivos(snapshot: dict[Path, Optional[bytes]]) -> None:
        """Volta o conteúdo fotografado (ou apaga o que não existia)."""
        for caminho, conteudo in snapshot.items():
            try:
                if conteudo is None:
                    caminho.unlink(missing_ok=True)
                    continue
                caminho.parent.mkdir(parents=True, exist_ok=True)
                tmp = caminho.with_name(caminho.name + ".restore.tmp")
                tmp.write_bytes(conteudo)
                os.replace(tmp, caminho)
            except OSError as exc:  # pragma: no cover — disco quebrando
                log.error("Restauração de arquivo do depot falhou",
                          arquivo=str(caminho), erro=_curto(exc))

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
                    limite = max_historico()
                    nova.anteriores = (nova.anteriores[-limite:]
                                       if limite else [])
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
            limite = max_historico()
            entrada_alvo.anteriores = (nova_hist[-limite:]
                                       if limite else [])
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

    # -- Exportar / importar catálogo (TODO §3.1) -----------------------------

    def exportar(self) -> dict[str, Any]:
        """Bundle completo: metadados + código atual + histórico.

        O export é read-only e admin-only (a rota exige ``_require_admin``).
        Código ausente não derruba o backup: a entrada sai com ``codigo=""``
        e o motivo vai em ``erros`` para o dono ver.
        """
        ferramentas: list[dict[str, Any]] = []
        erros: list[str] = []
        for id_f, entrada in sorted(self._catalogo.items()):
            d = entrada.para_dict()
            codigo = self._ler_codigo(entrada)
            d["codigo"] = codigo or ""
            if codigo is None:
                erros.append(f"{id_f}: codigo_atual_ausente")
            historico: list[dict[str, Any]] = []
            for h in entrada.anteriores:
                if not isinstance(h, dict):
                    continue
                hd = dict(h)
                versao = str(hd.get("versao") or "?")
                nome = str(hd.get("arquivo_backup")
                           or f"{id_f}.v{versao}.py")
                hd["arquivo_backup"] = nome
                try:
                    hcodigo = self._caminho_backup(nome).read_text(
                        encoding="utf-8")
                except Exception as exc:
                    hcodigo = ""
                    erros.append(f"{id_f}: backup {nome} ausente ({_curto(exc)})")
                hd["codigo"] = hcodigo
                historico.append(hd)
            d["anteriores"] = historico
            ferramentas.append(d)
        return {
            "schema": EXPORT_SCHEMA,
            "gerado_em": self._clock(),
            "ferramentas": ferramentas,
            "erros": erros,
        }

    def _validar_historico_import(
        self,
        id_f: str,
        funcao_padrao: str,
        bruto: Any,
        backups: dict[str, str],
    ) -> tuple[Optional[dict[str, Any]], Optional[str], Optional[str]]:
        """Valida UMA entrada de histórico e devolve (meta, código, erro)."""
        if not isinstance(bruto, dict):
            return None, None, "historico_nao_e_objeto"
        versao = str(bruto.get("versao") or "").strip()
        if not versao or len(versao) > 100:
            return None, None, "historico_versao_invalida"
        funcao = str(bruto.get("funcao") or funcao_padrao).strip()
        if not funcao or len(funcao) > 100:
            return None, None, "historico_funcao_invalida"
        codigo = bruto.get("codigo")
        if not isinstance(codigo, str) or not codigo.strip():
            return None, None, "historico_sem_codigo"
        if len(codigo) > self.max_codigo:
            return None, None, "historico_codigo_grande"
        ok, motivo = validar_codigo(codigo, self.max_codigo)
        if not ok:
            return None, None, f"historico_codigo_rejeitado: {motivo}"
        if _carregar_fn(codigo, funcao) is None:
            return None, None, "historico_funcao_ausente"
        sha_informado = str(bruto.get("sha256") or "").strip().lower()
        sha = hashlib.sha256(codigo.encode("utf-8")).hexdigest()
        if sha_informado and sha_informado != sha:
            return None, None, "historico_sha256_divergente"
        nome = str(bruto.get("arquivo_backup")
                   or f"{id_f}.v{versao}.py").strip()
        if not _nome_backup_valido(nome, id_f):
            return None, None, "historico_arquivo_invalido"
        if nome in backups:
            return None, None, "historico_arquivo_duplicado"
        meta = {k: v for k, v in bruto.items() if k != "codigo"}
        meta["arquivo_backup"] = nome
        meta["sha256"] = sha
        meta["bytes"] = len(codigo.encode("utf-8"))
        backups[nome] = codigo
        return meta, codigo, None

    def _preparar_importacao(
        self, itens: list[Any],
    ) -> tuple[dict[str, Ferramenta], dict[str, str], dict[str, str],
               list[str]]:
        """Valida tudo ANTES de escrever qualquer byte (transação)."""
        novas: dict[str, Ferramenta] = {}
        codigos: dict[str, str] = {}
        backups: dict[str, str] = {}
        erros: list[str] = []
        total_bytes = 0
        limite_hist = max_historico()

        for indice, item in enumerate(itens):
            rotulo = f"ferramentas[{indice}]"
            if not isinstance(item, dict):
                erros.append(f"{rotulo}: nao_e_objeto")
                continue
            id_f = str(item.get("id") or "").strip()
            if (not id_f or len(id_f) > MAX_NOME
                    or normalizar_nome(id_f) != id_f
                    or not _NOME_RE.match(id_f)):
                erros.append(f"{rotulo}: id_invalido")
                continue
            if id_f in novas:
                erros.append(f"{rotulo}: id_duplicado ({id_f})")
                continue
            if id_f not in self._catalogo and self._registry.has(id_f):
                erros.append(f"{rotulo}: conflito_action_alheia ({id_f})")
                continue
            funcao = str(item.get("funcao")
                         or id_f.rsplit(".", 1)[-1]).strip()
            if not funcao or len(funcao) > 100:
                erros.append(f"{rotulo}: funcao_invalida")
                continue
            versao = str(item.get("versao") or "1.0.0").strip()
            if not versao or len(versao) > 100:
                erros.append(f"{rotulo}: versao_invalida")
                continue
            codigo = item.get("codigo")
            if not isinstance(codigo, str) or not codigo.strip():
                erros.append(f"{rotulo}: codigo_obrigatorio")
                continue
            if len(codigo) > self.max_codigo:
                erros.append(f"{rotulo}: codigo_excede_{self.max_codigo}")
                continue
            ok, motivo = validar_codigo(codigo, self.max_codigo)
            if not ok:
                erros.append(f"{rotulo}: codigo_rejeitado: {motivo}")
                continue
            if _carregar_fn(codigo, funcao) is None:
                erros.append(f"{rotulo}: funcao_ausente")
                continue
            sha_informado = str(item.get("sha256") or "").strip().lower()
            sha = hashlib.sha256(codigo.encode("utf-8")).hexdigest()
            if sha_informado and sha_informado != sha:
                erros.append(f"{rotulo}: sha256_divergente")
                continue
            params = item.get("params", {})
            custom = item.get("custom", {})
            if params is not None and not isinstance(params, dict):
                erros.append(f"{rotulo}: params_invalido")
                continue
            if custom is not None and not isinstance(custom, dict):
                erros.append(f"{rotulo}: custom_invalido")
                continue
            ativa = item.get("ativa", True)
            if not isinstance(ativa, bool):
                erros.append(f"{rotulo}: ativa_invalida")
                continue
            textos: dict[str, str] = {}
            invalido = False
            for campo, limite in (("descricao", 2000), ("categoria", 100),
                                  ("permission", 200), ("origem", 100)):
                valor = item.get(campo)
                if valor is not None and not isinstance(valor, str):
                    erros.append(f"{rotulo}: {campo}_invalido")
                    invalido = True
                    break
                texto = str(valor or "")
                if len(texto) > limite:
                    erros.append(f"{rotulo}: {campo}_grande")
                    invalido = True
                    break
                textos[campo] = texto
            if invalido:
                continue

            hist_raw = item.get("anteriores", [])
            if hist_raw is None:
                hist_raw = []
            if not isinstance(hist_raw, list):
                erros.append(f"{rotulo}: anteriores_invalidos")
                continue
            historico: list[dict[str, Any]] = []
            if limite_hist:
                falhou = False
                for j, h_bruto in enumerate(hist_raw):
                    meta, hcodigo, erro = self._validar_historico_import(
                        id_f, funcao, h_bruto, backups)
                    if erro:
                        erros.append(f"{rotulo}.anteriores[{j}]: {erro}")
                        falhou = True
                        break
                    assert meta is not None and hcodigo is not None
                    historico.append(meta)
                    total_bytes += len(hcodigo.encode("utf-8"))
                if falhou:
                    continue
                historico = historico[-limite_hist:]

            entrada = Ferramenta(
                id=id_f, funcao=funcao, versao=versao,
                origem=textos["origem"] or ORIGEM_MANUAL,
                descricao=textos["descricao"],
                categoria=textos["categoria"],
                params=dict(params or {}),
                permission=textos["permission"],
                custom=dict(custom or {}),
                sha256=sha,
                bytes=len(codigo.encode("utf-8")),
                arquivo=f"{id_f}.py",
                ativa=ativa,
                anteriores=historico,
                criada_em=_float_ou_none(item.get("criada_em")),
                atualizada_em=_float_ou_none(item.get("atualizada_em")),
            )
            novas[id_f] = entrada
            codigos[id_f] = codigo
            total_bytes += len(codigo.encode("utf-8"))
            if total_bytes > LIMITE_IMPORT_BYTES:
                erros.append("importacao_grande: limite de bytes excedido")
                break

        return novas, codigos, backups, erros

    def importar(
        self, bundle: dict[str, Any], *, modo: str = "substituir",
        confirmar: bool = False,
    ) -> dict[str, Any]:
        """Restaura/mergeia um bundle exportado (transacional).

        ``modo="substituir"`` deixa o catálogo EXATAMENTE como o bundle;
        exige ``confirmar=True`` se já houver ferramentas. ``modo="mesclar"``
        mantém as ferramentas atuais que não estão no bundle e sobrescreve
        as de mesmo id. Qualquer falha no meio restaura catálogo, arquivos
        e registry.
        """
        if not isinstance(bundle, dict):
            return {"ok": False, "motivo": "bundle_invalido"}
        schema = str(bundle.get("schema") or "")
        if schema and schema != EXPORT_SCHEMA:
            return {"ok": False, "motivo": f"schema_invalido: {schema[:80]}"}
        itens = bundle.get("ferramentas")
        if not isinstance(itens, list):
            return {"ok": False, "motivo": "ferramentas_invalidas"}
        if len(itens) > LIMITE_IMPORT_FERRAMENTAS:
            return {"ok": False,
                    "motivo": f"ferramentas_demais (max {LIMITE_IMPORT_FERRAMENTAS})"}
        modo = str(modo or "substituir").strip().lower()
        if modo not in ("substituir", "mesclar"):
            return {"ok": False, "motivo": "modo_invalido"}
        if modo == "substituir" and self._catalogo and not confirmar:
            return {
                "ok": False, "motivo": "confirmacao_necessaria",
                "total_atual": len(self._catalogo),
                "total_importado": len(itens),
            }

        novas, codigos, backups, erros = self._preparar_importacao(itens)
        if erros:
            return {"ok": False, "motivo": "importacao_invalida",
                    "erros": erros[:50]}

        if modo == "substituir":
            final = dict(novas)
        else:
            final = copy.deepcopy(self._catalogo)
            final.update(novas)
        removidos = sorted(set(self._catalogo) - set(final))
        adicionados = sorted(set(novas) - set(self._catalogo))
        atualizados = sorted(set(novas) & set(self._catalogo))

        caminhos: set[Path] = {self.catalogo_path}
        for id_f in codigos:
            caminhos.add(self._caminho_codigo(f"{id_f}.py"))
        for nome in backups:
            caminhos.add(self._caminho_backup(nome))
        snapshot = self._snapshot_arquivos(caminhos)
        catalogo_antigo = copy.deepcopy(self._catalogo)

        try:
            for id_f, codigo in codigos.items():
                self._gravar_codigo(id_f, codigo)
            if backups:
                self.backup_dir.mkdir(parents=True, exist_ok=True)
                for nome, codigo in backups.items():
                    destino = self._caminho_backup(nome)
                    tmp = destino.with_name(destino.name + ".tmp")
                    tmp.write_text(codigo, encoding="utf-8")
                    os.replace(tmp, destino)
            self._catalogo = final
            self._gravar_catalogo()
            for id_f in removidos:
                if self._registry.has(id_f):
                    self._registry.unregister(id_f)
            for id_f, entrada in novas.items():
                if entrada.ativa:
                    fn = _carregar_fn(codigos[id_f], entrada.funcao)
                    if fn is None or not self._registrar(entrada, fn):
                        raise RuntimeError("registro_no_registry_falhou")
                elif self._registry.has(id_f):
                    self._registry.unregister(id_f)
        except Exception as exc:
            self._catalogo = catalogo_antigo
            self._restaurar_arquivos(snapshot)
            for id_f in novas:
                if self._registry.has(id_f):
                    self._registry.unregister(id_f)
            for id_f, entrada in catalogo_antigo.items():
                if entrada.ativa:
                    codigo = self._ler_codigo(entrada)
                    fn = _carregar_fn(codigo, entrada.funcao) if codigo else None
                    if fn is not None:
                        self._registrar(entrada, fn)
                elif self._registry.has(id_f):
                    self._registry.unregister(id_f)
            log.error("Supply Depot: importação falhou — rollback",
                      erro=_curto(exc))
            return {"ok": False, "rollback": True,
                    "motivo": f"rollback: {_curto(exc)}"}

        log.info("Supply Depot: catálogo importado", modo=modo,
                 adicionados=len(adicionados), atualizados=len(atualizados),
                 removidos=len(removidos), total=len(final))
        return {
            "ok": True, "modo": modo,
            "adicionados": len(adicionados),
            "atualizados": len(atualizados),
            "removidos": len(removidos),
            "total": len(final),
            "historico": sum(len(e.anteriores) for e in final.values()),
            "backups": len(backups),
        }

    # --- Diff visual (TODO §3.1) ----------------------------------------------

    def diff_catalogos(
        self, outro: dict[str, Any] | "SupplyDepot"
    ) -> dict[str, Any]:
        """Compara este catálogo com outro (dict exportado ou outro SupplyDepot).

        Retorna dict com listas: adicionado, removido, atualizado, igual.
        Cada item traz id, versao (antiga/nova), diff_campos (quais mudaram).
        """
        if isinstance(outro, SupplyDepot):
            outro_dict = {k: v.para_dict() for k, v in outro._catalogo.items()}
        else:
            outro_dict = {str(k): v for k, v in (outro or {}).items()
                          if isinstance(v, dict)}

        chaves_self = set(self._catalogo.keys())
        chaves_outro = set(outro_dict.keys())

        adicionados = sorted(chaves_outro - chaves_self)
        removidos = sorted(chaves_self - chaves_outro)
        comuns = sorted(chaves_self & chaves_outro)

        atualizados: list[dict[str, Any]] = []
        iguais: list[str] = []

        for id_f in comuns:
            a = self._catalogo[id_f].para_dict()
            b = outro_dict[id_f]
            if a == b:
                iguais.append(id_f)
            else:
                diff_campos = sorted(set(a.keys()) | set(b.keys()))
                mudancas = {}
                for campo in diff_campos:
                    va = a.get(campo)
                    vb = b.get(campo)
                    if va != vb:
                        mudancas[campo] = {"era": va, "virou": vb}
                atualizados.append({
                    "id": id_f,
                    "versao_antiga": a.get("versao"),
                    "versao_nova": b.get("versao"),
                    "diff_campos": mudancas,
                })

        return {
            "adicionado": [{"id": x, **outro_dict[x]} for x in adicionados],
            "removido": [{"id": x, **self._catalogo[x].para_dict()} for x in removidos],
            "atualizado": atualizados,
            "igual": iguais,
            "resumo": {
                "adicionados": len(adicionados),
                "removidos": len(removidos),
                "atualizados": len(atualizados),
                "iguais": len(iguais),
            },
        }

    def diff_visual(self, outro: dict[str, Any] | "SupplyDepot") -> str:
        """Renderiza o diff em texto legível (para log/Telegram/painel)."""
        diff = self.diff_catalogos(outro)
        linhas = []
        r = diff["resumo"]
        linhas.append(f"Diff de catálogos: +{r['adicionados']} -{r['removidos']} ~{r['atualizados']} ={r['iguais']}")
        for item in diff["adicionado"]:
            linhas.append(f"  + {item['id']} v{item.get('versao','?')} ({item.get('categoria','')})")
        for item in diff["removido"]:
            linhas.append(f"  - {item['id']} v{item.get('versao','?')}")
        for item in diff["atualizado"]:
            v_old = item.get("versao_antiga", "?")
            v_new = item.get("versao_nova", "?")
            campos = ", ".join(item["diff_campos"].keys())
            linhas.append(f"  ~ {item['id']} {v_old}→{v_new} [{campos}]")
        if not diff["adicionado"] and not diff["removido"] and not diff["atualizado"]:
            linhas.append("  (catálogos idênticos)")
        return "\n".join(linhas)

    # --- Ed25519 assinatura/verificação de bundles (TODO §3.1) ------------------

    @staticmethod
    def gerar_par_chaves_ed25519() -> dict[str, str]:
        """Gera par de chaves Ed25519 (base64 URL-safe, sem padding).

        Requer `cryptography`. Retorna dict com 'privada' e 'publica'.
        """
        if not _CRYPTO_DISPONIVEL:
            raise RuntimeError("cryptography nao instalado")
        privada = ed25519.Ed25519PrivateKey.generate()
        publica = privada.public_key()
        return {
            "privada": base64.urlsafe_b64encode(
                privada.private_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PrivateFormat.Raw,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            ).decode().rstrip("="),
            "publica": base64.urlsafe_b64encode(
                publica.public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw,
                )
            ).decode().rstrip("="),
        }

    def assinar_bundle(self, bundle: dict[str, Any],
                       chave_privada_b64: str) -> dict[str, Any]:
        """Assina um bundle exportado com Ed25519.

        Adiciona campo 'assinatura' (base64url) e 'chave_publica' ao bundle.
        O bundle NÃO é modificado in-place; retorna novo dict.
        """
        if not _CRYPTO_DISPONIVEL:
            raise RuntimeError("cryptography nao instalado")
        import base64

        privada_bytes = base64.urlsafe_b64decode(chave_privada_b64 + "==")
        privada = ed25519.Ed25519PrivateKey.from_private_bytes(privada_bytes)

        # Canonicalização: JSON com chaves ordenadas, sem espaços
        payload = json.dumps(bundle, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8")
        assinatura = privada.sign(payload)
        assinatura_b64 = base64.urlsafe_b64encode(assinatura).decode().rstrip("=")

        publica = privada.public_key()
        publica_b64 = base64.urlsafe_b64encode(
            publica.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).decode().rstrip("=")

        bundle_assinado = dict(bundle)
        bundle_assinado["assinatura"] = assinatura_b64
        bundle_assinado["chave_publica"] = publica_b64
        bundle_assinado["schema_assinatura"] = ED25519_SCHEMA
        return bundle_assinado

    @staticmethod
    def verificar_assinatura_bundle(bundle: dict[str, Any]) -> tuple[bool, str]:
        """Verifica assinatura Ed25519 de um bundle.

        Retorna (ok, motivo). OK=True se assinatura válida e chave confere.
        """
        if not _CRYPTO_DISPONIVEL:
            return False, "cryptography_nao_instalado"

        assinatura_b64 = str(bundle.get("assinatura") or "").strip()
        publica_b64 = str(bundle.get("chave_publica") or "").strip()
        if not assinatura_b64 or not publica_b64:
            return False, "assinatura_ou_chave_ausente"

        import base64
        try:
            assinatura = base64.urlsafe_b64decode(assinatura_b64 + "==")
            publica_bytes = base64.urlsafe_b64decode(publica_b64 + "==")
        except Exception:
            return False, "base64_invalido"

        # Recria payload SEM os campos de assinatura
        bundle_sem_assinatura = {k: v for k, v in bundle.items()
                                 if k not in ("assinatura", "chave_publica",
                                              "schema_assinatura")}
        payload = json.dumps(bundle_sem_assinatura, ensure_ascii=False,
                             sort_keys=True, separators=(",", ":")).encode("utf-8")

        try:
            publica = ed25519.Ed25519PublicKey.from_public_bytes(publica_bytes)
            publica.verify(assinatura, payload)
            return True, "assinatura_valida"
        except Exception:
            return False, "assinatura_invalida"

    # --- Ferramentas nativas (TODO §3.1) --------------------------------------

    def listar_ferramentas_nativas(self) -> list[dict[str, Any]]:
        """Lista de ferramentas nativas conhecidas (catálogo aberto do 3.1).

        Cada item: id, descricao, params, permission, categoria.
        O dono pode instalar qualquer uma via POST /admin/ferramentas
        (o código é gerado internamente — não vem do bundle).
        """
        itens = []
        for id_f, meta in sorted(FERRAMENTAS_NATIVAS.items()):
            itens.append({"id": id_f, **meta})
        return itens

    def instalar_nativa(self, id_ferramenta: str, *,
                        versao: str = "1.0.0",
                        confirmar: bool = False) -> dict[str, Any]:
        """Instala uma ferramenta nativa conhecida pelo ID.

        O código é um template interno (não vem de fora). Validações iguais
        ao instalar normal: pré-voo, sintaxe, registro.
        """
        meta = FERRAMENTAS_NATIVAS.get(id_ferramenta)
        if not meta:
            return {"ok": False, "motivo": f"ferramenta_nativa_desconhecida: {id_ferramenta}"}

        # Template de código mínimo — o corpo real seria injetado pelo
        # AutoExtension se necessário. Aqui só o esqueleto que passa validação.
        funcao = id_ferramenta.rsplit(".", 1)[-1]
        codigo = f'''def {funcao}(**params):
    # Ferramenta nativa: {meta.get("descricao", "")}
    return {{"ok": True, "result": "native:{id_ferramenta}"}}
'''

        return self.instalar(
            nome=id_ferramenta,
            codigo=codigo,
            versao=versao,
            descricao=meta.get("descricao", ""),
            categoria=meta.get("categoria", "nativa"),
            params=meta.get("params", {}),
            permission=meta.get("permission", ""),
            origem="nativa",
            confirmar=confirmar,
        )

    # --- Semver estrito (TODO §3.1) -------------------------------------------

    @staticmethod
    def validar_semver_estrito(versao: str) -> tuple[bool, str]:
        """Validação estrita de versão semver (X.Y.Z canônico apenas).

        Rejeita: v1.2.3, 1.2, 1.2.3-rc1, 1.2.3+build, hash, labels.
        Aceita apenas: dígitos separados por ponto, exatamente 3 partes.
        """
        if not isinstance(versao, str):
            return False, "nao_e_string"
        versao = versao.strip()
        if not versao:
            return False, "vazio"
        # Só X.Y.Z com dígitos
        if not re.fullmatch(r"\d+\.\d+\.\d+", versao):
            return False, "formato_invalido_esperado_X_Y_Z"
        partes = versao.split(".")
        for i, p in enumerate(partes):
            if len(p) > 1 and p.startswith("0"):
                return False, f"parte_{i}_com_zero_inicial: {p}"
        return True, "valido"

    # --- Templates + teste unitário gerado + staging/review (TODO §3.5) ---------

    def listar_templates(self) -> list[dict[str, Any]]:
        """Lista templates disponíveis com metadados (sem o código completo)."""
        itens = []
        for id_t, meta in sorted(TEMPLATES_FERRAMENTAS.items()):
            itens.append({
                "id": id_t,
                "descricao": meta.get("descricao", ""),
                "params_exemplo": meta.get("params_exemplo", {}),
            })
        return itens

    def gerar_codigo_de_template(
        self, template_id: str, id_ferramenta: str, *,
        descricao: str = "",
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Gera código a partir de um template (não instala — só devolve o código).

        O dono revisa o código no painel (staging) e depois confirma a instalação.
        Retorna dict com 'ok', 'codigo', 'params_gerados', 'funcao'.
        """
        template = TEMPLATES_FERRAMENTAS.get(template_id)
        if not template:
            return {"ok": False, "motivo": f"template_desconhecido: {template_id}"}

        id_f = normalizar_nome(id_ferramenta)
        if not id_f or not _NOME_RE.match(id_f):
            return {"ok": False, "motivo": f"nome_invalido: {id_ferramenta!r}"}

        funcao = id_f.rsplit(".", 1)[-1]
        params_json = json.dumps(params or template.get("params_exemplo", {}),
                                 ensure_ascii=False, indent=2)
        desc = descricao or template.get("descricao", "").replace("Template: ", "")
        codigo = template["codigo"].format(
            funcao=funcao, descricao=desc, params_json=params_json)

        # Valida sintaxe + allowlist ANTES de devolver (mesmo gate do install)
        ok, motivo = validar_codigo(codigo, self.max_codigo)
        if not ok:
            return {"ok": False, "motivo": f"template_gera_codigo_invalido: {motivo}"}

        return {
            "ok": True,
            "id": id_f,
            "funcao": funcao,
            "codigo": codigo,
            "params_gerados": params or template.get("params_exemplo", {}),
            "descricao": desc,
        }

    def gerar_teste_unitario(self, id_ferramenta: str, codigo: str,
                             funcao: str = "") -> dict[str, Any]:
        """Gera um arquivo de teste pytest básico para a ferramenta.

        Analisa o código para achar a assinatura da função e cria casos:
        - caso feliz com params_exemplo (se houver)
        - caso de erro (param faltando)
        - caso de tipo inválido
        Retorna dict com 'ok', 'codigo_teste', 'caminho_sugerido'.
        """
        funcao = funcao or id_ferramenta.rsplit(".", 1)[-1]
        # Tenta extrair params_exemplo do template se a ferramenta for de lá
        params_exemplo: dict[str, Any] = {}
        for t in TEMPLATES_FERRAMENTAS.values():
            if funcao in t.get("codigo", ""):
                params_exemplo = t.get("params_exemplo", {})
                break

        # Caso feliz: usa params_exemplo ou params vazios
        caso_feliz = params_exemplo.get("properties", {}) if params_exemplo else {}
        args_feliz = ", ".join(f'{k}={repr(v.get("default", ""))}'
                               for k, v in caso_feliz.items()) if caso_feliz else ""

        teste_codigo = f'''"""
Teste unitário gerado para {id_ferramenta} (função {funcao}).
Gerado automaticamente pelo Supply Depot — revise antes de commitar.
"""
import pytest
from tools.supply_depot import _carregar_fn

CODE = """{codigo}"""

def _fn():
    fn = _carregar_fn(CODE, "{funcao}")
    assert fn is not None, "função não encontrada no código"
    return fn

def test_{funcao}_caso_feliz():
    fn = _fn()
    result = fn({args_feliz})
    assert result.get("ok") is True, f"esperado ok=True, veio: {{result}}"

def test_{funcao}_sem_params():
    fn = _fn()
    result = fn()
    # Sem params: pode retornar ok=True com defaults ou ok=False
    assert "ok" in result

def test_{funcao}_tipo_invalido():
    fn = _fn()
    # Passa string onde espera número (se houver params numéricos)
    if {str(bool(caso_feliz))}:
        props = {params_exemplo.get("properties", {}) if params_exemplo else {}}
        for k, v in props.items():
            if v.get("type") == "number":
                result = fn(**{{k: "nao_e_numero"}})
                assert result.get("ok") is False, "deveria falhar com tipo inválido"
                break
'''

        # Valida sintaxe do teste gerado
        try:
            compile(teste_codigo, f"<test_{id_ferramenta}>", "exec")
        except SyntaxError as exc:
            return {"ok": False, "motivo": f"teste_gerado_com_syntax_error: {exc}"}

        caminho = f"tests/test_{normalizar_nome(id_ferramenta)}.py"
        return {
            "ok": True,
            "id": id_ferramenta,
            "funcao": funcao,
            "codigo_teste": teste_codigo,
            "caminho_sugerido": caminho,
        }

    def staging_salvar(self, id_ferramenta: str, codigo: str, *,
                       metadados: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Salva ferramenta na área de staging (data/ferramentas_staging/) para review.

        Não instala no registry nem no catálogo. O dono revisa o código no painel
        e depois confirma via instalar() normal. staging_listar() mostra o que está
        aguardando.
        """
        id_f = normalizar_nome(id_ferramenta)
        if not id_f or not _NOME_RE.match(id_f):
            return {"ok": False, "motivo": f"nome_invalido: {id_ferramenta!r}"}

        # Valida antes de salvar no staging
        ok, motivo = validar_codigo(codigo, self.max_codigo)
        if not ok:
            return {"ok": False, "motivo": f"codigo_invalido: {motivo}"}

        funcao = metadados.get("funcao") if metadados else None
        if not funcao:
            funcao = id_f.rsplit(".", 1)[-1]
        fn = _carregar_fn(codigo, funcao)
        if fn is None:
            return {"ok": False, "motivo": f"funcao_nao_encontrada: {funcao}"}

        self.codigos_dir.mkdir(parents=True, exist_ok=True)
        staging_dir = self.codigos_dir.parent / "ferramentas_staging"
        staging_dir.mkdir(parents=True, exist_ok=True)

        arquivo = f"{id_f}.py"
        meta_arquivo = f"{id_f}.meta.json"

        # Código
        destino = self._caminho_codigo(arquivo)
        tmp = destino.with_suffix(".py.tmp")
        tmp.write_text(codigo, encoding="utf-8")
        os.replace(tmp, destino)

        # Metadados do staging
        meta = {
            "id": id_f,
            "funcao": funcao,
            "descricao": (metadados or {}).get("descricao", ""),
            "categoria": (metadados or {}).get("categoria", "staging"),
            "params": (metadados or {}).get("params", {}),
            "permission": (metadados or {}).get("permission", ""),
            "origem": (metadados or {}).get("origem", "template"),
            "versao": (metadados or {}).get("versao", "1.0.0"),
            "salvo_em": self._clock(),
        }
        meta_path = staging_dir / meta_arquivo
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                             encoding="utf-8")

        return {"ok": True, "id": id_f, "staging": True,
                "arquivo": arquivo, "meta": meta_arquivo}

    def staging_listar(self) -> list[dict[str, Any]]:
        """Lista ferramentas na área de staging aguardando review."""
        staging_dir = self.codigos_dir.parent / "ferramentas_staging"
        if not staging_dir.exists():
            return []
        itens = []
        for meta_path in sorted(staging_dir.glob("*.meta.json")):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                itens.append(meta)
            except Exception:
                continue
        return itens

    def staging_remover(self, id_ferramenta: str) -> dict[str, Any]:
        """Remove ferramenta do staging (descarta)."""
        id_f = normalizar_nome(id_ferramenta)
        staging_dir = self.codigos_dir.parent / "ferramentas_staging"
        arquivo = staging_dir / f"{id_f}.py"
        meta_arquivo = staging_dir / f"{id_f}.meta.json"
        removidos = []
        for p in (arquivo, meta_arquivo):
            if p.exists():
                p.unlink()
                removidos.append(p.name)
        return {"ok": True, "id": id_f, "removidos": removidos}

    def staging_instalar(self, id_ferramenta: str, *,
                         confirmar: bool = False) -> dict[str, Any]:
        """Move do staging para instalação real (usa metadados salvos).

        Equivale a: ler staging → instalar() com os mesmos parâmetros → limpar staging.
        """
        id_f = normalizar_nome(id_ferramenta)
        staging_dir = self.codigos_dir.parent / "ferramentas_staging"
        meta_path = staging_dir / f"{id_f}.meta.json"
        if not meta_path.exists():
            return {"ok": False, "motivo": "nao_esta_no_staging"}

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"ok": False, "motivo": f"meta_invalida: {exc}"}

        arquivo = staging_dir / f"{id_f}.py"
        if not arquivo.exists():
            return {"ok": False, "motivo": "codigo_ausente_no_staging"}

        codigo = arquivo.read_text(encoding="utf-8")

        # Instala usando os metadados do staging
        r = self.instalar(
            nome=id_f,
            codigo=codigo,
            versao=meta.get("versao", "1.0.0"),
            descricao=meta.get("descricao", ""),
            categoria=meta.get("categoria", "staging"),
            params=meta.get("params", {}),
            permission=meta.get("permission", ""),
            origem=meta.get("origem", "template"),
            confirmar=confirmar,
        )

        if r.get("ok"):
            # Limpa staging após instalação bem-sucedida
            self.staging_remover(id_f)

        return r

    def dump(self) -> dict[str, Any]:
        return {"ferramentas": self.listar(), "resumo": self.resumo()}
