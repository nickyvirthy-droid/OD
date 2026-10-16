import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:omegadrakon/services/od_api.dart';
import 'package:omegadrakon/services/theme_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// TODO §3.8 (16/10): tema claro/escuro com a preferência no PERFIL.
///
/// O que este arquivo trava: a cópia local (que faz o app abrir no tema certo
/// sem rede), o envio best-effort para `/profile/preferences` e a regra de
/// precedência — perfil com escolha explícita VENCE; perfil ainda no padrão
/// deixa a escolha local SEMEAR o perfil (escolha offline não se perde).

http.Response jsonResponse(Object body, {int status = 200}) => http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );

OdApi apiWith(MockClient client) =>
    OdApi(baseUrl: 'http://od.test:8000', client: client);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('ThemeService — cópia local', () {
    test('carrega o que estava salvo (dark vira ThemeMode.dark)', () async {
      SharedPreferences.setMockInitialValues({ThemeService.chaveLocal: 'dark'});
      final tema = ThemeService();
      await tema.carregar();
      expect(tema.value, ThemeMode.dark);
    });

    test('valor desconhecido ou ausente segue o aparelho', () async {
      SharedPreferences.setMockInitialValues({ThemeService.chaveLocal: 'roxo'});
      final tema = ThemeService();
      await tema.carregar();
      expect(tema.value, ThemeMode.system);
    });

    test('definir aplica, salva local e manda para o perfil', () async {
      final chamadas = <http.Request>[];
      final api = apiWith(MockClient((request) async {
        chamadas.add(request);
        return jsonResponse({'ok': true, 'preferences': {'theme': 'light'}});
      }));
      final tema = ThemeService();
      await tema.definir(ThemeMode.light, api: api);

      expect(tema.value, ThemeMode.light);
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString(ThemeService.chaveLocal), 'light');
      expect(chamadas.single.method, 'PUT');
      expect(chamadas.single.url.path, '/profile/preferences');
      expect(jsonDecode(chamadas.single.body)['theme'], 'light');
    });

    test('servidor fora: a escolha vale localmente e não levanta', () async {
      final api = apiWith(MockClient((_) async => jsonResponse(
            {'ok': false, 'error': 'indisponível'},
            status: 503,
          )));
      final tema = ThemeService();
      await tema.definir(ThemeMode.dark, api: api);

      expect(tema.value, ThemeMode.dark);
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString(ThemeService.chaveLocal), 'dark');
    });
  });

  group('ThemeService — sincronia com o perfil', () {
    test('perfil com escolha explícita VENCE o local', () async {
      SharedPreferences.setMockInitialValues({ThemeService.chaveLocal: 'light'});
      final tema = ThemeService();
      await tema.carregar();
      final api = apiWith(MockClient(
        (_) async => jsonResponse({
          'ok': true,
          'preferences': {'theme': 'dark'},
        }),
      ));

      expect(await tema.sincronizar(api), isTrue); // mudou
      expect(tema.value, ThemeMode.dark);
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString(ThemeService.chaveLocal), 'dark');
    });

    test('perfil no padrão: a escolha local SEMEIA o perfil', () async {
      SharedPreferences.setMockInitialValues({ThemeService.chaveLocal: 'dark'});
      final tema = ThemeService();
      await tema.carregar();
      final chamadas = <http.Request>[];
      final api = apiWith(MockClient((request) async {
        chamadas.add(request);
        if (request.method == 'PUT') {
          return jsonResponse({'ok': true, 'preferences': {'theme': 'dark'}});
        }
        // perfil ainda no padrão (ninguém escolheu no site/painel)
        return jsonResponse({
          'ok': true,
          'preferences': {'theme': 'system'},
        });
      }));

      expect(await tema.sincronizar(api), isFalse); // nada a adotar
      expect(tema.value, ThemeMode.dark); // escolha local preservada
      expect(chamadas.last.method, 'PUT');
      expect(jsonDecode(chamadas.last.body)['theme'], 'dark');
    });

    test('sem aparelho decidido e perfil no padrão: nada acontece', () async {
      final api = apiWith(MockClient(
        (_) async => jsonResponse({
          'ok': true,
          'preferences': {'theme': 'system'},
        }),
      ));
      final tema = ThemeService();
      expect(await tema.sincronizar(api), isFalse);
      expect(tema.value, ThemeMode.system);
    });

    test('servidor inalcançável mantém o cache (e não levanta)', () async {
      SharedPreferences.setMockInitialValues({ThemeService.chaveLocal: 'dark'});
      final tema = ThemeService();
      await tema.carregar();
      final api = apiWith(MockClient((_) async => throw const SocketExceptionStub()));

      expect(await tema.sincronizar(api), isFalse);
      expect(tema.value, ThemeMode.dark);
    });

    test('sem api (modo avançado) a sincronia é um no-op', () async {
      final tema = ThemeService();
      expect(await tema.sincronizar(null), isFalse);
      await tema.definir(ThemeMode.light, api: null);
      expect(tema.value, ThemeMode.light);
    });
  });

  group('OdApi — preferências', () {
    test('getPreferences devolve o mapa do servidor', () async {
      final api = apiWith(MockClient((request) async {
        expect(request.method, 'GET');
        expect(request.url.path, '/profile/preferences');
        return jsonResponse({
          'ok': true,
          'preferences': {'theme': 'light'},
        });
      }));
      expect(await api.getPreferences(), {'theme': 'light'});
    });

    test('setPreferences envia o tema e devolve o resultado', () async {
      final api = apiWith(MockClient((request) async {
        expect(request.method, 'PUT');
        expect(jsonDecode(request.body), {'theme': 'dark'});
        return jsonResponse({'ok': true, 'preferences': {'theme': 'dark'}});
      }));
      expect(await api.setPreferences(theme: 'dark'), {'theme': 'dark'});
    });

    test('valor recusado pelo servidor vira OdApiError com o motivo',
        () async {
      final api = apiWith(MockClient((_) async => jsonResponse(
            {'ok': false, 'error': 'valor inválido para theme: roxo'},
            status: 400,
          )));
      expect(
        () => api.setPreferences(theme: 'roxo'),
        throwsA(isA<OdApiError>()
            .having((e) => e.message, 'message', contains('theme'))),
      );
    });
  });
}

/// Exceção de rede simples para o teste do caminho "servidor fora" sem
/// depender do IOClient real.
class SocketExceptionStub implements Exception {
  const SocketExceptionStub();
  @override
  String toString() => 'Connection refused';
}
