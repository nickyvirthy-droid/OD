/// Mensagem de conversa com o OmegaDrakon.
class OdMessage {
  final String role; // 'user' | 'assistant'
  final String content;
  final DateTime timestamp;

  OdMessage({
    required this.role,
    required this.content,
    DateTime? timestamp,
  }) : timestamp = timestamp ?? DateTime.now();

  bool get isUser => role == 'user';
  bool get isAssistant => role == 'assistant';
}
