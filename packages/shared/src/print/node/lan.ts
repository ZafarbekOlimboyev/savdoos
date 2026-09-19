// Tarmoq (LAN) ESC/POS printeriga xom TCP (odatda 9100 port) — Electron main.
//
// ⚠️  Manzil/port bu yerda TEKSHIRILMAYDI — chaqiruvchi (`ipc.ts`) `validate.ts` orqali faqat xususiy
//     IPv4 va 9100–9109 ni o'tkazadi. Sinovlar shu funksiyani 127.0.0.1 dagi "virtual printer"ga yo'naltiradi.
// ⚠️  TCP "yetkazildi" printer "chop etdi" degani EMAS: baytlar printer buferiga tushgach `ok: true`.
//     Qog'oz tugaganini faqat holat so'rovini (DLE EOT 4) qo'llaydigan profil oldindan aniqlaydi.
import * as net from "node:net";
import type { PrintResult } from "../bridge";

export interface LanOptions {
  /** Butun jarayon (ulanish + yozish) uchun muddat. */
  timeoutMs?: number;
  /** Profil `status_query` — yuborishdan oldin DLE EOT 4 (qog'oz sensori). */
  statusQuery?: boolean;
  /** Holat javobini kutish (ms). Javob bo'lmasa — davom etamiz (ko'p printer javob bermaydi). */
  statusWaitMs?: number;
}

const DLE_EOT_PAPER = Uint8Array.of(0x10, 0x04, 0x04);
const STATUS_WAIT_MS = 700;
const CLOSE_WAIT_MS = 1000;
const OFFLINE_ERRORS = new Set([
  "ECONNREFUSED", "EHOSTUNREACH", "ENETUNREACH", "EHOSTDOWN", "EADDRNOTAVAIL", "ENETDOWN", "ENOTFOUND",
]);

/**
 * DLE EOT 4 javob bayti: bit0=0, bit1=1, bit4=1, bit7=0 (qat'iy bitlar). Bit 5–6 = 11 → qog'oz tugagan.
 * Qat'iy bitlar mos kelmasa — bu holat bayti emas (printer boshqa narsa yubordi): e'tiborsiz.
 */
export function paperStatus(b: number): "ok" | "near_end" | "out" | "unknown" {
  if ((b & 0x93) !== 0x12) return "unknown";
  if ((b & 0x60) === 0x60) return "out";
  if ((b & 0x0c) === 0x0c) return "near_end";
  return "ok";
}

export function sendLan(host: string, port: number, bytes: Uint8Array, opts: LanOptions = {}): Promise<PrintResult> {
  const timeoutMs = Math.max(50, opts.timeoutMs ?? 5000);
  const statusWaitMs = Math.max(0, opts.statusWaitMs ?? STATUS_WAIT_MS);
  return new Promise<PrintResult>((resolve) => {
    const sock = new net.Socket();
    const warnings: string[] = [];
    let settled = false;
    let connected = false;
    let statusTimer: ReturnType<typeof setTimeout> | null = null;
    let closeTimer: ReturnType<typeof setTimeout> | null = null;

    const finish = (r: PrintResult) => {
      if (settled) return;
      settled = true;
      clearTimeout(overall);
      if (statusTimer) clearTimeout(statusTimer);
      if (closeTimer) clearTimeout(closeTimer);
      if (warnings.length && r.ok) r.warnings = [...(r.warnings ?? []), ...warnings];
      sock.removeAllListeners("data");
      sock.destroy();
      resolve(r);
    };

    const overall = setTimeout(() => {
      finish({ ok: false, code: "TIMEOUT", error: `${host}:${port} — ${timeoutMs} ms ichida javob yo'q` });
    }, timeoutMs);

    sock.on("error", (err: NodeJS.ErrnoException) => {
      const code = err.code ?? "";
      if (!connected && OFFLINE_ERRORS.has(code)) {
        finish({ ok: false, code: "OFFLINE", error: `${code} ${host}:${port}` });
      } else if (code === "ETIMEDOUT") {
        finish({ ok: false, code: "TIMEOUT", error: `${code} ${host}:${port}` });
      } else {
        finish({ ok: false, code: "FAILED", error: `${code || err.message || "socket error"} ${host}:${port}`.trim() });
      }
    });

    const writeReceipt = () => {
      if (settled) return;
      sock.removeAllListeners("data");
      sock.write(bytes, (err) => {
        if (err) return; // 'error' hodisasi natijani beradi
        // Baytlar yadroga topshirildi: FIN yuboramiz va printer yopishini qisqa kutamiz.
        sock.end();
        closeTimer = setTimeout(() => finish({ ok: true }), CLOSE_WAIT_MS);
      });
    };

    sock.on("close", () => {
      if (settled) return;
      if (closeTimer) finish({ ok: true });
      else finish({ ok: false, code: connected ? "FAILED" : "OFFLINE", error: `${host}:${port} ulanish yopildi` });
    });

    sock.connect({ host, port }, () => {
      connected = true;
      sock.setNoDelay(true);
      if (!opts.statusQuery) return writeReceipt();
      sock.once("data", (chunk: Buffer) => {
        if (statusTimer) clearTimeout(statusTimer);
        const st = paperStatus(chunk[0]);
        if (st === "out") {
          finish({ ok: false, code: "PAPER_OUT", error: "qog'oz tugagan (DLE EOT 4)" });
          return;
        }
        if (st === "near_end") warnings.push("paper_near_end");
        writeReceipt();
      });
      sock.write(DLE_EOT_PAPER);
      statusTimer = setTimeout(writeReceipt, statusWaitMs);
    });
  });
}
