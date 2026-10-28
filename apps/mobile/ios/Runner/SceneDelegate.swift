import Flutter
import UIKit

/// Ilova sahnasi + APP SWITCHER MAXFIYLIGI pardasi.
///
/// ⚠️  NEGA BU KERAK. iOS ilova fonga chiqqanda ekranning SURATINI oladi va
///     uni App Switcher'da ko'rsatadi. Bu surat diskda saqlanadi va ilova
///     qulflangan bo'lsa ham ko'rinadi: telefonni qo'liga olgan kishi
///     ilovani OCHMASDAN, PIN ham, Face ID ham so'ralmasdan oxirgi ekranni
///     o'qiy oladi — savdo, kassa, qarz va mijoz raqamlarini.
///
///     Flutter tomonidagi qulf (`AppLockBarrier`) buni TO'SMAYDI: u faqat
///     ilova ichidagi daraxtni boshqaradi, iOS esa suratni oynadan oladi.
///     O'lchangan dalil: `~/Documents/BinOS-iOS-Evidence/r6-simulator/
///     RED-appswitcher-ekran-korinadi.png`.
///
///     Yechim Apple'ning tavsiya etgan yo'li: sahna faolligini yo'qotishidan
///     OLDIN oyna ustiga NOSHAFFOF parda qo'yiladi, qaytganda olib tashlanadi.
///     Parda `LaunchScreen` storyboard'idan quriladi — foydalanuvchi uni
///     ilovaning odatiy ochilish ekrani deb qabul qiladi.
///
/// ⚠️  TARTIB MUHIM. Parda `sceneWillResignActive` da qo'yiladi (Control
///     Center, bildirishnoma pardasi va chaqiruv bannerlari uchun ham) VA
///     `sceneDidEnterBackground` da qayta tasdiqlanadi — iOS suratni aynan
///     shu ikki nuqta orasida oladi.
///
/// ⚠️  POYGA. Parda `sceneDidBecomeActive` da olib tashlanadi, lekin Flutter
///     o'zining `resumed` hodisasini KEYINROQ oladi — ya'ni qulf qaroriga
///     (`Lock.consumeResume`) qadar bir necha kadr o'tishi mumkin. Shu
///     oraliqda ma'lumot ko'rinmasligi uchun Flutter tomonda IKKINCHI parda
///     bor (`AppLockBarrier` ning `_obscured` holati), u `inactive` da
///     yoqiladi va faqat `resumed` da, qulf qarori chiqqandan keyin o'chadi.
///     Ya'ni native parda olingan paytda Flutter pardasi hali turadi.
class SceneDelegate: FlutterSceneDelegate {

  /// Hozir oyna ustida turgan parda (bo'lsa).
  private var privacyCover: UIView?

  // MARK: - Sahna hayotiy sikli

  override func sceneWillResignActive(_ scene: UIScene) {
    super.sceneWillResignActive(scene)
    showPrivacyCover(in: scene)
  }

  override func sceneDidEnterBackground(_ scene: UIScene) {
    // Kafolat: ba'zi o'tishlarda surat aynan shu yerdan keyin olinadi.
    showPrivacyCover(in: scene)
    super.sceneDidEnterBackground(scene)
  }

  override func sceneDidBecomeActive(_ scene: UIScene) {
    super.sceneDidBecomeActive(scene)
    hidePrivacyCover()
  }

  // MARK: - Parda

  private func showPrivacyCover(in scene: UIScene) {
    guard privacyCover == nil,
          let windowScene = scene as? UIWindowScene,
          let window = windowScene.windows.first(where: { $0.isKeyWindow })
            ?? windowScene.windows.first
    else { return }

    let cover = makeCoverView()
    cover.frame = window.bounds
    cover.autoresizingMask = [.flexibleWidth, .flexibleHeight]
    // ⚠️  Oynaning ENG USTIGA: ostidagi Flutter view hech qanday holatda
    //     surat ichiga tushmasin.
    window.addSubview(cover)
    window.bringSubviewToFront(cover)
    privacyCover = cover
  }

  private func hidePrivacyCover() {
    privacyCover?.removeFromSuperview()
    privacyCover = nil
  }

  /// `LaunchScreen` storyboard'idan parda. U yuklanmasa — noshaffof zaxira.
  private func makeCoverView() -> UIView {
    if let view = UIStoryboard(name: "LaunchScreen", bundle: .main)
      .instantiateInitialViewController()?.view {
      view.isOpaque = true
      if view.backgroundColor == nil || view.backgroundColor == .clear {
        view.backgroundColor = .black
      }
      return view
    }
    // ⚠️  Zaxira ATAYLAB qora va noshaffof: storyboard nomi o'zgarsa ham
    //     parda YO'QOLMASLIGI kerak — aks holda maxfiylik jim buziladi.
    let fallback = UIView()
    fallback.backgroundColor = .black
    fallback.isOpaque = true
    return fallback
  }
}
