import 'package:flutter/material.dart';
import '../services/od_api.dart';

/// Tela de status do OmegaDrakon (health + capabilities).
class StatusScreen extends StatefulWidget {
  final OdApi api;
  const StatusScreen({super.key, required this.api});

  @override
  State<StatusScreen> createState() => _StatusScreenState();
}

class _StatusScreenState extends State<StatusScreen> {
  Map<String, dynamic>? _health;
  Map<String, dynamic>? _capabilities;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    setState(() => _loading = true);
    try {
      final health = await widget.api.getHealth();
      final caps = await widget.api.getCapabilities();
      setState(() {
        _health = health;
        _capabilities = caps;
        _loading = false;
      });
    } catch (e) {
      setState(() {
        _health = {'ok': false, 'error': e.toString()};
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }

    return RefreshIndicator(
      onRefresh: _refresh,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // Status geral
          _buildHealthCard(),
          const SizedBox(height: 16),
          // Checks
          _buildChecksCard(),
          const SizedBox(height: 16),
          // Info do sistema
          _buildSystemInfo(),
        ],
      ),
    );
  }

  Widget _buildHealthCard() {
    final ok = _health?['ok'] == true;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(
          children: [
            Icon(
              ok ? Icons.check_circle : Icons.error,
              color: ok ? Colors.green : Colors.red,
              size: 48,
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    ok ? 'OmegaDrakon Online' : 'OmegaDrakon Offline',
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                  Text(
                    'Status: ${_health?['status'] ?? 'desconhecido'}',
                    style: Theme.of(context).textTheme.bodyMedium,
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildChecksCard() {
    final checks = _health?['checks'] as Map<String, dynamic>? ?? {};
    if (checks.isEmpty) return const SizedBox.shrink();

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Checks (${checks.length})',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const Divider(),
            ...checks.entries.map((entry) {
              final check = entry.value as Map<String, dynamic>;
              final ok = check['ok'] == true;
              return ListTile(
                dense: true,
                leading: Icon(
                  ok ? Icons.check : Icons.close,
                  color: ok ? Colors.green : Colors.red,
                  size: 20,
                ),
                title: Text(entry.key),
                subtitle: Text(check['detail'] ?? check['status'] ?? ''),
              );
            }),
          ],
        ),
      ),
    );
  }

  Widget _buildSystemInfo() {
    final info = _capabilities?['system'] as Map<String, dynamic>?;
    if (info == null) return const SizedBox.shrink();

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Sistema',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const Divider(),
            _infoRow('Versão', info['version'] ?? '?'),
            _infoRow('Runtime', info['runtime'] ?? '?'),
            _infoRow('Agentes', '${info['agents'] ?? '?'} perfis'),
            _infoRow('Actions', '${info['actions'] ?? '?'}'),
          ],
        ),
      ),
    );
  }

  Widget _infoRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(color: Colors.grey)),
          Text(value, style: const TextStyle(fontWeight: FontWeight.bold)),
        ],
      ),
    );
  }
}
