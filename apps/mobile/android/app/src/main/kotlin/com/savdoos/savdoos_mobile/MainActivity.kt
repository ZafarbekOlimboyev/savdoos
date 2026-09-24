package com.savdoos.savdoos_mobile

import android.content.Intent
import android.net.Uri
import android.provider.Settings
import android.view.WindowManager
import io.flutter.embedding.android.FlutterFragmentActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

// local_auth (barmoq izi / Face ID) biometrik dialogi FragmentActivity talab qiladi.
class MainActivity : FlutterFragmentActivity() {
    // Ekran himoyasi (FLAG_SECURE): maxfiy ekranlarда skrinshot / so'nggi-ilovalar
    // ko'rinishini bloklaydi. Faqat login/PIN ekranlarида yoqiladi (Dart tomondan).
    private val secureChannel = "savdoos/secure"

    // Ilova sozlamalari sahifasi: kamera ruxsati BUTUNLAY rad etilganda
    // (Android "boshqa so'rama") qayta so'rash imkoni yo'q — operatorни to'g'ridan-to'g'ri
    // shu ilovaning ruxsatlar sahifasiga olib boramiz. Boshqa platformalarда bu kanal
    // umuman yo'q: Dart tomoni MissingPluginException'ni "qo'llab-quvvatlanmaydi" deb
    // o'qiydi va tugmani KO'RSATMAYDI (yo'q eshikni va'da qilmaymiz).
    private val appSettingsChannel = "savdoos/app_settings"

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, secureChannel)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "on" -> {
                        runOnUiThread {
                            window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
                        }
                        result.success(null)
                    }
                    "off" -> {
                        runOnUiThread {
                            window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
                        }
                        result.success(null)
                    }
                    else -> result.notImplemented()
                }
            }

        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, appSettingsChannel)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    // Android'да har doim bor. Dart tomoni shu javobga qarab tugmani ko'rsatadi.
                    "supported" -> result.success(true)
                    "open" -> result.success(openAppSettings())
                    else -> result.notImplemented()
                }
            }
    }

    // ACTION_APPLICATION_DETAILS_SETTINGS + "package:<applicationId>" — AYNAN shu
    // ilovaning ruxsatlar sahifasi (umumiy sozlamalar emas). Hech qanday yangi
    // ruxsat talab qilmaydi. Qaytadi: ochildimi (false bo'lsa Dart tomoni matn bilan
    // tushuntiradi va qo'lda kiritishни taklif qiladi).
    private fun openAppSettings(): Boolean = try {
        val intent = Intent(
            Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
            Uri.fromParts("package", packageName, null)
        )
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        startActivity(intent)
        true
    } catch (e: Exception) {
        false
    }
}
