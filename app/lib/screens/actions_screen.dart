import 'package:flutter/material.dart';
import '../models/action.dart';
import '../services/od_api.dart';

/// Tela do catálogo de ações do OmegaDrakon.
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
        _actions = actions.map((a) => OdAction.fromJson(a)).toList();
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
            Text('Erro: $_error'),
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
                  leading: Text(action.riskIcon, style: const TextStyle(fontSize: 24)),
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
                  onTap: () => _executeAction(action),
                ),
              );
            },
          ),
        ),
      ],
    );
  }

  void _executeAction(OdAction action) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Executar: ${action.name}'),
        content: Text(action.description),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () async {
              Navigator.pop(context);
              try {
                final result = await widget.api.executeAction(action.name);
                if (mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      content: Text(result),
                      behavior: SnackBarBehavior.floating,
                    ),
                  );
                }
              } catch (e) {
                if (mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      content: Text('Erro: $e'),
                      backgroundColor: Colors.red,
                    ),
                  );
                }
              }
            },
            child: const Text('Executar'),
          ),
        ],
      ),
    );
  }
}
