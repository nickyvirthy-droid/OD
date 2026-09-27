package com.omegadrakon.nicky

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import androidx.core.content.FileProvider
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File

/**
 * OmegaDrakon • canal nativo da AUTO-ATUALIZAÇÃO (v1.7.0)
 *
 * O Dart baixa o APK novo para o cache privado do app e pede dois serviços:
 *   - cacheDir: a pasta de cache (o APK precisa ficar num caminho que o
 *     instalador consiga ler via FileProvider);
 *   - installApk: dispara ACTION_INSTALL_PACKAGE apontando para o arquivo.
 *
 * Permissões necessárias (AndroidManifest): REQUEST_INSTALL_PACKAGES e, no
 * Android 8+, o usuário concede "Instalar apps desconhecidos" na própria
 * tela que o sistema abre.
 */
class MainActivity : FlutterActivity() {

    private val channelName = "com.omegadrakon.nicky/updater"

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "cacheDir" -> result.success(cacheDir.absolutePath)
                    "installApk" -> {
                        val path = call.argument<String>("path")
                        if (path.isNullOrBlank()) {
                            result.error("invalid_args", "path ausente", null)
                            return@setMethodCallHandler
                        }
                        try {
                            installApk(File(path))
                            result.success(null)
                        } catch (error: Exception) {
                            result.error("install_failed", error.message, null)
                        }
                    }
                    else -> result.notImplemented()
                }
            }
    }

    /** Instala o APK via FileProvider (content:// — exigido desde o Android 7). */
    private fun installApk(apk: File) {
        if (!apk.isFile) {
            throw IllegalArgumentException("APK não encontrado: ${apk.path}")
        }
        val uri: Uri = FileProvider.getUriForFile(
            this, "${applicationContext.packageName}.fileprovider", apk
        )
        val intent = Intent(Intent.ACTION_INSTALL_PACKAGE).apply {
            data = uri
            flags = Intent.FLAG_GRANT_READ_URI_PERMISSION or
                Intent.FLAG_ACTIVITY_NEW_TASK
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
            !packageManager.canRequestPackageInstalls()
        ) {
            // Sem a permissão de "fontes desconhecidas", manda o usuário
            // direto para a tela de concessão deste app.
            val settings = Intent(
                android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                Uri.parse("package:$packageName")
            ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            startActivity(settings)
        }
        startActivity(intent)
    }
}
