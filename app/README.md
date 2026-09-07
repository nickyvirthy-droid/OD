# OmegaDrakon — App Android 🐉

> Interface Viva no bolso — converse com o OD de qualquer lugar via Tailscale.

## Funcionalidades

| Tela | Função |
|---|---|
| **Chat** | Conversa com o OD (8 perfis: auto, guardian, regulus, luma, vox, athenae, nyx, nexus) |
| **Ações** | Catálogo de ações do OD com busca, risco e execução |
| **Status** | Health checks, capacidades e info do sistema |
| **Config** | API key, URL do servidor, teste de conexão |

## Requisitos

- Flutter SDK >= 3.2.0
- Android SDK (API 21+)
- Tailscale instalado no celular e no servidor
- OmegaDrakon rodando no servidor nicky-server

## Setup

```bash
cd app
flutter pub get
flutter run
```

## Build APK

```bash
flutter build apk --release
# APK em: build/app/outputs/flutter-apk/app-release.apk
```

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
