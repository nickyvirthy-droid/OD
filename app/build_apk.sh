#!/usr/bin/env bash
# Builda o APK release do app.
# Requer: Flutter SDK >= 3.27 + Android SDK (API 24+) + google-services.json
#         em android/app/ (o build exige o arquivo desde a integração FCM).
set -euo pipefail
cd "$(dirname "$0")"

echo "==> flutter pub get"
flutter pub get

echo "==> flutter build apk --release (completo)"
flutter build apk --release

echo "==> flutter build apk --release --split-per-abi (por arquitetura)"
flutter build apk --release --split-per-abi

OUT="$(pwd)/build/app/outputs/flutter-apk"
echo "==> publicando APKs em site/"
cp "$OUT/app-release.apk" ../site/OmegaDrakon.apk
cp "$OUT/app-arm64-v8a-release.apk" ../site/OmegaDrakon-arm64.apk

echo ""
echo "APKs publicados em site/:"
echo "  - OmegaDrakon.apk        (completo, todas as arquiteturas)"
echo "  - OmegaDrakon-arm64.apk  (recomendado p/ celulares modernos)"