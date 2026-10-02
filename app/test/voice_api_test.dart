import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';


import 'package:omegadrakon/services/od_api.dart';

/// Voz no app (v1.17.3): [OdApi.transcribe] e [OdApi.synthesize] contra os
/// contratos do servidor (POST /transcribe {audio_b64} → {ok, text};
/// POST /tts {text} → {ok, audio_b64, bytes}).
///
/// A captura do microfone e a reprodução (pacotes record/audioplayers) exigem
/// plugins nativos — fora do escopo de teste de unidade; o que o app TESTA é
/// a camada HTTP e o parse das respostas.
void main() {
  OdApi apiWith(MockClient client) => OdApi(baseUrl: 'http://test', client: client);

  test('transcribe manda audio_b64 e devolve o texto', () async {
    String? capturedBody;
    Uri? capturedUri;
    final api = apiWith(
      MockClient(
        (request) async {
          capturedUri = request.url;
          capturedBody = request.body;
          return http.Response(
            jsonEncode({'ok': true, 'text': 'fala do celular'}),
            200,
          );
        },
      ),
    );
    final text = await api.transcribe([1, 2, 3, 4]);
    expect(text, 'fala do celular');
    expect(capturedUri!.path, '/transcribe');
    final payload = jsonDecode(capturedBody!) as Map<String, dynamic>;
    expect(payload['audio_b64'], base64Encode([1, 2, 3, 4]));
  });

  test('transcribe com áudio incompreensível (ok=false) lança OdApiError', () async {
    final api = apiWith(
      MockClient(
        (_) async => http.Response(
          jsonEncode({'ok': false, 'text': ''}),
          200,
        ),
      ),
    );
    expect(
      () => api.transcribe([9, 9]),
      throwsA(isA<OdApiError>()),
    );
  });

  test('transcribe 501 (STT ausente no servidor) tem mensagem clara', () async {
    final api = apiWith(
      MockClient((_) async => http.Response('{"error": "stt"}', 501)),
    );
    expect(
      () => api.transcribe([9]),
      throwsA(
        isA<OdApiError>().having(
          (e) => e.message,
          'message',
          contains('indisponível'),
        ),
      ),
    );
  });

  test('synthesize devolve os bytes do WAV decodificados', () async {
    final wav = Uint8List.fromList([0x52, 0x49, 0x46, 0x46, 1, 2, 3]);
    Uri? capturedUri;
    String? capturedBody;
    final api = apiWith(
      MockClient(
        (request) async {
          capturedUri = request.url;
          capturedBody = request.body;
          return http.Response(
            jsonEncode({
              'ok': true,
              'audio_b64': base64Encode(wav),
              'bytes': wav.length,
            }),
            200,
          );
        },
      ),
    );
    final out = await api.synthesize('bom dia');
    expect(out, wav);
    expect(capturedUri!.path, '/tts');
    final payload = jsonDecode(capturedBody!) as Map<String, dynamic>;
    expect(payload['text'], 'bom dia');
  });

  test('synthesize 501/502 lança erro amigável', () async {
    final api = apiWith(
      MockClient((_) async => http.Response('{"error": "tts"}', 501)),
    );
    expect(() => api.synthesize('oi'), throwsA(isA<OdApiError>()));
  });

  test('401 na voz lança OdAuthError', () async {
    final api = apiWith(
      MockClient((_) async => http.Response('{"error": "unauthorized"}', 401)),
    );
    expect(() => api.transcribe([1]), throwsA(isA<OdAuthError>()));
    expect(() => api.synthesize('oi'), throwsA(isA<OdAuthError>()));
  });
}
