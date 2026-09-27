import React from 'react';
import { AbsoluteFill, useCurrentFrame } from 'remotion';

import { C, H, W } from '../theme';

/**
 * Navy dunyo: chuqur gradient + ikki yumshoq nur (logo ranglari). Nurlar juda
 * sekin suzadi — sahna "tirik", lekin diqqatni tortmaydi.
 * Nozik don (grain) h264'da gradient pog'onalanishini yashiradi.
 */
export const Backdrop: React.FC<{ intensity?: number }> = ({ intensity = 1 }) => {
  const f = useCurrentFrame();
  const t = f / 30;
  const gx = 78 + Math.sin(t * 0.35) * 4;
  const gy = 18 + Math.cos(t * 0.3) * 3;
  const bx = 12 + Math.cos(t * 0.28) * 5;
  const by = 86 + Math.sin(t * 0.33) * 3;
  return (
    <AbsoluteFill style={{ background: `linear-gradient(180deg, ${C.navy900} 0%, #021434 45%, ${C.navy950} 100%)` }}>
      <AbsoluteFill
        style={{
          background: `radial-gradient(60% 38% at ${gx}% ${gy}%, rgba(20,184,176,${0.2 * intensity}) 0%, rgba(20,184,176,0) 70%)`,
        }}
      />
      <AbsoluteFill
        style={{
          background: `radial-gradient(70% 45% at ${bx}% ${by}%, rgba(14,90,167,${0.42 * intensity}) 0%, rgba(14,90,167,0) 72%)`,
        }}
      />
      <svg width={W} height={H} style={{ position: 'absolute', inset: 0, opacity: 0.05, mixBlendMode: 'overlay' }}>
        <filter id="grain">
          <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves={2} seed={7} stitchTiles="stitch" />
          <feColorMatrix type="saturate" values="0" />
        </filter>
        <rect width="100%" height="100%" filter="url(#grain)" />
      </svg>
    </AbsoluteFill>
  );
};
