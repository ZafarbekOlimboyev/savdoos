# SavdoOS — R8/ProGuard keep qoidalari (release minify uchun).
# Maqsad: kodни qisqartirish/obfuskatsiya qilinganда reflection bilan ishlaydigan
# plaginlar (ML Kit shtrix-kod, Flutter engine) buzilmasin.

# ── Flutter engine + plaginlar (odatda avtomatik qo'shiladi, ehtiyot uchun) ──
-keep class io.flutter.** { *; }
-keep class io.flutter.plugins.** { *; }
-dontwarn io.flutter.embedding.**

# ── Google Play Core (Flutter deferred-components referensi — biz ishlatmaymiz) ──
# Bu qoidalarsiz R8 "missing class com.google.android.play.core.**" bilan build'ni to'xtatishi mumkin.
-dontwarn com.google.android.play.core.**
-keep class com.google.android.play.core.** { *; }

# ── ML Kit shtrix-kod (mobile_scanner) — modelni reflection bilan yuklaydi ──
-keep class com.google.mlkit.** { *; }
-keep class com.google.android.gms.internal.mlkit_** { *; }
-dontwarn com.google.mlkit.**

# ── Umumiy: native metodlar, annotatsiyalar, imzolar ──
-keepclasseswithmembernames class * { native <methods>; }
-keepattributes *Annotation*, Signature, InnerClasses, EnclosingMethod
