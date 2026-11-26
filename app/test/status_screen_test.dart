/// OmegaDrakon • TESTES — Cartão "Atualizador de SO" da aba Status
///
/// A aba Status lê o /health e agora mostra o bloco `os_updater` em um card
/// próprio (pacotes, firmwares, falhas do ciclo, reboot pendente e kernel) e
/// pinta de laranja os checks `degraded` — antes o `os_updater` com reboot
/// pendente aparecia com o mesmo verde de "tudo certo".
///
/// O que este teste prova:
///   - o card mostra os números estruturados do /health (sem parsear texto);
///   - reboot pendente aparece escrito na tela;
///   - o check `os_updater` degraded ganha o ícone de alerta, e um check
///     `degraded` com ok=false continua vermelho;
///   - servidor antigo (sem o bloco) não quebra a aba: o card simplesmente
///     não aparece.
library;

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:omegadrakon/screens/status_screen.dart';
import 'package:omegadrakon/services/od_api.dart';

http.Response _json(Object body) => http.Response(
      jsonEncode(body),
      200,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );

Map<String, dynamic> _health({
  bool comBloco = true,
  bool reboot = true,
  int falhas = 0,
}) {
  final corpo = <String, dynamic>{
    'ok': true,
    'status': 'up',
    'checks': {
      'api': {'name': 'api', 'ok': true, 'status': 'up', 'detail': 'ok'},
      'os_updater': {
        'name': 'os_updater',
        'ok': true,
        'status': reboot ? 'degraded' : 'up',
        'detail': 'pacotes=67 firmwares=51 falhas=$falhas '
            'reboot_pendente=${reboot ? 'sim' : 'nao'} kernel=6.8.0-147-generic',
        'critical': false,
      },
      'loops': {'name': 'loops', 'ok': false, 'status': 'degraded', 'detail': 'x'},
    },
  };
  if (comBloco) {
    corpo['os_updater'] = {
      'ok': true,
      'precisa_reboot': reboot,
      'pendente_reboot': false,
      'upgradable': 67,
      'firmware_upgrades': 51,
      'falhas_consecutivas': falhas,
      'sucessos_consecutivos': 1,
      'ultima_execucao': 1794273354.0,
      'kernel': '6.8.0-147-generic',
    };
  }
  return corpo;
}

OdApi _apiCom(Map<String, dynamic> health) => OdApi(
      baseUrl: 'http://od.test:8000',
      apiKey: 'od_teste',
      client: MockClient((r) async {
        if (r.url.path == '/health') return _json(health);
        if (r.url.path == '/capabilities') {
          return _json({'version': '1.46.1', 'counts': {'actions': 1}});
        }
        if (r.url.path == '/supervision') {
          return _json({'restarts': 0, 'loops': []});
        }
        return http.Response('{}', 404);
      }),
    );

Future<void> _abrir(WidgetTester tester, OdApi api) async {
  await tester.pumpWidget(MaterialApp(home: Scaffold(body: StatusScreen(api: api))));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('mostra pacotes, firmwares e reboot pendente do /health',
      (tester) async {
    await _abrir(tester, _apiCom(_health()));

    expect(find.text('Atualizador de SO'), findsOneWidget);
    expect(find.text('Pacotes'), findsOneWidget);
    expect(find.text('67'), findsOneWidget);
    expect(find.text('Firmwares'), findsOneWidget);
    expect(find.text('51'), findsOneWidget);
    expect(find.text('Reboot pendente'), findsOneWidget);
    expect(find.text('sim'), findsOneWidget);
    expect(find.text('6.8.0-147-generic'), findsOneWidget);
    // Check degraded do os_updater: alerta laranja, não o verde de tudo ok.
    expect(find.byIcon(Icons.warning_amber), findsOneWidget);
    // ok=false continua vermelho, mesmo com status degraded.
    expect(find.byIcon(Icons.close), findsOneWidget);
  });

  testWidgets('falha do ciclo aparece no card', (tester) async {
    await _abrir(tester, _apiCom(_health(reboot: false, falhas: 2)));
    expect(find.text('Falhas do ciclo'), findsOneWidget);
    expect(find.text('2'), findsOneWidget);
    expect(find.text('não'), findsOneWidget);
  });

  testWidgets('servidor antigo sem o bloco não quebra a aba', (tester) async {
    // Cada pump é uma árvore NOVA: o State do StatusScreen não é reusado.
    await _abrir(tester, _apiCom(_health(comBloco: false)));
    expect(find.text('Atualizador de SO'), findsNothing);
    expect(find.text('Checks (3)'), findsOneWidget);
  });
}
