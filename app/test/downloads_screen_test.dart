/// OmegaDrakon • TESTES — Tela de Downloads (aba "Downloads", Parte D do NOMAD)
///
/// Prova o contrato da tela com o servidor:
///   - renderiza a fila vinda de GET /admin/downloads (jobs + resumo);
///   - o SSE empurrado (/admin/downloads/events) atualiza a tela AO VIVO
///     (snapshot liga o selo "📡 ao vivo", `estado` move a barra);
///   - cancelar e apagar falam com as rotas certas;
///   - enfileirar pelo botão "Baixar" manda URL+destino.
///
/// O SSE do cenário fica DE PROPÓSITO ABERTO: stream que fecha liga o
/// polling de 5 s da tela e o pumpAndSettle nunca assenta (timer
/// periódico). O controller é fechado no teardown, depois do dispose.
library;

import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:omegadrakon/screens/downloads_screen.dart';
import 'package:omegadrakon/services/od_api.dart';

const _jobNaFila = {
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
};

const _jobConcluido = {
  'id': 'dl-0002',
  'url': 'https://exemplo.test/docs/manual.pdf',
  'destino': '/app/data/downloads/manual.pdf',
  'nome': 'manual.pdf',
  'status': 'concluido',
  'bytes_feitos': 2048,
  'bytes_total': 2048,
  'pct': 1.0,
  'tentativas': 1,
  'max_tentativas': 5,
  'erro': '',
  'sha256': '',
  'sha256_real': 'abababababababababababababababababababababababababababababababab',
};

Map<String, dynamic> _resumoDe(List<Map<String, dynamic>> jobs) {
  int contar(String s) => jobs.where((j) => j['status'] == s).length;
  return {
    'total': jobs.length,
    'ativas':
        contar('na_fila') + contar('baixando') + contar('aguardando'),
    'na_fila': contar('na_fila'),
    'baixando': contar('baixando'),
    'aguardando': contar('aguardando'),
    'concluidos': contar('concluido'),
    'erros': contar('erro'),
    'cancelados': contar('cancelado'),
    'bytes_baixados': jobs.fold<int>(
      0,
      (s, j) => s + (((j['bytes_feitos'] as num?) ?? 0).toInt()),
    ),
  };
}

/// Cenário: fila mutável + SSE por um controller que a teste controla.
class _Cenario {
  _Cenario(this.eventos, this.client, this.chamadas, this.jobs);
  final StreamController<List<int>> eventos;
  final MockClient client;
  final List<String> chamadas;
  final List<Map<String, dynamic>> jobs;

  OdApi get api => OdApi(
        baseUrl: 'http://od.test:8000',
        apiKey: 'od_teste',
        client: client,
      );

  /// Empurra um pacote SSE como o servidor faria.
  void sse(Map<String, dynamic> pacote) {
    eventos.add(utf8.encode('data: ${jsonEncode(pacote)}\n\n'));
  }

  void fechar() => eventos.close();
}

_Cenario _cenario({List<Map<String, dynamic>>? jobs, int falhasGet = 0}) {
  final lista = (jobs ?? const [_jobNaFila])
      .map((j) => Map<String, dynamic>.from(j))
      .toList();
  final eventos = StreamController<List<int>>();
  final chamadas = <String>[];
  var getsFalhos = 0;

  http.StreamedResponse json(Object corpo, [int status = 200]) =>
      http.StreamedResponse(
        Stream.fromIterable([utf8.encode(jsonEncode(corpo))]),
        status,
        headers: {'content-type': 'application/json; charset=utf-8'},
      );

  final client = MockClient.streaming((r, corpo) async {
    final caminho = r.url.path;
    chamadas.add('${r.method} $caminho');
    if (caminho == '/admin/downloads/events') {
      return http.StreamedResponse(
        eventos.stream,
        200,
        headers: {'content-type': 'text/event-stream; charset=utf-8'},
      );
    }
    if (r.method == 'GET' && caminho == '/admin/downloads') {
      if (getsFalhos++ < falhasGet) {
        return http.StreamedResponse(
          Stream.fromIterable(
            [utf8.encode('{"error":"downloads_indisponivel"}')],
          ),
          503,
          headers: {'content-type': 'application/json'},
        );
      }
      return json({
        'ok': true,
        'jobs': lista,
        'resumo': _resumoDe(lista),
      });
    }
    if (r.method == 'POST' && caminho == '/admin/downloads') {
      final dados = jsonDecode((r as http.Request).body)
          as Map<String, dynamic>;
      final url = dados['url'] as String? ?? '';
      final job = {
        ..._jobNaFila,
        'id': 'dl-0003',
        'url': url,
        'nome': url.isEmpty ? 'download' : url.split('/').last,
        'destino': dados['destino'] ?? '',
      };
      lista.add(job);
      return json({'ok': true, 'job': job, 'duplicado': false}, 201);
    }
    if (r.method == 'POST' && caminho.endsWith('/cancel')) {
      final id = caminho.split('/')[3];
      final i = lista.indexWhere((j) => j['id'] == id);
      lista[i] = {...lista[i], 'status': 'cancelado', 'pct': null};
      return json({'ok': true, 'job': lista[i]});
    }
    if (r.method == 'DELETE') {
      final id = caminho.split('/')[3];
      lista.removeWhere((j) => j['id'] == id);
      return json({'ok': true, 'removido': id});
    }
    return json({'ok': false, 'error': 'not_found'}, 404);
  });

  return _Cenario(eventos, client, chamadas, lista);
}

Widget _wrap(Widget child) => MaterialApp(home: Scaffold(body: child));

/// Desmonta a tela (cancela assinatura/timers) antes do fim do teste.
Future<void> _desmontar(WidgetTester tester) =>
    tester.pumpWidget(const SizedBox());

void main() {
  testWidgets('mostra a fila vinda do servidor', (tester) async {
    final c = _cenario();
    addTearDown(c.fechar);
    await tester.pumpWidget(_wrap(DownloadsScreen(api: c.api)));
    await tester.pump();
    await tester.pump();

    expect(find.text('Downloads do servidor'), findsOneWidget);
    expect(find.text('modelo-7b.gguf'), findsOneWidget);
    expect(find.textContaining('Na fila'), findsWidgets);
    expect(find.textContaining('1 ativa(s)'), findsOneWidget);
    // sem evento SSE ainda: a tela está no modo de consulta
    expect(find.text('↻ consultando (5 s)'), findsOneWidget);
    expect(c.chamadas, contains('GET /admin/downloads'));

    await _desmontar(tester);
  });

  testWidgets('SSE liga o modo ao vivo e move a barra de progresso',
      (tester) async {
    final c = _cenario();
    addTearDown(c.fechar);
    await tester.pumpWidget(_wrap(DownloadsScreen(api: c.api)));
    await tester.pump();
    await tester.pump();
    expect(find.text('↻ consultando (5 s)'), findsOneWidget);

    // snapshot do servidor na abertura do stream
    c.sse({
      'evento': 'snapshot',
      'jobs': [_jobNaFila],
      'resumo': _resumoDe([_jobNaFila]),
    });
    await tester.pump();
    await tester.pump();
    expect(find.text('📡 ao vivo (SSE)'), findsOneWidget);

    // transição no meio do download: barra nova e status novo
    c.sse({
      'evento': 'estado',
      'job': {..._jobNaFila, 'status': 'baixando', 'bytes_feitos': 1720},
    });
    await tester.pump();
    await tester.pump();

    expect(find.text('Baixando'), findsOneWidget);
    expect(find.textContaining('1.7 KB / 4.0 KB'), findsOneWidget);
    expect(
      find.byWidgetPredicate(
        (w) => w is LinearProgressIndicator && w.value != null,
      ),
      findsOneWidget,
    );

    await _desmontar(tester);
  });

  testWidgets('cancelar fala com a rota de cancelamento', (tester) async {
    final c = _cenario();
    addTearDown(c.fechar);
    await tester.pumpWidget(_wrap(DownloadsScreen(api: c.api)));
    await tester.pump();
    await tester.pump();

    await tester.tap(find.byIcon(Icons.cancel_outlined));
    await tester.pumpAndSettle();

    expect(c.chamadas, contains('POST /admin/downloads/dl-0001/cancel'));
    expect(find.text('Cancelado'), findsOneWidget);
    // job cancelado não é mais cancelável: o ícone de cancelar some
    expect(find.byIcon(Icons.cancel_outlined), findsNothing);
    expect(find.byIcon(Icons.delete_outline), findsOneWidget);

    await _desmontar(tester);
  });

  testWidgets('apagar registro some com o job (só depois de confirmar)',
      (tester) async {
    final c = _cenario(jobs: [_jobNaFila, _jobConcluido]);
    addTearDown(c.fechar);
    await tester.pumpWidget(_wrap(DownloadsScreen(api: c.api)));
    await tester.pump();
    await tester.pump();
    expect(find.text('manual.pdf'), findsOneWidget);

    await tester.tap(find.byIcon(Icons.delete_outline));
    await tester.pumpAndSettle();
    // confirmação apareceu e ainda NÃO apagou
    expect(find.text('Apagar registro?'), findsOneWidget);
    expect(c.chamadas.where((x) => x.startsWith('DELETE')), isEmpty);

    final confirmar = find.descendant(
      of: find.byType(AlertDialog),
      matching: find.widgetWithText(FilledButton, 'Apagar'),
    );
    await tester.tap(confirmar);
    await tester.pumpAndSettle();

    expect(c.chamadas, contains('DELETE /admin/downloads/dl-0002'));
    expect(find.text('manual.pdf'), findsNothing);
    expect(find.text('modelo-7b.gguf'), findsOneWidget); // o outro fica

    await _desmontar(tester);
  });

  testWidgets('botão Baixar enfileira URL colada no diálogo', (tester) async {
    final c = _cenario();
    addTearDown(c.fechar);
    await tester.pumpWidget(_wrap(DownloadsScreen(api: c.api)));
    await tester.pump();
    await tester.pump();

    await tester.tap(find.widgetWithText(FilledButton, 'Baixar'));
    await tester.pumpAndSettle();
    expect(find.byType(AlertDialog), findsOneWidget);

    await tester.enterText(
      find.byType(TextField).first,
      'https://exemplo.test/dataset/avalia.jsonl',
    );
    await tester.enterText(find.byType(TextField).last, 'datasets/avalia.jsonl');
    await tester.tap(
      find.descendant(
        of: find.byType(AlertDialog),
        matching: find.widgetWithText(FilledButton, 'Baixar'),
      ),
    );
    await tester.pumpAndSettle();

    expect(c.chamadas, contains('POST /admin/downloads'));
    expect(find.textContaining('Enfileirado: dl-0003'), findsOneWidget);
    expect(find.text('avalia.jsonl'), findsOneWidget);

    await _desmontar(tester);
  });

  testWidgets('fila vazia explica o que fazer', (tester) async {
    final c = _cenario(jobs: const []);
    addTearDown(c.fechar);
    await tester.pumpWidget(_wrap(DownloadsScreen(api: c.api)));
    await tester.pump();
    await tester.pump();

    expect(find.textContaining('Nenhum download na fila'), findsOneWidget);
    expect(find.textContaining('0 ativa(s)'), findsOneWidget);

    await _desmontar(tester);
  });

  testWidgets('erro do servidor aparece na tela sem derrubar a lista',
      (tester) async {
    final c = _cenario(falhasGet: 1);
    addTearDown(c.fechar);

    await tester.pumpWidget(_wrap(DownloadsScreen(api: c.api)));
    await tester.pump();
    await tester.pump();

    expect(find.textContaining('downloads_indisponivel'), findsOneWidget);
    // a tela continua de pé: cabeçalho e ação de novo download ali
    expect(find.text('Downloads do servidor'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Baixar'), findsOneWidget);

    await _desmontar(tester);
  });
}
