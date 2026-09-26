import 'dart:async';

import 'package:flutter/material.dart';
import 'services/od_api.dart';
import 'services/push_service.dart';
import 'screens/chat_screen.dart';
import 'screens/actions_screen.dart';
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
    setState(() {
      _authenticated = true;
      _initialIndex = 3;
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
    if (!_authenticated) {
      return LoginScreen(
        api: _api,
        onAuthenticated: _onAuthenticated,
        onAdvanced: _onAdvanced,
      );
    }
    return OdHome(
      api: _api,
      initialIndex: _initialIndex,
      onSettingsSaved: _onSettingsSaved,
    );
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
