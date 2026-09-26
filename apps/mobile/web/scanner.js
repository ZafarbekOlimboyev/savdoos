/*
 * BinOS — web barkod skaneri (iPhone/Safari uchun o'z quvurimiz).
 *
 * NEGA O'Z QUVURIMIZ. `mobile_scanner` ning web yo'li kamerani AYNAN shunday
 * so'raydi (mobile_scanner-5.2.3/lib/src/web/mobile_scanner_web.dart):
 *
 *     getUserMedia({ video: { facingMode: 'environment' } })
 *
 * — hech qanday `width`/`height`/`frameRate` yo'q, va `cameraResolution`
 * parametri web implementatsiyasida UMUMAN o'qilmaydi (`grep` bilan
 * tekshirilgan: `lib/src/web/` da bu nom uchramaydi). Ya'ni plagin API'si
 * orqali o'lchamni ko'tarishning yo'li yo'q. Cheklovsiz `environment` oqimda
 * Safari past standart o'lchamni beradi; ZXing esa BUTUN kadrni, format
 * ko'rsatmasisiz dekodlaydi. Natijada ko'z uchun tiniq preview, decoder uchun
 * esa EAN-13 ning ingichka chiziqlari ~1 pikseldan kam.
 *
 * ⚠️  Bu quvur SHU qatlamni — kamera va dekodlashni — almashtiradi. Barkod
 *     MATNI o'zgarmasdan Dart tomoniga uzatiladi: tarozi etiketkasi qoidasi
 *     (`27` + PLU(5) + gramm(5) + EAN-13) va mahsulotga moslashtirish
 *     SERVERDA (`GET /products/scan`) qoladi — bu yerda tegilmaydi.
 *
 * ⚠️  CSP: `script-src 'self'` — shu bois alohida fayl, inline skript yo'q.
 *     ZXing `index.html` da `vendor/` dan oldindan yuklanadi (global `ZXing`).
 *
 * MAXFIYLIK: kadr, rasm yoki видео HECH QAYERGA yuborilmaydi. Diagnostika
 * faqat SANOQ va o'lchamlardan iborat; barkod qiymati diagnostikaga tushmaydi.
 */
(function () {
  'use strict';

  var sessions = Object.create(null);
  var seq = 0;

  // Chakana savdoda uchraydigan formatlar. Ro'yxat cheklangani decoderni
  // tezlashtiradi: cheklanmasa ZXing har kadrda HAMMA simvologiyani sinaydi.
  // Tarozi etiketkasi — oddiy EAN-13, shu ro'yxat uni qamrab oladi.
  function formatList(Z) {
    var F = Z.BarcodeFormat;
    return [F.EAN_13, F.EAN_8, F.UPC_A, F.UPC_E, F.CODE_128, F.CODE_39, F.ITF];
  }

  // Constraint narvoni: har bir pog'ona OLDINGISIDAN kamroq talab qiladi.
  // Hammasi `ideal` — `exact` EMAS: qo'llab-quvvatlanmagan cheklov kamerani
  // umuman ochilmay qolishiga OLIB KELMASIN (OverconstrainedError).
  function constraintLadder() {
    var env = { ideal: 'environment' };
    return [
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
      id: id,
      containerId: containerId,
      stream: null, video: null, canvas: null, ctx: null,
      reader: null, timer: null, running: false,
      cb: null,
      lastCode: '', lastCodeAt: 0,
      diag: {
        permission: 'unknown',       // unknown | granted | denied | unsupported | error
        cameras: 0,                  // enumerateDevices dagi videoinput soni
        selectedLabel: '',           // brauzer bersa
        constraintStep: -1,          // narvonning nechanchi pog'onasi ishladi
        videoWidth: 0, videoHeight: 0, readyState: 0, facingMode: '',
        decoderReady: false,
        attempts: 0, successes: 0,
        roiAttempts: 0, fullAttempts: 0,
        lastFormat: '', lastErrorKind: '',
        loopErrors: 0, grabErrors: 0, starts: 0,
        startedAt: 0, firstFrameMs: 0,
      },
    };
    return id;
  }

  // ── Kamera ochish ──────────────────────────────────────────────────────────
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
        var name = (err && err.name) || '';
        // Ruxsat rad etilgan bo'lsa pastroq pog'ona ham yordam bermaydi.
        if (name === 'NotAllowedError' || name === 'SecurityError') throw err;
        if (name === 'NotFoundError' || name === 'NotReadableError') throw err;
        return attempt();     // OverconstrainedError va boshqalar -> pastroq talab
      });
    }
    return attempt();
  }

  // Video o'lchamlari KELGUNCHA kutamiz. Bu qadamsiz ZXing capture canvas'ni
  // 0x0 qilib YARATIB QO'YADI va uni keshlaydi — sessiya oxirigacha hech narsa
  // dekodlanmaydi (`getCaptureCanvas`: `if (!this.captureCanvas) …`).
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
    var track = s.stream && s.stream.getVideoTracks ? s.stream.getVideoTracks()[0] : null;
    if (!track) return;
    s.diag.selectedLabel = track.label || '';
    try {
      var st = track.getSettings ? track.getSettings() : {};
      if (st.facingMode) s.diag.facingMode = st.facingMode;
      if (st.width) s.diag.videoWidth = st.width;
      if (st.height) s.diag.videoHeight = st.height;
    } catch (e) { /* getSettings hamma joyda yo'q */ }
  }

  function countCameras(s) {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return Promise.resolve();
    return navigator.mediaDevices.enumerateDevices().then(function (list) {
      s.diag.cameras = list.filter(function (d) { return d.kind === 'videoinput'; }).length;
    }, function () { /* ruxsatsiz enumeratsiya bo'sh bo'lishi mumkin */ });
  }

  // ── Dekodlash ──────────────────────────────────────────────────────────────
  //
  // Ikki xil kadr NAVBATMA-NAVBAT sinaladi:
  //   ROI  — markaziy tasma (kattalashtirilgan, chiziqlar qalinroq);
  //   FULL — butun kadr (foydalanuvchi barkodni ramkaga aniq joylashtirmasa ham).
  // Shu bois tor cropga bog'lanib qolmaymiz: tolerantlik saqlanadi.
  // ⚠️  UI RAMKASI SHU QIYMATLARGA BOG'LANGAN: `lib/platform/scanner.dart`
  //     dagi `kScanRoiW`/`kScanRoiH` bilan AYNI bo'lishi SHART, aks holda
  //     operatorga ko'rsatilayotgan ramka dekodlanadigan joyni ALDAB ko'rsatadi.
  //     Moslikni `tests/scanner-loop.test.ts` tekshiradi.
  var ROI_W = 0.86, ROI_H = 0.46;     // kadr ulushi
  var MAX_EDGE = 1280;                // kanvas tomoni shundan oshmaydi (tezlik)

  function ensureCanvas(s, w, h) {
    if (!s.canvas) {
      s.canvas = document.createElement('canvas');
      s.ctx = s.canvas.getContext('2d', { willReadFrequently: true });
    }
    if (s.canvas.width !== w || s.canvas.height !== h) {
      s.canvas.width = w;         // o'lcham o'zgarsa kanvas QAYTA quriladi
      s.canvas.height = h;        // (video o'lchami almashishi Safari'da bo'ladi)
    }
  }

  function grab(s, useRoi) {
    var v = s.video;
    var vw = v.videoWidth, vh = v.videoHeight;
    if (!(vw > 0 && vh > 0)) return false;
    s.diag.videoWidth = vw; s.diag.videoHeight = vh; s.diag.readyState = v.readyState;

    var sx = 0, sy = 0, sw = vw, sh = vh;
    if (useRoi) {
      sw = Math.round(vw * ROI_W); sh = Math.round(vh * ROI_H);
      sx = Math.round((vw - sw) / 2); sy = Math.round((vh - sh) / 2);
    }
    var scale = Math.min(1, MAX_EDGE / Math.max(sw, sh));
    var dw = Math.max(1, Math.round(sw * scale)), dh = Math.max(1, Math.round(sh * scale));
    ensureCanvas(s, dw, dh);
    try {
      s.ctx.drawImage(v, sx, sy, sw, sh, 0, 0, dw, dh);
    } catch (e) {
      // iOS'da video vaqtincha "yaroqsiz" holatda bo'lsa `drawImage` tashlaydi.
      // Bu kadr o'tkazib yuboriladi; halqa DAVOM ETADI.
      s.diag.grabErrors++;
      s.diag.lastErrorKind = (e && e.name) ? String(e.name) : 'DrawImage';
      return false;
    }
    return true;
  }

  function decodeOnce(s, Z) {
    var useRoi = (s.diag.attempts % 2) === 0;
    if (!grab(s, useRoi)) return null;
    s.diag.attempts++;
    if (useRoi) s.diag.roiAttempts++; else s.diag.fullAttempts++;
    try {
      var src = new Z.HTMLCanvasElementLuminanceSource(s.canvas);
      var bitmap = new Z.BinaryBitmap(new Z.HybridBinarizer(src));
      var res = s.reader.decode(bitmap);
      return res;
    } catch (e) {
      // `NotFoundException` — kadrda barkod yo'q; bu XATO EMAS, normal holat.
      var n = (e && (e.name || (e.constructor && e.constructor.name))) || 'Error';
      if (n !== 'NotFoundException' && n !== 'NotFoundException2') s.diag.lastErrorKind = n;
      return null;
    } finally {
      try { s.reader.reset(); } catch (e2) { /* MultiFormatReader holatini tozalash */ }
    }
  }

  // ⚠️  HALQA HECH QACHON O'LMASLIGI KERAK. Aynan shu narsa `mobile_scanner` ning
  //     web yo'lidagi nuqson: ZXing `decodeContinuously` o'zini FAQAT
  //     NotFound/Checksum/Format istisnolarida qayta rejalashtiradi, boshqa har
  //     qanday throw (TypeError, DOMException) halqani butunlay to'xtatadi —
  //     kamera esa oqim berishda davom etadi. Natija: mukammal preview, nol
  //     dekodlash urinishi, hech qanday xato. Shu bois bu yerda BUTUN tana
  //     try/catch ichida va keyingi tik HAR DOIM rejalashtiriladi.
  function loop(s, Z) {
    if (!s.running) return;
    try {
      tick(s, Z);
    } catch (e) {
      s.diag.loopErrors++;
      s.diag.lastErrorKind = (e && (e.name || e.message)) ? String(e.name || e.message).slice(0, 60) : 'LoopError';
    }
    s.timer = setTimeout(function () { loop(s, Z); }, 120);
  }

  function tick(s, Z) {
    if (!document.hidden) {
      var res = decodeOnce(s, Z);
      if (res) {
        var text = '';
        try { text = res.getText ? res.getText() : (res.text || ''); } catch (e) { text = ''; }
        var fmt = '';
        try { fmt = String(res.getBarcodeFormat ? res.getBarcodeFormat() : ''); } catch (e) { fmt = ''; }
        if (text) {
          s.diag.successes++;
          s.diag.lastFormat = fmt;
          var t = nowMs();
          // Bitta kod -> bitta mantiqiy so'rov: ayni qiymat 1.5 s ichida takrorlanmaydi.
          if (!(text === s.lastCode && (t - s.lastCodeAt) < 1500)) {
            s.lastCode = text; s.lastCodeAt = t;
            if (s.cb) { try { s.cb(text); } catch (e) { /* Dart tomoni */ } }
          }
        }
      }
    }
  }

  // ── Ommaviy API ────────────────────────────────────────────────────────────
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
      s.diag.startedAt = nowMs();
      return openStream(s).then(function (stream) {
        s.stream = stream;
        s.diag.permission = 'granted';
        describeStream(s);

        var host = document.getElementById(s.containerId);
        if (!host) return 'generic';
        var v = document.createElement('video');
        // iOS: `playsinline` bo'lmasa Safari видеони to'liq ekranga oladi va
        // inline preview ishlamaydi; `muted` bo'lmasa avtomatik ijro bloklanadi.
        v.setAttribute('playsinline', '');
        v.setAttribute('autoplay', '');
        v.setAttribute('muted', '');
        v.muted = true;
        v.style.width = '100%'; v.style.height = '100%';
        v.style.objectFit = 'cover';        // faqat KO'RSATISH uchun; dekodlash
        v.style.display = 'block';          // xom `video` elementidan o'qiydi
        host.textContent = '';
        host.appendChild(v);
        s.video = v;
        v.srcObject = stream;

        return Promise.resolve(v.play()).catch(function () { /* autoplay siyosati */ })
          .then(function () { return waitForFrame(v, 6000); })
          .then(function (ok) {
            s.diag.firstFrameMs = Math.round(nowMs() - s.diag.startedAt);
            if (!ok) { s.diag.lastErrorKind = 'NoVideoDimensions'; return 'generic'; }
            s.diag.videoWidth = v.videoWidth; s.diag.videoHeight = v.videoHeight;
            s.diag.readyState = v.readyState;

            var hints = new Map();
            hints.set(Z.DecodeHintType.POSSIBLE_FORMATS, formatList(Z));
            hints.set(Z.DecodeHintType.TRY_HARDER, true);
            s.reader = new Z.MultiFormatReader();
            s.reader.setHints(hints);
            s.diag.decoderReady = true;
      s.diag.starts++;   // kamera nechа marta ishga tushdi

            // Video o'lchami almashsa kanvas qayta quriladi (`ensureCanvas`).
            v.addEventListener('resize', function () {
              s.diag.videoWidth = v.videoWidth; s.diag.videoHeight = v.videoHeight;
            });

            s.running = true;
            countCameras(s);
            loop(s, Z);
            return 'ok';
          });
      }, function (err) {
        var name = (err && err.name) || '';
        if (name === 'NotAllowedError' || name === 'SecurityError') { s.diag.permission = 'denied'; return 'permission'; }
        if (name === 'NotFoundError' || name === 'OverconstrainedError') { s.diag.permission = 'unsupported'; return 'unsupported'; }
        s.diag.permission = 'error';
        s.diag.lastErrorKind = name || 'getUserMedia';
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
        try { s.stream.getTracks().forEach(function (t) { t.stop(); }); } catch (e) { /* allaqachon to'xtagan */ }
        s.stream = null;
      }
      if (s.video) {
        try { s.video.srcObject = null; s.video.remove(); } catch (e) { /* DOM olib tashlangan */ }
        s.video = null;
      }
      // Kanvas va decoder tashlanadi: keyingi `start` ularni YANGIDAN quradi,
      // ya'ni eski o'lchamli kanvas yoki o'lik decoder qolib ketmaydi.
      s.canvas = null; s.ctx = null; s.reader = null;
      s.diag.decoderReady = false;
    },

    dispose: function (id) { api.stop(id); delete sessions[id]; },

    diagnostics: function (id) {
      var s = S(id);
      if (!s) return '{}';
      var d = s.diag;
      var secs = d.startedAt ? Math.max(0.001, (nowMs() - d.startedAt) / 1000) : 0.001;
      var out = {};
      for (var k in d) if (Object.prototype.hasOwnProperty.call(d, k)) out[k] = d[k];
      out.attemptsPerSec = Math.round((d.attempts / secs) * 10) / 10;
      out.running = s.running;
      out.loopAlive = !!(s.running && s.timer);
      out.roi = ROI_W + 'x' + ROI_H;
      return JSON.stringify(out);
    },
  };

  self.binosScanner = api;
})();
