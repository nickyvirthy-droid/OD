import 'package:flutter/material.dart';

import '../services/od_api.dart';

/// Tela de entrada do app: login/registro de conta.
///
/// A conta dá o **mesmo histórico** no app, no chat web e no Telegram
/// (o servidor usa o usuário da credencial). A API key continua disponível
/// como "modo avançado", no botão da base — é o caminho de quem já usa a
/// chave do servidor.
class LoginScreen extends StatefulWidget {
  const LoginScreen({
    super.key,
    required this.api,
    required this.onAuthenticated,
    this.onAdvanced,
  });

  final OdApi api;

  /// Chamado quando o login/registro dá certo.
  final VoidCallback onAuthenticated;

  /// Chamado no "modo avançado" (tela de Configurações/API key).
  final VoidCallback? onAdvanced;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _user = TextEditingController();
  final _pass = TextEditingController();
  final _email = TextEditingController();
  bool _register = false;
  bool _busy = false;
  String _error = '';

  @override
  void dispose() {
    _user.dispose();
    _pass.dispose();
    _email.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final user = _user.text.trim();
    final pass = _pass.text;
    if (user.isEmpty || pass.isEmpty) {
      setState(() => _error = 'Preencha usuário e senha.');
      return;
    }
    if (_register && _email.text.trim().isEmpty) {
      setState(() => _error = 'Informe o email para criar a conta.');
      return;
    }
    setState(() {
      _busy = true;
      _error = '';
    });
    try {
      if (_register) {
        await widget.api.register(user, _email.text.trim(), pass);
      }
      await widget.api.login(user, pass);
      if (mounted) widget.onAuthenticated();
    } on OdApiError catch (e) {
      if (mounted) setState(() => _error = e.message);
    } catch (e) {
      if (mounted) setState(() => _error = 'Falha de rede: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 380),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text('🐉', textAlign: TextAlign.center,
                    style: TextStyle(fontSize: 48)),
                const SizedBox(height: 8),
                Text(
                  'Entrar no OmegaDrakon',
                  textAlign: TextAlign.center,
                  style: theme.textTheme.headlineSmall,
                ),
                const SizedBox(height: 4),
                Text(
                  'Sua conversa continua de onde parou — no app, no chat e no Telegram.',
                  textAlign: TextAlign.center,
                  style: theme.textTheme.bodySmall,
                ),
                const SizedBox(height: 24),
                TextField(
                  controller: _user,
                  autocorrect: false,
                  decoration: const InputDecoration(
                    labelText: 'Usuário',
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 12),
                if (_register) ...[
                  TextField(
                    controller: _email,
                    keyboardType: TextInputType.emailAddress,
                    autocorrect: false,
                    decoration: const InputDecoration(
                      labelText: 'Email',
                      border: OutlineInputBorder(),
                    ),
                  ),
                  const SizedBox(height: 12),
                ],
                TextField(
                  controller: _pass,
                  obscureText: true,
                  decoration: const InputDecoration(
                    labelText: 'Senha',
                    border: OutlineInputBorder(),
                  ),
                  onSubmitted: (_) => _submit(),
                ),
                if (_error.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  Text(_error, style: TextStyle(color: theme.colorScheme.error)),
                ],
                const SizedBox(height: 20),
                FilledButton(
                  onPressed: _busy ? null : _submit,
                  child: _busy
                      ? const SizedBox(
                          height: 18,
                          width: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : Text(_register ? 'Criar conta' : 'Entrar'),
                ),
                TextButton(
                  onPressed: _busy
                      ? null
                      : () => setState(() {
                            _register = !_register;
                            _error = '';
                          }),
                  child: Text(_register
                      ? 'Já tenho conta — entrar'
                      : 'Não tem conta? Registrar'),
                ),
                if (widget.onAdvanced != null)
                  TextButton(
                    onPressed: _busy ? null : widget.onAdvanced,
                    child: const Text('Modo avançado (API key)'),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
