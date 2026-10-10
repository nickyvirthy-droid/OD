import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

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
/// sonda TODOS os caminhos publicados do servidor e usa o primeiro que
/// responder, em ordem de preferência (o mais direto primeiro):
///
///   1. **LAN pura** `http://192.168.0.250:8000` — casa, sem Tailscale;
///   2. **Tailnet direto** `http://100.77.67.53:8000` — Tailscale ativo;
///   3. **Funnel** `https://nicky-server.tail1b1f51.ts.net` — internet,
///      TLS, depende do Tailscale estar logado no celular;
///   4. **DDNS/roteador** `http://nicky.theworkpc.com` — internet sem
///      depender do Tailscale (quando a operadora deixa a porta passar).
///
/// O usuário nunca digita URL.
const String odDefaultLanUrl = 'http://192.168.0.250:8000';
const String odDefaultLocalUrl = 'http://100.77.67.53:8000';
const String odDefaultExternalUrl = 'https://nicky-server.tail1b1f51.ts.net';
const String odDefaultRouterUrl = 'http://nicky.theworkpc.com';

/// Ordem de sonda do [OdApi.pickBestUrl]: da rota mais direta (menor
/// latência) para a mais indireta. É a lista COMPLETA de caminhos —
/// qualquer um que responder serve.
const List<String> odDefaultUrls = [
  odDefaultLanUrl,
  odDefaultLocalUrl,
  odDefaultExternalUrl,
  odDefaultRouterUrl,
];

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

  /// A URL ativa é de uma rede local de verdade (LAN/tailnet)? É o rótulo
  /// exibido nas Configurações; a URL em si fica oculta.
  ///
  /// Classifica por HOST, não por esquema: o caminho do DDNS do roteador
  /// (`http://nicky.theworkpc.com`) é http mas é INTERNET; o do Funnel é
  /// https e também é internet. Local = 192.168.x (LAN), 100.x (Tailscale)
  /// e loopback.
  bool get usingLocalUrl {
    final host = Uri.parse(baseUrl).host;
    return host.startsWith('192.168.') ||
        host.startsWith('100.') ||
        host == 'localhost' ||
        host == '127.0.0.1';
  }

  /// Escolhe a melhor URL pela LOCALIZAÇÃO da rede.
  ///
  /// Sonda TODOS os caminhos conhecidos do servidor ([odDefaultUrls] —
  /// LAN, tailnet, Funnel e DDNS do roteador) EM PARALELO e usa o PRIMEIRO
  /// que responder na ordem de preferência (rota mais direta primeiro).
  /// O segundo que responde fica de fallback. A escolha é persistida.
  ///
  /// URLs salvas de uso manual (Avançado) entram na frente da lista —
  /// quem configurou algo à mão tem prioridade — mas NUNCA substituem a
  /// lista: os 4 caminhos padrão continuam sendo sondados.
  ///
  /// Sonda paralela de propósito: o pior caso (nada responde) custa UM
  /// timeout de sonda (~4s), não um por URL.
  ///
  /// Nada alcançável: mantém o último caminho usado (é o que tem mais
  /// chance de voltar a funcionar sozinho quando a rede voltar).
  Future<String> pickBestUrl() async {
    final prefs = await SharedPreferences.getInstance();
    final manual = prefs.getString('od_server_url') ?? '';
    final manualFallback = prefs.getString('od_server_url_fallback') ?? '';
    final ordem = <String>{
      // Prioridade manual (Avançado), sem duplicar os padrões.
      if (manual.trim().isNotEmpty) manual.trim(),
      if (manualFallback.trim().isNotEmpty) manualFallback.trim(),
      ...odDefaultUrls,
    };
    final urls = <String>[...ordem];

    final resultados = await Future.wait([
      for (final url in urls) isReachable(url),
    ]);
    final vivos = <String>[
      for (var i = 0; i < urls.length; i++)
        if (resultados[i]) urls[i],
    ];

    if (vivos.isNotEmpty) {
      baseUrl = vivos.first;
      fallbackUrl = vivos.length > 1 ? vivos[1] : null;
    }
    // Nada vivo: mantém o par atual (pode voltar sozinho).
    if (fallbackUrl == baseUrl) fallbackUrl = null;
    await saveUrls();
    return baseUrl;
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
              serverId: (m['id'] as num?)?.toInt(),
            ))
        .where((m) => m.content.isNotEmpty)
        .toList(growable: false);
  }

  /// Apaga UMA mensagem do histórico da conta (DELETE /history/me/messages/{message_id}).
  ///
  /// Exige sessão de conta (Bearer). Retorna true se a mensagem foi removida.
  /// Lança [OdApiError] com statusCode 404 se a mensagem não existe ou não
  /// pertence ao usuário, 401 se a sessão é inválida.
  Future<bool> deleteHistoryMessage(int messageId) async {
    if (!hasCredential) throw OdApiError('Credencial necessária para apagar mensagem');
    final response = await _send(
      'DELETE',
      Uri.parse('$baseUrl/history/me/messages/$messageId'),
    );
    if (response.statusCode == 200) {
      final data = _tryJson(response.body);
      return data?['ok'] == true;
    } else if (response.statusCode == 401) {
      throw OdAuthError('Sessão inválida ou ausente');
    } else if (response.statusCode == 404) {
      throw OdApiError('Mensagem não encontrada', statusCode: 404);
    } else {
      throw OdApiError(
        'Falha ao apagar mensagem: ${response.statusCode}',
        statusCode: response.statusCode,
      );
    }
  }

  /// Apaga TODA a conversa da conta (DELETE /history/me).
  ///
  /// Exige sessão de conta (Bearer). Retorna o número de mensagens removidas.
  /// Lança [OdApiError] com statusCode 401 se a sessão é inválida.
  Future<int> clearHistory() async {
    if (!hasCredential) throw OdApiError('Credencial necessária para limpar histórico');
    final response = await _send(
      'DELETE',
      Uri.parse('$baseUrl/history/me'),
    );
    if (response.statusCode == 200) {
      final data = _tryJson(response.body);
      return (data?['removed'] as num?)?.toInt() ?? 0;
    } else if (response.statusCode == 401) {
      throw OdAuthError('Sessão inválida ou ausente');
    } else {
      throw OdApiError(
        'Falha ao limpar histórico: ${response.statusCode}',
        statusCode: response.statusCode,
      );
    }
  }

  /// Resolve o id no servidor da mensagem mais recente do usuário com o
  /// mesmo [content] (DELETE /history/me/messages/{id} precisa do id).
  ///
  /// Mensagens escritas nesta sessão ainda não têm serverId: nem o
  /// streaming (frames `done`) nem o POST /message devolvem ids. Em vez de
  /// trocar o protocolo, o apagar pergunta ao histórico no momento do uso —
  /// a última mensagem do USUÁRIO com texto idêntico é a candidata (ordem
  /// cronológica do servidor). Devolve null quando não há candidata (a
  /// chamada decide remover só localmente).
  Future<int?> resolveUserMessageId(String content) async {
    final alvo = content.trim();
    if (alvo.isEmpty || !hasCredential) return null;
    final history = await getHistory(limit: 100);
    for (var i = history.length - 1; i >= 0; i--) {
      final m = history[i];
      if (m.isUser && m.serverId != null && m.content.trim() == alvo) {
        return m.serverId;
      }
    }
    return null;
  }

  // ------------------------------------------------------------------
  // Voz (v1.17.3): transcrição e síntese pelos endpoints da API.
  // Contratos: POST /transcribe {audio_b64} → {ok, text};
  //            POST /tts {text} → {ok, audio_b64, bytes}.
  // ------------------------------------------------------------------

  /// Transcreve áudio gravado (bytes do MediaRecorder, ex.: audio/webm).
  /// Retorna o texto reconhecido; [OdApiError] quando o servidor não
  /// consegue transcrever (501 = STT ausente no servidor; 400 = áudio
  /// inválido; timeout do whisper pode ser longo — 240s, igual ao chat).
  Future<String> transcribe(List<int> audioBytes) async {
    final response = await _send(
      'POST',
      Uri.parse('$baseUrl/transcribe'),
      body: jsonEncode({'audio_b64': base64Encode(audioBytes)}),
      timeout: odChatTimeout,
    );
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      final text = (data['text'] as String?) ?? '';
      if (data['ok'] == true && text.isNotEmpty) return text;
      throw OdApiError(
        'Não entendi o áudio — fale mais perto do microfone.',
        statusCode: response.statusCode,
      );
    } else if (response.statusCode == 401) {
      throw OdAuthError('API key inválida ou ausente');
    } else if (response.statusCode == 501) {
      throw OdApiError(
        'Transcrição indisponível no servidor (STT ausente).',
        statusCode: response.statusCode,
      );
    }
    throw OdApiError(
      'Erro ${response.statusCode} na transcrição.',
      statusCode: response.statusCode,
    );
  }

  /// Sintetiza a resposta em voz (WAV bytes). [OdApiError] quando o TTS
  /// não está disponível (501) ou a síntese falha (502).
  Future<List<int>> synthesize(String text) async {
    final response = await _send(
      'POST',
      Uri.parse('$baseUrl/tts'),
      body: jsonEncode({'text': text}),
      timeout: odRequestTimeout,
    );
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      final b64 = (data['audio_b64'] as String?) ?? '';
      if (data['ok'] == true && b64.isNotEmpty) return base64Decode(b64);
      throw OdApiError('Síntese veio vazia.', statusCode: response.statusCode);
    } else if (response.statusCode == 401) {
      throw OdAuthError('API key inválida ou ausente');
    }
    throw OdApiError(
      'Voz indisponível (erro ${response.statusCode}).',
      statusCode: response.statusCode,
    );
  }

  // ------------------------------------------------------------------
  // Painéis: mesma funcionalidade do /dashboard e /admin do site.
  // ------------------------------------------------------------------

  /// Quem está logado e com qual papel (GET /auth/me).
  ///
  /// Contrato: `{ok, user{id,username,email}, via, role}` — role 'admin' é
  /// o dono (OD_API_KEY ou sessão própria); 'user' é conta comum;
  /// 'anonymous' é conversa sem conta.
  Future<Map<String, dynamic>> getMe() async {
    final response = await _send('GET', Uri.parse('$baseUrl/auth/me'));
    if (response.statusCode != 200) {
      throw OdApiError('auth/me falhou: ${response.statusCode}');
    }
    return jsonDecode(response.body);
  }

  /// GET /dashboard/stats — agregados do orquestrador (histórico, cache,
  /// vector store, métricas). Disponível para qualquer conta logada.
  Future<Map<String, dynamic>> getDashboardStats() async {
    final response = await _send('GET', Uri.parse('$baseUrl/dashboard/stats'));
    if (response.statusCode != 200) {
      throw OdApiError('dashboard/stats falhou: ${response.statusCode}');
    }
    return jsonDecode(response.body);
  }

  /// POST /account/password — troca a PRÓPRIA senha (exige a atual).
  ///
  /// O servidor encerra TODAS as sessões da conta — inclusive a do app que
  /// fez a troca (resposta `sessions_closed`); quem chama deve deslogar
  /// localmente e voltar ao login.
  Future<int> changePassword(String current, String next) async {
    final response = await _send(
      'POST',
      Uri.parse('$baseUrl/account/password'),
      body: jsonEncode({'current_password': current, 'new_password': next}),
    );
    final data = _tryJson(response.body);
    if (response.statusCode == 200 && data?['ok'] == true) {
      return (data?['sessions_closed'] as num?)?.toInt() ?? 0;
    }
    throw OdApiError(
      (data?['error'] as String?) ??
          'Falha ao trocar a senha (${response.statusCode})',
      statusCode: response.statusCode,
    );
  }

  /// POST /account/api-key — rotaciona a PRÓPRIA API key.
  Future<String> rotateApiKey() async {
    final response = await _send(
      'POST',
      Uri.parse('$baseUrl/account/api-key'),
    );
    final data = _tryJson(response.body);
    if (response.statusCode == 200 && data?['ok'] == true) {
      return (data?['api_key'] as String?) ?? '';
    }
    throw OdApiError(
      (data?['error'] as String?) ??
          'Falha ao rotacionar a API key (${response.statusCode})',
      statusCode: response.statusCode,
    );
  }

  /// GET /admin/users — contas + baldes legados (só admin; 403 fora).
  Future<Map<String, dynamic>> getAdminUsers() async {
    final response = await _send('GET', Uri.parse('$baseUrl/admin/users'));
    if (response.statusCode != 200) {
      throw OdApiError(
        'admin/users falhou: ${response.statusCode}',
        statusCode: response.statusCode,
      );
    }
    return jsonDecode(response.body);
  }

  /// POST /admin/users/{username}/password — reset da senha pelo admin
  /// (sem senha atual; mata as sessões da conta). O dono não é alvo (403).
  Future<void> adminResetPassword(String username, String newPassword) async {
    final response = await _send(
      'POST',
      Uri.parse(
        '$baseUrl/admin/users/${Uri.encodeComponent(username)}/password',
      ),
      body: jsonEncode({'new_password': newPassword}),
    );
    final data = _tryJson(response.body);
    if (response.statusCode == 200 && data?['ok'] == true) return;
    throw OdApiError(
      (data?['error'] as String?) ??
          'Falha no reset (${response.statusCode})',
      statusCode: response.statusCode,
    );
  }

  /// DELETE /admin/users/{username} — remove a conta (mantém o histórico).
  /// O dono não é alvo (403 dono_nao_removivel).
  Future<void> adminDeleteUser(String username) async {
    final response = await _send(
      'DELETE',
      Uri.parse('$baseUrl/admin/users/${Uri.encodeComponent(username)}'),
    );
    final data = _tryJson(response.body);
    if (response.statusCode == 200 && data?['ok'] == true) return;
    throw OdApiError(
      (data?['error'] as String?) ??
          'Falha ao remover a conta (${response.statusCode})',
      statusCode: response.statusCode,
    );
  }

  // -- Sessão de desenvolvimento on-demand + caixa (2026-10-08) -------------

  /// POST /admin/dev/sessao — ativa/para a sessão on-demand.
  ///
  /// `ativar` lê a ideia do DONO no `txt.txt` (erro `sem_ideia` se vazio;
  /// `ja_implementado` com `commit`/`ts` no corpo se a ideia já foi
  /// feita — o painel oferece limpar o txt.txt);
  /// `cli` entra só na ativação (auto = cascata Freebuff→OpenCode→Kilo).
  Future<Map<String, dynamic>> adminDevSessao({
    required String acao,
    String cli = 'auto',
  }) async {
    final response = await _send(
      'POST',
      Uri.parse('$baseUrl/admin/dev/sessao'),
      body: jsonEncode(acao == 'ativar'
          ? {'acao': acao, 'cli': cli}
          : {'acao': acao}),
    );
    final data = _tryJson(response.body);
    if (response.statusCode == 200 && data?['ok'] == true) return data!;
    throw OdApiError(
      (data?['error'] as String?) ??
          'Sessão de desenvolvimento falhou (${response.statusCode})',
      statusCode: response.statusCode,
      details: data,
    );
  }

  /// GET /admin/dev/sessao — estado + log + caixa pendente.
  Future<Map<String, dynamic>> getDevSessao() async {
    final response =
        await _send('GET', Uri.parse('$baseUrl/admin/dev/sessao'));
    if (response.statusCode != 200) {
      throw OdApiError(
        'admin/dev/sessao falhou: ${response.statusCode}',
        statusCode: response.statusCode,
      );
    }
    return jsonDecode(response.body);
  }

  /// GET /admin/dev/caixa — mensagens sistema ↔ dono da sessão.
  Future<Map<String, dynamic>> getDevCaixa() async {
    final response = await _send('GET', Uri.parse('$baseUrl/admin/dev/caixa'));
    if (response.statusCode != 200) {
      throw OdApiError(
        'admin/dev/caixa falhou: ${response.statusCode}',
        statusCode: response.statusCode,
      );
    }
    return jsonDecode(response.body);
  }

  /// POST /admin/dev/caixa — resposta/autorização do dono (a sessão retoma).
  Future<Map<String, dynamic>> adminDevCaixaReply(String texto) async {
    final response = await _send(
      'POST',
      Uri.parse('$baseUrl/admin/dev/caixa'),
      body: jsonEncode({'texto': texto}),
    );
    final data = _tryJson(response.body);
    if (response.statusCode == 200 && data?['ok'] == true) return data!;
    throw OdApiError(
      (data?['error'] as String?) ?? 'Falha ao responder a caixa',
      statusCode: response.statusCode,
    );
  }

  /// DELETE /admin/dev/caixa — limpa a caixa (idempotente).
  Future<void> adminDevCaixaClear() async {
    final response =
        await _send('DELETE', Uri.parse('$baseUrl/admin/dev/caixa'));
    final data = _tryJson(response.body);
    if (response.statusCode == 200 && data?['ok'] == true) return;
    throw OdApiError(
      (data?['error'] as String?) ?? 'Falha ao limpar a caixa',
      statusCode: response.statusCode,
    );
  }

  // -- Ideias do dono + limitações (v1.13.0) -------------------------------

  /// GET /admin/ideias — conteúdo do txt.txt (canal de ideias do dono).
  Future<Map<String, dynamic>> getIdeias() async {
    final response = await _send('GET', Uri.parse('$baseUrl/admin/ideias'));
    if (response.statusCode != 200) {
      throw OdApiError(
        'admin/ideias falhou: ${response.statusCode}',
        statusCode: response.statusCode,
      );
    }
    return jsonDecode(response.body);
  }

  /// PUT /admin/ideias — grava o txt.txt (substitui; vazio é válido).
  Future<void> adminWriteIdeias(String conteudo) async {
    final response = await _send(
      'PUT',
      Uri.parse('$baseUrl/admin/ideias'),
      body: jsonEncode({'conteudo': conteudo}),
    );
    final data = _tryJson(response.body);
    if (response.statusCode == 200 && data?['ok'] == true) return;
    throw OdApiError(
      (data?['error'] as String?) ??
          'Falha ao salvar txt.txt (${response.statusCode})',
      statusCode: response.statusCode,
    );
  }

  /// DELETE /admin/ideias — zera o txt.txt (idempotente).
  Future<void> adminClearIdeias() async {
    final response =
        await _send('DELETE', Uri.parse('$baseUrl/admin/ideias'));
    final data = _tryJson(response.body);
    if (response.statusCode == 200 && data?['ok'] == true) return;
    throw OdApiError(
      (data?['error'] as String?) ??
          'Falha ao zerar txt.txt (${response.statusCode})',
      statusCode: response.statusCode,
    );
  }

  /// GET /admin/limitacoes — o que o sistema NÃO soube responder
  /// (registro automático da Casa de Limitações).
  Future<Map<String, dynamic>> getLimitacoes() async {
    final response =
        await _send('GET', Uri.parse('$baseUrl/admin/limitacoes'));
    if (response.statusCode != 200) {
      throw OdApiError(
        'admin/limitacoes falhou: ${response.statusCode}',
        statusCode: response.statusCode,
      );
    }
    return jsonDecode(response.body);
  }

  /// DELETE /admin/limitacoes — limpa o registro de limitações.
  Future<void> adminClearLimitacoes() async {
    final response =
        await _send('DELETE', Uri.parse('$baseUrl/admin/limitacoes'));
    final data = _tryJson(response.body);
    if (response.statusCode == 200 && data?['ok'] == true) return;
    throw OdApiError(
      (data?['error'] as String?) ??
          'Falha ao limpar limitações (${response.statusCode})',
      statusCode: response.statusCode,
    );
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
  /// Se AMBAS falharem, re-sonda TODOS os caminhos padrão — a rede pode
  /// ter trocado em pleno uso (Wi-Fi ↔ dados, Tailscale subiu/caiu) e o
  /// par salvo de URLs ficou velho. Achando outro caminho, promove-o a
  /// primário (a escolha é persistida).
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
    // Nem primária nem fallback: re-sonda os 4 caminhos do sistema.
    final reescolhida = await pickBestUrl();
    try {
      final prev = baseUrl;
      baseUrl = reescolhida;
      final health = await getHealth();
      if (health['ok'] == true) return true;
      baseUrl = prev;
    } catch (_) {
      // Segue falso — nada respondeu em caminho nenhum.
    }
    return false;
  }

  // ------------------------------------------------------------------
  // Registro Mestre de peças (tela "Verificar" — v1.24.0).
  //
  // Mesma API pública do site /site/verificacao.html: qualquer um consulta
  // autenticidade pelo ID gravado na peça; a sala de bate-papo da peça é
  // leitura pública e escrita com conta (username assina, nome real nunca).
  // ------------------------------------------------------------------

  /// GET /registry/{codigo} — consulta pública de autenticidade.
  ///
  /// Busca tolerante a hífens/espaços (o servidor normaliza). Lança
  /// [OdApiError] com statusCode 404 quando o código não consta.
  Future<OdRegistryItem> verifyPiece(String codigo) async {
    final response = await _send(
      'GET',
      Uri.parse('$baseUrl/registry/${Uri.encodeComponent(codigo.trim())}'),
    );
    final data = _tryJson(response.body);
    if (response.statusCode == 200 && data?['ok'] == true) {
      return OdRegistryItem.fromJson(data!['peca'] as Map<String, dynamic>);
    }
    if (response.statusCode == 404) {
      throw OdApiError('Código não consta no Registro Mestre', statusCode: 404);
    }
    throw OdApiError(
      'Verificação falhou: ${data?['error'] ?? response.statusCode}',
      statusCode: response.statusCode,
    );
  }

  /// GET /registry/{codigo}/photo — foto pública da peça em bytes.
  /// Null quando a peça não tem foto (404) — nunca é erro.
  Future<Uint8List?> registryPhoto(String codigo) async {
    final response = await _send(
      'GET',
      Uri.parse(
        '$baseUrl/registry/${Uri.encodeComponent(codigo.trim())}/photo',
      ),
    );
    if (response.statusCode == 200 && response.bodyBytes.isNotEmpty) {
      return response.bodyBytes;
    }
    return null;
  }

  /// GET /registry/{codigo}/chat — mensagens da sala (?since= para polling).
  Future<List<OdRegistryMessage>> registryChat(
    String codigo, {
    int since = 0,
  }) async {
    final response = await _send(
      'GET',
      Uri.parse(
        '$baseUrl/registry/${Uri.encodeComponent(codigo.trim())}'
        '/chat?since=$since',
      ),
    );
    final data = _tryJson(response.body);
    if (response.statusCode != 200 || data?['ok'] != true) {
      throw OdApiError('Sala da peça indisponível', statusCode: response.statusCode);
    }
    return ((data!['mensagens'] as List?) ?? [])
        .map((m) => OdRegistryMessage.fromJson(m as Map<String, dynamic>))
        .toList();
  }

  /// POST /registry/{codigo}/chat — publica na sala (conta obrigatória;
  /// o servidor responde 401 sem credencial).
  Future<OdRegistryMessage> registryChatPost(
    String codigo,
    String text,
  ) async {
    final response = await _send(
      'POST',
      Uri.parse(
        '$baseUrl/registry/${Uri.encodeComponent(codigo.trim())}/chat',
      ),
      body: jsonEncode({'text': text}),
    );
    final data = _tryJson(response.body);
    if (response.statusCode == 201 && data?['ok'] == true) {
      return OdRegistryMessage.fromJson(
        data!['mensagem'] as Map<String, dynamic>,
      );
    }
    if (response.statusCode == 401) {
      throw OdApiError(
        'Entre com sua conta para conversar na sala da peça',
        statusCode: 401,
      );
    }
    throw OdApiError(
      'Envio falhou: ${data?['error'] ?? response.statusCode}',
      statusCode: response.statusCode,
    );
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

  /// ID da mensagem no servidor (PK do banco).
  final int? serverId;

  OdHistoryMessage({
    required this.role,
    required this.content,
    double? ts,
    this.answeredBy = '',
    this.serverId,
  }) : timestamp = ts == null
            ? DateTime.now()
            : DateTime.fromMillisecondsSinceEpoch((ts * 1000).round());

  bool get isUser => role == 'user';
}

/// Peça do Registro Mestre (projeção PÚBLICA de GET /registry/{codigo}).
///
/// Preço e notas internas NUNCA chegam aqui — o servidor não os envia.
class OdRegistryItem {
  final String publicId;
  final String? engravedCode;
  final String name;
  final String? collection;
  final String kind;    // 'exclusiva' | 'publica'
  final String status;  // 'estoque' | 'vendida' | 'registrada'
  final String? ownerUsername;  // só quando status == 'registrada'
  final bool registered;
  final String? photoUrl;       // /registry/{id}/photo quando existe

  OdRegistryItem({
    required this.publicId,
    required this.engravedCode,
    required this.name,
    required this.collection,
    required this.kind,
    required this.status,
    required this.ownerUsername,
    required this.registered,
    required this.photoUrl,
  });

  factory OdRegistryItem.fromJson(Map<String, dynamic> json) {
    return OdRegistryItem(
      publicId: (json['public_id'] as String?) ?? '',
      engravedCode: json['engraved_code'] as String?,
      name: (json['name'] as String?) ?? '',
      collection: json['collection'] as String?,
      kind: (json['kind'] as String?) ?? 'exclusiva',
      status: (json['status'] as String?) ?? 'estoque',
      ownerUsername: json['owner_username'] as String?,
      registered: json['registered'] == true,
      photoUrl: json['photo'] as String?,
    );
  }

  /// Selo para a tela: (texto, éAlerta) — ambar para "vendida" (aguardando
  /// registro), verde para estoque/registrada.
  (String, bool) get selo => switch (status) {
        'vendida' => ('Peça autêntica · vendida', true),
        'registrada' => ('Peça autêntica · registrada', false),
        _ => ('Peça autêntica', false),
      };

  String get statusLabel => switch (status) {
        'vendida' => 'Vendida',
        'registrada' => 'Registrada',
        _ => 'Em estoque',
      };
}

/// Mensagem da sala de bate-papo de uma peça (registry_chat).
class OdRegistryMessage {
  final int id;
  final String username;
  final String text;
  final DateTime createdAt;

  OdRegistryMessage({
    required this.id,
    required this.username,
    required this.text,
    required this.createdAt,
  });

  factory OdRegistryMessage.fromJson(Map<String, dynamic> json) {
    final ts = (json['created_at'] as num?)?.toDouble() ?? 0;
    return OdRegistryMessage(
      id: (json['id'] as num?)?.toInt() ?? 0,
      username: (json['username'] as String?) ?? '?',
      text: (json['text'] as String?) ?? '',
      createdAt: ts <= 0
          ? DateTime.now()
          : DateTime.fromMillisecondsSinceEpoch((ts * 1000).round()),
    );
  }
}

class OdApiError implements Exception {
  final String message;
  final int? statusCode;

  /// Corpo do erro do servidor (quando existe) — ex.: `ja_implementado`
  /// vem com `commit`/`ts` para o painel montar o aviso de limpeza.
  final Map<String, dynamic>? details;

  OdApiError(this.message, {this.statusCode, this.details});
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
