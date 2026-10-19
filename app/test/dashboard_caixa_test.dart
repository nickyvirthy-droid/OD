/// OmegaDrakon • TESTES — Botão da caixa de arquivos no Painel (v1.42.0)
///
/// Decisão do dono (19/10): "com o tailscale funcionando não existe
/// finalidade em embutir, seria melhor apenas um botão que abre o
/// navegador". O app não ganha webview: um botão no card "Meu painel"
/// abre a caixa (File Browser) no navegador de fora.
///
/// - A URI é derivada da MESMA host que o app usa para falar com o
///   od-core (IP da tailnet), trocando a porta para 8410 — o bind duplo
///   da caixa (127.0.0.1 para as actions + tailnet para o dono) é de
///   19/10 e está no compose.
/// - O toque num ambiente sem navegador (teste) não pode derrubar a tela:
///   o caminho honesto é o aviso do SnackBar.
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

/// Painel de uma conta simples (role != admin): o card "Meu painel"
/// carrega sem seção admin — /auth/me e /dashboard/stats são os dois
/// únicos endpoints que o _refresh exige nesse caso.
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

  test('URI da caixa: mesma host do od-core local na porta 8410', () {
    expect(odFileBrowserUri.scheme, 'http');
    expect(odFileBrowserUri.host, Uri.parse(odDefaultLocalUrl).host);
    expect(odFileBrowserUri.port, 8410);
    expect(odFileBrowserUri.toString(), 'http://100.77.67.53:8410');
  });

  testWidgets('Painel traz o botão "Caixa de arquivos (abre no navegador)"',
      (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: DashboardScreen(api: _apiPainel())),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Caixa de arquivos (abre no navegador)'), findsOneWidget);
    expect(find.byIcon(Icons.folder_open_outlined), findsOneWidget);
  });

  testWidgets('toque abre a caixa no navegador de fora (URI certa) e, se o '
      'lançador recusar, aviso honesto', (tester) async {
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

    await tester.ensureVisible(find.text('Caixa de arquivos (abre no navegador)'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Caixa de arquivos (abre no navegador)'));
    await tester.pumpAndSettle();

    expect(chamadas, isNotEmpty,
        reason: 'o botão tem de chamar o lançador de URLs');
    expect(
      chamadas.map((c) => c.arguments.toString()).join(' '),
      contains('http://100.77.67.53:8410'),
      reason: 'a URI tem de ser a caixa na tailnet (odFileBrowserUri)',
    );
    expect(
      find.text('Não abriu — confere se o Tailscale está ligado.'),
      findsOneWidget,
    );
    expect(find.byType(DashboardScreen), findsOneWidget);
  });
}
