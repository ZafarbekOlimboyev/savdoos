// Hujjat cheki chop etish holati (Phase 5F, F4): POS muvaffaqiyat ekrani, Sotuvlarim, Qaytarishlar,
// Manager Sotuvlar/Qaytarishlar nazorati — hammasi shu bitta hook + qatordan foydalanadi.
//
// ⚠️  CHOP ETISH — SOTUVDAN KEYINGI YON TA'SIR. `usePrintDoc().print` hech qachon xato otmaydi va
//     sotuv/qaytarish holatiga, savatga tegmaydi: printer xatosi faqat shu qatorda "Xato: …" bo'lib
//     ko'rinadi. Chaqiruvchi uni `await` qilmasa ham bo'ladi ("Yangi savdo" hech narsani kutmaydi).
// ⚠️  Holat MAHALLIY jurnaldan (`lib/printing.ts`, `usePrintJobs`) — boshqa ekranga o'tib qaytilsa ham
//     o'sha hujjatning oxirgi chop etilishi ko'rinadi (oflayn sotuv client_uuid kaliti bilan ham).
import { createContext, useCallback, useContext, useEffect, useRef, useState, type CSSProperties } from "react";
import { Link, useInRouterContext } from "react-router-dom";
import { useT } from "@/lib/i18n";
import {
  cachedReceiptProfile, docKey, getReceiptProfile, printDoc, retryJob, usePrintJobs, PRINT_ERROR_CODES,
  type LocalPrintJob, type PrintDocType, type PrintErrorCode,
} from "@/lib/printing";
import { useAuth } from "@/store/auth";
import type { ReceiptDTO } from "@/receipt";

export interface PrintTarget {
  doc_type: PrintDocType;
  /** Server hujjat id'si (onlayn sotuv, qaytarish). */
  doc_id?: string | null;
  /** Oflayn sotuv kaliti — server id'si hali yo'q. */
  client_uuid?: string | null;
  /**
   * Oflayn VAQTINCHALIK DTO quruvchisi — faqat chop etish paytida chaqiriladi (sotuv yo'lida emas).
   * Onlayn hujjat uchun BERILMAYDI: aks holda server DTO olinmasa haqiqiy raqamli sotuv "OFLAYN"
   * banneri bilan chiqib ketardi.
   */
  dto?: () => ReceiptDTO | null;
  /**
   * ESKI server (5F'dan oldingi, chek marshruti YO'Q) uchun zaxira DTO quruvchisi — onlayn sotuvning
   * o'z mahalliy surati. printing.ts uni FAQAT marshrut yo'qligi aniq bo'lganda ishlatadi; marshrut
   * bor server (masalan "Chek topilmadi"/403) baribir xato beradi — chek doim server yozuvidan.
   */
  fallback?: () => ReceiptDTO | null;
}

/**
 * Chop etish xatosida "Printer sozlamasi" qayerga olib boradi. Manager standarti — Sozlamalar havolasi
 * («Chek va printer» bo'limi, `sozlamalar.view` ruxsati bilan). `open` berilsa — havola EMAS, tugma: sozlama
 * joyida (oynada) ochiladi. POS shunday qiladi (apps/pos/src/App.tsx): muvaffaqiyat/qaytarish ekrani chekning
 * yagona "Qayta urinish" joyi — boshqa sahifaga o'tilsa o'sha chek POS'da qayta chop etib bo'lmasdi.
 * `null` — ko'rsatilmaydi.
 */
export interface PrinterSetupLink { to?: string; perm: string | null; open?: () => void }
export const PrinterSetupLinkContext = createContext<PrinterSetupLink | null>({ to: "/sozlamalar?tab=receipt", perm: "sozlamalar.view" });
// Shu kodlarda sabab — printer/ulanish sozlamasi (chek ma'lumoti yoki tarmoq emas).
const SETUP_CODES = new Set<string>(["NO_PRINTER", "OFFLINE", "REJECTED", "TIMEOUT", "PAPER_OUT"]);

// Quruvchi otsa (noto'g'ri son) — chek chiqmaydi, lekin UI yiqilmaydi.
function build(fn?: () => ReceiptDTO | null): ReceiptDTO | undefined {
  if (!fn) return undefined;
  try {
    return fn() ?? undefined;
  } catch {
    return undefined;
  }
}

export interface PrintState {
  jobs: LocalPrintJob[];
  last: LocalPrintJob | null;
  busy: boolean;
  /** Hujjat bir marta chop etilgan — keyingi bosish NUSXA (tugma yozuvi shunga qarab). */
  printedOnce: boolean;
  /**
   * `target` — ixtiyoriy aniq maqsad (masalan avto-chop etish effekti o'z sotuvini yopib oladi:
   * kassir shu orada "Yangi savdo" bossa ham AYNAN o'sha chek chiqadi). Berilmasa — joriy maqsad.
   */
  print: (mode: "auto" | "manual", target?: PrintTarget | null) => Promise<LocalPrintJob | null>;
  retry: (job: LocalPrintJob) => Promise<LocalPrintJob | null>;
}

// Hech bir yozuvga mos kelmaydigan kalit (doc_type faqat SALE/RETURN) — `usePrintJobs("")` HAMMA
// yozuvni qaytarardi, shu bois bo'sh kalit ishlatilmaydi.
const NO_KEY = "NONE:-";
// Shundan eski PENDING — ilova yopilgan/uzilgan urinish (yangi urinish bunchalik cho'zilmaydi).
const STALE_PENDING_MS = 90_000;

function keyOf(target: PrintTarget | null): string {
  const id = target ? target.doc_id || target.client_uuid || null : null;
  return target && id ? docKey(target.doc_type, id) : NO_KEY;
}

export function usePrintDoc(target: PrintTarget | null): PrintState {
  const key = keyOf(target);
  const jobs = usePrintJobs(key);
  // "Band" holati HUJJAT bo'yicha: A chek chop etilayotganda B tanlansa, B "Chop etilmoqda" ko'rinmasin.
  const [busyMap, setBusyMap] = useState<Record<string, number>>({});
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const bump = useCallback((k: string, d: number) => {
    if (!alive.current) return;
    setBusyMap((m) => {
      const n = (m[k] ?? 0) + d;
      const next = { ...m };
      if (n > 0) next[k] = n;
      else delete next[k];
      return next;
    });
  }, []);
  // Eng so'nggi maqsad — tugma bosilganda (masalan boshqa chek tanlangach) eski closure ishlamasin.
  const targetRef = useRef(target);
  targetRef.current = target;

  const print = useCallback(async (mode: "auto" | "manual", explicit?: PrintTarget | null): Promise<LocalPrintJob | null> => {
    const tg = explicit ?? targetRef.current;
    if (!tg || !(tg.doc_id || tg.client_uuid)) return null;
    const k = keyOf(tg);
    bump(k, 1);
    try {
      return await printDoc({
        doc_type: tg.doc_type, doc_id: tg.doc_id ?? null, client_uuid: tg.client_uuid ?? null, mode,
        dto: build(tg.dto), fallbackDto: build(tg.fallback),
      });
    } catch {
      return null; // argument xatosi — hech narsa chop etilmaydi, sotuv holatiga ta'sir yo'q
    } finally {
      bump(k, -1);
    }
  }, [bump]);

  const retry = useCallback(async (job: LocalPrintJob): Promise<LocalPrintJob | null> => {
    // ASL chek — `printDoc(manual)` AYNAN o'sha yozuvni qayta uradi (oflayn DTO ham qayta beriladi).
    if (job.copy === "ORIGINAL") return print("manual");
    const k = job.key;
    bump(k, 1);
    try {
      return await retryJob(job.id);
    } catch {
      return null;
    } finally {
      bump(k, -1);
    }
  }, [print, bump]);

  const last = jobs.length ? jobs[jobs.length - 1] : null;
  const printedOnce = jobs.some((j) => j.status === "PRINTED");
  // Nusxani qayta urinish yozuvi kaliti server id'si bo'lishi mumkin (oflayn → bog'langan) — shu bois
  // band holati joriy kalit YOKI oxirgi yozuv kaliti bo'yicha.
  const busy = (busyMap[key] ?? 0) > 0 || (!!last && (busyMap[last.key] ?? 0) > 0);
  return { jobs, last, busy, printedOnce, print, retry };
}

/**
 * Shablon `auto_print` yoqilgan bo'lsa hujjatni BIR MARTA avto-chop etadi (hujjat kaliti bo'yicha).
 * StrictMode ikki marta mount qilsa ham ref qo'riqlaydi; `printDoc(auto)` o'zi ham idempotent (asl chek
 * yozuvi bor bo'lsa qayta chiqmaydi). Maqsad yopib olinadi: foydalanuvchi shu orada boshqa ekranga
 * o'tsa ("Yangi savdo") ham AYNAN shu hujjat cheki chiqadi. Profil keshda bo'lsa — kutilmaydi.
 */
export function useAutoPrint(state: PrintState, target: PrintTarget | null): void {
  const k = keyOf(target);
  const handled = useRef<string | null>(null);
  const latest = useRef({ state, target });
  latest.current = { state, target };
  useEffect(() => {
    const { state: st, target: tg } = latest.current;
    if (!tg || k === NO_KEY || handled.current === k) return;
    handled.current = k;
    const go = (p: { effective?: { auto_print?: boolean } } | null) => {
      if (p?.effective?.auto_print === true) void st.print("auto", tg);
    };
    const cached = cachedReceiptProfile();
    if (cached) go(cached);
    else void getReceiptProfile().then(go, () => undefined);
  }, [k]);
}

type T = (key: string, vars?: Record<string, string | number>) => string;

const NET_RE = /failed to fetch|networkerror|network error|load failed|abort|timed? ?out/i;
// printing.ts ning ichki (tarjimasiz) matnlari — chek DTO'si olinmadi/yo'q.
const NO_DATA = new Set(["chek ma'lumoti yo'q", "chek olinmadi", "chek ma'lumoti noto'g'ri shaklda"]);

/**
 * Xato sababi — DOIM tarjima qilingan matn. Xom qurilma matni (Electron "Print job failed", ichki
 * lotincha "noto'g'ri javob") ru/uzc/ky ekranida chiqmasin: noma'lumi umumiy `ps.err.FAILED`,
 * texnik tafsilot faqat `printErrorDetail` → title (qo'llab-quvvatlash uchun).
 */
export function printErrorReason(t: T, job: Pick<LocalPrintJob, "code" | "error">): string {
  const code = job.code;
  if (code === "NO_DATA") return t("pr.errNoData");
  if (code && code !== "FAILED" && PRINT_ERROR_CODES.includes(code as PrintErrorCode)) return t(`ps.err.${code}`);
  const e = (job.error ?? "").trim();
  if (NO_DATA.has(e)) return t("pr.errNoData");
  if (e && NET_RE.test(e)) return t("pr.errNetwork");
  return t("ps.err.FAILED");
}

/** Xom texnik tafsilot (tarjimasiz) — faqat tooltip uchun; kodning o'zi yoki bo'sh bo'lsa null. */
export function printErrorDetail(job: Pick<LocalPrintJob, "code" | "error">): string | null {
  const e = (job.error ?? "").trim();
  return e && e !== job.code ? e.slice(0, 300) : null;
}

type Tone = "muted" | "ok" | "danger" | "warn";
const TONE: Record<Tone, string> = { muted: "var(--muted)", ok: "var(--ok)", danger: "var(--danger)", warn: "var(--warn)" };

interface Line { text: string; tone: Tone; retry: LocalPrintJob | null; detail?: string | null; setup?: boolean }

function statusLine(t: T, state: PrintState): Line | null {
  const { last, busy } = state;
  if (busy) return { text: t("pr.printing"), tone: "muted", retry: null };
  if (!last) return null;
  if (last.status === "PENDING") {
    const age = Date.now() - Date.parse(last.updated_at);
    if (Number.isFinite(age) && age > STALE_PENDING_MS) return { text: t("pr.stale"), tone: "warn", retry: last };
    return { text: t("pr.printing"), tone: "muted", retry: null };
  }
  if (last.status === "FAILED") {
    return {
      text: t("pr.failed", { reason: printErrorReason(t, last) }), tone: "danger", retry: last,
      detail: printErrorDetail(last), setup: !!last.code && SETUP_CODES.has(last.code),
    };
  }
  let text: string;
  if (last.transport === "browser") text = t("pr.sent"); // brauzer dialogi natijani aytmaydi
  else if (last.copy === "REPRINT") {
    text = typeof last.copy_no === "number" && last.copy_no > 0 ? t("pr.printedCopy", { n: last.copy_no }) : t("pr.printedCopyPlain");
  } else text = t("pr.printed");
  const notes: string[] = [];
  if (last.provisional) notes.push(t("pr.provisional"));
  if (last.code === "PRINT_ORIGINAL_EXISTS") notes.push(t("pr.originalElsewhere"));
  if (notes.length) text += ` · ${notes.join(" · ")}`;
  return { text, tone: last.transport === "browser" ? "muted" : "ok", retry: null };
}

/**
 * Kichik holat qatori (aria-live). Bo'sh holatda ham live-region DOM'da turadi — ekran o'quvchi
 * keyingi o'zgarishni ("Chop etildi" / "Xato") e'lon qilishi uchun; bo'sh bo'lsa joy egallamaydi.
 */
export function PrintStatus({ state, style, testId = "print-status" }: {
  state: PrintState;
  style?: CSSProperties;
  testId?: string;
}): JSX.Element {
  const t = useT();
  const d = statusLine(t, state);
  const setupLink = useContext(PrinterSetupLinkContext);
  const perms = useAuth((s) => s.employee?.permissions);
  const inRouter = useInRouterContext();
  // Printer sababli xato — to'g'rilash joyi (Manager'da faqat Sozlamalar ruxsati bo'lsa): oyna yoki havola.
  const setup = !!d?.setup && !!setupLink && (!setupLink.perm || (perms ?? []).includes(setupLink.perm));
  const setupOpen = setup && setupLink?.open ? setupLink.open : null;
  const setupTo = setup && !setupOpen && inRouter && setupLink?.to ? setupLink.to : null;
  return (
    <div role="status" aria-live="polite" aria-label={t("pr.statusLabel")} data-testid={testId}
      data-status={d ? (state.busy ? "PENDING" : state.last?.status) : undefined}
      style={d ? { fontSize: 12.5, fontWeight: 600, lineHeight: 1.4, color: TONE[d.tone], ...style } : undefined}>
      {d && (
        <>
          <span title={d.detail ?? undefined}>{d.text}</span>
          {d.retry && (
            <button type="button" data-testid={`${testId}-retry`}
              onClick={() => { if (d.retry) void state.retry(d.retry); }}
              style={LINK}>
              {t("pr.retry")}
            </button>
          )}
          {setupOpen && (
            <button type="button" aria-haspopup="dialog" data-testid={`${testId}-setup`} onClick={() => setupOpen()} style={LINK}>
              {t("pr.setup")}
            </button>
          )}
          {setupTo && <Link to={setupTo} data-testid={`${testId}-setup`} style={LINK}>{t("pr.setup")}</Link>}
        </>
      )}
    </div>
  );
}

const LINK: CSSProperties = {
  marginLeft: 8, padding: 0, border: "none", background: "none", cursor: "pointer", font: "inherit", fontWeight: 700,
  color: "var(--accent-strong)", textDecoration: "underline",
};
