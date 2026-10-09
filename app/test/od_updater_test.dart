/// OmegaDrakon • TESTES — OdUpdateInfo (versionCode da auto-atualização)
///
/// Cenário REAL que motivou estes testes (2026-09-27): o celular do dono
/// está na linhagem arm64 dos builds ANTIGOS (offset 2000: 1.5.0 = 2014,
/// 1.6.1 = 2016). O primeiro APK da v1.7.0 saiu com o code cru 17 →
/// downgrade → instalador recusou ("pacote parece ser inválido").
/// Correção: builds publicam code cru >= 2017 (> 2016, piso da linhagem
/// antiga) e a comparação é DIRETA — sem normalização de offset.
library;

import 'package:flutter_test/flutter_test.dart';

import 'package:omegadrakon/services/od_updater.dart';

OdUpdateInfo _info({
  required int serverCode,
  required int localCode,
}) {
  return OdUpdateInfo(
    version: '1.7.0',
    versionCode: serverCode,
    localVersionCode: localCode,
    apkUrl: 'http://x/site/OmegaDrakon.apk',
  );
}

void main() {
  group('OdUpdateInfo — linhagem arm64 antiga (offset 2000)', () {
    test('1.6.1 arm64 (2016) recebe o 2017 — o caso real do dono', () {
      expect(_info(serverCode: 2017, localCode: 2016).isNewer, isTrue);
    });

    test('1.5.0 arm64 (2014) também receberia o 2017', () {
      expect(_info(serverCode: 2017, localCode: 2014).isNewer, isTrue);
    });

    test('1.2.8 arm64 (2011) recebe o 2017', () {
      expect(_info(serverCode: 2017, localCode: 2011).isNewer, isTrue);
    });
  });

  group('OdUpdateInfo — linhagem completa antiga (code cru)', () {
    test('1.6.1 completo (16) recebe o 2017', () {
      expect(_info(serverCode: 2017, localCode: 16).isNewer, isTrue);
    });

    test('1.2.8 completo (11) recebe o 2017', () {
      expect(_info(serverCode: 2017, localCode: 11).isNewer, isTrue);
    });
  });

  group('OdUpdateInfo — estabilidade (nunca re-oferece a mesma versão)', () {
    test('2017 instalado (arm64 atualizado) vs servidor 2017 = estável', () {
      expect(_info(serverCode: 2017, localCode: 2017).isNewer, isFalse);
    });

    test('servidor antigo (17) NUNCA derrapa o app 2017 para trás', () {
      // O bug da 1ª v1.7.0: se o servidor anunciasse 17 para um app que
      // já tivesse 2017, qualquer normalização/desconto permitiria loop.
      expect(_info(serverCode: 17, localCode: 2017).isNewer, isFalse);
    });

    test('bump seguinte (2018) é oferecido para quem já está no 2017', () {
      expect(_info(serverCode: 2018, localCode: 2017).isNewer, isTrue);
    });

    test('downgrade explícito nunca é oferecido', () {
      expect(_info(serverCode: 2016, localCode: 2017).isNewer, isFalse);
    });
  });

  group('odUpdateStatusMessage — a tela mostra as DUAS versões (1.23.1)', () {
    // O dono cobrou (2026-10-09): "o app não mostra a versão atual ao
    // clicar Verificar Atualização". A mensagem SEMPRE traz publicada ×
    // instalada, com os versionCodes.
    test('sem atualização: publicada e instalada aparecem', () {
      final msg = odUpdateStatusMessage(
        OdUpdateInfo(
          version: '1.23.1',
          versionCode: 2051,
          localVersionCode: 2051,
          apkUrl: 'http://x/site/OmegaDrakon.apk',
        ),
        localVersion: '1.23.1',
      );
      expect(msg, contains('v1.23.1'));
      expect(msg, contains('2051'));
      expect(msg, contains('mais recente'));
    });

    test('com atualização: nomeia a nova E a instalada com códigos', () {
      final msg = odUpdateStatusMessage(
        OdUpdateInfo(
          version: '1.23.1',
          versionCode: 2051,
          localVersionCode: 2050,
          apkUrl: 'http://x/site/OmegaDrakon.apk',
          size: 55 * 1024 * 1024,
        ),
        localVersion: '1.23.0',
      );
      expect(msg, contains('Nova versão v1.23.1'));
      expect(msg, contains('2051'));
      expect(msg, contains('v1.23.0'));
      expect(msg, contains('2050'));
    });

    test('PackageInfo indisponível: cai para o versionCode instalado', () {
      final msg = odUpdateStatusMessage(
        OdUpdateInfo(
          version: '1.23.1',
          versionCode: 2051,
          localVersionCode: 2051,
          apkUrl: 'http://x/site/OmegaDrakon.apk',
        ),
        localVersion: '',
      );
      expect(msg, contains('código 2051'));
      expect(msg, isNot(contains('v (código')));
    });

    test('servidor inacessível: mensagem de falha honesta', () {
      final msg = odUpdateStatusMessage(null, localVersion: '1.23.1');
      expect(msg, contains('Não consegui verificar'));
    });
  });
}
