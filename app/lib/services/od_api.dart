import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;
import 'package:http/io_client.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Tempo para estabelecer a conexão TCP (contempla o handshake do Tailscale).
/// Curto de propósito: sem rota até o servidor deve falhar em segundos,
/// não em ~2 minutos (errno 110 do kernel).
const Duration odConnectTimeout = Duration(seconds: 8);

/// Timeout padrão por requisição (health, capabilities, execução de ações).
const Duration odRequestTimeout = Duration(seconds: 30);

/// Timeout do chat — a resposta envolve LLM local em CPU no servidor
/// (llama.cpp ~5 tok/s; latências reais de 1–3min). Casado com o
/// OD_LLM_TIMEOUT_S (240s) do servidor.
const Duration odChatTimeout = Duration(seconds: 240);

/// Tentativas para erros transitórios de rede.
const int odMaxAttempts = 3;

/// Janela base do backoff exponencial entre tentativas (400ms, 800ms, ...).
const Duration odRetryDelay = Duration(milliseconds: 400);

/// URLs padrão do OmegaDrakon — ocultas na configuração do usuário.
///
/// O app escolhe sozinho pela LOCALIZAÇÃO da rede ([OdApi.pickBestUrl]):
/// com rota até o tailnet usa a URL local (latência mínima) e, fora de
/// casa, a externa (Tailscale Funnel — TLS, funciona de qualquer lugar).
/// O usuário nunca digita URL.
const String odDefaultLocalUrl = 'http://100.77.67.53:8000';
const String odDefaultExternalUrl = 'https://nicky-server.tail1b1f51.ts.net';

/// Tempo da sonda de localização: curto de propósito — a rede local
/// responde em milissegundos; sem rota, o erro é no timeout e não vale
/// esperar os 8s do connectTimeout padrão.
const Duration odProbeTimeout = Duration(seconds: 4);

/// Cliente da API REST do OmegaDrakon.
///
/// Uso:
///   final api = OdApi(baseUrl: 'http://100.77.67.53:8000');
///   await api.setApiKey('minha-chave');
///   final resp = await api.sendMessage('Olá!');
///
/// Resiliência:
///   - conexão NOVA a cada requisição: sockets keep-alive morrem
///     silenciosamente quando o celular dorme ou o Tailscale troca de rota
///     (Wi-Fi ↔ dados); reusá-los pendura a chamada até estourar errno 110;
///   - connectTimeout curto + timeout total por chamada;
///   - retry apenas quando SEGURO: GET é sempre repetível; POST só quando a
///     conexão nem chegou a estabelecer (recusada/sem rota/DNS) — nesses
///     casos o servidor não processou nada, então repetir não executa uma
///     ação duas vezes.
class OdApi {
  final http.Client? _injectedClient;
  final Duration connectTimeout;
  final Duration requestTimeout;
  final int maxAttempts;
  final Duration retryDelay;
  String baseUrl;

  /// URL de fallback (ex.: externa quando a primária é Tailscale).
  /// Quando definida, o [_tryWithFallback] tenta a URL primária e, se
  /// falhar por rede, repete pela secundária.
  String? fallbackUrl;
  String _apiKey;
  // Sessão de conta (login/registro). Com token, o servidor usa o USUÁRIO
  // autenticado e ignora o user_id do corpo — é o que faz o histórico ser o
  // mesmo no app, no chat e no Telegram.
  String _token;
  String _username;

  OdApi({
    required this.baseUrl,
    this.fallbackUrl,
    http.Client? client,
    this.connectTimeout = odConnectTimeout,
    this.requestTimeout = odRequestTimeout,
    this.maxAttempts = odMaxAttempts,
    this.retryDelay = odRetryDelay,
    String apiKey = '',
    String token = '',
    String username = '',
  })  : _injectedClient = client,
        // Credenciais SÓ em memória (sem SharedPreferences): usado por testes
        // e verificações vivas que rodam sem o binding do Flutter — o binding
        // troca o HttpClient por um dublê que responde 400 e aí não haveria
        // socket real para exercitar. Em produção use setApiKey()/setToken(),
        // que persistem.
        _apiKey = apiKey,
        _token = token,
        _username = username;

  /// API key para autenticação X-API-Key (modo avançado).
  String get apiKey => _apiKey;

  /// Token da sessão de conta (login/registro).
  String get token => _token;

  /// Username da conta logada ("" quando é só API key).
  String get username => _username;

  /// Há alguma credencial utilizável (sessão de conta OU API key).
  bool get hasCredential => _token.isNotEmpty || _apiKey.isNotEmpty;

  /// Troca a URL do servidor em runtime (usada ao salvar as configurações).
  void setBaseUrl(String url) {
    baseUrl = url.trim();
  }

  /// Troca a URL de fallback em runtime (null/vazia limpa o fallback).
  void setFallbackUrl(String? url) {
    fallbackUrl = url?.trim().isEmpty == true ? null : url?.trim();
  }

  /// A URL ativa é a da rede local? (classificação por formato: https =
  /// externa; o resto — http/100.x — é local). É o rótulo exibido nas
  /// Configurações; a URL em si fica oculta.
  bool get usingLocalUrl => !baseUrl.startsWith('https://');

  /// Escolhe a melhor URL pela LOCALIZAÇÃO da rede.
  ///
  /// Sonda primeiro a rede local (Tailscale 100.x — responde em
  /// milissegundos quando o celular está no tailnet/em casa) e, sem rota,
  /// usa a externa (Funnel, funciona de qualquer lugar). A que responder
  /// vira a primária; a outra fica de fallback. A escolha é persistida.
  ///
  /// Prefere a URL salva do último uso (quando existir) sobre os padrões —
  /// é o que faz o app voltar ao caminho que já funcionou.
  ///
  /// Nada alcançável: mantém local como primária (é a única hipótese que
  /// pode voltar a funcionar sozinha quando a rede voltar).
  Future<String> pickBestUrl() async {
    final prefs = await SharedPreferences.getInstance();
    final local = prefs.getString('od_server_url')?.isNotEmpty == true
        ? prefs.getString('od_server_url')!
        : odDefaultLocalUrl;
    final external =
        prefs.getString('od_server_url_fallback')?.isNotEmpty == true
            ? prefs.getString('od_server_url_fallback')!
            : odDefaultExternalUrl;

    String escolhida;
    if (await isReachable(local)) {
      baseUrl = local;
      fallbackUrl = external;
      escolhida = local;
    } else if (await isReachable(external)) {
      baseUrl = external;
      fallbackUrl = local;
      escolhida = external;
    } else {
      baseUrl = local;
      fallbackUrl = external;
      escolhida = local;
    }
    await saveUrls();
    return escolhida;
  }

  /// True quando o servidor respondeu na [url] — QUALQUER status HTTP conta
  /// (o 401 do gate com OD_API_AUTH_ALL=1 prova que a rota existe). Uma
  /// tentativa só, sem retry de rede e com timeout curto ([odProbeTimeout]).
  Future<bool> isReachable(String url) async {
    try {
      final response = await _send(
        'GET',
        Uri.parse('$url/health'),
        attempts: 1,
        timeout: odProbeTimeout,
      );
      return response.statusCode >= 200 && response.statusCode < 600;
    } catch (_) {
      return false;
    }
  }

  /// Salva a API key (persistida em SharedPreferences).
  Future<void> setApiKey(String key) async {
    _apiKey = key;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('od_api_key', key);
  }

  /// Salva (ou limpa, com string vazia) a sessão de conta.
  Future<void> setToken(String token, {String username = ''}) async {
    _token = token;
    _username = token.isEmpty ? '' : username;
    final prefs = await SharedPreferences.getInstance();
    if (token.isEmpty) {
      await prefs.remove('od_session_token');
      await prefs.remove('od_username');
    } else {
      await prefs.setString('od_session_token', token);
      await prefs.setString('od_username', _username);
    }
  }

  /// Entra com usuário e senha (POST /auth/login) e guarda a sessão.
  Future<bool> login(String username, String password) async {
    final response = await _send(
      'POST',
      Uri.parse('$baseUrl/auth/login'),
      body: jsonEncode({'username': username.trim(), 'password': password}),
    );
    final data = _tryJson(response.body);
    final token = (data?['token'] as String?) ?? '';
    if (response.statusCode == 200 && data?['ok'] == true && token.isNotEmpty) {
      await setToken(token, username: (data?['user']?['username'] as String?) ?? username);
      return true;
    }
    throw OdApiError(
      (data?['error'] as String?) ?? 'Falha no login (${response.statusCode})',
      statusCode: response.statusCode,
    );
  }

  /// Cria a conta (POST /auth/register). O login é um passo separado.
  Future<void> register(String username, String email, String password) async {
    final response = await _send(
      'POST',
      Uri.parse('$baseUrl/auth/register'),
      body: jsonEncode({
        'username': username.trim(),
        'email': email.trim(),
        'password': password,
      }),
    );
    final data = _tryJson(response.body);
    if (response.statusCode == 201 && data?['ok'] == true) return;
    throw OdApiError(
      (data?['error'] as String?) ?? 'Falha ao criar a conta (${response.statusCode})',
      statusCode: response.statusCode,
    );
  }

  /// Encerra a sessão no servidor (best-effort) e apaga o token local.
  Future<void> logout() async {
    try {
      if (_token.isNotEmpty) {
        await _send('POST', Uri.parse('$baseUrl/auth/logout'));
      }
    } catch (_) {
      // Best-effort: sair localmente vale mesmo se o servidor não responder.
    }
    await setToken('');
  }

  /// Salva ambas as URLs (primária e fallback) em SharedPreferences.
  Future<void> saveUrls() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('od_server_url', baseUrl);
    if (fallbackUrl != null) {
      await prefs.setString('od_server_url_fallback', fallbackUrl!);
    } else {
      await prefs.remove('od_server_url_fallback');
    }
  }

  /// Carrega a API key e as URLs salvas.
  ///
  /// Retorna `true` se a chave estava configurada (mesmo que as URLs tenham
  /// vindo do default).
  Future<bool> loadSavedApiKey() async {
    final prefs = await SharedPreferences.getInstance();
    _apiKey = prefs.getString('od_api_key') ?? '';
    _token = prefs.getString('od_session_token') ?? '';
    _username = prefs.getString('od_username') ?? '';
    // URL primária salva sobrescreve o default do construtor.
    final savedUrl = prefs.getString('od_server_url');
    if (savedUrl != null && savedUrl.isNotEmpty) {
      baseUrl = savedUrl;
    }
    final savedFallback = prefs.getString('od_server_url_fallback');
    if (savedFallback != null && savedFallback.isNotEmpty) {
      fallbackUrl = savedFallback;
    }
    return hasCredential;
  }

  /// Headers padrão para requisições.
  ///
  /// A sessão de conta tem prioridade; a API key entra só como modo avançado.
  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (_token.isNotEmpty) 'Authorization': 'Bearer $_token',
        if (_token.isEmpty && _apiKey.isNotEmpty) 'X-API-Key': _apiKey,
      };

  /// Executa a requisição com resiliência (ver doc da classe).
  ///
  /// [attempts] sobrescreve o máximo de tentativas (a sonda de localização
  /// usa 1 — retry em sonda só multiplicaria a espera).
  Future<http.Response> _send(
    String method,
    Uri uri, {
    String? body,
    Duration? timeout,
    int? attempts,
  }) async {
    final maxTentativas = attempts ?? maxAttempts;
    var attempt = 0;
    while (true) {
      attempt++;
      // Cliente novo a cada tentativa — nunca reusa socket antigo.
      // connectionTimeout é no nível TCP (HttpClient): sem rota até o
      // servidor falha em segundos, não em ~2min (errno 110 do kernel).
      // Cliente injetado (testes) é reutilizado e NÃO fechado aqui.
      final owned = _injectedClient == null;
      final client = _injectedClient ??
          IOClient(
            HttpClient()
              ..connectionTimeout = connectTimeout
              ..idleTimeout = const Duration(seconds: 5),
          );
      try {
        final request = http.Request(method, uri)
          ..headers.addAll(_headers);
        if (body != null) {
          request.body = body;
        }
        final streamed = await client.send(request).timeout(
              timeout ?? requestTimeout,
              onTimeout: () => throw TimeoutException(
                'sem resposta do servidor em ${(timeout ?? requestTimeout).inSeconds}s',
              ),
            );
        return await http.Response.fromStream(streamed);
      } catch (error) {
        final networkError = _asNetworkError(error, uri);
        // Erro de aplicação (resposta 4xx/5xx etc.): não é rede, não retenta.
        if (networkError == null) rethrow;
        if (attempt >= maxTentativas || !_mayRetry(method, error)) {
          throw networkError;
        }
      } finally {
        if (owned) client.close();
      }
      // Backoff antes da próxima tentativa (com conexão nova).
      await Future<void>.delayed(retryDelay * attempt);
    }
  }

  /// A chamada pode ser repetida sem risco de executar algo duas vezes?
  /// GET (health/capabilities) é idempotente: sempre pode.
  /// POST (/message, /executa) só quando a conexão NEM CHEGOU a estabelecer.
  bool _mayRetry(String method, Object error) {
    if (method.toUpperCase() == 'GET') return true;
    final raw = error.toString();
    return raw.contains('Connection refused') ||
        raw.contains('Network is unreachable') ||
        raw.contains('Failed host lookup') ||
        raw.contains('No address associated');
  }

  /// Mapeia exceções transitórias de transporte para [OdNetworkError].
  /// Retorna null para erros que não são de rede (não devem ser retentados).
  OdNetworkError? _asNetworkError(Object error, Uri uri) {
    final transient = error is IOException || // Socket/Handshake/Http (dart:io)
        error is http.ClientException || // conexão fechada/cancelada (http)
        error is TimeoutException;
    if (!transient) return null;
    return OdNetworkError(_describeNetworkError(error, uri), cause: error);
  }

  /// Mensagem pronta para o usuário, em pt-BR, com a pista provável.
  String _describeNetworkError(Object error, Uri uri) {
    final raw = error.toString();
    if (error is TimeoutException ||
        raw.contains('errno = 110') ||
        raw.contains('Connection timed out')) {
      return 'O servidor em ${uri.host} não respondeu a tempo. '
          'Verifique se o Tailscale está conectado no celular e se o OD '
          '(servidor) está online.';
    }
    if (raw.contains('Connection refused')) {
      return 'O servidor ${uri.host}:${uri.port} recusou a conexão — '
          'o serviço da API está rodando?';
    }
    if (raw.contains('Network is unreachable') ||
        raw.contains('No address associated') ||
        raw.contains('Failed host lookup')) {
      return 'Sem rota de rede até ${uri.host}. '
          'Verifique a internet e se o Tailscale está ativo.';
    }
    return 'Falha de rede ao falar com ${uri.host}: $raw';
  }

  /// Envia uma mensagem e retorna a resposta do assistente.
  ///
  /// Contrato do servidor: POST /message com {user_id, text, profile} —
  /// 'message' é aceito como alias de 'text' e sem user_id vira 'app'.
  /// A resposta do OD vem no campo 'message' do JSON (OrchestrationResult).
  Future<String> sendMessage(String message, {String profile = 'auto'}) async {
    final response = await _send(
      'POST',
      Uri.parse('$baseUrl/message'),
      body: jsonEncode({
        'text': message,
        'user_id': 'app',
        'profile': profile,
      }),
      timeout: odChatTimeout,
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      if (data['ok'] == false && (data['error'] as String?)?.isNotEmpty == true) {
        throw OdApiError(
          'Erro do OD: ${data['error']}',
          statusCode: response.statusCode,
        );
      }
      return data['message'] ?? data['response'] ?? 'Sem resposta';
    } else if (response.statusCode == 401) {
      throw OdAuthError('API key inválida ou ausente');
    } else {
      throw OdApiError(
        'Erro ${response.statusCode}: ${response.body}',
        statusCode: response.statusCode,
      );
    }
  }

  /// Carrega as mensagens recentes da conta (GET /history/{user_id}).
  ///
  /// Com sessão Bearer o servidor usa o usuário autenticado e o [userId] é
  /// ignorado; com API key (modo avançado) usa o balde informado. [me] resolve
  /// para a própria conta. Falha silenciosa (best-effort): histórico é
  /// conveniência — a conversa nova nunca deve depender dele.
  Future<List<OdHistoryMessage>> getHistory({
    String userId = 'me',
    int limit = 50,
  }) async {
    if (!hasCredential) return const [];
    final response = await _send(
      'GET',
      Uri.parse(
        '$baseUrl/history/${Uri.encodeComponent(userId)}'
        '?limit=$limit',
      ),
    );
    if (response.statusCode != 200) return const [];
    final data = _tryJson(response.body);
    final raw = data?['messages'];
    if (raw is! List) return const [];
    return raw
        .whereType<Map>()
        .map((m) => OdHistoryMessage(
              role: (m['role'] as String?) ?? 'user',
              content: (m['content'] as String?) ?? '',
              ts: (m['ts'] as num?)?.toDouble(),
              answeredBy: (m['llm_used'] as String?) ?? '',
            ))
        .where((m) => m.content.isNotEmpty)
        .toList(growable: false);
  }

  /// Verifica a saúde do sistema.
  Future<Map<String, dynamic>> getHealth() async {
    final response = await _send(
      'GET',
      Uri.parse('$baseUrl/health'),
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    }
    throw OdApiError('Health check falhou: ${response.statusCode}');
  }

  /// Retorna as capacidades do sistema.
  Future<Map<String, dynamic>> getCapabilities() async {
    final response = await _send(
      'GET',
      Uri.parse('$baseUrl/capabilities'),
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    }
    throw OdApiError('Capabilities falhou: ${response.statusCode}');
  }

  /// Estado da supervisão dos loops do núcleo (GET /supervision).
  ///
  /// O OD roda vários loops no MESMO processo (API, Telegram, recovery, MQTT,
  /// presença, visão). Cada um é isolado pelo launcher: um loop que cai é
  /// CONTIDO e reiniciado em vez de derrubar o core — este endpoint conta esse
  /// rastro. `ok=false` + `status=degraded` significam "loop caiu nos últimos
  /// `window_s` segundos" e vêm com **HTTP 200**: degradado não é erro de
  /// requisição, o servidor está de pé.
  ///
  /// Contrato: `{ok, status, window_s, degraded[], restarts, loops[], ts}`,
  /// com cada item de `loops[]` trazendo `name`, `failures`, `restarts`,
  /// `last_kind`, `last_error`, `age_s`, `degraded` e `crash_loop`.
  Future<Map<String, dynamic>> getSupervision() async {
    final response = await _send(
      'GET',
      Uri.parse('$baseUrl/supervision'),
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body) as Map<String, dynamic>;
    }
    throw OdApiError('Supervisão falhou: ${response.statusCode}');
  }

  /// Catálogo de actions (GET /actions — ActionRegistry com risco).
  Future<List<Map<String, dynamic>>> getActions() async {
    final response = await _send(
      'GET',
      Uri.parse('$baseUrl/actions'),
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      final actions = data['actions'] ?? [];
      return List<Map<String, dynamic>>.from(actions);
    }
    throw OdApiError('Catálogo de ações falhou: ${response.statusCode}');
  }

  /// Executa uma ação específica (POST /executa — paridade do Telegram).
  ///
  /// Ações destrutivas (risk high) exigem [confirm] — sem ele o servidor
  /// responde 422 e aqui lança [OdApiError] com a mensagem do servidor.
  Future<String> executeAction(
    String actionName, {
    Map<String, dynamic>? params,
    bool confirm = false,
  }) async {
    final response = await _send(
      'POST',
      Uri.parse('$baseUrl/executa'),
      body: jsonEncode({
        'action': actionName,
        if (params != null && params.isNotEmpty) 'params': params,
        if (confirm) 'confirm': true,
      }),
    );

    final data = response.statusCode == 200 || response.statusCode >= 400
        ? _tryJson(response.body)
        : null;
    final map = data is Map<String, dynamic> ? data : null;
    if (map != null && map['status'] == 'ok') {
      return _formatActionResult(actionName, map['data']);
    }
    if (map != null && map['error'] != null) {
      throw OdApiError(
        '${map['error']}',
        statusCode: response.statusCode,
      );
    }
    throw OdApiError('Ação falhou: ${response.statusCode}');
  }

  /// Formata o resultado de uma action para exibição no chat da tela.
  String _formatActionResult(String actionName, Object? data) {
    if (data == null) return '✅ `$actionName` executada (sem retorno)';
    if (data is String) return data;
    if (data is Map) {
      final lines = data.entries
          .map((e) => '${e.key}: ${e.value}')
          .take(30)
          .join('\n');
      return lines.isEmpty ? '✅ `$actionName` executada' : lines;
    }
    return data.toString();
  }

  static Map<String, dynamic>? _tryJson(String body) {
    try {
      final decoded = jsonDecode(body);
      return decoded is Map<String, dynamic> ? decoded : null;
    } catch (_) {
      return null;
    }
  }

  /// Registra o token FCM deste aparelho no servidor (push do OD).
  ///
  /// O OD passa a poder mandar notificação para cá mesmo com o app fechado.
  /// O token é a chave do registro — reenviar só atualiza o aparelho.
  ///
  /// Best-effort de propósito: devolve false (sem lançar) quando não há token
  /// ou chave, ou quando a rede/servidor falha. Push nunca pode atrapalhar o
  /// uso do app.
  Future<bool> registerPushToken(
    String token, {
    String platform = 'android',
    String device = '',
  }) async {
    if (token.isEmpty || !hasCredential) return false;
    try {
      final response = await _send(
        'POST',
        Uri.parse('$baseUrl/push/register'),
        body: jsonEncode({
          'token': token,
          'platform': platform,
          if (device.isNotEmpty) 'device': device,
        }),
      );
      return response.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  /// Remove este aparelho do push (troca de conta/aparelho).
  Future<bool> unregisterPushToken(String token) async {
    if (token.isEmpty || !hasCredential) return false;
    try {
      final response = await _send(
        'POST',
        Uri.parse('$baseUrl/push/unregister'),
        body: jsonEncode({'token': token}),
      );
      return response.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  /// Verifica se a API está acessível (health check rápido).
  ///
  /// Se houver [fallbackUrl], tenta a primária e, se falhar, a secundária.
  Future<bool> isAvailable() async {
    try {
      final health = await getHealth();
      if (health['ok'] == true) return true;
    } catch (_) {
      // Cai no fallback abaixo.
    }
    // Tenta a URL de fallback se a primária falhou.
    final alt = fallbackUrl;
    if (alt != null && alt != baseUrl) {
      try {
        final prev = baseUrl;
        baseUrl = alt;
        final health = await getHealth();
        if (health['ok'] == true) {
          // Troca as URLs: a que funciona agora é a primária.
          baseUrl = alt;
          fallbackUrl = prev;
          return true;
        }
        baseUrl = prev;
      } catch (_) {
        baseUrl = fallbackUrl ?? baseUrl;
      }
    }
    return false;
  }
}

/// Mensagem vinda do histórico da conta (GET /history/{user_id}).
///
/// O servidor grava role 'user'/'assistant' (e 'system' para avisos); o app
/// exibe 'assistant' e 'system' como lado do OD.
class OdHistoryMessage {
  final String role;
  final String content;
  final DateTime timestamp;

  /// Quem/resposta gravada pelo servidor (llm_used do turno).
  final String answeredBy;

  OdHistoryMessage({
    required this.role,
    required this.content,
    double? ts,
    this.answeredBy = '',
  }) : timestamp = ts == null
            ? DateTime.now()
            : DateTime.fromMillisecondsSinceEpoch((ts * 1000).round());

  bool get isUser => role == 'user';
}

class OdApiError implements Exception {
  final String message;
  final int? statusCode;
  OdApiError(this.message, {this.statusCode});
  @override
  String toString() => 'OdApiError: $message';
}

class OdAuthError extends OdApiError {
  OdAuthError(super.message);
}

/// Falha de transporte (rede/Tailscale/timeout): o servidor não chegou a
/// responder. Diferente de [OdApiError] (resposta HTTP de erro).
/// A mensagem já vem pronta para exibição ao usuário.
class OdNetworkError extends OdApiError {
  final Object? cause;
  OdNetworkError(super.message, {this.cause});
  @override
  String toString() => 'OdNetworkError: $message';
}
