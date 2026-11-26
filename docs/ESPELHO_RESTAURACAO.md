# Espelho offline — restauração real (26/11/2026)

Prova de que o acervo de `/home/alex/dados/od-mirror` (5,7 GB) restaura o OD
em uma máquina sem internet — não só resolve dependências, mas **roda**.

> Contexto: até 12/11 a prova era um `pip install --no-index` de 15 s e o gate
> com aquele venv. A fila (item 10, P2 nº 19) pedia o que faltava: um **venv
> limpo** e um **container** subindo de mídia espelhada, sem rede.

## 1. venv limpo só com o espelho

```bash
python3.12 -m venv /tmp/od_mirror_venv
PIP_NO_INDEX=1 /tmp/od_mirror_venv/bin/pip install \
  --no-index --find-links /home/alex/dados/od-mirror/pip \
  -r /home/alex/dados/od-mirror/requirements.txt \
  -r /home/alex/dados/od-mirror/requirements-dev.txt
```

- **60 pacotes em 18 s**, nenhum download (o `PIP_NO_INDEX=1` garante que o pip
  nem tente a rede).
- O `.venv` do projeto não foi tocado.

## 2. Gate completo dentro desse venv (boot de verdade)

```bash
cd /home/alex/OmegaDrakon
PYTHONPATH=. /tmp/od_mirror_venv/bin/python -m pytest -q -p no:cacheprovider
```

**5807 passed / 17 skipped / 2 failed em 249 s.**

As 2 falhas são `tests/test_websocket.py::TestOrchestratorStreaming::
test_process_stream_rate_limit` e `::test_process_stream_llm_token_a_token` —
as mesmas que já falham no HEAD do repositório quando a suíte roda inteira
(passam isoladas). Não são do espelho e estão registradas no TODO.

Como o `od-core` é stdlib (`http.server`) e as dependências externas são todas
opcionais por import tardio, o gate cobre o caminho de boot da API, do
orquestrador, do RAG, dos mapas e das integrações. Subir o `od-core` de
verdade a partir do espelho foi deliberadamente **não** feito: seria uma
segunda instância disputando Postgres, MQTT e o bot do Telegram com a que está
no ar.

## 3. Container a partir do tar espelhado, sem rede

```bash
docker load -i /home/alex/dados/od-mirror/docker/postgres_16-alpine.tar
docker run -d --name od-mirror-prova --network none \
  -e POSTGRES_PASSWORD=prova -e POSTGRES_HOST_AUTH_METHOD=trust postgres:16-alpine
docker exec od-mirror-prova pg_isready -h 127.0.0.1 -U postgres
docker exec od-mirror-prova psql -h 127.0.0.1 -U postgres -tAc "select version()"
```

- `Loaded image: postgres:16-alpine` (tag preservada pelo tar).
- `127.0.0.1:5432 - accepting connections`, `PostgreSQL 16.15 on
  x86_64-pc-linux-musl`, consulta `select` respondida.
- Interfaces dentro do container: **só `lo`** — prova de que não houve rede.
- Container removido ao fim (`docker rm -f`); a imagem já estava no host.

## 4. Integridade

```bash
cd /home/alex/dados/od-mirror && sha256sum -c MANIFEST.txt
```

**134/134 OK** (46 s).

## Achado corrigido

O `README.md` do espelho dizia que `requirements-dev.txt` (10 wheels, para
rodar o gate offline) estava no acervo — os **wheels estavam** em `pip/`, mas o
**arquivo não**: nem na pasta, nem no `MANIFEST`. Sem ele, restaurar o gate
dependia de copiar o `requirements-dev.txt` do repositório.

Corrigido nesta prova: o arquivo foi copiado para o espelho e entrou no
`MANIFEST` (`sha256sum -c` confirma), e o README ganhou a seção deste teste.
Agora a restauração offline sai inteira do espelho:

```bash
PIP_NO_INDEX=1 pip install --no-index --find-links od-mirror/pip \
  -r od-mirror/requirements.txt -r od-mirror/requirements-dev.txt
```

## Limites

- Os wheels são **cp312 / Linux x86_64** (esta máquina). Em outra versão de
  Python ou arquitetura, é preciso reespelhar com `pip download`.
- O espelho leva o **LLM 3B coder** e o runtime do llama.cpp (provados em
  18/11), não o 7B nem o 3B generalista.
- **Dados** de containers e o `.env` não estão no espelho, por decisão: dados
  vêm do fluxo de backup, segredos do cofre.
- O `.gguf` e o runtime são desta build; em outra arquitetura, reespelhar.
- A prova cobriu **um** container (Postgres) e o venv completo. Os outros 16
  tars foram validados por `docker load` + `sha256` em 12/11, não bootados um a
  um nesta rodada.
