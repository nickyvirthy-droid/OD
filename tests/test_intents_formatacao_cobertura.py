#!/usr/bin/env python3
"""
OMEGA DRAKON • TESTS
Módulo: tests/test_intents_formatacao_cobertura.py
Descrição: cobertura das respostas PT-BR de `format_intent_result` que o
           chat usa no fastpath (clima, luzes/raio-X do lar, portas, IP,
           Google Workspace, rádio e Vigia). O gate de cobertura do CI
           (`--cov-fail-under=90`) mede linhas: estes são os ramos que
           ficaram sem guarda depois das entregas de outubro/novembro.
           Função pura — nenhuma action, rede ou disco é chamada.
Interface Viva: Nicky Virthy
Arquiteto: Alex Projeti

Baseado em:
  - core/intents.py (format_intent_result e formatadores)
"""

from __future__ import annotations

import pytest

from core.intents import format_intent_result


class TestHaWeather:
    def test_sem_temperatura_cai_ao_llm(self) -> None:
        assert format_intent_result("ha_weather", {"ok": True}) is None

    def test_leitura_completa_traduz_condicao_e_extras(self) -> None:
        texto = format_intent_result("ha_weather", {
            "ok": True, "temperature": 26, "temperature_unit": "°C",
            "condition": "partlycloudy", "humidity": 61,
            "wind_speed": 12, "wind_speed_unit": "km/h",
        })
        assert "Clima na região da casa: 26°C" in texto
        assert "parcialmente nublado" in texto
        assert "umidade 61%" in texto
        assert "vento 12 km/h" in texto
        assert "Fonte: Home Assistant" in texto

    def test_condicao_desconhecida_sai_como_veio(self) -> None:
        texto = format_intent_result("ha_weather", {
            "ok": True, "temperature": 19, "condition": "weird-code",
        })
        assert "weird-code" in texto
        assert "umidade" not in texto


class TestWeatherCity:
    def test_erro_da_fonte_nao_vira_resposta(self) -> None:
        assert format_intent_result("weather_city", {
            "ok": True, "error": "fonte_indisponivel",
        }) is None


class TestExchangeRate:
    def test_erro_e_sem_bid_caem_ao_llm(self) -> None:
        assert format_intent_result("exchange_rate", {
            "ok": True, "error": "fonte_indisponivel",
        }) is None
        assert format_intent_result("exchange_rate", {"ok": True}) is None

    def test_cotacao_completa_formata_pt_br(self) -> None:
        texto = format_intent_result("exchange_rate", {
            "ok": True, "codigo": "USD", "moeda": "dólar",
            "bid": 5.1844, "ask": 5.1901, "variacao_pct": -0.42,
            "maximo": 5.21, "minimo": 5.17,
        })
        assert "💱 Dólar: R$ 5,1844" in texto
        assert "venda R$ 5,1901" in texto
        assert "📉 Variação hoje: -0.42%" in texto
        assert "Faixa do dia: R$ 5,17 – R$ 5,21" in texto

    def test_cotacao_minima_sem_variacao_ou_faixa(self) -> None:
        texto = format_intent_result("exchange_rate", {
            "ok": True, "codigo": "BTC", "bid": 350123.45, "variacao_pct": 1.5,
        })
        assert "R$ 350123,45" in texto
        assert "📈 Variação" in texto
        assert "Faixa do dia" not in texto


class TestLuzesERaioX:
    def test_lights_vazio(self) -> None:
        texto = format_intent_result("ha_lights", {"ok": True, "lights": []})
        assert "Nenhuma luz/interruptor acessível" in texto

    def test_lights_com_acesas_e_apagadas(self) -> None:
        texto = format_intent_result("ha_lights", {
            "ok": True, "on": 1, "total": 2, "lights": [
                {"name": "Cozinha", "entity": "light.cozinha", "on": True},
                {"name": "Sala", "entity": "light.sala", "on": False},
            ],
        })
        assert "1 acesa(s) de 2" in texto
        assert "🟢 Cozinha (light.cozinha)" in texto
        assert "Apagadas: Sala" in texto

    def test_lights_nenhuma_acesa(self) -> None:
        texto = format_intent_result("ha_lights", {
            "ok": True, "on": 0, "total": 1,
            "lights": [{"name": "Sala", "on": False}],
        })
        assert "nenhuma acesa" in texto
        assert "Apagadas: Sala" in texto

    def test_summary_completo(self) -> None:
        texto = format_intent_result("ha_summary", {
            "ok": True,
            "weather": {"temperature": 27, "temperature_unit": "°C",
                        "humidity": 55},
            "lights": {"on": 2, "total": 5},
            "people": [{"entity": "person.alex", "state": "home"}],
            "batteries": [{"name": "Porta", "level": 82}],
            "router": {"external_ip": "203.0.113.9", "download_kib_s": 1200},
        })
        assert "Raio-X do lar" in texto
        assert "Clima: 27°C, umidade 55%" in texto
        assert "2 acesa(s) de 5" in texto
        assert "person.alex: home" in texto
        assert "Bateria Porta: 82%" in texto
        assert "IP externo 203.0.113.9, download 1200 KiB/s" in texto

    def test_summary_minimo(self) -> None:
        texto = format_intent_result("ha_summary", {"ok": True})
        assert "Luzes: 0 acesa(s) de 0" in texto
        assert "IP externo" not in texto


class TestRede:
    def test_network_hosts_vazio(self) -> None:
        texto = format_intent_result("network_hosts", {"ok": True, "count": 0})
        assert "Nenhum dispositivo vizinho" in texto

    def test_network_hosts_com_nome_fabricante_e_corte(self) -> None:
        hosts = [
            {"ip": "192.168.0.10", "mac": "aa", "interface": "wlan0",
             "state": "REACHABLE", "nome": "TV Sala"},
            {"ip": "192.168.0.11", "mac": "bb", "interface": "wlan0",
             "state": "STALE", "fabricante": "Acme"},
        ]
        hosts += [
            {"ip": f"192.168.0.{i}", "mac": "cc", "interface": "eth0",
             "state": "STALE"} for i in range(12, 23)
        ]
        # 2 iniciais + 11 do range = 13 total, mostra 10, sobram 3
        texto = format_intent_result("network_hosts", {
            "ok": True, "hosts": hosts, "count": len(hosts),
        })
        assert "TV Sala · 192.168.0.10" in texto
        assert "Acme" in texto
        assert "e mais 3" in texto


class TestPortasEIp:
    def test_listening_ports_vazio(self) -> None:
        texto = format_intent_result("listening_ports", {"ok": True, "ports": []})
        assert "Nenhuma porta TCP escutando" in texto

    def test_listening_ports_com_processo_e_corte(self) -> None:
        ports = [
            {"port": 8000, "addr": "0.0.0.0", "process": "python3"},
            {"port": 22, "addr": "127.0.0.1", "process": ""},
        ] + [{"port": 9000 + i, "addr": "0.0.0.0"} for i in range(11)]
        texto = format_intent_result("listening_ports", {"ok": True, "ports": ports})
        assert "13 porta(s)" in texto
        assert "python3" in texto
        assert "e mais 1" in texto

    def test_ip_sem_nada_cai_ao_llm(self) -> None:
        assert format_intent_result("ip_address", {"ok": True}) is None

    def test_ip_lista_e_saida(self) -> None:
        # addresses[:8] mostra apenas os primeiros 8
        texto = format_intent_result("ip_address", {
            "ok": True, "addresses": [f"10.0.0.{i}" for i in range(1, 10)],
            "outbound": "10.0.0.1",
        })
        assert "10.0.0.1 (saída)" in texto
        assert "10.0.0.8" in texto
        assert "10.0.0.9" not in texto  # 9º é cortado pelo limite de 8

    def test_ip_saida_fora_da_lista(self) -> None:
        texto = format_intent_result("ip_address", {
            "ok": True, "addresses": ["192.168.0.250"], "outbound": "100.64.0.9",
        })
        assert "100.64.0.9 (saída padrão)" in texto


class TestGoogleLeituras:
    def test_gmail_vazio(self) -> None:
        texto = format_intent_result("google_gmail_list", {
            "ok": True, "messages": [],
        })
        assert "Nenhuma mensagem" in texto

    def test_gmail_lista_com_remetente_e_corte(self) -> None:
        msgs = [{"subject": "Nota", "from": "a@b.c"}] + [{} for _ in range(11)]
        texto = format_intent_result("google_gmail_list", {
            "ok": True, "messages": msgs,
        })
        assert "12 mensagem(ns)" in texto
        assert "(sem assunto)" in texto
        assert "de a@b.c" in texto
        assert "e mais 2 não listada" in texto

    def test_gmail_sem_credencial_explica(self) -> None:
        texto = format_intent_result("google_gmail_list", {
            "ok": False, "error": "Google não configurado",
        })
        assert "ainda não está configurado/autorizado" in texto

    def test_gmail_outro_erro_e_honesto(self) -> None:
        texto = format_intent_result("google_gmail_list", {
            "ok": False, "error": "quota excedida",
        })
        assert "Google indisponível agora: quota excedida" in texto
        assert "falha na consulta" in format_intent_result(
            "google_gmail_list", {"ok": False}
        )

    def test_calendario_vazio_e_com_local(self) -> None:
        vazio = format_intent_result("google_calendar_events", {
            "ok": True, "events": [], "days": 3,
        })
        assert "Nenhum compromisso nos próximos 3" in vazio
        cheio = format_intent_result("google_calendar_events", {
            "ok": True, "events": [
                {"summary": "Consulta", "start": {"dateTime": "2026-11-24T09:00:00"},
                 "location": "Clínica"},
            ],
        })
        assert "Consulta" in cheio
        assert "📍 Clínica" in cheio

    def test_drive_vazio_e_corte(self) -> None:
        vazio = format_intent_result("google_drive_list", {"ok": True, "files": []})
        assert "Nenhum arquivo" in vazio
        arquivos = [{"name": f"arq{i}", "mime_type": "text/plain"}
                    for i in range(16)]
        texto = format_intent_result("google_drive_list", {
            "ok": True, "files": arquivos,
        })
        assert "16 arquivo(s)" in texto
        assert "e mais 1 não listado" in texto


class TestRadioEVigia:
    def test_radio_parada_com_dica(self) -> None:
        texto = format_intent_result("radio_stop", {
            "ok": True, "status": "parado",
            "hint": "rádio parada — nada tocava",
        })
        assert texto.startswith("📻 Rádio parada")
        assert "nada tocava" in texto

    def test_radio_parada_sem_status(self) -> None:
        assert format_intent_result("radio_stop", {"ok": True}) == "📻 Rádio parada."

    def test_radio_volume_sem_leitura(self) -> None:
        assert format_intent_result("radio_volume", {"ok": True}) is None

    def test_radio_status_tocando_com_detalhes(self) -> None:
        texto = format_intent_result("radio_status", {
            "ok": True, "status": "tocando", "pid": 1234,
            "volume_sink": "alsa_output", "hint": "playlist A",
        })
        assert "player 1234" in texto
        assert "Saída: alsa_output" in texto
        assert "playlist A" in texto

    def test_radio_status_parado_e_desconhecido(self) -> None:
        assert format_intent_result("radio_status", {
            "ok": True, "status": "parado",
        }) == "📻 Rádio parada."
        assert format_intent_result("radio_status", {"ok": True}) is None

    def test_vigia_erro_com_lista_de_pendentes(self) -> None:
        texto = format_intent_result("network_bloquear", {
            "ok": False, "error": "mais_de_um_pendente",
            "pendentes": [{"mac": "aa:bb:cc:dd:ee:ff", "n": 2}],
        })
        assert "⛔ mais_de_um_pendente" in texto
        assert "2. aa:bb:cc:dd:ee:ff" in texto
        assert "Responda o número" in texto


class TestOutrosFormatadores:
    def test_busca_web_trunca_trecho_longo(self) -> None:
        texto = format_intent_result("web_search", {
            "ok": True, "query": "python", "source": "DuckDuckGo",
            "results": [{"title": "Doc", "url": "https://x",
                         "snippet": "a" * 250}],
        })
        assert "a" * 177 + "…" in texto
        assert "Fonte: DuckDuckGo" in texto

    def test_cpu_temp_sem_leitura_cai_ao_llm(self) -> None:
        assert format_intent_result("cpu_temp", {"ok": True}) is None

    def test_cpu_temp_com_leituras(self) -> None:
        texto = format_intent_result("cpu_temp", {
            "ok": True, "celsius": 48.5,
            "hottest": {"type": "x86_pkg_temp"},
            "readings": [{"type": "x86_pkg_temp", "celsius": 48.5},
                         {"zone": "thermal_zone1", "celsius": 40.0}],
        })
        assert "48.5°C" in texto
        assert "x86_pkg_temp" in texto
        assert "thermal_zone1: 40.0°C" in texto

    def test_readiness_sem_itens_cai_ao_llm(self) -> None:
        assert format_intent_result("readiness_report", {"ok": True}) is None

    def test_readiness_com_itens_e_pendentes(self) -> None:
        texto = format_intent_result("readiness_report", {
            "ok": True, "pontos": 1, "total": 2, "percent": 50.0,
            "itens": [{"nome": "disco", "ok": True, "detalhe": "ok"},
                      {"nome": "backup", "ok": False, "detalhe": "velho"}],
            "pendentes": ["backup"],
        })
        assert "Prontidão: 1/2 (50.0%)" in texto
        assert "✅ disco: ok" in texto
        assert "⚠️ backup: velho" in texto
        assert "Pendente: backup" in texto

    def test_saude_desconhecida_nunca_volta_vazia(self) -> None:
        texto = format_intent_result("saude_coisa_nova", {"ok": True})
        assert "Referência indisponível por enquanto." in texto
        assert "não substitui" in texto or "médic" in texto.lower()
