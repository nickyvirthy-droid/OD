/// Mensagem de conversa com o OmegaDrakon.
class OdMessage {
  final String role; // 'user' | 'assistant'
  final String content;
  final DateTime timestamp;

  /// QUEM/mo respondeu — label curto exibido na bolha:
  /// 'Nicky Virthy', 'Regulus', 'cache', 'fastpath:math'...
  /// Vazio nas mensagens antigas do histórico (o servidor só expõe agora)
  /// e nas do usuário.
  final String answeredBy;

  /// Rota da resposta: 'llm' | 'cache' | 'datetime' | 'quick_response' |
  /// 'action_intent'. Vazio quando desconhecido (histórico antigo).
  final String route;

  /// ID da mensagem no servidor (quando carregada do histórico).
  /// Usado para apagar a mensagem no servidor via DELETE /history/me/messages/{id}.
  final int? serverId;

  OdMessage({
    required this.role,
    required this.content,
    DateTime? timestamp,
    this.answeredBy = '',
    this.route = '',
    this.serverId,
  }) : timestamp = timestamp ?? DateTime.now();

  bool get isUser => role == 'user';
  bool get isAssistant => role == 'assistant';

  /// Se a mensagem pode ser apagada no servidor (tem serverId e é do usuário).
  bool get canDeleteOnServer => isUser && serverId != null;

  /// Label do "quem respondeu" já em linguagem de gente:
  /// cache → "cache (resposta anterior)"; fastpath:X → "ação: X".
  String get answeredByLabel {
    if (answeredBy.isEmpty) return '';
    if (answeredBy == 'cache') return 'cache';
    if (answeredBy.startsWith('fastpath:')) {
      return 'ação: ${answeredBy.substring('fastpath:'.length)}';
    }
    return answeredBy;
  }

  OdMessage copyWith({
    String? content,
    String? answeredBy,
    String? route,
    int? serverId,
  }) =>
      OdMessage(
        role: role,
        content: content ?? this.content,
        timestamp: timestamp,
        answeredBy: answeredBy ?? this.answeredBy,
        route: route ?? this.route,
        serverId: serverId ?? this.serverId,
      );
}
