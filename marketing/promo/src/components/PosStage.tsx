import React from 'react';
import { Img, staticFile } from 'remotion';

/**
 * HAQIQIY POS suratlari sahnasi.
 *
 * Koordinatalar — POS'ning CSS pikselida (1920x1080), `capture/capture.mjs`
 * manifestidagi qutilar bilan AYNAN bir xil. Suratlar DSF 2 da olingan
 * (3840x2160), shu bois kamera 1.3x gacha yaqinlashsa ham matn tiniq qoladi.
 *
 * Kamera: POS nuqtasi (fx, fy) ekrandagi (sx, sy) ga tushadi, masshtab `s`.
 */
export type Box = { x: number; y: number; w: number; h: number };

export interface Cam {
  s: number;
  fx: number;
  fy: number;
  sx: number;
  sy: number;
  rotX?: number;
  opacity?: number;
  blur?: number;
}

const POS_W = 1920;
const POS_H = 1080;
const RADIUS = 26; // ekran pikselida

export const PosStage: React.FC<{ cam: Cam; children: React.ReactNode }> = ({ cam, children }) => {
  const { s, fx, fy, sx, sy, rotX = 0, opacity = 1, blur = 0 } = cam;
  const left = sx - fx * s;
  const top = sy - fy * s;
  return (
    <div
      style={{
        position: 'absolute',
        left: 0,
        top: 0,
        width: POS_W,
        height: POS_H,
        transformOrigin: '0 0',
        transform: `translate(${left}px, ${top}px) scale(${s})`,
        perspective: `${2400 / s}px`,
      }}
    >
      <div
        style={{
          position: 'absolute',
          inset: 0,
          borderRadius: RADIUS / s,
          overflow: 'hidden',
          background: '#eceef4',
          transformOrigin: '50% 100%',
          transform: rotX ? `rotateX(${rotX}deg)` : undefined,
          opacity,
          filter: blur > 0 ? `blur(${blur / s}px)` : undefined,
          boxShadow: `0 0 0 ${1.5 / s}px rgba(255,255,255,0.14), 0 ${50 / s}px ${140 / s}px rgba(0,0,0,0.55)`,
        }}
      >
        {children}
      </div>
    </div>
  );
};

/** Butun ekran surati (baza qatlam). */
export const PosShot: React.FC<{ file: string; opacity?: number }> = ({ file, opacity = 1 }) => (
  <Img
    src={staticFile(`ui/pos/${file}`)}
    style={{ position: 'absolute', left: 0, top: 0, width: POS_W, height: POS_H, opacity }}
  />
);

/**
 * "Yamoq": boshqa holat suratining bir qutisi — AYNI joyda. Harakat faqat
 * shu quti ichida bo'ladi, piksellar esa haqiqiy UI'niki.
 */
export const Patch: React.FC<{
  file: string;
  box: Box;
  style?: React.CSSProperties;
  inner?: React.CSSProperties;
  clipRight?: number; // qutining o'ng tomonidan kesiladigan px (yozilish effekti)
}> = ({ file, box, style, inner, clipRight }) => (
  <div
    style={{
      position: 'absolute',
      left: box.x,
      top: box.y,
      width: box.w,
      height: box.h,
      overflow: 'hidden',
      clipPath: clipRight !== undefined ? `inset(0 ${clipRight}px 0 0)` : undefined,
      ...style,
    }}
  >
    <Img
      src={staticFile(`ui/pos/${file}`)}
      style={{ position: 'absolute', left: -box.x, top: -box.y, width: POS_W, height: POS_H, ...inner }}
    />
  </div>
);

/**
 * Summa "slot" kabi aylanadi (masalan JAMI: 0 → 9 000).
 *
 * `box` — ikkala holatdagi summa qutilarining birlashmasi. Ikkala kesim ham
 * TO'LIQ shaffofmas va surilish masofasi aynan quti balandligi — ya'ni ular
 * orasida bo'shliq ham, ustma-ust tushish ham yo'q: ostidagi baza ko'rinmaydi
 * (ilgari yarim shaffof kesimlar orasidan yangi baza ko'rinib, ikki raqam
 * ustma-ust chiqardi).
 */
export const Roll: React.FC<{ from: string; to: string; box: Box; p: number }> = ({ from, to, box, p }) => {
  const d = box.h;
  return (
    <div style={{ position: 'absolute', left: box.x, top: box.y, width: box.w, height: box.h, overflow: 'hidden' }}>
      <Patch file={from} box={{ ...box, x: 0, y: 0 }} inner={{ left: -box.x, top: -box.y - p * d }} />
      <Patch file={to} box={{ ...box, x: 0, y: 0 }} inner={{ left: -box.x, top: -box.y + (1 - p) * d }} />
    </div>
  );
};

/** Ikki holatdagi summa qutilarining birlashmasi (+ kichik zaxira). */
export function unionBox(a: Box, b: Box, pad = 3): Box {
  const x = Math.min(a.x, b.x) - pad;
  const y = Math.min(a.y, b.y) - pad;
  const r = Math.max(a.x + a.w, b.x + b.w) + pad;
  const btm = Math.max(a.y + a.h, b.y + b.h) + pad;
  return { x, y, w: r - x, h: btm - y };
}
