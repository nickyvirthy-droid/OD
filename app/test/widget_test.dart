import 'dart:async';
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
import 'package:omegadrakon/services/od_ws.dart';
import 'package:omegadrakon/widgets/message_bubble.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Canal WebSocket falso: responde o `auth` e chama o roteiro no `message`.
class _ScriptedChannel implements OdWsChannel {
  _ScriptedChannel({this.onMessage});

  final FutureOr<void> Function(_ScriptedChannel channel)? onMessage;
  final List<Map<String, dynamic>> sent = [];
  final _controller = StreamController<String>();

  @override
  Stream<String> get incoming => _controller.stream;

  @override
  void send(String data) {
    final frame = jsonDecode(data) as Map<String, dynamic>;
    sent.add(frame);
    if (frame['type'] == 'auth') {
      _controller.add('{"type":"authenticated"}');
    } else if (frame['type'] == 'message') {
      onMessage?.call(this);
    }
  }

  @override
  Future<void> close() async {
    if (!_controller.isClosed) await _controller.close();
  }

  void emit(Object frame) {
    if (_controller.isClosed) return;
    _controller.add(frame is String ? frame : jsonEncode(frame));
  }

  void fail(Object error) {
    if (_controller.isClosed) return;
    _controller.addError(error);
  }
}

OdWsConnector _connectorFor(_ScriptedChannel channel) =>
    (url, timeout) async => channel;

/// Falha de rede usada nos testes de widget (sem socket real).
class _OfflineException implements Exception {
  const _OfflineException();

  @override
  String toString() => 'SocketException: Connection refused';
}

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
          case '/supervision':
            // Mesma FORMA do GET /supervision (sem loop caído desde o boot).
            return _json({
              'ok': true,
              'status': 'up',
              'window_s': 300.0,
              'degraded': <String>[],
              'restarts': 0,
              'loops': <Object>[],
              'ts': 1789477297.6,
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

/// API fake com um payload controlado de /supervision (a aba Status é
/// best-effort: a supervisão não pode derrubar a tela).
OdApi _apiWithSupervision(Object supervision, {int status = 200}) => OdApi(
      baseUrl: 'http://od.test:8000',
      client: MockClient((request) async {
        switch (request.url.path) {
          case '/health':
            return _json({
              'ok': true,
              'status': 'up',
              'checks': {
                'core': {'ok': true, 'detail': 'ok'},
              },
            });
          case '/capabilities':
            return _json({
              'system': 'Omega Drakon',
              'version': '1.2.0',
              'counts': {'capabilities': 40, 'actions': 57},
              'runtime': {
                'modes': ['api', 'all'],
              },
            });
          case '/supervision':
            return _json(supervision, status: status);
          default:
            return http.Response('not found', 404);
        }
      }),
    );

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('OdApp (smoke)', () {
    testWidgets('sem credencial abre na tela de entrada', (tester) async {
      await tester.pumpWidget(const OdApp());
      await tester.pumpAndSettle();

      // Sem sessão nem API key salvas, o app abre no login.
      expect(find.text('Entrar no OmegaDrakon'), findsOneWidget);
      expect(find.text('Modo avançado (API key)'), findsOneWidget);
    });

    testWidgets('modo avançado leva às Configurações', (tester) async {
      await tester.pumpWidget(const OdApp());
      await tester.pumpAndSettle();

      await tester.tap(find.text('Modo avançado (API key)'));
      await tester.pumpAndSettle();

      expect(find.text('Configurações'), findsOneWidget);
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

    testWidgets('carrega o histórico da conta ao abrir', (tester) async {
      final api = OdApi(
        baseUrl: 'http://od.test:8000',
        apiKey: 'chave-teste',
        client: MockClient((request) async {
          if (request.url.path == '/history/me') {
            return _json({
              'ok': true,
              'user_id': 'alex',
              'messages': [
                {'role': 'user', 'content': 'mensagem antiga do usuário', 'ts': 1789477200.0},
                {'role': 'assistant', 'content': 'resposta antiga do OD', 'ts': 1789477260.0},
              ],
            });
          }
          return http.Response('not found', 404);
        }),
      );
      await tester.pumpWidget(_wrap(ChatScreen(api: api)));
      await tester.pumpAndSettle();

      expect(find.text('mensagem antiga do usuário'), findsOneWidget);
      expect(find.text('resposta antiga do OD'), findsOneWidget);
      // A tela de boas-vindas deu lugar à conversa.
      expect(find.text('Envie uma mensagem para começar'), findsNothing);
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

    // -- Streaming (WebSocket) -------------------------------------------------

    testWidgets('mostra a resposta conforme os tokens chegam (não de uma vez)',
        (tester) async {
      final channel = _ScriptedChannel(
        onMessage: (c) async {
          c.emit({'type': 'processing'});
          c.emit({'type': 'token', 'content': 'Olá'});
          await Future<void>.delayed(const Duration(milliseconds: 300));
          c.emit({'type': 'token', 'content': ', humano'});
          c.emit({'type': 'done', 'content': 'Olá, humano'});
        },
      );
      final api = _mockApi(); // o REST responde 'Resposta do OD' se for chamado
      await tester.pumpWidget(_wrap(ChatScreen(
        api: api,
        chat: OdStreamingChat(api, connector: _connectorFor(channel)),
      )));
      await tester.pumpAndSettle();

      await tester.enterText(find.byType(TextField), 'oi');
      await tester.tap(find.byIcon(Icons.send));
      await tester.pump(); // dispara o envio
      await tester.pump(const Duration(milliseconds: 50));

      // Primeiro token já na tela; o "Digitando..." já saiu.
      expect(find.text('Olá'), findsOneWidget);
      expect(find.text('Digitando...'), findsNothing);
      expect(find.text('Olá, humano'), findsNothing);

      await tester.pump(const Duration(milliseconds: 400));
      await tester.pumpAndSettle();

      expect(find.text('Olá, humano'), findsOneWidget);
      expect(find.text('Streaming ativo'), findsOneWidget);
      // Se o streaming funcionou, o REST não foi usado.
      expect(find.text('Resposta do OD'), findsNothing);
      // E o envio destravou: o botão voltou a ser o de enviar (o spinner só
      // some quando o stream termina de fato — foi o que sumiu primeiro quando
      // o gerador ficava preso no encerramento do canal).
      expect(find.byIcon(Icons.send), findsOneWidget);
      expect(find.byType(CircularProgressIndicator), findsNothing);
    });

    testWidgets('sem WebSocket cai para o POST /message e avisa o transporte',
        (tester) async {
      final api = _mockApi();
      await tester.pumpWidget(_wrap(ChatScreen(
        api: api,
        chat: OdStreamingChat(
          api,
          connector: (_, __) async => throw const _OfflineException(),
        ),
      )));
      await tester.pumpAndSettle();

      await tester.enterText(find.byType(TextField), 'oi');
      await tester.tap(find.byIcon(Icons.send));
      await tester.pumpAndSettle();

      expect(find.text('Resposta do OD'), findsOneWidget);
      expect(find.text('Resposta via REST'), findsOneWidget);
    });

    testWidgets('streaming cortado no meio mantém o texto e avisa na mesma bolha',
        (tester) async {
      final channel = _ScriptedChannel(
        onMessage: (c) {
          c.emit({'type': 'token', 'content': 'começou bem'});
          c.fail(const _OfflineException());
        },
      );
      final api = _mockApi();
      await tester.pumpWidget(_wrap(ChatScreen(
        api: api,
        chat: OdStreamingChat(api, connector: _connectorFor(channel)),
      )));
      await tester.pumpAndSettle();

      await tester.enterText(find.byType(TextField), 'oi');
      await tester.tap(find.byIcon(Icons.send));
      await tester.pumpAndSettle();

      // O texto parcial continua e o aviso fica na MESMA bolha (uma bolha de
      // erro nova pareceria uma segunda resposta).
      expect(find.textContaining('começou bem'), findsOneWidget);
      expect(find.textContaining('interrompida no meio do streaming'), findsOneWidget);
      expect(find.text('Resposta do OD'), findsNothing); // não duplicou pelo REST
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

    testWidgets('mostra a supervisão sem nenhum loop caído', (tester) async {
      await tester.pumpWidget(_wrap(StatusScreen(api: _mockApi())));
      await tester.pumpAndSettle();

      expect(find.text('Supervisão dos loops'), findsOneWidget);
      expect(find.text('Todos de pé'), findsOneWidget);
      expect(find.text('Nenhum loop reiniciado desde o boot'), findsOneWidget);
    });

    testWidgets('mostra o loop caído quando a supervisão está degradada',
        (tester) async {
      // Payload real do GET /supervision com um loop reiniciado.
      final api = _apiWithSupervision({
        'ok': false,
        'status': 'degraded',
        'window_s': 300.0,
        'degraded': ['telegram'],
        'restarts': 1,
        'loops': [
          {
            'name': 'telegram',
            'failures': 1,
            'restarts': 1,
            'last_kind': 'TimeoutError',
            'last_error': 'The read operation timed out',
            'age_s': 12.0,
            'degraded': true,
            'crash_loop': false,
          }
        ],
      });

      await tester.pumpWidget(_wrap(StatusScreen(api: api)));
      await tester.pumpAndSettle();

      expect(find.text('Supervisão dos loops'), findsOneWidget);
      expect(find.text('1 reiniciado(s)'), findsOneWidget);
      expect(find.widgetWithText(ListTile, 'telegram'), findsOneWidget);
      expect(
        find.textContaining('TimeoutError'),
        findsOneWidget,
      );
    });

    // Regressão de FORMA, no mesmo espírito do teste do manifesto acima: usa o
    // payload REAL de GET /supervision capturado em 2026-09-15 (od-core
    // v1.2.0+6). Mock com payload inventado passa mesmo se o servidor mudar o
    // contrato — foi assim que o bug do `system` aninhado escapou até o APK.
    testWidgets('renderiza os payloads REAIS de /supervision (up e degradado)',
        (tester) async {
      final payloads = jsonDecode(
        File('test/fixtures/supervision_payloads.json').readAsStringSync(),
      ) as Map<String, dynamic>;

      await tester.pumpWidget(_wrap(
        StatusScreen(api: _apiWithSupervision(payloads['up'] as Object)),
      ));
      await tester.pumpAndSettle();
      expect(find.text('Supervisão dos loops'), findsOneWidget);
      expect(find.text('Nenhum loop reiniciado desde o boot'), findsOneWidget);

      // Pump de um widget vazio no meio: sem isso o Flutter reaproveita o State
      // (mesmo tipo, sem key) e o `initState` não roda de novo — a segunda
      // renderização ficaria com o payload 'up'.
      await tester.pumpWidget(const SizedBox());
      await tester.pumpAndSettle();

      await tester.pumpWidget(_wrap(
        StatusScreen(api: _apiWithSupervision(payloads['degraded'] as Object)),
      ));
      await tester.pumpAndSettle();
      expect(find.text('1 reiniciado(s)'), findsOneWidget);
      expect(find.widgetWithText(ListTile, 'telegram'), findsOneWidget);
      expect(
        find.text('1 reinício(s) • último: TimeoutError • há 0s'),
        findsOneWidget,
      );
    });

    testWidgets('supervisão indisponível não derruba a aba Status',
        (tester) async {
      // Servidor antigo (sem a rota): o resto da tela tem que continuar.
      final api = _apiWithSupervision({'ok': false}, status: 404);

      await tester.pumpWidget(_wrap(StatusScreen(api: api)));
      await tester.pumpAndSettle();

      expect(find.text('OmegaDrakon Online'), findsOneWidget);
      expect(find.text('1.2.0'), findsOneWidget);
      expect(
        find.textContaining('Supervisão dos loops indisponível'),
        findsOneWidget,
      );
    });
  });

  group('SettingsScreen', () {
    testWidgets('URLs ficam ocultas por padrão (só no Avançado com switch)',
        (tester) async {
      await tester.pumpWidget(_wrap(SettingsScreen(
        api: _mockApi(),
        onSaved: () {},
      )));

      // A conexão é automática — nada de campo de URL à vista.
      expect(find.text('URL local (Tailscale)'), findsNothing);
      expect(find.text('URL externa (Funnel)'), findsNothing);
      expect(
        find.textContaining('conexão é automática'),
        findsOneWidget,
      );

      // Dentro do Avançado, as URLs só aparecem após o switch.
      await tester.scrollUntilVisible(
        find.text('Avançado'),
        200,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.tap(find.text('Avançado'));
      await tester.pumpAndSettle();
      expect(find.text('URL local (Tailscale)'), findsNothing);
      await tester.tap(find.text('Mostrar URLs'));
      await tester.pumpAndSettle();
      expect(find.text('URL local (Tailscale)'), findsOneWidget);
      expect(find.text('URL externa (Funnel)'), findsOneWidget);
    });

    testWidgets('valida URL vazia ao salvar (Avançado)', (tester) async {
      await tester.pumpWidget(_wrap(SettingsScreen(
        api: _mockApi(),
        onSaved: () {},
      )));

      await tester.scrollUntilVisible(
        find.text('Avançado'),
        200,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.tap(find.text('Avançado'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Mostrar URLs'));
      await tester.pumpAndSettle();

      // Campo de URL já vem preenchido com a baseUrl — esvazia para validar.
      await tester.enterText(
        find.widgetWithText(TextField, 'URL local (Tailscale)'),
        '',
      );
      // O teclado virtual empurra o botão para fora da tela: rolar até ele
      // e fechar o teclado (o foco no campo mantém o inset ativo).
      await tester.scrollUntilVisible(
        find.text('Salvar avançado'),
        -80,
        scrollable: find.byType(Scrollable).first,
      );
      FocusManager.instance.primaryFocus?.unfocus();
      await tester.pumpAndSettle();
      await tester.tap(find.text('Salvar avançado'));
      await tester.pumpAndSettle();

      expect(
        find.text('URL do servidor é obrigatória'),
        findsOneWidget,
      );
    });

    testWidgets('salvar avançado aplica URL e API key na instância',
        (tester) async {
      final api = _mockApi();
      var saved = false;
      await tester.pumpWidget(_wrap(SettingsScreen(
        api: api,
        onSaved: () => saved = true,
      )));

      await tester.scrollUntilVisible(
        find.text('Avançado'),
        200,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.tap(find.text('Avançado'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.widgetWithText(TextField, 'API Key (chave do servidor)'),
        'chave-nova',
      );
      await tester.tap(find.text('Mostrar URLs'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.widgetWithText(TextField, 'URL local (Tailscale)'),
        'http://nova.od:9000',
      );
      // O teclado virtual empurra o botão para fora da tela: rolar até ele
      // e fechar o teclado (o foco no campo mantém o inset ativo).
      await tester.scrollUntilVisible(
        find.text('Salvar avançado'),
        -80,
        scrollable: find.byType(Scrollable).first,
      );
      FocusManager.instance.primaryFocus?.unfocus();
      await tester.pumpAndSettle();
      await tester.tap(find.text('Salvar avançado'));
      await tester.pumpAndSettle();

      expect(saved, isTrue);
      expect(api.baseUrl, 'http://nova.od:9000');
      expect(api.apiKey, 'chave-nova');
      expect(find.text('Configurações salvas!'), findsOneWidget);
    });

    testWidgets('seção Conta: login com as credenciais do site',
        (tester) async {
      OdApi? capturada;
      final api = OdApi(
        baseUrl: 'http://od.test:8000',
        client: MockClient((request) async {
          expect(request.url.path, '/auth/login');
          final body = jsonDecode(request.body);
          expect(body['username'], 'alex');
          expect(body['password'], 'senha123');
          return _json({
            'ok': true,
            'token': 'tok-site',
            'user': {'username': 'alex'},
          });
        }),
      );
      capturada = api;

      await tester.pumpWidget(_wrap(SettingsScreen(
        api: capturada,
        onSaved: () {},
      )));

      // Sem sessão, a seção mostra nome + senha (as mesmas do site).
      expect(
        find.textContaining('MESMO nome e senha'),
        findsOneWidget,
      );
      expect(find.text('Nome de usuário'), findsOneWidget);
      await tester.enterText(
        find.widgetWithText(TextField, 'Nome de usuário'),
        'alex',
      );
      await tester.enterText(
        find.widgetWithText(TextField, 'Senha'),
        'senha123',
      );
      await tester.tap(find.text('Entrar'));
      await tester.pumpAndSettle();

      expect(find.text('Conectado como alex'), findsOneWidget);
      expect(capturada.token, 'tok-site');
    });

    testWidgets('seção Conta: logado mostra o usuário e o Sair',
        (tester) async {
      final api = OdApi(
        baseUrl: 'http://od.test:8000',
        token: 'tok-ativo',
        username: 'alex',
        client: MockClient((request) async {
          expect(request.url.path, '/auth/logout');
          return _json({'ok': true});
        }),
      );
      await tester.pumpWidget(_wrap(SettingsScreen(
        api: api,
        onSaved: () {},
      )));

      expect(find.text('alex'), findsOneWidget);
      expect(find.text('Sair da conta'), findsOneWidget);
      expect(find.text('Nome de usuário'), findsNothing);

      await tester.tap(find.text('Sair da conta'));
      await tester.pumpAndSettle();
      expect(api.token, isEmpty);
      expect(find.text('Sessão encerrada.'), findsOneWidget);
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
      // Assistente sem answeredBy exibe o selo 🐉 OD
      expect(find.text('🐉 OD'), findsOneWidget);
    });

    testWidgets('bolha mostra QUEM respondeu (nome canônico) e a hora',
        (tester) async {
      final ts = DateTime(2026, 9, 26, 12, 5); // 12:05
      await tester.pumpWidget(_wrap(MessageBubble(
        message: OdMessage(
          role: 'assistant',
          content: 'a resposta técnica',
          timestamp: ts,
          answeredBy: 'Regulus — O Conselheiro',
          route: 'llm',
        ),
      )));

      expect(find.text('Regulus — O Conselheiro'), findsOneWidget);
      expect(find.text('12:05'), findsOneWidget);
      expect(find.text('🐉 OD'), findsNothing);
    });

    testWidgets('resposta do cache exibe o rótulo cache e a hora',
        (tester) async {
      final ts = DateTime(2026, 9, 26, 9, 7);
      await tester.pumpWidget(_wrap(MessageBubble(
        message: OdMessage(
          role: 'assistant',
          content: 'resposta repetida',
          timestamp: ts,
          answeredBy: 'cache',
          route: 'cache',
        ),
      )));

      expect(find.text('cache'), findsOneWidget);
      expect(find.text('09:07'), findsOneWidget);
    });

    testWidgets('bolha do usuário mostra a hora (sem cabeçalho de entidade)',
        (tester) async {
      final ts = DateTime(2026, 9, 26, 23, 59);
      await tester.pumpWidget(_wrap(MessageBubble(
        message: OdMessage(role: 'user', content: 'oi', timestamp: ts),
      )));

      expect(find.text('23:59'), findsOneWidget);
      expect(find.text('🐉 OD'), findsNothing);
    });
  });
}
