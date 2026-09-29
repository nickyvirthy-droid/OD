import 'dart:async';

import 'package:flutter/material.dart';
import 'services/od_api.dart';
import 'services/od_updater.dart';
import 'services/push_service.dart';
import 'screens/chat_screen.dart';
import 'screens/actions_screen.dart';
import 'screens/dashboard_screen.dart';
import 'screens/status_screen.dart';
import 'screens/settings_screen.dart';
import 'screens/login_screen.dart';

/// OmegaDrakon — Interface Viva no bolso 🐉
///
/// App Android para conversar com o OD, executar ações e monitorar
/// o sistema de qualquer lugar via Tailscale.
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // Push FCM é best-effort e NUNCA bloqueia nem derruba o boot: roda em
  // segundo plano, com try/catch em volta de TUDO (inclusive da criação
  // do singleton) — qualquer falha do Firebase, o app abre normal.
  unawaited(_initPushBestEffort());
  runApp(const OdApp());
}

/// Inicializa o push sem nunca deixar exceção escapar para o main().
Future<void> _initPushBestEffort() async {
  try {
    await PushService.instance.init();
  } catch (_) {
    // Best-effort: push falhou, app segue funcionando.
  }
}

class OdApp extends StatelessWidget {
  const OdApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'OmegaDrakon',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorSchemeSeed: const Color(0xFF1A237E),
        useMaterial3: true,
        brightness: Brightness.light,
      ),
      darkTheme: ThemeData(
        colorSchemeSeed: const Color(0xFF1A237E),
        useMaterial3: true,
        brightness: Brightness.dark,
      ),
      themeMode: ThemeMode.system,
      home: const OdRoot(),
    );
  }
}

/// Decide entre a tela de entrada e o app, conforme a credencial salva.
///
/// Sem sessão nenhuma na primeira vez, abre o login (a API key continua
/// acessível pelo "modo avançado", que leva às Configurações).
class OdRoot extends StatefulWidget {
  const OdRoot({super.key});

  @override
  State<OdRoot> createState() => _OdRootState();
}

class _OdRootState extends State<OdRoot> {
  late final OdApi _api;
  bool _ready = false;
  bool _authenticated = false;
  int _initialIndex = 0;

  // Auto-atualização (v1.7.0): o servidor anuncia a versão publicada e o
  // app oferece a troca sem ninguém abrir o site.
  OdUpdateInfo? _update;
  bool _downloading = false;
  double _downloadProgress = 0;

  @override
  void initState() {
    super.initState();
    // URLs padrão do sistema — o usuário NUNCA configura URL: o app escolhe
    // sozinho pela localização da rede (ver pickBestUrl).
    _api = OdApi(baseUrl: odDefaultLocalUrl, fallbackUrl: odDefaultExternalUrl);
    _bootstrap();
  }

  Future<void> _bootstrap() async {
    // 1) Credenciais salvas + URLs do último uso.
    final has = await _api.loadSavedApiKey();
    // 2) Localização de rede: sonda a rede local (Tailscale) e usa a externa
    //    quando ela não responde. Antes do login, para o login já entrar
    //    pelo caminho que funciona.
    await _api.pickBestUrl();
    if (!mounted) return;
    setState(() {
      _authenticated = has;
      _ready = true;
    });
    if (has) {
      // Sessão/API key válidas: registra o token FCM deste aparelho.
      unawaited(PushService.instance.attach(_api));
    }
    // Checagem de atualização: best-effort, nunca bloqueia nem derruba o
    // boot (servidor fora / sem rota → simplesmente não há banner).
    unawaited(_checkUpdateBestEffort());
  }

  Future<void> _checkUpdateBestEffort() async {
    final info = await OdUpdater(api: _api).check();
    if (info == null || !info.isNewer || !mounted) return;
    setState(() => _update = info);
  }

  Future<void> _applyUpdate() async {
    final info = _update;
    if (info == null || _downloading) return;
    setState(() {
      _downloading = true;
      _downloadProgress = 0;
    });
    try {
      final apk = await OdUpdater(api: _api).download(
        info,
        onProgress: (progress) {
          if (mounted) setState(() => _downloadProgress = progress);
        },
      );
      await OdUpdater(api: _api).install(apk);
    } on OdApiError catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(error.message)),
        );
      }
    } finally {
      if (mounted) {
        setState(() {
          _downloading = false;
          _downloadProgress = 0;
        });
      }
    }
  }

  /// Banner fino no topo enquanto há atualização disponível/em download.
  Widget? get _updateBanner {
    final info = _update;
    if (info == null) return null;
    return Material(
      color: Theme.of(context).colorScheme.secondaryContainer,
      child: SafeArea(
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 8, 8),
          child: Row(
            children: [
              const Icon(Icons.system_update_alt, size: 20),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  _downloading
                      ? 'Baixando v${info.version}… '
                          '${(100 * _downloadProgress).toStringAsFixed(0)}%'
                      : 'Nova versão ${info.version} disponível'
                          '${info.sizeMb}',
                ),
              ),
              if (_downloading)
                const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              else TextButton(
                onPressed: _applyUpdate,
                child: const Text('Atualizar'),
              ),
              if (!_downloading)
                IconButton(
                  icon: const Icon(Icons.close, size: 18),
                  onPressed: () => setState(() => _update = null),
                ),
            ],
          ),
        ),
      ),
    );
  }

  void _onAuthenticated() {
    unawaited(PushService.instance.attach(_api));
    setState(() {
      _authenticated = true;
      _initialIndex = 0;
    });
  }

  void _onAdvanced() {
    // Modo avançado: vai direto às Configurações (API key do servidor).
    // 5ª aba: Chat(0) · Ações(1) · Painel(2) · Status(3) · Config(4).
    setState(() {
      _authenticated = true;
      _initialIndex = 4;
    });
  }

  void _onSettingsSaved() {
    unawaited(PushService.instance.attach(_api));
    setState(() => _initialIndex = 0);
  }

  @override
  Widget build(BuildContext context) {
    if (!_ready) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      );
    }
    final Widget home;
    if (!_authenticated) {
      home = LoginScreen(
        api: _api,
        onAuthenticated: _onAuthenticated,
        onAdvanced: _onAdvanced,
      );
    } else {
      home = OdHome(
        api: _api,
        initialIndex: _initialIndex,
        onSettingsSaved: _onSettingsSaved,
      );
    }
    final banner = _updateBanner;
    if (banner == null) return home;
    return Column(children: [banner, Expanded(child: home)]);
  }
}

class OdHome extends StatefulWidget {
  const OdHome({
    super.key,
    required this.api,
    this.initialIndex = 0,
    required this.onSettingsSaved,
  });

  final OdApi api;
  final int initialIndex;
  final VoidCallback onSettingsSaved;

  @override
  State<OdHome> createState() => _OdHomeState();
}

class _OdHomeState extends State<OdHome> {
  late int _currentIndex;

  @override
  void initState() {
    super.initState();
    _currentIndex = widget.initialIndex;
  }

  @override
  Widget build(BuildContext context) {
    final screens = [
      ChatScreen(api: widget.api),
      ActionsScreen(api: widget.api),
      DashboardScreen(api: widget.api),
      StatusScreen(api: widget.api),
      SettingsScreen(api: widget.api, onSaved: widget.onSettingsSaved),
    ];

    return Scaffold(
      body: SafeArea(
        child: screens[_currentIndex],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _currentIndex,
        onDestinationSelected: (index) {
          setState(() => _currentIndex = index);
        },
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.chat_outlined),
            selectedIcon: Icon(Icons.chat),
            label: 'Chat',
          ),
          NavigationDestination(
            icon: Icon(Icons.bolt_outlined),
            selectedIcon: Icon(Icons.bolt),
            label: 'Ações',
          ),
          NavigationDestination(
            icon: Icon(Icons.dashboard_outlined),
            selectedIcon: Icon(Icons.dashboard),
            label: 'Painel',
          ),
          NavigationDestination(
            icon: Icon(Icons.monitor_heart_outlined),
            selectedIcon: Icon(Icons.monitor_heart),
            label: 'Status',
          ),
          NavigationDestination(
            icon: Icon(Icons.settings_outlined),
            selectedIcon: Icon(Icons.settings),
            label: 'Config',
          ),
        ],
      ),
    );
  }
}
