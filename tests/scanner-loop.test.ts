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
// Quyidagi birinchi test aynan shuni qo'riqlaydi.
import { beforeEach, describe, expect, it } from 'vitest';
import * as fs from 'fs';
import * as path from 'path';
import * as vm from 'vm';

const SCANNER = path.resolve(__dirname, '../apps/mobile/web/scanner.js');

interface Harness {
  api: any;
  ctx: any;
  video: any;
  decodeCalls: () => number;
  setDecoder: (fn: (bitmap: unknown) => unknown) => void;
  tick: (ms: number) => Promise<void>;
}

/// Soxta DOM + soxta ZXing bilan `scanner.js` ni yuklaydi.
function boot(opts: {
  videoWidth?: number;
  videoHeight?: number;
  getUserMedia?: (c: unknown) => Promise<unknown>;
} = {}): Harness {
  let decodeCalls = 0;
  let decoder: (bitmap: unknown) => unknown = () => {
    const e = new Error('not found');
    e.name = 'NotFoundException';
    throw e;
  };

  const track = {
    label: 'Back Camera',
    stop() {},
    getSettings: () => ({ facingMode: 'environment', width: opts.videoWidth ?? 1920, height: opts.videoHeight ?? 1080 }),
  };
  const stream = { getVideoTracks: () => [track], getTracks: () => [track] };

  const video: any = {
    videoWidth: opts.videoWidth ?? 1920,
    videoHeight: opts.videoHeight ?? 1080,
    readyState: 4,
    style: {},
    muted: false,
    srcObject: null,
    setAttribute() {},
    addEventListener() {},
    remove() {},
    play: () => Promise.resolve(),
  };

  const host: any = { id: '', style: {}, textContent: '', appendChild() {} };
  const canvas: any = {
    width: 0, height: 0,
    getContext: () => ({ drawImage() {} }),
  };

  const ctx: any = {
    console,
    Map, Promise, Error, Math, JSON, Object, String, Number, Date, Set,
    setTimeout, clearTimeout,
    performance: { now: () => Date.now() },
    document: {
      hidden: false,
      getElementById: (id: string) => (id === host.id ? host : null),
      createElement: (tag: string) => (tag === 'video' ? video : canvas),
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
      HybridBinarizer: class { constructor(public s: unknown) {} },
      BinaryBitmap: class { constructor(public b: unknown) {} },
      MultiFormatReader: class {
        hints: unknown;
        setHints(h: unknown) { this.hints = h; }
        reset() {}
        decode(bitmap: unknown) { decodeCalls++; return decoder(bitmap); }
      },
    },
  };
  ctx.self = ctx;
  ctx.globalThis = ctx;
  ctx.window = ctx;
  vm.createContext(ctx);
  new vm.Script(fs.readFileSync(SCANNER, 'utf-8'), { filename: 'scanner.js' }).runInContext(ctx);

  const api = ctx.binosScanner;
  // Host `div` ni ro'yxatdan o'tkazamiz: `create()` bergan id bilan.
  const origCreate = api.create.bind(api);
  api.create = (containerId: string) => { host.id = containerId; return origCreate(containerId); };

  return {
    api, ctx, video,
    decodeCalls: () => decodeCalls,
    setDecoder: (fn) => { decoder = fn; },
    tick: (ms: number) => new Promise<void>((r) => setTimeout(r, ms)),
  };
}

describe('web skaner quvuri — xulq', () => {
  let h: Harness;
  beforeEach(() => { h = boot(); });

  it('`binosScanner` ko\'prigi e\'lon qilinadi', () => {
    for (const m of ['create', 'start', 'stop', 'dispose', 'setCallback', 'diagnostics']) {
      expect(typeof h.api[m], m).toBe('function');
    }
  });

  it('kamera ochiladi va dekodlash halqasi yuradi', async () => {
    const id = h.api.create('host-1');
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(400);
    const d = JSON.parse(h.api.diagnostics(id));
    expect(d.permission).toBe('granted');
    expect(d.decoderReady).toBe(true);
    expect(d.videoWidth).toBe(1920);
    expect(d.attempts).toBeGreaterThan(0);
    expect(d.cameras).toBe(2);
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
    const first = JSON.parse(h.api.diagnostics(id)).attempts;
    await h.tick(400);
    const second = JSON.parse(h.api.diagnostics(id)).attempts;
    expect(first).toBeGreaterThan(0);
    expect(second).toBeGreaterThan(first);           // halqa davom etmoqda
    const d = JSON.parse(h.api.diagnostics(id));
    expect(d.running).toBe(true);
    expect(d.lastErrorKind).toBe('TypeError');       // xato YUTILMAYDI, qayd etiladi
    expect(d.successes).toBe(0);
    h.api.dispose(id);
  });

  // TASHQI QORIQCHI. Istisno `decodeOnce` ning try blokidan TASHQARIDA tugiladi
  // (media element yaroqsiz bolib qolgan holat). `loop()` dagi try/catch olib
  // tashlansa — halqa BIR MARTA yiqilib, sessiya oxirigacha olik qoladi va
  // `loopErrors` osmaydi. Aynan shu narsa `mobile_scanner` web yolidagi nuqson edi.
  it("kadr olishda istisno bolsa ham halqa TIRIK qoladi (tashqi qoriqchi)", async () => {
    const id = h.api.create('host-2b');
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(250);
    Object.defineProperty(h.video, 'videoWidth', {
      configurable: true,
      get() { const e = new Error('invalid state'); e.name = 'InvalidStateError'; throw e; },
    });
    await h.tick(400);
    const a = JSON.parse(h.api.diagnostics(id));
    await h.tick(400);
    const b = JSON.parse(h.api.diagnostics(id));
    expect(a.loopErrors).toBeGreaterThan(0);
    expect(b.loopErrors).toBeGreaterThan(a.loopErrors);
    expect(b.running).toBe(true);
    expect(b.lastErrorKind).toBe('InvalidStateError');
    h.api.dispose(id);
  });

  it('video o\'lchami kelmasa START xato qaytaradi (0x0 kanvas keshlanmaydi)', async () => {
    const h0 = boot({ videoWidth: 0, videoHeight: 0 });
    const id = h0.api.create('host-3');
    const res = await h0.api.start(id);
    expect(res).toBe('generic');
    const d = JSON.parse(h0.api.diagnostics(id));
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
    expect(JSON.parse(h2.api.diagnostics(id)).permission).toBe('denied');
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
    expect(JSON.parse(h3.api.diagnostics(id)).constraintStep).toBe(2);
    h3.api.dispose(id);
  });

  it('bitta kod -> bitta chaqiruv (takror bosilmaydi)', async () => {
    const id = h.api.create('host-6');
    const seen: string[] = [];
    h.setDecoder(() => ({ getText: () => '4780000000038', getBarcodeFormat: () => 'EAN_13' }));
    h.api.setCallback(id, (code: string) => seen.push(code));
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(600);                                 // bir necha tik
    expect(seen.length).toBe(1);                       // 1.5 s ichida FAQAT bitta
    const d = JSON.parse(h.api.diagnostics(id));
    expect(d.successes).toBeGreaterThan(1);            // dekodlash esa davom etgan
    expect(d.lastFormat).toBe('EAN_13');
    h.api.dispose(id);
  });

  it('stop kamerani va halqani to\'xtatadi, start qayta tiklaydi', async () => {
    const id = h.api.create('host-7');
    expect(await h.api.start(id)).toBe('ok');
    await h.tick(250);
    h.api.stop(id);
    const stopped = JSON.parse(h.api.diagnostics(id));
    expect(stopped.running).toBe(false);
    expect(stopped.decoderReady).toBe(false);
    const before = stopped.attempts;
    await h.tick(300);
    expect(JSON.parse(h.api.diagnostics(id)).attempts).toBe(before);   // o'lik halqa yo'q
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
    // `MultiFormatReader.setHints` ga berilgan POSSIBLE_FORMATS ro'yxati.
    const src = fs.readFileSync(SCANNER, 'utf-8');
    for (const f of ['EAN_13', 'EAN_8', 'UPC_A', 'UPC_E', 'CODE_128', 'CODE_39', 'ITF']) {
      expect(src).toContain(`F.${f}`);
    }
    h.api.dispose(id);
  });
});

describe('ROI — JS va Dart bitta manbada', () => {
  // Operatorga ko'rsatilayotgan ramka AYNAN dekodlanadigan oynani bildirishi
  // kerak. Ikki fayl ajralib ketsa ramka yolg'on ko'rsata boshlaydi.
  it('web/scanner.js va lib/platform/scanner.dart dagi ROI teng', () => {
    const js = fs.readFileSync(SCANNER, 'utf-8');
    const dart = fs.readFileSync(
      path.resolve(__dirname, '../apps/mobile/lib/platform/scanner.dart'), 'utf-8');
    const m = js.match(/ROI_W\s*=\s*([\d.]+),\s*ROI_H\s*=\s*([\d.]+)/);
    expect(m, 'scanner.js dagi ROI topilmadi').toBeTruthy();
    const dw = dart.match(/kScanRoiW\s*=\s*([\d.]+)/);
    const dh = dart.match(/kScanRoiH\s*=\s*([\d.]+)/);
    expect(dw, 'scanner.dart dagi kScanRoiW topilmadi').toBeTruthy();
    expect(dh, 'scanner.dart dagi kScanRoiH topilmadi').toBeTruthy();
    expect(Number(dw![1])).toBe(Number(m![1]));
    expect(Number(dh![1])).toBe(Number(m![2]));
  });
});
