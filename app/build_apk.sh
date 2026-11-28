#!/usr/bin/env bash
# Builda o APK release do app.
# Requer: Flutter SDK >= 3.27 + Android SDK (API 24+) + google-services.json
#         em android/app/ (o build exige o arquivo desde a integração FCM).
set -euo pipefail
cd "$(dirname "$0")"

echo "==> flutter pub get"
flutter pub get

# versionCode EXATO do pubspec (o +N é o versionCode Android que a
# auto-atualização compara com o anunciado em /app/version — sem esta flag
# o split por ABI somaria 1000*ABI e quebraria a comparação).
FORCE_CODE="-Pforce-version-code-ignoring-abi=true"

echo "==> flutter build apk --release (completo)"
flutter build apk --release "$FORCE_CODE"

echo "==> flutter build apk --release --split-per-abi (por arquitetura)"
flutter build apk --release --split-per-abi "$FORCE_CODE"

OUT="$(pwd)/build/app/outputs/flutter-apk"

# Guarda de versão: confere com aapt que os DOIS APKs saíram com o versionCode
# do pubspec ANTES de publicar. Sem isso, um build feito por fora deste script
# (sem FORCE_CODE) soma 1000×ABI — o arm64 da 1.45.1 saiu 4082 em 17/11 e
# passaria batido por anos. Ver tools/verificar_apk_versao.py.
echo "==> conferindo versionCode dos APKs (aapt) antes de publicar"
if [ -x "../.venv/bin/python" ]; then PY_CMD="../.venv/bin/python"; else PY_CMD="python3"; fi
"$PY_CMD" ../tools/verificar_apk_versao.py \
  --pubspec pubspec.yaml \
  --apk "$OUT/app-release.apk" "$OUT/app-arm64-v8a-release.apk"

echo "==> publicando APKs em site/"
cp "$OUT/app-release.apk" ../site/OmegaDrakon.apk
cp "$OUT/app-arm64-v8a-release.apk" ../site/OmegaDrakon-arm64.apk

echo ""
echo "APKs publicados em site/:"
echo "  - OmegaDrakon.apk        (completo, todas as arquiteturas)"
echo "  - OmegaDrakon-arm64.apk  (recomendado p/ celulares modernos)"