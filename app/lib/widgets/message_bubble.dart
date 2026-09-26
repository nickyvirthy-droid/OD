import 'package:flutter/material.dart';
import '../models/message.dart';

/// Bolha de mensagem no chat — com HORA e QUEM respondeu.
///
/// Assistente: cabeçalho com o nome de quem respondeu (Nicky Virthy,
/// Regulus, Nyx... ou 'cache'/'ação: X') e a hora à direita. Usuário:
/// só a hora, discreta.
class MessageBubble extends StatelessWidget {
  final OdMessage message;

  const MessageBubble({super.key, required this.message});

  static String _hhmm(DateTime ts) =>
      '${ts.hour.toString().padLeft(2, '0')}:${ts.minute.toString().padLeft(2, '0')}';

  /// Ícone pelo tipo de resposta — é a leitura rápida de "quem falou".
  static IconData _iconFor(OdMessage m) {
    final who = m.answeredBy.toLowerCase();
    if (m.route == 'cache' || who == 'cache') return Icons.history_toggle_off;
    if (who.startsWith('ação:')) return Icons.bolt;
    if (who.contains('nyx')) return Icons.dark_mode_outlined;
    if (who.contains('regulus')) return Icons.balance;
    if (who.contains('luma')) return Icons.auto_awesome;
    if (who.contains('vox')) return Icons.mic;
    if (who.contains('athenae')) return Icons.account_balance;
    if (who.contains('nexus')) return Icons.hub;
    return Icons.smart_toy_outlined;
  }

  @override
  Widget build(BuildContext context) {
    final isUser = message.isUser;
    final colorScheme = Theme.of(context).colorScheme;

    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: EdgeInsets.only(
          left: isUser ? 64 : 0,
          right: isUser ? 0 : 64,
          bottom: 8,
        ),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        decoration: BoxDecoration(
          color: isUser
              ? colorScheme.primaryContainer
              : colorScheme.surfaceContainerHighest,
          borderRadius: BorderRadius.only(
            topLeft: const Radius.circular(16),
            topRight: const Radius.circular(16),
            bottomLeft: Radius.circular(isUser ? 16 : 4),
            bottomRight: Radius.circular(isUser ? 4 : 16),
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (!isUser) ...[
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    _iconFor(message),
                    size: 12,
                    color: colorScheme.primary,
                  ),
                  const SizedBox(width: 4),
                  Flexible(
                    child: Text(
                      message.answeredByLabel.isEmpty
                          ? '🐉 OD'
                          : message.answeredByLabel,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.bold,
                        color: colorScheme.primary,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 2),
            ],
            Text(
              message.content,
              style: TextStyle(
                color: isUser
                    ? colorScheme.onPrimaryContainer
                    : colorScheme.onSurface,
              ),
            ),
            const SizedBox(height: 2),
            Align(
              alignment: Alignment.centerRight,
              child: Text(
                _hhmm(message.timestamp),
                style: TextStyle(
                  fontSize: 10,
                  color: (isUser
                          ? colorScheme.onPrimaryContainer
                          : colorScheme.onSurface)
                      .withValues(alpha: 0.45),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
