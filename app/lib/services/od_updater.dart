/// OmegaDrakon • AUTO-ATUALIZAÇÃO DO APP (v1.7.0)
///
/// O dono pediu: quando houver versão nova, o app se atualiza sozinho,
/// sem ninguém precisar abrir o site. Fluxo completo:
///
///   1. GET /app/version (público, sem chave) →
///      {version, version_code, apk, size, sha256}
///   2. Compara `version_code` do servidor com o local (package_info_plus —
///      o +N do pubspec.yaml, versionCode Android)
///   3. Servidor maior → baixa o APK em streaming (progresso p/ a UI)
///   4. Confere o SHA-256 do download contra o anunciado pelo servidor
///   5. Dispara a instalação via FileProvider (ACTION_INSTALL_PACKAGE) —
///      o Android pede a confirmação do usuário, como toda instalação
///      fora da Play Store
///
/// Segurança: o hash garante que o binário instalado é EXATAMENTE o
/// publicado pelo servidor — download truncado ou corrompido (rede ruim,
/// Funnel instável) NUNCA chega a ser instalado.
///
/// Sobre versionCode e APKs divididos por ABI: builds ATÉ a 1.6.1 somavam
/// 2000 no split arm64 (o celular do dono ficou na linhagem 2011–2016).
/// Da v1.7.0 em diante o `build_apk.sh` força o versionCode CRU do pubspec
/// com `-Pforce-version-code-ignoring-abi=true` e o piso é 2017 — a
/// comparação ([OdUpdateInfo.isNewer]) é inteira e direta, sem offsets.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart' as crypto;
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:package_info_plus/package_info_plus.dart';

import 'od_api.dart';

/// Timeout da checagem de versão — GET /app/version é um JSON minúsculo.
const Duration odUpdateCheckTimeout = Duration(seconds: 15);

/// Timeout do download do APK (~18–50 MB pela Funnel; Wi-Fi lento conta
/// em minutos — é download de arquivo, não chamada de chat).
const Duration odUpdateDownloadTimeout = Duration(minutes: 15);

/// Canal nativo (MainActivity.kt): pasta de cache do app + instalador.
const MethodChannel _odUpdaterChannel =
    MethodChannel('com.omegadrakon.nicky/updater');

/// O que o servidor anunciou de novo, com a versão local para comparar.
class OdUpdateInfo {
  /// versionName no servidor (X.Y.Z — o OD_VERSION do sistema).
  final String version;

  /// versionCode no servidor (o +N do pubspec da build publicada).
  final int versionCode;

  /// versionCode crua do app instalado (com o deslocamento de ABI, se houver).
  final int localVersionCode;

  /// URL absoluta do APK publicado (OmegaDrakon.apk em /site/).
  final String apkUrl;

  /// Tamanho do APK em bytes (0 quando o servidor não anunciou).
  final int size;

  /// SHA-256 hex do APK publicado ('' quando o servidor não anunciou).
  final String sha256;

  const OdUpdateInfo({
    required this.version,
    required this.versionCode,
    required this.localVersionCode,
    required this.apkUrl,
    this.size = 0,
    this.sha256 = '',
  });

  /// Há versão mais nova no servidor?
  ///
  /// Comparação DIRETA de inteiros — sem normalização de offset. Funciona
  /// porque os builds publicados passaram a forçar o versionCode CRU do
  /// pubspec (`force-version-code-ignoring-abi`) e o piso subiu para 2017
  /// (> 2016, maior code da linhagem antiga arm64 que somava 2000). Assim:
  ///   - arm64 antigo 2011–2016 recebe 2017 (2017 > 2016);
  ///   - completo antigo 11–16 recebe 2017;
  ///   - app 2017 instalado vs servidor 2017 = estável (nunca re-oferece);
  ///   - futuros bumps (2018, 2019…) são monotônicos para todos.
  ///
  /// Bug fixado (2026-09-27): a v1.7.0 nasceu com code 17 — downgrade
  /// contra a linhagem arm64 2016 no celular do dono → instalador recusou
  /// ("pacote parece ser inválido"). E uma normalização com desconto fixo
  /// transformaria o 2017 cru em 17/1017, oferecendo a mesma atualização
  /// para sempre.
  bool get isNewer => versionCode > localVersionCode;

  /// Tamanho em MB, pronto para exibição ('' quando desconhecido).
  String get sizeMb =>
      size <= 0 ? '' : ' (${(size / (1024 * 1024)).toStringAsFixed(0)} MB)';

  factory OdUpdateInfo.fromJson(
    Map<String, dynamic> json, {
    required String baseUrl,
    required int localVersionCode,
  }) {
    final rawApk = (json['apk'] as String?) ?? '/site/OmegaDrakon.apk';
    return OdUpdateInfo(
      version: (json['version'] as String?) ?? '',
      versionCode: (json['version_code'] as num?)?.toInt() ?? 0,
      localVersionCode: localVersionCode,
      apkUrl: rawApk.startsWith('http') ? rawApk : '$baseUrl$rawApk',
      size: (json['size'] as num?)?.toInt() ?? 0,
      sha256: (json['sha256'] as String?) ?? '',
    );
  }
}

/// Falha da atualização (download corrompido, instalador recusou etc.).
/// Mensagem pronta para o usuário — rede em si é tratada silenciosamente
/// na checagem ([OdUpdater.check]) e com [OdNetworkError] no download.
class OdUpdateError extends OdApiError {
  OdUpdateError(super.message);
}

/// Serviço de atualização do app — usa a [OdApi] apenas para saber a URL
/// ativa (local/Funnel escolhida no bootstrap).
class OdUpdater {
  OdUpdater({required this.api});

  final OdApi api;

  /// Versão local do app (versionName X.Y.Z do pubspec). Sem plataforma
  /// (testes), retorna ''.
  Future<String> localVersion() async {
    try {
      final info = await PackageInfo.fromPlatform();
      return info.version;
    } catch (_) {
      return '';
    }
  }

  /// Consulta o servidor e devolve o anúncio de versão.
  ///
  /// Retorna null quando NÃO há como comparar (sem rede, servidor antigo
  /// sem /app/version, resposta inválida) — checagem é conveniência e
  /// NUNCA deve incomodar o usuário com erro.
  Future<OdUpdateInfo?> check() async {
    try {
      final pkg = await PackageInfo.fromPlatform();
      final localCode = int.tryParse(pkg.buildNumber) ?? 0;
      final response = await http
          .get(Uri.parse('${api.baseUrl}/app/version'))
          .timeout(odUpdateCheckTimeout);
      if (response.statusCode != 200) return null;
      final data = jsonDecode(response.body);
      if (data is! Map<String, dynamic> || data['ok'] != true) return null;
      return OdUpdateInfo.fromJson(
        data,
        baseUrl: api.baseUrl,
        localVersionCode: localCode,
      );
    } catch (_) {
      return null;
    }
  }

  /// Baixa o APK anunciado em [info], com progresso (0.0 → 1.0).
  ///
  /// Confere o SHA-256 quando o servidor o anunciou; binário diferente do
  /// anunciado é apagado e rejeitado ([OdUpdateError]).
  Future<File> download(
    OdUpdateInfo info, {
    void Function(double progress)? onProgress,
  }) async {
    final dir = await _cacheDir();
    final file = File('$dir/OmegaDrakon-${info.version}.apk');
    if (await file.exists()) {
      // Download anterior interrompido — recomeça do zero (sem retomada:
      // o hash confere o arquivo INTEIRO de qualquer forma).
      await file.delete();
    }

    final client = http.Client();
    try {
      final response = await client
          .send(http.Request('GET', Uri.parse(info.apkUrl)))
          .timeout(odUpdateDownloadTimeout);
      if (response.statusCode != 200 && response.statusCode != 206) {
        throw OdUpdateError(
          'Servidor respondeu ${response.statusCode} ao baixar o APK',
        );
      }
      final total =
          response.contentLength ?? (info.size > 0 ? info.size : 0);
      final sink = file.openWrite();
      var received = 0;
      try {
        await for (final chunk in response.stream) {
          received += chunk.length;
          sink.add(chunk);
          if (total > 0 && onProgress != null) {
            onProgress((received / total).clamp(0.0, 1.0));
          }
        }
        await sink.flush();
      } finally {
        await sink.close();
      }
    } on OdUpdateError {
      rethrow;
    } catch (error) {
      if (await file.exists()) await file.delete();
      if (error is OdApiError) rethrow;
      throw OdUpdateError('Falha ao baixar a atualização: $error');
    } finally {
      client.close();
    }

    if (info.sha256.isNotEmpty) {
      final actual = await _sha256OfFile(file);
      if (actual != info.sha256.toLowerCase()) {
        await file.delete();
        throw OdUpdateError(
          'Download corrompido (hash não confere). Tente de novo.',
        );
      }
    }
    return file;
  }

  /// Dispara a instalação do APK baixado — o Android mostra a tela de
  /// confirmação ("Instalar este app?") e o usuário aprova.
  ///
  /// Retorna true quando o Android ACEITOU abrir o instalador (não significa
  /// que instalou — o usuário pode cancelar na tela do sistema).
  Future<bool> install(File apk) async {
    try {
      await _odUpdaterChannel
          .invokeMethod<void>('installApk', {'path': apk.path});
      return true;
    } on PlatformException catch (error) {
      throw OdUpdateError(
        'Instalação não iniciou: ${error.message ?? error.code}',
      );
    } on MissingPluginException {
      throw OdUpdateError(
        'Instalador indisponível nesta plataforma (só no Android).',
      );
    }
  }

  /// Pasta de cache do app (via canal nativo). No Android é o cacheDir
  /// privado do app — instalável via FileProvider. Fallback para
  /// Directory.systemTemp cobre desktop/testes.
  Future<String> _cacheDir() async {
    try {
      final dir = await _odUpdaterChannel.invokeMethod<String>('cacheDir');
      if (dir != null && dir.isNotEmpty) return dir;
    } on MissingPluginException {
      // Plataforma sem canal (teste/desktop): usa o fallback.
    }
    return Directory.systemTemp.path;
  }

  /// SHA-256 hex de um arquivo, em streaming (APK de ~50 MB não vai
  /// para a memória inteira).
  Future<String> _sha256OfFile(File file) async {
    final out = _DigestSink();
    final input = crypto.sha256.startChunkedConversion(out);
    await for (final chunk in file.openRead()) {
      input.add(chunk);
    }
    input.close();
    final digest = out.value;
    if (digest == null) {
      throw OdUpdateError('Não foi possível calcular o hash do download');
    }
    return digest.toString();
  }
}

/// Destino do hasher em streaming: recebe o [crypto.Digest] final no close.
class _DigestSink implements Sink<crypto.Digest> {
  crypto.Digest? value;

  @override
  void add(crypto.Digest data) => value = data;

  @override
  void close() {}
}
