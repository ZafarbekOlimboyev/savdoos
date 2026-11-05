import { useEffect, useRef } from "react";
import { createWedge, isEditableTarget, WEDGE_MIN_LEN } from "./scanWedge";

// ═══ UNIVERSAL APPARAT-SKANER YO'LI ═════════════════════════════════════════
//
//   Fizik skaner
//        ↓
//   createWedge()  — barkod buferi (sof holat mashinasi, `scanWedge.ts`)
//        ↓
//   useBarcodeScanner()  — YAGONA ushlash mexanizmi (shu fayl)
//        ↓
//   ekranning O'Z handleri  — semantika ekranga tegishli
//
// Ekranma-ekran alohida wedge YOZILMAYDI: ushlash qoidasi (qachon bu skaner,
// qachon odam) bir joyda turadi, ekran esa faqat «topilgan kod bilan nima
// qilish»ni aytadi.
//
// ⚠️  GLOBAL SINGLETON YO'Q. Har chaqiruv o'z buferi va o'z tinglovchisiga ega;
//     ekranlar orasida yashirin umumiy holat saqlanmaydi. Ikki ekran bir vaqtda
//     ulangan bo'lsa (marshrut almashuvi) ham bitta skan IKKI MARTA ishlanmaydi
//     — buni modul darajasidagi o'zgaruvchi emas, HODISANING O'ZI hal qiladi:
//     da'vo qilgan birinchi tinglovchi `preventDefault()` chaqiradi, keyingisi
//     esa `e.defaultPrevented` ni ko'rib chetga chiqadi.
//
// ⚠️  STRICTMODE / PRODUCTION PARITETI. `apps/*/src/main.tsx` ilovani
//     `React.StrictMode` ga o'raydi, ya'ni DEV'da effekt mount → unmount →
//     mount bo'ladi; paketlangan .exe'da esa BIR MARTA. Shu bois:
//       · bufer effekt ICHIDA yaratiladi (qayta mount toza bufer beradi);
//       · tozalash HAMMA tinglovchini olib tashlaydi (ikki marta obuna bo'lib
//         har skan ikki marta ishlanmasin);
//       · «birinchi yurishni o'tkazib yuborish» naqshi ISHLATILMAYDI — aynan
//         shu naqsh (ref + skip) dev va prod xulqini AJRATIB, apparat skaner
//         nuqsonini relizgacha olib borgan edi.

export interface BarcodeScannerOptions {
  /** Burst `Enter` bilan tugaganda chaqiriladi. Kod — xom bufer (raqam/harf). */
  onScan: (code: string) => void;
  /**
   * Ekran skanni QABUL QILISHGA tayyormi. `false` bo'lsa bufer tozalanadi va
   * hodisa TEGILMAYDI (da'vo ham qilinmaydi) — ya'ni modal/dialog ortida savat
   * yoki hujjat skan bilan qimirlamaydi.
   */
  enabled?: boolean;
  /** Barkod deb qabul qilinadigan eng qisqa uzunlik. */
  minLen?: number;
}

export function useBarcodeScanner({ onScan, enabled = true, minLen = WEDGE_MIN_LEN }: BarcodeScannerOptions): void {
  //  Tinglovchi `[]` deps bilan BIR MARTA obuna bo'ladi; handler va holat esa
  //  har renderda yangilanadi. Shu bois ular REF orqali o'qiladi — aks holda
  //  effekt har renderda qayta ulanib, burst o'rtasida bufer yo'qolardi.
  const onScanRef = useRef(onScan);
  onScanRef.current = onScan;
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  useEffect(() => {
    const wedge = createWedge(minLen);
    const onKey = (e: KeyboardEvent) => {
      //  Yorliq birikmasi (Ctrl/Alt/Cmd) — skaner EMAS.
      if (e.ctrlKey || e.altKey || e.metaKey) { wedge.reset(); return; }
      //  Ekran tayyor emas (modal/dialog/boshqa ko'rinish).
      if (!enabledRef.current) { wedge.reset(); return; }
      //  ODAM tahrirlanadigan maydonda yozmoqda (qidiruv, summa, nom, miqdor…).
      //  Zarbalar O'SHA elementga tegishli va uning o'z handleri ishlaydi — shu
      //  bois bu yo'l CHETDA turadi. Ikki yo'lning O'ZARO INKORI aynan shu
      //  shartda: bitta skan ikki marta ishlanishi mumkin emas.
      if (isEditableTarget(document.activeElement)) { wedge.reset(); return; }
      //  Boshqa bir tinglovchi (masalan ikkinchi ulangan ekran) allaqachon
      //  da'vo qilgan — ikkinchi marta ishlamaymiz.
      if (e.defaultPrevented) { wedge.reset(); return; }

      const code = wedge.push(e.key);
      if (code === null) return;
      //  Skan DA'VO QILINDI. `preventDefault` SHART: fokus tugmada bo'lsa
      //  skanerning `Enter` i o'sha tugmani BOSARDI (o'lchangan nuqson: qo'lda
      //  kirimda «qator qo'shish» tugmasi bosilib YANGI BO'SH QATOR qo'shilardi).
      //  Bufer qisqa yoki uzilgan bo'lsa da'vo QILINMAYDI va `Enter` o'z
      //  standart ishini bajaradi — klaviatura bilan boshqarish buzilmaydi.
      e.preventDefault();
      e.stopPropagation();
      onScanRef.current(code);
    };
    //  ── BURST CHEGARALARI (vaqt o'lchamasdan) ───────────────────────────────
    //  Odam o'rtaga tushsa (bosish, fokus almashishi, oynani almashtirish) yarim
    //  bufer keyingi skanga PREFIKS bo'lib qo'shilmasin. Inter-key millisekund
    //  chegarasi ATAYLAB ishlatilmaydi — u skaner modeliga va renderer
    //  yuklamasiga bog'liq bo'lib, sekin skanerni JIM yo'qotardi.
    const drop = () => wedge.reset();
    //  CAPTURE fazasi: tugmaning standart «bosilishi»dan va boshqa
    //  tinglovchilardan OLDIN qaror qilinadi.
    window.addEventListener("keydown", onKey, true);
    window.addEventListener("pointerdown", drop, true);
    window.addEventListener("focusin", drop, true);
    document.addEventListener("visibilitychange", drop);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener("pointerdown", drop, true);
      window.removeEventListener("focusin", drop, true);
      document.removeEventListener("visibilitychange", drop);
    };
    //  `minLen` ATAYLAB bog'liqlik: u o'zgarsa bufer qoidasi o'zgaradi.
  }, [minLen]);
}
