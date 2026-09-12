import 'package:flutter_test/flutter_test.dart';
import 'package:omegadrakon/models/action.dart';
import 'package:omegadrakon/models/message.dart';

void main() {
  group('OdAction', () {
    test('fromJson mapeia todos os campos', () {
      final action = OdAction.fromJson({
        'name': 'system_info',
        'description': 'Info do sistema',
        'category': 'system',
        'permission': 'read',
        'risk': 'low',
        'params': {
          'required': ['verbose'],
          'properties': {
            'verbose': {'type': 'bool'},
          },
        },
      });

      expect(action.name, 'system_info');
      expect(action.description, 'Info do sistema');
      expect(action.category, 'system');
      expect(action.permission, 'read');
      expect(action.risk, 'low');
      expect(action.params, isA<Map<String, dynamic>>());
      expect(action.params.containsKey('properties'), isTrue);
    });

    test('fromJson aceita chave "action" e preenche padrões', () {
      final action = OdAction.fromJson({
        'action': 'ping',
        'description': 'Ping',
      });

      expect(action.name, 'ping');
      expect(action.permission, '');
      expect(action.risk, 'low');
      expect(action.params, isEmpty);
    });

    test('riskIcon reflete o nível de risco', () {
      expect(OdAction.fromJson({'risk': 'high'}).riskIcon, '🔴');
      expect(OdAction.fromJson({'risk': 'medium'}).riskIcon, '🟡');
      expect(OdAction.fromJson({'risk': 'low'}).riskIcon, '🟢');
      expect(OdAction.fromJson({}).riskIcon, '🟢');
    });
  });

  group('OdMessage', () {
    test('isUser e isAssistant por role', () {
      final user = OdMessage(role: 'user', content: 'oi');
      final assistant = OdMessage(role: 'assistant', content: 'olá');

      expect(user.isUser, isTrue);
      expect(user.isAssistant, isFalse);
      expect(assistant.isAssistant, isTrue);
      expect(assistant.isUser, isFalse);
    });

    test('timestamp assume o momento atual quando omitido', () {
      final message = OdMessage(role: 'user', content: 'oi');
      final agora = DateTime.now();
      expect(
        message.timestamp.difference(agora).inSeconds.abs(),
        lessThan(5),
      );
    });
  });
}