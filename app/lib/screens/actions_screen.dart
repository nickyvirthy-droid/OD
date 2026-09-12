import 'package:flutter/material.dart';
import '../models/action.dart';
import '../services/od_api.dart';

/// Tela do catálogo de ações do OmegaDrakon (GET /actions — ActionRegistry).
class ActionsScreen extends StatefulWidget {
  final OdApi api;
  const ActionsScreen({super.key, required this.api});

  @override
  State<ActionsScreen> createState() => _ActionsScreenState();
}

class _ActionsScreenState extends State<ActionsScreen> {
  List<OdAction> _actions = [];
  bool _loading = true;
  String? _error;
  String _search = '';

  @override
  void initState() {
    super.initState();
    _loadActions();
  }

  Future<void> _loadActions() async {
    try {
      final actions = await widget.api.getActions();
      setState(() {
        _actions = actions.map((a) => OdAction.fromJson(a)).toList()
          ..sort((a, b) => a.name.compareTo(b.name));
        _loading = false;
      });
    } catch (e) {
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  List<OdAction> get _filtered {
    if (_search.isEmpty) return _actions;
    return _actions
        .where((a) =>
            a.name.toLowerCase().contains(_search.toLowerCase()) ||
            a.description.toLowerCase().contains(_search.toLowerCase()))
        .toList();
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }

    if (_error != null) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.error_outline, size: 48, color: Colors.red),
            const SizedBox(height: 16),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 24),
              child: Text(
                'Erro: $_error',
                textAlign: TextAlign.center,
              ),
            ),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: () {
                setState(() {
                  _loading = true;
                  _error = null;
                });
                _loadActions();
              },
              child: const Text('Tentar novamente'),
            ),
          ],
        ),
      );
    }

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.all(8),
          child: TextField(
            decoration: const InputDecoration(
              hintText: 'Buscar ações...',
              prefixIcon: Icon(Icons.search),
              border: OutlineInputBorder(),
            ),
            onChanged: (v) => setState(() => _search = v),
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Row(
            children: [
              Text(
                '${_filtered.length} ações',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ],
          ),
        ),
        Expanded(
          child: ListView.builder(
            padding: const EdgeInsets.all(8),
            itemCount: _filtered.length,
            itemBuilder: (context, index) {
              final action = _filtered[index];
              return Card(
                margin: const EdgeInsets.symmetric(vertical: 4),
                child: ListTile(
                  leading: Text(
                    action.riskIcon,
                    style: const TextStyle(fontSize: 24),
                  ),
                  title: Text(
                    action.name,
                    style: const TextStyle(fontWeight: FontWeight.bold),
                  ),
                  subtitle: Text(
                    action.description,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                  ),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => _openActionDialog(action),
                ),
              );
            },
          ),
        ),
      ],
    );
  }

  /// Campos do schema de params: {required: [...], properties: {...}} ou
  /// formato plano {campo: {type, required, default}}.
  List<MapEntry<String, Map<String, dynamic>>> _paramFields(OdAction action) {
    final schema = action.params;
    if (schema.isEmpty) {
      return const <MapEntry<String, Map<String, dynamic>>>[];
    }
    final props = schema.containsKey('properties')
        ? Map<String, dynamic>.from(schema['properties'] as Map)
        : Map<String, dynamic>.from(schema);
    return props.entries.map((e) {
      final spec = e.value is Map
          ? Map<String, dynamic>.from(e.value as Map)
          : <String, dynamic>{};
      return MapEntry<String, Map<String, dynamic>>(e.key, spec);
    }).toList();
  }

  void _openActionDialog(OdAction action) {
    final fields = _paramFields(action);
    if (fields.isEmpty && action.risk != 'high') {
      _executeAction(action, {});
      return;
    }
    showDialog(
      context: context,
      builder: (dialogContext) => _ActionDialog(
        action: action,
        fields: fields,
        onExecute: (params, confirm) =>
            _executeAction(action, params, confirm: confirm),
      ),
    );
  }

  Future<void> _executeAction(
    OdAction action,
    Map<String, dynamic> params, {
    bool confirm = false,
  }) async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      final result = await widget.api.executeAction(
        action.name,
        params: params,
        confirm: confirm,
      );
      messenger.showSnackBar(
        SnackBar(
          content: Text(result),
          behavior: SnackBarBehavior.floating,
          duration: const Duration(seconds: 6),
        ),
      );
    } catch (e) {
      messenger.showSnackBar(
        SnackBar(
          content: Text('Erro: $e'),
          backgroundColor: Colors.red,
          behavior: SnackBarBehavior.floating,
          duration: const Duration(seconds: 6),
        ),
      );
    }
  }
}

/// Diálogo de execução: formulário de params (a partir do schema) + aviso
/// e confirmação explícita para ações destrutivas (risk high).
class _ActionDialog extends StatefulWidget {
  final OdAction action;
  final List<MapEntry<String, Map<String, dynamic>>> fields;
  final void Function(Map<String, dynamic> params, bool confirm) onExecute;

  const _ActionDialog({
    required this.action,
    required this.fields,
    required this.onExecute,
  });

  @override
  State<_ActionDialog> createState() => _ActionDialogState();
}

class _ActionDialogState extends State<_ActionDialog> {
  final _controllers = <String, TextEditingController>{};
  bool _confirmChecked = false;

  bool _isRequired(Map<String, dynamic> field) =>
      field['required'] == true || field['required'] == 'True';

  String? _cast(String name, String raw, String type) {
    final value = raw.trim();
    switch (type) {
      case 'int':
        return int.tryParse(value)?.toString() ??
            (value.isEmpty ? null : '__tipo inválido: int esperado');
      case 'float':
        return double.tryParse(value)?.toString() ??
            (value.isEmpty ? null : '__tipo inválido: float esperado');
      case 'bool':
        if (value.isEmpty) return null;
        final lowered = value.toLowerCase();
        if (lowered == 'true' || lowered == '1' || lowered == 'yes') {
          return 'True';
        }
        if (lowered == 'false' || lowered == '0' || lowered == 'no') {
          return 'False';
        }
        return '__tipo inválido: bool esperado (true/false)';
      default:
        return value.isEmpty ? null : value;
    }
  }

  @override
  void dispose() {
    for (final c in _controllers.values) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final action = widget.action;
    final destructive = action.risk == 'high';
    return AlertDialog(
      title: Text('${action.riskIcon} ${action.name}'),
      content: SizedBox(
        width: double.maxFinite,
        child: ListView(
          shrinkWrap: true,
          children: [
            Text(action.description),
            if (action.category.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(
                'Categoria: ${action.category}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ],
            if (widget.fields.isNotEmpty) ...[
              const SizedBox(height: 12),
              ...widget.fields.map(_buildField),
            ],
            if (destructive) ...[
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: Colors.red.withValues(alpha: 0.08),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: Colors.red.withValues(alpha: 0.4)),
                ),
                child: CheckboxListTile(
                  contentPadding: EdgeInsets.zero,
                  dense: true,
                  controlAffinity: ListTileControlAffinity.leading,
                  title: const Text(
                    'Ação destrutiva — confirmo a execução',
                    style: TextStyle(fontWeight: FontWeight.bold),
                  ),
                  value: _confirmChecked,
                  onChanged: (v) =>
                      setState(() => _confirmChecked = v ?? false),
                ),
              ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancelar'),
        ),
        FilledButton(
          onPressed: destructive && !_confirmChecked ? null : _submit,
          child: const Text('Executar'),
        ),
      ],
    );
  }

  Widget _buildField(MapEntry<String, Map<String, dynamic>> entry) {
    final name = entry.key;
    final spec = entry.value;
    final controller =
        _controllers.putIfAbsent(name, () => TextEditingController());
    final hint = <String>[
      if (spec['type'] != null) 'tipo: ${spec['type']}',
      if (spec['default'] != null) 'default: ${spec['default']}',
    ].join(' · ');
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: TextField(
        controller: controller,
        decoration: InputDecoration(
          labelText: _isRequired(spec) ? '$name *' : name,
          hintText: hint.isEmpty ? null : hint,
          border: const OutlineInputBorder(),
          isDense: true,
        ),
      ),
    );
  }

  void _submit() {
    final params = <String, dynamic>{};
    for (final entry in widget.fields) {
      final raw = _controllers[entry.key]?.text ?? '';
      final type = (entry.value['type'] ?? 'str').toString();
      final casted = _cast(entry.key, raw, type);
      if (casted == null) continue;
      if (casted.startsWith('__')) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(casted.replaceFirst('__', '')),
            backgroundColor: Colors.orange,
          ),
        );
        return;
      }
      // Converte de volta para o tipo do schema.
      switch (type) {
        case 'int':
          params[entry.key] = int.parse(casted);
        case 'float':
          params[entry.key] = double.parse(casted);
        case 'bool':
          params[entry.key] = casted == 'True';
        default:
          params[entry.key] = casted;
      }
    }
    Navigator.pop(context);
    widget.onExecute(params, true);
  }
}
