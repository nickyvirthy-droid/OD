/// OmegaDrakon • TESTES — Tela "Curadoria do acervo" (17/11)
///
/// Pedido do dono: fechar a curadoria da rádio também no celular — excluir a
/// música que ele não gosta, bloquear faixas e liberar músicas escolhidas de
/// cantores bloqueados, sem abrir o navegador.
///
/// A tela é empurrada pelo card do Painel (não virou nona aba): o teste prova
/// o card só para admin, a navegação e cada ação batendo na rota certa.
library;

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:omegadrakon/screens/curadoria_screen.dart';
import 'package:omegadrakon/screens/dashboard_screen.dart';
import 'package:omegadrakon/services/od_api.dart';
import 'package:shared_preferences/shared_preferences.dart';

http.Response _json(Object body, [int status = 200]) => http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );

Map<String, dynamic> _corpo({
  List<Map<String, dynamic>> musicas = const [
    {
      'caminho': 'acervo/Outros/Annita - Envolver.mp3',
      'artista': 'Annita',
      'titulo': 'Envolver',
      'bloqueada': false,
      'artista_bloqueado': false,
    },
    {
      'caminho': 'acervo/Gospel/Pregador - Fogo.mp3',
      'artista': 'Pregador',
      'titulo': 'Fogo',
      'bloqueada': false,
      'artista_bloqueado': true,
    },
  ],
  List<Map<String, dynamic>> bloqueadas = const [],
  List<Map<String, dynamic>> excecoes = const [],
}) =>
    {
      'ok': true,
      'musicas': musicas,
      'bloqueadas': bloqueadas,
      'excecoes': excecoes,
      'decisoes': <Object>[],
      'horas_decisao': 24,
    };

/// Curadoria com o `POST/DELETE` registrado; o GET sempre devolve o estado.
OdApi _api({
  required List<String> chamadas,
  Map<String, dynamic>? respostaGet,
  Map<String, dynamic>? respostaAcao,
  int statusAcao = 200,
}) =>
    OdApi(
      baseUrl: 'http://od.test:8000',
      apiKey: 'od_dono',
      client: MockClient((request) async {
        chamadas.add('${request.method} ${request.url.path} ${request.body}');
        if (request.method == 'GET') {
          return _json(respostaGet ?? _corpo());
        }
        return _json(respostaAcao ?? _corpo(), statusAcao);
      }),
    );

Widget _tela(OdApi api) => MaterialApp(home: CuradoriaScreen(api: api));

Future<void> _abrirMenu(WidgetTester tester, int indice) async {
  final botoes = find.byTooltip('Ações');
  await tester.ensureVisible(botoes.at(indice));
  await tester.pumpAndSettle();
  await tester.tap(botoes.at(indice));
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('mostra o acervo, os selos e as duas listas', (tester) async {
    tester.view.physicalSize = const Size(1200, 2400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    final chamadas = <String>[];
    await tester.pumpWidget(_tela(_api(
      chamadas: chamadas,
      respostaGet: _corpo(
        bloqueadas: [
          {'artista': 'Annita', 'titulo': 'Envolver'},
        ],
        excecoes: [
          {'artista': 'Pregador', 'titulo': 'Fogo'},
        ],
      ),
    )));
    await tester.pumpAndSettle();

    expect(chamadas.single, startsWith('GET /api/radio/musicas'));
    expect(find.text('Acervo (2)'), findsOneWidget);
    // Annita aparece no acervo E na lista de bloqueadas; Pregador no acervo
    // e na lista de exceções.
    expect(find.text('Annita — Envolver'), findsNWidgets(2));
    expect(find.text('Pregador — Fogo'), findsNWidgets(2));
    // O selo explica por que a faixa sairia do ar.
    expect(find.text('cantor bloqueado'), findsOneWidget);
    expect(find.text('Músicas bloqueadas (1)'), findsOneWidget);
    expect(find.text('Exceções de cantores bloqueados (1)'), findsOneWidget);
  });

  testWidgets('excluir pede confirmação e NÃO bloqueia por padrão',
      (tester) async {
    tester.view.physicalSize = const Size(1200, 2400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    final chamadas = <String>[];
    await tester.pumpWidget(_tela(_api(chamadas: chamadas)));
    await tester.pumpAndSettle();

    await _abrirMenu(tester, 0);
    await tester.tap(find.text('Excluir do acervo (pode voltar num pedido)'));
    await tester.pumpAndSettle();

    expect(find.text('Excluir do acervo?'), findsOneWidget);
    expect(
      find.textContaining('Excluir não bloqueia'),
      findsOneWidget,
    );
    expect(chamadas, hasLength(1)); // só o GET; ainda não apagou

    await tester.tap(find.text('Excluir'));
    await tester.pumpAndSettle();

    expect(chamadas.last, startsWith('POST /api/radio/musicas/excluir'));
    expect(chamadas.last, contains('"bloquear":false'));
    expect(find.textContaining('Faixa excluída do acervo'), findsOneWidget);
  });

  testWidgets('"Excluir e bloquear" manda bloquear=true', (tester) async {
    tester.view.physicalSize = const Size(1200, 2400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    final chamadas = <String>[];
    await tester.pumpWidget(_tela(_api(chamadas: chamadas)));
    await tester.pumpAndSettle();

    await _abrirMenu(tester, 0);
    await tester.tap(find.text('Excluir e bloquear'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Excluir e bloquear').last);
    await tester.pumpAndSettle();

    expect(chamadas.last, startsWith('POST /api/radio/musicas/excluir'));
    expect(chamadas.last, contains('"bloquear":true'));
  });

  testWidgets('bloquear a música chama a lista de bloqueadas', (tester) async {
    tester.view.physicalSize = const Size(1200, 2400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    final chamadas = <String>[];
    await tester.pumpWidget(_tela(_api(chamadas: chamadas)));
    await tester.pumpAndSettle();

    await _abrirMenu(tester, 1);
    await tester.tap(find.text('Bloquear a música (apaga depois de tocar)'));
    await tester.pumpAndSettle();

    expect(chamadas.last, startsWith('POST /api/radio/musicas/bloqueadas'));
    expect(chamadas.last, contains('"artista":"Pregador"'));
    expect(chamadas.last, contains('"titulo":"Fogo"'));
  });

  testWidgets('cantor bloqueado oferece liberar a música como exceção',
      (tester) async {
    tester.view.physicalSize = const Size(1200, 2400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    final chamadas = <String>[];
    await tester.pumpWidget(_tela(_api(chamadas: chamadas)));
    await tester.pumpAndSettle();

    await _abrirMenu(tester, 0);
    // Cantor NÃO bloqueado: a opção de exceção não aparece.
    expect(find.text('Liberar esta música do cantor bloqueado'), findsNothing);
    await tester.tapAt(const Offset(10, 10)); // fecha o menu
    await tester.pumpAndSettle();

    await _abrirMenu(tester, 1);
    await tester.tap(find.text('Liberar esta música do cantor bloqueado'));
    await tester.pumpAndSettle();

    expect(chamadas.last, startsWith('POST /api/radio/musicas/excecoes'));
    expect(find.textContaining('Música liberada'), findsOneWidget);
  });

  testWidgets('desbloquear tira a música da lista negra', (tester) async {
    tester.view.physicalSize = const Size(1200, 2400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    final chamadas = <String>[];
    await tester.pumpWidget(_tela(_api(
      chamadas: chamadas,
      respostaGet: _corpo(
        musicas: const [],
        bloqueadas: [
          {'artista': 'Annita', 'titulo': 'Envolver'},
        ],
      ),
      respostaAcao: _corpo(musicas: const []),
    )));
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('Desbloquear'));
    await tester.pumpAndSettle();
    expect(chamadas.last, startsWith('DELETE /api/radio/musicas/bloqueadas'));
    expect(chamadas.last, contains('"artista":"Annita"'));
    expect(find.textContaining('pode tocar de novo'), findsOneWidget);
  });

  testWidgets('tirar a exceção devolve a música ao bloqueio do cantor',
      (tester) async {
    tester.view.physicalSize = const Size(1200, 2400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    final chamadas = <String>[];
    await tester.pumpWidget(_tela(_api(
      chamadas: chamadas,
      respostaGet: _corpo(
        musicas: const [],
        excecoes: [
          {'artista': 'Pregador', 'titulo': 'Fogo'},
        ],
      ),
      respostaAcao: _corpo(musicas: const []),
    )));
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('Tirar a exceção'));
    await tester.pumpAndSettle();
    expect(chamadas.last, startsWith('DELETE /api/radio/musicas/excecoes'));
    expect(chamadas.last, contains('"titulo":"Fogo"'));
  });

  testWidgets('403 mostra a mensagem de dono e o botão de tentar de novo',
      (tester) async {
    tester.view.physicalSize = const Size(1200, 2400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(_tela(OdApi(
      baseUrl: 'http://od.test:8000',
      client: MockClient((_) async => _json(
            {'ok': false, 'error': 'acesso_negado'},
            403,
          )),
    )));
    await tester.pumpAndSettle();

    expect(find.textContaining('Só o dono pode curar'), findsOneWidget);
    expect(find.text('Tentar'), findsOneWidget);
  });

  group('entrada pelo Painel', () {
    OdApi apiDono(List<String> chamadas) => OdApi(
          baseUrl: 'http://od.test:8000',
          client: MockClient((request) async {
            chamadas.add(request.url.path);
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
                return _json(_corpo());
              default:
                return http.Response('not found', 404);
            }
          }),
        );

    testWidgets('admin vê o card e abre a curadoria', (tester) async {
      tester.view.physicalSize = const Size(1200, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);

      final chamadas = <String>[];
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(body: DashboardScreen(api: apiDono(chamadas))),
      ));
      await tester.pumpAndSettle();

      expect(find.text('Curadoria do acervo'), findsOneWidget);
      await tester.ensureVisible(find.text('Abrir'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Abrir'));
      await tester.pumpAndSettle();

      expect(find.byType(CuradoriaScreen), findsOneWidget);
      expect(find.text('Acervo (2)'), findsOneWidget);
    });

    testWidgets('conta comum não vê o card de curadoria', (tester) async {
      tester.view.physicalSize = const Size(1200, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);

      final chamadas = <String>[];
      final api = OdApi(
        baseUrl: 'http://od.test:8000',
        client: MockClient((request) async {
          chamadas.add(request.url.path);
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
      await tester.pumpWidget(
        MaterialApp(home: Scaffold(body: DashboardScreen(api: api))),
      );
      await tester.pumpAndSettle();

      expect(find.text('Curadoria do acervo'), findsNothing);
      expect(chamadas, isNot(contains('/api/radio/musicas')));
    });
  });
}
