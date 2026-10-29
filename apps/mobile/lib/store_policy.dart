import 'platform/platform.dart';

/// What the app may say about BinOS plans, per distribution channel.
///
/// The native iOS app ships through the App Store, where showing other plans or
/// telling the user to raise or change a plan outside the app is an App Store
/// Review Guideline 3.1.1 / 3.1.3 risk. So on iOS the Tarif entry is hidden and
/// a plan limit is stated as a plain fact. Android and the web build keep their
/// tariff screen and wording unchanged.
///
/// UX ONLY, like ShellGates: the server still enforces every plan limit.
class StorePolicy {
  StorePolicy._();

  /// Whether plan details and "raise your plan" prompts may be shown.
  static bool get showsPlanUpsell => !AppPlatform.isNativeIos;
}
