import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'od_api.dart';

// Cliente do streaming do chat (WebSocket) com fallback para `POST /message`.
///
// O core expõe dois caminhos para a MESMA conversa:
//
//   - `POST /message` (HTTP) — o app já usava; a resposta vem inteira, depois
//     de o LLM terminar (1–3 min em CPU no servidor);
//   - **WebSocket** na porta `OD_WS_PORT` (padrão **8001**, entrega do core de
//     2026-09-18) — a resposta chega em frames `token` conforme é gerada, o
//     que faz a primeira palavra aparecer em segundos em vez de minutos.
//
// A tela de chat usa o WebSocket quando ele está de pé e **cai sozinha** para
// o REST quando não estiver: core antigo (sem a porta), porta fechada, chave
// recusada, rede trocando de rota (Wi-Fi ↔ dados). Depois de uma falha o WS
// entra em espera (cooldown) — sem isso, toda mensagem pagaria o timeout de
// conexão antes de cair para o REST, deixando o chat mais lento do que era
// antes desta entrega.
//
// Protocolo (o mesmo que `integrations/api/ws_server.py` fala):
//
//   app → core: `{"type":"auth","api_key":...,"user_id":"app"}`
//               `{"type":"message","text":...,"profile":...}`
//   core → app: `{"type":"authenticated"}` · `{"type":"processing"}`
//               `{"type":"token","content":"..."}` (vários)
//               `{"type":"done","content":...,"route":...}` · `{"type":"error"}`
//
// Nota de dependência: usa `dart:io` (`WebSocket`), que é o mesmo caminho de
// rede já usado pelo `OdApi` — nenhum pacote novo entra no pubspec por causa
// disto.

/// Tempo para abrir o WebSocket e para o handshake de autenticação.
const Duration odWsConnectTimeout = Duration(seconds: 8);

/// Tempo de espera por CADA frame depois que a mensagem foi enviada.
/// Generoso de propósito: no primeiro token o servidor ainda está avaliando o
/// prompt em CPU. Casado com o `odChatTimeout` do REST (240s).
const Duration odWsFrameTimeout = Duration(seconds: 240);

/// Quanto tempo o app evita o WebSocket depois de uma falha.
const Duration odWsCooldown = Duration(minutes: 2);

/// De onde veio a resposta desta mensagem.
enum OdChatTransport {
  /// Streaming token-a-token pelo WebSocket.
  webSocket,

  /// Resposta inteira pelo `POST /message` (fallback).
  rest,
}

/// Pedaço de resposta do chat.
///
/// O consumidor concatena os [text] em ordem e para quando [done] for `true`.
/// No transporte [OdChatTransport.rest] vem um único delta com o texto todo.
/// [answeredBy] e [route] só vêm preenchidos no delta final (frame `done`):
/// QUEM respondeu (nome canônico do perfil — Regulus, Nyx...) e por qual
/// caminho (llm/cache/datetime/quick_response/action_intent).
class OdChatDelta {
  final String text;
  final bool done;
  final OdChatTransport transport;
  final String answeredBy;
  final String route;

  const OdChatDelta({
    required this.text,
    required this.done,
    required this.transport,
    this.answeredBy = '',
    this.route = '',
  });

  @override
  String toString() =>
      'OdChatDelta("$text", done: $done, transport: ${transport.name}, '
      'answeredBy: $answeredBy, route: $route)';
}

/// Falha do streaming depois que parte da resposta já foi exibida.
///
/// NÃO é possível cair para o REST aqui: a resposta veio pela metade e um
/// segundo envio da mesma mensagem geraria texto duplicado (e, no servidor,
/// uma segunda inferência). A tela mostra o que chegou e avisa que foi cortado.
class OdStreamingError extends OdApiError {
  OdStreamingError(super.message);
}

/// Canal WebSocket mínimo — é o que os testes substituem.
abstract class OdWsChannel {
  /// Mensagens de TEXTO que chegaram do servidor.
  Stream<String> get incoming;

  void send(String data);

  Future<void> close();
}

/// Abre um canal WebSocket (produção: `dart:io`).
typedef OdWsConnector = Future<OdWsChannel> Function(Uri url, Duration timeout);

/// Canal de produção sobre `dart:io WebSocket`.
class _IoWsChannel implements OdWsChannel {
  _IoWsChannel(this._socket);

  final WebSocket _socket;

  @override
  Stream<String> get incoming => _socket
      .map((event) => event is String ? event : utf8.decode(event as List<int>));

  @override
  void send(String data) => _socket.add(data);

  @override
  Future<void> close() => _socket.close();
}

/// Conector real: abre o WebSocket e devolve o canal.
Future<OdWsChannel> _ioConnector(Uri url, Duration timeout) async {
  final socket = await WebSocket.connect(url.toString()).timeout(timeout);
  // Ping periódico: o Tailscale e a rede móvel derrubam conexões ociosas; o
  // servidor já manda ping (20s) e responde, mas manter o app enviando evita
  // socket meio-aberto depois de o celular dormir.
  socket.pingInterval = const Duration(seconds: 20);
  return _IoWsChannel(socket);
}

/// Chat com streaming e fallback para o REST.
///
/// Uso na tela:
///   final chat = OdStreamingChat(api);
///   await for (final delta in chat.send('Olá')) { ... }
class OdStreamingChat {
  OdStreamingChat(
    this.api, {
    OdWsConnector? connector,
    this.wsPort = 8001,
    this.wsPath = '/ws',
    this.connectTimeout = odWsConnectTimeout,
    this.frameTimeout = odWsFrameTimeout,
    this.cooldown = odWsCooldown,
  }) : _connector = connector ?? _ioConnector;

  final OdApi api;
  final OdWsConnector _connector;

  /// Porta do servidor WebSocket no core (`OD_WS_PORT`).
  final int wsPort;

  /// Caminho do streaming quando ele vai pelo **mesmo host/porta** da API
  /// (HTTPS na 443 atrás de proxy reverso — Tailscale serve/Funnel): o proxy
  /// publica tudo numa porta só, então o WS vai por caminho (`/ws`).
  final String wsPath;

  final Duration connectTimeout;
  final Duration frameTimeout;
  final Duration cooldown;

  DateTime? _wsDownUntil;

  /// O WebSocket está sendo tentado agora? (falso durante o cooldown)
  bool get streamingPreferred {
    final until = _wsDownUntil;
    return until == null || DateTime.now().isAfter(until);
  }

  /// Deriva o endpoint do streaming da URL que o usuário já configura, **por
  /// URL** (a primária e a externa podem ter formatos diferentes):
  ///
  ///   - `https://host` (sem porta, isto é, 443): `wss://host` + [wsPath] —
  ///     caso do proxy reverso (Tailscale serve/Funnel), que só tem a 443;
  ///   - qualquer outra: troca o esquema e usa a porta do streaming
  ///     (`http://host:8000` → `ws://host:8001`).
  ///
  /// Servidor com `OD_WS_PORT` fora do padrão simplesmente cai no fallback
  /// REST.
  ///
  /// Quando há [fallbackUrl], tenta a primária e depois a secundária.
  Uri get wsUri => _deriveWsUri(api.baseUrl);

  Uri? get _wsUriFallback {
    final alt = api.fallbackUrl;
    if (alt == null || alt == api.baseUrl) return null;
    return _deriveWsUri(alt);
  }

  Uri _deriveWsUri(String base) {
    final parsed = Uri.parse(base);
    final seguro = parsed.scheme == 'https';
    final semPortaPropria = !parsed.hasPort || parsed.port == 443;
    if (seguro && semPortaPropria) {
      // Sem `port:` de propósito: o Dart não conhece a porta padrão do `wss`
      // e imprimiria `:443` à toa.
      return Uri(scheme: 'wss', host: parsed.host, path: wsPath);
    }
    return Uri(
      scheme: seguro ? 'wss' : 'ws',
      host: parsed.host,
      port: wsPort,
    );
  }

  /// Envia a mensagem e emite a resposta em pedaços.
  ///
  /// Lança [OdNetworkError]/[OdApiError] quando nem o REST respondeu (é o
  /// mesmo erro que a tela já tratava) e [OdStreamingError] quando o stream
  /// morreu no meio (aí a resposta já está parcial na tela).
  Stream<OdChatDelta> send(String text, {String profile = 'auto'}) async* {
    if (streamingPreferred) {
      var recebidos = 0;
      // Tenta a URL primária e, se houver fallback, a secundária.
      final uris = [wsUri, if (_wsUriFallback != null) _wsUriFallback!];
      for (final uri in uris) {
        try {
          await for (final delta in _sendViaWs(text, profile: profile, uri: uri)) {
            recebidos++;
            yield delta;
          }
          return;
        } catch (error) {
          // Se já chegou texto ao usuário, não tenta a outra URL (duplicaria).
          if (recebidos > 0) {
            _markWsFailure();
            throw OdStreamingError(
              'A resposta foi interrompida no meio do streaming '
              '(${_describe(error)}). O texto acima pode estar incompleto.',
            );
          }
          // Se esta foi a última URI, marca falha e cai pro REST.
          if (uri == uris.last) {
            _markWsFailure();
          }
        }
      }
      // Se chegou aqui, todas as URIs falharam antes de receber algo.
    }

    final resposta = await api.sendMessage(text, profile: profile);
    yield OdChatDelta(
      text: resposta,
      done: true,
      transport: OdChatTransport.rest,
    );
  }

  /// Fluxo pelo WebSocket: autentica, envia e traduz os frames em deltas.
  Stream<OdChatDelta> _sendViaWs(
    String text, {
    required String profile,
    Uri? uri,
  }) async* {
    final channel = await _connector(uri ?? wsUri, connectTimeout);
    final frames = StreamIterator<String>(channel.incoming);
    try {
      // 1) Autenticação — o core recusa mensagem de sessão não autenticada.
      // Com sessão de conta, manda o token (a identidade sai da credencial e
      // o histórico é o da conta); senão, o caminho avançado por API key.
      channel.send(jsonEncode({
        'type': 'auth',
        if (api.token.isNotEmpty) 'token': api.token else 'api_key': api.apiKey,
        'user_id': 'app',
      }));
      final auth = await _nextFrame(frames, connectTimeout);
      final authType = auth['type'];
      if (authType == 'error') {
        throw OdApiError(_describeServerError(auth), statusCode: 401);
      }
      if (authType != 'authenticated') {
        throw OdApiError('Handshake do streaming inesperado: $auth');
      }

      // 2) Mensagem.
      channel.send(jsonEncode({
        'type': 'message',
        'text': text,
        'profile': profile,
        'user_id': 'app',
      }));

      // 3) Frames de resposta até `done` (ou erro).
      while (true) {
        final frame = await _nextFrame(frames, frameTimeout);
        switch (frame['type']) {
          case 'token':
            final content = frame['content'];
            if (content is String && content.isNotEmpty) {
              yield OdChatDelta(
                text: content,
                done: false,
                transport: OdChatTransport.webSocket,
              );
            }
          case 'done':
            yield OdChatDelta(
              text: '',
              done: true,
              transport: OdChatTransport.webSocket,
              answeredBy: (frame['profile_name'] as String?) ??
                  ((frame['llm_used'] as String?) ?? ''),
              route: (frame['route'] as String?) ?? '',
            );
            return;
          case 'error':
            throw OdApiError(_describeServerError(frame));
          default:
            // `processing` e qualquer frame novo do servidor: ignorado de
            // propósito (o app não quebra se o core evoluir o protocolo).
            continue;
        }
      }
    } finally {
      // Encerramento best-effort e SEM await: nem o cancel da assinatura nem o
      // close handshake do socket completam garantidamente (o outro lado pode
      // ter morrido no meio do stream, o Tailscale pode trocar de rota...).
      // Esperar por eles deixaria a tela travada com a resposta já pronta —
      // foi exatamente o que o teste de widget pegou (o spinner não destravava
      // porque o gerador não retornava).
      unawaited(frames.cancel());
      unawaited(channel.close().catchError((Object _) {}));
    }
  }

  Future<Map<String, dynamic>> _nextFrame(
    StreamIterator<String> frames,
    Duration timeout,
  ) async {
    final hasNext = await frames.moveNext().timeout(
          timeout,
          onTimeout: () =>
              throw TimeoutException('sem resposta do streaming em '
                  '${timeout.inSeconds}s'),
        );
    if (!hasNext) {
      throw const SocketException('o servidor fechou o streaming');
    }
    final decoded = jsonDecode(frames.current);
    if (decoded is! Map<String, dynamic>) {
      throw OdApiError('Frame inválido do streaming: ${frames.current}');
    }
    return decoded;
  }

  /// Mensagem em pt-BR para os códigos de erro do `ws_server`.
  String _describeServerError(Map<String, dynamic> frame) {
    final code = '${frame['message'] ?? 'erro_desconhecido'}';
    switch (code) {
      case 'api_key_invalida':
        return 'API key inválida ou ausente';
      case 'nao_autenticado':
        return 'A sessão de streaming não foi autenticada';
      case 'rate_limited':
        return 'Muitas mensagens em pouco tempo. Aguarde um instante.';
      case 'text_obrigatorio':
        return 'Mensagem vazia não pode ser enviada';
    }
    if (code.startsWith('erro_processamento')) {
      return 'Erro do OD ao processar a mensagem ($code)';
    }
    return 'Erro do OD no streaming: $code';
  }

  String _describe(Object error) {
    if (error is OdApiError) return error.message;
    return error.toString();
  }

  /// Registra a falha e mantém o REST como caminho preferido por [cooldown].
  void _markWsFailure() {
    _wsDownUntil = DateTime.now().add(cooldown);
  }
}
