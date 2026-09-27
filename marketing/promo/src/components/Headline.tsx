import React from 'react';

import { ACCENT_GRADIENT, C, FONT } from '../theme';

/**
 * Qatorma-qator "niqobli" chiqish: har qator o'z qutisi ichidan pastdan
 * ko'tariladi (overflow: hidden), kechikish bilan. `accent` — ikkinchi qator
 * logo gradientida.
 *
 * `enter` va `exit` 0..1 — kompozitsiya vaqt jadvalidan beriladi.
 */
export const Headline: React.FC<{
  lines: [string, string];
  size: number;
  top: number;
  enter: [number, number]; // har qator uchun 0..1
  exit?: number; // 0..1
  accentSecond?: boolean;
  align?: 'center' | 'left';
}> = ({ lines, size, top, enter, exit = 0, accentSecond = true, align = 'center' }) => {
  const lh = size * 0.98;
  return (
    <div
      style={{
        position: 'absolute',
        top,
        left: 0,
        right: 0,
        padding: '0 64px',
        textAlign: align,
        transform: `translateY(${-exit * 60}px)`,
        opacity: 1 - exit,
        filter: exit > 0 ? `blur(${exit * 8}px)` : undefined,
      }}
    >
      {lines.map((line, i) => {
        const p = enter[i];
        const accent = accentSecond && i === 1;
        return (
          <div key={i} style={{ overflow: 'hidden', height: lh * 1.08, lineHeight: `${lh}px` }}>
            <div
              style={{
                fontFamily: FONT,
                fontWeight: 900,
                fontSize: size,
                letterSpacing: '-0.035em',
                color: C.white,
                transform: `translateY(${(1 - p) * lh * 1.05}px)`,
                opacity: Math.min(1, p * 1.6),
                ...(accent
                  ? {
                      backgroundImage: ACCENT_GRADIENT,
                      WebkitBackgroundClip: 'text',
                      backgroundClip: 'text',
                      color: 'transparent',
                    }
                  : {}),
              }}
            >
              {line}
            </div>
          </div>
        );
      })}
    </div>
  );
};

/** Modul nomi — kichik "tabletka" (reference'dagi doimiy yorliq tili). */
export const Pill: React.FC<{ text: string; top: number; p: number; exit?: number }> = ({ text, top, p, exit = 0 }) => (
  <div style={{ position: 'absolute', top, left: 0, right: 0, display: 'flex', justifyContent: 'center' }}>
    <div
      style={{
        fontFamily: FONT,
        fontWeight: 700,
        fontSize: 30,
        letterSpacing: '0.02em',
        color: C.white,
        padding: '14px 30px',
        borderRadius: 999,
        background: 'rgba(255,255,255,0.08)',
        border: '1.5px solid rgba(255,255,255,0.16)',
        backdropFilter: 'blur(8px)',
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        opacity: p * (1 - exit),
        transform: `translateY(${(1 - p) * 18 - exit * 40}px) scale(${0.94 + 0.06 * p})`,
      }}
    >
      <span style={{ width: 12, height: 12, borderRadius: 6, background: C.green, boxShadow: `0 0 14px ${C.green}` }} />
      {text}
    </div>
  </div>
);
