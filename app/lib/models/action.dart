/// Ação disponível no OmegaDrakon (GET /actions — ActionRegistry).
class OdAction {
  final String name;
  final String description;
  final String category;
  final String permission;
  final String risk; // 'low' | 'medium' | 'high'
  final Map<String, dynamic> params;

  OdAction({
    required this.name,
    required this.description,
    this.category = '',
    this.permission = '',
    this.risk = 'low',
    this.params = const {},
  });

  factory OdAction.fromJson(Map<String, dynamic> json) {
    final rawParams = json['params'];
    return OdAction(
      name: json['name'] ?? json['action'] ?? '',
      description: json['description'] ?? '',
      category: json['category'] ?? '',
      permission: json['permission'] ?? '',
      risk: json['risk'] ?? 'low',
      params: rawParams is Map<String, dynamic>
          ? rawParams
          : const {},
    );
  }

  /// Ícone baseado no risco (nível de interferência no sistema).
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
