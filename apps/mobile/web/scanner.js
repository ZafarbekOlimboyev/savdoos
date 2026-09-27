/*
 * BinOS — web barkod skaneri (iPhone/Safari uchun o'z quvurimiz).
 *
 * NEGA O'Z QUVURIMIZ. `mobile_scanner` ning web yo'li kamerani cheklovsiz
 * so'raydi (`{video:{facingMode:'environment'}}`; `cameraResolution` web
 * implementatsiyasida UMUMAN o'qilmaydi) va ZXing halqasi kutilmagan istisnoda
 * JIM o'ladi (faqat NotFound/Checksum/Format qayta rejalashtiriladi) — kamera
 * esa oqim berishda davom etadi. Natija: mukammal preview, nol urinish.
 *
 * ⚠️  KOORDINATA TUZOG'I (real iPhone 16 Pro, 2026-09-26). Preview `object-fit:
 *     cover` bilan PORTRET qutida ko'rsatiladi, kamera esa LANDSHAFT kadr
 *     beradi: 1920x1080 oqim ~402x874 qutida "cover" qilinsa ekranda video
 *     enining ATIGI ~26% i ko'rinadi. Shu bois kesim EKRAN fazosida hisoblanib,
 *     `cover` o'zgarishi orqali video koordinatasiga qaytariladi: dekodlanadigan
 *     joy — AYNAN ramkada ko'ringan joy.
 *
 * ⚠️  TEZLIK — hammasi O'LCHANGAN (2026-09-27), taxmin emas. Skaner qidirib
 *     yurganda kadrlarning deyarli HAMMASI muvaffaqiyatsiz, ya'ni UX ni
 *     muvaffaqiyatsiz kadr narxi belgilaydi (muvaffaqiyatli dekod ~1 ms).
 *       1. `decode(bitmap)` — vendored buildda `setHints(undefined)` ni
 *          bajaradi va format ro'yxatini HAR URINISHDA o'chiradi (1 o'quvchi →
 *          5: QR/DataMatrix/Aztec/PDF417 + takroriy 1D). Teksturali
 *          topilmaydigan kadrda: 427x302 da 147 ms, 700x500 da 352 ms.
 *          `decodeWithState` bilan: 15 ms va 35 ms. ENG KATTA yutuq shu.
 *       2. TRY_HARDER — hintlar amal qilganda 427x302 da 960 ms, 700x500 da
 *          2406 ms (butun kadr qatorma-qator + 90° burib qayta urinish).
 *          O'CHIRILGAN.
 *       3. `drawImage(video, ...)` 4K manbadan 70–165 ms va kesim
 *          KICHRAYTIRILSA HAM kamaymaydi (narx — kadrni GPU dan olish).
 *          `createImageBitmap(video, sx,sy,sw,sh)` ~0.1 ms; to'liq sikl 1080p
 *          da 20.3 → 9.4 ms, topilmaydigan kadrda 33.3 → 21.7 ms.
 *       4. Dekod narxi PIKSELGA proporsional, shu bois kesim JAMI PIKSEL
 *          bo'yicha cheklanadi — portretda BALANDLIK ham (ilgari faqat en
 *          cheklanardi va dekodga 2.1 MP li kadr ketardi).
 *     Shundan: `createImageBitmap` (zaxira — `drawImage`), `decodeWithState`,
 *     TRY_HARDER yo'q, jami piksel chegarasi, va butun ko'rinadigan qutini
 *     bitta ulkan kesimda olish O'RNIGA tor tasmani uchta vertikal o'rinda
 *     navbat bilan supurish: narx bir xil, dekod oson, qamrov kengroq.
 *
 * ⚠️  Barkod MATNI o'zgarmasdan Dart tomoniga uzatiladi: tarozi etiketkasi
 *     qoidasi (`27` + PLU(5) + gramm(5)) va mahsulotga moslashtirish SERVERDA.
 *
 * MAXFIYLIK: kadr, rasm, video HECH QAYERGA yuborilmaydi. Diagnostika faqat
 * sanoq, o'lcham va vaqt; barkod QIYMATI diagnostikaga tushmaydi.
 */
(function () {
  'use strict';

  var sessions = Object.create(null);
  var seq = 0;

  // Ramka (va dekodlanadigan tasma) — KO'RINADIGAN qutining ulushi.
  // ⚠️  `lib/platform/scanner.dart` dagi `kScanRoiW`/`kScanRoiH` bilan AYNI
  //     bo'lishi SHART (`tests/scanner-loop.test.ts` tekshiradi).
  var ROI_W = 0.86, ROI_H = 0.28;
  // Tasmaning vertikal markazlari: ramka (0.50), undan yuqori va past. Ramkadan
  // tashqarisi — TOLERANTLIK, va'da emas: o'lcham o'zgarmagani uchun narxi ham
  // o'zgarmaydi.
  var BANDS = [0.50, 0.30, 0.70];
  // Kesimning JAMI pikseli. ⚠️  Faqat ENNI cheklash YETARLI EMAS: portret
  // qutida ko'rinadigan bo'lak baland va tor bo'ladi (masalan 993x2158), ya'ni
  // en chegarasi hech qachon ishlamay, dekodga 2.1 MP li kadr ketardi.
  var MAX_CROP_PX = 350000;
  // To'liq 1D to'plami (Code128/39/ITF ham) shu oraliqdan tez-tez ishlamaydi:
  // u tolerantlik uchun, issiq yo'l uchun emas (28–82 ms va 15–35 ms).
  var ALL_FORMATS_EVERY_MS = 350;
  // rVFC kelmasa (kamera muzladi, brauzer qo'llamaydi) halqani turtadi.
  var WATCHDOG_MS = 700;
  // Bir xil kod ketma-ket kadrlarda takrorlanmasin. Dart javob bergach
  // (`resume`) bu holat TOZALANADI — operator ayni mahsulotni qayta skanerlasa
  // kutib qolmaydi.
  var DUP_MS = 1200;

  function fastFormats(Z) {
    var F = Z.BarcodeFormat;
    return [F.EAN_13, F.EAN_8, F.UPC_A, F.UPC_E];
  }
  function allFormats(Z) {
    var F = Z.BarcodeFormat;
    return [F.EAN_13, F.EAN_8, F.UPC_A, F.UPC_E, F.CODE_128, F.CODE_39, F.ITF];
  }

  // Hammasi `ideal` — `exact` EMAS. Yuqori o'lcham MUHIM: portret qutida
  // landshaft kadrning ~26% i ko'rinadi, manba qancha katta bo'lsa ko'rinadigan
  // bo'lakda shuncha ko'p piksel qoladi. Kadr olish endi arzon (bitmap), shu
  // bois yuqori o'lcham tezlikka zarar qilmaydi.
  function constraintLadder() {
    var env = { ideal: 'environment' };
    return [
      { video: { facingMode: env, width: { ideal: 3840 }, height: { ideal: 2160 }, frameRate: { ideal: 30 } } },
      { video: { facingMode: env, width: { ideal: 1920 }, height: { ideal: 1080 }, frameRate: { ideal: 30 } } },
      { video: { facingMode: env, width: { ideal: 1280 }, height: { ideal: 720 } } },
      { video: { facingMode: env } },
      { video: true },
    ];
  }

  function nowMs() { return (self.performance && performance.now) ? performance.now() : Date.now(); }
  function S(id) { return sessions[id]; }

  // ── Kichik o'lchov jamlagichi ───────────────────────────────────────────────
  // O'rtacha yolg'on gapiradi: operator SAKRASHNI (p95) sezadi. Oxirgi 64 ta
  // qiymat yetarli va xotira o'smaydi.
  function meter() { return { n: 0, sum: 0, max: 0, ring: [], i: 0 }; }
  function note(m, ms) {
    m.n++; m.sum += ms; if (ms > m.max) m.max = ms;
    if (m.ring.length < 64) m.ring.push(ms); else { m.ring[m.i] = ms; m.i = (m.i + 1) % 64; }
  }
  function quant(m, p) {
    if (!m.ring.length) return 0;
    var a = m.ring.slice().sort(function (x, y) { return x - y; });
    return a[Math.min(a.length - 1, Math.floor(p * a.length))];
  }
  function r1(x) { return Math.round(x * 10) / 10; }
  function report(m) {
    if (!m.n) return '-';
    return r1(quant(m, 0.5)) + '/' + r1(quant(m, 0.95)) + '/' + r1(m.max);   // med/p95/max
  }

  function newSession(containerId) {
    var id = 'bs' + (++seq);
    sessions[id] = {
      id: id, containerId: containerId,
      stream: null, video: null,
      slot: null,
      reader: null, readerAll: null,
      timer: null, watchdog: null, rvfc: 0,
      running: false, paused: false, busy: false,
      useBitmap: true, sched: 'timer',
      cb: null, band: 0, lastAllAt: 0, lastTickAt: 0,
      lastCode: '', lastCodeAt: 0,
      stat: { acquire: meter(), readback: meter(), decode: meter(), gap: meter(), deliver: meter() },
      diag: {
        permission: 'unknown', cameras: 0, selectedLabel: '',
        constraintStep: -1, facingMode: '',
        videoWidth: 0, videoHeight: 0, readyState: 0,
        trackWidth: 0, trackHeight: 0, trackFps: 0,
        cssWidth: 0, cssHeight: 0, coverScale: 0, visibleFrac: 0,
        cropW: 0, cropH: 0, cropScale: 1, cropPx: 0,
        decoderReady: false, detector: 'n/a',
        acquirePath: '-', bitmapFallback: '', decodeApi: '-',
        framesGrabbed: 0, attempts: 0, roiAttempts: 0, wideAttempts: 0, successes: 0,
        hiddenSkips: 0, pausedSkips: 0, attemptsBeforeHit: 0, firstHitMs: 0,
        lastFormat: '', lastPath: '', lastErrorKind: '',
        loopErrors: 0, grabErrors: 0, starts: 0, watchdogKicks: 0,
        startedAt: 0, firstFrameMs: 0, lastFrameAt: 0,
      },
    };
    return id;
  }

  function openStream(s) {
    var ladder = constraintLadder();
    var i = 0;
    function attempt() {
      if (i >= ladder.length) return Promise.reject(new Error('NoConstraintWorked'));
      var step = i++;
      return navigator.mediaDevices.getUserMedia(ladder[step]).then(function (stream) {
        s.diag.constraintStep = step;
        return stream;
      }, function (err) {
        var n = (err && err.name) || '';
        if (n === 'NotAllowedError' || n === 'SecurityError') throw err;
        if (n === 'NotFoundError' || n === 'NotReadableError') throw err;
        return attempt();
      });
    }
    return attempt();
  }

  function waitForFrame(video, timeoutMs) {
    return new Promise(function (resolve) {
      var t0 = nowMs();
      (function poll() {
        if (video.videoWidth > 0 && video.videoHeight > 0 && video.readyState >= 2) return resolve(true);
        if (nowMs() - t0 > timeoutMs) return resolve(false);
        setTimeout(poll, 50);
      })();
    });
  }

  // Kamera ROSTDAN nima berganini yozamiz. Cheklovlar `ideal`, ya'ni ular hech
  // qachon rad etilmaydi: qurilma 4K berdimi yoki 720p — buni FAQAT shu yerdan
  // bilish mumkin, taxmin qilib bo'lmaydi.
  function describeStream(s) {
    var t = s.stream && s.stream.getVideoTracks ? s.stream.getVideoTracks()[0] : null;
    if (!t) return;
    s.diag.selectedLabel = t.label || '';
    try {
      var st = t.getSettings ? t.getSettings() : {};
      if (st.facingMode) s.diag.facingMode = st.facingMode;
      if (st.width) s.diag.trackWidth = st.width;
      if (st.height) s.diag.trackHeight = st.height;
      if (st.frameRate) s.diag.trackFps = Math.round(st.frameRate);
    } catch (e) { /* getSettings hamma joyda yo'q */ }
  }

  function countCameras(s) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
    navigator.mediaDevices.enumerateDevices().then(function (l) {
      s.diag.cameras = l.filter(function (d) { return d.kind === 'videoinput'; }).length;
    }, function () { /* ruxsatsiz ro'yxat bo'sh bo'ladi */ });
  }

  // `object-fit: cover`: video `scale = max(cw/vw, ch/vh)` bilan kattalashib
  // chekkalari KESILADI, ya'ni ekranda manbaning markaziy `cw/scale` x `ch/scale`
  // bo'lagi ko'rinadi. Ramka — SHU bo'lakning ulushi.
  function visibleBox(s) {
    var v = s.video;
    var vw = v.videoWidth, vh = v.videoHeight;
    var cw = v.clientWidth || vw, ch = v.clientHeight || vh;
    var scale = Math.max(cw / vw, ch / vh);
    var visW = Math.min(vw, cw / scale), visH = Math.min(vh, ch / scale);
    s.diag.cssWidth = Math.round(cw);
    s.diag.cssHeight = Math.round(ch);
    s.diag.coverScale = Math.round(scale * 100) / 100;
    s.diag.visibleFrac = Math.round((visW / vw) * 100) / 100;
    return { x: (vw - visW) / 2, y: (vh - visH) / 2, w: visW, h: visH };
  }

  // Navbatdagi tasma: markazi BANDS bo'yicha suriladi, o'lchami o'zgarmaydi.
  function regionFor(s) {
    var b = visibleBox(s);
    var w = b.w * ROI_W, h = b.h * ROI_H;
    var cy = BANDS[s.band % BANDS.length];
    var y = b.y + b.h * cy - h / 2;
    y = Math.max(b.y, Math.min(b.y + b.h - h, y));       // qutidan chiqmasin
    return { x: b.x + (b.w - w) / 2, y: y, w: w, h: h, band: s.band % BANDS.length };
  }

  // Jami piksel bo'yicha cheklov — IKKALA o'q ham qisqaradi.
  // ⚠️  Pastga yaxlitlash: yuqoriga yaxlitlansa natija chegaradan bir necha yuz
  //     piksel oshib ketardi va "kesim chegaradan oshmaydi" invarianti YOLG'ON
  //     bo'lardi.
  function fitCrop(w, h) {
    var k = Math.min(1, Math.sqrt(MAX_CROP_PX / Math.max(1, w * h)));
    return { w: Math.max(1, Math.floor(w * k)), h: Math.max(1, Math.floor(h * k)), k: k };
  }

  // Bitta canvas yetarli: tasma o'lchami har doim bir xil, ya'ni canvas bir
  // marta ajratiladi. (Ilgari ROI va keng kesim navbatlashib, canvas sekundiga
  // ~14 marta qayta ajratilardi — har safar nol bilan to'ldirilib.)
  function slotFor(s, dw, dh) {
    var slot = s.slot;
    if (!slot) {
      slot = { c: document.createElement('canvas'), ctx: null, lum: null };
      slot.ctx = slot.c.getContext('2d', { willReadFrequently: true });
      s.slot = slot;
    }
    if (slot.c.width !== dw || slot.c.height !== dh) {
      slot.c.width = dw; slot.c.height = dh; slot.lum = null;
    }
    return slot;
  }

  // Kadrni olish. Asosiy yo'l — `createImageBitmap` (GPU tomonida kesadi);
  // zaxira — `drawImage`. Zaxiraga o'tish BIR MARTA bo'ladi va diagnostikada
  // ko'rinadi.
  function acquire(s, region) {
    var v = s.video;
    if (!v || !(v.videoWidth > 0 && v.videoHeight > 0)) return Promise.resolve(null);
    s.diag.videoWidth = v.videoWidth;
    s.diag.videoHeight = v.videoHeight;
    s.diag.readyState = v.readyState;

    var d = fitCrop(region.w, region.h);
    var slot = slotFor(s, d.w, d.h);
    var sx = Math.max(0, Math.round(region.x)), sy = Math.max(0, Math.round(region.y));
    var sw = Math.max(1, Math.min(v.videoWidth - sx, Math.round(region.w)));
    var sh = Math.max(1, Math.min(v.videoHeight - sy, Math.round(region.h)));
    var t0 = nowMs();

    function finish(path) {
      s.diag.acquirePath = path;
      s.diag.cropW = d.w; s.diag.cropH = d.h;
      s.diag.cropScale = Math.round(d.k * 100) / 100;
      s.diag.cropPx = d.w * d.h;
      s.diag.framesGrabbed++;
      s.diag.lastFrameAt = nowMs();
      note(s.stat.acquire, nowMs() - t0);
      return slot;
    }
    function viaDraw() {
      try {
        slot.ctx.drawImage(v, sx, sy, sw, sh, 0, 0, d.w, d.h);
        return finish('drawImage');
      } catch (e) {
        s.diag.grabErrors++;
        s.diag.lastErrorKind = (e && e.name) ? String(e.name) : 'DrawImage';
        return null;
      }
    }

    if (s.useBitmap && typeof self.createImageBitmap === 'function') {
      var p;
      try {
        p = self.createImageBitmap(v, sx, sy, sw, sh);
      } catch (e) {
        s.useBitmap = false;
        s.diag.bitmapFallback = (e && e.name) || 'sinxron';
        return Promise.resolve(viaDraw());
      }
      return Promise.resolve(p).then(function (bmp) {
        try { slot.ctx.drawImage(bmp, 0, 0, d.w, d.h); }
        finally { try { bmp.close(); } catch (e2) { /* close hamma joyda yo'q */ } }
        return finish('bitmap');
      }, function (e) {
        s.useBitmap = false;                       // bir marta: keyin drawImage
        s.diag.bitmapFallback = (e && e.name) || 'xato';
        return viaDraw();
      });
    }
    return Promise.resolve(viaDraw());
  }

  // Piksellarni o'qish + dekod. Luminance buferi QAYTA ISHLATILADI: har
  // urinishda yangi massiv ajratish ip uzilishlariga olib keladi.
  function decodeSlot(s, Z, slot, useAll) {
    var w = slot.c.width, h = slot.c.height;
    var t0 = nowMs();
    var im;
    try {
      im = slot.ctx.getImageData(0, 0, w, h).data;
    } catch (e) {
      s.diag.grabErrors++;
      s.diag.lastErrorKind = (e && e.name) ? String(e.name) : 'getImageData';
      return null;
    }
    if (!slot.lum || slot.lum.length !== w * h) slot.lum = new Uint8ClampedArray(w * h);
    var lum = slot.lum;
    for (var i = 0, j = 0; i < im.length; i += 4, j++) {
      lum[j] = (im[i] * 306 + im[i + 1] * 601 + im[i + 2] * 117) >> 10;
    }
    note(s.stat.readback, nowMs() - t0);

    var reader = useAll ? s.readerAll : s.reader;
    if (!reader) return null;
    var t1 = nowMs();
    try {
      var bitmap = new Z.BinaryBitmap(new Z.HybridBinarizer(new Z.RGBLuminanceSource(lum, w, h)));
      // ⚠️  `decode(bitmap)` NI CHAQIRMANG. Vendored buildda u
      //     `decode(t, e) { return this.setHints(e), this.decodeInternal(t) }`,
      //     ya'ni BITTA argument bilan chaqirilsa `setHints(undefined)` bajariladi:
      //     start paytida berilgan format ro'yxati HAR URINISHDA o'chadi va
      //     ZXing zaxira tarmog'iga tushib, QRCode/DataMatrix/Aztec/PDF417 hamda
      //     takroriy 1D o'quvchilarni qo'shadi (o'lchangan: 1 o'quvchi → 5).
      //     Narxi (node, teksturali topilmaydigan kadr): 427x302 da 147 ms
      //     o'rniga 15 ms, 700x500 da 352 ms o'rniga 35 ms — ya'ni qidiruv
      //     rejimida deyarli BUTUN vaqt shu yerda ketardi.
      //     `decodeWithState` sozlangan o'quvchilarni SAQLAYDI.
      s.diag.decodeApi = reader.decodeWithState ? 'decodeWithState' : 'decode';
      return reader.decodeWithState ? reader.decodeWithState(bitmap) : reader.decode(bitmap);
    } catch (e) {
      var n = (e && (e.name || (e.constructor && e.constructor.name))) || 'Error';
      if (n.indexOf('NotFound') !== 0) s.diag.lastErrorKind = n;   // NotFound — normal
      return null;
    } finally {
      note(s.stat.decode, nowMs() - t1);
      try { reader.reset(); } catch (e2) { /* holatni tozalash */ }
    }
  }

  function tick(s, Z) {
    // Sahifa yashirin bo'lsa kadr OLINMAYDI (batareya). Buni SANAYMIZ: aks holda
    // panel "halqa tirik, urinish 0" deb turadi va sabab noma'lum qoladi.
    if (document.hidden) { s.diag.hiddenSkips++; return null; }
    // Dart javob bilan band (qidiryapti, varaq ochiq) — ip UNIKI bo'lsin.
    if (s.paused) { s.diag.pausedSkips++; return null; }

    var t = nowMs();
    if (s.lastTickAt) note(s.stat.gap, t - s.lastTickAt);
    s.lastTickAt = t;

    var useAll = (t - s.lastAllAt) >= ALL_FORMATS_EVERY_MS;
    var region = regionFor(s);
    s.band++;

    return acquire(s, region).then(function (slot) {
      if (!slot) return;
      s.diag.attempts++;
      if (useAll) { s.lastAllAt = nowMs(); s.diag.wideAttempts++; } else { s.diag.roiAttempts++; }

      var res = decodeSlot(s, Z, slot, useAll);
      if (!res) return;

      var text = '';
      try { text = res.getText ? res.getText() : (res.text || ''); } catch (e) { text = ''; }
      if (!text) return;

      s.diag.successes++;
      s.diag.lastPath = (useAll ? 'toliq' : 'tez') + '/tasma' + region.band;
      try { s.diag.lastFormat = String(res.getBarcodeFormat ? res.getBarcodeFormat() : ''); } catch (e) { /* ixtiyoriy */ }
      if (!s.diag.firstHitMs) {
        s.diag.firstHitMs = Math.round(nowMs() - s.diag.startedAt);
        s.diag.attemptsBeforeHit = s.diag.attempts;
      }

      var now2 = nowMs();
      if (text === s.lastCode && (now2 - s.lastCodeAt) < DUP_MS) return;
      s.lastCode = text; s.lastCodeAt = now2;
      if (s.cb) {
        var tCb = nowMs();
        try { s.cb(text); } catch (e) { /* Dart tomoni */ }
        note(s.stat.deliver, nowMs() - tCb);       // ko'prik + Dart ning sinxron qismi
      }
    });
  }

  // ⚠️  HALQA HECH QACHON O'LMASLIGI KERAK — `mobile_scanner` web yo'lidagi
  //     nuqson aynan shu edi. Har bir yo'l (sinxron istisno, rad etilgan va'da,
  //     rVFC kelmasligi) keyingi urinishni REJALASHTIRADI.
  function runTick(s, Z) {
    if (!s.running || s.busy) return;
    s.busy = true;
    var done = function () {
      s.busy = false;
      if (s.running) schedule(s, Z);
    };
    var p = null;
    try {
      p = tick(s, Z);
    } catch (e) {
      s.diag.loopErrors++;
      s.diag.lastErrorKind = (e && (e.name || e.message)) ? String(e.name || e.message).slice(0, 60) : 'LoopError';
    }
    if (p && typeof p.then === 'function') {
      p.then(done, function (e) {
        s.diag.loopErrors++;
        s.diag.lastErrorKind = (e && (e.name || e.message)) ? String(e.name || e.message).slice(0, 60) : 'AsyncLoopError';
        done();
      });
    } else done();
  }

  // Kadr KELGANDA ishlaymiz (`requestVideoFrameCallback`), taymer bo'yicha emas:
  // bir xil kadrni ikki marta dekodlash ham, yangi kadrni kutib turish ham
  // yo'qoladi. rVFC yo'q yoki kelmay qolsa — qorovul taymer turtadi.
  function schedule(s, Z) {
    if (!s.running) return;
    var v = s.video;
    if (v && typeof v.requestVideoFrameCallback === 'function') {
      try {
        s.sched = 'rvfc';
        s.rvfc = v.requestVideoFrameCallback(function () { s.rvfc = 0; runTick(s, Z); });
      } catch (e) { s.sched = 'timer'; }
    } else s.sched = 'timer';
    if (s.sched === 'timer') s.timer = setTimeout(function () { s.timer = null; runTick(s, Z); }, 8);
    armWatchdog(s, Z);
  }

  function armWatchdog(s, Z) {
    if (s.watchdog) clearTimeout(s.watchdog);
    s.watchdog = setTimeout(function () {
      s.watchdog = null;
      if (!s.running) return;
      if (s.paused || document.hidden) { armWatchdog(s, Z); return; }   // ataylab jim
      if (nowMs() - s.lastTickAt < WATCHDOG_MS) { armWatchdog(s, Z); return; }
      s.diag.watchdogKicks++;
      s.busy = false;                                   // osilib qolgan urinishni tark etamiz
      runTick(s, Z);
    }, WATCHDOG_MS);
  }

  function clearTimers(s) {
    if (s.timer) { clearTimeout(s.timer); s.timer = null; }
    if (s.watchdog) { clearTimeout(s.watchdog); s.watchdog = null; }
    if (s.rvfc && s.video && typeof s.video.cancelVideoFrameCallback === 'function') {
      try { s.video.cancelVideoFrameCallback(s.rvfc); } catch (e) { /* ixtiyoriy */ }
    }
    s.rvfc = 0;
  }

  var api = {
    create: function (containerId) { return newSession(containerId); },

    start: function (id) {
      var s = S(id);
      if (!s) return Promise.resolve('generic');
      var Z = self.ZXing;
      if (!Z || !Z.MultiFormatReader) { s.diag.permission = 'unsupported'; return Promise.resolve('unsupported'); }
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        s.diag.permission = 'unsupported';
        return Promise.resolve('unsupported');
      }
      // Native `BarcodeDetector` BOR-YO'QLIGI faqat TEKSHIRILADI (taxmin
      // qilinmaydi) va diagnostikaga yoziladi. Safari da odatda yo'q — ZXing
      // asosiy yo'l bo'lib qoladi.
      s.diag.detector = (typeof self.BarcodeDetector === 'function') ? 'mavjud' : 'yoq';
      s.diag.startedAt = nowMs();

      return openStream(s).then(function (stream) {
        s.stream = stream;
        s.diag.permission = 'granted';
        describeStream(s);

        var host = document.getElementById(s.containerId);
        if (!host) return 'generic';
        var v = document.createElement('video');
        v.setAttribute('playsinline', '');
        v.setAttribute('autoplay', '');
        v.setAttribute('muted', '');
        v.muted = true;
        v.style.width = '100%'; v.style.height = '100%';
        v.style.objectFit = 'cover';
        v.style.display = 'block';
        host.textContent = '';
        host.appendChild(v);
        s.video = v;
        v.srcObject = stream;

        return Promise.resolve(v.play()).catch(function () { /* autoplay siyosati */ })
          .then(function () { return waitForFrame(v, 6000); })
          .then(function (ok) {
            s.diag.firstFrameMs = Math.round(nowMs() - s.diag.startedAt);
            if (!ok) { s.diag.lastErrorKind = 'NoVideoDimensions'; return 'generic'; }
            s.diag.videoWidth = v.videoWidth;
            s.diag.videoHeight = v.videoHeight;
            s.diag.readyState = v.readyState;
            describeStream(s);                       // o'lchamlar endi aniq

            // ⚠️  TRY_HARDER YOQILMAYDI. Hintlar haqiqatda amal qilganda (yuqoriga
            //     qarang: `decodeWithState`) u OneDReader ni kadrning HAMMA
            //     qatorini skanerlashga va muvaffaqiyatsizlikda rasmni 90° ga
            //     burib QAYTA urinishga majbur qiladi. O'lchangan: 427x302 da
            //     960 ms, 700x500 da 2406 ms — bitta urinish. Ilgari u zararsiz
            //     ko'rinardi, chunki hintlar baribir o'chib ketardi.
            function mk(formats) {
              var h = new Map();
              h.set(Z.DecodeHintType.POSSIBLE_FORMATS, formats);
              var r = new Z.MultiFormatReader();
              r.setHints(h);
              return r;
            }
            // Issiq yo'l: chakana EAN/UPC (o'lchangan 15–35 ms).
            s.reader = mk(fastFormats(Z));
            // Tolerantlik yo'li: Code128/39/ITF ham (28–82 ms), har
            // ALL_FORMATS_EVERY_MS da bir marta.
            s.readerAll = mk(allFormats(Z));
            s.diag.decoderReady = true;
            s.diag.starts++;

            v.addEventListener('resize', function () {
              s.diag.videoWidth = v.videoWidth;
              s.diag.videoHeight = v.videoHeight;
              describeStream(s);
            });

            s.running = true;
            s.paused = false;
            s.lastTickAt = nowMs();
            countCameras(s);
            schedule(s, Z);
            return 'ok';
          });
      }, function (err) {
        var n = (err && err.name) || '';
        if (n === 'NotAllowedError' || n === 'SecurityError') { s.diag.permission = 'denied'; return 'permission'; }
        if (n === 'NotFoundError' || n === 'OverconstrainedError') { s.diag.permission = 'unsupported'; return 'unsupported'; }
        s.diag.permission = 'error';
        s.diag.lastErrorKind = n || 'getUserMedia';
        return 'generic';
      });
    },

    setCallback: function (id, fn) { var s = S(id); if (s) s.cb = fn; },

    // Kod topilgach Dart javob berayotganda dekodlashni TO'XTATAMIZ: ip bitta,
    // va o'sha paytda operator kutayotgan narsa — reaksiya, keyingi kadr emas.
    // Kamera, oqim va o'quvchilar TIRIK qoladi, ya'ni davom etish darhol.
    pause: function (id) { var s = S(id); if (s) s.paused = true; },

    resume: function (id) {
      var s = S(id);
      if (!s) return;
      s.paused = false;
      // Dart keyingi kodni kutyapti — dublikat qulfini ochamiz, aks holda AYNI
      // mahsulotni qayta skanerlash `DUP_MS` gacha kutardi.
      s.lastCode = ''; s.lastCodeAt = 0;
      s.lastTickAt = nowMs();
    },

    stop: function (id) {
      var s = S(id);
      if (!s) return;
      s.running = false;
      s.busy = false;
      clearTimers(s);
      if (s.stream) {
        try { s.stream.getTracks().forEach(function (t) { t.stop(); }); } catch (e) { /* to'xtagan */ }
        s.stream = null;
      }
      if (s.video) {
        try { s.video.srcObject = null; s.video.remove(); } catch (e) { /* DOM dan olingan */ }
        s.video = null;
      }
      s.slot = null;
      s.reader = null; s.readerAll = null;
      s.diag.decoderReady = false;
    },

    dispose: function (id) { api.stop(id); delete sessions[id]; },

    diagnostics: function (id) {
      var s = S(id);
      if (!s) return '{}';
      var d = s.diag, out = {};
      for (var k in d) if (Object.prototype.hasOwnProperty.call(d, k) && k.charAt(0) !== '_') out[k] = d[k];
      var secs = d.startedAt ? Math.max(0.001, (nowMs() - d.startedAt) / 1000) : 0.001;
      out.attemptsPerSec = Math.round((d.attempts / secs) * 10) / 10;
      out.running = s.running;
      out.paused = s.paused;
      out.sched = s.sched;
      out.loopAlive = !!(s.running && (s.timer || s.rvfc || s.busy || s.watchdog));
      out.lastFrameAgeMs = d.lastFrameAt ? Math.round(nowMs() - d.lastFrameAt) : -1;
      out.roi = ROI_W + 'x' + ROI_H;
      out.bands = BANDS.length;
      // med/p95/max (ms) — o'rtacha emas: operator sakrashni sezadi.
      out.acquireMs = report(s.stat.acquire);
      out.readbackMs = report(s.stat.readback);
      out.decodeMs = report(s.stat.decode);
      out.gapMs = report(s.stat.gap);
      out.deliverMs = report(s.stat.deliver);
      // Eski nomlar panel va testlar uchun saqlanadi.
      out.grabMsAvg = s.stat.acquire.n ? r1(s.stat.acquire.sum / s.stat.acquire.n) : 0;
      out.decodeMsAvg = s.stat.decode.n ? r1(s.stat.decode.sum / s.stat.decode.n) : 0;
      out.decodeMsMax = Math.round(s.stat.decode.max);
      return JSON.stringify(out);
    },
  };

  self.binosScanner = api;
})();
