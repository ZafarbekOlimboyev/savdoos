import React from 'react';
import { Img, staticFile } from 'remotion';

import { C, FONT } from '../theme';

/** Faqat "B" belgisi (shaffof fon) — navy ustida eng toza ko'rinish. */
export const BrandMark: React.FC<{ size: number; p: number; gloss?: number }> = ({ size, p, gloss = 0 }) => (
  <div
    style={{
      width: size,
      height: size,
      position: 'relative',
      transform: `scale(${0.72 + 0.28 * p})`,
      opacity: Math.min(1, p * 1.4),
      filter: `blur(${(1 - Math.min(1, p)) * 16}px) drop-shadow(0 18px 50px rgba(46,229,143,${0.22 * p}))`,
    }}
  >
    <Img src={staticFile('brand/binos-mark.png')} style={{ width: '100%', height: '100%' }} />
    {gloss > 0 && gloss < 1 ? (
      // Belgi ustidan bir marta o'tadigan yorug'lik — faqat belgining shakli ichida.
      <div
        style={{
          position: 'absolute',
          inset: 0,
          WebkitMaskImage: `url(${staticFile('brand/binos-mark.png')})`,
          WebkitMaskSize: '100% 100%',
          background: `linear-gradient(105deg, transparent ${gloss * 140 - 40}%, rgba(255,255,255,0.55) ${gloss * 140 - 25}%, transparent ${gloss * 140 - 10}%)`,
        }}
      />
    ) : null}
  </div>
);

/** Ilova belgisi (to'liq nishon) — yakuniy kadr uchun. */
export const BrandIcon: React.FC<{ size: number; p: number }> = ({ size, p }) => (
  <div
    style={{
      width: size,
      height: size,
      borderRadius: size * 0.225,
      overflow: 'hidden',
      transform: `scale(${0.6 + 0.4 * p}) translateY(${(1 - p) * 30}px)`,
      opacity: Math.min(1, p * 1.5),
      boxShadow: `0 0 0 2px rgba(255,255,255,0.10), 0 30px 80px rgba(0,0,0,0.45), 0 0 90px rgba(20,184,176,${0.25 * p})`,
    }}
  >
    <Img src={staticFile('brand/binos-icon.png')} style={{ width: '100%', height: '100%' }} />
  </div>
);

/**
 * "BinOS" so'z-belgisi. ⚠️ Rasmiy wordmark fayli repo'da yo'q — Inter 800 bilan
 * terilgan (qarang: public/brand/PROVENANCE.md). Rasmiysi berilsa shu yerda almashadi.
 */
export const Wordmark: React.FC<{ size: number; p: number }> = ({ size, p }) => (
  <div
    style={{
      fontFamily: FONT,
      fontWeight: 800,
      fontSize: size,
      letterSpacing: '-0.04em',
      color: C.white,
      opacity: p,
      transform: `translateY(${(1 - p) * 24}px)`,
    }}
  >
    Bin<span style={{ color: C.green }}>OS</span>
  </div>
);
