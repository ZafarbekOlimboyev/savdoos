import 'package:flutter/foundation.dart';

import 'secret_store.dart';
import 'secret_store_plugin.dart';

/// Android (Keystore-wrapped EncryptedSharedPreferences), iOS (Keychain) and
/// desktop (OS credential store): the medium is protected from other apps.
SecretStore createSecretStore() => const PluginSecretStore(hardwareBacked: true);

/// Test hook: the Android options the store was built with.
@visibleForTesting
Map<String, String> debugAndroidOptions(SecretStore store) => PluginSecretStore.storage.aOptions.toMap();
