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
3. `app/pubspec.yaml`: `version: novo.x.y+<build+1>` (se o app mudou)
4. `site/index.html`: badge do hero + card do APK (se o app mudou)
5. `docs/CHANGELOG.md`: seção `## [novo.x.y]` no topo (ou subseção datada
   dentro da seção vigente, quando o bump é retroativo/lote)
6. `docs/README_VERSAO.md`: relatório §2.1 da versão (§2.1.1)
7. Suíte verde + prova viva da versão no ar (regra 10 das Regras)

## 6. Histórico de saneamento (2026-09-26)

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
