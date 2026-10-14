/// OmegaDrakon • TESTES — Fila de downloads resumable (Parte D do NOMAD)
///
/// O app é o CLIENTE do SSE (`/admin/downloads/events`): aqui prova que
/// ele enfileira, lista, cancela, apaga e — o mais importante — consome o
/// stream ao vivo (snapshot inicial, transições e `: ping` do meio),
/// caindo com OdApiError quando o servidor recusa.
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

const _job = {
  'id': 'dl-0001',
  'url': 'https://exemplo.test/pesos/modelo-7b.gguf',
  'destino': '/app/data/downloads/modelo-7b.gguf',
  'nome': 'modelo-7b.gguf',
  'status': 'na_fila',
  'bytes_feitos': 0,
  'bytes_total': 4096,
  'pct': 0.0,
  'tentativas': 0,
  'max_tentativas': 5,
  'erro': '',
  'sha256': '',
  'sha256_real': '',
  'criado_em': 1791582200.0,
  'atualizado_em': 1791582200.0,
  'fim_em': null,
  'proximo_retry': null,
};

const _resumo = {
  'total': 1,
  'ativas': 1,
  'na_fila': 1,
  'baixando': 0,
  'aguardando': 0,
  'concluidos': 0,
  'erros': 0,
  'cancelados': 0,
  'bytes_baixados': 0,
};

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('Fila de downloads — REST', () {
    test('listDownloads monta os jobs e o resumo', () async {
      final api = _api(MockClient((r) async {
        expect(r.method, 'GET');
        expect(r.url.path, '/admin/downloads');
        expect(r.headers['X-API-Key'], 'od_teste');
        return _json({'ok': true, 'jobs': [_job], 'resumo': _resumo});
      }));

      final fila = await api.listDownloads();
      expect(fila.jobs, hasLength(1));
      expect(fila.jobs.first.id, 'dl-0001');
      expect(fila.jobs.first.nome, 'modelo-7b.gguf');
      expect(fila.jobs.first.ativo, isTrue);
      expect(fila.resumo.naFila, 1);
      expect(fila.resumo.ativas, 1);
      expect(fila.jobs.first.bytesLabel, '0 B / 4.0 KB');
      expect(fila.jobs.first.statusLabel, 'Na fila');
    });

    test('createDownload devolve o job criado (201)', () async {
      late Map<String, dynamic> enviado;
      final api = _api(MockClient((r) async {
        expect(r.method, 'POST');
        expect(r.url.path, '/admin/downloads');
        enviado = jsonDecode(r.body) as Map<String, dynamic>;
        return _json({'ok': true, 'job': _job, 'duplicado': false}, 201);
      }));

      final job = await api.createDownload(
        url: 'https://exemplo.test/pesos/modelo-7b.gguf',
        destino: 'pesos/modelo-7b.gguf',
        sha256: 'a' * 64,
      );
      expect(enviado['url'], 'https://exemplo.test/pesos/modelo-7b.gguf');
      expect(enviado['destino'], 'pesos/modelo-7b.gguf');
      expect(enviado['sha256'], 'a' * 64);
      expect(job.id, 'dl-0001');
    });

    test('dedup do servidor (200 no lugar de 201) também vale', () async {
      final api = _api(MockClient((r) async {
        return _json({'ok': true, 'job': _job, 'duplicado': true});
      }));
      final job = await api.createDownload(url: 'https://exemplo.test/a');
      expect(job.id, 'dl-0001'); // mesmo job ativo de volta
    });

    test('erro de validação vira OdApiError com a mensagem do servidor',
        () async {
      final api = _api(MockClient((r) async {
        return _json({'ok': false, 'error': 'url_invalida'}, 400);
      }));
      final erro = await api.createDownload(url: 'nao-e-url')
          .then<Object?>((_) => fail('deveria falhar'))
          .catchError((Object e) => e);
      expect(erro, isA<OdApiError>());
      expect((erro as OdApiError).message, contains('url_invalida'));
      expect(erro.statusCode, 400);
    });

    test('fila indisponível (503) explica que a fila está desligada',
        () async {
      final api = _api(MockClient((r) async {
        return _json({'ok': false, 'error': 'downloads_indisponivel'}, 503);
      }));
      final erro = await api.listDownloads()
          .then<Object?>((_) => fail('deveria falhar'))
          .catchError((Object e) => e);
      expect((erro as OdApiError).statusCode, 503);
      expect(erro.message, contains('downloads_indisponivel'));
    });

    test('cancelDownload devolve o job já cancelado', () async {
      final api = _api(MockClient((r) async {
        expect(r.method, 'POST');
        expect(r.url.path, '/admin/downloads/dl-0001/cancel');
        return _json({
          'ok': true,
          'job': {..._job, 'status': 'cancelado'},
        });
      }));
      final job = await api.cancelDownload('dl-0001');
      expect(job.status, 'cancelado');
      expect(job.terminal, isTrue);
      expect(job.ativo, isFalse);
    });

    test('deleteDownload: 200 some com o registro, 409 explica o motivo',
        () async {
      var chamada = 0;
      final api = _api(MockClient((r) async {
        chamada++;
        expect(r.method, 'DELETE');
        expect(r.url.path, '/admin/downloads/dl-0001');
        if (chamada == 1) {
          return _json({'ok': false, 'error': 'job_ativo'}, 409);
        }
        return _json({'ok': true, 'removido': 'dl-0001'});
      }));

      final erro = await api.deleteDownload('dl-0001')
          .then<Object?>((_) => fail('primeira chamada deveria dar 409'))
          .catchError((Object e) => e);
      expect((erro as OdApiError).statusCode, 409);
      expect(erro.message, contains('ainda está ativo'));

      await api.deleteDownload('dl-0001'); // segunda: some de verdade
    });
  });

  group('Fila de downloads — SSE', () {
    test('lê snapshot + estado e ignora o : ping', () async {
      final sse = 'data: ${jsonEncode({
            'evento': 'snapshot',
            'jobs': [_job],
            'resumo': _resumo,
          })}\n\n'
          ': ping\n\n'
          'data: ${jsonEncode({
            'evento': 'estado',
            'job': {..._job, 'status': 'baixando', 'pct': 0.42},
          })}\n\n';

      late http.BaseRequest pedido;
      final api = _api(MockClient.streaming((r, corpo) async {
        pedido = r;
        return http.StreamedResponse(
          Stream.fromIterable([utf8.encode(sse)]),
          200,
          headers: {'content-type': 'text/event-stream; charset=utf-8'},
        );
      }));

      final eventos = await api.streamDownloads().toList();
      expect(eventos.map((e) => e.evento), ['snapshot', 'estado']);

      // abertura: a rota certa, com a credencial e sem timeout de corpo
      expect(pedido.method, 'GET');
      expect(pedido.url.path, '/admin/downloads/events');
      expect(pedido.headers['X-API-Key'], 'od_teste');

      // snapshot traz a fila inteira…
      final snap = eventos.first;
      expect(snap.jobs, hasLength(1));
      expect(snap.resumo?.total, 1);
      expect(snap.job, isNull);

      // …e a transição traz só o job, já com o progresso novo
      final estado = eventos[1];
      expect(estado.job?.id, 'dl-0001');
      expect(estado.job?.status, 'baixando');
      expect(estado.job?.pct, 0.42);
    });

    test('evento removido chega para a tela tirar o job da lista', () async {
      final sse = 'data: ${jsonEncode({
            'evento': 'removido',
            'job': _job,
          })}\n\n';
      final api = _api(MockClient.streaming((r, corpo) async {
        return http.StreamedResponse(
          Stream.fromIterable([utf8.encode(sse)]),
          200,
          headers: {'content-type': 'text/event-stream'},
        );
      }));
      final eventos = await api.streamDownloads().toList();
      expect(eventos.single.evento, 'removido');
      expect(eventos.single.job?.id, 'dl-0001');
    });

    test('stream recusado (401) lança OdApiError com o código', () async {
      final api = _api(MockClient.streaming((r, corpo) async {
        return http.StreamedResponse(
          Stream.fromIterable([utf8.encode('{"error":"credencial_requerida"}')]),
          401,
          headers: {'content-type': 'application/json'},
        );
      }));
      final erro = await api.streamDownloads()
          .toList()
          .then<Object?>((_) => fail('deveria falhar'))
          .catchError((Object e) => e);
      expect((erro as OdApiError).statusCode, 401);
      expect(erro.message, contains('recusado'));
    });
  });
}
