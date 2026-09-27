import { Easing, interpolate, spring } from 'remotion';

import { FPS } from '../theme';

/** Premium "chiqish" egri chizig'i: tez boshlanib, yumshoq to'xtaydi. */
export const EASE_OUT = Easing.bezier(0.16, 1, 0.3, 1);
/** Kamera "qamchisi": ikkala uchida ham yumshoq, o'rtada tez. */
export const EASE_WHIP = Easing.bezier(0.7, 0, 0.2, 1);
export const EASE_IN = Easing.bezier(0.55, 0, 0.9, 0.35);
/** Ikki uchida yumshoq — bir joydan ikkinchisiga "o'tish" (masalan oyna → belgi). */
export const EASE_INOUT = Easing.bezier(0.65, 0, 0.35, 1);

/** [from, to] oralig'ida 0→1, chegaradan tashqarida qat'iy. */
export function prog(frame: number, from: number, to: number, easing = EASE_OUT): number {
  return interpolate(frame, [from, to], [0, 1], { easing, extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
}

export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/** Remotion spring — tabiiy "qo'nish" (ozgina oshib ketish bilan). */
export function pop(frame: number, start: number, damping = 14, mass = 0.8): number {
  return spring({ frame: frame - start, fps: FPS, config: { damping, mass, stiffness: 140 } });
}
