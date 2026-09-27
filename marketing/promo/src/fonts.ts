import { continueRender, delayRender, staticFile } from 'remotion';

// Shriftlar kadr chizilishidan OLDIN yuklanadi: aks holda birinchi kadrlar
// zaxira shrift bilan chiqib, keyin "sakraydi" (render deterministik bo'lmaydi).
const WEIGHTS = [500, 600, 700, 800, 900] as const;

let loaded: Promise<void> | null = null;

export function loadFonts(): void {
  if (loaded) return;
  const handle = delayRender('Inter shriftlari');
  loaded = Promise.all(
    WEIGHTS.map(async (w) => {
      const face = new FontFace('Inter', `url(${staticFile(`fonts/inter-latin-${w}-normal.woff2`)}) format('woff2')`, {
        weight: String(w),
        style: 'normal',
      });
      await face.load();
      // TS lib.dom ba'zi versiyalarida `FontFaceSet.add` e'lon qilinmagan.
      (document.fonts as unknown as { add(f: FontFace): void }).add(face);
    }),
  ).then(() => continueRender(handle));
}
