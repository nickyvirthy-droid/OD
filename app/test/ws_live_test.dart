/// Teste VIVO do streaming contra o core real — **opt-in**.
///
/// A suíte normal roda com dublês (rápido e determinístico). Este arquivo é o
/// outro lado: usa o conector de PRODUÇÃO (`dart:io WebSocket`) contra o
/// servidor de verdade, com a chave de verdade. Fica `skip` por padrão porque
/// depende do core de pé.
///
/// Como rodar (no servidor, onde o core escuta a 8001):
///
///   cd app
///   OD_LIVE_WS=1 OD_API_KEY="$(grep '^OD_API_KEY=' ../.env | cut -d= -f2)" \
///     flutter test test/ws_live_test.dart
///
/// Variáveis: `OD_LIVE_BASE` (padrão `http://127.0.0.1:8000`) e `OD_LIVE_WS_PORT`
/// (padrão 8001). Sem `OD_LIVE_WS=1` tudo aqui é pulado.
///
/// IMPORTANTE: este arquivo NÃO inicializa o binding do flutter_test de
/// propósito — o binding troca o `HttpClient` por um dublê que responde 400,
/// e aí não haveria socket real nenhum para testar.
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:omegadrakon/services/od_api.dart';
import 'package:omegadrakon/services/od_ws.dart';

void main() {
  final habilitado = Platform.environment['OD_LIVE_WS'] == '1';
  final base = Platform.environment['OD_LIVE_BASE'] ?? 'http://127.0.0.1:8000';
  final chave = Platform.environment['OD_API_KEY'] ?? '';
  final portaWs =
      int.tryParse(Platform.environment['OD_LIVE_WS_PORT'] ?? '') ?? 8001;

  OdStreamingChat chatPara(OdApi api) =>
      OdStreamingChat(api, wsPort: portaWs);

  group('streaming VIVO contra o core (OD_WS_PORT=$portaWs)', () {
    test(
      'o app recebe a resposta token-a-token pelo WebSocket real',
      () async {
        // Chave em memória de propósito: setApiKey() tocaria o
        // SharedPreferences, que exige o binding — e o binding mataria o
        // socket real deste teste.
        final api = OdApi(baseUrl: base, apiKey: chave);

        final chat = chatPara(api);
        // Prompt que rende VÁRIOS tokens: a resposta curta vem num chunk só e
        // não provaria entrega incremental (mesma lição do sandbox do core).
        final deltas = await chat
            .send('Liste os números de 1 a 15, um por linha, sem comentários.',
                profile: 'guardian')
            .toList()
            .timeout(const Duration(minutes: 4));

        final texto = deltas.map((d) => d.text).join();
        // ignore: avoid_print
        print('LIVE deltas=${deltas.length} transport=${deltas.last.transport} '
            'texto=${texto.trim()}');

        expect(
          deltas.last.transport,
          OdChatTransport.webSocket,
          reason: 'esperava o caminho WebSocket (a :$portaWs está no ar?)',
        );
        expect(deltas.last.done, isTrue);
        expect(texto.trim(), isNotEmpty);
        // Streaming de verdade: VÁRIOS frames de token (o `done` vem vazio).
        expect(deltas.where((d) => !d.done && d.text.isNotEmpty).length,
            greaterThanOrEqualTo(3));
      },
      skip: habilitado ? false : 'defina OD_LIVE_WS=1 para falar com o core real',
    );

    test(
      'chave errada: o streaming recusa e o app cai para o REST (401 do core)',
      () async {
        final api = OdApi(baseUrl: base, apiKey: 'chave-com-certeza-errada');

        final chat = chatPara(api);

        await expectLater(
          chat.send('oi').toList().timeout(const Duration(minutes: 1)),
          throwsA(isA<OdAuthError>()),
          reason: 'o fallback REST deve receber o 401 do core',
        );
      },
      skip: habilitado ? false : 'defina OD_LIVE_WS=1 para falar com o core real',
    );
  });
}
