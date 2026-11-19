/// OmegaDrakon • TESTES — Vigia da Rede no app (ordem do dono, 19/11)
///
/// O aviso de dispositivo desconhecido chega no Telegram e no app; até 19/11
/// não havia botão onde o aviso aparecia. Aqui o app é o cliente de
/// `GET /admin/vigia` e de `POST /admin/vigia/{conhecer,bloquear}` — as
/// MESMAS actions do chat e do painel /admin.
library;

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:omegadrakon/screens/dashboard_screen.dart';
import 'package:omegadrakon/services/od_api.dart';
import 'package:shared_preferences/shared_preferences.dart';

http.Response _json(Object body, [int status = 200]) => http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );

const _pendente = {
  'n': 1,
  'mac': 'A2:E5:1D:2D:4E:91',
  'ip': '192.168.0.186',
  'fabricante': 'desconhecido',
  'nome': '',
  'conectado': false,
  'ultima_vez': '2026-11-19T15:14:25-03:00',
  'desde': '2026-11-16T18:09:50-03:00',
};

/// Painel do DONO com o Vigia configurável. `pendentes` muda para vazio
/// depois da ação, como o servidor faz ao resolver.
OdApi _apiDono({
  List<Map<String, dynamic>>? pendentes,
  List<String>? posts,
  int statusAcao = 200,
  Map<String, dynamic>? corpoAcao,
}) {
  var chamadasVigia = 0;
  return OdApi(
    baseUrl: 'http://od.test:8000',
    client: MockClient((request) async {
      switch (request.url.path) {
        case '/auth/me':
          return _json({
            'user': {'username': 'alex'},
            'role': 'admin',
            'via': 'teste',
          });
        case '/dashboard/stats':
          return _json({'history': {}});
        case '/admin/users':
          return _json({'users': <Object>[], 'total': 0});
        case '/admin/dev/sessao':
          return _json({'ativo': false, 'caixa_pendente': 0});
        case '/admin/dev/caixa':
          return _json({'mensagens': <Object>[]});
        case '/admin/ideias':
          return _json({'conteudo': ''});
        case '/admin/limitacoes':
          return _json({'entradas': <Object>[]});
        case '/api/radio/musicas':
          return _json({'decisoes': <Object>[]});
        case '/admin/vigia':
          chamadasVigia++;
          final lista = pendentes ?? const [_pendente];
          return _json({
            'ok': true,
            'existe': true,
            'pendentes': chamadasVigia == 1 ? lista : <Object>[],
          });
        case '/admin/vigia/conhecer':
        case '/admin/vigia/bloquear':
          posts?.add('${request.url.path} ${request.body}');
          return _json(corpoAcao ?? {'ok': true, 'mensagem': 'feito'},
              statusAcao);
        default:
          return http.Response('not found', 404);
      }
    }),
  );
}

/// Conta comum: nenhuma rota do Vigia pode ser chamada.
OdApi _apiComum({List<String>? pedidos}) => OdApi(
      baseUrl: 'http://od.test:8000',
      client: MockClient((request) async {
        pedidos?.add(request.url.path);
        switch (request.url.path) {
          case '/auth/me':
            return _json({
              'user': {'username': 'fulano'},
              'role': 'user',
              'via': 'teste',
            });
          case '/dashboard/stats':
            return _json({'history': {}});
          default:
            return http.Response('not found', 404);
        }
      }),
    );

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('Vigia da Rede — REST', () {
    test('listVigiaPendentes lê campos e monta os rótulos', () async {
      final api = _apiDono();
      final lista = await api.listVigiaPendentes();
      expect(lista, hasLength(1));
      final p = lista.single;
      expect(p.mac, 'A2:E5:1D:2D:4E:91');
      expect(p.numero, 1);
      expect(p.conectado, isFalse);
      expect(p.rotulo, contains('192.168.0.186'));
      expect(p.rotulo, isNot(contains('—')), reason: 'sem nome não inventa');
      expect(p.statusLabel, 'fora da rede');
      expect(p.detalhe, contains('pendente desde 16/11'));
    });

    test('conectado/sem informação nunca inventam status', () {
      final agora = OdDispositivoPendente.fromJson({
        ..._pendente,
        'conectado': true,
      });
      expect(agora.statusLabel, 'conectado agora');

      final semInfo = OdDispositivoPendente.fromJson({'mac': 'X'});
      expect(semInfo.conectado, isNull);
      expect(semInfo.statusLabel, 'sem informação de conexão');
      expect(semInfo.detalhe, 'sem informação de conexão');
    });

    test('conhecer manda o MAC e devolve a mensagem do servidor', () async {
      final posts = <String>[];
      final api = _apiDono(posts: posts);
      final mensagem = await api.conhecerDispositivo('A2:E5');
      expect(mensagem, 'feito');
      expect(posts.single, startsWith('/admin/vigia/conhecer'));
      expect(posts.single, contains('"alvo":"A2:E5"'));
    });

    test('403 tem texto de dono; erro do servidor é repassado', () async {
      final negado = OdApi(
        baseUrl: 'http://od.test:8000',
        client: MockClient((_) async => _json({'error': 'acesso_negado'}, 403)),
      );
      expect(
        () => negado.listVigiaPendentes(),
        throwsA(isA<OdApiError>().having(
          (e) => e.message,
          'message',
          'Só o dono vê os dispositivos pendentes da rede.',
        )),
      );

      final falha = _apiDono(
        posts: <String>[],
        statusAcao: 200,
        corpoAcao: {
          'ok': false,
          'error': 'Bloqueio não executado: sem ROUTER_ADMIN_PASSWORD',
        },
      );
      expect(
        () => falha.bloquearDispositivo('A2:E5'),
        throwsA(isA<OdApiError>().having(
          (e) => e.message,
          'message',
          contains('sem ROUTER_ADMIN_PASSWORD'),
        )),
      );
    });
  });

  group('Vigia da Rede — Painel', () {
    testWidgets('card mostra o pendente e Reconhecer chama a action',
        (tester) async {
      // Painel é longo: tela alta para o card do Vigia ficar montado.
      tester.view.physicalSize = const Size(1400, 1600);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);

      final posts = <String>[];
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(body: DashboardScreen(api: _apiDono(posts: posts))),
      ));
      await tester.pumpAndSettle();

      expect(find.textContaining('Vigia da Rede — 1'), findsOneWidget);
      expect(find.textContaining('fora da rede'), findsOneWidget);

      await tester.ensureVisible(find.text('Reconhecer'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Reconhecer'));
      await tester.pumpAndSettle();
      expect(posts.single, startsWith('/admin/vigia/conhecer'));
      // SnackBar de confirmação + o card recarregado sem o pendente.
      expect(find.textContaining('feito'), findsOneWidget);
      expect(find.textContaining('192.168.0.186'), findsNothing);
    });

    testWidgets('Bloquear pede confirmação antes de chamar a action',
        (tester) async {
      // Painel é longo: tela alta para o card do Vigia ficar montado.
      tester.view.physicalSize = const Size(1400, 1600);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);

      final posts = <String>[];
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(body: DashboardScreen(api: _apiDono(posts: posts))),
      ));
      await tester.pumpAndSettle();

      await tester.ensureVisible(find.widgetWithText(TextButton, 'Bloquear'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(TextButton, 'Bloquear'));
      await tester.pumpAndSettle();
      expect(find.text('Bloquear dispositivo?'), findsOneWidget);
      expect(posts, isEmpty, reason: 'cancelar não pode bloquear');

      await tester.tap(find.widgetWithText(FilledButton, 'Bloquear'));
      await tester.pumpAndSettle();
      expect(posts.single, startsWith('/admin/vigia/bloquear'));
      expect(find.textContaining('feito'), findsOneWidget);
    });

    testWidgets('conta comum não chama nenhuma rota do Vigia', (tester) async {
      final pedidos = <String>[];
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(body: DashboardScreen(api: _apiComum(pedidos: pedidos))),
      ));
      await tester.pumpAndSettle();

      expect(pedidos, isNot(contains('/admin/vigia')));
      expect(find.textContaining('Vigia da Rede'), findsNothing);
    });
  });
}
