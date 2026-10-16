import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'od_api.dart';

/// Tema claro/escuro do app (TODO §3.8, 2026-10-16).
///
/// Três estados, iguais aos do site e do painel: **segue o aparelho** (padrão
/// de quem nunca escolheu), **claro** e **escuro**. A escolha vive no PERFIL
/// do servidor (`/profile/preferences`, a MESMA que o site e o painel leem) e
/// tem cópia local em `SharedPreferences` — o app abre já no tema certo, sem
/// rede e sem piscar.
///
/// Regra de precedência (a mesma dos outros dois clientes):
///   1. o perfil tem escolha EXPLÍCITA (claro/escuro) → ela vence: o dono
///      escolheu isso em algum aparelho;
///   2. o perfil ainda está no padrão e este aparelho tem escolha local →
///      o local SEMEIA o perfil (escolha feita offline não se perde);
///   3. sem escolha em lugar nenhum → segue o aparelho.
class ThemeService extends ValueNotifier<ThemeMode> {
  ThemeService() : super(ThemeMode.system);

  /// Instância única do app (o `main.dart` pinta o MaterialApp por ela).
  static final ThemeService instance = ThemeService();

  /// Chave da cópia local (o site usa a mesma em `localStorage`).
  static const String chaveLocal = 'od_theme';

  /// Texto → ThemeMode (qualquer coisa desconhecida é "segue o aparelho").
  static ThemeMode doTexto(String? valor) {
    switch (valor) {
      case 'light':
        return ThemeMode.light;
      case 'dark':
        return ThemeMode.dark;
      default:
        return ThemeMode.system;
    }
  }

  /// ThemeMode → texto do contrato da API (`system` | `light` | `dark`).
  static String paraTexto(ThemeMode modo) {
    switch (modo) {
      case ThemeMode.light:
        return 'light';
      case ThemeMode.dark:
        return 'dark';
      case ThemeMode.system:
        return 'system';
    }
  }

  /// Lê a cópia local. Nunca levanta: sem `SharedPreferences` o app abre no
  /// padrão (seguir o aparelho) em vez de travar o boot.
  Future<void> carregar() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      value = doTexto(prefs.getString(chaveLocal));
    } catch (_) {
      value = ThemeMode.system;
    }
  }

  Future<void> _gravarLocal(ThemeMode modo) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(chaveLocal, paraTexto(modo));
    } catch (_) {
      // Cache local indisponível: o tema vale para esta sessão e o perfil
      // (quando alcançável) continua sendo a verdade.
    }
  }

  /// Escolha do dono: aplica na hora, grava local e avisa o perfil.
  ///
  /// O envio ao servidor é **best-effort** — sem rede/sem conta o local já
  /// resolve a tela; a próxima sincronia com o perfil semeia a escolha.
  Future<void> definir(ThemeMode modo, {OdApi? api}) async {
    value = modo;
    await _gravarLocal(modo);
    if (api == null) return;
    try {
      await api.setPreferences(theme: paraTexto(modo));
    } catch (_) {
      // Silêncio proposital: a escolha já está aplicada e salva aqui.
    }
  }

  /// Adota o que está no PERFIL (escolha feita em outro aparelho) ou semeia
  /// o perfil com a escolha local. Devolve `true` quando o tema mudou.
  Future<bool> sincronizar(OdApi? api) async {
    if (api == null) return false;
    Map<String, dynamic> dados;
    try {
      dados = await api.getMe();
    } catch (_) {
      return false; // servidor fora: o cache local já está aplicado
    }
    final preferencias = dados['preferences'];
    final doServidor = doTexto(
      preferencias is Map ? preferencias['theme']?.toString() : null,
    );
    if (doServidor == ThemeMode.light || doServidor == ThemeMode.dark) {
      if (doServidor == value) return false;
      value = doServidor;
      await _gravarLocal(doServidor);
      return true;
    }
    if (value != ThemeMode.system) {
      try {
        await api.setPreferences(theme: paraTexto(value));
      } catch (_) {
        // Sem rede agora; o perfil recebe na próxima sincronia.
      }
    }
    return false;
  }
}
