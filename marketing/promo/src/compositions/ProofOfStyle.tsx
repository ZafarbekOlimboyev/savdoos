import React from 'react';
import { AbsoluteFill, Audio, interpolate, Sequence, staticFile, useCurrentFrame } from 'remotion';

import manifest from '../../public/ui/pos/manifest.json';
import { BarcodeSticker } from '../components/BarcodeSticker';
import { Backdrop } from '../components/Backdrop';
import { BrandIcon, BrandMark, Wordmark } from '../components/Brand';
import { Headline, Pill } from '../components/Headline';
import { Box, Cam, Patch, PosShot, PosStage, Roll, unionBox } from '../components/PosStage';
import { copyFor, Lang } from '../copy';
import { loadFonts } from '../fonts';
import { EASE_IN, EASE_INOUT, EASE_OUT, EASE_WHIP, lerp, pop, prog } from '../lib/anim';
import { C, FONT, W } from '../theme';

loadFonts();

/**
 * PROOF OF STYLE — 8 s (240 kadr, 30 fps), 1080x1920.
 *
 *   0.0–1.6  Hook: BinOS belgisi + "DO‘KONINGIZ / BITTA TIZIMDA."
 *   1.1–6.1  Kassa: haqiqiy POS oynasi kiradi → qidiruv maydoniga yaqinlashish →
 *            etiketka skanerlanadi (raqamlar maydonga yoziladi — HAQIQIY surat) →
 *            kamera savatga "qamchi" bilan o'tadi → qator kiradi, JAMI aylanadi →
 *            ikkinchi skan.
 *   6.1–8.0  Yakun: oyna chiqadi, ilova belgisi + BinOS + shior.
 *
 * Barcha vaqtlar shu `T` jadvalida — sahna kodi raqam yozmaydi.
 */
export const PROOF_FRAMES = 240;

const T = {
  markIn: 3,
  gloss: [14, 36],
  hook1: 10,
  hook2: 15,
  hookOut: [36, 50],
  winIn: [34, 66],
  pill: 56,
  title1: 60,
  title2: 65,
  push: [70, 94],
  st1: 88,
  beam1: [100, 110],
  beep1: 108,
  typed1: [108, 111],
  glow1: [108, 128],
  enter1: 118,
  whip: [116, 134],
  row1: 130,
  total1: [132, 146],
  base1: [130, 136],
  st2: 146,
  beam2: [156, 164],
  beep2: 162,
  row2: 166,
  total2: [168, 182],
  base2: [166, 172],
  titleOut: [182, 194],
  winOut: [182, 198],
  icon: 193,
  word: 200,
  tag1: 206,
  tag2: 211,
} as const;

type Manifest = {
  states: Array<{ file: string; boxes: { search: Box; total: Box; amount: Box; rows: Box[] } }>;
  scans: Array<{ barcode: string; name: string; typed: string }>;
};
const M = manifest as unknown as Manifest;
const S0 = M.states[0];
const S1 = M.states[1];
const S2 = M.states[2];

/** Yakuniy belgining markazi (ekran y) — oyna aynan shu nuqtaga siqiladi. */
const ICON_TOP = 600;
const ICON_SIZE = 220;
const ICON_CY = ICON_TOP + ICON_SIZE / 2;

/** Kamera: POS nuqtasi (fx, fy) ekranning (sx, sy) nuqtasiga. */
function camAt(f: number): Cam {
  const enter = prog(f, T.winIn[0], T.winIn[1]);
  const push = prog(f, T.push[0], T.push[1]);
  const whip = prog(f, T.whip[0], T.whip[1], EASE_WHIP);
  const out = prog(f, T.winOut[0], T.winOut[1], EASE_INOUT);
  // Boshlang'ich: butun oyna, pastki yarmida.
  let cam: Cam = { s: 0.53, fx: 960, fy: 540, sx: 540, sy: lerp(2250, 1290, enter), rotX: lerp(24, 0, enter), opacity: Math.min(1, enter * 2.2) };
  // Qidiruv maydoniga yaqinlashish (chap-yuqori).
  // CSS x=0 (oyna qirrasi) ekranda x=40 ga tushadi: 424 = (540 - 40) / 1.18
  cam = { ...cam, s: lerp(0.53, 1.18, push), fx: lerp(960, 424, push), fy: lerp(540, 0, push), sy: lerp(cam.sy, 600, push) };
  // Qidiruv ↔ savat "qamchisi" (ma'lumot oqimini kuzatadi).
  // 4-ustun (CSS 1141) ekranda x=40 da — kartalar yarim kesilmasin: 1141 + 500 / 1.3
  cam = { ...cam, s: lerp(cam.s, 1.3, whip), fx: lerp(cam.fx, 1525.6, whip), fy: lerp(cam.fy, 540, whip), sy: lerp(cam.sy, 1240, whip) };
  // Tirik ushlab turish: sekin, sezilarsiz siljish.
  cam.s *= 1 + 0.02 * prog(f, T.push[1], T.whip[0]) + 0.03 * prog(f, T.whip[1], T.winOut[0]);
  // Chiqish: oyna ilova belgisi o'rniga "siqiladi" (mahsulot → brend).
  cam = {
    ...cam,
    s: lerp(cam.s, 0.11, out),
    fx: lerp(cam.fx, 960, out),
    fy: lerp(cam.fy, 540, out),
    sy: lerp(cam.sy, ICON_CY, out),
    opacity: (cam.opacity ?? 1) * (1 - prog(f, T.winOut[1] - 6, T.winOut[1])),
  };
  return cam;
}

/**
 * Yo'nalishli harakat xiralashuvi: kamera tezligidan (ekrandagi siljish, px/kadr).
 * Bitta o'tishli SVG `feGaussianBlur` — gorizontal va vertikal alohida.
 * (`@remotion/motion-blur` qatlamlari rangni feruzaga surib yuborardi.)
 */
function motionBlur(f: number): { bx: number; by: number } {
  // Faqat TO'G'RI chiziqli harakatda (oyna ko'tarilishi, panorama). Zoom'da
  // (yaqinlashish, belgiga siqilish) nuqtalar radial harakatlanadi — yo'nalishli
  // blur u yerda oynani oq "dog'"ga aylantiradi.
  const linear = (f >= T.winIn[0] && f <= T.winIn[1]) || (f >= T.whip[0] && f <= T.whip[1]);
  if (!linear) return { bx: 0, by: 0 };
  const at = (c: Cam) => [c.sx + (960 - c.fx) * c.s, c.sy + (540 - c.fy) * c.s];
  const [x0, y0] = at(camAt(f - 1));
  const [x1, y1] = at(camAt(f));
  const k = 0.32; // ~115° "zatvor"
  const bx = Math.min(34, Math.abs(x1 - x0) * k);
  const by = Math.min(34, Math.abs(y1 - y0) * k);
  return { bx: bx < 0.6 ? 0 : bx, by: by < 0.6 ? 0 : by };
}

/** Etiketka: chapdan "uchib" kiradi, nur o'tadi, keyin chiqib ketadi. */
function stickerPose(f: number, inAt: number, outFrom: number, outTo: number, carry: number) {
  const p = pop(f, inAt, 15, 0.9);
  const o = prog(f, outFrom, outTo, EASE_IN);
  return {
    x: lerp(-620, 0, p) - carry,
    rot: lerp(-14, -4, p) + o * -6,
    opacity: Math.min(1, p * 1.5) * (1 - o),
    y: o * 90,
  };
}

const PosScene: React.FC<{ lang: Lang }> = () => {
  const f = useCurrentFrame();
  const cam = camAt(f);

  // Yozilgan raqamlar (Enter'dan oldingi haqiqiy lahza).
  const typedP = prog(f, T.typed1[0], T.typed1[1]);
  const typedGone = prog(f, T.enter1, T.enter1 + 3);
  const glow = interpolate(f, [T.glow1[0], T.glow1[0] + 3, T.glow1[1]], [0, 1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });

  // Savat qatorlari va JAMI.
  const row1 = pop(f, T.row1, 16, 0.7);
  const row2 = pop(f, T.row2, 16, 0.7);
  const base1 = prog(f, T.base1[0], T.base1[1]);
  const base2 = prog(f, T.base2[0], T.base2[1]);
  const tot1 = prog(f, T.total1[0], T.total1[1]);
  const tot2 = prog(f, T.total2[0], T.total2[1]);

  // Etiketkalar (ekran fazosida).
  const whipCarry = 900 * prog(f, T.whip[0], T.whip[1], EASE_WHIP);
  const st1 = stickerPose(f, T.st1, T.whip[0], T.whip[0] + 12, whipCarry);
  const st2 = stickerPose(f, T.st2, T.beam2[1] + 8, T.beam2[1] + 20, 0);
  const beam1 = prog(f, T.beam1[0], T.beam1[1], EASE_WHIP);
  const beam2 = prog(f, T.beam2[0], T.beam2[1], EASE_WHIP);
  const flash1 = interpolate(f, [T.beep1, T.beep1 + 2, T.beep1 + 12], [0, 1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const flash2 = interpolate(f, [T.beep2, T.beep2 + 2, T.beep2 + 12], [0, 1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });

  const search = S0.boxes.search;
  const r1 = S1.boxes.rows[0];
  const r2 = S2.boxes.rows[1];

  return (
    <AbsoluteFill>
      <PosStage cam={cam}>
        {/* Baza: holatlar ketma-ket, qisqa o'tish bilan */}
        <PosShot file={S0.file} />
        {base1 > 0 ? <PosShot file={S1.file} opacity={base1} /> : null}
        {base2 > 0 ? <PosShot file={S2.file} opacity={base2} /> : null}

        {/* Skaner raqamlarni maydonga yozdi (haqiqiy surat), Enter — maydon tozalanadi */}
        {typedP > 0 && typedGone < 1 ? (
          <Patch file={M.scans[0].typed} box={search} clipRight={lerp(search.w, 0, typedP)} style={{ opacity: 1 - typedGone }} />
        ) : null}
        {glow > 0 ? (
          <div
            style={{
              position: 'absolute',
              left: search.x,
              top: search.y,
              width: search.w,
              height: search.h,
              borderRadius: 11,
              boxShadow: `0 0 0 ${2.5 / cam.s}px rgba(46,229,143,${glow}), 0 0 ${28 / cam.s}px rgba(46,229,143,${0.6 * glow})`,
            }}
          />
        ) : null}

        {/* 1-qator savatga kiradi; JAMI 0 → 9 000 aylanadi */}
        {f >= T.row1 && f < T.row1 + 24 ? (
          <>
            <Patch file={S0.file} box={r1} style={{ opacity: row1 > 0.98 ? 0 : 1 }} />
            <Patch file={S1.file} box={r1} style={{ opacity: Math.min(1, row1 * 1.4), transform: `translateY(${(1 - row1) * -46}px) scale(${0.97 + 0.03 * row1})` }} />
          </>
        ) : null}
        {tot1 > 0 && tot1 < 1 ? <Roll from={S0.file} to={S1.file} box={unionBox(S0.boxes.amount, S1.boxes.amount)} p={tot1} /> : null}

        {/* 2-qator; 9 000 → 24 000 */}
        {f >= T.row2 && f < T.row2 + 24 ? (
          <>
            <Patch file={S1.file} box={r2} style={{ opacity: row2 > 0.98 ? 0 : 1 }} />
            <Patch file={S2.file} box={r2} style={{ opacity: Math.min(1, row2 * 1.4), transform: `translateY(${(1 - row2) * -46}px) scale(${0.97 + 0.03 * row2})` }} />
          </>
        ) : null}
        {tot2 > 0 && tot2 < 1 ? <Roll from={S1.file} to={S2.file} box={unionBox(S1.boxes.amount, S2.boxes.amount)} p={tot2} /> : null}
      </PosStage>

      {/* Etiketkalar — real hayotdagi mahsulot yorlig'i (video elementi) */}
      {st1.opacity > 0 ? (
        <div style={{ position: 'absolute', left: 110 + st1.x, top: 1250 + st1.y, transform: `rotate(${st1.rot}deg)`, opacity: st1.opacity }}>
          <BarcodeSticker code={M.scans[0].barcode} width={430} beam={beam1} flash={flash1} />
        </div>
      ) : null}
      {st2.opacity > 0 ? (
        <div style={{ position: 'absolute', left: 64 + st2.x, top: 1310 + st2.y, transform: `rotate(${st2.rot}deg)`, opacity: st2.opacity }}>
          <BarcodeSticker code={M.scans[1].barcode} width={400} beam={beam2} flash={flash2} />
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

const Sfx: React.FC<{ at: number; file: string; volume?: number }> = ({ at, file, volume = 1 }) => (
  <Sequence from={at} layout="none">
    <Audio src={staticFile(`audio/${file}`)} volume={volume} />
  </Sequence>
);

export const ProofOfStyle: React.FC<{ lang: Lang }> = ({ lang }) => {
  const f = useCurrentFrame();
  const copy = copyFor(lang);

  // Hook
  const mark = pop(f, T.markIn, 13, 0.9);
  const gloss = prog(f, T.gloss[0], T.gloss[1]);
  const hookOut = prog(f, T.hookOut[0], T.hookOut[1], EASE_IN);
  const h1 = pop(f, T.hook1, 16, 0.8);
  const h2 = pop(f, T.hook2, 16, 0.8);

  // Kassa sarlavhasi
  const pillP = pop(f, T.pill, 16, 0.8);
  const t1 = pop(f, T.title1, 16, 0.8);
  const t2 = pop(f, T.title2, 16, 0.8);
  const titleOut = prog(f, T.titleOut[0], T.titleOut[1], EASE_IN);

  // Yakun
  const icon = pop(f, T.icon, 12, 0.9);
  const word = prog(f, T.word, T.word + 16, EASE_OUT);
  const tag1 = pop(f, T.tag1, 16, 0.8);
  const tag2 = pop(f, T.tag2, 16, 0.8);

  const posVisible = f >= T.winIn[0] && f <= T.winOut[1];
  const mb = posVisible ? motionBlur(f) : { bx: 0, by: 0 };

  return (
    <AbsoluteFill style={{ background: C.navy950 }}>
      <Backdrop intensity={1 + 0.35 * icon} />

      {/* HOOK */}
      {hookOut < 1 ? (
        <>
          <div
            style={{
              position: 'absolute',
              top: 470 - hookOut * 80,
              left: (W - 300) / 2,
              opacity: 1 - hookOut,
              filter: hookOut > 0 ? `blur(${hookOut * 10}px)` : undefined,
            }}
          >
            <BrandMark size={300} p={mark} gloss={gloss} />
          </div>
          <Headline lines={copy.hook} size={124} top={860} enter={[h1, h2]} exit={hookOut} />
        </>
      ) : null}

      {/* KASSA */}
      {posVisible ? (
        <>
          <svg width={0} height={0} style={{ position: 'absolute' }}>
            <filter id="mblur" x="-5%" y="-5%" width="110%" height="110%">
              <feGaussianBlur stdDeviation={`${mb.bx} ${mb.by}`} />
            </filter>
          </svg>
          <AbsoluteFill style={{ filter: mb.bx + mb.by > 0 ? 'url(#mblur)' : undefined }}>
            <PosScene lang={lang} />
          </AbsoluteFill>
        </>
      ) : null}
      {f >= T.pill - 2 && titleOut < 1 ? (
        <>
          <Pill text={copy.pos.pill} top={150} p={pillP} exit={titleOut} />
          <Headline lines={copy.pos.title} size={104} top={250} enter={[t1, t2]} exit={titleOut} />
        </>
      ) : null}

      {/* YAKUN */}
      {f >= T.icon - 1 ? (
        <AbsoluteFill style={{ alignItems: 'center' }}>
          <div style={{ position: 'absolute', top: ICON_TOP }}>
            <BrandIcon size={ICON_SIZE} p={icon} />
          </div>
          <div style={{ position: 'absolute', top: 866 }}>
            <Wordmark size={140} p={word} />
          </div>
          <div
            style={{
              position: 'absolute',
              top: 1040,
              fontFamily: FONT,
              fontWeight: 600,
              fontSize: 40,
              letterSpacing: '-0.01em',
              color: C.mist,
              opacity: word,
              transform: `translateY(${(1 - word) * 16}px)`,
            }}
          >
            {copy.end.line}
          </div>
          <Headline lines={copy.end.tagline} size={78} top={1170} enter={[tag1, tag2]} />
        </AbsoluteFill>
      ) : null}

      {/* AUDIO — musiqa: kod bilan sintez qilingan original (scripts/gen_audio.py) */}
      <Audio src={staticFile('audio/music.wav')} volume={0.55} />
      <Sfx at={0} file="whoosh.wav" volume={0.5} />
      <Sfx at={T.markIn + 5} file="impact.wav" volume={0.55} />
      <Sfx at={T.hook1} file="tick.wav" volume={0.5} />
      <Sfx at={T.hook2} file="tick.wav" volume={0.5} />
      <Sfx at={T.winIn[0]} file="whoosh.wav" volume={0.45} />
      <Sfx at={T.title1} file="tick.wav" volume={0.45} />
      <Sfx at={T.push[0]} file="whoosh.wav" volume={0.35} />
      <Sfx at={T.st1} file="whoosh.wav" volume={0.3} />
      <Sfx at={T.beep1} file="beep.wav" volume={0.6} />
      <Sfx at={T.whip[0]} file="whoosh.wav" volume={0.5} />
      <Sfx at={T.row1} file="pop.wav" volume={0.6} />
      <Sfx at={T.st2} file="whoosh.wav" volume={0.3} />
      <Sfx at={T.beep2} file="beep.wav" volume={0.6} />
      <Sfx at={T.row2} file="pop.wav" volume={0.6} />
      <Sfx at={T.winOut[0]} file="whoosh.wav" volume={0.45} />
      <Sfx at={T.icon + 3} file="impact.wav" volume={0.6} />
      <Sfx at={T.tag1} file="tick.wav" volume={0.4} />
    </AbsoluteFill>
  );
};
