# Projeti — referência do material de trabalho e da leitura do Orion

> **Finalidade:** fechar o item 7 da fila (26/11) com o estado MEDIDO do
> material `analise/Projeti/` e a referência de leitura da escala do Orion —
> sem portar RPA e sem publicar dado de terceiro.
> **Fonte:** `analise/Projeti/` (235 MB, 953 arquivos) analisada em 13/11 e
> zipada para a HD do dono; o que este documento usa ficou em
> `data/refs_todo/Projeti/Cod/` (10 arquivos, 200 KB, **fora do git**).
> **Regra de dados:** os arquivos contêm **nomes, matrículas e viaturas de
> policiais** (dado pessoal de terceiros, regra 16). Nada de exemplo real
> neste doc, em teste, em log ou no Git. Os exemplos abaixo são sintéticos.
> **Data:** 2026-11-26 · fila de prioridades item 7.
> **Assinatura:** `OD // CORE`

---

## 1. Estado dos quatro sub-itens

| Sub-item | Estado em 26/11 |
|----------|-----------------|
| `google-services.json` duplicado | **Fora do servidor.** O de Projeti era byte a byte igual ao do app (sha256 `5e64634c…`, projeto `nicky-e4f99`, `com.omegadrakon.nicky`). A única cópia que resta é a oficial, `app/android/app/google-services.json` (mesmo sha256 conferido hoje). Nada a apagar no servidor. |
| `OmegaDrakon.apk` de 51 MB órfão | **Fora do servidor** (só no zip da HD). Nunca foi possível ler a versão dele; não batia com nenhum `backups/apk-*`. Continua sem versão conhecida — se o dono quiser, o caminho é abrir o zip e rodar `aapt dump badging`. |
| Ferramentas Windows (`.exe`) | **Fora do servidor** desde 13/11 (só no zip). O desktop Windows está na tailnet; para usar, trazer do zip. |
| Dados do Orion | **Referência de leitura** documentada neste arquivo (§2). Sem action: não há demanda medida. |

Nada disso pede decisão de exclusão no servidor: a pasta `analise/` já foi
esvaziada em 13/11 e o conteúdo vive no zip da HD do dono. Podar o zip é
ação dele.

---

## 2. Leitura da escala do Orion — formato real

O Orion (`orion.intranet.policiamilitar.sp.gov.br`) é uma aplicação web
interna; os notebooks não usam API, e sim `pyautogui` (tabulação cega) e
arquivos exportados/colados. Três formatos aparecem no material:

### 2.1 Escala em CSV/TSV — `Mapa.csv`, `Mapa.txt`, `MapaForcaTudo.txt`

Cabeçalho (14 colunas, nomes originais):

```
inicio,final,cmd,municipio,setor,sub,local,vtr,escala,mod,re,func,re2,func2
```

| Campo | Conteúdo | Exemplo sintético |
|-------|----------|-------------------|
| `inicio` / `final` | data e hora `dd/mm/aaaa HH:MM` | `01/01/2025 18:30` |
| `cmd` | comando/unidade | `CPI-8` |
| `municipio` / `setor` / `sub` | recorte territorial | `Cidade X` / `Area do Municipio` / `Nenhum Subsetor` |
| `local` | viatura ou área | `3ª CIA PM` |
| `vtr` | prefixo da viatura | `I-00000` |
| `escala` | tipo | `Ordinaria` |
| `mod` | modalidade | `CGP` |
| `re` / `re2` | matrícula do encarregado / motorista | `000000` |
| `func` / `func2` | função | `Encarregado` / `Motorista` |

Duas armadilhas medidas nos arquivos:

1. **`Mapa.csv` tem a linha de cabeçalho inteira entre aspas**
   (`"inicio,final,…,func2"`) — `csv.reader` entrega UMA coluna; é preciso
   detectar e re-dividir, ou tratar como TSV.
2. **`Mapa.txt` usa CRLF (`\r\n`) e termina com linha em branco** — sem
   `newline=''` no `open`, o último campo ganha `\r` e a comparação falha.

### 2.2 Blocos por unidade — `MapaForcaTudo.txt`

Estrutura em blocos: uma linha só com o código da unidade (ex.: `608423000`),
linha em branco, depois uma linha por viatura com campos separados por TAB
(inclusive TABs vazios):

```
<codigo_unidade>
<vtr>\t<status>\t<equipe…>\t\t<atividade>\t<modalidade>\t<inicio>\t<fim>
```

- o 2º campo é o status (`DISPONÍVEL`, `RESERVA`, `SUPERVISÃO`);
- o 3º carrega a composição (posto + matrícula + nome, entre colchetes);
- os dois TABs seguidos antes da atividade são posicionais (campo vazio);
- datas em `dd/mm/aa HH:MM:SS`.

### 2.3 Variante mais antiga — `MapaForca.txt`

Linha de unidade, linha em branco, depois uma linha por viatura com a
composição em colchetes, token de rádio (`TPD:`/`TMD:` + id), dois TABs,
atividade, modalidade e janela `dd/mm/aa HH:MM:SS` → `dd/mm/aa HH:MM:SS`.
A composição pode ter 1 a 4 ocupantes (viatura de moto tem 1).

### 2.4 Como os notebooks leem

- `ler.ipynb` — abre `MapaForca.txt` em UTF-8, `read()`, separa blocos por
  linha de unidade e imprime os campos; é a referência mais limpa de parsing.
- `mapa.ipynb` / `inserirmapa.ipynb` — RPA `pyautogui` (124 e 76 chamadas)
  sobre a tela do Orion para cadastrar turno/data. Depende de resolução,
  de foco de janela e de tempo de resposta do site.
- `teste.ipynb` / `google.ipynb` — exploração (planilha/Drive).

---

## 3. Decisão

- **Não portar o RPA.** Tabulação cega é frágil por construção (quebra com
  mudança de layout, resolução ou latência) e o ganho não foi medido.
- **Se um dia automatizar de verdade:** ler por fonte autorizada (export,
  API ou scraping permitido), **somente leitura**, com testes em cima de
  dados **sintéticos** e o dado real sempre fora do Git — a mesma régua da
  action `mapa_forca_consulta` que lê `data/refs_todo/Projeti/Cod` sem
  enviar nada a LLM externa.
- **Hoje:** referência. Nenhuma action nova.

---

## 4. Achado colateral — trilha de backups do APK (26/11)

Ao conferir "APK × backups" o `aapt` (build-tools 36.0.0) mostrou que a
trilha tem furos:

| Pasta | versionName/versionCode DENTRO do APK |
|-------|----------------------------------------|
| `backups/apk-v1.44.0-2080/` | **1.45.0 / 2081** |
| `backups/apk-v1.45.0-2081/` | **1.45.0 / 2081** (byte a byte igual à de cima) |
| `backups/apk-v1.45.1-2082/` | 1.45.1 / 2082 |
| `backups/apk-v1.47.0-2085/` | 1.47.0 / 2085 (criada hoje, com `site/`) |

Consequências medidas:

1. o binário **1.44.0/2080 não existe em `backups/`** — a pasta com esse
   nome guarda o build seguinte;
2. **1.45.0 está arquivado duas vezes** (pastas diferentes, sha256 igual);
3. **1.46.0/2083, 1.46.1/2084 e 1.47.0/2085 não tinham backup** — o de
   1.47.0 foi criado hoje a partir de `site/` e conferido com `aapt`
   (completo `4fa3bb88…` / arm64 `e096d1fd…`).

Renomear/apagar pasta de backup é ação do dono (regra 7). A recomendação é
que o nome da pasta passe a ser **a versão que está dentro** e que o
`aapt dump badging` seja o conferidor — o passo entrou no checklist de bump
(`docs/VERSIONAMENTO.md` §5, item 9) para não repetir.
