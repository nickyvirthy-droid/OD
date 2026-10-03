"""Testes do helper local de autorização Google (tools/google_oauth_helper.py).

O helper roda no computador do dono e resolve o problema de "não consigo
copiar nada": ele mesmo abre o navegador, captura a URL de retorno em
http://localhost:8766/ e envia o código ao servidor por SSH (ou salva em
arquivo, que é só mandar por scp).

Aqui se prova: (1) a URL embutida bate com config/google_credentials.json
(redirect_uri=http://localhost:8766/ e os 3 escopos de leitura, sem segredo);
(2) o servidor local captura ?code= e grava o arquivo; (3) a página de
confirmação responde 200; (4) erro do Google (access_denied) sai com código 1;
(5) porta ocupada é recusada; (6) falha de SSH vira mensagem legível.
"""

from __future__ import annotations

import socket
import threading
import time
import urllib.request

from tools import google_oauth_helper as helper


def _porta_livre() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _rodar_main(argv: list[str]) -> tuple[list[int], threading.Thread]:
    """Roda helper.main numa thread (ele bloqueia esperando o código)."""
    codigos: list[int] = []
    thread = threading.Thread(
        target=lambda: codigos.append(helper.main(argv)), daemon=True
    )
    thread.start()
    return codigos, thread


def _esperar_porta(porta: int, limite: float = 4.0) -> None:
    fim = time.time() + limite
    while time.time() < fim:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", porta)) == 0:
                return
        time.sleep(0.05)
    raise AssertionError(f"porta {porta} nunca abriu")


class TestUrlEmbutida:
    def test_redirect_bate_com_o_config(self):
        # o que o navegador pede é EXATAMENTE o que o servidor troca
        assert "redirect_uri=http%3A%2F%2Flocalhost%3A8766%2F" in helper.CONSENT_URL

    def test_os_tres_escopos_de_leitura(self):
        for escopo in ("drive.readonly", "calendar.readonly", "gmail.readonly"):
            assert escopo in helper.CONSENT_URL
        # escrita não existe (decisão do dono: leitura primeiro)
        assert "gmail.compose" not in helper.CONSENT_URL

    def test_nao_vaza_client_secret(self):
        assert "client_secret" not in helper.CONSENT_URL
        assert "GOCSPX" not in helper.CONSENT_URL

    def test_offline_e_consentimento(self):
        # access_type=offline + prompt=consent garantem o refresh_token
        assert "access_type=offline" in helper.CONSENT_URL
        assert "prompt=consent" in helper.CONSENT_URL


class TestCaptura:
    def test_code_capturado_vira_arquivo(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        porta = _porta_livre()
        codigos, thread = _rodar_main(
            ["--dry-run", "--no-open", "--no-ssh", "--porta", str(porta)]
        )
        _esperar_porta(porta)
        with urllib.request.urlopen(
            f"http://127.0.0.1:{porta}/?code=TESTE-42&scope=x", timeout=5
        ) as resp:
            corpo = resp.read().decode("utf-8")
            assert resp.status == 200
            assert "Código recebido" in corpo
        thread.join(timeout=10)
        assert not thread.is_alive()
        assert codigos == [0]
        salvo = (tmp_path / "google_auth_url.txt").read_text(encoding="utf-8").strip()
        assert "code=TESTE-42" in salvo

    def test_erro_do_google_falha_com_1(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        porta = _porta_livre()
        codigos, thread = _rodar_main(
            ["--dry-run", "--no-open", "--no-ssh", "--porta", str(porta)]
        )
        _esperar_porta(porta)
        with urllib.request.urlopen(
            f"http://127.0.0.1:{porta}/?error=access_denied", timeout=5
        ) as resp:
            assert resp.status == 200  # a página responde mesmo no erro
        thread.join(timeout=10)
        assert codigos == [1]
        assert not (tmp_path / "google_auth_url.txt").exists()


class TestPorta:
    def test_porta_ocupada_e_recusada(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as ocupada:
            ocupada.bind(("127.0.0.1", 0))
            ocupada.listen(1)
            porta = ocupada.getsockname()[1]
            assert (
                helper.main(["--dry-run", "--no-open", "--porta", str(porta)]) == 1
            )


class TestEnvio:
    def test_envio_sem_ssh_falha_com_mensagem(self):
        # host inexistente → mensagem legível, nunca exceção
        saida = helper._enviar_para_o_servidor(
            "http://localhost:8766/?code=x", "invalid.invalid:caminho/x.txt"
        )
        assert "SSH" in saida

    def test_alvo_sem_caminho_usa_o_default(self):
        saida = helper._enviar_para_o_servidor("http://x/?code=y", "sem-caminho")
        assert "SSH" in saida  # falha rápido, sem travar o fluxo
