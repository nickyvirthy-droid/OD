/// OmegaDrakon • TESTES — Task Queue (R1): histórico, retry e remoção
///
/// O app é o CLIENTE de `/admin/tasks*`: aqui prova que lista as tarefas
/// (inclusive as concluídas do histórico), reenfileira falha/dead letter,
/// apaga registro terminal e traduz o 503 da fila desligada em mensagem
/// legível — sem inventar lista vazia quando o serviço está fora.
library;

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:omegadrakon/services/od_api.dart';

OdApi _api(MockClient client) => OdApi(
      baseUrl: 'http://od.test:8000',
      apiKey: 'od_teste',
      client: client,
    );

http.Response _json(Object body, [int status = 200]) => http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json; charset=utf-8'},
    );

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

const _mortas = {
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

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('Task Queue — REST', () {
    test('listTasks monta a fila e o histórico de concluídas', () async {
      final api = _api(MockClient((r) async {
        expect(r.method, 'GET');
        expect(r.url.path, '/admin/tasks');
        expect(r.url.queryParameters['limit'], '200');
        expect(r.headers['X-API-Key'], 'od_teste');
        return _json({
          'ok': true,
          'tasks': [_concluida, _mortas],
          'count': 2,
        });
      }));

      final tarefas = await api.listTasks(limit: 200);
      expect(tarefas, hasLength(2));
      final ok = tarefas.first;
      expect(ok.id, 't-ok-0001');
      expect(ok.actionName, 'filesystem_exists');
      expect(ok.status, 'completed');
      expect(ok.statusLabel, 'Concluída');
      expect(ok.terminal, isTrue);
      expect(ok.podeRetentar, isFalse);
      expect(ok.detalheLabel, 'true');
      expect(ok.duracaoLabel, '1.0 s');
      expect(ok.attempts, 1);

      final morta = tarefas.last;
      expect(morta.statusLabel, 'Dead letter');
      expect(morta.podeRetentar, isTrue);
      expect(morta.detalheLabel, contains('FileNotFoundError'));
    });

    test('listTasks com filtro envia o status na query', () async {
      final api = _api(MockClient((r) async {
        expect(r.url.queryParameters['status'], 'dead_letter');
        return _json({'ok': true, 'tasks': [_mortas], 'count': 1});
      }));

      final tarefas = await api.listTasks(status: 'dead_letter');
      expect(tarefas.single.id, 't-dead-0002');
    });

    test('fila desligada (503) vira mensagem legível', () async {
      final api = _api(MockClient((r) async => _json(
            {'ok': false, 'error': 'task_queue_indisponivel'},
            503,
          )));

      await expectLater(
        api.listTasks(),
        throwsA(isA<OdApiError>()
            .having((e) => e.statusCode, 'statusCode', 503)
            .having((e) => e.message, 'message',
                contains('desligada no servidor'))),
      );
    });

    test('retryTask devolve a task NOVA do servidor', () async {
      final api = _api(MockClient((r) async {
        expect(r.method, 'POST');
        expect(r.url.path, '/admin/tasks/t-dead-0002/retry');
        return _json({
          'ok': true,
          'task': {..._mortas, 'task_id': 't-nova-0003', 'status': 'pending',
            'attempts': 0, 'last_error': ''},
          'retried_from': 't-dead-0002',
        });
      }));

      final nova = await api.retryTask('t-dead-0002');
      expect(nova.id, 't-nova-0003');
      expect(nova.status, 'pending');
      expect(nova.statusLabel, 'Pendente');
      expect(nova.podeRetentar, isFalse);
    });

    test('deleteTask apaga registro terminal e explica o 409', () async {
      var apagou = false;
      final api = _api(MockClient((r) async {
        if (r.url.path == '/admin/tasks/t-ok-0001') {
          apagou = true;
          return _json({'ok': true, 'removido': 't-ok-0001'});
        }
        return _json({'ok': false, 'error': 'task_nao_terminal'}, 409);
      }));

      await api.deleteTask('t-ok-0001');
      expect(apagou, isTrue);

      await expectLater(
        api.deleteTask('t-ativa'),
        throwsA(isA<OdApiError>()
            .having((e) => e.statusCode, 'statusCode', 409)
            .having((e) => e.message, 'message', contains('ainda está ativa'))),
      );
    });
  });
}
