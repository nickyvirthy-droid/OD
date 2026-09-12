# OmegaDrakon — App Android 🐉

> Interface Viva no bolso — converse com o OD de qualquer lugar via Tailscale.

## Funcionalidades

| Tela | Função |
|---|---|
| **Chat** | Conversa com o OD (8 perfis: auto, guardian, regulus, luma, vox, athenae, nyx, nexus) |
| **Ações** | Catálogo de ações do OD com busca, risco e execução |
| **Status** | Health checks, capacidades e info do sistema |
| **Config** | API key, URL do servidor, teste de conexão |
| **Push 🔔** | Alertas do OD (proativos, recovery, presença) via FCM com notificações locais (Android 13+) |

## Requisitos

- Flutter SDK >= 3.27 (Dart >= 3.6)
- JDK 17 + Android SDK
- Tailscale instalado no celular e no servidor
- OmegaDrakon rodando no servidor nicky-server

> **Push FCM:** o build funciona **sem** Firebase (o push fica desativado em
> runtime). Para ativar as notificações, siga `docs/FIREBASE_SETUP.md`
> (google-services.json + plugin gradle) — depois disso o build passa a
> exigir o arquivo.

## Setup

```bash
cd app
flutter pub get
flutter run
```

> O scaffold Android (build.gradle.kts, gradle wrapper etc.) é gerado
> automaticamente pelo `build_apk.sh` (via `flutter create .`, idempotente —
> não sobrescreve o `lib/`).

## Build APK

```bash
cd app
./build_apk.sh
# APK em: build/app/outputs/flutter-apk/app-release.apk
```

Último build validado: **Flutter 3.47.2 · APK 51.6 MB** (com desugaring
habilitado para o `flutter_local_notifications`).

## Testes

```bash
cd app
./run_tests.sh   # flutter analyze + flutter test
```

Cobertura: `test/od_api_test.dart` (cliente HTTP com mock), `test/models_test.dart`
e `test/widget_test.dart` (smoke do app + 4 telas + bolha de mensagem).

## Conexão

1. Instale o Tailscale no celular
2. Entre no tailnet `nickyvirthy@`
3. Abra o app e configure:
   - URL: `http://100.77.67.53:8000`
   - API Key: (a chave do `.env` do servidor)
4. Teste a conexão
5. Comece a conversar!

## Arquitetura

```
app/lib/
├── main.dart              # Entry point + navegação
├── models/
│   ├── message.dart       # Modelo de mensagem
│   └── action.dart        # Modelo de ação
├── screens/
│   ├── chat_screen.dart   # Tela de conversa
│   ├── actions_screen.dart # Catálogo de ações
│   ├── status_screen.dart # Health + capabilities
│   └── settings_screen.dart # Config + API key
├── services/
│   └── od_api.dart        # Cliente HTTP da API
└── widgets/
    └── message_bubble.dart # Bolha de mensagem
```

## Segurança

- API key armazenada em SharedPreferences (encrypted no Android)
- Comunicação via Tailscale (VPN WireGuard peer-to-peer)
- Nenhuma porta exposta na internet
- Auth via `X-API-Key` em todos os endpoints
