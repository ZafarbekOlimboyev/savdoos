// Ekrandagi HAMMA matn shu yerda — kompozitsiya kodida matn yo'q.
//
// Yangi til (rus, qirg'iz) qo'shish = shu faylga bitta obyekt + UI suratlarini
// o'sha tilda qayta olish (`PROMO_LANG=ru node capture/capture.mjs`). Kompozitsiya
// qayta yozilmaydi.
//
// Qoida: har bir zarbada 2–6 so'z. Reklama — taqdimot emas.
// ⚠️  Raqam, foiz, mijozlar soni kabi TASDIQLANMAGAN da'volar yozilmaydi.

export type Lang = 'uz' | 'ru' | 'ky';

export interface Copy {
  hook: [string, string];
  pos: { pill: string; title: [string, string] };
  end: { line: string; tagline: [string, string] };
}

const uz: Copy = {
  hook: ['DO‘KONINGIZ', 'BITTA TIZIMDA.'],
  pos: { pill: 'Kassa', title: ['SAVDO.', 'TEZ VA ODDIY.'] },
  end: { line: 'Do‘kon qanday ishlashi kerak.', tagline: ['BITTA TIZIM.', 'BITTA HAQIQAT.'] },
};

const COPY: Partial<Record<Lang, Copy>> = { uz };

export function copyFor(lang: Lang): Copy {
  const c = COPY[lang];
  // Tarjima yo'q bo'lsa JIM o'zbekchaga tushmaymiz: "ru" deb chiqarilgan video
  // ichida o'zbek matni bo'lishi — ko'rinmas xato.
  if (!c) throw new Error(`"${lang}" tilidagi matn hali yozilmagan (src/copy.ts)`);
  return c;
}
