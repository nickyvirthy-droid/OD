import 'package:flutter/material.dart';
import '../services/od_api.dart';

/// Tela de configurações.
///
/// Estrutura pensada para quem NÃO é admin:
/// - **Conta** — o mesmo usuário/senha do site (chat web): entra sem sair
///   do app, sem digitar chave nenhuma.
/// - **Servidor** — a conexão é AUTOMÁTICA pela localização da rede
///   ([OdApi.pickBestUrl]); as URLs ficam ocultas.
/// - **Avançado** — API key e URLs manuais, escondidos num expandible para
///   não atrapalhar quem só conversa.
class SettingsScreen extends StatefulWidget {
  final OdApi api;
  final VoidCallback onSaved;
  const SettingsScreen({
    super.key,
    required this.api,
    required this.onSaved,
  });

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  // -- Conta (mesmas credenciais do site) --
  final _user = TextEditingController();
  final _pass = TextEditingController();
  bool _busyAccount = false;
  String _accountError = '';

  // -- Avançado (API key + URLs) --
  late final TextEditingController _keyController;
  late final TextEditingController _urlController;
  late final TextEditingController _fallbackController;
  bool _showUrls = false;

  bool _testing = false;
  bool? _connected;

  @override
  void initState() {
    super.initState();
    _keyController = TextEditingController(text: widget.api.apiKey);
    _urlController = TextEditingController(text: widget.api.baseUrl);
    _fallbackController =
        TextEditingController(text: widget.api.fallbackUrl ?? '');
  }

  @override
  void dispose() {
    _user.dispose();
    _pass.dispose();
    _keyController.dispose();
    _urlController.dispose();
    _fallbackController.dispose();
    super.dispose();
  }

  // -------------------------------------------------------------------------
  // Conta — login com o MESMO usuário/senha do site (POST /auth/login).
  // -------------------------------------------------------------------------
  Future<void> _loginAccount() async {
    final user = _user.text.trim();
    final pass = _pass.text;
    if (user.isEmpty || pass.isEmpty) {
      setState(() => _accountError = 'Preencha nome e senha.');
      return;
    }
    setState(() {
      _busyAccount = true;
      _accountError = '';
    });
    try {
      await widget.api.login(user, pass);
      if (!mounted) return;
      setState(() => _busyAccount = false);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Conectado como ${widget.api.username}')),
      );
      widget.onSaved();
    } on OdApiError catch (e) {
      if (mounted) {
        setState(() {
          _busyAccount = false;
          _accountError = e.message;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _busyAccount = false;
          _accountError = 'Falha de rede: $e';
        });
      }
    }
  }

  Future<void> _logoutAccount() async {
    setState(() => _busyAccount = true);
    await widget.api.logout();
    if (!mounted) return;
    setState(() => _busyAccount = false);
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Sessão encerrada.')),
    );
    widget.onSaved();
  }

  // -------------------------------------------------------------------------
  // Conexão — a URL é escolhida pela LOCALIZAÇÃO da rede (nada manual).
  // -------------------------------------------------------------------------
  Future<void> _reconnectByLocation() async {
    setState(() {
      _testing = true;
      _connected = null;
    });
    final escolhida = await widget.api.pickBestUrl();
    final ok = await widget.api.isAvailable();
    setState(() {
      _testing = false;
      _connected = ok;
    });
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(ok
            ? 'Conectado via ${widget.api.usingLocalUrl ? 'rede local' : 'internet'}'
            : 'Servidor inalcançável nas duas redes'),
      ),
    );
    debugPrint(escolhida); // URL fica em log de depuração, não na tela.
  }

  // -------------------------------------------------------------------------
  // Avançado — API key e URLs manuais (escondido por padrão).
  // -------------------------------------------------------------------------
  Future<void> _saveAdvanced() async {
    final url = _urlController.text.trim();
    final key = _keyController.text.trim();

    if (url.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('URL do servidor é obrigatória')),
      );
      return;
    }

    widget.api.setBaseUrl(url);
    widget.api.setFallbackUrl(
      _fallbackController.text.trim().isEmpty
          ? null
          : _fallbackController.text.trim(),
    );
    await widget.api.setApiKey(key);
    await widget.api.saveUrls();

    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Configurações salvas!')),
      );
      widget.onSaved();
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final logado = widget.api.token.isNotEmpty;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text('Configurações', style: theme.textTheme.headlineSmall),
        const SizedBox(height: 20),

        // -- CONTA -----------------------------------------------------------
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(children: [
                  const Icon(Icons.account_circle),
                  const SizedBox(width: 8),
                  Text('Conta', style: theme.textTheme.titleMedium),
                ]),
                const Divider(),
                if (logado) ...[
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: const Icon(Icons.verified_user, color: Colors.green),
                    title: Text(widget.api.username),
                    subtitle: const Text(
                        'Mesma conta do site — conversa continua de onde parou'),
                  ),
                  OutlinedButton.icon(
                    onPressed: _busyAccount ? null : _logoutAccount,
                    icon: const Icon(Icons.logout),
                    label: const Text('Sair da conta'),
                  ),
                ] else ...[
                  const Text(
                    'Use o MESMO nome e senha que você usa no site do OmegaDrakon.',
                    style: TextStyle(color: Colors.grey),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _user,
                    autocorrect: false,
                    decoration: const InputDecoration(
                      labelText: 'Nome de usuário',
                      border: OutlineInputBorder(),
                      prefixIcon: Icon(Icons.person),
                    ),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _pass,
                    obscureText: true,
                    decoration: const InputDecoration(
                      labelText: 'Senha',
                      border: OutlineInputBorder(),
                      prefixIcon: Icon(Icons.lock),
                    ),
                    onSubmitted: (_) => _loginAccount(),
                  ),
                  if (_accountError.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    Text(_accountError,
                        style: TextStyle(color: theme.colorScheme.error)),
                  ],
                  const SizedBox(height: 12),
                  FilledButton.icon(
                    onPressed: _busyAccount ? null : _loginAccount,
                    icon: _busyAccount
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.login),
                    label: const Text('Entrar'),
                  ),
                ],
              ],
            ),
          ),
        ),
        const SizedBox(height: 16),

        // -- SERVIDOR (conexão automática, URLs ocultas) ----------------------
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(children: [
                  const Icon(Icons.router),
                  const SizedBox(width: 8),
                  Text('Servidor', style: theme.textTheme.titleMedium),
                ]),
                const Divider(),
                const Text(
                  'A conexão é automática: em casa o app usa a rede local '
                  '(mais rápida); fora de casa, vai pela internet com '
                  'segurança (HTTPS). Você não precisa configurar nada.',
                ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    Icon(
                      widget.api.usingLocalUrl ? Icons.home : Icons.public,
                      size: 16,
                      color: Colors.grey,
                    ),
                    const SizedBox(width: 6),
                    Text(
                      widget.api.usingLocalUrl
                          ? 'Conectado pela rede local'
                          : 'Conectado pela internet (Funnel)',
                      style: const TextStyle(color: Colors.grey, fontSize: 12),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                OutlinedButton.icon(
                  onPressed: _testing ? null : _reconnectByLocation,
                  icon: _testing
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : Icon(
                          _connected == null
                              ? Icons.wifi_find
                              : _connected!
                                  ? Icons.wifi
                                  : Icons.wifi_off,
                          color: _connected == true ? Colors.green : null,
                        ),
                  label: Text(_testing ? 'Procurando...' : 'Reconectar agora'),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 16),

        // -- AVANÇADO (API key + URLs, escondido) -----------------------------
        Card(
          child: ExpansionTile(
            leading: const Icon(Icons.tune),
            title: const Text('Avançado'),
            subtitle: const Text('API key e URLs manuais'),
            childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
            children: [
              TextField(
                controller: _keyController,
                decoration: const InputDecoration(
                  labelText: 'API Key (chave do servidor)',
                  hintText: 'Cole sua chave aqui',
                  border: OutlineInputBorder(),
                  prefixIcon: Icon(Icons.key),
                ),
                obscureText: true,
              ),
              const SizedBox(height: 12),
              // URLs ocultas atrás do switch — quem precisa delas sabe onde.
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Mostrar URLs'),
                subtitle: const Text('Padrão do sistema: ocultas'),
                value: _showUrls,
                onChanged: (v) => setState(() {
                  _showUrls = v;
                  if (v) {
                    _urlController.text = widget.api.baseUrl;
                    _fallbackController.text =
                        widget.api.fallbackUrl ?? odDefaultExternalUrl;
                  }
                }),
              ),
              if (_showUrls) ...[
                TextField(
                  controller: _urlController,
                  decoration: const InputDecoration(
                    labelText: 'URL local (Tailscale)',
                    hintText: odDefaultLocalUrl,
                    border: OutlineInputBorder(),
                    prefixIcon: Icon(Icons.dns),
                  ),
                  keyboardType: TextInputType.url,
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _fallbackController,
                  decoration: const InputDecoration(
                    labelText: 'URL externa (Funnel)',
                    hintText: odDefaultExternalUrl,
                    border: OutlineInputBorder(),
                    prefixIcon: Icon(Icons.language),
                  ),
                  keyboardType: TextInputType.url,
                ),
              ],
              const SizedBox(height: 16),
              FilledButton.icon(
                onPressed: _saveAdvanced,
                icon: const Icon(Icons.save),
                label: const Text('Salvar avançado'),
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),

        // -- Info -------------------------------------------------------------
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Como funciona', style: theme.textTheme.titleMedium),
                const Divider(),
                const Text(
                  '• Conta: crie no site (ou aqui mesmo pelo login do app) e '
                  'sua conversa é a mesma no app, no chat e no Telegram.\n'
                  '• Sem conta, o "Avançado" aceita a API key do servidor.\n'
                  '• Em casa o app fala com o servidor pela rede local; fora, '
                  'pela internet com criptografia — sozinho, sem você '
                  'escolher nada.',
                  style: TextStyle(height: 1.5),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}
