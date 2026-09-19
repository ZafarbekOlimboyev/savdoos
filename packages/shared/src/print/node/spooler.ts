// Windows RAW chop etish (USB/COM termal printer drayveri orqali ESC/POS) — Electron main.
//
// Yo'l: PowerShell + ichki C# (winspool.drv: OpenPrinter → StartDocPrinter "RAW" → WritePrinter).
// ⚠️  IN'EKTSIYA YO'Q: skript matni O'ZGARMAS (hech narsa ichiga qo'yilmaydi). Printer nomi va baytlar
//     fayli yo'li `-File skript.ps1 <printer> <fayl>` ko'rinishida ALOHIDA argv elementlari bo'lib
//     o'tadi (`shell: false`), skript ularni `$args[0]`/`$args[1]` dan o'qiydi. Baytlar vaqtinchalik
//     faylga yoziladi (buyruq satriga emas) va ishdan keyin o'chiriladi.
// ⚠️  Windows'dan boshqa OT — REJECTED (CUPS raw yo'li hozircha yo'q).
import * as childProcess from "node:child_process";
import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import type { PrintResult } from "../bridge";

export const SPOOLER_SCRIPT = String.raw`$ErrorActionPreference = 'Stop'
$printer = [string]$args[0]
$dataPath = [string]$args[1]
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class BinosRawPrint {
  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
  public class DOCINFOW {
    [MarshalAs(UnmanagedType.LPWStr)] public string pDocName;
    [MarshalAs(UnmanagedType.LPWStr)] public string pOutputFile;
    [MarshalAs(UnmanagedType.LPWStr)] public string pDataType;
  }
  [DllImport("winspool.drv", EntryPoint = "OpenPrinterW", SetLastError = true, CharSet = CharSet.Unicode)]
  public static extern bool OpenPrinter(string pPrinterName, out IntPtr phPrinter, IntPtr pDefault);
  [DllImport("winspool.drv", SetLastError = true)]
  public static extern bool ClosePrinter(IntPtr hPrinter);
  [DllImport("winspool.drv", EntryPoint = "StartDocPrinterW", SetLastError = true, CharSet = CharSet.Unicode)]
  public static extern int StartDocPrinter(IntPtr hPrinter, int level, [In] DOCINFOW di);
  [DllImport("winspool.drv", SetLastError = true)]
  public static extern bool EndDocPrinter(IntPtr hPrinter);
  [DllImport("winspool.drv", SetLastError = true)]
  public static extern bool StartPagePrinter(IntPtr hPrinter);
  [DllImport("winspool.drv", SetLastError = true)]
  public static extern bool EndPagePrinter(IntPtr hPrinter);
  [DllImport("winspool.drv", SetLastError = true)]
  public static extern bool WritePrinter(IntPtr hPrinter, byte[] pBytes, int dwCount, out int dwWritten);
  public static int Send(string printer, byte[] data) {
    IntPtr h;
    if (!OpenPrinter(printer, out h, IntPtr.Zero)) return 2;
    try {
      DOCINFOW di = new DOCINFOW();
      di.pDocName = "BinOS receipt";
      di.pDataType = "RAW";
      if (StartDocPrinter(h, 1, di) == 0) return 3;
      try {
        if (!StartPagePrinter(h)) return 3;
        int written = 0;
        bool ok = WritePrinter(h, data, data.Length, out written);
        EndPagePrinter(h);
        if (!ok || written != data.Length) return 4;
      } finally {
        EndDocPrinter(h);
      }
      return 0;
    } finally {
      ClosePrinter(h);
    }
  }
}
'@
$bytes = [System.IO.File]::ReadAllBytes($dataPath)
exit ([BinosRawPrint]::Send($printer, $bytes))
`;

export interface SpoolerDeps {
  platform?: string;
  tmpdir: string;
  spawn?: typeof childProcess.spawn;
  timeoutMs?: number;
}

/** Skript chiqish kodi → natija (skript: 0 ok, 2 printer ochilmadi, 3 hujjat boshlanmadi, 4 yozilmadi). */
export function spoolerExit(code: number | null, stderr: string): PrintResult {
  const tail = stderr.replace(/\s+/g, " ").trim().slice(0, 200);
  switch (code) {
    case 0:
      return { ok: true };
    case 2:
      return { ok: false, code: "NO_PRINTER", error: "OpenPrinter: printer topilmadi" };
    case 3:
      return { ok: false, code: "REJECTED", error: "StartDocPrinter: spooler RAW hujjatni qabul qilmadi" };
    case 4:
      return { ok: false, code: "FAILED", error: "WritePrinter: baytlar to'liq yozilmadi" };
    default:
      return { ok: false, code: "FAILED", error: `powershell exit ${code}${tail ? ": " + tail : ""}` };
  }
}

export async function sendSpooler(printer: string, bytes: Uint8Array, deps: SpoolerDeps): Promise<PrintResult> {
  const platform = deps.platform ?? process.platform;
  if (platform !== "win32") return { ok: false, code: "REJECTED", error: `RAW spooler faqat Windows'da (${platform})` };
  const spawn = deps.spawn ?? childProcess.spawn;
  const timeoutMs = deps.timeoutMs ?? 60_000; // birinchi Add-Type (C# kompilyatsiyasi) sekin bo'lishi mumkin
  let dir: string | null = null;
  try {
    dir = await fs.promises.mkdtemp(path.join(deps.tmpdir, "binos-raw-"));
    const script = path.join(dir, "raw.ps1");
    const data = path.join(dir, crypto.randomBytes(8).toString("hex") + ".bin");
    // BOM bilan UTF-8: Windows PowerShell 5.1 BOM'siz faylni ANSI deb o'qiydi.
    await fs.promises.writeFile(script, String.fromCharCode(0xfeff) + SPOOLER_SCRIPT, "utf8");
    await fs.promises.writeFile(data, bytes);
    const args = ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", script, printer, data];
    return await new Promise<PrintResult>((resolve) => {
      let stderr = "";
      let done = false;
      const child = spawn("powershell.exe", args, { shell: false, windowsHide: true, stdio: ["ignore", "ignore", "pipe"] });
      const timer = setTimeout(() => {
        if (done) return;
        done = true;
        try { child.kill(); } catch { /* ignore */ }
        resolve({ ok: false, code: "TIMEOUT", error: `powershell ${timeoutMs} ms ichida tugamadi` });
      }, timeoutMs);
      child.stderr?.on("data", (c: Buffer) => {
        if (stderr.length < 4000) stderr += c.toString("utf8");
      });
      child.on("error", (e: Error) => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        resolve({ ok: false, code: "FAILED", error: `powershell ishga tushmadi: ${e.message}`.slice(0, 250) });
      });
      child.on("close", (code: number | null) => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        resolve(spoolerExit(code, stderr));
      });
    });
  } catch (e) {
    return { ok: false, code: "FAILED", error: `spooler: ${(e as Error)?.message ?? String(e)}`.slice(0, 250) };
  } finally {
    if (dir) await fs.promises.rm(dir, { recursive: true, force: true }).catch(() => undefined);
  }
}
