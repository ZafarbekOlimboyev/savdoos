/*
 * BinOS — web barkod skaneri (iPhone/Safari uchun o'z quvurimiz).
 *
 * NEGA O'Z QUVURIMIZ. `mobile_scanner` ning web yo'li kamerani cheklovsiz
 * so'raydi (`{video:{facingMode:'environment'}}`; `cameraResolution` web
 * implementatsiyasida UMUMAN o'qilmaydi) va ZXing halqasi kutilmagan istisnoda
 * JIM o'ladi (faqat NotFound/Checksum/Format qayta rejalashtiriladi) — kamera
 * esa oqim berishda davom etadi. Natija: mukammal preview, nol urinish.
 *
 * ⚠️  KOORDINATA TUZOG'I (real iPhone 16 Pro'da o'lchangan, 2026-09-26).
 *     Preview `object-fit: cover` bilan PORTRET qutida ko'rsatiladi, kamera esa
 *     LANDSHAFT kadr beradi. 1920x1080 oqim ~402x874 CSS qutida "cover" qilinsa
 *     ekranda video enining ATIGI ~26% i ko'rinadi. Kesimni intrinsic
 *     koordinatada (enining 86%) olish — operator KO'RMAYDIGAN maydonni
 *     dekodlash demak: ekranda katta ko'ringan barkod intrinsic kadrda ~13% en
 *     egallaydi va modulga ~2 piksel qoladi (ZXing chegarasi). Shu bois kesim
 *     ENDI EKRAN fazosida hisoblanib, `cover` o'zgarishi orqali video
 *     koordinatasiga qaytariladi: dekodlanadigan joy — AYNAN ramkada ko'ringan joy.
 *
 * ⚠️  TEZLIK (o'lchangan: `node` da haqiqiy ZXing). Muvaffaqiyatli dekod ~1 ms,
 *     lekin MUVAFFAQIYATSIZ kadr qimmat: 1280x720 / 7 format / TRY_HARDER
 *     ~1145 ms, 1280x385 ~500 ms, 960x140 ~355 ms. Skaner qidirib yurganda
 *     kadrlarning deyarli hammasi muvaffaqiyatsiz — UX'ni AYNAN shu narx
 *     belgilaydi. Shuning uchun: tor TASMA (1D kodga balandlik kam kerak),
 *     tez yo'lda faqat EAN/UPC va TRY_HARDER'siz; to'liq format to'plami va
 *     kengroq maydon har 4-urinishda (tolerantlik saqlanadi).
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
  // Har nechanchi urinishda butun ko'rinadigan quti + to'liq format to'plami.
  var WIDE_EVERY = 4;
  // Kesim kengligi shundan oshsa siqiladi (CPU chegarasi).
  var MAX_CROP_W = 1600;

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
  // bo'lakda shuncha ko'p piksel qoladi.
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

  function newSession(containerId) {
    var id = 'bs' + (++seq);
    sessions[id] = {
      id: id, containerId: containerId,
      stream: null, video: null, canvas: null, ctx: null,
      reader: null, readerAll: null,
      timer: null, running: false, cb: null,
      lastCode: '', lastCodeAt: 0,
      diag: {
        permission: 'unknown', cameras: 0, selectedLabel: '',
        constraintStep: -1, facingMode: '',
        videoWidth: 0, videoHeight: 0, readyState: 0,
        cssWidth: 0, cssHeight: 0, coverScale: 0, visibleFrac: 0,
        cropW: 0, cropH: 0, cropScale: 1,
        decoderReady: false, detector: 'n/a',
        framesGrabbed: 0, attempts: 0, roiAttempts: 0, wideAttempts: 0, successes: 0,
        grabMsAvg: 0, decodeMsAvg: 0, decodeMsMax: 0,
        lastFormat: '', lastPath: '', lastErrorKind: '',
        loopErrors: 0, grabErrors: 0, starts: 0,
        startedAt: 0, firstFrameMs: 0, lastFrameAt: 0,
        _grabSum: 0, _decSum: 0, _decN: 0,
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

  function describeStream(s) {
    var t = s.stream && s.stream.getVideoTracks ? s.stream.getVideoTracks()[0] : null;
    if (!t) return;
    s.diag.selectedLabel = t.label || '';
    try {
      var st = t.getSettings ? t.getSettings() : {};
      if (st.facingMode) s.diag.facingMode = st.facingMode;
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

  function grab(s, wide) {
    var t0 = nowMs();
    var v = s.video;
    if (!v || !(v.videoWidth > 0 && v.videoHeight > 0)) return null;
    s.diag.videoWidth = v.videoWidth;
    s.diag.videoHeight = v.videoHeight;
    s.diag.readyState = v.readyState;

    var b = visibleBox(s);
    var w = wide ? b.w : b.w * ROI_W;
    var h = wide ? b.h : b.h * ROI_H;
    var x = b.x + (b.w - w) / 2;
    var y = b.y + (b.h - h) / 2;

    var k = Math.min(1, MAX_CROP_W / w);
    var dw = Math.max(1, Math.round(w * k)), dh = Math.max(1, Math.round(h * k));
    if (!s.canvas) {
      s.canvas = document.createElement('canvas');
      s.ctx = s.canvas.getContext('2d', { willReadFrequently: true });
    }
    if (s.canvas.width !== dw || s.canvas.height !== dh) {
      s.canvas.width = dw; s.canvas.height = dh;
    }
    try {
      s.ctx.drawImage(v, Math.round(x), Math.round(y), Math.round(w), Math.round(h), 0, 0, dw, dh);
    } catch (e) {
      s.diag.grabErrors++;
      s.diag.lastErrorKind = (e && e.name) ? String(e.name) : 'DrawImage';
      return null;
    }
    s.diag.cropW = dw; s.diag.cropH = dh;
    s.diag.cropScale = Math.round(k * 100) / 100;
    s.diag.framesGrabbed++;
    s.diag.lastFrameAt = nowMs();
    s.diag._grabSum += (nowMs() - t0);
    s.diag.grabMsAvg = Math.round((s.diag._grabSum / s.diag.framesGrabbed) * 10) / 10;
    return s.canvas;
  }

  function decodeWith(s, Z, canvas, wide) {
    var reader = wide ? s.readerAll : s.reader;
    if (!reader) return null;
    try {
      var src = new Z.HTMLCanvasElementLuminanceSource(canvas);
      return reader.decode(new Z.BinaryBitmap(new Z.HybridBinarizer(src)));
    } catch (e) {
      var n = (e && (e.name || (e.constructor && e.constructor.name))) || 'Error';
      if (n.indexOf('NotFound') !== 0) s.diag.lastErrorKind = n;   // NotFound — normal
      return null;
    } finally {
      try { reader.reset(); } catch (e2) { /* holatni tozalash */ }
    }
  }

  function tick(s, Z) {
    if (document.hidden) return;
    var wide = (s.diag.attempts % WIDE_EVERY) === (WIDE_EVERY - 1);
    var canvas = grab(s, wide);
    if (!canvas) return;
    s.diag.attempts++;
    if (wide) s.diag.wideAttempts++; else s.diag.roiAttempts++;

    var t0 = nowMs();
    var res = decodeWith(s, Z, canvas, wide);
    var dt = nowMs() - t0;
    s.diag._decSum += dt; s.diag._decN++;
    s.diag.decodeMsAvg = Math.round((s.diag._decSum / s.diag._decN) * 10) / 10;
    if (dt > s.diag.decodeMsMax) s.diag.decodeMsMax = Math.round(dt);
    if (!res) return;

    var text = '';
    try { text = res.getText ? res.getText() : (res.text || ''); } catch (e) { text = ''; }
    if (!text) return;
    s.diag.successes++;
    s.diag.lastPath = wide ? 'wide' : 'roi';
    try { s.diag.lastFormat = String(res.getBarcodeFormat ? res.getBarcodeFormat() : ''); } catch (e) { /* ixtiyoriy */ }
    var t = nowMs();
    if (!(text === s.lastCode && (t - s.lastCodeAt) < 1500)) {
      s.lastCode = text; s.lastCodeAt = t;
      if (s.cb) { try { s.cb(text); } catch (e) { /* Dart tomoni */ } }
    }
  }

  // ⚠️  HALQA HECH QACHON O'LMASLIGI KERAK — `mobile_scanner` web yo'lidagi
  //     nuqson aynan shu edi. Butun tana try/catch ichida va keyingi tik HAR
  //     DOIM rejalashtiriladi. Dekodning o'zi yuzlab ms turadi, shu bois
  //     qo'shimcha kutish qisqa (ilgari 120 ms edi).
  function loop(s, Z) {
    if (!s.running) return;
    try {
      tick(s, Z);
    } catch (e) {
      s.diag.loopErrors++;
      s.diag.lastErrorKind = (e && (e.name || e.message)) ? String(e.name || e.message).slice(0, 60) : 'LoopError';
    }
    s.timer = setTimeout(function () { loop(s, Z); }, 16);
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
      // qilinmaydi) va diagnostikaga yoziladi. Safari'da odatda yo'q — ZXing
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

            function mk(formats, tryHarder) {
              var h = new Map();
              h.set(Z.DecodeHintType.POSSIBLE_FORMATS, formats);
              if (tryHarder) h.set(Z.DecodeHintType.TRY_HARDER, true);
              var r = new Z.MultiFormatReader();
              r.setHints(h);
              return r;
            }
            s.reader = mk(fastFormats(Z), false);
            s.readerAll = mk(allFormats(Z), true);
            s.diag.decoderReady = true;
            s.diag.starts++;

            v.addEventListener('resize', function () {
              s.diag.videoWidth = v.videoWidth;
              s.diag.videoHeight = v.videoHeight;
            });

            s.running = true;
            countCameras(s);
            loop(s, Z);
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

    stop: function (id) {
      var s = S(id);
      if (!s) return;
      s.running = false;
      if (s.timer) { clearTimeout(s.timer); s.timer = null; }
      if (s.stream) {
        try { s.stream.getTracks().forEach(function (t) { t.stop(); }); } catch (e) { /* to'xtagan */ }
        s.stream = null;
      }
      if (s.video) {
        try { s.video.srcObject = null; s.video.remove(); } catch (e) { /* DOM'dan olingan */ }
        s.video = null;
      }
      s.canvas = null; s.ctx = null; s.reader = null; s.readerAll = null;
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
      out.loopAlive = !!(s.running && s.timer);
      out.lastFrameAgeMs = d.lastFrameAt ? Math.round(nowMs() - d.lastFrameAt) : -1;
      out.roi = ROI_W + 'x' + ROI_H;
      return JSON.stringify(out);
    },
  };

  self.binosScanner = api;
})();
