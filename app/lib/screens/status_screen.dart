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
  Map<String, dynamic>? _supervision;
  bool _supervisionFailed = false;
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
    await _loadSupervision();
  }

  /// Supervisão dos loops é BEST-EFFORT: um erro aqui não pode derrubar a aba
  /// Status inteira (a mesma lição do bug do `system` aninhado no APK 1.2.0).
  Future<void> _loadSupervision() async {
    try {
      final supervision = await widget.api.getSupervision();
      if (!mounted) return;
      setState(() {
        _supervision = supervision;
        _supervisionFailed = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _supervision = null;
        _supervisionFailed = true;
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
          // Supervisão dos loops do núcleo
          _buildSupervisionCard(),
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

  /// Card "Supervisão dos loops" — lê GET /supervision.
  ///
  /// Cada loop do núcleo (API, Telegram, recovery, MQTT, presença, visão) roda
  /// no MESMO processo e é isolado pelo launcher: uma falha é CONTIDA e o loop
  /// reiniciado, no lugar de derrubar o core — antes de 2026-09-15 um timeout
  /// de rede do Telegram derrubou o processo inteiro 89 vezes. O card mostra
  /// esse rastro: `degraded` quer dizer "caiu nos últimos `window_s` segundos"
  /// e volta a ok sozinho depois da janela.
  ///
  /// Sem cast (só `is` + fallback): o formato do endpoint pode evoluir sem
  /// quebrar a tela.
  Widget _buildSupervisionCard() {
    if (_supervisionFailed) {
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              const Icon(Icons.help_outline, color: Colors.grey, size: 20),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  'Supervisão dos loops indisponível '
                  '(servidor sem a rota /supervision?)',
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
              ),
            ],
          ),
        ),
      );
    }
    final supervision = _supervision;
    if (supervision == null) return const SizedBox.shrink();

    final loops = supervision['loops'];
    final list = loops is List ? loops : const [];
    final degradados = supervision['degraded'];
    final nDegradados = degradados is List ? degradados.length : 0;
    final janela = supervision['window_s'];
    final restarts = supervision['restarts'];

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Supervisão dos loops',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const Divider(),
            _infoRow(
              'Estado',
              nDegradados == 0
                  ? 'Todos de pé'
                  : '$nDegradados reiniciado(s)',
            ),
            _infoRow(
              'Janela',
              janela is num ? '${janela.toInt()} s' : '?',
            ),
            _infoRow('Reinícios', restarts == null ? '0' : '$restarts'),
            if (list.isEmpty)
              const Padding(
                padding: EdgeInsets.only(top: 8),
                child: Text('Nenhum loop reiniciado desde o boot'),
              )
            else
              ...list.map(_loopTile),
          ],
        ),
      ),
    );
  }

  /// Linha de um loop supervisionado (nome + reinícios + último erro).
  Widget _loopTile(dynamic raw) {
    if (raw is! Map) return const SizedBox.shrink();
    final name = '${raw['name'] ?? '?'}';
    final degraded = raw['degraded'] == true;
    final restarts = raw['restarts'] ?? 0;
    final kind = raw['last_kind'];
    final age = raw['age_s'];

    final detalhe = StringBuffer('$restarts reinício(s)');
    if (kind != null && '$kind'.isNotEmpty) {
      detalhe.write(' • último: $kind');
    }
    if (age is num) detalhe.write(' • há ${age.toInt()}s');

    return ListTile(
      dense: true,
      leading: Icon(
        degraded ? Icons.warning_amber : Icons.check,
        color: degraded ? Colors.orange : Colors.green,
        size: 20,
      ),
      title: Text(name),
      subtitle: Text(detalhe.toString()),
    );
  }

  /// Card "Sistema" — lê o manifesto REAL de GET /capabilities.
  ///
  /// O manifesto é plano: `version` no topo, contagens em `counts`
  /// (`capabilities`, `actions`) e modos de runtime em `runtime.modes`.
  /// Importante: `system` é o NOME do sistema (string), NÃO um objeto —
  /// ler com `as Map<String, dynamic>?` estourava
  /// `type 'String' is not a subtype of type 'Map<String, dynamic>?'` e
  /// derrubava a aba Status inteira. Por isso aqui só se usa `is` + fallback
  /// '?', nunca cast: o card não pode quebrar a tela se o manifesto mudar.
  Widget _buildSystemInfo() {
    final caps = _capabilities;
    if (caps == null || caps.isEmpty) return const SizedBox.shrink();

    final counts = caps['counts'];
    final runtime = caps['runtime'];
    final modes = runtime is Map ? runtime['modes'] : null;
    final capabilities = counts is Map ? counts['capabilities'] : null;
    final actions = counts is Map ? counts['actions'] : null;

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
            _infoRow('Versão', '${caps['version'] ?? '?'}'),
            _infoRow(
              'Runtime',
              modes is List && modes.isNotEmpty ? '${modes.length} modos' : '?',
            ),
            _infoRow(
              'Capacidades',
              capabilities == null ? '?' : '$capabilities',
            ),
            _infoRow('Actions', actions == null ? '?' : '$actions'),
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
