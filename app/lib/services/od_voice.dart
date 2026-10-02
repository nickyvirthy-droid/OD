import 'dart:async';
import 'dart:io';

import 'package:audioplayers/audioplayers.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:record/record.dart';

/// Estado do gravador para a UI (botão do microfone).
enum OdVoiceState { idle, recording, transcribing }

/// Voz no app (v1.18.0): captura de microfone + reprodução da resposta.
///
/// - Gravação: pacote `record`, codec AAC em M4A (universal no Android);
///   o servidor converte qualquer formato com ffmpeg antes do whisper.cpp.
/// - Reprodução: `audioplayers` tocando o WAV vindo do /tts do servidor.
/// - A permissão RECORD_AUDIO é pedida na 1ª gravação (runtime permission).
class OdVoice {
  final AudioRecorder _recorder = AudioRecorder();
  final AudioPlayer _player = AudioPlayer();

  /// Grava até [maxDuration] do microfone e devolve os bytes do arquivo.
  /// Lança [OdVoicePermissionDenied] sem permissão do usuário.
  Future<List<int>> record({
    Duration maxDuration = const Duration(seconds: 30),
  }) async {
    final status = await Permission.microphone.request();
    if (!status.isGranted) {
      throw OdVoicePermissionDenied();
    }
    if (!await _recorder.hasPermission()) {
      throw OdVoicePermissionDenied();
    }
    final path =
        '${Directory.systemTemp.path}/od_voz_${DateTime.now().millisecondsSinceEpoch}.m4a';
    await _recorder.start(
      const RecordConfig(encoder: AudioEncoder.aacLc, sampleRate: 16000),
      path: path,
    );
    // Gravação com teto de tempo: o usuário para tocando de novo, mas um
    // teto evita um arquivo gigante se esquecerem o botão ligado.
    await Future.any([
      _waitStop(),
      Future<void>.delayed(maxDuration),
    ]);
    final recorded = await _recorder.stop();
    if (recorded == null) {
      throw OdVoiceError('Gravação não pôde ser finalizada.');
    }
    return File(recorded).readAsBytesSync();
  }

  /// Completa quando [stopRecording] é chamado.
  Future<void> _waitStop() {
    final c = Completer<void>();
    _stopWaiters.add(c);
    return c.future;
  }

  final List<Completer<void>> _stopWaiters = [];

  /// Para a gravação em curso (idempotente).
  Future<void> stopRecording() async {
    for (final w in _stopWaiters) {
      if (!w.isCompleted) w.complete();
    }
    _stopWaiters.clear();
    try {
      if (await _recorder.isRecording()) {
        await _recorder.stop();
      }
    } catch (_) {
      // já parado
    }
  }

  /// Toca os bytes WAV da resposta do /tts. Best-effort: erro só loga
  /// (o texto da resposta continua na tela — voz é opcional).
  Future<void> play(List<int> wavBytes) async {
    final path =
        '${Directory.systemTemp.path}/od_tts_${DateTime.now().millisecondsSinceEpoch}.wav';
    final file = File(path);
    await file.writeAsBytes(wavBytes, flush: true);
    try {
      await _player.play(DeviceFileSource(path));
    } catch (_) {
      // Sem alto-falante disponível etc. — silêncio é aceitável aqui.
    }
  }

  /// Para a reprodução em curso (troca de tela/envio novo).
  Future<void> stopPlayback() => _player.stop();

  void dispose() {
    _recorder.dispose();
    _player.dispose();
  }
}

class OdVoiceError implements Exception {
  final String message;
  OdVoiceError(this.message);
  @override
  String toString() => message;
}

class OdVoicePermissionDenied extends OdVoiceError {
  OdVoicePermissionDenied()
      : super('Permissão de microfone negada — libere nas configurações.');
}
