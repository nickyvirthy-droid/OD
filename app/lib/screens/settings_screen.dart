import 'package:flutter/material.dart';
import '../services/od_api.dart';

/// Tela de configurações (API key + servidor com URL primária e fallback).
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
  late final TextEditingController _urlController;
  late final TextEditingController _fallbackController;
  late final TextEditingController _keyController;
  bool _testing = false;
  bool? _connected;
  String? _connectedVia;

  @override
  void initState() {
    super.initState();
    _urlController = TextEditingController(text: widget.api.baseUrl);
    _fallbackController =
        TextEditingController(text: widget.api.fallbackUrl ?? '');
    _keyController = TextEditingController(text: widget.api.apiKey);
  }

  @override
  void dispose() {
    _urlController.dispose();
    _fallbackController.dispose();
    _keyController.dispose();
    super.dispose();
  }

  Future<void> _testConnection() async {
    setState(() {
      _testing = true;
      _connected = null;
      _connectedVia = null;
    });

    final tempApi = OdApi(
      baseUrl: _urlController.text.trim(),
      fallbackUrl: _fallbackController.text.trim().isEmpty
          ? null
          : _fallbackController.text.trim(),
    );
    await tempApi.setApiKey(_keyController.text.trim());

    // Tenta a URL primária primeiro.
    final primary = await _testUrl(tempApi, _urlController.text.trim());
    if (primary) {
      setState(() {
        _testing = false;
        _connected = true;
        _connectedVia = _urlController.text.trim();
      });
      return;
    }

    // Tenta a fallback.
    final fallback = _fallbackController.text.trim();
    if (fallback.isNotEmpty) {
      final secondary = await _testUrl(tempApi, fallback);
      if (secondary) {
        setState(() {
          _testing = false;
          _connected = true;
          _connectedVia = fallback;
        });
        return;
      }
    }

    setState(() {
      _testing = false;
      _connected = false;
    });
  }

  Future<bool> _testUrl(OdApi api, String url) async {
    api.setBaseUrl(url);
    return api.isAvailable();
  }

  Future<void> _save() async {
    final url = _urlController.text.trim();
    final key = _keyController.text.trim();

    if (url.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('URL do servidor é obrigatória')),
      );
      return;
    }

    // Aplica a nova URL e a chave na instância usada pelas telas
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
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text(
          'Configurações',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        const SizedBox(height: 24),

        // URL primária (Tailscale)
        TextField(
          controller: _urlController,
          decoration: const InputDecoration(
            labelText: 'URL do servidor (rede local)',
            hintText: 'http://100.77.67.53:8000',
            border: OutlineInputBorder(),
            prefixIcon: Icon(Icons.dns),
          ),
          keyboardType: TextInputType.url,
        ),
        const SizedBox(height: 12),

        // URL fallback (externa)
        TextField(
          controller: _fallbackController,
          decoration: const InputDecoration(
            labelText: 'URL externa (internet)',
            hintText: 'https://nicky-server.tail1b1f51.ts.net',
            border: OutlineInputBorder(),
            prefixIcon: Icon(Icons.language),
          ),
          keyboardType: TextInputType.url,
        ),
        const SizedBox(height: 16),

        // API Key
        TextField(
          controller: _keyController,
          decoration: const InputDecoration(
            labelText: 'API Key',
            hintText: 'Cole sua chave aqui',
            border: OutlineInputBorder(),
            prefixIcon: Icon(Icons.key),
          ),
          obscureText: true,
        ),
        const SizedBox(height: 24),

        // Botões
        Row(
          children: [
            Expanded(
              child: OutlinedButton.icon(
                onPressed: _testing ? null : _testConnection,
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
                label: Text(_testing ? 'Testando...' : 'Testar conexão'),
              ),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: FilledButton.icon(
                onPressed: _save,
                icon: const Icon(Icons.save),
                label: const Text('Salvar'),
              ),
            ),
          ],
        ),

        if (_connected == true)
          Padding(
            padding: const EdgeInsets.only(top: 16),
            child: Card(
              color: Colors.green.shade50,
              child: ListTile(
                leading: const Icon(Icons.check_circle, color: Colors.green),
                title: const Text('Conexão OK'),
                subtitle: Text('Conectado via $_connectedVia'),
              ),
            ),
          ),

        if (_connected == false)
          Padding(
            padding: const EdgeInsets.only(top: 16),
            child: Card(
              color: Colors.red.shade50,
              child: const ListTile(
                leading: Icon(Icons.error, color: Colors.red),
                title: Text('Sem conexão'),
                subtitle: Text('Verifique as URLs e a API key'),
              ),
            ),
          ),

        const SizedBox(height: 24),

        // Info
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Como acessar',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const Divider(),
                const Text(
                  'Rede local (Tailscale):)\n'
                  '  1. Instale o Tailscale no celular\n'
                  '  2. Entre no mesmo tailnet\n'
                  '  3. URL: http://100.77.67.53:8000\n\n'
                  'Internet (externa — Tailscale Funnel):\n'
                  '  1. URL: https://nicky-server.tail1b1f51.ts.net\n'
                  '  2. Funciona de qualquer lugar (HTTPS)\n\n'
                  'Cole a API key do .env do servidor.',
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
