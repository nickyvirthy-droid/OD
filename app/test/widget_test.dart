import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:omegadrakon/main.dart';
import 'package:omegadrakon/models/message.dart';
import 'package:omegadrakon/screens/actions_screen.dart';
import 'package:omegadrakon/screens/chat_screen.dart';
import 'package:omegadrakon/screens/settings_screen.dart';
import 'package:omegadrakon/screens/status_screen.dart';
import 'package:omegadrakon/services/od_api.dart';
import 'package:omegadrakon/widgets/message_bubble.dart';
import 'package:shared_preferences/shared_preferences.dart';

http.Response _json(Object body, {int status = 200}) => http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );

/// API fake respondendo as rotas usadas pelas telas.
OdApi _mockApi() => OdApi(
      baseUrl: 'http://od.test:8000',
      client: MockClient((request) async {
        switch (request.url.path) {
          case '/message':
            return _json({'response': 'Resposta do OD'});
          case '/health':
            return _json({
              'ok': true,
              'status': 'healthy',
              'checks': {
                'core': {'ok': true, 'detail': 'ok'},
                'memory': {'ok': true, 'detail': 'ok'},
              },
            });
          case '/actions':
            return _json({
              'ok': true,
              'count': 2,
              'actions': [
                {
                  'name': 'system_info',
                  'description': 'Informações do sistema',
                  'category': 'system',
                  'permission': 'system_info',
                  'risk': 'low',
                  'params': {
                    'required': ['verbose'],
                    'properties': {
                      'verbose': {'type': 'bool'},
                    },
                  },
                },
                {
                  'name': 'ping',
                  'description': 'Ping em um host',
                  'category': 'network',
                  'risk': 'medium',
                  'params': {},
                },
              ],
            });
          case '/capabilities':
            // Mesma FORMA do manifesto real do servidor (plano, com `system`
            // sendo o nome em string e as contagens em `counts`). O mock antigo
            // usava um `system` aninhado que o servidor nunca devolveu — o
            // StatusScreen passava no teste e quebrava no celular.
            return _json({
              'system': 'Omega Drakon',
              'version': '1.2.0',
              'counts': {'capabilities': 40, 'actions': 57},
              'runtime': {
                'modes': ['api', 'all'],
              },
            });
          default:
            return http.Response('not found', 404);
        }
      }),
    );

Widget _wrap(Widget child) => MaterialApp(home: Scaffold(body: child));

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('OdApp (smoke)', () {
    testWidgets('sem chave salva abre na Config e navega para o Chat',
        (tester) async {
      await tester.pumpWidget(const OdApp());
      await tester.pumpAndSettle();

      // Sem API key salva, cai direto nas configurações
      expect(find.text('Configurações'), findsOneWidget);

      await tester.tap(find.text('Chat'));
      await tester.pumpAndSettle();
      expect(find.text('Envie uma mensagem para começar'), findsOneWidget);
      expect(find.byType(NavigationBar), findsOneWidget);
    });
  });

  group('ChatScreen', () {
    testWidgets('envia mensagem e mostra a resposta', (tester) async {
      final api = _mockApi();
      await tester.pumpWidget(_wrap(ChatScreen(api: api)));
      await tester.pumpAndSettle();

      // Seletor de perfil — primeiro e último dos 8 perfis (lista horizontal é lazy)
      expect(find.textContaining('Auto'), findsOneWidget);
      await tester.scrollUntilVisible(
        find.text('🔗 Nexus'),
        100,
        scrollable: find.byType(Scrollable).first,
      );
      expect(find.textContaining('Nexus'), findsOneWidget);
      // Volta para o início para o envio
      await tester.scrollUntilVisible(
        find.textContaining('Auto'),
        -100,
        scrollable: find.byType(Scrollable).first,
      );

      await tester.enterText(find.byType(TextField), 'Olá OD');
      await tester.tap(find.byIcon(Icons.send));
      await tester.pumpAndSettle();

      expect(find.text('Olá OD'), findsOneWidget);
      expect(find.text('Resposta do OD'), findsOneWidget);
    });

    testWidgets('mostra erro quando a API falha', (tester) async {
      final api = OdApi(
        baseUrl: 'http://od.test:8000',
        client: MockClient((_) async => http.Response('', 500)),
      );
      await tester.pumpWidget(_wrap(ChatScreen(api: api)));
      await tester.pumpAndSettle();

      await tester.enterText(find.byType(TextField), 'oi');
      await tester.tap(find.byIcon(Icons.send));
      await tester.pumpAndSettle();

      expect(find.textContaining('⚠️ Erro'), findsOneWidget);
    });
  });

  group('ActionsScreen', () {
    testWidgets('lista as ações e filtra pela busca', (tester) async {
      await tester.pumpWidget(_wrap(ActionsScreen(api: _mockApi())));
      await tester.pumpAndSettle();

      expect(find.widgetWithText(ListTile, 'system_info'), findsOneWidget);
      expect(find.widgetWithText(ListTile, 'ping'), findsOneWidget);
      expect(find.text('2 ações'), findsOneWidget);

      await tester.enterText(find.byType(TextField), 'system');
      await tester.pumpAndSettle();
      expect(find.widgetWithText(ListTile, 'system_info'), findsOneWidget);
      expect(find.widgetWithText(ListTile, 'ping'), findsNothing);
      expect(find.text('1 ações'), findsOneWidget);
    });
  });

  group('StatusScreen', () {
    testWidgets('mostra health e capabilities', (tester) async {
      await tester.pumpWidget(_wrap(StatusScreen(api: _mockApi())));
      await tester.pumpAndSettle();

      expect(find.text('OmegaDrakon Online'), findsOneWidget);
      expect(find.text('Checks (2)'), findsOneWidget);
      expect(find.text('1.2.0'), findsOneWidget);
      expect(find.text('2 modos'), findsOneWidget);
      expect(find.text('40'), findsOneWidget);
      expect(find.text('57'), findsOneWidget);
    });

    // Regressão do bug encontrado no APK 1.2.0: com o manifesto REAL (gerado
    // em 2026-09-12 a partir do servidor em produção) a tela quebrava com
    // `type 'String' is not a subtype of type 'Map<String, dynamic>?'` porque
    // `system` é o nome do sistema, não um objeto.
    testWidgets('renderiza a seção Sistema com o manifesto REAL do servidor',
        (tester) async {
      final caps = jsonDecode(
        File('test/fixtures/capabilities_manifest.json').readAsStringSync(),
      ) as Map<String, dynamic>;

      final api = OdApi(
        baseUrl: 'http://od.test:8000',
        client: MockClient((request) async {
          if (request.url.path == '/health') {
            return _json({
              'ok': true,
              'status': 'up',
              'checks': {},
            });
          }
          return _json(caps);
        }),
      );

      await tester.pumpWidget(_wrap(StatusScreen(api: api)));
      await tester.pumpAndSettle();

      final counts = caps['counts'] as Map<String, dynamic>;
      final modes = (caps['runtime'] as Map<String, dynamic>)['modes'] as List;
      expect(find.text('${caps['version']}'), findsOneWidget);
      expect(find.text('${modes.length} modos'), findsOneWidget);
      expect(find.text('${counts['capabilities']}'), findsOneWidget);
      expect(find.text('${counts['actions']}'), findsOneWidget);
    });
  });

  group('SettingsScreen', () {
    testWidgets('valida URL vazia ao salvar', (tester) async {
      await tester.pumpWidget(_wrap(SettingsScreen(
        api: _mockApi(),
        onSaved: () {},
      )));

      // Campo de URL já vem preenchido com a baseUrl — esvazia para validar
      await tester.enterText(find.byType(TextField).first, '');
      await tester.tap(find.text('Salvar'));
      await tester.pumpAndSettle();

      expect(
        find.text('URL do servidor é obrigatória'),
        findsOneWidget,
      );
    });

    testWidgets('salvar aplica URL e API key na instância', (tester) async {
      final api = _mockApi();
      var saved = false;
      await tester.pumpWidget(_wrap(SettingsScreen(
        api: api,
        onSaved: () => saved = true,
      )));

      await tester.enterText(
        find.byType(TextField).first,
        'http://nova.od:9000',
      );
      await tester.enterText(find.byType(TextField).last, 'chave-nova');
      await tester.tap(find.text('Salvar'));
      await tester.pumpAndSettle();

      expect(saved, isTrue);
      expect(api.baseUrl, 'http://nova.od:9000');
      expect(api.apiKey, 'chave-nova');
      expect(find.text('Configurações salvas!'), findsOneWidget);
    });
  });

  group('MessageBubble', () {
    testWidgets('renderiza mensagem do usuário e do assistente',
        (tester) async {
      await tester.pumpWidget(_wrap(Column(
        children: [
          MessageBubble(message: OdMessage(role: 'user', content: 'minha msg')),
          MessageBubble(
            message: OdMessage(role: 'assistant', content: 'resposta'),
          ),
        ],
      )));

      expect(find.text('minha msg'), findsOneWidget);
      expect(find.text('resposta'), findsOneWidget);
      // Assistente exibe o selo 🐉 OD
      expect(find.text('🐉 OD'), findsOneWidget);
    });
  });
}
