// BinOS promo — vizual tokenlar.
//
// Rang manbai — ASL logo (`public/brand/binos-logo-source.webp`): nishon foni
// navy #011A44, "B" gradienti ko'k → feruza → yashil. Video dunyosi shu navy;
// aksent — logoning gradienti.
//
// ⚠️  Mahsulot UI'sining o'z aksenti binafsha (#6d5dd3, `packages/shared/src/styles.css`).
//     UI suratlari O'ZGARTIRILMAYDI — binafsha faqat haqiqiy ekran ichida ko'rinadi,
//     video ramkasiga (fon, matn, nur) qo'shilmaydi.

export const C = {
  navy950: '#010A1C',
  navy900: '#011A44', // logo nishoni foni
  navy800: '#06265C',
  navy600: '#0E4A8F',
  blue: '#0E5AA7', // logo gradientining boshi
  teal: '#14B8B0',
  green: '#2EE58F', // logo gradientining oxiri
  white: '#FFFFFF',
  mist: '#A9B8D4', // ikkinchi darajali matn (navy ustida o'qiladi)
  ink: '#0B1426',
} as const;

// Matndagi aksent: logoning ochiq qismi (navy ustida kontrast yetarli).
export const ACCENT_GRADIENT = `linear-gradient(92deg, #45C8F0 0%, ${C.teal} 45%, ${C.green} 100%)`;

export const FONT = `'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif`;

export const W = 1080;
export const H = 1920;
export const FPS = 30;
