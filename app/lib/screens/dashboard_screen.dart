import 'dart:convert';

import 'package:flutter/material.dart';
import '../services/od_api.dart';

/// Tela "Painel" — mesmas funcionalidades do /dashboard e /admin do site:
///
/// - Qualquer conta logada: stats gerais (/dashboard/stats), troca da
///   própria senha (/account/password) e rotação da própria API key
///   (/account/api-key).
/// - Só o dono/admin: gestão de contas (/admin/users) — reset de senha e
///   remoção de conta — e baldes legados. O gate é duplo: a seção só
///   aparece com role=admin (que vem do /auth/me) e o servidor recusa
///   403 de qualquer forma (o gate de verdade é do lado do servidor).
class DashboardScreen extends StatefulWidget {
  final OdApi api;
  const DashboardScreen({super.key, required this.api});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  Map<String, dynamic>? _me;
  Map<String, dynamic>? _stats;
  Map<String, dynamic>? _admin;
  String? _error;
  bool _loading = true;
  bool _isAdmin = false;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final me = await widget.api.getMe();
      final stats = await widget.api.getDashboardStats();
      setState(() {
        _me = me;
        _stats = stats;
        _isAdmin = (me['role'] as String?) == 'admin';
      });
      if (_isAdmin) {
        // Best-effort: falha aqui não derruba o painel do usuário.
        try {
          final admin = await widget.api.getAdminUsers();
          if (!mounted) return;
          setState(() => _admin = admin);
        } catch (_) {
          if (!mounted) return;
          setState(() => _admin = null);
        }
      }
      if (!mounted) return;
      setState(() => _loading = false);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  void _snack(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _confirmAndRun(
    String title,
    String message,
    Future<void> Function() action,
  ) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(title),
        content: Text(message),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Confirmar'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await action();
      _snack('Feito.');
      await _refresh();
    } on OdApiError catch (e) {
      _snack(e.message);
    } catch (e) {
      _snack('Erro: $e');
    }
  }

  Future<void> _changePassword() async {
    final current = TextEditingController();
    final next = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Trocar minha senha'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: current,
              obscureText: true,
              decoration: const InputDecoration(labelText: 'Senha atual'),
            ),
            TextField(
              controller: next,
              obscureText: true,
              decoration: const InputDecoration(
                labelText: 'Nova senha (mín. 6)',
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Trocar'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    if (next.text.trim().length < 6) {
      _snack('A nova senha deve ter pelo menos 6 caracteres');
      return;
    }
    try {
      final closed = await widget.api.changePassword(
        current.text,
        next.text.trim(),
      );
      // A sessão deste app morreu junto (servidor mata todas) — voltar ao
      // login é obrigatório, não opcional.
      _snack('Senha trocada ($closed sessão(ões) encerrada(s)). Entre de novo.');
      await widget.api.logout();
      if (!mounted) return;
      Navigator.of(context, rootNavigator: true).pop();
    } on OdApiError catch (e) {
      _snack(e.message);
    } catch (e) {
      _snack('Erro: $e');
    }
  }

  Future<void> _rotateApiKey() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Rotacionar API key'),
        content: const Text(
          'A chave atual deixa de valer na hora. O que usava ela recebe 401 '
          'até ser atualizado. Continuar?',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Rotacionar'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      final key = await widget.api.rotateApiKey();
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Nova API key'),
          content: SelectableText(key),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('OK'),
            ),
          ],
        ),
      );
      await _refresh();
    } on OdApiError catch (e) {
      _snack(e.message);
    } catch (e) {
      _snack('Erro: $e');
    }
  }

  Future<void> _resetPassword(String username) async {
    final controller = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Resetar senha de $username'),
        content: TextField(
          controller: controller,
          obscureText: true,
          decoration: const InputDecoration(
            labelText: 'Nova senha (mín. 6)',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Resetar'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    if (controller.text.trim().length < 6) {
      _snack('A senha deve ter pelo menos 6 caracteres');
      return;
    }
    await _confirmAndRun(
      'Resetar senha',
      '$username vai poder entrar com a senha nova; as sessões dele caem.',
      () => widget.api.adminResetPassword(username, controller.text.trim()),
    );
  }

  Future<void> _deleteUser(String username) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Remover $username'),
        content: const Text(
          'A conta sai do sistema (o histórico dela permanece no banco). '
          'Esta ação não pode ser desfeita.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Remover'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    await _confirmAndRun(
      'Confirmar remoção',
      'Remover a conta $username definitivamente?',
      () => widget.api.adminDeleteUser(username),
    );
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
            Text(_error!, textAlign: TextAlign.center),
            const SizedBox(height: 12),
            FilledButton(onPressed: _refresh, child: const Text('Tentar de novo')),
          ],
        ),
      );
    }

    final user = (_me?['user'] as Map?) ?? const {};
    final history = ((_stats?['history'] as Map?) ?? const {})['per_user'];
    final messages = (history is Map)
        ? ((history[user['username']] as Map?)?['messages'] as num?)?.toInt() ?? 0
        : 0;

    return RefreshIndicator(
      onRefresh: _refresh,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            child: ListTile(
              leading: const Icon(Icons.account_circle_outlined),
              title: Text('${user['username'] ?? '-'}'),
              subtitle: Text('Papel: ${_me?['role'] ?? '-'} · via ${_me?['via'] ?? '-'}'),
            ),
          ),
          const SizedBox(height: 16),
          Text('Meu painel', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          Card(
            child: Column(
              children: [
                ListTile(
                  leading: const Icon(Icons.forum_outlined),
                  title: const Text('Minhas mensagens'),
                  trailing: Text('$messages'),
                ),
                ListTile(
                  leading: const Icon(Icons.query_stats),
                  title: const Text('Stats do sistema (/dashboard/stats)'),
                  onTap: () => _showRaw(_stats),
                ),
                ListTile(
                  leading: const Icon(Icons.password_outlined),
                  title: const Text('Trocar minha senha'),
                  onTap: _changePassword,
                ),
                ListTile(
                  leading: const Icon(Icons.key_outlined),
                  title: const Text('Rotacionar minha API key'),
                  onTap: _rotateApiKey,
                ),
              ],
            ),
          ),
          if (_isAdmin) ...[
            const SizedBox(height: 16),
            Text('Admin', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            _buildAdminCard(),
          ],
          const SizedBox(height: 24),
        ],
      ),
    );
  }

  Widget _buildAdminCard() {
    final admin = _admin;
    if (admin == null) {
      return const Card(
        child: ListTile(
          leading: Icon(Icons.admin_panel_settings_outlined),
          title: Text('Contas'),
          subtitle: Text('Falha ao carregar /admin/users'),
        ),
      );
    }
    final users = (admin['users'] as List?) ?? const [];
    final buckets = (admin['legacy_buckets'] as List?) ?? const [];
    return Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ListTile(
            leading: const Icon(Icons.admin_panel_settings_outlined),
            title: Text('Contas (${admin['total'] ?? users.length})'),
            subtitle: const Text('Reset de senha e remoção — o dono não é alvo'),
          ),
          for (final u in users.whereType<Map>())
            ListTile(
              dense: true,
              leading: Icon(
                u['owner'] == true
                    ? Icons.star
                    : Icons.person_outline,
              ),
              title: Text('${u['username']}'),
              subtitle: Text(
                'sessões ${u['sessions']} · msgs ${u['messages']}'
                '${u['owner'] == true ? ' · dono' : ''}',
              ),
              trailing: u['owner'] == true
                  ? null
                  : PopupMenuButton<String>(
                      onSelected: (value) {
                        if (value == 'reset') _resetPassword('${u['username']}');
                        if (value == 'delete') _deleteUser('${u['username']}');
                      },
                      itemBuilder: (_) => const [
                        PopupMenuItem(value: 'reset', child: Text('Resetar senha')),
                        PopupMenuItem(value: 'delete', child: Text('Remover conta')),
                      ],
                    ),
            ),
          if (buckets.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
              child: Text(
                'Baldes legados (sem conta): '
                '${buckets.map((b) => '${b['user_id']} (${b['messages']})').join(', ')}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
        ],
      ),
    );
  }

  void _showRaw(Map<String, dynamic>? data) {
    if (!mounted) return;
    showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Resposta do servidor'),
        content: SingleChildScrollView(child: SelectableText(_pretty(data))),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('OK'),
          ),
        ],
      ),
    );
  }

  String _pretty(Map<String, dynamic>? data) {
    try {
      return const JsonEncoder.withIndent('  ').convert(data);
    } catch (_) {
      return data?.toString() ?? '';
    }
  }
}
