# OMEGADRAKON — POLÍTICA DE VERSIONAMENTO

> **Status:** Documento Normativo — vigente
> **Data:** 2026-09-26
> **Base:** Semantic Versioning 2.0.0 (https://semver.org/lang/pt-BR/)
> **Finalidade:** definir como o sistema incrementa a versão e onde ela vive.
> **Assinatura:** `OD // CORE`

---

## 1. Formato

A versão do OmegaDrakon tem o formato **X.Y.Z** (Maior.Menor.Correção):

- **X (MAJOR):** muda quando há quebra de compatibilidade na API pública —
  endpoint removido ou com contrato incompatível, protocolo do WebSocket
  alterado de forma que um cliente antigo pare de funcionar, migração de
  banco que invalide dados existentes.
- **Y (MINOR):** muda quando entra **funcionalidade nova com compatibilidade**
  — rotas novas, páginas novas, capacidade nova (auth de usuários, papéis,
  histórico paginado, painéis, Funnel). Patch zera (`x.y.0`).
- **Z (PATCH):** muda quando entra **correção de bug sem funcionalidade nova**
  — fix de comportamento errado, fechamento de bypass, ajuste de layout.
  Minor zera não; apenas o patch incrementa (`x.y.z+1`).

A API pública declarada é o par **REST + WebSocket** expostos pelo od-core
(`integrations/api/`) e consumido pelos clientes oficiais (app Flutter, chat
web, bot Telegram).

## 2. O `+build` é metadado — nunca substitui a versão

- No app Flutter, o sufixo `+N` do `pubspec.yaml` é o **versionCode Android**:
  número de build, monotônico, exigido para instalar por cima. Ele **não
  comunica mudança de conteúdo** e não tem precedência no SemVer.
- **Proibido** (erro histórico de 2026-09): empilhar `1.2.8+8`, `+9`, `+10`,
  `+11` com features novas entrando enquanto o `versionName` ficava parado.
  Cada lote de features sobe o **Y** (ou Z, se só fix) e o build sobe junto:
  `1.2.8+8` → `1.3.0+9` → `1.3.1+10` → `1.4.0+11`…
- Precedência SemVer: `1.3.0 > 1.2.8` — o que vale é X.Y.Z, não o `+N`.

## 3. Fonte da verdade

| Onde | O quê |
|---|---|
| `.env` → `OD_VERSION=x.y.z` | **Fonte única** da versão do sistema (servidor/API/capabilities). `.env` é local; o fallback em `core/capabilities.py` acompanha o valor vigente |
| `core/capabilities.py` | `OD_VERSION` resolvido (env → `.env` → fallback congelado) — todo o resto lê daqui |
| `app/pubspec.yaml` → `version: x.y.z+N` | Versão do app (versionName) + versionCode Android |
| `site/index.html` | Anúncio da landing (`v1.2.8` e card do APK) |
| `docs/CHANGELOG.md` | Registro por versão (versão nova no topo) |
| `docs/README_VERSAO.md` | Relatório §2.1 por versão (§2.1.1 das Regras de Trabalho) |

## 4. Quando bumpar

O bump acontece **no deploy da mudança**, não "depois de acumular": se a
entrega adiciona capacidade, o PATCH/MINOR sobe junto da entrega. Nada de
versão congelada recebendo features por baixo do pano.

## 5. Checklist de bump (obrigatório na entrega)

1. `.env`: `OD_VERSION=novo.x.y`
2. `core/capabilities.py`: fallback congelado alinhado
3. `app/pubspec.yaml`: `version: novo.x.y+<build+1>` — **sempre que
   publicar APK novo**, mesmo sem mudança de código no app: versionCode
   igual deixa o updater do app mudo por definição (a comparação é só
   por versionCode) e quem tem a versão anterior nunca recebe o versionName
   novo (pegado em 2026-10-09, v1.23.0 publicada com o code 2050 da
   1.22.1 — o celular do dono seguia dizendo "já está na versão mais
   recente").
4. `integrations/api/server.py`: `_APP_VERSION_CODE = <novo build>` — o
   versionCode que o `GET /app/version` anuncia TEM que ser o do APK
   publicado em `site/`; errado aqui mata a auto-atualização em silêncio
   (o servidor anunciaria o build que o celular já tem com o sha256 do
   binário novo). Pegado no ar em 2026-09-28 (v1.7.1 anunciava 2017 com
   o binário 2018) — hoje a guarda `test_app_version_code_bate_com_o_pubspec`
   quebra a suíte se ficar para trás.
5. `site/index.html`: badge do hero + card do APK (se o app mudou)
6. `docs/CHANGELOG.md`: seção `## [novo.x.y]` no topo (ou subseção datada
   dentro da seção vigente, quando o bump é retroativo/lote)
7. `docs/README_VERSAO.md`: relatório §2.1 da versão (§2.1.1)
8. Suíte verde + prova viva da versão no ar (regra 10 das Regras)

## 6. Guardas de coerência (2026-09-26)

`tests/test_version_policy.py` fixa a política na suíte: OD_VERSION em
formato SemVer, `.env` = capabilities resolvida = fallback congelado,
`pubspec.yaml` com versionName = versão do sistema e build inteiro,
`_APP_VERSION_CODE` (server.py) = build do pubspec, site anunciando a
versão vigente (≥ 2 ocorrências) e CHANGELOG com a seção `## [X.Y.Z]`.
Bump parcial quebra a suíte. Verificado com 5 mutações (todas detectadas
e revertidas) + a mutação 2018→2017 de 2026-09-28 (detectada, revertida
bit-exata).

**Guarda de checkout limpo (2026-10-02):** a CI roda em checkout limpo onde o
próprio `.env` (gitignored) não existe. `test_env_e_capabilities_na_mesma_versao`
lia o `.env` sem guarda e derrubava a suíte com `FileNotFoundError` ANTES de
rodar os testes. `_env_version()` agora devolve `None` quando o arquivo não
existe e o teste pula com motivo — sem `.env` não há estado local a validar, e
a verdade passa a ser o fallback congelado (coberto por
`test_fallback_congelado_e_a_versao_vigente`).

**Guarda de ordem do CHANGELOG (2026-09-29):**
`test_changelog_secoes_em_ordem_cronologica` exige as seções `## [X.Y.Z]`
em ordem ESTRITAMENTE descendente (mais recente no topo, sem cabeçalho
repetido). Motivação: a `[1.7.0]` foi gravada ACIMA da `[1.8.0]` nas
sessões de 28/09 ('última seção gravada no topo' em vez de 'mais recente
no topo') e só foi reordenada em 29/09. Teste do teste: 1ª rodada com
`sorted(reverse=True)` aceitou cabeçalho duplicado (mutação fraca,
precedente de 28/09) — endurecida para comparação par a par estrita; 3/3
mutações detectadas e revertidas bit-exata (desordem real, cabeçalho
duplicado, seção da versão vigente renomeada).

## 7. Histórico de saneamento (2026-09-26)

- Até aqui o sistema rodou `OD_VERSION=1.2.0` (de 09-12) enquanto o app
  empilhava `1.2.8+8…+11` — o `+N` fazia o papel que era do X.Y.Z.
- Saneamento aplicado: **sistema → 1.3.0** (auth de usuários, papéis, vínculo
  Telegram, anônimo, histórico visual/paginado, painéis = features, MINOR);
  **app → 1.3.0+12** (mesma conta de features; versionCode segue monotônico).
- Os números antigos (`1.2.0`, `1.2.8+N`) permanecem citados em documentos
  históricos, fixtures e CHANGELOG — são evidência, não estado.

```python
"""
OMEGA DRAKON • SYSTEMS
Tecnologia que respira.
Módulo: docs/VERSIONAMENTO.md
Descrição: Política de versionamento (SemVer 2.0.0) do OmegaDrakon.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti
"""
__signature__ = "OD // CORE"
```
