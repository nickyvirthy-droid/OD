import 'dart:convert';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';

/// Callback executado quando uma mensagem chega com o app em background.
/// Precisa ser uma função top-level anotada para o engine chamar.
@pragma('vm:entry-point')
Future<void> odOnBackgroundMessage(RemoteMessage message) async {
  await Firebase.initializeApp();
  await PushService.instance.show(message);
}

/// Serviço de push notifications via Firebase Cloud Messaging (FCM).
///
/// Recebe mensagens remotas do ProactiveNotifier / RecoveryLoop do OD e as
/// exibe como notificações locais (Android 13+ exige POST_NOTIFICATIONS).
///
/// ⚠️ IMPORTANTE: nada aqui pode lançar ou travar o boot do app. O singleton
/// NÃO constrói `FirebaseMessaging.instance` no campo (isso chama
/// `Firebase.app()`, que lança se o Firebase ainda não foi inicializado —
/// exceção síncrona no main() = tela preta). O _messaging é criado apenas
/// DENTRO de init(), depois do `Firebase.initializeApp()`.
class PushService {
  PushService._();

  static final PushService instance = PushService._();

  final FlutterLocalNotificationsPlugin _local =
      FlutterLocalNotificationsPlugin();

  /// Criado só após [Firebase.initializeApp()] em [init] — nunca no campo.
  FirebaseMessaging? _messaging;
  bool _localReady = false;

  String? _token;

  /// Token FCM deste dispositivo (para registrar no servidor, se desejado).
  String? get token => _token;

  /// Inicializa Firebase, notificações locais, permissão e handlers.
  ///
  /// Best-effort de ponta a ponta: cada etapa é protegida por _safe() e
  /// main() chama sem await — Firebase travado ou com erro nunca impede
  /// a primeira tela de renderizar.
  Future<void> init() async {
    try {
      await Firebase.initializeApp();
    } catch (_) {
      return; // Firebase não configurado — push desativado, app segue normal
    }

    // Só agora o app existe — FirebaseMessaging.instance não lança mais.
    final messaging = _messaging ??= FirebaseMessaging.instance;

    await _safe(_initLocalNotifications);
    await _safe(() => _requestPermission(messaging));
    await _safe(() => _refreshToken(messaging));

    await _safe(() async {
      FirebaseMessaging.onMessage.listen(show);
      FirebaseMessaging.onBackgroundMessage(odOnBackgroundMessage);
      FirebaseMessaging.onMessageOpenedApp.listen(show);

      final initial = await messaging.getInitialMessage();
      if (initial != null) await show(initial);
    });
  }

  /// Roda um passo protegido — exceções são engolidas (best-effort).
  Future<void> _safe(Future<void> Function() step) async {
    try {
      await step();
    } catch (_) {
      // Nunca deixa o push quebrar ou travar o app.
    }
  }

  /// Exibe a mensagem como notificação local (best-effort, nunca lança).
  Future<void> show(RemoteMessage message) async {
    try {
      await _initLocalNotifications();

      final title = message.notification?.title ?? 'OmegaDrakon';
      final body =
          message.notification?.body ?? message.data['message'] ?? '';

      await _local.show(
        message.messageId.hashCode,
        title,
        body,
        const NotificationDetails(
          android: AndroidNotificationDetails(
            'od_alerts',
            'Alertas OmegaDrakon',
            channelDescription: 'Alertas do OD: proativos, recovery e presença',
            importance: Importance.high,
            priority: Priority.high,
          ),
        ),
        payload: jsonEncode(message.data),
      );
    } catch (_) {
      // Notificação é best-effort; nunca derruba o app.
    }
  }

  Future<void> _initLocalNotifications() async {
    if (_localReady) return;
    const settings = AndroidInitializationSettings('@mipmap/ic_launcher');
    await _local.initialize(
      const InitializationSettings(android: settings),
      onDidReceiveNotificationResponse: (_) {},
    );
    _localReady = true;
  }

  Future<void> _requestPermission(FirebaseMessaging messaging) async {
    final settings = await messaging.requestPermission(
      alert: true,
      badge: true,
      sound: true,
    );
    final status = settings.authorizationStatus;
    if (status != AuthorizationStatus.authorized &&
        status != AuthorizationStatus.provisional) {
      return;
    }

    final android = _local
        .resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>();
    await android?.requestNotificationsPermission();
  }

  Future<void> _refreshToken(FirebaseMessaging messaging) async {
    try {
      _token = await messaging.getToken();
    } catch (_) {
      // Sem token ainda — o listener abaixo atualiza quando chegar.
    }
    messaging.onTokenRefresh.listen((token) => _token = token);
  }
}