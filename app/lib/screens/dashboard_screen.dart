import 'dart:async';
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
/// - v1.13.0 (paridade total com o site): Ideias do dono
///   (/admin/ideias — txt.txt), canal de desenvolvimento on-demand
///   (/admin/dev/sessao + caixa /admin/dev/caixa) e Limitações registradas
///   pelo sistema (/admin/limitacoes). A ordem é a do /admin: Ideias e
///   logo abaixo o Canal de desenvolvimento (decisão do dono de 08/10);
///   a fila pedido.txt foi excluída do sistema.
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
  Map<String, dynamic>? _sessao;
  List<Map<String, dynamic>> _caixa = const [];
  String _ideias = '';
  List<Map<String, dynamic>> _limitacoes = const [];
  final TextEditingController _ideiasController = TextEditingController();
  final TextEditingController _respostaController = TextEditingController();
  String _cli = 'auto';
  Timer? _ticker;
  String? _error;
  bool _loading = true;
  bool _isAdmin = false;

  @override
  void initState() {
    super.initState();
    _refresh();
    // Auto-refresh de 5 s ENQUANTO a sessão estiver ativa ou houver
    // autorização pendente — mesma cadência do painel do site.
    _ticker = Timer.periodic(const Duration(seconds: 5), (_) {
      if (!mounted || !_isAdmin) return;
      final ativo = _sessao?['ativo'] == true;
      final pendentes = ((_sessao?['caixa_pendente'] as num?) ?? 0) > 0;
      if (ativo || pendentes) _refreshDev();
    });
  }

  @override
  void dispose() {
    _ticker?.cancel();
    _ideiasController.dispose();
    _respostaController.dispose();
    super.dispose();
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
        await _refreshDev();
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

  Future<bool> _confirm(String message) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Confirmar'),
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
    return ok == true;
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
            const SizedBox(height: 16),
            _buildIdeiasCard(),
            const SizedBox(height: 16),
            _buildDevSessaoCard(),
            const SizedBox(height: 16),
            _buildLimitacoesCard(),
          ],
          const SizedBox(height: 24),
        ],
      ),
    );
  }

  // -- Ideias + Canal de desenvolvimento + limitações ----------------------
  //
  // Paridade com o site (/admin): a ordem das seções é Ideias (txt.txt) e
  // LOGO ABAIXO o Canal de desenvolvimento (decisão do dono, 08/10). A fila
  // `pedido.txt` foi EXCLUÍDA do sistema — o canal é só a sessão on-demand
  // (▶ Ativar), com caixa de autorização e log. A ideia vem do txt.txt.

  Future<void> _refreshDev() async {
    try {
      final sessao = await widget.api.getDevSessao();
      final caixa = await widget.api.getDevCaixa();
      final ideias = await widget.api.getIdeias();
      final limitacoes = await widget.api.getLimitacoes();
      if (!mounted) return;
      setState(() {
        _sessao = sessao;
        _caixa = ((caixa['mensagens'] as List?) ?? const [])
            .whereType<Map<String, dynamic>>()
            .toList();
        _ideias = (ideias['conteudo'] as String?) ?? '';
        _ideiasController.text = _ideias;
        _limitacoes = ((limitacoes['entradas'] as List?) ?? const [])
            .whereType<Map<String, dynamic>>()
            .toList();
      });
    } catch (_) {
      // Best-effort: seção de dev não derruba o painel.
    }
  }

  /// Código do servidor em português — mesmo mapa do painel do site.
  String _erroSessao(Object e) {
    final cod = e is OdApiError ? e.message : '';
    const mapa = {
      'sem_ideia': 'txt.txt vazio — nada a ativar. '
          'Escreva a ideia em Ideias (txt.txt).',
      'ja_implementado': 'Essa ideia já foi implementada — txt.txt mantido.',
      'sessao_ativa':
          'Já existe uma sessão ativa — pare antes de ativar outra.',
      'sessao_nao_ativa': 'Nenhuma sessão ativa.',
      'cli_invalida': 'CLI inválida.',
      'acao_invalida': 'Ação inválida.',
      'falha_ao_iniciar_sessao': 'Falha ao iniciar a sessão.',
      'falha_ao_parar': 'Falha ao parar a sessão.',
    };
    return mapa[cod] ?? (cod.isEmpty ? e.toString() : cod);
  }

  Widget _buildDevSessaoCard() {
    final sessao = _sessao ?? const <String, dynamic>{};
    final ativo = sessao['ativo'] == true;
    final status = (sessao['status'] as String?) ?? 'parada';
    final pendentes = (sessao['caixa_pendente'] as num?) ?? 0;
    const rotulos = {
      'parada': 'PARADA',
      'preparando': 'PREPARANDO',
      'executando': 'EXECUTANDO',
      'aguardando_autorizacao': 'AGUARDANDO AUTORIZAÇÃO',
      'validando': 'VALIDANDO',
      'concluido': 'CONCLUÍDA',
      'falhou': 'FALHOU',
      'interrompida': 'INTERROMPIDA',
    };
    final detalhes = <String>[
      if (sessao['ideia_preview'] != null)
        'ideia: ${sessao['ideia_preview']}',
      if ((sessao['analise'] as String?)?.isNotEmpty == true)
        'análise: ${sessao['analise']}',
      if (sessao['cli_usada'] != null) 'CLI: ${sessao['cli_usada']}',
      if (sessao['rodada'] != null) 'rodada: ${sessao['rodada']}',
      if (sessao['testes'] != null) 'testes: ${sessao['testes']}',
      if (sessao['diff'] != null) 'diff: ${sessao['diff']}',
      if (sessao['commit'] != null) 'commit: ${sessao['commit']}',
      if (sessao['motivo'] != null) 'motivo: ${sessao['motivo']}',
    ];
    return Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ListTile(
            leading: const Icon(Icons.build_outlined),
            title: const Text('Canal de desenvolvimento'),
            subtitle: Text(
              'Sessão: ${rotulos[status] ?? status.toUpperCase()}'
              '${sessao['pid'] != null ? ' (pid ${sessao['pid']})' : ''}'
              '${pendentes > 0 ? ' · $pendentes autorização(ões) pendente(s)' : ''}',
            ),
            trailing: IconButton(
              icon: const Icon(Icons.refresh),
              tooltip: 'Atualizar',
              onPressed: _refreshDev,
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: Text(
              'A ideia vem do txt.txt (seção Ideias): ▶ Ativar não faz nada '
              'com o txt.txt vazio; avisa "já implementado" (e oferece limpar) '
              'se a ideia já foi feita numa sessão concluída; numa ideia nova '
              'a CLI analisa viabilidade, prós, contras e alternativas, '
              'publica a análise na caixa e implementa a melhor opção — com '
              'autorização na caixa e suíte verde antes do commit.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: Wrap(
              spacing: 12,
              runSpacing: 8,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                FilledButton.icon(
                  icon: const Icon(Icons.play_arrow),
                  label: const Text('Ativar'),
                  onPressed: ativo ? null : _ativarSessao,
                ),
                OutlinedButton.icon(
                  icon: const Icon(Icons.stop),
                  label: const Text('Parar'),
                  onPressed: ativo ? _pararSessao : null,
                ),
                DropdownButton<String>(
                  value: _cli,
                  items: const [
                    DropdownMenuItem(
                      value: 'auto',
                      child: Text('CLI: automática (cascata)'),
                    ),
                    DropdownMenuItem(value: 'freebuff', child: Text('Freebuff')),
                    DropdownMenuItem(value: 'opencode', child: Text('OpenCode')),
                    DropdownMenuItem(value: 'kilo', child: Text('Kilo')),
                  ],
                  onChanged: ativo
                      ? null
                      : (v) => setState(() => _cli = v ?? 'auto'),
                ),
              ],
            ),
          ),
          if (detalhes.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
              child: Text(detalhes.join('\n')),
            ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 4),
            child: Text(
              'Caixa de desenvolvimento (autorizações)',
              style: Theme.of(context).textTheme.titleSmall,
            ),
          ),
          if (_caixa.isEmpty)
            const Padding(
              padding: EdgeInsets.fromLTRB(16, 0, 16, 8),
              child: Text('— nenhuma mensagem —'),
            )
          else
            for (final m in _caixa)
              ListTile(
                dense: true,
                leading: Icon(
                  m['de'] == 'dono'
                      ? Icons.person_outline
                      : Icons.smart_toy_outlined,
                  size: 18,
                ),
                title: Text('${m['texto'] ?? ''}'),
                subtitle: Text(
                  '[${m['ts'] ?? ''}] ${m['de'] == 'dono' ? 'VOCÊ' : 'SISTEMA'}'
                  '${m['tipo'] == 'pedir_autorizacao' && m['respondida'] != true ? ' · AGUARDANDO' : ''}',
                ),
              ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _respostaController,
                    decoration: const InputDecoration(
                      hintText: 'Resposta/autorização para a sessão...',
                      border: OutlineInputBorder(),
                    ),
                    onSubmitted: (_) => _enviarCaixa(),
                  ),
                ),
                const SizedBox(width: 8),
                IconButton.filled(
                  icon: const Icon(Icons.send),
                  tooltip: 'Enviar',
                  onPressed: _enviarCaixa,
                ),
                IconButton(
                  icon: const Icon(Icons.delete_outline),
                  tooltip: 'Limpar caixa',
                  onPressed: _limparCaixa,
                ),
              ],
            ),
          ),
          if (((sessao['log_tail'] as String?) ?? '').isNotEmpty)
            ExpansionTile(
              title: const Text('Log da sessão'),
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                  child: Text(
                    '${sessao['log_tail']}',
                    style: const TextStyle(
                      fontFamily: 'monospace',
                      fontSize: 12,
                    ),
                  ),
                ),
              ],
            ),
        ],
      ),
    );
  }

  Future<void> _ativarSessao() async {
    // A ideia vem do txt.txt — só LEIA para o preview e o passo (1).
    String trecho = '';
    var previewOk = false;
    try {
      final ideias = await widget.api.getIdeias();
      trecho = ((ideias['conteudo'] as String?) ?? '').trim();
      previewOk = true;
    } catch (_) {
      // Sem prévia o servidor ainda decide (sem_ideia) se precisar.
    }
    // (1) txt.txt vazio → NÃO faz nada: nem diálogo, nem chamada.
    if (previewOk && trecho.isEmpty) {
      _snack('txt.txt vazio — nada a ativar. '
          'Escreva a ideia em Ideias (txt.txt).');
      return;
    }
    final aviso = trecho.isEmpty
        ? '\n\n⚠ sem prévia do txt.txt — o servidor valida antes de subir.'
        : '\n\nIdeia no txt.txt:\n'
            '${trecho.length > 300 ? '${trecho.substring(0, 300)}…' : trecho}';
    final ok = await _confirm(
      "▶ Ativar desenvolvimento com a CLI '$_cli'? A sessão lê o txt.txt, "
      'iniciar/ e docs/, analisa viabilidade/prós/contras/alternativas e '
      'só commita com testes verdes.$aviso',
    );
    if (!ok) return;
    try {
      final data =
          await widget.api.adminDevSessao(acao: 'ativar', cli: _cli);
      _snack('▶ Sessão iniciada (pid ${data['pid']}).');
      await _refreshDev();
    } on OdApiError catch (e) {
      // (2) ideia igual a uma sessão concluída → aviso + oferta de limpeza.
      if (e.message == 'ja_implementado') {
        await _jaImplementado(e.details);
        return;
      }
      _snack(_erroSessao(e));
    }
  }

  /// Aviso de "já implementado" + pergunta se o dono quer limpar o txt.txt
  /// (mesmo fluxo do painel do site — paridade).
  Future<void> _jaImplementado(Map<String, dynamic>? details) async {
    final commit = ((details?['commit'] as String?) ?? '').trim();
    final ts = ((details?['ts'] as String?) ?? '').trim();
    final onde = (commit.isNotEmpty ? 'commit $commit' : 'sessão concluída') +
        (ts.isNotEmpty ? ' em $ts' : '');
    final limpar = await _confirm(
      '✔ Essa ideia já foi implementada ($onde).\n\n'
      'Limpar o txt.txt agora?\n\n'
      '(Cancelar mantém o texto — para rodar de novo, edite a ideia.)',
    );
    if (!limpar) {
      _snack('Ideia já implementada — txt.txt mantido.');
      return;
    }
    try {
      await widget.api.adminClearIdeias();
      _snack('✔ Ideia já implementada — txt.txt zerado.');
      await _refreshDev();
    } on OdApiError catch (e) {
      _snack('Ideia já implementada, mas não consegui limpar o txt.txt: '
          '${_erroSessao(e)}');
    }
  }

  Future<void> _pararSessao() async {
    final ok = await _confirm(
      '⏹ Parar a sessão de desenvolvimento? A CLI em execução é encerrada.',
    );
    if (!ok) return;
    try {
      await widget.api.adminDevSessao(acao: 'parar');
      _snack('⏹ Sessão parada.');
      await _refreshDev();
    } on OdApiError catch (e) {
      _snack(_erroSessao(e));
    }
  }

  Future<void> _enviarCaixa() async {
    final texto = _respostaController.text.trim();
    if (texto.isEmpty) {
      _snack('Escreva a resposta antes de enviar.');
      return;
    }
    try {
      await widget.api.adminDevCaixaReply(texto);
      _respostaController.clear();
      await _refreshDev();
    } on OdApiError catch (e) {
      _snack(_erroSessao(e));
    }
  }

  Future<void> _limparCaixa() async {
    final ok = await _confirm('Limpar a caixa de desenvolvimento?');
    if (!ok) return;
    try {
      await widget.api.adminDevCaixaClear();
      await _refreshDev();
    } on OdApiError catch (e) {
      _snack(_erroSessao(e));
    }
  }

  Widget _buildIdeiasCard() {
    return Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const ListTile(
            leading: Icon(Icons.lightbulb_outline),
            title: Text('Ideias (txt.txt)'),
            subtitle: Text(
              'Seu canal: ideias de melhoria e o que o sistema ainda não cobre',
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: TextField(
              controller: _ideiasController,
              maxLines: 6,
              decoration: const InputDecoration(
                hintText: 'Ex.: o sistema não sabe o valor do dólar — criar action...',
                border: OutlineInputBorder(),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
            child: Wrap(
              spacing: 12,
              children: [
                FilledButton.icon(
                  icon: const Icon(Icons.save_outlined),
                  label: const Text('Salvar'),
                  onPressed: _saveIdeias,
                ),
                TextButton.icon(
                  icon: const Icon(Icons.refresh),
                  label: const Text('Recarregar'),
                  onPressed: _refreshDev,
                ),
                TextButton.icon(
                  icon: const Icon(Icons.delete_outline),
                  label: const Text('Zerar'),
                  onPressed: _clearIdeias,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _saveIdeias() async {
    try {
      await widget.api.adminWriteIdeias(_ideiasController.text);
      _snack('txt.txt salvo.');
    } on OdApiError catch (e) {
      _snack(e.message);
    }
  }

  Future<void> _clearIdeias() async {
    final ok = await _confirm('Zerar o txt.txt? (o conteúdo atual é perdido)');
    if (!ok) return;
    try {
      await widget.api.adminClearIdeias();
      _snack('txt.txt zerado.');
      await _refreshDev();
    } on OdApiError catch (e) {
      _snack(e.message);
    }
  }

  Widget _buildLimitacoesCard() {
    return Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ListTile(
            leading: const Icon(Icons.report_problem_outlined),
            title: Text('Limitações (${_limitacoes.length})'),
            subtitle: const Text(
              'O que o sistema NÃO soube responder — registro automático',
            ),
            trailing: IconButton(
              icon: const Icon(Icons.refresh),
              onPressed: _refreshDev,
            ),
          ),
          if (_limitacoes.isEmpty)
            const Padding(
              padding: EdgeInsets.fromLTRB(16, 0, 16, 12),
              child: Text(
                'Nenhuma limitação registrada — o sistema respondeu tudo.',
              ),
            )
          else
            for (final e in _limitacoes)
              ListTile(
                dense: true,
                leading: const Icon(Icons.help_outline, size: 18),
                title: Text('${e['pergunta'] ?? ''}'),
                subtitle: Text('[${e['ts'] ?? ''}] ${e['motivo'] ?? ''}'),
              ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
            child: TextButton.icon(
              icon: const Icon(Icons.delete_sweep_outlined),
              label: const Text('Limpar registro'),
              onPressed: _clearLimitacoes,
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _clearLimitacoes() async {
    final ok = await _confirm('Limpar o registro de limitações?');
    if (!ok) return;
    try {
      await widget.api.adminClearLimitacoes();
      _snack('Registro de limitações limpo.');
      await _refreshDev();
    } on OdApiError catch (e) {
      _snack(e.message);
    }
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
