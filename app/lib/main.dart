import 'package:flutter/material.dart';
import 'services/od_api.dart';
import 'screens/chat_screen.dart';
import 'screens/actions_screen.dart';
import 'screens/status_screen.dart';
import 'screens/settings_screen.dart';

/// OmegaDrakon — Interface Viva no bolso 🐉
///
/// App Android para conversar com o OD, executar ações e monitorar
/// o sistema de qualquer lugar via Tailscale.
void main() {
  runApp(const OdApp());
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
      home: const OdHome(),
    );
  }
}

class OdHome extends StatefulWidget {
  const OdHome({super.key});

  @override
  State<OdHome> createState() => _OdHomeState();
}

class _OdHomeState extends State<OdHome> {
  int _currentIndex = 0;
  late final OdApi _api;

  @override
  void initState() {
    super.initState();
    _api = OdApi(baseUrl: 'http://100.77.67.53:8000');
    _initApi();
  }

  Future<void> _initApi() async {
    final loaded = await _api.loadSavedApiKey();
    if (!loaded && mounted) {
      // Primeira vez — mostra settings
      setState(() => _currentIndex = 3);
    }
  }

  @override
  Widget build(BuildContext context) {
    final screens = [
      ChatScreen(api: _api),
      ActionsScreen(api: _api),
      StatusScreen(api: _api),
      SettingsScreen(
        api: _api,
        onSaved: () => setState(() => _currentIndex = 0),
      ),
    ];

    return Scaffold(
      body: screens[_currentIndex],
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
