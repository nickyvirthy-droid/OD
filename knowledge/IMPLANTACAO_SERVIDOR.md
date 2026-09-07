# Implantação do Servidor — Detalhes Reais

> **Status:** nota operacional (não é spec)
> **Escopo:** `/home/alex/OmegaDrakon`
> **Assinatura:** `OD // CORE`

## 1. Onde tudo está, de fato

- **Raiz do projeto:** `/home/alex/OmegaDrakon`
- **Launcher:** `runtime/launcher.py` (modos: api|telegram|mqtt|presence|vision|recovery|all|capabilities)
- **LLM real:** llama-server em `/opt/omegadrakon/ai/runtimes/llama`
- **Modelo do LLM:** `/home/alex/LLM/data/models/gemma-4-E4B-it-Q4_K_M.gguf`
- **Audio (STT/TTS):** `voice/stt/` e `voice/tts/` na raiz do projeto
- **Binários reaproveitados do legado:** whisper-cli, ggml-base.bin, piper, dii_pt-BR.onnx, pt_BR-faber-medium.onnx

## 2. Usuário e services de sistema

- od-core: `systemctl --user` — unit `runtime/systemd/od-core.service`
- od-llm: `systemctl --user` — unit `runtime/systemd/od-llm.service`
- install-user.sh: copia as duas units para `$XDG_CONFIG_HOME/systemd/user/` e ativa

## 3. O que o od-llm.service aponta

- WorkingDirectory: `/opt/omegadrakon/ai/runtimes/llama`
- ExecStart: `llama-server` com o modelo gemma-4-E4B-it-Q4_K_M.gguf
- Escuta: 127.0.0.1:8081

## 4. Legados fora do OD (ainda presentes no servidor)

- `/home/alex/nicky`
- `/home/alex/NV`
- `/home/alex/nexus`
- `/home/alex/Legado` (pasta de consolidação dos documentos reintegrados)

## 5. Backups/zips de legados (referência)

- `/home/alex/Projetos/nicky_legado.zip`
- `/home/alex/Projetos/nv_legado.zip`
- `/home/alex/Projetos/nx_legado.zip`

## 6. Referências no OD que ainda citam caminhos externos

- `runtime/control_bridge/bridge.py`: bloqueia `/home/alex/Legado` e `/opt/omegadrakon` como paths proibidos na bridge
- `runtime/systemd/od-llm.service`: WorkingDirectory e ExecStart apontam para `/opt/omegadrakon/...`
- `docs/README_VERSAO.md`: tabela de evidência cita `/opt/omegadrakon/ai/runtimes/llama`
- `agents/nicky_virthy/SOUL.md`: menciona `/home/alex/Legado` como separado do ecossistema ativo
- `tests/test_security.py`: cena “agent cannot touch legacy system” usa `/home/alex/Legado/nicky/config.py`
- `conversation_abc/session.json`: notas sobre os zips de Projetos/ e as pastas nicky/NV/nexus

## 7. Regra prática

- Caminhos internos do OD são `/home/alex/OmegaDrakon/...`
- Caminhos externos são legados reais do servidor que o OD não deve tocar
- Control Bridge já rejeita os legados no nivel de comando; o resto é questão de documentação e de referencias no repo
