// @vitest-environment node
//
// `web/scanner.js` NING O'ZINI soxta DOM ichida yurgizadi (`node:vm`) va
// quvurning xulqini isbotlaydi — kamerasiz, brauzersiz.
//
// Nega bu test bor. `mobile_scanner` ning web yo'lidagi nuqson AYNAN shu
// qatlamda edi: ZXing `decodeContinuously` halqasi faqat NotFound/Checksum/
// Format istisnolarida qayta rejalashtiriladi, boshqa har qanday throw
// (TypeError, DOMException) uni BUTUNLAY to'xtatadi — kamera esa oqim berishda
// davom etadi. Natija: mukammal preview, nol urinish, hech qanday xato.
// Birinchi testlar aynan shuni qo'riqlaydi; halqa endi asinxron bo'lgani uchun
// rad etilgan va'da va kelmay qolgan `requestVideoFrameCallback` ham shu
// ro'yxatga qo'shildi.
import { beforeEach, describe, expect, it } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';
import * as vm from 'vm';

const SCANNER = path.resolve(__dirname, '../apps/mobile/web/scanner.js');
const SRC = fs.readFileSync(SCANNER, 'utf-8');

interface Grab { sx: number; sy: number; sw: number; sh: number; }

interface Harness {
  api: any;
  ctx: any;
  video: any;
  grabs: Grab[];
  apiCalls: string[];
  hintsAtDecode: any[];
  canvasResizes: () => number;
  decodeCalls: () => number;
  setDecoder: (fn: (bitmap: unknown) => unknown) => void;
  fireFrame: () => void;            // rVFC rejimida bitta kadr yetkazadi
  tick: (ms: number) => Promise<void>;
}

/// Soxta DOM + soxta ZXing bilan `scanner.js` ni yuklaydi.
function boot(opts: {
  videoWidth?: number;
  videoHeight?: number;
  getUserMedia?: (c: unknown) => Promise<unknown>;
  cssWidth?: number;
  cssHeight?: number;
  /// `createImageBitmap` mavjudmi va u nima qiladi.
  bitmap?: 'yes' | 'no' | 'reject' | 'throw';
  /// `requestVideoFrameCallback` mavjudmi; 'manual' — test o'zi kadr yetkazadi.
  rvfc?: 'no' | 'auto' | 'manual' | 'never';
} = {}): Harness {
  let decodeCalls = 0;
  let canvasResizes = 0;
  const apiCalls: string[] = [];
  const hintsAtDecode: any[] = [];
  const grabs: Grab[] = [];
  let decoder: (bitmap: unknown) => unknown = () => {
    const e = new Error('not found');
    e.name = 'NotFoundException';
    throw e;
  };

  const track = {
    label: 'Back Camera',
    stop() {},
    getSettings: () => ({
      facingMode: 'environment',
      width: opts.videoWidth ?? 1920,
      height: opts.videoHeight ?? 1080,
      frameRate: 30,
    }),
  };
  const stream = { getVideoTracks: () => [track], getTracks: () => [track] };

  const frameCallbacks: Array<() => void> = [];
  const video: any = {
    videoWidth: opts.videoWidth ?? 1920,
    videoHeight: opts.videoHeight ?? 1080,
    // Portret CSS qutisi — real iPhone'dagi kabi (object-fit: cover).
    clientWidth: opts.cssWidth ?? 402,
    clientHeight: opts.cssHeight ?? 874,
    readyState: 4,
    style: {},
    muted: false,
    srcObject: null,
    setAttribute() {},
    addEventListener() {},
    remove() {},
    play: () => Promise.resolve(),
  };
  const rvfcMode = opts.rvfc ?? 'no';
  if (rvfcMode !== 'no') {
    let seq = 0;
    video.requestVideoFrameCallback = (cb: () => void) => {
      seq++;
      if (rvfcMode === 'auto') setTimeout(cb, 8);       // brauzer kadr yetkazgandek
      else if (rvfcMode === 'manual') frameCallbacks.push(cb);
      // 'never' — ro'yxatga OLINADI, lekin HECH QACHON chaqirilmaydi (kamera muzladi)
      return seq;
    };
    video.cancelVideoFrameCallback = () => {};
  }

  const host: any = { id: '', style: {}, textContent: '', appendChild() {} };
  function makeCanvas(): any {
    const c: any = {
      _w: 0, _h: 0,
      getContext: () => ({
        drawImage(_img: unknown, sx?: number, sy?: number, sw?: number, sh?: number) {
          // `drawImage(video, sx,sy,sw,sh, 0,0,dw,dh)` — zaxira yo'l;
          // `drawImage(bitmap, 0,0,dw,dh)` — bitmap yo'li (kesim allaqachon bo'lgan).
          if (typeof sw === 'number' && typeof sh === 'number' && arguments.length > 5) {
            grabs.push({ sx: sx!, sy: sy!, sw, sh });
          }
        },
        getImageData: (_x: number, _y: number, w: number, h: number) => ({
          data: new Uint8ClampedArray(Math.max(1, w * h) * 4),
        }),
      }),
    };
    Object.defineProperty(c, 'width', {
      get: () => c._w,
      set: (v: number) => { if (v !== c._w) canvasResizes++; c._w = v; },
    });
    Object.defineProperty(c, 'height', {
      get: () => c._h,
      set: (v: number) => { c._h = v; },
    });
    return c;
  }

  const ctx: any = {
    console,
    Map, Promise, Error, Math, JSON, Object, String, Number, Date, Set, Uint8ClampedArray,
    setTimeout, clearTimeout,
    performance: { now: () => Date.now() },
    document: {
      hidden: false,
      getElementById: (id: string) => (id === host.id ? host : null),
      createElement: (tag: string) => (tag === 'video' ? video : makeCanvas()),
    },
    navigator: {
      mediaDevices: {
        getUserMedia: opts.getUserMedia ?? (() => Promise.resolve(stream)),
        enumerateDevices: () => Promise.resolve([{ kind: 'videoinput' }, { kind: 'videoinput' }]),
      },
    },
    ZXing: {
      BarcodeFormat: { EAN_13: 7, EAN_8: 6, UPC_A: 14, UPC_E: 15, CODE_128: 4, CODE_39: 2, ITF: 8 },
      DecodeHintType: { POSSIBLE_FORMATS: 2, TRY_HARDER: 3 },
      HTMLCanvasElementLuminanceSource: class { constructor(public c: unknown) {} },
      RGBLuminanceSource: class { constructor(public lum: unknown, public w: number, public h: number) {} },
      HybridBinarizer: class { constructor(public s: unknown) {} },
      BinaryBitmap: class { constructor(public b: unknown) {} },
      MultiFormatReader: class {
        hints: any;
        setHints(h: any) { this.hints = h; }
        reset() {}
        // Haqiqiy buildda `decode(t, e)` — `setHints(e)` ni bajaradi, ya'ni
        // bitta argument bilan chaqirilsa hintlar O'CHADI. Soxta o'quvchi ham
        // AYNAN shunday qiladi: aks holda test nuqsonni ko'rmaydi.
        decode(bitmap: unknown, hints?: any) {
          this.hints = hints;
          decodeCalls++; apiCalls.push('decode');
          return decoder(bitmap);
        }
        decodeWithState(bitmap: unknown) {
          decodeCalls++; apiCalls.push('decodeWithState');
          hintsAtDecode.push(this.hints);
          return decoder(bitmap);
        }
      },
    },
  };
  const bm = opts.bitmap ?? 'yes';
  if (bm !== 'no') {
    ctx.createImageBitmap = (_v: unknown, sx: number, sy: number, sw: number, sh: number) => {
      if (bm === 'throw') throw new TypeError('createImageBitmap is not usable here');
      if (bm === 'reject') {
        const e = new Error('detached');
        e.name = 'InvalidStateError';
        return Promise.reject(e);
      }
      grabs.push({ sx, sy, sw, sh });
      return Promise.resolve({ width: sw, height: sh, close() {} });
    };
  }
  ctx.self = ctx;
  ctx.globalThis = ctx;
  ctx.window = ctx;
  vm.createContext(ctx);
  new vm.Script(SRC, { filename: 'scanner.js' }).runInContext(ctx);

  const api = ctx.binosScanner;
  // Host `div` ni ro'yxatdan o'tkazamiz: `create()` bergan id bilan.
  const origCreate = api.create.bind(api);
  api.create = (containerId: string) => { host.id = containerId; return origCreate(containerId); };

  return {
    api, ctx, video, grabs, apiCalls, hintsAtDecode,
    canvasResizes: () => canvasResizes,
    decodeCalls: () => decodeCalls,
    setDecoder: (fn) => { decoder = fn; },
    fireFrame: () => { const cb = frameCallbacks.shift(); if (cb) cb(); },
    tick: (ms: number) => new Promise<void>((r) => setTimeout(r, ms)),
  };
}

const diag = (h: Harness, id: string) => JSON.parse(h.api.diagnostics(id));

describe('web skaner quvuri — xulq', () => {
  let h: Harness;
  beforeEach(() => { h = boot(); });

  it('`binosScanner` ko\'prigi e\'lon qilinadi', () => {
    for (const m of ['create', 'start', 'stop', 'pause', 'resume', 'dispose', 'setCallback', 'diagnostics']) {
      expect(typeof h.api[m], m).toBe('function');
    }
  });

  it('kamera ochiladi va dekodlash halqasi yuradi', async () => {
    const id = h.api.create('host-1');
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(400);
    const d = diag(h, id);
    expect(d.permission).toBe('granted');
    expect(d.decoderReady).toBe(true);
    expect(d.videoWidth).toBe(1920);
    expect(d.attempts).toBeGreaterThan(0);
    expect(d.cameras).toBe(2);
    // Kamera ROSTDAN nima berganini yozamiz: cheklovlar `ideal`, ya'ni ular
    // hech qachon rad etilmaydi va qurilma nimani bergani FAQAT shu yerdan
    // bilinadi (4K so'rab 720p olish mumkin, va buni panel aytishi kerak).
    expect(d.trackWidth).toBe(1920);
    expect(d.trackHeight).toBe(1080);
    expect(d.trackFps).toBe(30);
    h.api.dispose(id);
  });

  // ⚠️  ASOSIY QO'RIQCHI. Dekoder HAR chaqiruvda TypeError tashlaydi — bu
  //     ZXing'ning o'z halqasini o'ldiradigan sinf. Bizning halqa TO'XTAMASLIGI
  //     va urinishni davom ettirishi SHART.
  it('dekoder istisno tashlasa urinish DAVOM etadi (ichki qoriqchi)', async () => {
    const id = h.api.create('host-2');
    h.setDecoder(() => { throw new TypeError('canvas is broken'); });
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(300);
    const first = diag(h, id).attempts;
    await h.tick(400);
    const second = diag(h, id).attempts;
    expect(first).toBeGreaterThan(0);
    expect(second).toBeGreaterThan(first);           // halqa davom etmoqda
    const d = diag(h, id);
    expect(d.running).toBe(true);
    expect(d.lastErrorKind).toBe('TypeError');       // xato YUTILMAYDI, qayd etiladi
    expect(d.successes).toBe(0);
    h.api.dispose(id);
  });

  // TASHQI QORIQCHI. Istisno dekodlash try blokidan TASHQARIDA tug'iladi
  // (media element yaroqsiz bo'lib qolgan holat). `runTick` dagi try/catch olib
  // tashlansa — halqa BIR MARTA yiqilib, sessiya oxirigacha o'lik qoladi va
  // `loopErrors` o'smaydi. Aynan shu narsa `mobile_scanner` web yo'lidagi nuqson edi.
  it("kadr olishda istisno bolsa ham halqa TIRIK qoladi (tashqi qoriqchi)", async () => {
    const id = h.api.create('host-2b');
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(250);
    Object.defineProperty(h.video, 'videoWidth', {
      configurable: true,
      get() { const e = new Error('invalid state'); e.name = 'InvalidStateError'; throw e; },
    });
    await h.tick(400);
    const a = diag(h, id);
    await h.tick(400);
    const b = diag(h, id);
    expect(a.loopErrors).toBeGreaterThan(0);
    expect(b.loopErrors).toBeGreaterThan(a.loopErrors);
    expect(b.running).toBe(true);
    expect(b.lastErrorKind).toBe('InvalidStateError');
    h.api.dispose(id);
  });

  // UCHINCHI QO'RIQCHI (halqa endi ASINXRON). Kadr olish va'dasi RAD etilsa va
  // zaxira yo'l ham yiqilsa, hech qanday `catch` bo'lmasa halqa jimgina o'lardi.
  it('kadr olish vadasi rad etilsa halqa TIRIK qoladi (asinxron qoriqchi)', async () => {
    const h5 = boot({ bitmap: 'reject' });
    const id = h5.api.create('host-2c');
    expect(await h5.api.start(id)).toBe('ok');
    await h5.tick(400);
    const d = diag(h5, id);
    expect(d.running).toBe(true);
    expect(d.attempts).toBeGreaterThan(0);
    // Bir marta rad etilgach zaxira yo'lga o'tadi va SHU YERDA qoladi.
    expect(d.acquirePath).toBe('drawImage');
    expect(d.bitmapFallback).toBe('InvalidStateError');
    h5.api.dispose(id);
  });

  it('video o\'lchami kelmasa START xato qaytaradi (0x0 kanvas keshlanmaydi)', async () => {
    const h0 = boot({ videoWidth: 0, videoHeight: 0 });
    const id = h0.api.create('host-3');
    const res = await h0.api.start(id);
    expect(res).toBe('generic');
    const d = diag(h0, id);
    expect(d.lastErrorKind).toBe('NoVideoDimensions');
    expect(d.decoderReady).toBe(false);
    expect(d.attempts).toBe(0);                      // buzuq kanvas bilan urinilmadi
    h0.api.dispose(id);
  }, 15000);

  it('ruxsat rad etilsa pastroq cheklovlar bilan QAYTA urinilmaydi', async () => {
    let calls = 0;
    const h2 = boot({
      getUserMedia: () => {
        calls++;
        const e = new Error('denied');
        e.name = 'NotAllowedError';
        return Promise.reject(e);
      },
    });
    const id = h2.api.create('host-4');
    expect(await h2.api.start(id)).toBe('permission');
    expect(calls).toBe(1);                            // narvon bo'ylab tushmaydi
    expect(diag(h2, id).permission).toBe('denied');
  });

  it('cheklov qo\'llab-quvvatlanmasa narvon bo\'ylab pastga tushadi', async () => {
    let calls = 0;
    const track = { label: 'cam', stop() {}, getSettings: () => ({ facingMode: 'environment' }) };
    const h3 = boot({
      getUserMedia: () => {
        calls++;
        if (calls < 3) {
          const e = new Error('over');
          e.name = 'OverconstrainedError';
          return Promise.reject(e);
        }
        return Promise.resolve({ getVideoTracks: () => [track], getTracks: () => [track] });
      },
    });
    const id = h3.api.create('host-5');
    expect(await h3.api.start(id)).toBe('ok');
    expect(calls).toBe(3);
    expect(diag(h3, id).constraintStep).toBe(2);
    h3.api.dispose(id);
  });

  it('bitta kod -> bitta chaqiruv (takror bosilmaydi)', async () => {
    const id = h.api.create('host-6');
    const seen: string[] = [];
    h.setDecoder(() => ({ getText: () => '4780000000038', getBarcodeFormat: () => 'EAN_13' }));
    h.api.setCallback(id, (code: string) => seen.push(code));
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(600);                                 // bir necha tik
    expect(seen.length).toBe(1);                       // dublikat oynasi ichida FAQAT bitta
    const d = diag(h, id);
    expect(d.successes).toBeGreaterThan(1);            // dekodlash esa davom etgan
    expect(d.lastFormat).toBe('EAN_13');
    h.api.dispose(id);
  });

  it('stop kamerani va halqani to\'xtatadi, start qayta tiklaydi', async () => {
    const id = h.api.create('host-7');
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(250);
    h.api.stop(id);
    const stopped = diag(h, id);
    expect(stopped.running).toBe(false);
    expect(stopped.decoderReady).toBe(false);
    const before = stopped.attempts;
    await h.tick(300);
    expect(diag(h, id).attempts).toBe(before);   // o'lik halqa yo'q
    h.api.dispose(id);
  });

  it('ZXing yuklanmagan bo\'lsa `unsupported` qaytaradi (jim yiqilish emas)', async () => {
    const h4 = boot();
    h4.ctx.ZXing = undefined;
    const id = h4.api.create('host-8');
    expect(await h4.api.start(id)).toBe('unsupported');
  });

  it('chakana formatlar ro\'yxati dekoderga beriladi', async () => {
    const id = h.api.create('host-9');
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(200);
    for (const f of ['EAN_13', 'EAN_8', 'UPC_A', 'UPC_E', 'CODE_128', 'CODE_39', 'ITF']) {
      expect(SRC).toContain(`F.${f}`);
    }
    h.api.dispose(id);
  });
});

describe('kadrni olish — arzon yo\'l va uning zaxirasi', () => {
  // O'lchangan (Edge, sun'iy kamera): `drawImage(video, ...)` 4K manbadan
  // 70–165 ms, `createImageBitmap` ~0.1 ms. Shu bois asosiy yo'l — bitmap.
  it('mavjud bo\'lsa createImageBitmap ishlatiladi', async () => {
    const h = boot({ bitmap: 'yes' });
    const id = h.api.create('host-bmp');
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(300);
    expect(diag(h, id).acquirePath).toBe('bitmap');
    expect(h.grabs.length).toBeGreaterThan(0);
    h.api.dispose(id);
  });

  it('createImageBitmap sinxron tashlasa zaxira yo\'l ishlaydi', async () => {
    const h = boot({ bitmap: 'throw' });
    const id = h.api.create('host-bmp2');
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(300);
    const d = diag(h, id);
    expect(d.acquirePath).toBe('drawImage');
    expect(d.bitmapFallback).toBe('TypeError');
    expect(d.attempts).toBeGreaterThan(0);
    h.api.dispose(id);
  });

  it('createImageBitmap umuman bo\'lmasa (eski Safari) halqa baribir ishlaydi', async () => {
    const h = boot({ bitmap: 'no' });
    const id = h.api.create('host-bmp3');
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(300);
    const d = diag(h, id);
    expect(d.acquirePath).toBe('drawImage');
    expect(d.attempts).toBeGreaterThan(0);
    h.api.dispose(id);
  });
});

describe('rejalashtirish — kadr kelganda, taymer bilan emas', () => {
  it('requestVideoFrameCallback mavjud bo\'lsa o\'sha ishlatiladi', async () => {
    const h = boot({ rvfc: 'auto' });
    const id = h.api.create('host-rvfc');
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(300);
    const d = diag(h, id);
    expect(d.sched).toBe('rvfc');
    expect(d.attempts).toBeGreaterThan(0);
    h.api.dispose(id);
  });

  // ⚠️  rVFC ning xavfi: kamera muzlasa yoki brauzer kadr bermasa, callback
  //     HECH QACHON kelmaydi va halqa jimgina to'xtaydi — bu biz tuzatgan
  //     nuqsonning aynan o'zi bo'lardi. Qorovul taymer buni ushlaydi.
  it('rVFC kadr bermasa QOROVUL halqani turtadi', async () => {
    const h = boot({ rvfc: 'never' });
    const id = h.api.create('host-rvfc-dead');
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(1000);
    const a = diag(h, id);
    expect(a.watchdogKicks).toBeGreaterThan(0);
    expect(a.attempts).toBeGreaterThan(0);
    await h.tick(900);
    const b = diag(h, id);
    expect(b.attempts).toBeGreaterThan(a.attempts);   // to'xtab qolmadi
    expect(b.loopAlive).toBe(true);
    h.api.dispose(id);
  }, 15000);

  it('taymer rejimida ham urinishlar oraligi qayd etiladi', async () => {
    const h = boot({ rvfc: 'no' });
    const id = h.api.create('host-gap');
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(400);
    const d = diag(h, id);
    expect(d.sched).toBe('timer');
    expect(d.gapMs).not.toBe('-');                   // med/p95/max yozilgan
    h.api.dispose(id);
  });
});

describe('pauza — javob tayyorlanayotganda ip Dart\'niki', () => {
  it('pauza urinishni to\'xtatadi, kamera esa TIRIK qoladi', async () => {
    const h = boot();
    const id = h.api.create('host-pause');
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(300);
    h.api.pause(id);
    const a = diag(h, id);
    expect(a.paused).toBe(true);
    await h.tick(400);
    const b = diag(h, id);
    expect(b.attempts).toBe(a.attempts);             // dekodlash to'xtadi
    expect(b.pausedSkips).toBeGreaterThan(0);
    expect(b.running).toBe(true);                    // ... lekin sessiya tirik
    expect(b.decoderReady).toBe(true);
    h.api.resume(id);
    await h.tick(400);
    expect(diag(h, id).attempts).toBeGreaterThan(b.attempts);
    h.api.dispose(id);
  }, 15000);

  // Dublikat qulfi Dart javob berguncha kerak, undan KEYIN emas: operator ayni
  // mahsulotni qayta skanerlasa kutib qolmasin.
  it('resume dublikat qulfini tozalaydi (ayni kod DARHOL qayta yuboriladi)', async () => {
    const h = boot();
    const id = h.api.create('host-dup');
    const seen: string[] = [];
    h.setDecoder(() => ({ getText: () => '4700024930227', getBarcodeFormat: () => 'EAN_13' }));
    h.api.setCallback(id, (c: string) => { seen.push(c); h.api.pause(id); });
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(300);
    expect(seen.length).toBe(1);
    h.api.resume(id);                                 // Dart javobni tugatdi
    await h.tick(300);
    expect(seen.length).toBe(2);                      // ... va AYNI kod qayta keldi
    h.api.dispose(id);
  });
});

describe('ROI — JS va Dart bitta manbada', () => {
  // Operatorga ko'rsatilayotgan ramka AYNAN dekodlanadigan oynani bildirishi
  // kerak. Ikki fayl ajralib ketsa ramka yolg'on ko'rsata boshlaydi.
  it('web/scanner.js va lib/platform/scanner.dart dagi ROI teng', () => {
    const dart = fs.readFileSync(
      path.resolve(__dirname, '../apps/mobile/lib/platform/scanner.dart'), 'utf-8');
    const m = SRC.match(/ROI_W\s*=\s*([\d.]+),\s*ROI_H\s*=\s*([\d.]+)/);
    expect(m, 'scanner.js dagi ROI topilmadi').toBeTruthy();
    const dw = dart.match(/kScanRoiW\s*=\s*([\d.]+)/);
    const dh = dart.match(/kScanRoiH\s*=\s*([\d.]+)/);
    expect(dw, 'scanner.dart dagi kScanRoiW topilmadi').toBeTruthy();
    expect(dh, 'scanner.dart dagi kScanRoiH topilmadi').toBeTruthy();
    expect(Number(dw![1])).toBe(Number(m![1]));
    expect(Number(dh![1])).toBe(Number(m![2]));
  });
});

describe('kesim EKRAN fazosida hisoblanadi (object-fit: cover)', () => {
  // Real iPhone 16 Pro'da topilgan nuqson: kesim INTRINSIC koordinatada
  // olinardi, preview esa portret qutida `cover` bilan ko'rsatiladi — ekranda
  // landshaft kadrning atigi ~26% i ko'rinadi. Natijada ramkada katta ko'ringan
  // barkod dekoderga ~2 px/modul bo'lib tushardi va o'qilmasdi.
  it('landshaft oqim + portret quti: kesim KORINADIGAN bolakdan olinadi', async () => {
    const h = boot({ videoWidth: 1920, videoHeight: 1080, cssWidth: 402, cssHeight: 874 });
    const id = h.api.create('host-cover');
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(250);
    const d = diag(h, id);
    // cover: scale = max(402/1920, 874/1080) = 0.8093 -> korinadigan en = 402/0.8093 = 497 px
    expect(d.coverScale).toBeCloseTo(0.81, 2);
    expect(d.visibleFrac).toBeCloseTo(0.26, 2);
    // ROI = korinadigan qutining 86% x 28% -> ~427 x ~278, INTRINSIC 86% (1651) EMAS.
    expect(d.cropW).toBeGreaterThan(380);
    expect(d.cropW).toBeLessThan(470);
    expect(d.cropH).toBeGreaterThan(240);
    expect(d.cropH).toBeLessThan(320);
    expect(d.cropScale).toBe(1);        // bunday kichik kesim SIQILMAYDI
    h.api.dispose(id);
  });

  it('portret oqim: deyarli butun en korinadi', async () => {
    const h = boot({ videoWidth: 1080, videoHeight: 1920, cssWidth: 402, cssHeight: 874 });
    const id = h.api.create('host-portrait');
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(250);
    expect(diag(h, id).visibleFrac).toBeGreaterThan(0.8);
    h.api.dispose(id);
  });
});

describe('kesim narxi cheklangan', () => {
  // ⚠️  Ilgari cheklov faqat ENGA qo'yilgandi (`MAX_CROP_W`). Portret qutida
  //     ko'rinadigan bo'lak BALAND va tor bo'ladi (4K da ~993x2158), ya'ni en
  //     chegarasi HECH QACHON ishlamasdi va dekodga 2.1 MP li kadr ketardi —
  //     muvaffaqiyatsiz dekod narxi esa piksel soniga proporsional.
  it('4K oqim + portret quti: kesim JAMI piksel chegarasidan oshmaydi', async () => {
    const h = boot({ videoWidth: 3840, videoHeight: 2160, cssWidth: 402, cssHeight: 874 });
    const id = h.api.create('host-cap');
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(300);
    const d = diag(h, id);
    const cap = Number(SRC.match(/MAX_CROP_PX\s*=\s*(\d+)/)![1]);
    expect(d.cropPx).toBeLessThanOrEqual(cap);
    expect(d.cropW * d.cropH).toBe(d.cropPx);
    h.api.dispose(id);
  });

  it('BALANDLIK ham qisqaradi (eski cheklov faqat enni ushlardi)', async () => {
    // 4K oqim + planshetdek portret quti: ko‘rinadigan bo‘lak ~1216x2160, ya’ni
    // tasma ~1046x605 = 633k px. Eski `MAX_CROP_W = 1600` cheklovi bu yerda
    // UMUMAN ishlamasdi (1046 < 1600) va 633k px dekodga ketaverardi.
    const h = boot({ videoWidth: 3840, videoHeight: 2160, cssWidth: 900, cssHeight: 1600 });
    const id = h.api.create('host-cap2');
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(300);
    const d = diag(h, id);
    const cap = Number(SRC.match(/MAX_CROP_PX\s*=\s*(\d+)/)![1]);
    expect(d.cropPx).toBeLessThanOrEqual(cap);
    expect(d.cropScale).toBeLessThan(1);          // siqildi
    expect(d.cropW).toBeLessThan(1046);           // en qisqardi
    expect(d.cropH).toBeLessThan(605);            // ... va BALANDLIK ham
    h.api.dispose(id);
  });

  it('kanvas qayta-qayta ajratilmaydi (tasma o\'lchami doimiy)', async () => {
    const h = boot();
    const id = h.api.create('host-canvas');
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(600);
    const d = diag(h, id);
    expect(d.attempts).toBeGreaterThan(4);
    // Bitta o'lcham -> bitta ajratish. (Ilgari ROI va keng kesim navbatlashib,
    // kanvas har to'rt urinishda ikki marta qayta ajratilardi.)
    expect(h.canvasResizes()).toBeLessThanOrEqual(1);
    h.api.dispose(id);
  });
});

describe('tasma supurish va format navbati', () => {
  it('tasma uch vertikal o\'rinda navbat bilan olinadi', async () => {
    const h = boot({ videoWidth: 1920, videoHeight: 1080, cssWidth: 402, cssHeight: 874 });
    const id = h.api.create('host-band');
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(500);
    const ys = new Set(h.grabs.map((g) => g.sy));
    expect(ys.size).toBeGreaterThanOrEqual(3);          // markaz + yuqori + past
    const xs = new Set(h.grabs.map((g) => g.sx));
    expect(xs.size).toBe(1);                            // gorizontal o'rin o'zgarmaydi
    const sizes = new Set(h.grabs.map((g) => `${g.sw}x${g.sh}`));
    expect(sizes.size).toBe(1);                         // o'lcham ham
    h.api.dispose(id);
  });

  it('to\'liq format to\'plami VAQT bo\'yicha ishlaydi (har urinishda emas)', async () => {
    const h = boot();
    const id = h.api.create('host-all');
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(900);
    const d = diag(h, id);
    expect(d.attempts).toBeGreaterThan(4);
    expect(d.roiAttempts).toBeGreaterThan(0);
    expect(d.wideAttempts).toBeGreaterThan(0);          // tolerantlik yo'li ishlaydi
    // ... lekin issiq yo'lni egallab olmaydi: oraliq kamida ALL_FORMATS_EVERY_MS.
    const gap = Number(SRC.match(/ALL_FORMATS_EVERY_MS\s*=\s*(\d+)/)![1]);
    expect(d.wideAttempts).toBeLessThanOrEqual(Math.ceil(900 / gap) + 1);
    expect(d.roiAttempts).toBeGreaterThan(d.wideAttempts);
    h.api.dispose(id);
  }, 15000);
});

describe('diagnostika bayrogi tuzogi', () => {
  // `bool.fromEnvironment` FAQAT literal "true" ni tan oladi: `--dart-define=X=1`
  // bilan u JIMGINA `false` bo'ladi va panel bundle'dan tushib qoladi. Birinchi
  // nomzodda aynan shu bo'lgan.
  it('scanner.dart bool.fromEnvironment ISHLATMAYDI', () => {
    const dart = fs.readFileSync(
      path.resolve(__dirname, '../apps/mobile/lib/platform/scanner.dart'), 'utf-8');
    expect(dart).not.toContain("bool.fromEnvironment('BINOS_SCAN_DIAG')");
    expect(dart).toContain("String.fromEnvironment('BINOS_SCAN_DIAG')");
    for (const v of ['1', 'true']) expect(dart).toContain(`== '${v}'`);
  });
});

describe('dekoder hintlari HAR urinishda saqlanadi', () => {
  // ⚠️  Vendored ZXing da `decode(t, e)` — `setHints(e)` ni bajaradi. Bitta
  //     argument bilan chaqirilsa hintlar `undefined` bo'ladi: format ro'yxati
  //     o'chadi va ZXing zaxira tarmog'iga tushib QR/DataMatrix/Aztec/PDF417
  //     hamda takroriy 1D o'quvchilarni qo'shadi. Teksturali topilmaydigan
  //     kadrda bu 427x302 uchun 147 ms (15 ms o'rniga), 700x500 uchun 352 ms
  //     (35 ms o'rniga) — qidiruv rejimidagi butun vaqt shu yerda edi.
  it('skaner decodeWithState ni chaqiradi (decode emas)', async () => {
    const h = boot();
    const id = h.api.create('host-hints');
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(300);
    expect(h.apiCalls.length).toBeGreaterThan(0);
    expect(new Set(h.apiCalls)).toEqual(new Set(['decodeWithState']));
    expect(JSON.parse(h.api.diagnostics(id)).decodeApi).toBe('decodeWithState');
    h.api.dispose(id);
  });

  it('hintlar dekod paytida HAM joyida turadi (format ro‘yxati o‘chmaydi)', async () => {
    const h = boot();
    const id = h.api.create('host-hints2');
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(300);
    expect(h.hintsAtDecode.length).toBeGreaterThan(0);
    for (const hints of h.hintsAtDecode) {
      expect(hints, 'hintlar yuvilgan').toBeTruthy();
      const formats = hints.get(2);                 // DecodeHintType.POSSIBLE_FORMATS
      expect(Array.isArray(formats)).toBe(true);
      expect(formats.length).toBeGreaterThan(0);
    }
    h.api.dispose(id);
  });

  it('TRY_HARDER yoqilmaydi (hintlar amal qilganda 960–2400 ms)', async () => {
    const h = boot();
    const id = h.api.create('host-th');
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(300);
    for (const hints of h.hintsAtDecode) {
      expect(hints.get(3), 'TRY_HARDER yoqilgan').toBeUndefined();   // DecodeHintType.TRY_HARDER
    }
    expect(SRC).not.toContain('TRY_HARDER, true');
    h.api.dispose(id);
  });

  it('zaxira: decodeWithState bo‘lmasa ham halqa ishlaydi', async () => {
    const h = boot();
    // Eski/boshqa ZXing buildi: faqat `decode` bor.
    delete (h.ctx.ZXing.MultiFormatReader.prototype as any).decodeWithState;
    const id = h.api.create('host-nostate');
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(300);
    const d = JSON.parse(h.api.diagnostics(id));
    expect(d.attempts).toBeGreaterThan(0);
    expect(d.decodeApi).toBe('decode');
    h.api.dispose(id);
  });
});
