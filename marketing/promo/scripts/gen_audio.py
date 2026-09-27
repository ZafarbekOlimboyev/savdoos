"""BinOS promo — musiqa va SFX'ni KOD bilan sintez qiladi (deterministik).

    python scripts/gen_audio.py            # public/audio/*.wav

NEGA SINTEZ. Tijoriy musiqani repo'ga qo'yish mumkin emas (litsenziya), va
"bepul" deb yuklangan trekning huquqiy holatini tekshirib bo'lmaydi. Bu yerdagi
hamma tovush — shu faylning o'zi yaratgan original to'lqin: hech qanday
namuna (sample), loop yoki uchinchi tomon materiali ishlatilmaydi. Shu bois
ular erkin ishlatiladi.

⚠️  Bu VAQTINCHALIK musiqa. Yakuniy versiyada litsenziyalangan trek bilan
    almashtirish tavsiya etiladi — kompozitsiya musiqani bitta fayldan oladi
    (`public/audio/music.wav`), ya'ni almashtirish bitta fayl.

Deterministik: tasodifiy manba qat'iy `SEED` bilan, ya'ni har yurishda bayt-
ba-bayt bir xil fayl.
"""
from __future__ import annotations

import pathlib
import sys
import wave

import numpy as np

SR = 48000
SEED = 20260927
OUT = pathlib.Path(__file__).resolve().parent.parent / "public" / "audio"


# ── asboblar ────────────────────────────────────────────────────────────────
def t_axis(sec: float) -> np.ndarray:
    return np.arange(int(sec * SR)) / SR


def env_adsr(n: int, a: float, d: float, s: float, r: float) -> np.ndarray:
    """a/d/r — soniya, s — daraja (0..1)."""
    a_n, d_n, r_n = int(a * SR), int(d * SR), int(r * SR)
    s_n = max(0, n - a_n - d_n - r_n)
    e = np.concatenate([
        np.linspace(0, 1, max(1, a_n), endpoint=False),
        np.linspace(1, s, max(1, d_n), endpoint=False),
        np.full(s_n, s),
        np.linspace(s, 0, max(1, r_n)),
    ])
    return e[:n] if len(e) >= n else np.pad(e, (0, n - len(e)))


def onepole_lp(x: np.ndarray, cutoff) -> np.ndarray:
    """Bir qutbli past o'tkazuvchi filtr; `cutoff` son yoki massiv (Hz)."""
    c = np.broadcast_to(np.asarray(cutoff, dtype=float), x.shape)
    k = 1.0 - np.exp(-2.0 * np.pi * c / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc += k[i] * (x[i] - acc)
        y[i] = acc
    return y


def onepole_hp(x: np.ndarray, cutoff: float) -> np.ndarray:
    return x - onepole_lp(x, cutoff)


def saw(freq: float, t: np.ndarray, harmonics: int = 24) -> np.ndarray:
    """Band-limited arra (aliasingsiz): 1/n amplitudali garmonikalar."""
    out = np.zeros_like(t)
    for n in range(1, harmonics + 1):
        if freq * n > SR / 2 * 0.9:
            break
        out += np.sin(2 * np.pi * freq * n * t) / n
    return out * (2 / np.pi)


def reverb(x: np.ndarray, mix: float = 0.25) -> np.ndarray:
    """Oddiy Schroeder reverb: 4 comb + 2 allpass."""
    def comb(sig, delay_ms, fb):
        d = int(SR * delay_ms / 1000)
        y = np.copy(sig)
        for i in range(d, len(y)):
            y[i] += fb * y[i - d]
        return y

    def allpass(sig, delay_ms, g):
        d = int(SR * delay_ms / 1000)
        y = np.zeros_like(sig)
        buf = np.zeros_like(sig)
        for i in range(len(sig)):
            delayed = buf[i - d] if i >= d else 0.0
            buf[i] = sig[i] + g * delayed
            y[i] = -g * buf[i] + delayed
        return y

    wet = sum(comb(x, ms, 0.78) for ms in (29.7, 37.1, 41.1, 43.7)) / 4
    wet = allpass(allpass(wet, 5.0, 0.7), 1.7, 0.7)
    return (1 - mix) * x + mix * wet


def midi(n: float) -> float:
    return 440.0 * 2 ** ((n - 69) / 12)


def write(name: str, left: np.ndarray, right: np.ndarray | None = None, peak_db: float = -3.0) -> None:
    right = left if right is None else right
    st = np.stack([left, right], axis=1)
    pk = np.max(np.abs(st)) or 1.0
    st = st / pk * (10 ** (peak_db / 20))
    pcm = (np.clip(st, -1, 1) * 32767).astype("<i2")
    OUT.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT / name), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(f"  {name:<18} {len(left) / SR:5.2f} s")


# ── musiqa ──────────────────────────────────────────────────────────────────
def music(duration: float) -> None:
    """Minimal, "premium" fon: yumshoq pad + sub-puls + yengil zarb. 104 BPM."""
    rng = np.random.default_rng(SEED)
    bpm = 104.0
    beat = 60.0 / bpm
    t = t_axis(duration)
    n = len(t)
    L = np.zeros(n)
    R = np.zeros(n)

    # Akkordlar (har biri 4 zarb): Am9 – Fmaj7 – C(add9) – G6
    chords = [
        [57, 60, 64, 67, 71],
        [53, 57, 60, 64, 67],
        [48, 55, 60, 62, 64],
        [55, 59, 62, 64, 67],
    ]
    bar = 4 * beat
    for bi in range(int(duration / bar) + 1):
        start = bi * bar
        if start >= duration:
            break
        seg = min(bar + 0.6, duration - start)
        ts = t_axis(seg)
        ch = chords[bi % len(chords)]
        pad = np.zeros_like(ts)
        for k, note in enumerate(ch):
            f = midi(note)
            detune = 1.0 + (0.0035 if k % 2 else -0.0035)
            pad += 0.55 * saw(f * detune, ts, 18) + 0.45 * saw(f / detune, ts, 18)
        pad /= len(ch)
        cutoff = 900 + 700 * np.sin(np.pi * ts / seg) ** 2          # sekin "nafas"
        pad = onepole_lp(pad, cutoff) * env_adsr(len(ts), 0.45, 0.4, 0.8, 0.6)
        i0 = int(start * SR)
        i1 = min(n, i0 + len(ts))
        L[i0:i1] += pad[: i1 - i0] * 0.9
        R[i0:i1] += np.roll(pad, 90)[: i1 - i0] * 0.9                # kichik stereo kenglik

        # sub-bas: ildiz nota, har zarbda
        root = midi(ch[0] - 12)
        for b in range(4):
            bs = start + b * beat
            if bs >= duration:
                break
            bl = min(beat * 0.9, duration - bs)
            tb = t_axis(bl)
            sub = np.sin(2 * np.pi * root * tb) * env_adsr(len(tb), 0.01, 0.15, 0.5, 0.2)
            j0 = int(bs * SR)
            j1 = min(n, j0 + len(tb))
            L[j0:j1] += sub[: j1 - j0] * 0.35
            R[j0:j1] += sub[: j1 - j0] * 0.35

    # sidechain "nafas": har zarbda pad biroz pasayadi
    phase = (t % beat) / beat
    duck = 1.0 - 0.35 * np.exp(-phase * 7.0)
    L *= duck
    R *= duck

    # zarb 1.4 s dan keyin kiradi (kirish yengil bo'lsin)
    k_start = 1.4
    for b in range(int(duration / beat) + 1):
        tb0 = b * beat
        if tb0 < k_start or tb0 >= duration - 0.2:
            continue
        i0 = int(tb0 * SR)
        # yumshoq kick (1 va 3-zarb)
        if b % 2 == 0:
            kt = t_axis(0.28)
            f = 48 + 90 * np.exp(-kt * 38)
            kick = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-kt * 14)
            j1 = min(n, i0 + len(kt))
            L[i0:j1] += kick[: j1 - i0] * 0.55
            R[i0:j1] += kick[: j1 - i0] * 0.55
        # yopiq hi-hat: har zarb orasida (off-beat)
        h0 = int((tb0 + beat / 2) * SR)
        if h0 < n:
            ht = t_axis(0.05)
            hat = onepole_hp(rng.standard_normal(len(ht)), 7000) * np.exp(-ht * 90)
            j1 = min(n, h0 + len(ht))
            L[h0:j1] += hat[: j1 - h0] * 0.10
            R[h0:j1] += hat[: j1 - h0] * 0.13

    L = reverb(L, 0.22)
    R = reverb(R, 0.22)
    # yumshoq cheklagich + kirish/chiqish
    fade = np.ones(n)
    fi, fo = int(0.35 * SR), int(0.9 * SR)
    fade[:fi] = np.linspace(0, 1, fi)
    fade[-fo:] = np.linspace(1, 0, fo)
    L = np.tanh(L * 1.2) * fade
    R = np.tanh(R * 1.2) * fade
    write("music.wav", L, R, peak_db=-6.0)


# ── SFX ─────────────────────────────────────────────────────────────────────
def sfx() -> None:
    rng = np.random.default_rng(SEED + 1)

    # whoosh: supuriluvchi filtrli shovqin, stereo o'tish
    t = t_axis(0.6)
    noise = rng.standard_normal(len(t))
    sweep = 300 + 3200 * (t / t[-1]) ** 1.6
    body = onepole_lp(noise, sweep) - onepole_lp(noise, sweep * 0.25)
    envl = np.exp(-((t - 0.32) ** 2) / (2 * 0.11 ** 2))
    pan = np.clip(t / t[-1], 0, 1)
    write("whoosh.wav", body * envl * (1.1 - pan), body * envl * (0.1 + pan), peak_db=-4.0)

    # impact: past zarb + qisqa tranzient
    t = t_axis(0.5)
    f = 42 + 50 * np.exp(-t * 22)
    thump = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)
    trans = onepole_lp(rng.standard_normal(len(t)), 2500) * np.exp(-t * 60) * 0.5
    write("impact.wav", thump + trans, peak_db=-3.0)

    # beep: kassa skaneri (~2.6 kHz), yumshoq qirralar
    t = t_axis(0.11)
    tone = np.sin(2 * np.pi * 2620 * t) + 0.18 * np.sin(2 * np.pi * 7860 * t)
    write("beep.wav", tone * env_adsr(len(t), 0.004, 0.02, 0.85, 0.03), peak_db=-6.0)

    # pop: savatga element qo'shildi
    t = t_axis(0.09)
    f = 780 + 620 * (t / t[-1])
    pop = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 45)
    write("pop.wav", pop, peak_db=-8.0)

    # tick: matn paydo bo'lishi
    t = t_axis(0.03)
    tick = onepole_hp(rng.standard_normal(len(t)), 3000) * np.exp(-t * 220)
    write("tick.wav", tick, peak_db=-12.0)


if __name__ == "__main__":
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0
    print(f"audio -> {OUT}")
    music(dur)
    sfx()
