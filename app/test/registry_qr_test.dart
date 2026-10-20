/// OmegaDrakon • TESTES — Câmera QR da aba Verificar (v1.44.0)
///
/// Prova o contrato da "câmera QR" (a v2 da Etapa 4 do Registro Mestre):
///
///   - [extrairCodigoQr] (od_qr.dart, função PURA): o QR do cartão é a
///     URL da verificação pública com `?posse=POSSE-…` em QUALQUER base
///     (LAN/tailnet/funnel/DDNS — só o parâmetro importa); aceita
///     `?codigo=…` (consulta direta) e o texto cru POSSE-…; QR alheio
///     → null (a tela ignora e segue lendo).
///   - Tela: com conta, o botão "📷 Ler QR" está no card "Registrar
///     minha peça"; sem conta, NÃO está (registro exige cadastro —
///     decisão do dono da Etapa 4) e a instrução de login aparece.
///
/// A câmera em si (mobile_scanner) não roda em VM de teste — o que é
/// dela (permissão negada, aparelho sem câmera) é tratado honestamente
/// no errorBuilder da tela, sem derrubar o caminho de digitar o código.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:omegadrakon/screens/registry_screen.dart';
import 'package:omegadrakon/services/od_api.dart';
import 'package:omegadrakon/services/od_qr.dart';

const _urlCartao =
    'https://nicky-server.tail1b1f51.ts.net/site/verificacao.html'
    '?posse=POSSE-ABCD-EF01-2345-6789';

void main() {
  group('extrairCodigoQr — parser puro do QR do cartão', () {
    test('URL completa com ?posse= (o formato que o servidor gera)', () {
      final l = extrairCodigoQr(_urlCartao);
      expect(l, isNotNull);
      expect(l!.posse, 'POSSE-ABCD-EF01-2345-6789');
      expect(l.codigo, isNull);
      expect(l.vazio, isFalse);
    });

    test('?posse= sem hífen/caixa baixa vira a forma canônica do cartão',
        () {
      final l = extrairCodigoQr(
        'http://192.168.0.250:8000/site/verificacao.html'
        '?posse=posseabcdefgh12345678',
      );
      expect(l?.posse, 'POSSE-ABCD-EFGH-1234-5678');
    });

    test('QR alheio (mesma host, sem os parâmetros) é ignorado', () {
      expect(
        extrairCodigoQr('https://nicky-server.tail1b1f51.ts.net/site/loja.html'),
        isNull,
      );
      expect(extrairCodigoQr('https://example.com/qualquer'), isNull);
    });

    test('?codigo= leva à consulta pública da peça', () {
      final l = extrairCodigoQr(
        'http://nicky.theworkpc.com:8000/site/verificacao.html'
        '?codigo=nv-sj-2026-0001',
      );
      expect(l?.codigo, 'NV-SJ-2026-0001');
      expect(l?.posse, isNull);
    });

    test('texto cru POSSE-… (sem URL) também serve', () {
      final l = extrairCodigoQr('posse-1234-abcd-5678-ef01');
      expect(l?.posse, 'POSSE-1234-ABCD-5678-EF01');
    });

    test('texto vazio ou só espaço não é leitura', () {
      expect(extrairCodigoQr(''), isNull);
      expect(extrairCodigoQr('   '), isNull);
    });
  });

  group('tela Verificar — botão da câmera', () {
    Future<OdApi> apiComConta() async {
      final client = MockClient((req) async => http.Response('{}', 404));
      return OdApi(
        baseUrl: 'http://od.test:8000',
        apiKey: 'od_teste',
        username: 'comprador-teste',
        client: client,
      );
    }

    Future<OdApi> apiSemConta() async {
      final client = MockClient((req) async => http.Response('{}', 404));
      return OdApi(baseUrl: 'http://od.test:8000', client: client);
    }

    testWidgets('com conta: 📷 ao lado do campo de posse, no card certo',
        (tester) async {
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(body: RegistryScreen(api: await apiComConta())),
      ));
      expect(find.text('Registrar minha peça'), findsOneWidget);
      expect(find.byTooltip('Ler QR com a câmera'), findsOneWidget);
    });

    testWidgets('sem conta: sem câmera — registro exige cadastro', (
      tester,
    ) async {
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(body: RegistryScreen(api: await apiSemConta())),
      ));
      expect(find.text('Registrar minha peça'), findsOneWidget);
      expect(find.byTooltip('Ler QR com a câmera'), findsNothing);
      expect(find.textContaining('Sem conta ainda?'), findsOneWidget);
    });
  });
}
