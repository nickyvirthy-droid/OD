import 'package:flutter/material.dart';
import '../services/od_api.dart';

/// Tela de configurações (API key + servidor).
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
  late final TextEditingController _keyController;
  bool _testing = false;
  bool? _connected;

  @override
  void initState() {
    super.initState();
    _urlController = TextEditingController(text: widget.api.baseUrl);
    _keyController = TextEditingController(text: widget.api.apiKey);
  }

  @override
  void dispose() {
    _urlController.dispose();
    _keyController.dispose();
    super.dispose();
  }

  Future<void> _testConnection() async {
    setState(() {
      _testing = true;
      _connected = null;
    });

    final tempApi = OdApi(baseUrl: _urlController.text.trim());
    await tempApi.setApiKey(_keyController.text.trim());
    final ok = await tempApi.isAvailable();

    setState(() {
      _testing = false;
      _connected = ok;
    });
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
    await widget.api.setApiKey(key);

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

        // URL do servidor
        TextField(
          controller: _urlController,
          decoration: const InputDecoration(
            labelText: 'URL do servidor',
            hintText: 'http://100.77.67.53:8000',
            border: OutlineInputBorder(),
            prefixIcon: Icon(Icons.dns),
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
              child: const ListTile(
                leading: Icon(Icons.check_circle, color: Colors.green),
                title: Text('Conexão OK'),
                subtitle: Text('Servidor acessível via Tailscale'),
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
                subtitle: Text('Verifique a URL e a API key'),
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
                  '1. Instale o Tailscale no celular\n'
                  '2. Entre no mesmo tailnet\n'
                  '3. Use a URL: http://100.77.67.53:8000\n'
                  '4. Cole a API key do .env do servidor',
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
