/// Ação disponível no OmegaDrakon.
class OdAction {
  final String name;
  final String description;
  final String permission;
  final String risk; // 'low' | 'medium' | 'high'
  final List<String> params;

  OdAction({
    required this.name,
    required this.description,
    this.permission = '',
    this.risk = 'low',
    this.params = const [],
  });

  factory OdAction.fromJson(Map<String, dynamic> json) {
    return OdAction(
      name: json['name'] ?? json['action'] ?? '',
      description: json['description'] ?? '',
      permission: json['permission'] ?? '',
      risk: json['risk'] ?? 'low',
      params: List<String>.from(json['params'] ?? []),
    );
  }

  /// Ícone baseado no risco.
  String get riskIcon {
    switch (risk) {
      case 'high':
        return '🔴';
      case 'medium':
        return '🟡';
      default:
        return '🟢';
    }
  }
}
