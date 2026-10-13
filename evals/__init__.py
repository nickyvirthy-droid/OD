"""OMEGA DRAKON • EVALS — exame padrão do assistente.

Mede a qualidade das respostas antes/depois de qualquer mudança de
persona ou prompt (Parte A da absorção do Project NOMAD — ver
docs/ANALISE_PROJECT_NOMAD.md). Não é biblioteca de produção: é
ferramenta de desenvolvimento que roda FORA do serviço (od-core nunca
sobe com isto importado) e NUNCA escreve em produção — toda rodada usa
`persist=False` (nem histórico, nem cache).

Interface Viva: Nicky Virthy
"""

from evals.golden import (
    MODOS_CONHECIDOS,
    Esperado,
    Golden,
    GoldenInvalido,
    carregar_goldens,
    goldens_do_modo,
)
from evals.avaliacao import Resultado, avaliar
from evals.runner import (
    caminho_baseline,
    carregar_baseline,
    comparar,
    gravar_baseline,
    montar_orquestrador,
    rodar_modo,
)

__all__ = [
    "MODOS_CONHECIDOS",
    "Esperado",
    "Golden",
    "GoldenInvalido",
    "carregar_goldens",
    "goldens_do_modo",
    "Resultado",
    "avaliar",
    "caminho_baseline",
    "carregar_baseline",
    "comparar",
    "gravar_baseline",
    "montar_orquestrador",
    "rodar_modo",
]
