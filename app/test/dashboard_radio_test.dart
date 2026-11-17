/// OmegaDrakon • TESTES — Decisões da rádio no Painel (17/11)
///
/// Regra do dono: faixa de cantor bloqueado **ou** de música bloqueada toca
/// uma vez para o ouvinte e espera decisão — ele tem 24 h para permitir
/// (fica no acervo e vira exceção); sem decisão, o servidor apaga.
///
/// Aqui o app é o cliente de `/api/radio/musicas` (campo `decisoes`) e de
/// `POST /api/radio/musicas/decisao`: o teste prova a leitura, a tradução
/// dos motivos, o prazo formatado e os dois botões do card do Painel.
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
      headers: {'content-type': 'application/json'},
    );

const _pendente = {
  'artista': 'Annita',
  'titulo': 'Envolver',
  'caminho': 'acervo/Outros/Annita - Envolver.mp3',
  'motivo': 'musica',
  'usuario': 'fulano',
  'status': 'aguardando',
  'segundos_restantes': 82800,
};

/// Painel do DONO: `/auth/me` com role admin + as rotas que o `_refresh`
/// pede. `decisoes` muda de vazio para a pendência na segunda chamada, para
/// o teste de ação provar que o card se atualiza depois de decidir.
OdApi _apiDono({
  List<Map<String, dynamic>> decisoes = const [_pendente],
  List<String>? posts,
  int statusDecisao = 200,
  Map<String, dynamic>? corpoDecisao,
}) {
  var chamadasMusicas = 0;
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
          return _json({
            'history': {
              'per_user': {
                'alex': {'messages': 3},
              },
            },
          });
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
          chamadasMusicas++;
          return _json({'decisoes': chamadasMusicas == 1 ? decisoes : []});
        case '/api/radio/musicas/decisao':
          posts?.add(request.body);
          return _json(corpoDecisao ?? {'ok': true, 'permitida': true},
              statusDecisao);
        default:
          return http.Response('not found', 404);
      }
    }),
  );
}

/// Painel de conta simples: o card da rádio NÃO pode ser montado.
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

  group('Rádio — decisões (REST)', () {
    test('listRadioDecisoes lê o campo decisoes do servidor', () async {
      final api = _apiDono();
      final decisoes = await api.listRadioDecisoes();
      expect(decisoes, hasLength(1));
      final d = decisoes.single;
      expect(d.artista, 'Annita');
      expect(d.titulo, 'Envolver');
      expect(d.motivo, 'musica');
      expect(d.usuario, 'fulano');
      expect(d.nome, 'Annita — Envolver');
      expect(d.motivoLabel, 'música bloqueada');
      expect(d.prazoLabel, 'apaga em 23h 0min');
      expect(d.detalhe, contains('pedido de @fulano'));
    });

    test('motivo cantor e prazo vencido são traduzidos', () {
      final d = OdDecisaoRadio.fromJson({
        'artista': 'Annita',
        'titulo': 'X',
        'motivo': 'cantor',
        'segundos_restantes': 0,
      });
      expect(d.motivoLabel, 'cantor bloqueado');
      expect(d.prazoLabel, contains('prazo vencido'));
      expect(d.detalhe, isNot(contains('@')));

      final semPrazo = OdDecisaoRadio.fromJson({'titulo': 'Y'});
      expect(semPrazo.prazoLabel, 'sem prazo');
      expect(semPrazo.nome, 'Y');
    });

    test('conta comum recebe a mensagem de dono no 403', () async {
      final api = OdApi(
        baseUrl: 'http://od.test:8000',
        client: MockClient((_) async => _json({'error': 'acesso_negado'}, 403)),
      );
      expect(
        () => api.listRadioDecisoes(),
        throwsA(isA<OdApiError>().having(
          (e) => e.message,
          'message',
          'Só o dono vê as decisões da rádio.',
        )),
      );
    });

    test('decidirRadio manda permitir=true e aceita o 200', () async {
      final posts = <String>[];
      final api = _apiDono(posts: posts);
      await api.decidirRadio('Annita', 'Envolver', permitir: true);
      expect(posts, hasLength(1));
      final corpo = jsonDecode(posts.single) as Map<String, dynamic>;
      expect(corpo, {
        'artista': 'Annita',
        'titulo': 'Envolver',
        'permitir': true,
      });
    });

    test('409 ja_decidida e 404 nao_encontrado têm texto próprio', () async {
      final ja = _apiDono(
        posts: <String>[],
        statusDecisao: 409,
        corpoDecisao: {'ok': false, 'motivo': 'ja_decidida'},
      );
      expect(
        () => ja.decidirRadio('Annita', 'X', permitir: true),
        throwsA(isA<OdApiError>().having(
          (e) => e.message,
          'message',
          'Essa faixa já foi decidida.',
        )),
      );

      final nao = _apiDono(
        posts: <String>[],
        statusDecisao: 404,
        corpoDecisao: {'ok': false, 'motivo': 'nao_encontrado'},
      );
      expect(
        () => nao.decidirRadio('Annita', 'X', permitir: false),
        throwsA(isA<OdApiError>().having(
          (e) => e.message,
          'message',
          'Essa faixa não está mais esperando decisão.',
        )),
      );
    });
  });

  group('Rádio — card no Painel', () {
    testWidgets('dono vê a pendência com prazo e os dois botões',
        (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: DashboardScreen(api: _apiDono())),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('Decisões pendentes (24 h) — 1'), findsOneWidget);
      expect(find.text('Annita — Envolver'), findsOneWidget);
      expect(find.textContaining('apaga em 23h 0min'), findsOneWidget);
      expect(find.text('Permitir'), findsOneWidget);
      expect(find.text('Apagar já'), findsOneWidget);
    });

    testWidgets('Permitir chama a API e a pendência some do card',
        (tester) async {
      final posts = <String>[];
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: DashboardScreen(api: _apiDono(posts: posts))),
        ),
      );
      await tester.pumpAndSettle();

      await tester.ensureVisible(find.text('Permitir'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Permitir'));
      await tester.pumpAndSettle();

      final corpo = jsonDecode(posts.single) as Map<String, dynamic>;
      expect(corpo['permitir'], true);
      expect(find.textContaining('permitida — fica no acervo'),
          findsOneWidget); // SnackBar
      expect(find.text('Annita — Envolver'), findsNothing);
      // O Painel recarregou: a lista veio vazia na segunda chamada.
      expect(posts.single, contains('"permitir":true'));
    });

    testWidgets('Apagar já pede confirmação antes de chamar a API',
        (tester) async {
      final posts = <String>[];
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: DashboardScreen(api: _apiDono(posts: posts))),
        ),
      );
      await tester.pumpAndSettle();

      await tester.ensureVisible(find.text('Apagar já'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Apagar já'));
      await tester.pumpAndSettle();
      expect(find.text('Apagar já?'), findsOneWidget);
      expect(posts, isEmpty); // ainda não decidiu

      await tester.tap(find.text('Cancelar'));
      await tester.pumpAndSettle();
      expect(posts, isEmpty);

      await tester.tap(find.text('Apagar já'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Apagar'));
      await tester.pumpAndSettle();

      final corpo = jsonDecode(posts.single) as Map<String, dynamic>;
      expect(corpo['permitir'], false);
    });

    testWidgets('conta comum não consulta nem mostra o card da rádio',
        (tester) async {
      final pedidos = <String>[];
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: DashboardScreen(api: _apiComum(pedidos: pedidos))),
        ),
      );
      await tester.pumpAndSettle();

      expect(pedidos, isNot(contains('/api/radio/musicas')));
      expect(find.textContaining('Decisões pendentes'), findsNothing);
    });
  });
}
