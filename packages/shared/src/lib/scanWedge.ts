// ═══ APPARAT SKANER («keyboard wedge») BUFERI ════════════════════════════════
//
// USB/HID barkod skaner — operatsion tizim uchun KLAVIATURA. U barkod belgilarini
// ketma-ket «bosadi» va oxirida `Enter` yuboradi. Hech qanday maxsus hodisa,
// qurilma identifikatori yoki `input` elementi YO'Q: zarbalar shunchaki
// `document.activeElement` ga ketadi, hech narsa fokusda bo'lmasa — `<body>` ga,
// ya'ni HECH QAYERGA.
//
// ⚠️  NEGA VAQT O'LCHANMAYDI. Ko'p «wedge» amalga oshirishlar zarbalar orasidagi
//     millisekundlarni o'lchab skanerni odamdan ajratadi. Bu yerda ATAYLAB
//     ishlatilmadi: chegara skaner modeliga, USB polling tezligiga va renderer
//     yuklamasiga bog'liq bo'lib qoladi — sekin skaner yoki band kadr skanni
//     JIM yo'qotardi, aynan hozir tuzatilayotgan nuqsonning yangi ko'rinishi.
//     Ajratish FOKUS bo'yicha qilinadi (`POSKassa.tsx`): tahrirlanadigan element
//     fokusda bo'lsa — bu odamning yozuvi, uni o'sha element o'zi ishlaydi;
//     fokusda hech narsa bo'lmasa — bu skaner. Qaror DETERMINISTIK.
//
// Bu modul ATAYLAB SOF: DOM ham, vaqt ham, React ham yo'q — holat mashinasi
// yolg'iz sinaladi va «negativ nazorat» testi uchun aniq chok beradi.

/** Barkod deb qabul qilinadigan eng qisqa uzunlik. */
export const WEDGE_MIN_LEN = 4;

export interface Wedge {
  /** Tugmani buferga beradi. Skan TUGAGANDA to'liq barkodni, aks holda `null`. */
  push(key: string): string | null;
  /** Buferni tozalaydi (fokus/holat o'zgarganda). */
  reset(): void;
  /** Sinovlar uchun: hozirgi bufer. */
  peek(): string;
}

//  Skaner katta harf yuborishda `Shift` ni ham bosadi; bu tugmalar buferni
//  BUZMASLIGI kerak, aks holda Code-128 kabi harfli barkod yarmida uzilardi.
const MODIFIERS = new Set(["Shift", "Control", "Alt", "Meta", "AltGraph", "CapsLock", "Dead"]);

//  FAQAT harf/raqam yig'iladi. `+`, `-`, `=`, `_` ATAYLAB tashqarida: ular
//  POS'ning global yorliqlari (miqdorni ±1 qilish) va ularni buferga olish
//  kassirning klaviatura yorliqlarini o'g'irlardi. Do'kon barkodlari EAN-13
//  (raqam).
const BARCODE_CHAR = /^[0-9A-Za-z]$/;

export function createWedge(minLen: number = WEDGE_MIN_LEN): Wedge {
  let buf = "";
  //  ⚠️  UZILISH BAYROG'I — ADVERSARIAL KO'RIKDA TOPILGAN PUL NUQSONI.
  //      Ilgari burst yarmidagi har qanday «boshqa» tugma buferni JIMGINA
  //      tozalardi, keyin qolgan belgilar YANGI burst bo'lib yig'ilardi va
  //      `Enter` o'sha DUMNI da'vo qilardi. Natija o'lchangan: `ART-12-345678`
  //      etiketkasi (server `-` ni olib tashlab `12345678` deb saqlaydi)
  //      skanerlansa, dum `345678` BOSHQA mahsulotning haqiqiy barkodi bo'lsa
  //      — kassir bexabar BOSHQA mahsulotni sotardi, xatosiz. Ayni narsa
  //      kirill klaviatura sxemasida ham: harf `BARCODE_CHAR` dan o'tmaydi.
  //
  //      Endi burst uzilsa u «iflos» bo'ladi va `Enter` HECH NARSA da'vo
  //      qilmaydi — kassir «Mahsulot topilmadi» xabarini ko'radi, bu esa
  //      boshqa mahsulot sotilishidan QAT'IYAN yaxshi.
  //
  //      BO'SH buferdagi reset esa TOZA qoladi: shu sababli skanerning
  //      sozlangan prefiksi (masalan `~` yoki STX) skanni buzmaydi.
  let dirty = false;
  return {
    push(key: string): string | null {
      if (key.length === 1 && BARCODE_CHAR.test(key)) {
        buf += key;
        return null;
      }
      if (key === "Enter") {
        //  Qisqa YOKI uzilgan bufer — barkod EMAS: jimgina tashlanadi va
        //  `Enter` o'z standart ishini bajarishi uchun DA'VO QILINMAYDI.
        const out = !dirty && buf.length >= minLen ? buf : null;
        buf = "";
        dirty = false;
        return out;
      }
      if (MODIFIERS.has(key)) return null;
      //  Boshqa har qanday tugma (Tab, Escape, F2, `-`, o'q tugmalari…) — skan
      //  ketma-ketligi UZILDI.
      if (buf.length) dirty = true;
      buf = "";
      return null;
    },
    reset(): void {
      buf = "";
      dirty = false;
    },
    peek(): string {
      return buf;
    },
  };
}

/** Tahrirlanadigan element — odam yozayotgan joy. Skaner yo'li bu yerda ISHLAMAYDI. */
export function isEditableTarget(el: Element | null): boolean {
  if (!el) return false;
  const tag = el.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  return (el as HTMLElement).isContentEditable === true;
}
