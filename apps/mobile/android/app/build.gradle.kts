import java.util.Properties
import java.io.FileInputStream

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// Play release imzolash sirlari (android/key.properties — repo'ga KIRMAYDI)
val keystoreProperties = Properties()
val keystorePropertiesFile = rootProject.file("key.properties")
if (keystorePropertiesFile.exists()) {
    keystoreProperties.load(FileInputStream(keystorePropertiesFile))
}

android {
    namespace = "com.savdoos.savdoos_mobile"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.savdoos.savdoos_mobile"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        create("release") {
            if (keystorePropertiesFile.exists()) {
                keyAlias = keystoreProperties["keyAlias"] as String
                keyPassword = keystoreProperties["keyPassword"] as String
                storeFile = file(keystoreProperties["storeFile"] as String)
                storePassword = keystoreProperties["storePassword"] as String
            }
        }
    }

    buildTypes {
        release {
            // XAVFSIZLIK: release APK/AAB HAQIQIY kalit bilan imzolanishi shart.
            // key.properties yo'q bo'lsa — jimgina debug kalitga tushib ketmaymiz (tasodifan
            // debug-imzoli release chiqib ketmasin). Faqat -PallowDebugSigning bilan lokal
            // `flutter run --release` uchun ataylab ruxsat beriladi.
            val allowDebug = project.hasProperty("allowDebugSigning")
            if (keystorePropertiesFile.exists()) {
                signingConfig = signingConfigs.getByName("release")
            } else if (allowDebug) {
                signingConfig = signingConfigs.getByName("debug")
            } else {
                throw org.gradle.api.GradleException(
                    "Release imzo kaliti topilmadi (android/key.properties yo'q). " +
                    "Play uchun release kalit kerak. Lokal test uchun: -PallowDebugSigning."
                )
            }
            // Kodni qisqartirish + obfuskatsiya (Java/Kotlin qatlami; Dart allaqachon native).
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
