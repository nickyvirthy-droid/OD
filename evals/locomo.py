"""OMEGA DRAKON • EVALS • LOCOMO — memória de longa duração medida.

R5 do roadmap (`docs/ANALISE_SISTEMA_TODO.md`): "Eval Framework (LOCOMO
subset + custom benchmarks) rodando no CI".

O que este módulo mede, e o que ele NÃO mede
--------------------------------------------
O LOCOMO de verdade (arXiv 2402.17753) avalia a RESPOSTA de um LLM sobre
conversas de ~50 sessões. Aqui, no CI, não há LLM nem rede — então medimos
a parte que é a fundação da resposta: **a memória longa consegue recuperar
o fato certo depois de muitas sessões?** (recall@1, recall@5 e MRR), além
de dois modos de falha que importam:

* **temporal** — o fato velho foi substituído e não pode voltar na busca;
* **adversarial** — pergunta sobre o que NUNCA foi dito não pode inventar
  memória (falso positivo).

Dois modos de ingestão, de propósito:

* `producao` — cada turno passa pelo caminho REAL do chat (`MemoryGraph.salvar`,
  extração determinística por regex). Mede o que o OD lembra de fato.
* `turnos` — cada turno é gravado cru (sem extração). Isola a QUALIDADE DA
  BUSCA da COBERTURA do extrator: se `turnos` está bom e `producao` não, o
  problema é regex de extração, não índice.

Nada aqui escreve em `data/`: cada conversa roda em SQLite temporário e o
eval nunca sobe serviço (não importa `od-core`).

Interface Viva: Nicky Virthy
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from core.memory_layer import MemoryGraph, normalizar

# ---------------------------------------------------------------------------
# Constantes do exame
# ---------------------------------------------------------------------------

PADRAO_SUBSET = Path(__file__).parent / "locomo_subset.jsonl"
PADRAO_BASELINE = Path(__file__).parent / "baseline-locomo.json"

MODOS: tuple[str, ...] = ("producao", "turnos")
TIPOS: tuple[str, ...] = ("single_hop", "multi_hop", "temporal", "adversarial")

# Piso do gate (medido em 28/11/2026 — ver docs/CHANGELOG.md):
# nenhum modo pode cair abaixo disto, e quem já passou não pode regredir.
PISO_RECALL5: dict[str, float] = {"producao": 0.85, "turnos": 0.95}
# Adversarial não tem margem: memória que inventa fato é defeito, não nota.
PISO_FALSOS_POSITIVOS = 0

_TOP_K = 5


class LocomoInvalido(ValueError):
    """Subset malformado — expectativa morta não entra no exame."""


# ---------------------------------------------------------------------------
# Carga e validação
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Pergunta:
    id: str
    tipo: str
    pergunta: str
    evidencias: tuple[str, ...] = ()
    nao_evidencias: tuple[str, ...] = ()
    armadilhas: tuple[str, ...] = ()
    modos: tuple[str, ...] = MODOS


@dataclass(frozen=True)
class Conversa:
    id: str
    usuario: str
    sessoes: tuple[tuple[str, ...], ...]
    perguntas: tuple[Pergunta, ...]

    @property
    def turnos(self) -> int:
        return sum(len(s) for s in self.sessoes)


_CAMPOS_CONVERSA = {"id", "usuario", "sessoes", "perguntas"}
_CAMPOS_PERGUNTA = {
    "id", "tipo", "pergunta", "evidencias", "nao_evidencias", "armadilhas",
    "modos",
}


def _exigir(cond: bool, msg: str) -> None:
    if not cond:
        raise LocomoInvalido(msg)


def _pergunta_de(bruto: Any, conversa_id: str) -> Pergunta:
    _exigir(isinstance(bruto, dict), f"{conversa_id}: pergunta não é objeto")
    desconhecidos = set(bruto) - _CAMPOS_PERGUNTA
    _exigir(
        not desconhecidos,
        f"{conversa_id}: campo desconhecido na pergunta: {sorted(desconhecidos)}",
    )
    for campo in ("id", "tipo", "pergunta"):
        _exigir(
            isinstance(bruto.get(campo), str) and bruto[campo].strip(),
            f"{conversa_id}: pergunta sem {campo}",
        )
    tipo = bruto["tipo"]
    _exigir(
        tipo in TIPOS,
        f"{conversa_id}/{bruto.get('id')}: tipo {tipo!r} desconhecido "
        f"(válidos: {TIPOS})",
    )
    listas = {}
    for campo in ("evidencias", "nao_evidencias", "armadilhas"):
        valor = bruto.get(campo, [])
        _exigir(
            isinstance(valor, list) and all(isinstance(v, str) and v.strip() for v in valor),
            f"{conversa_id}/{bruto['id']}: {campo} precisa ser lista de textos",
        )
        listas[campo] = tuple(v.strip() for v in valor)
    modos = tuple(bruto.get("modos", list(MODOS)))
    _exigir(
        bool(modos) and all(m in MODOS for m in modos),
        f"{conversa_id}/{bruto['id']}: modos {modos} inválidos (válidos: {MODOS})",
    )
    if tipo == "adversarial":
        _exigir(
            not listas["evidencias"],
            f"{conversa_id}/{bruto['id']}: adversarial não pode exigir evidência",
        )
        _exigir(
            bool(listas["armadilhas"]),
            f"{conversa_id}/{bruto['id']}: adversarial exige ao menos uma armadilha",
        )
    else:
        _exigir(
            bool(listas["evidencias"]),
            f"{conversa_id}/{bruto['id']}: pergunta sem evidência esperada",
        )
        _exigir(
            not listas["armadilhas"],
            f"{conversa_id}/{bruto['id']}: armadilha só existe em adversarial",
        )
    return Pergunta(
        id=bruto["id"],
        tipo=tipo,
        pergunta=bruto["pergunta"].strip(),
        evidencias=listas["evidencias"],
        nao_evidencias=listas["nao_evidencias"],
        armadilhas=listas["armadilhas"],
        modos=modos,
    )


def _conversa_de(bruto: Any, indice: int) -> Conversa:
    _exigir(isinstance(bruto, dict), f"conversa #{indice} não é objeto")
    desconhecidos = set(bruto) - _CAMPOS_CONVERSA
    _exigir(
        not desconhecidos,
        f"conversa #{indice}: campo desconhecido: {sorted(desconhecidos)}",
    )
    for campo in ("id", "usuario"):
        _exigir(
            isinstance(bruto.get(campo), str) and bruto[campo].strip(),
            f"conversa #{indice} sem {campo}",
        )
    sessoes_brutas = bruto.get("sessoes")
    _exigir(
        isinstance(sessoes_brutas, list) and len(sessoes_brutas) >= 2,
        f"{bruto['id']}: LOCOMO exige pelo menos duas sessões",
    )
    sessoes: list[tuple[str, ...]] = []
    for n, sessao in enumerate(sessoes_brutas, start=1):
        _exigir(
            isinstance(sessao, list) and len(sessao) >= 2,
            f"{bruto['id']}: sessão {n} precisa de pelo menos dois turnos",
        )
        _exigir(
            all(isinstance(t, str) and t.strip() for t in sessao),
            f"{bruto['id']}: sessão {n} tem turno vazio",
        )
        sessoes.append(tuple(t.strip() for t in sessao))
    perguntas_brutas = bruto.get("perguntas")
    _exigir(
        isinstance(perguntas_brutas, list) and perguntas_brutas,
        f"{bruto['id']}: conversa sem perguntas",
    )
    perguntas = tuple(_pergunta_de(p, bruto["id"]) for p in perguntas_brutas)
    ids = [p.id for p in perguntas]
    _exigir(
        len(ids) == len(set(ids)),
        f"{bruto['id']}: id de pergunta repetido",
    )
    return Conversa(
        id=bruto["id"].strip(),
        usuario=bruto["usuario"].strip(),
        sessoes=tuple(sessoes),
        perguntas=perguntas,
    )


def carregar_subset(caminho: Path | str | None = None) -> list[Conversa]:
    """Lê o subset (um JSON por linha) e valida tudo na carga."""
    caminho = Path(caminho) if caminho is not None else PADRAO_SUBSET
    _exigir(caminho.exists(), f"subset LOCOMO não encontrado: {caminho}")
    conversas: list[Conversa] = []
    for numero, linha in enumerate(
        caminho.read_text(encoding="utf-8").splitlines(), start=1
    ):
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        try:
            bruto = json.loads(linha)
        except json.JSONDecodeError as exc:
            raise LocomoInvalido(f"linha {numero}: JSON inválido ({exc})") from exc
        conversas.append(_conversa_de(bruto, numero))
    _exigir(conversas, "subset LOCOMO vazio")
    ids = [c.id for c in conversas]
    _exigir(len(ids) == len(set(ids)), "conversa repetida no subset")
    return conversas


# ---------------------------------------------------------------------------
# Ingestão (dois modos)
# ---------------------------------------------------------------------------

def _ingerir(conversa: Conversa, modo: str, base: Path) -> MemoryGraph:
    """Monta a memória da conversa no modo pedido (SQLite temporário)."""
    if modo not in MODOS:
        raise LocomoInvalido(f"modo {modo!r} desconhecido (válidos: {MODOS})")
    grafo = MemoryGraph(base / f"{conversa.id}.db")
    indice = 0
    for sessao in conversa.sessoes:
        for turno in sessao:
            indice += 1
            if modo == "producao":
                # Caminho real do chat: extração determinística por regex.
                grafo.salvar(turno, user_id=conversa.usuario, origem="locomo")
            else:
                # Turno cru: entidade própria para o turno não substituir o
                # anterior (a substituição vale por user+tipo+entidade).
                grafo.adicionar_fato(
                    conversa.usuario,
                    turno,
                    entidade=f"t{indice}",
                    origem="locomo",
                )
    return grafo


# ---------------------------------------------------------------------------
# Busca e pontuação
# ---------------------------------------------------------------------------

def _texto_normalizado(*partes: str) -> str:
    return normalizar(" ".join(partes))


def _contem(texto: str, trecho: str) -> bool:
    """Evidência presente no texto, ignorando caixa e acento."""
    return _texto_normalizado(trecho) in _texto_normalizado(texto)


def _primeira_posicao(obtidos: Sequence[str], evidencias: Sequence[str]) -> int:
    """1-based: primeira posição em que TODAS as evidências já apareceram."""
    vistas: list[str] = []
    for posicao, texto in enumerate(obtidos, start=1):
        vistas.append(texto)
        if all(
            any(_contem(t, ev) for t in vistas) for ev in evidencias
        ):
            return posicao
    return 0


def avaliar(conversa: Conversa, modo: str, base: Path) -> list[dict[str, Any]]:
    """Roda as perguntas de UMA conversa e devolve o resultado por pergunta."""
    with _ingerir(conversa, modo, base) as grafo:
        resultados: list[dict[str, Any]] = []
        for pergunta in conversa.perguntas:
            if modo not in pergunta.modos:
                # Ex.: substituição de fato só existe no modo `producao`.
                continue
            obtidos = [
                f"{no.entidade} {no.conteudo}"
                for no in grafo.buscar(
                    conversa.usuario, pergunta.pergunta, limite=_TOP_K, semantica=False
                )
            ]
            if pergunta.tipo == "adversarial":
                armadilha = next(
                    (
                        texto
                        for texto in obtidos
                        if any(_contem(texto, a) for a in pergunta.armadilhas)
                    ),
                    "",
                )
                falsos = [pergunta.id] if armadilha else []
                # Adversarial ACERTA quando não inventa: a ausência do fato é
                # a resposta certa, não um erro de recuperação.
                primeira = 0 if armadilha else 1
            else:
                primeira = _primeira_posicao(obtidos, pergunta.evidencias)
                falsos = []
                if pergunta.nao_evidencias and any(
                    _contem(texto, velho)
                    for texto in obtidos
                    for velho in pergunta.nao_evidencias
                ):
                    # Fato substituído voltou: conta como erro de recuperação.
                    primeira = 0
            resultados.append(
                {
                    "conversa": conversa.id,
                    "id": pergunta.id,
                    "tipo": pergunta.tipo,
                    "pergunta": pergunta.pergunta,
                    "ok@1": primeira == 1,
                    "ok@5": 1 <= primeira <= _TOP_K,
                    "rr": 0.0 if primeira == 0 else 1.0 / primeira,
                    "primeira": primeira,
                    "obtidos": obtidos,
                    "falsos_positivos": falsos,
                }
            )
        return resultados


def _resumir(modo: str, resultados: list[dict[str, Any]], subset: Path) -> dict[str, Any]:
    total = len(resultados)
    acertos1 = sum(1 for r in resultados if r["ok@1"])
    acertos5 = sum(1 for r in resultados if r["ok@5"])
    falsos = sorted(
        p for r in resultados for p in r.get("falsos_positivos", [])
    )
    por_tipo: dict[str, dict[str, Any]] = {}
    for tipo in TIPOS:
        do_tipo = [r for r in resultados if r["tipo"] == tipo]
        if not do_tipo:
            continue
        por_tipo[tipo] = {
            "perguntas": len(do_tipo),
            "recall@1": round(
                sum(1 for r in do_tipo if r["ok@1"]) / len(do_tipo), 4
            ),
            "recall@5": round(
                sum(1 for r in do_tipo if r["ok@5"]) / len(do_tipo), 4
            ),
        }
    return {
        "modo": modo,
        "subset": str(subset.name),
        "perguntas": total,
        "acertos@1": acertos1,
        "acertos@5": acertos5,
        "recall@1": round(acertos1 / total, 4) if total else 0.0,
        "recall@5": round(acertos5 / total, 4) if total else 0.0,
        "mrr": round(sum(r["rr"] for r in resultados) / total, 4) if total else 0.0,
        "falsos_positivos": falsos,
        "por_tipo": por_tipo,
        "resultados": resultados,
    }


def rodar_locomo(
    modos: Iterable[str] = MODOS,
    *,
    subset: Path | str | None = None,
) -> dict[str, Any]:
    """Roda o exame inteiro (todos os modos) e devolve o relatório."""
    caminho = Path(subset) if subset is not None else PADRAO_SUBSET
    conversas = carregar_subset(caminho)
    relatorio: dict[str, Any] = {
        "exame": "locomo-subset",
        "data": __import__("datetime").datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "subset": str(caminho.name),
        "conversas": len(conversas),
        "turnos": sum(c.turnos for c in conversas),
        "perguntas": sum(len(c.perguntas) for c in conversas),
        "modos": {},
    }
    with tempfile.TemporaryDirectory(prefix="od_locomo_") as tmp:
        base = Path(tmp)
        for modo in modos:
            if modo not in MODOS:
                raise LocomoInvalido(f"modo {modo!r} desconhecido (válidos: {MODOS})")
            resultados: list[dict[str, Any]] = []
            for conversa in conversas:
                resultados.extend(avaliar(conversa, modo, base))
            relatorio["modos"][modo] = _resumir(modo, resultados, caminho)
    return relatorio


# ---------------------------------------------------------------------------
# Gate (piso + baseline) — é isto que roda no CI
# ---------------------------------------------------------------------------

def carregar_baseline(caminho: Path | str | None = None) -> dict[str, Any] | None:
    caminho = Path(caminho) if caminho is not None else PADRAO_BASELINE
    if not caminho.exists():
        return None
    return json.loads(caminho.read_text(encoding="utf-8"))


def gravar_baseline(
    relatorio: dict[str, Any], caminho: Path | str | None = None
) -> Path:
    caminho = Path(caminho) if caminho is not None else PADRAO_BASELINE
    payload = {
        "subset": relatorio["subset"],
        "data": relatorio.get("data", ""),
        "modos": {
            modo: {
                "recall@1": dados["recall@1"],
                "recall@5": dados["recall@5"],
                "mrr": dados["mrr"],
                "ok": {
                    f"{r['conversa']}/{r['id']}": bool(r["ok@5"])
                    for r in dados["resultados"]
                },
            }
            for modo, dados in relatorio["modos"].items()
        },
    }
    caminho.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return caminho


def verificar(
    relatorio: dict[str, Any], baseline: dict[str, Any] | None = None
) -> list[str]:
    """Problemas do exame (vazio = passou). Piso primeiro, baseline depois."""
    problemas: list[str] = []
    for modo, dados in relatorio["modos"].items():
        piso = PISO_RECALL5.get(modo, 0.0)
        if dados["recall@5"] < piso:
            problemas.append(
                f"{modo}: recall@5 {dados['recall@5']:.0%} abaixo do piso {piso:.0%}"
            )
        if len(dados["falsos_positivos"]) > PISO_FALSOS_POSITIVOS:
            problemas.append(
                f"{modo}: falso positivo em {dados['falsos_positivos']} "
                "(memória inventada)"
            )
        if not baseline:
            continue
        antes = baseline.get("modos", {}).get(modo, {})
        depois = {
            f"{r['conversa']}/{r['id']}": bool(r["ok@5"]) for r in dados["resultados"]
        }
        for chave, passou_antes in antes.get("ok", {}).items():
            if passou_antes and depois.get(chave) is False:
                problemas.append(f"{modo}: regrediu {chave} (passava na baseline)")
        if antes.get("recall@5") is not None and dados["recall@5"] < antes["recall@5"]:
            problemas.append(
                f"{modo}: recall@5 caiu de {antes['recall@5']:.0%} "
                f"para {dados['recall@5']:.0%} em relação à baseline"
            )
    return problemas


def _resumo(relatorio: dict[str, Any]) -> str:
    linhas = [
        f"LOCOMO subset — {relatorio['conversas']} conversas, "
        f"{relatorio['turnos']} turnos, {relatorio['perguntas']} perguntas"
    ]
    for modo, dados in relatorio["modos"].items():
        linhas.append(
            f"  {modo:<9} recall@1 {dados['recall@1']:>6.0%} · "
            f"recall@5 {dados['recall@5']:>6.0%} · MRR {dados['mrr']:.3f} · "
            f"FP {len(dados['falsos_positivos'])}"
        )
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m evals.locomo",
        description="Subset LOCOMO — memória de longa duração (CI-safe).",
    )
    parser.add_argument("--subset", type=Path, default=None)
    parser.add_argument(
        "--modo", choices=[*MODOS, "todos"], default="todos", help="modo de ingestão"
    )
    parser.add_argument("--json", action="store_true", help="relatório em JSON")
    parser.add_argument(
        "--sem-gate", action="store_true", help="só mede (não falha o processo)"
    )
    parser.add_argument(
        "--atualizar-baseline", action="store_true", help="regrava a baseline"
    )
    args = parser.parse_args(argv)

    modos = MODOS if args.modo == "todos" else (args.modo,)
    relatorio = rodar_locomo(modos, subset=args.subset)
    problemas = verificar(relatorio, carregar_baseline())

    if args.json:
        print(json.dumps(relatorio, ensure_ascii=False, indent=2))
    else:
        print(_resumo(relatorio))
        for problema in problemas:
            print(f"  ✗ {problema}")

    if args.atualizar_baseline:
        caminho = gravar_baseline(relatorio)
        print(f"Baseline gravada em {caminho}")

    return 0 if args.sem_gate or not problemas else 1


if __name__ == "__main__":
    raise SystemExit(main())
