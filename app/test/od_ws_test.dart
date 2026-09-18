import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:omegadrakon/services/od_api.dart';
import 'package:omegadrakon/services/od_ws.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Canal falso guiado pelo ROTEIRO: ele responde conforme o cliente envia
/// (`auth` → handshake, `message` → o roteiro decide os frames).
///
/// É o que dá determinismo: o teste consegue soltar token a token, falhar no
/// meio do stream ou responder erro de autenticação sem corrida com timers.
class ScriptedChannel implements OdWsChannel {
  ScriptedChannel({
    this.authReply = '{"type":"authenticated"}',
    this.onMessage,
  });

  /// Frame devolvido ao `auth` (por padrão, autenticado).
  final String authReply;

  /// Chamado quando o cliente manda `message` — o roteiro do teste.
  final void Function(ScriptedChannel channel)? onMessage;

  final List<Map<String, dynamic>> sent = [];
  final _controller = StreamController<String>();
  bool closed = false;

  @override
  Stream<String> get incoming => _controller.stream;

  @override
  void send(String data) {
    final frame = jsonDecode(data) as Map<String, dynamic>;
    sent.add(frame);
    switch (frame['type']) {
      case 'auth':
        _controller.add(authReply);
      case 'message':
        onMessage?.call(this);
    }
  }

  @override
  Future<void> close() async {
    closed = true;
    if (!_controller.isClosed) await _controller.close();
  }

  /// Solta um frame (Map é serializado; String passa direto).
  void emit(Object frame) {
    if (_controller.isClosed) return;
    _controller.add(frame is String ? frame : jsonEncode(frame));
  }

  /// Mata o canal (rede caiu, servidor fechou).
  void fail(Object error) {
    if (_controller.isClosed) return;
    _controller.addError(error);
  }
}

/// Conector falso: conta as tentativas e devolve o canal da vez.
class FakeConnector {
  FakeConnector(this.open);

  final FutureOr<OdWsChannel> Function(int call) open;
  final List<Uri> urls = [];
  int calls = 0;

  Future<OdWsChannel> connect(Uri url, Duration timeout) async {
    calls++;
    urls.add(url);
    return await open(calls);
  }
}

OdApi apiWith(MockClient client, {String key = 'chave'}) => OdApi(
      baseUrl: 'http://od.test:8000',
      client: client,
      retryDelay: Duration.zero,
    );

http.Response jsonResponse(Object body, {int status = 200}) => http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );

/// Fallback REST padrão.
MockClient restOk([String response = 'Resposta via REST']) => MockClient(
      (request) async => jsonResponse({'ok': true, 'message': response}),
    );

/// Roteiro comum: `processing`, dois tokens e `done`.
void doisTokens(ScriptedChannel channel) {
  channel.emit({'type': 'processing'});
  channel.emit({'type': 'token', 'content': 'Olá'});
  channel.emit({'type': 'token', 'content': ', humano'});
  channel.emit({
    'type': 'done',
    'content': 'Olá, humano',
    'route': 'llm',
    'llm_used': 'gemma-local',
  });
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('OdStreamingChat — derivação da URL', () {
    test('http porta 8000 vira ws porta 8001', () {
      final chat = OdStreamingChat(OdApi(baseUrl: 'http://100.77.67.53:8000'));
      expect(chat.wsUri.toString(), 'ws://100.77.67.53:8001');
    });

    test('https vira wss', () {
      final chat = OdStreamingChat(OdApi(baseUrl: 'https://od.exemplo:9000'));
      expect(chat.wsUri.scheme, 'wss');
      expect(chat.wsUri.host, 'od.exemplo');
      expect(chat.wsUri.port, 8001);
    });

    test('porta do streaming é configurável (OD_WS_PORT fora do padrão)', () {
      final chat = OdStreamingChat(
        OdApi(baseUrl: 'http://od.test:8000'),
        wsPort: 9100,
      );
      expect(chat.wsUri.port, 9100);
    });
  });

  group('OdStreamingChat — streaming pelo WebSocket', () {
    test('autentica, envia a mensagem e monta a resposta token-a-token',
        () async {
      final channel = ScriptedChannel(onMessage: doisTokens);
      final connector = FakeConnector((_) => channel);
      final api = apiWith(
        MockClient((_) async => fail('não deveria usar o REST')),
      );
      await api.setApiKey('minha-chave');

      final chat = OdStreamingChat(api, connector: connector.connect);
      final deltas = await chat.send('oi', profile: 'guardian').toList();

      // Protocolo: auth com a chave, depois message com texto e perfil.
      final auth = channel.sent[0];
      expect(auth['type'], 'auth');
      expect(auth['api_key'], 'minha-chave');
      expect(auth['user_id'], 'app');

      final message = channel.sent[1];
      expect(message['type'], 'message');
      expect(message['text'], 'oi');
      expect(message['profile'], 'guardian');

      expect(deltas.map((d) => d.text).toList(), ['Olá', ', humano', '']);
      expect(
        deltas.every((d) => d.transport == OdChatTransport.webSocket),
        isTrue,
      );
      expect(deltas.last.done, isTrue);
      expect(deltas.map((d) => d.text).join(), 'Olá, humano');
      expect(channel.closed, isTrue); // socket fechado no fim
      expect(connector.calls, 1);
      expect(connector.urls.single.toString(), 'ws://od.test:8001');
    });

    test('ignora frames desconhecidos (o protocolo pode evoluir)', () async {
      final channel = ScriptedChannel(
        onMessage: (c) {
          c.emit({'type': 'algum_frame_novo', 'x': 1});
          c.emit({'type': 'token', 'content': 'ok'});
          c.emit({'type': 'done', 'content': 'ok'});
        },
      );
      final chat = OdStreamingChat(
        apiWith(restOk()),
        connector: FakeConnector((_) => channel).connect,
      );

      final deltas = await chat.send('oi').toList();
      expect(deltas.first.text, 'ok');
      expect(deltas.last.done, isTrue);
    });

    test('token vazio não vira delta; done sem token não inventa texto',
        () async {
      final channel = ScriptedChannel(
        onMessage: (c) {
          c.emit({'type': 'token', 'content': ''});
          c.emit({'type': 'done', 'content': '', 'route': 'cache'});
        },
      );
      final chat = OdStreamingChat(
        apiWith(restOk()),
        connector: FakeConnector((_) => channel).connect,
      );

      final deltas = await chat.send('oi').toList();
      expect(deltas, hasLength(1));
      expect(deltas.single.text, '');
      expect(deltas.single.done, isTrue);
    });
  });

  group('OdStreamingChat — fallback para POST /message', () {
    test('WebSocket inacessível cai para o REST com um único delta', () async {
      final connector = FakeConnector((_) => throw const SocketExceptionStub());
      final api = apiWith(restOk('Resposta inteira do REST'));
      await api.setApiKey('chave');

      final chat = OdStreamingChat(api, connector: connector.connect);
      final deltas = await chat.send('oi').toList();

      expect(deltas, hasLength(1));
      expect(deltas.single.text, 'Resposta inteira do REST');
      expect(deltas.single.transport, OdChatTransport.rest);
      expect(deltas.single.done, isTrue);
      expect(connector.calls, 1);
    });

    test('chave recusada pelo streaming cai para o REST', () async {
      final channel = ScriptedChannel(
        authReply: '{"type":"error","message":"api_key_invalida"}',
      );
      final api = apiWith(restOk('Resposta via REST'));

      final chat = OdStreamingChat(
        api,
        connector: FakeConnector((_) => channel).connect,
      );
      final deltas = await chat.send('oi').toList();

      expect(deltas.single.transport, OdChatTransport.rest);
      expect(deltas.single.text, 'Resposta via REST');
      expect(channel.closed, isTrue); // não deixa socket pendurado
    });

    test('servidor que fecha no handshake cai para o REST', () async {
      final channel = ScriptedChannel();
      channel.fail(const SocketExceptionStub());
      final api = apiWith(restOk('via REST'));

      final chat = OdStreamingChat(
        api,
        connector: FakeConnector((_) => channel).connect,
      );

      expect((await chat.send('oi').toList()).single.text, 'via REST');
    });
  });

  group('OdStreamingChat — interrupção e cooldown', () {
    test('queda DEPOIS de já ter texto NÃO cai para o REST (evita duplicar)',
        () async {
      final channel = ScriptedChannel(
        onMessage: (c) {
          c.emit({'type': 'token', 'content': 'metade'});
          c.fail(const SocketExceptionStub());
        },
      );
      var restCalls = 0;
      final api = apiWith(MockClient((_) async {
        restCalls++;
        return jsonResponse({'ok': true, 'message': 'não deveria chegar aqui'});
      }));

      final chat = OdStreamingChat(
        api,
        connector: FakeConnector((_) => channel).connect,
      );

      final recebidos = <OdChatDelta>[];
      Object? erro;
      try {
        await for (final delta in chat.send('oi')) {
          recebidos.add(delta);
        }
      } catch (e) {
        erro = e;
      }

      expect(erro, isA<OdStreamingError>());
      expect(recebidos.map((d) => d.text).join(), 'metade');
      expect(restCalls, 0); // NÃO repetiu a mensagem pelo REST
    });

    test('erro do servidor no meio do stream vira interrupção (sem fallback)',
        () async {
      final channel = ScriptedChannel(
        onMessage: (c) {
          c.emit({'type': 'token', 'content': 'começando'});
          c.emit({
            'type': 'error',
            'message': 'erro_processamento: RuntimeError',
          });
        },
      );
      final chat = OdStreamingChat(
        apiWith(restOk()),
        connector: FakeConnector((_) => channel).connect,
      );

      await expectLater(
        chat.send('oi').toList(),
        throwsA(isA<OdStreamingError>()),
      );
    });

    test('encerramento do canal NÃO segura a resposta (close que pendura)',
        () async {
      // O outro lado pode ter morrido no meio: o close handshake (e o cancel
      // da assinatura) pode nunca completar. Esperar por isso travaria a tela
      // com a resposta já pronta — foi o bug que o teste de widget pegou.
      final channel = _NeverClosingChannel(onMessage: doisTokens);
      final chat = OdStreamingChat(
        apiWith(restOk()),
        connector: FakeConnector((_) => channel).connect,
      );

      final deltas = await chat.send('oi').toList().timeout(
            const Duration(seconds: 5),
            onTimeout: () => fail('o chat ficou preso no encerramento do canal'),
          );

      expect(deltas.map((d) => d.text).join(), 'Olá, humano');
      expect(deltas.last.done, isTrue);
      expect(channel.closed, isTrue); // tentou fechar (best-effort)
    });

    test('cooldown: falhou uma vez, as próximas vão direto ao REST', () async {
      final connector = FakeConnector((_) => throw const SocketExceptionStub());
      final api = apiWith(restOk('via REST'));
      await api.setApiKey('chave');

      final chat = OdStreamingChat(api, connector: connector.connect);

      expect(await chat.send('primeira').toList(), hasLength(1));
      expect(connector.calls, 1);

      final segunda = await chat.send('segunda').toList();

      expect(segunda.single.transport, OdChatTransport.rest);
      expect(connector.calls, 1); // NÃO tentou o WebSocket de novo
      expect(chat.streamingPreferred, isFalse);
    });

    test('cooldown curto: passado o prazo o WebSocket volta a ser tentado',
        () async {
      final channel = ScriptedChannel(onMessage: doisTokens);
      final connector = FakeConnector((_) => channel);
      final api = apiWith(restOk('via REST'));

      final chat = OdStreamingChat(
        api,
        connector: connector.connect,
        cooldown: Duration.zero,
      );
      await chat.send('primeira').toList();
      expect(connector.calls, 1);

      await chat.send('segunda').toList();
      await chat.send('terceira').toList();
      expect(connector.calls, 3); // sem cooldown, cada mensagem abre um canal
      expect(chat.streamingPreferred, isTrue);
    });

    test('REST com 401 propaga OdAuthError', () async {
      final connector = FakeConnector((_) => throw const SocketExceptionStub());
      final api = apiWith(MockClient((_) async => http.Response('', 401)));
      await api.setApiKey('chave-errada');

      final chat = OdStreamingChat(api, connector: connector.connect);

      await expectLater(chat.send('oi').toList(), throwsA(isA<OdAuthError>()));
    });
  });
}

/// Canal que nunca completa o `close()` (simula socket meio-aberto).
class _NeverClosingChannel extends ScriptedChannel {
  _NeverClosingChannel({super.onMessage});

  @override
  Future<void> close() {
    closed = true;
    return Completer<void>().future; // nunca completa
  }
}

/// Exceção de rede usada pelos testes (não depende de socket real).
class SocketExceptionStub implements Exception {
  const SocketExceptionStub();

  @override
  String toString() => 'SocketException: Connection refused';
}
