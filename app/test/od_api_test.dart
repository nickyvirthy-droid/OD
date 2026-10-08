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

  group('OdApi.login/registro (sessão de conta)', () {
    test('login guarda o token e passa a mandar Bearer', () async {
      final api = apiWith(MockClient((request) async {
        if (request.url.path == '/auth/login') {
          final body = jsonDecode(request.body);
          expect(body['username'], 'alex');
          expect(body['password'], 'senha123');
          return jsonResponse({
            'ok': true,
            'token': 'tok-123',
            'user': {'username': 'alex'},
          });
        }
        // Depois do login, o /message leva o Bearer (e não a API key).
        expect(request.headers['Authorization'], 'Bearer tok-123');
        expect(request.headers.containsKey('X-API-Key'), isFalse);
        return jsonResponse({'ok': true, 'message': 'oi'});
      }));

      expect(await api.login('alex', 'senha123'), isTrue);
      expect(api.token, 'tok-123');
      expect(api.username, 'alex');
      expect(await api.sendMessage('oi'), 'oi');
    });

    test('login com erro lança OdApiError com a mensagem do servidor',
        () async {
      final api = apiWith(MockClient((_) async => jsonResponse(
            {'ok': false, 'error': 'Usuário ou senha inválidos'},
            status: 401,
          )));
      expect(
        () => api.login('alex', 'errada'),
        throwsA(isA<OdApiError>()
            .having((e) => e.message, 'message', contains('inválidos'))),
      );
    });

    test('getHistory lista as mensagens da conta com Bearer', () async {
      final api = apiWith(MockClient((request) async {
        if (request.url.path == '/auth/login') {
          return jsonResponse({
            'ok': true,
            'token': 'tok-h',
            'user': {'username': 'alex'},
          });
        }
        expect(request.url.path, '/history/me');
        expect(request.url.queryParameters['limit'], '50');
        expect(request.headers['Authorization'], 'Bearer tok-h');
        return jsonResponse({
          'ok': true,
          'user_id': 'alex',
          'messages': [
            {
              'role': 'user',
              'content': 'pergunta antiga',
              'ts': 1789477200.0,
              'llm_used': '',
            },
            {
              'role': 'assistant',
              'content': 'resposta antiga',
              'ts': 1789477260.5,
              'llm_used': 'gemma-local',
            },
          ],
        });
      }));

      await api.login('alex', 'senha123');
      final msgs = await api.getHistory();
      expect(msgs.length, 2);
      expect(msgs[0].isUser, isTrue);
      expect(msgs[0].content, 'pergunta antiga');
      expect(msgs[1].isUser, isFalse);
      expect(msgs[1].content, 'resposta antiga');
      expect(msgs[1].timestamp.isAfter(msgs[0].timestamp), isTrue);
    });

    test('getHistory sem credencial não chama o servidor', () async {
      final api = apiWith(
        MockClient((_) async => fail('não deveria chamar a API')),
      );
      expect(await api.getHistory(), isEmpty);
    });

    test('getHistory best-effort: erro HTTP devolve lista vazia', () async {
      final api = OdApi(
        baseUrl: 'http://od.test:8000',
        apiKey: 'chave',
        client: MockClient((_) async => http.Response('', 501)),
      );
      expect(await api.getHistory(), isEmpty);
    });

    test('registro chama /auth/register', () async {
      final api = apiWith(MockClient((request) async {
        expect(request.url.path, '/auth/register');
        final body = jsonDecode(request.body);
        expect(body['email'], 'bia@example.com');
        return jsonResponse(
          {'ok': true, 'user': {'username': 'bia'}},
          status: 201,
        );
      }));
      await api.register('bia', 'bia@example.com', 'senha123');
    });

    test('a sessão salva sobrevive ao loadSavedApiKey', () async {
      final api = apiWith(MockClient((_) async => jsonResponse({
            'ok': true,
            'token': 'tok-9',
            'user': {'username': 'alex'},
          })));
      await api.login('alex', 'senha123');

      final outro = OdApi(
        baseUrl: 'http://od.test:8000',
        client: MockClient((_) async => jsonResponse({})),
      );
      expect(await outro.loadSavedApiKey(), isTrue);
      expect(outro.token, 'tok-9');
      expect(outro.username, 'alex');
    });

    test('logout limpa a sessão local', () async {
      final api = apiWith(MockClient((request) async {
        if (request.url.path == '/auth/login') {
          return jsonResponse({
            'ok': true,
            'token': 'tok-x',
            'user': {'username': 'alex'},
          });
        }
        return jsonResponse({'ok': true});
      }));
      await api.login('alex', 'senha123');
      await api.logout();
      expect(api.token, isEmpty);
      expect(api.hasCredential, isFalse);
    });
  });

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

    test('getSupervision decodifica o estado dos loops', () async {
      final api = apiWith(MockClient((request) async {
        expect(request.url.toString(), 'http://od.test:8000/supervision');
        return jsonResponse({
          'ok': true,
          'status': 'up',
          'window_s': 300.0,
          'degraded': <String>[],
          'restarts': 0,
          'loops': <Object>[],
          'ts': 1789477297.6,
        });
      }));

      final data = await api.getSupervision();
      expect(data['ok'], isTrue);
      expect(data['status'], 'up');
      expect(data['window_s'], 300.0);
      expect(data['loops'], isEmpty);
    });

    test('getSupervision degradado é resposta válida (HTTP 200)', () async {
      // Degradado NÃO é erro de requisição: o core está de pé e o app precisa
      // ler o payload normalmente para mostrar o loop caído.
      final api = apiWith(MockClient((_) async => jsonResponse({
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
          })));

      final data = await api.getSupervision();
      expect(data['ok'], isFalse);
      expect(data['degraded'], ['telegram']);
      expect(data['loops'], hasLength(1));
    });

    test('getSupervision falha com status != 200', () async {
      final api = apiWith(
        MockClient((_) async => jsonResponse({}, status: 404)),
      );
      expect(() => api.getSupervision(), throwsA(isA<OdApiError>()));
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

  group('OdApi.push (token FCM no servidor)', () {
    test('registerPushToken envia token, plataforma e aparelho', () async {
      final api = apiWith(MockClient((request) async {
        expect(request.url.path, '/push/register');
        expect(request.method, 'POST');
        final body = jsonDecode(request.body);
        expect(body['token'], 'token-fcm-123');
        expect(body['platform'], 'android');
        expect(body['device'], 'Redmi Note 14');
        return jsonResponse({'ok': true, 'devices': 1});
      }));
      await api.setApiKey('chave');

      expect(
        await api.registerPushToken('token-fcm-123', device: 'Redmi Note 14'),
        isTrue,
      );
    });

    test('sem device o campo não vai', () async {
      final api = apiWith(MockClient((request) async {
        final body = jsonDecode(request.body);
        expect(body.containsKey('device'), isFalse);
        return jsonResponse({'ok': true});
      }));
      await api.setApiKey('chave');

      expect(await api.registerPushToken('token'), isTrue);
    });

    test('sem chave não chama a rede', () async {
      var called = false;
      final api = apiWith(MockClient((_) async {
        called = true;
        return jsonResponse({'ok': true});
      }));

      expect(await api.registerPushToken('token'), isFalse);
      expect(called, isFalse);
    });

    test('falha de servidor devolve false sem lançar', () async {
      final api = apiWith(MockClient((_) async => jsonResponse(
            {'error': 'push_indisponivel'},
            status: 503,
          )));
      await api.setApiKey('chave');

      expect(await api.registerPushToken('token'), isFalse);
    });

    test('unregisterPushToken remove o aparelho', () async {
      final api = apiWith(MockClient((request) async {
        expect(request.url.path, '/push/unregister');
        expect(jsonDecode(request.body)['token'], 'token-fcm-123');
        return jsonResponse({'ok': true, 'removed': true});
      }));
      await api.setApiKey('chave');

      expect(await api.unregisterPushToken('token-fcm-123'), isTrue);
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

// ---------------------------------------------------------------------------
// Painéis do app — mesmas funcionalidades do /dashboard e /admin do site.
// ---------------------------------------------------------------------------

group('OdApi.painéis (conta e admin)', () {
  test('getMe retorna role do usuário logado', () async {
    final api = apiWith(MockClient((request) async {
      expect(request.url.path, '/auth/me');
      expect(request.headers['Authorization'], 'Bearer tok-me');
      return jsonResponse({
        'ok': true,
        'user': {'id': 1, 'username': 'alex', 'email': 'a@x.dev'},
        'via': 'session',
        'role': 'admin',
      });
    }));
    await api.setToken('tok-me');
    final me = await api.getMe();
    expect(me['role'], 'admin');
    expect(me['user']['username'], 'alex');
  });

  test('getDashboardStats consome /dashboard/stats', () async {
    final api = apiWith(MockClient((request) async {
      expect(request.url.path, '/dashboard/stats');
      return jsonResponse({
        'ok': true,
        'history': {'per_user': {}},
        'cache': {'entries': 0},
      });
    }));
    final stats = await api.getDashboardStats();
    expect(stats['ok'], isTrue);
  });

  test('changePassword devolve sessions_closed', () async {
    final api = apiWith(MockClient((request) async {
      expect(request.url.path, '/account/password');
      final body = jsonDecode(request.body);
      expect(body['current_password'], 'antiga');
      expect(body['new_password'], 'nova123');
      return jsonResponse({'ok': true, 'sessions_closed': 2});
    }));
    expect(await api.changePassword('antiga', 'nova123'), 2);
  });

  test('changePassword com senha errada lança erro do servidor', () async {
    final api = apiWith(MockClient((_) async =>
        jsonResponse({'ok': false, 'error': 'senha_incorreta'}, status: 403)));
    expect(
      () => api.changePassword('errada', 'nova123'),
      throwsA(isA<OdApiError>()
          .having((e) => e.message, 'message', 'senha_incorreta')
          .having((e) => e.statusCode, 'status', 403)),
    );
  });

  test('rotateApiKey devolve a nova chave', () async {
    final api = apiWith(
        MockClient((request) async {
          expect(request.url.path, '/account/api-key');
          expect(request.method, 'POST');
          return jsonResponse({'ok': true, 'api_key': 'od_nova'});
        }));
    expect(await api.rotateApiKey(), 'od_nova');
  });

  test('getAdminUsers passa o Bearer e devolve contas', () async {
    final api = apiWith(MockClient((request) async {
      expect(request.url.path, '/admin/users');
      expect(request.headers['Authorization'], 'Bearer tok-adm');
      return jsonResponse({
        'ok': true,
        'users': [
          {
            'id': 1,
            'username': 'alex',
            'email': 'a@x.dev',
            'sessions': 3,
            'messages': 10,
            'owner': true,
          },
        ],
        'legacy_buckets': [],
        'total': 1,
      });
    }));
    await api.setToken('tok-adm');
    final data = await api.getAdminUsers();
    expect((data['users'] as List).length, 1);
  });

  test('getAdminUsers para papel user propaga o 403', () async {
    final api = apiWith(MockClient((_) async =>
        jsonResponse({'ok': false, 'error': 'acesso_negado'}, status: 403)));
    await api.setToken('tok-user');
    expect(
      () => api.getAdminUsers(),
      throwsA(isA<OdApiError>().having((e) => e.statusCode, 'status', 403)),
    );
  });

  test('adminResetPassword manda new_password na rota certa', () async {
    final api = apiWith(MockClient((request) async {
      expect(request.url.path, '/admin/users/bia/password');
      expect(jsonDecode(request.body)['new_password'], 'se Nova6');
      return jsonResponse({'ok': true, 'username': 'bia'});
    }));
    await api.adminResetPassword('bia', 'se Nova6');
  });

  test('adminDeleteUser faz DELETE na rota certa', () async {
    final api = apiWith(MockClient((request) async {
      expect(request.url.path, '/admin/users/bia');
      expect(request.method, 'DELETE');
      return jsonResponse({'ok': true, 'username': 'bia'});
    }));
    await api.adminDeleteUser('bia');
  });
  });

  group('OdApi.sessão de desenvolvimento + caixa + ideias + limitações', () {
    test('getDevSessao consome o estado da sessão', () async {
      final api = apiWith(MockClient((request) async {
        expect(request.url.path, '/admin/dev/sessao');
        expect(request.method, 'GET');
        return jsonResponse({
          'ok': true,
          'ativo': true,
          'status': 'aguardando_autorizacao',
          'pid': 4343,
          'caixa_pendente': 1,
          'log_tail': 'rodando...',
        });
      }));
      await api.setToken('tok-adm');
      final data = await api.getDevSessao();
      expect(data['status'], 'aguardando_autorizacao');
      expect(data['caixa_pendente'], 1);
    });

    test('adminDevSessao ativar manda acao e cli', () async {
      final api = apiWith(MockClient((request) async {
        expect(request.url.path, '/admin/dev/sessao');
        expect(request.method, 'POST');
        final body = jsonDecode(request.body);
        expect(body['acao'], 'ativar');
        expect(body['cli'], 'kilo');
        return jsonResponse({'ok': true, 'pid': 4343});
      }));
      await api.setToken('tok-adm');
      final data = await api.adminDevSessao(acao: 'ativar', cli: 'kilo');
      expect(data['pid'], 4343);
    });

    test('adminDevSessao parar manda só a acao', () async {
      final api = apiWith(MockClient((request) async {
        expect(request.method, 'POST');
        final body = jsonDecode(request.body);
        expect(body['acao'], 'parar');
        expect(body.containsKey('cli'), isFalse);
        return jsonResponse({'ok': true, 'status': 'parado'});
      }));
      await api.setToken('tok-adm');
      await api.adminDevSessao(acao: 'parar');
    });

    test('adminDevSessao propaga o código do servidor (sem_ideia)', () async {
      final api = apiWith(MockClient((_) async => jsonResponse(
          {'ok': false, 'error': 'sem_ideia'},
          status: 400)));
      await api.setToken('tok-adm');
      expect(
        () => api.adminDevSessao(acao: 'ativar'),
        throwsA(isA<OdApiError>()
            .having((e) => e.message, 'message', 'sem_ideia')
            .having((e) => e.statusCode, 'status', 400)),
      );
    });

    test('adminDevSessao traz commit/ts no ja_implementado (limpeza do '
        'txt.txt)', () async {
      final api = apiWith(MockClient((_) async => jsonResponse({
            'ok': false,
            'error': 'ja_implementado',
            'commit': 'abc1234',
            'ts': '2026-10-08 17:22:36',
            'motivo': 'implantado',
          }, status: 409)));
      await api.setToken('tok-adm');
      expect(
        () => api.adminDevSessao(acao: 'ativar'),
        throwsA(isA<OdApiError>()
            .having((e) => e.message, 'message', 'ja_implementado')
            .having((e) => e.statusCode, 'status', 409)
            .having((e) => e.details?['commit'], 'commit', 'abc1234')
            .having((e) => e.details?['ts'], 'ts', '2026-10-08 17:22:36')
            .having((e) => e.details?['motivo'], 'motivo', 'implantado')),
      );
    });

    test('getDevCaixa devolve as mensagens da caixa', () async {
      final api = apiWith(MockClient((request) async {
        expect(request.url.path, '/admin/dev/caixa');
        expect(request.method, 'GET');
        return jsonResponse({
          'ok': true,
          'mensagens': [
            {'de': 'sistema', 'texto': 'Posso deletar a tabela X?'},
          ],
          'total': 1,
          'pendentes': 1,
        });
      }));
      await api.setToken('tok-adm');
      final data = await api.getDevCaixa();
      expect(data['pendentes'], 1);
    });

    test('adminDevCaixaReply manda o texto da resposta', () async {
      final api = apiWith(MockClient((request) async {
        expect(request.url.path, '/admin/dev/caixa');
        expect(request.method, 'POST');
        expect(jsonDecode(request.body)['texto'], 'pode deletar');
        return jsonResponse({'ok': true});
      }));
      await api.setToken('tok-adm');
      await api.adminDevCaixaReply('pode deletar');
    });

    test('adminDevCaixaClear faz DELETE', () async {
      final api = apiWith(MockClient((request) async {
        expect(request.url.path, '/admin/dev/caixa');
        expect(request.method, 'DELETE');
        return jsonResponse({'ok': true});
      }));
      await api.setToken('tok-adm');
      await api.adminDevCaixaClear();
    });

    test('getIdeias devolve o conteúdo do txt.txt', () async {
      final api = apiWith(MockClient((request) async {
        expect(request.url.path, '/admin/ideias');
        expect(request.method, 'GET');
        return jsonResponse({
          'ok': true,
          'existe': true,
          'conteudo': 'ideia: action do dólar',
          'bytes': 22,
        });
      }));
      await api.setToken('tok-adm');
      final data = await api.getIdeias();
      expect(data['conteudo'], 'ideia: action do dólar');
    });

    test('adminWriteIdeias faz PUT com conteudo', () async {
      final api = apiWith(MockClient((request) async {
        expect(request.url.path, '/admin/ideias');
        expect(request.method, 'PUT');
        expect(jsonDecode(request.body)['conteudo'], 'nova ideia');
        return jsonResponse({'ok': true, 'bytes': 10});
      }));
      await api.setToken('tok-adm');
      await api.adminWriteIdeias('nova ideia');
    });

    test('adminWriteIdeias aceita vazio (rascunho limpo)', () async {
      final api = apiWith(MockClient((request) async {
        expect(jsonDecode(request.body)['conteudo'], '');
        return jsonResponse({'ok': true, 'bytes': 0});
      }));
      await api.setToken('tok-adm');
      await api.adminWriteIdeias('');
    });

    test('adminClearIdeias faz DELETE', () async {
      final api = apiWith(MockClient((request) async {
        expect(request.url.path, '/admin/ideias');
        expect(request.method, 'DELETE');
        return jsonResponse({'ok': true, 'bytes': 0});
      }));
      await api.setToken('tok-adm');
      await api.adminClearIdeias();
    });

    test('getLimitacoes devolve as entradas do registro', () async {
      final api = apiWith(MockClient((request) async {
        expect(request.url.path, '/admin/limitacoes');
        return jsonResponse({
          'ok': true,
          'existe': true,
          'total': 1,
          'entradas': [
            {
              'ts': '2026-09-30T17:00:00',
              'motivo': 'fallback_honesto_esgotado',
              'pergunta': 'qual o valor do dólar',
            },
          ],
        });
      }));
      await api.setToken('tok-adm');
      final data = await api.getLimitacoes();
      expect(data['total'], 1);
      expect(data['entradas'][0]['motivo'], 'fallback_honesto_esgotado');
    });

    test('adminClearLimitacoes faz DELETE', () async {
      final api = apiWith(MockClient((request) async {
        expect(request.url.path, '/admin/limitacoes');
        expect(request.method, 'DELETE');
        return jsonResponse({'ok': true, 'total': 0});
      }));
      await api.setToken('tok-adm');
      await api.adminClearLimitacoes();
    });
  });

  group('OdApi.pickBestUrl — 4 caminhos (regra do dono, 29/09)', () {
    const lan = 'http://192.168.0.250:8000';
    const tail = 'http://100.77.67.53:8000';
    const funnel = 'https://nicky-server.tail1b1f51.ts.net';
    const router = 'http://nicky.theworkpc.com';

    OdApi apiPorHost(Map<String, int> porHost) => OdApi(
              baseUrl: tail,
              client: MockClient((request) async => http.Response(
                  '', porHost[request.url.host] ?? 0)),
            );

    test('só a LAN responde → usa a LAN (e não o tailnet)', () async {
      final api = apiPorHost({'192.168.0.250': 401});
      expect(await api.pickBestUrl(), lan);
      expect(api.baseUrl, lan);
      expect(api.fallbackUrl, isNull); // Nenhum outro caminho vivo.
    });

    test('LAN morta + tailnet vivo → tailnet com a LAN de volta se voltar',
        () async {
      final api = apiPorHost({'100.77.67.53': 401});
      expect(await api.pickBestUrl(), tail);
      expect(api.baseUrl, tail);
    });

    test('casa com tudo vivo → prefere a LAN (rota mais direta)', () async {
      final api = apiPorHost({
        '192.168.0.250': 401,
        '100.77.67.53': 401,
        'nicky-server.tail1b1f51.ts.net': 401,
        'nicky.theworkpc.com': 401,
      });
      expect(await api.pickBestUrl(), lan);
      expect(api.fallbackUrl, tail); // Segunda da ordem fica de reserva.
    });

    test('fora de casa sem Tailscale → Funnel OU roteador, nessa ordem',
        () async {
      final api =
          apiPorHost({'nicky-server.tail1b1f51.ts.net': 401, 'nicky.theworkpc.com': 401});
      expect(await api.pickBestUrl(), funnel);
      expect(api.fallbackUrl, router);

      // Funnel fora (Tailscale deslogado no celular): cai pro roteador.
      final soRot = apiPorHost({'nicky.theworkpc.com': 401});
      expect(await soRot.pickBestUrl(), router);
      expect(soRot.usingLocalUrl, isFalse);
    });

    test('nenhum caminho responde → mantém o par atual', () async {
      final api = OdApi(
        baseUrl: tail,
        fallbackUrl: funnel,
        client: MockClient((_) async => throw const SocketException('sem rota')),
      );
      expect(await api.pickBestUrl(), tail);
      expect(api.baseUrl, tail);
      expect(api.fallbackUrl, funnel);
    });

    test('classificação local/internet por HOST (DDNS http é internet)',
        () async {
      expect(apiPorHost({}).usingLocalUrl, isTrue); // 100.x
      expect(OdApi(
        baseUrl: router,
        client: MockClient((_) async => http.Response('', 401)),
      ).usingLocalUrl, isFalse);
      expect(OdApi(
        baseUrl: funnel,
        client: MockClient((_) async => http.Response('', 401)),
      ).usingLocalUrl, isFalse);
    });
  });

  group('OdApi.isAvailable — re-sondagem quando o par salvo morre', () {
    test('primária morta + fallback vivo → promove o fallback', () async {
      final api = OdApi(
        baseUrl: 'http://morto.od:8000',
        fallbackUrl: 'http://vivo.od:8000',
        client: MockClient((request) async {
          if (request.url.host == 'vivo.od') {
            return jsonResponse({'ok': true});
          }
          throw const SocketException('sem rota');
        }),
      );
      expect(await api.isAvailable(), isTrue);
      expect(api.baseUrl, 'http://vivo.od:8000');
    });

    test('par salvo morto mas OUTRO caminho vive → re-sonda e acha',
        () async {
      final api = OdApi(
        baseUrl: 'http://morto1.od:8000',
        fallbackUrl: 'http://morto2.od:8000',
        client: MockClient((request) async {
          if (request.url.host == '100.77.67.53') {
            return jsonResponse({'ok': true});
          }
          throw const SocketException('sem rota');
        }),
      );
      expect(await api.isAvailable(), isTrue);
      expect(api.baseUrl, 'http://100.77.67.53:8000');
    });
  });
}
