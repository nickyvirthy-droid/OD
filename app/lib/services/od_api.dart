import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

/// Cliente da API REST do OmegaDrakon.
///
/// Uso:
///   final api = OdApi(baseUrl: 'http://100.77.67.53:8000');
///   await api.setApiKey('minha-chave');
///   final resp = await api.sendMessage('Olá!');
class OdApi {
  final String baseUrl;
  String _apiKey = '';

  OdApi({required this.baseUrl});

  /// API key para autenticação X-API-Key.
  String get apiKey => _apiKey;

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

  /// Envia uma mensagem e retorna a resposta do assistente.
  Future<String> sendMessage(String message, {String profile = 'auto'}) async {
    final response = await http.post(
      Uri.parse('$baseUrl/message'),
      headers: _headers,
      body: jsonEncode({
        'message': message,
        'profile': profile,
      }),
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      return data['response'] ?? data['message'] ?? 'Sem resposta';
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
    final response = await http.get(
      Uri.parse('$baseUrl/health'),
      headers: _headers,
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    }
    throw OdApiError('Health check falhou: ${response.statusCode}');
  }

  /// Retorna as capacidades do sistema.
  Future<Map<String, dynamic>> getCapabilities() async {
    final response = await http.get(
      Uri.parse('$baseUrl/capabilities'),
      headers: _headers,
    );

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
    }
    throw OdApiError('Capabilities falhou: ${response.statusCode}');
  }

  /// Lista as ações disponíveis.
  Future<List<Map<String, dynamic>>> getActions() async {
    final caps = await getCapabilities();
    final actions = caps['actions'] ?? [];
    return List<Map<String, dynamic>>.from(actions);
  }

  /// Executa uma ação específica.
  Future<String> executeAction(String actionName,
      {Map<String, dynamic>? params}) async {
    final response = await http.post(
      Uri.parse('$baseUrl/executa'),
      headers: _headers,
      body: jsonEncode({
        'action': actionName,
        if (params != null) 'params': params,
      }),
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      return data['result'] ?? data['response'] ?? 'Ação executada';
    }
    throw OdApiError('Ação falhou: ${response.statusCode}');
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
