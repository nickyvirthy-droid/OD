/// OmegaDrakon • TESTES — Tela de Tarefas (aba "Tarefas", Task Queue R1)
///
/// Prova o contrato da tela com o servidor:
///   - renderiza fila + histórico de concluídas com status e resultado;
///   - o filtro por status esconde o que não casa (sem refazer a chamada);
///   - ⟳ reenfileira falha/dead letter pela rota de retry;
///   - 🗑 apaga registro terminal depois da confirmação;
///   - 503 (fila desligada) aparece como aviso, não como lista vazia.
///
/// A tela relê de 5 em 5 s: o timer é cancelado no dispose, então cada
/// teste desmonta a árvore antes de terminar.
library;

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:omegadrakon/screens/tasks_screen.dart';
import 'package:omegadrakon/services/od_api.dart';

const _concluida = {
  'task_id': 't-ok-0001',
  'action_name': 'filesystem_exists',
  'payload': {'path': 'iniciar/RULES.md'},
  'metadata': {'role': 'admin'},
  'priority': 0,
  'status': 'completed',
  'created_ts': 1794662400.0,
  'started_ts': 1794662400.5,
  'finished_ts': 1794662401.5,
  'attempts': 1,
  'max_retries': 3,
  'last_error': '',
  'result': true,
};

const _morta = {
  'task_id': 't-dead-0002',
  'action_name': 'filesystem_read',
  'payload': {'path': 'nao/existe.txt'},
  'metadata': {'role': 'admin'},
  'priority': 0,
  'status': 'dead_letter',
  'created_ts': 1794662500.0,
  'started_ts': 1794662501.0,
  'finished_ts': 1794662510.0,
  'attempts': 3,
  'max_retries': 3,
  'last_error': 'Action falhou: FileNotFoundError',
  'result': null,
};

http.Response _json(Object body, [int status = 200]) => http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );

class _Cenario {
  final List<String> chamadas = [];
  late final OdApi api;
  List<Map<String, dynamic>> tarefas = [
    Map<String, dynamic>.from(_concluida),
    Map<String, dynamic>.from(_morta),
  ];
  int? statusForcado; // 503 simulado

  _Cenario() {
    api = OdApi(
      baseUrl: 'http://od.test:8000',
      apiKey: 'od_teste',
      client: MockClient((r) async {
        chamadas.add('${r.method} ${r.url.path}');
        if (statusForcado != null) {
          return _json({'ok': false, 'error': 'task_queue_indisponivel'},
              statusForcado!);
        }
        if (r.method == 'GET' && r.url.path == '/admin/tasks') {
          return _json({'ok': true, 'tasks': tarefas, 'count': tarefas.length});
        }
        if (r.method == 'POST' && r.url.path.endsWith('/retry')) {
          final origem = r.url.path.split('/')[3];
          final nova = {
            ...tarefas.firstWhere((t) => t['task_id'] == origem),
            'task_id': 't-nova-0003',
            'status': 'pending',
            'attempts': 0,
            'last_error': '',
            'result': null,
          };
          tarefas.add(nova);
          return _json({'ok': true, 'task': nova, 'retried_from': origem});
        }
        if (r.method == 'DELETE') {
          final id = r.url.path.split('/')[3];
          tarefas.removeWhere((t) => t['task_id'] == id);
          return _json({'ok': true, 'removido': id});
        }
        return _json({'ok': false, 'error': 'not_found'}, 404);
      }),
    );
  }
}

Widget _wrap(Widget child) => MaterialApp(home: Scaffold(body: child));

Future<void> _desmontar(WidgetTester tester) =>
    tester.pumpWidget(const SizedBox());

Future<void> _carregar(WidgetTester tester) async {
  await tester.pump();
  await tester.pump();
}

void main() {
  testWidgets('mostra status e resultado das tarefas do servidor',
      (tester) async {
    final c = _Cenario();
    await tester.pumpWidget(_wrap(TasksScreen(api: c.api)));
    await _carregar(tester);

    expect(find.text('Tarefas do servidor'), findsOneWidget);
    expect(find.text('filesystem_exists'), findsOneWidget);
    expect(find.text('Concluída'), findsOneWidget);
    expect(find.text('Dead letter'), findsOneWidget);
    expect(find.text('true'), findsOneWidget);
    expect(find.textContaining('FileNotFoundError'), findsOneWidget);
    expect(find.textContaining('1 concluída(s)'), findsOneWidget);
    expect(c.chamadas, contains('GET /admin/tasks'));

    await _desmontar(tester);
  });

  testWidgets('filtro por status esconde o que não casa', (tester) async {
    // Tela larga o bastante para os 6 chips caberem sem rolagem — o tap
    // falharia (clipped) no tamanho padrão de 800×600.
    tester.view.physicalSize = const Size(1400, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final c = _Cenario();
    await tester.pumpWidget(_wrap(TasksScreen(api: c.api)));
    await _carregar(tester);

    await tester.tap(find.text('dead letter'));
    await tester.pump();

    expect(find.text('filesystem_read'), findsOneWidget);
    expect(find.text('filesystem_exists'), findsNothing);
    // Mudar o filtro é local: nenhuma chamada nova.
    expect(c.chamadas.where((x) => x == 'GET /admin/tasks'), hasLength(1));

    await _desmontar(tester);
  });

  testWidgets('retry reenfileira pela rota certa', (tester) async {
    final c = _Cenario();
    await tester.pumpWidget(_wrap(TasksScreen(api: c.api)));
    await _carregar(tester);

    await tester.tap(find.byIcon(Icons.replay));
    await tester.pump();
    await tester.pump();

    expect(c.chamadas,
        contains('POST /admin/tasks/t-dead-0002/retry'));
    expect(find.text('t-nova-0003'), findsOneWidget);

    await _desmontar(tester);
  });

  testWidgets('apagar pede confirmação e remove o registro terminal',
      (tester) async {
    final c = _Cenario();
    await tester.pumpWidget(_wrap(TasksScreen(api: c.api)));
    await _carregar(tester);

    // Lista ordenada por criação (mais recente primeiro): o primeiro
    // cartão é o dead letter.
    await tester.tap(find.byIcon(Icons.delete_outline).first);
    await tester.pumpAndSettle();
    expect(find.text('Apagar registro?'), findsOneWidget);

    await tester.tap(find.text('Apagar'));
    await tester.pump();
    await tester.pump();

    expect(c.chamadas, contains('DELETE /admin/tasks/t-dead-0002'));
    expect(find.text('filesystem_read'), findsNothing);

    await _desmontar(tester);
  });

  testWidgets('fila desligada (503) aparece como aviso', (tester) async {
    final c = _Cenario()..statusForcado = 503;
    await tester.pumpWidget(_wrap(TasksScreen(api: c.api)));
    await _carregar(tester);

    expect(find.textContaining('desligada no servidor'), findsOneWidget);
    expect(find.textContaining('Nenhuma tarefa'), findsNothing);

    await _desmontar(tester);
  });
}
