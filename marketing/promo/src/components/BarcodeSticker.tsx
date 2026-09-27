import React from 'react';

import { ean13Runs } from '../lib/ean13';
import { C, FONT } from '../theme';

/**
 * Mahsulot etiketkasidagi shtrix-kod (haqiqiy EAN-13 chiziqlari) va skaner nuri.
 * `beam` 0..1 — nurning yuqoridan pastga o'tishi; 0 yoki 1 da nur ko'rinmaydi.
 * Bu VIDEO elementi (mahsulot UI'si emas): real hayotdagi etiketkani ifodalaydi.
 */
export const BarcodeSticker: React.FC<{
  code: string;
  width: number;
  beam: number;
  flash: number; // 0..1 — "o'qildi" yashil chaqnashi
}> = ({ code, width, beam, flash }) => {
  const runs = ean13Runs(code);
  const pad = width * 0.09;
  const barsW = width - pad * 2;
  const mod = barsW / 95;
  const barsH = width * 0.36;
  const guardExtra = mod * 5;
  const height = pad + barsH + guardExtra + width * 0.14 + pad * 0.5;
  const showBeam = beam > 0 && beam < 1;
  const beamY = pad + beam * (barsH + guardExtra);
  const digits = `${code[0]}  ${code.slice(1, 7)}  ${code.slice(7)}`;
  return (
    <div
      style={{
        width,
        height,
        borderRadius: width * 0.05,
        background: '#FFFFFF',
        position: 'relative',
        boxShadow: `0 30px 70px rgba(0,0,0,0.45), 0 0 0 ${flash * 5}px rgba(46,229,143,${0.55 * flash})`,
        overflow: 'hidden',
      }}
    >
      <svg width={width} height={pad + barsH + guardExtra} style={{ position: 'absolute', left: 0, top: 0 }}>
        {runs.map((r, i) => (
          <rect key={i} x={pad + r.x * mod} y={pad} width={r.w * mod} height={barsH + (r.guard ? guardExtra : 0)} fill={C.ink} />
        ))}
      </svg>
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: pad + barsH + guardExtra * 0.2,
          textAlign: 'center',
          fontFamily: FONT,
          fontWeight: 600,
          fontSize: width * 0.075,
          letterSpacing: '0.08em',
          color: C.ink,
          fontVariantNumeric: 'tabular-nums',
          whiteSpace: 'pre',
        }}
      >
        {digits}
      </div>
      {showBeam ? (
        <>
          {/* Nur izi — nur ortidan qoladigan yumshoq yashil tasma */}
          <div
            style={{
              position: 'absolute',
              left: pad * 0.4,
              right: pad * 0.4,
              top: Math.max(0, beamY - barsH * 0.35),
              height: Math.min(beamY, barsH * 0.35),
              background: 'linear-gradient(180deg, rgba(46,229,143,0) 0%, rgba(46,229,143,0.28) 100%)',
            }}
          />
          <div
            style={{
              position: 'absolute',
              left: pad * 0.3,
              right: pad * 0.3,
              top: beamY - 2,
              height: 4,
              borderRadius: 2,
              background: C.green,
              boxShadow: `0 0 18px 4px rgba(46,229,143,0.85), 0 0 60px 10px rgba(46,229,143,0.35)`,
            }}
          />
        </>
      ) : null}
    </div>
  );
};
