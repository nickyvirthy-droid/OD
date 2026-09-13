# OmegaDrakon App — Push via Firebase Cloud Messaging (FCM) 🔔

> Status: **recebimento configurado** (2026-09-09) e **envio implementado**
> (2026-09-12) — projeto Firebase `nicky-e4f99`, pacote `com.omegadrakon.nicky`,
> plugin google-services 4.5.0 (AGP 9 ok).
>
> Duas metades do push:
>
> | Metade | Estado |
> |---|---|
> | **App recebe** (FCM → celular) | ✅ configurado e no APK (console já entrega) |
> | **OD envia** (servidor → celular) | ✅ implementado — `core/push.py` + `/push/*` + sink do Notifier. **Dormente até existir a service account** (passo 6 abaixo) |

## Envio pelo OD (o que faltava) — passos 6 e 7

### 6. Credencial de servidor (service account)

O app recebe pelo `google-services.json`, mas **quem envia precisa de outra
credencial**: a service account do Firebase (o `google-services.json` NÃO
serve para enviar).

1. Firebase console → projeto `nicky-e4f99` → ⚙️ **Configurações do projeto**
2. Aba **Contas de serviço** → **Gerar nova chave privada** → JSON
3. Salve no servidor (a venv já tem `google-auth`):

```bash
mv ~/Downloads/nicky-e4f99-*.json ~/OmegaDrakon/config/firebase-service-account.json
```

O arquivo é **segredo** e já está no `.gitignore` (`service-account*.json`,
`*firebase-adminsdk*.json`). Alternativa: `OD_FCM_CREDENTIALS=/caminho/arquivo.json`.

### 7. Variáveis de ambiente

| Variável | Padrão | Função |
|---|---|---|
| `OD_FCM_CREDENTIALS` | `config/firebase-service-account.json` | caminho da service account |
| `OD_PUSH_ENABLED` | `1` (ligado se houver credencial) | `0` desliga o push |
| `OD_PUSH_PROJECT_ID` | o da credencial | força o projeto FCM |
| `OD_PUSH_DEVICES` | `data/push_devices.json` | registro dos aparelhos |

Reinicie para o serviço subir com a credencial: `systemctl --user restart od-core`.

### Endpoints de push (exigem `X-API-Key`)

```bash
# o app faz isso sozinho no boot e ao salvar as Configurações
curl -X POST http://100.77.67.53:8000/push/register \
  -H "X-API-Key: SUA_CHAVE" -H "Content-Type: application/json" \
  -d '{"token":"TOKEN_FCM","platform":"android","device":"Redmi Note 14"}'

# quem está registrado (tokens mascarados) + push ligado?
curl -H "X-API-Key: SUA_CHAVE" http://100.77.67.53:8000/push/devices

# notificação de teste para todos os aparelhos (503 se a credencial faltar)
curl -X POST http://100.77.67.53:8000/push/test \
  -H "X-API-Key: SUA_CHAVE" -H "Content-Type: application/json" \
  -d '{"title":"Teste OD","body":"Push funcionando 🎉"}'

# trocar de aparelho / parar de receber
curl -X POST http://100.77.67.53:8000/push/unregister \
  -H "X-API-Key: SUA_CHAVE" -H "Content-Type: application/json" \
  -d '{"token":"TOKEN_FCM"}'
```

Os alertas do `ProactiveNotifier` (LLM offline, disco, restart) já passam a
sair também como push — o Notifier ganhou o sink em `core/push.py`.

## Recebimento (lado app) — passos 1 a 5

## ⚠️ Importante

Desde que o FCM foi integrado, **o build Android exige o `google-services.json`**
e o plugin Gradle do Google Services. Sem eles o `flutter build apk` falha.
O arquivo já está em `app/android/app/google-services.json` (copiado de
`docs/`; ambos fora do git) e o build atual funciona com push ativo.

## Passos

### 1. Crie o projeto Firebase

1. Acesse https://console.firebase.google.com e clique em **Criar projeto**
2. Nome sugerido: `omegadrakon`
3. (Opcional) Ative o Google Analytics — não é necessário

### 2. Registre o app Android

1. No console do projeto, clique em **Android** (ícone + ou "Adicionar app")
2. **Nome do pacote (applicationId):** `com.omegadrakon.nicky`
   - Confirme o valor real em `app/android/app/build.gradle.kts`
   - (se você mudar o applicationId, o `google-services.json` precisa bater)
3. Baixe o **`google-services.json`** gerado

### 3. Coloque a credencial no projeto

```bash
# do diretório raiz do repo
cp ~/Downloads/google-services.json app/android/app/
```

O arquivo **não deve ir para o git** (é segredo do seu projeto Firebase):

```bash
echo "app/android/app/google-services.json" >> app/.gitignore
```

### 4. Ative o plugin Google Services no Gradle

O scaffold gerado (Flutter 3.47+) usa **Kotlin DSL** (`.gradle.kts`). Edite:

**`app/android/settings.gradle.kts`** — dentro do bloco `plugins`:

```kotlin
plugins {
    id("dev.flutter.flutter-plugin-loader") version "1.0.0"
    id("com.android.application") version "9.1.0" apply false
    id("org.jetbrains.kotlin.android") version "2.4.0" apply false
    id("com.google.gms.google-services") version "4.5.0" apply false   // <-- adicione
}
```

**`app/android/app/build.gradle.kts`** — dentro do bloco `plugins`:

```kotlin
plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
    id("com.google.gms.google-services")   // <-- adicione
}
```

> ⚠️ **Compatibilidade AGP 9:** usamos o google-services `4.5.0`, que suporta
> AGP 9 (o `4.4.2` era testado com AGP 8.x).

### 5. Build

```bash
cd app
./build_apk.sh
```

> O `google-services.json` **não vai para o git** (já está no `.gitignore`).
> Depois de configurado, o build do app passa a exigir o arquivo — sem ele o
> Gradle falha com "File google-services.json is missing".

## Testando o push

### Teste de ponta a ponta (o que importa: OD → celular)

1. Instale o APK no celular (com Tailscale ativo), abra e aceite as notificações
2. Confirme que o aparelho se registrou sozinho:
   `curl -H "X-API-Key: CHAVE" http://100.77.67.53:8000/push/devices`
   → `enabled: true`, `devices: 1`
3. Dispare: `POST /push/test` (ver acima) → a notificação aparece mesmo com o
   app em background ou fechado

### Teste do canal (console → celular), sem depender do OD

1. Firebase console → **Messaging** → **Create campaign** → *Firebase Notification*
2. Título `Teste OD`, texto `Push funcionando 🎉`
3. Em *Target*, escolha o app Android e publique (o app não exibe o token FCM,
   então "Send test message" com token não é o caminho aqui)
4. A notificação deve aparecer mesmo com o app em background

## Como funciona no código

**Servidor (OD envia):**

- `core/push.py` — `DeviceRegistry` (tokens em `data/push_devices.json`, upsert
  por token, escrita atômica), `FcmSender` (FCM HTTP v1 com OAuth2 da service
  account; HTTP por urllib) e `PushService` (fachada: `notify`, `sink`, `status`)
- `integrations/api/server.py` — `/push/register`, `/push/unregister`,
  `/push/devices`, `/push/test` (todos com `X-API-Key`)
- `runtime/launcher.py` — `build_push()` monta o serviço e o entrega à API e ao
  Notifier (sink de push); sem a credencial ele sobe **dormente**

**App (recebe e se registra):**

- `app/lib/services/push_service.dart` — inicialização do Firebase, permissão
  (Android 13+), token FCM, handler de mensagens (foreground/background/
  terminado) e `attach(api)` — manda o token para `/push/register`
- `app/lib/services/od_api.dart` — `registerPushToken` / `unregisterPushToken`
- `app/lib/main.dart` — `PushService.instance.init()` no boot e `attach(api)`
  quando há URL + chave (e de novo ao salvar as Configurações)
- `app/android/app/src/main/AndroidManifest.xml` — permissões `POST_NOTIFICATIONS`
  e `WAKE_LOCK`

> O app não mostra o token FCM em nenhuma tela (não há como copiá-lo para o
> "Send test message" do console) — por isso o teste de ponta a ponta é o
> `POST /push/test`, que usa o token que o próprio app registrou.

## Removendo o push (se preferir)

```bash
# 1. Reverta as mudanças de FCM
git checkout app/pubspec.yaml app/lib/main.dart
git rm app/lib/services/push_service.dart
# 2. Reverta o manifest
git checkout app/android/app/src/main/AndroidManifest.xml
# 3. Rode flutter pub get
```