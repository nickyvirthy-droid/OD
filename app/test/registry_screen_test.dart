/// OmegaDrakon • TESTES — Tela do Registro Mestre (aba "Verificar", v1.24.0)
///
/// Cenário REAL (2026-10-09): o dono perguntou "porque atualizou o APP se
/// ele não possui a tela de Registro Mestre" — a aba Verificar passa a
/// existir no app com a MESMA função do site /site/verificacao.html:
/// consulta pública pelo ID gravado na peça, selo de autenticidade, foto,
/// username do dono (nome real nunca) e a sala de bate-papo.
library;

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:omegadrakon/screens/registry_screen.dart';
import 'package:omegadrakon/services/od_api.dart';
import 'package:shared_preferences/shared_preferences.dart';

http.Response _json(Object body, [int status = 200]) => http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json'},
    );

const _pecaJson = {
  'public_id': 'OD-PROD-2026-0001',
  'engraved_code': 'NV-ABI-7F3A',
  'name': 'Anel Abissal (exemplo)',
  'collection': 'ABISSAL',
  'kind': 'exclusiva',
  'status': 'estoque',
  'owner_username': null,
  'created_at': 1791582200.0,
  'sold_at': null,
  'registered_at': null,
  'photo': '/registry/OD-PROD-2026-0001/photo',
  'registered': false,
};

/// API com o roteiro da peça exemplo: verificação 200, foto JPEG (bytes
/// mínimos), sala com uma mensagem e POST que devolve 201.
///
/// O mock NORMALIZA o código como o servidor faz (maiúsculas, sem
/// separadores) — assim o teste digita "odprod20260001" e acha, do mesmo
/// jeito que a produção. O chat honra `?since=` (sem isso, o polling de
/// 4 s reentrega a mesma mensagem e o pumpAndSettle nunca assenta).
OdApi _apiComPeca({String apiKey = '', String username = ''}) => OdApi(
      baseUrl: 'http://od.test:8000',
      apiKey: apiKey,
      username: username,
      client: MockClient((request) async {
        final match = RegExp(r'^/registry/([^/]+)(/photo|/chat)?$')
            .firstMatch(request.url.path);
        if (match == null) return http.Response('not found', 404);
        final norm = match
            .group(1)!
            .toUpperCase()
            .replaceAll(RegExp('[^A-Z0-9]'), '');
        if (norm != 'ODPROD20260001') {
          return http.Response('not found', 404);
        }
        final sub = match.group(2);
        if (sub == '/photo') {
          // PNG 1×1 REAL (69 B) — bytes falsos de "JPEG mínimo" estouram
          // "Invalid image data" no codec do teste widget.
          return http.Response.bytes(
            base64Decode(
              'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4'
              'nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC',
            ),
            200,
            headers: {'content-type': 'image/png'},
          );
        }
        if (sub == '/chat') {
          if (request.method == 'POST') {
            final body = jsonDecode(request.body) as Map<String, dynamic>;
            return _json({
              'ok': true,
              'mensagem': {
                'id': 7,
                'public_id': 'OD-PROD-2026-0001',
                'username': username.isEmpty ? 'alex' : username,
                'text': body['text'],
                'created_at': 1791582900.0,
              },
            }, 201);
          }
          final since =
              int.tryParse(request.url.queryParameters['since'] ?? '0') ?? 0;
          final mensagens = [
            {
              'id': 6,
              'public_id': 'OD-PROD-2026-0001',
              'username': 'fulano',
              'text': 'Ainda tem disponível?',
              'created_at': 1791582800.0,
            },
          ].where((m) => (m['id']! as int) > since).toList();
          return _json({
            'ok': true,
            'total': mensagens.length,
            'mensagens': mensagens,
          });
        }
        return _json({'ok': true, 'peca': _pecaJson});
      }),
    );

Widget _wrap(Widget child) => MaterialApp(home: Scaffold(body: child));

/// A sala (e o envio) ficam abaixo da dobra na viewport 800×600 do teste —
/// a ListView da página é preguiçosa e só constrói o que entra na tela.
Future<void> _rolarAteSala(WidgetTester tester, Finder alvo) async {
  await tester.scrollUntilVisible(
    alvo,
    240,
    scrollable: find.byType(Scrollable).first,
  );
  await tester.pumpAndSettle();
}

Future<void> _verificar(WidgetTester tester, {String codigo = 'odprod20260001'}) async {
  await tester.enterText(find.byType(TextField).first, codigo);
  await tester.tap(find.text('Verificar'));
  await tester.pumpAndSettle();
}

void main() {
  setUpAll(() {
    SharedPreferences.setMockInitialValues({});
  });

  group('RegistryScreen — verificação pública', () {
    testWidgets('mostra selo, peça, foto e o ID achado sem hífen',
        (tester) async {
      await tester.pumpWidget(_wrap(RegistryScreen(api: _apiComPeca())));
      await tester.pumpAndSettle();

      // dica de busca sem hífen presente desde o início
      expect(find.textContaining('Sem hífen também serve'), findsOneWidget);

      // digitou SEM hífen/espaços e achou
      await _verificar(tester);

      expect(find.text('✓ Peça autêntica'), findsOneWidget);
      expect(find.text('Anel Abissal (exemplo)'), findsOneWidget);
      expect(find.text('OD-PROD-2026-0001'), findsOneWidget);
      expect(find.text('NV-ABI-7F3A'), findsOneWidget);
      expect(find.text('Em estoque'), findsOneWidget);
      // foto renderizada (Image.memory com os bytes do mock)
      expect(find.byType(Image), findsOneWidget);
      // peça sem dono não exibe caixa de dono
      expect(find.textContaining('tem dono'), findsNothing);
    });

    testWidgets('peça registrada mostra o username do dono (nunca mais)',
        (tester) async {
      final api = OdApi(
        baseUrl: 'http://od.test:8000',
        client: MockClient((request) async {
          if (request.url.path == '/registry/OD-PROD-2026-0003') {
            return _json({
              'ok': true,
              'peca': {
                ..._pecaJson,
                'public_id': 'OD-PROD-2026-0003',
                'status': 'registrada',
                'owner_username': 'bia',
                'registered': true,
                'photo': null,
              },
            });
          }
          if (request.url.path == '/registry/OD-PROD-2026-0003/chat') {
            return _json({'ok': true, 'total': 0, 'mensagens': []});
          }
          return http.Response('not found', 404);
        }),
      );
      await tester.pumpWidget(_wrap(RegistryScreen(api: api)));
      await _verificar(tester, codigo: 'OD-PROD-2026-0003');

      expect(find.text('✓ Peça autêntica · registrada'), findsOneWidget);
      // o username aparece na caixa do dono E no texto da sala — checa a caixa
      expect(
        find.text(
            'Esta peça tem dono: @bia — o username é público; o nome real, nunca.'),
        findsOneWidget,
      );
      expect(find.byType(Image), findsNothing); // sem foto = sem Image
    });

    testWidgets('código desconhecido vira aviso, não exceção',
        (tester) async {
      final api = OdApi(
        baseUrl: 'http://od.test:8000',
        client: MockClient((_) async => http.Response('not found', 404)),
      );
      await tester.pumpWidget(_wrap(RegistryScreen(api: api)));
      await _verificar(tester, codigo: 'OD-PROD-1999-9999');

      expect(find.textContaining('não consta no Registro Mestre'),
          findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });

  group('RegistryScreen — sala de bate-papo', () {
    testWidgets('sem conta: lê a sala e avisa como escrever', (tester) async {
      await tester.pumpWidget(_wrap(RegistryScreen(api: _apiComPeca())));
      await _verificar(tester);
      await _rolarAteSala(tester, find.textContaining('@fulano'));

      // leitura pública: a mensagem do mock aparece
      expect(find.textContaining('@fulano'), findsOneWidget);
      expect(find.text('Ainda tem disponível?'), findsOneWidget);
      // sem conta: nota explicando, sem campo de envio
      expect(find.textContaining('Entre com sua conta'), findsOneWidget);
      expect(find.text('Mensagem'), findsNothing);
    });

    testWidgets('com conta: envia mensagem e ela entra na sala',
        (tester) async {
      final api = _apiComPeca(apiKey: 'od_teste', username: 'bia');
      await tester.pumpWidget(_wrap(RegistryScreen(api: api)));
      await _verificar(tester);
      await _rolarAteSala(tester, find.text('Mensagem'));

      expect(find.text('Mensagem'), findsOneWidget);
      await tester.enterText(find.byType(TextField).last, 'Qual o material?');
      await tester.tap(find.byIcon(Icons.send));
      await tester.pumpAndSettle();

      expect(find.text('Qual o material?'), findsOneWidget);
      expect(find.textContaining('@bia'), findsOneWidget);
    });
  });
}
