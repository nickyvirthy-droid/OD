/// OmegaDrakon • TESTES — Botão da biblioteca de livros no Painel
///
/// Calibre Web interligado (3ª da série "uma por vez", decisão do dono
/// em 19/10: "configurar e interligar"). O app NÃO ganha webview — mesmo
/// desenho do botão da caixa de arquivos: um toque abre a biblioteca no
/// navegador de fora (Tailscale).
///
/// - A URI deriva da MESMA host do od-core local (IP da tailnet) com a
///   porta 8420 — bind duplo do Calibre Web desde 19/10 (127.0.0.1 para
///   as actions + tailnet para o dono), no compose.
/// - Toque sem navegador (teste) → aviso honesto no SnackBar; a tela
///   nunca trava.
library;

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:omegadrakon/screens/dashboard_screen.dart';
import 'package:omegadrakon/services/od_api.dart';
import 'package:shared_preferences/shared_preferences.dart';

http.Response _json(Object body) => http.Response(
      jsonEncode(body),
      200,
      headers: {'content-type': 'application/json'},
    );

/// Painel de conta simples (role != admin) — mesmos dois endpoints que o
/// _refresh exige sem seção admin.
OdApi _apiPainel() => OdApi(
      baseUrl: 'http://od.test:8000',
      client: MockClient((request) async {
        switch (request.url.path) {
          case '/auth/me':
            return _json({
              'user': {'username': 'alex'},
              'role': 'user',
              'via': 'teste',
            });
          case '/dashboard/stats':
            return _json({
              'history': {
                'per_user': {
                  'alex': {'messages': 7},
                },
              },
            });
          default:
            return http.Response('not found', 404);
        }
      }),
    );

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('URI da biblioteca: mesma host do od-core local na porta 8420', () {
    expect(odCalibreUri.scheme, 'http');
    expect(odCalibreUri.host, Uri.parse(odDefaultLocalUrl).host);
    expect(odCalibreUri.port, 8420);
    expect(odCalibreUri.toString(), 'http://100.77.67.53:8420');
  });

  testWidgets('Painel traz o botão "Biblioteca de livros (abre no navegador)"',
      (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: DashboardScreen(api: _apiPainel())),
      ),
    );
    await tester.pumpAndSettle();

    expect(
        find.text('Biblioteca de livros (abre no navegador)'), findsOneWidget);
    expect(find.byIcon(Icons.menu_book_outlined), findsOneWidget);
  });

  testWidgets('toque abre a biblioteca no navegador de fora (URI certa) e, se '
      'o lançador recusar, aviso honesto', (tester) async {
    final chamadas = <MethodCall>[];
    const canal = MethodChannel('plugins.flutter.io/url_launcher');
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(canal, (call) async {
      chamadas.add(call);
      return false; // "navegador recusa" → caminho do aviso honesto
    });
    addTearDown(() => TestDefaultBinaryMessengerBinding
        .instance.defaultBinaryMessenger
        .setMockMethodCallHandler(canal, null));

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: DashboardScreen(api: _apiPainel())),
      ),
    );
    await tester.pumpAndSettle();

    await tester.ensureVisible(
        find.text('Biblioteca de livros (abre no navegador)'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Biblioteca de livros (abre no navegador)'));
    await tester.pumpAndSettle();

    expect(chamadas, isNotEmpty,
        reason: 'o botão tem de chamar o lançador de URLs');
    expect(
      chamadas.map((c) => c.arguments.toString()).join(' '),
      contains('http://100.77.67.53:8420'),
      reason: 'a URI tem de ser a biblioteca na tailnet (odCalibreUri)',
    );
    expect(
      find.text('Não abriu — confere se o Tailscale está ligado.'),
      findsOneWidget,
    );
    expect(find.byType(DashboardScreen), findsOneWidget);
  });
}
