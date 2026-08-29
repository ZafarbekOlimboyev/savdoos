package com.savdoos.savdoos_mobile

import android.view.WindowManager
import io.flutter.embedding.android.FlutterFragmentActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

// local_auth (barmoq izi / Face ID) biometrik dialogi FragmentActivity talab qiladi.
class MainActivity : FlutterFragmentActivity() {
    // Ekran himoyasi (FLAG_SECURE): maxfiy ekranlarда skrinshot / so'nggi-ilovalar
    // ko'rinishini bloklaydi. Faqat login/PIN ekranlarида yoqiladi (Dart tomondan).
    private val secureChannel = "savdoos/secure"

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
    }
}
