#!/usr/bin/env bash
# Roda o analyzer e a suíte de testes do app.
# Requer: Flutter SDK >= 3.27.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> flutter pub get"
flutter pub get

echo "==> flutter analyze"
flutter analyze

echo "==> flutter test"
flutter test