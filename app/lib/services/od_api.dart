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
  String _apiKey = '';

  OdApi({
    required this.baseUrl,
    http.Client? client,
    this.connectTimeout = odConnectTimeout,
    this.requestTimeout = odRequestTimeout,
    this.maxAttempts = odMaxAttempts,
    this.retryDelay = odRetryDelay,
  }) : _injectedClient = client;

  /// API key para autenticação X-API-Key.
  String get apiKey => _apiKey;

  /// Troca a URL do servidor em runtime (usada ao salvar as configurações).
  void setBaseUrl(String url) {
    baseUrl = url.trim();
  }

  /// Salva a API key (persistida em SharedPreferences).
  Future<void> setApiKey(String key) async {
    _apiKey = key;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('od_api_key', key);
  }

  /// Carrega a API key salva.
  Future<bool> loadSavedApiKey() async {
    final prefs = await SharedPreferences.getInstance();
    _apiKey = prefs.getString('od_api_key') ?? '';
    return _apiKey.isNotEmpty;
  }

  /// Headers padrão para requisições.
  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (_apiKey.isNotEmpty) 'X-API-Key': _apiKey,
      };

  /// Executa a requisição com resiliência (ver doc da classe).
  Future<http.Response> _send(
    String method,
    Uri uri, {
    String? body,
    Duration? timeout,
  }) async {
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
        if (attempt >= maxAttempts || !_mayRetry(method, error)) {
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

  /// Verifica se a API está acessível (health check rápido).
  Future<bool> isAvailable() async {
    try {
      final health = await getHealth();
      return health['ok'] == true;
    } catch (_) {
      return false;
    }
  }
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
