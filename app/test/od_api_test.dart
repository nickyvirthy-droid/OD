import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:omegadrakon/services/od_api.dart';
import 'package:shared_preferences/shared_preferences.dart';

OdApi apiWith(MockClient client) => OdApi(baseUrl: 'http://od.test:8000', client: client);

http.Response jsonResponse(Object body, {int status = 200}) => http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('OdApi.sendMessage', () {
    test('retorna a resposta do assistente no sucesso', () async {
      final api = apiWith(MockClient((request) async {
        expect(request.url.toString(), 'http://od.test:8000/message');
        expect(request.headers['Content-Type'], 'application/json');
        final body = jsonDecode(request.body);
        expect(body['text'], 'Olá!'); // contrato do servidor
        expect(body['user_id'], 'app');
        expect(body['profile'], 'auto');
        return jsonResponse({'ok': true, 'message': 'Olá, humano!'});
      }));

      final resp = await api.sendMessage('Olá!');
      expect(resp, 'Olá, humano!');
    });

    test('usa o profile informado', () async {
      final api = apiWith(MockClient((request) async {
        final body = jsonDecode(request.body);
        expect(body['profile'], 'nexus');
        return jsonResponse({'response': 'ok'});
      }));
      await api.sendMessage('oi', profile: 'nexus');
    });

    test('inclui X-API-Key apenas quando definida', () async {
      late Map<String, String> seenHeaders;
      final api = apiWith(MockClient((request) async {
        seenHeaders = request.headers;
        return jsonResponse({'response': 'ok'});
      }));

      await api.sendMessage('oi');
      expect(seenHeaders.containsKey('X-API-Key'), isFalse);

      await api.setApiKey('segredo');
      await api.sendMessage('oi');
      expect(seenHeaders['X-API-Key'], 'segredo');
    });

    test('401 lança OdAuthError', () async {
      final api = apiWith(MockClient((_) async => http.Response('', 401)));
      expect(
        () => api.sendMessage('oi'),
        throwsA(isA<OdAuthError>()),
      );
    });

    test('erro 5xx lança OdApiError com statusCode', () async {
      final api = apiWith(MockClient((_) async => http.Response('boom', 500)));
      try {
        await api.sendMessage('oi');
        fail('deveria lançar');
      } on OdApiError catch (e) {
        expect(e.statusCode, 500);
        expect(e.message, contains('500'));
      }
    });

    test('resposta sem campo response usa fallback', () async {
      final api = apiWith(MockClient((_) async => jsonResponse({'message': 'fallback'})));
      expect(await api.sendMessage('oi'), 'fallback');
    });
  });

  group('OdApi.health e capabilities', () {
    test('getHealth decodifica o JSON', () async {
      final api = apiWith(MockClient(
        (_) async => jsonResponse({'ok': true, 'status': 'healthy'}),
      ));
      final health = await api.getHealth();
      expect(health['ok'], isTrue);
      expect(health['status'], 'healthy');
    });

    test('getHealth falha com status != 200', () async {
      final api = apiWith(MockClient((_) async => http.Response('', 503)));
      expect(() => api.getHealth(), throwsA(isA<OdApiError>()));
    });

    test('getActions extrai o catálogo de /actions', () async {
      final api = apiWith(MockClient((request) async {
        expect(request.url.path, '/actions');
        return jsonResponse({
          'ok': true,
          'count': 2,
          'actions': [
            {'name': 'system_info', 'risk': 'low'},
            {'name': 'network_hosts', 'risk': 'medium'},
          ],
        });
      }));
      final actions = await api.getActions();
      expect(actions, hasLength(2));
      expect(actions.first['name'], 'system_info');
    });

    test('executeAction envia action e formata resultado', () async {
      final api = apiWith(MockClient((request) async {
        expect(request.url.path, '/executa');
        final body = jsonDecode(request.body);
        expect(body['action'], 'system_info');
        expect(body['params'], {'verbose': true});
        expect(body.containsKey('confirm'), isFalse);
        return jsonResponse({
          'status': 'ok',
          'data': {'node': 'nicky-server', 'uptime': '2h'},
        });
      }));
      final result = await api.executeAction(
        'system_info',
        params: {'verbose': true},
      );
      expect(result, contains('node: nicky-server'));
      expect(result, contains('uptime: 2h'));
    });

    test('executeAction destrutiva envia confirm=true', () async {
      final api = apiWith(MockClient((request) async {
        final body = jsonDecode(request.body);
        expect(body['action'], 'filesystem_delete');
        expect(body['confirm'], isTrue);
        return jsonResponse({'status': 'ok', 'data': 'removido'});
      }));
      final result = await api.executeAction(
        'filesystem_delete',
        params: {'path': '/tmp/x'},
        confirm: true,
      );
      expect(result, 'removido');
    });

    test('executeAction 422 sem confirm lança erro com mensagem', () async {
      final api = apiWith(MockClient((_) async => jsonResponse(
            {'error': 'confirmacao_obrigatoria: filesystem_delete é destrutiva'},
            status: 422,
          )));
      expect(
        () => api.executeAction('filesystem_delete'),
        throwsA(isA<OdApiError>()),
      );
    });
  });

  group('OdApi.disponibilidade e configuração', () {
    test('isAvailable true quando health ok', () async {
      final api = apiWith(MockClient((_) async => jsonResponse({'ok': true})));
      expect(await api.isAvailable(), isTrue);
    });

    test('isAvailable false em erro ou health não-ok', () async {
      final apiErr = apiWith(MockClient((_) async => http.Response('', 500)));
      expect(await apiErr.isAvailable(), isFalse);

      final apiNotOk = apiWith(MockClient((_) async => jsonResponse({'ok': false})));
      expect(await apiNotOk.isAvailable(), isFalse);
    });

    test('setApiKey persiste e loadSavedApiKey recupera', () async {
      SharedPreferences.setMockInitialValues({});
      final api = apiWith(MockClient((_) async => jsonResponse({'response': 'ok'})));

      expect(await api.loadSavedApiKey(), isFalse);
      await api.setApiKey('chave-salva');
      expect(api.apiKey, 'chave-salva');

      final api2 = apiWith(MockClient((_) async => jsonResponse({'response': 'ok'})));
      expect(await api2.loadSavedApiKey(), isTrue);
      expect(api2.apiKey, 'chave-salva');
    });

    test('setBaseUrl troca a URL usada nas chamadas', () async {
      final api = OdApi(baseUrl: 'http://antiga:8000', client: MockClient((request) async {
        expect(request.url.host, 'nova');
        return jsonResponse({'response': 'ok'});
      }));
      api.setBaseUrl('http://nova:9000');
      await api.sendMessage('oi');
      expect(api.baseUrl, 'http://nova:9000');
    });
  });

  group('OdApi.resiliência de rede', () {
    // Helper: cliente sem espera entre tentativas (testes rápidos).
    OdApi resilientApi(MockClient client, {int maxAttempts = 3}) => OdApi(
          baseUrl: 'http://od.test:8000',
          client: client,
          retryDelay: Duration.zero,
          maxAttempts: maxAttempts,
        );

    test('GET repete em erro transitório e recupera', () async {
      var calls = 0;
      final api = resilientApi(MockClient((_) async {
        calls++;
        if (calls < 3) throw http.ClientException('conexão fechada');
        return jsonResponse({'ok': true});
      }));

      final health = await api.getHealth();
      expect(health['ok'], isTrue);
      expect(calls, 3); // falhou 2x, sucesso na 3ª
    });

    test('GET esgota tentativas e lança OdNetworkError amigável', () async {
      var calls = 0;
      final api = resilientApi(MockClient((_) async {
        calls++;
        throw const SocketException(
          'Connection timed out',
          osError: OSError('Connection timed out', 110),
        );
      }));

      await expectLater(
        api.getHealth(),
        throwsA(isA<OdNetworkError>()),
      );
      expect(calls, 3); // maxAttempts
    });

    test('timeout errno 110 menciona Tailscale na mensagem', () async {
      final api = resilientApi(MockClient((_) async {
        throw const SocketException(
          'Connection timed out (OS Error: Connection timed out, errno = 110)',
        );
      }));

      try {
        await api.getHealth();
        fail('deveria lançar');
      } on OdNetworkError catch (e) {
        expect(e.message, contains('Tailscale'));
        expect(e.message, contains('não respondeu a tempo'));
      }
    });

    test('POST sem conexão estabelecida (refused) repete com segurança', () async {
      var calls = 0;
      final api = resilientApi(MockClient((_) async {
        calls++;
        if (calls < 2) {
          throw const SocketException(
            'Connection refused (OS Error: Connection refused, errno = 111)',
          );
        }
        return jsonResponse({'response': 'ok'});
      }));

      expect(await api.sendMessage('oi'), 'ok');
      expect(calls, 2); // repetiu porque o servidor nem recebeu a 1ª
    });

    test('POST com conexão estabelecida NÃO repete (evita executar 2x)', () async {
      var calls = 0;
      final api = resilientApi(MockClient((_) async {
        calls++;
        throw http.ClientException('conexão fechada no meio do POST');
      }));

      await expectLater(api.sendMessage('oi'), throwsA(isA<OdNetworkError>()));
      expect(calls, 1); // sem retry: não dá para saber se a ação rodou
    });

    test('POST refused sem sucesso esgota tentativas', () async {
      var calls = 0;
      final api = resilientApi(MockClient((_) async {
        calls++;
        throw const SocketException('Connection refused',
            osError: OSError('Connection refused', 111));
      }));

      await expectLater(
        api.sendMessage('oi'),
        throwsA(isA<OdNetworkError>()),
      );
      expect(calls, 3);
    });

    test('resposta HTTP 500 NÃO é retentada (não é rede)', () async {
      var calls = 0;
      final api = resilientApi(MockClient((_) async {
        calls++;
        return http.Response('boom', 500);
      }));

      await expectLater(api.getHealth(), throwsA(isA<OdApiError>()));
      expect(calls, 1);
    });
  });
}