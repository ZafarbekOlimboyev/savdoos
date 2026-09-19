// Qurilma printeri sozlamasi (Phase 5F) — ulanish turi, printer, LAN manzil, model, kenglik, sinov cheki.
//
// ⚠️  Sozlama SHU KOMPYUTERDA (lib/printerConfig.ts) — serverga yozilmaydi, boshqa kassaga tarqalmaydi.
// ⚠️  Sinov cheki `printTestReceipt` orqali: faqat GET so'rovlar, jurnalga tushmaydi.
// Fokus halqasi: `lot-screen` — repodagi klaviatura fokusini ko'rsatuvchi sinf (styles.css).
import { useEffect, useId, useState, type CSSProperties, type ReactNode } from "react";
import { inputStyle } from "@/components/ui";
import { useT } from "@/lib/i18n";
import { printTestReceipt, type PrintResult } from "@/lib/printing";
import {
  DEFAULT_LAN_PORT, hasElectronPrint, readPrinterConfig, subscribePrinterConfig, writePrinterConfig,
  type PrinterDeviceConfig, type PrinterTransport,
} from "@/lib/printerConfig";
import { PROFILES, profileFor, type PrinterProfile } from "@/receipt";
import type { PrinterInfo } from "@/print/bridge";
// Sof tekshiruv funksiyalari (node API'siz) — main ham AYNAN shularni qo'llaydi.
import { isLanPort, isPrivateIPv4 } from "@/print/node/validate";

const TRANSPORT_ORDER: PrinterTransport[] = ["system", "escpos_lan", "escpos_spooler", "browser"];
const ELECTRON_ONLY = new Set<PrinterTransport>(["system", "escpos_lan", "escpos_spooler"]);

const labelStyle: CSSProperties = { fontSize: 12.5, color: "var(--text3)", fontWeight: 600, display: "block" };
const noteStyle: CSSProperties = { fontSize: 12, color: "var(--muted)", marginTop: 6, lineHeight: 1.4 };
const errStyle: CSSProperties = { fontSize: 12, color: "var(--red)", marginTop: 6 };

function Field({ id, label, children, hint, error }: {
  id: string; label: string; children: ReactNode; hint?: ReactNode; error?: string | null;
}) {
  return (
    <div style={{ flex: "1 1 220px", minWidth: 0 }}>
      <label htmlFor={id} style={labelStyle}>{label}</label>
      <div style={{ marginTop: 6 }}>{children}</div>
      {error ? <div id={`${id}-err`} role="alert" style={errStyle}>{error}</div> : null}
      {hint ? <div id={`${id}-hint`} style={noteStyle}>{hint}</div> : null}
    </div>
  );
}

export function PrinterSetup(props: { compact?: boolean }): JSX.Element {
  const { compact } = props;
  const t = useT();
  const uid = useId().replace(/:/g, "");
  const ids = {
    transport: `ps-${uid}-transport`, printer: `ps-${uid}-printer`, host: `ps-${uid}-host`, port: `ps-${uid}-port`,
    profile: `ps-${uid}-profile`, width: `ps-${uid}-width`, cut: `ps-${uid}-cut`, qr: `ps-${uid}-qr`,
  };
  const electron = hasElectronPrint();
  const [cfg, setCfg] = useState<PrinterDeviceConfig>(() => readPrinterConfig());
  const [printers, setPrinters] = useState<PrinterInfo[] | null>(null);
  const [host, setHost] = useState(cfg.host ?? "");
  const [port, setPort] = useState(String(cfg.port ?? DEFAULT_LAN_PORT));
  const [hostErr, setHostErr] = useState(false);
  const [portErr, setPortErr] = useState(false);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string; detail?: string } | null>(null);

  useEffect(() => subscribePrinterConfig(() => setCfg(readPrinterConfig())), []);

  useEffect(() => {
    if (!electron || !window.savdoosPrint) return;
    let alive = true;
    window.savdoosPrint.listPrinters()
      .then((ps) => { if (alive) setPrinters(Array.isArray(ps) ? ps.filter((p) => p && typeof p.name === "string") : []); })
      .catch(() => { if (alive) setPrinters([]); });
    return () => { alive = false; };
  }, [electron]);

  function update(patch: Partial<PrinterDeviceConfig>) {
    writePrinterConfig({ ...cfg, ...patch });
    setCfg(readPrinterConfig());
    setSaved(true);
    setResult(null);
  }

  function setOverride<K extends "cut" | "qr">(k: K, v: string) {
    const ov: Partial<PrinterProfile> = { ...(cfg.overrides ?? {}) };
    if (v === "") delete ov[k];
    else (ov as Record<string, unknown>)[k] = v;
    update({ overrides: ov });
  }

  function commitHost() {
    const h = host.trim();
    const ok = isPrivateIPv4(h);
    setHostErr(!ok && h !== "");
    if (ok && h !== cfg.host) update({ host: h });
  }

  function commitPort() {
    const n = Number(port.trim());
    const ok = isLanPort(n);
    setPortErr(!ok);
    if (ok && n !== cfg.port) update({ port: n });
  }

  async function testPrint() {
    setBusy(true);
    setResult(null);
    let r: PrintResult;
    try {
      r = await printTestReceipt("sale");
    } catch (e) {
      r = { ok: false, code: "FAILED", error: String((e as Error)?.message ?? e) };
    }
    setBusy(false);
    if (r.ok) {
      // Brauzer oynasi natijani aytmaydi — "yuborildi" (virtual printer/sinovda tasdiqlangan).
      const unconfirmed = !window.__BINOS_VIRTUAL_PRINTER__ && (!electron || cfg.transport === "browser");
      setResult({ ok: true, text: t(unconfirmed ? "ps.testSent" : "ps.testOk") });
    } else {
      const reason = t(`ps.err.${r.code ?? "FAILED"}`);
      setResult({ ok: false, text: t("ps.testFail", { reason }), detail: r.error });
    }
  }

  const escpos = cfg.transport === "escpos_lan" || cfg.transport === "escpos_spooler";
  const needsPrinter = cfg.transport === "system" || cfg.transport === "escpos_spooler";
  const model = profileFor(cfg.profile_id, cfg.width_mm === 58 ? 58 : 80);
  const missing = !!cfg.printer && Array.isArray(printers) && !printers.some((p) => p.name === cfg.printer);
  const gap = compact ? 10 : 14;

  return (
    <div className="lot-screen" data-testid="printer-setup" style={{ display: "flex", flexDirection: "column", gap }}>
      {!compact && (
        <div>
          <div style={{ fontSize: 15, fontWeight: 700 }}>{t("ps.title")}</div>
          <div style={noteStyle}>{t("ps.desc")}</div>
        </div>
      )}

      <div style={{ display: "flex", flexWrap: "wrap", gap }}>
        <Field id={ids.transport} label={t("ps.transport")}
          hint={!electron || cfg.transport === "browser" ? t("ps.browserNote") : undefined}>
          <select id={ids.transport} value={cfg.transport} style={inputStyle}
            aria-describedby={!electron || cfg.transport === "browser" ? `${ids.transport}-hint` : undefined}
            onChange={(e) => update({ transport: e.target.value as PrinterTransport })}>
            {TRANSPORT_ORDER.map((tr) => {
              const off = ELECTRON_ONLY.has(tr) && !electron;
              return (
                <option key={tr} value={tr} disabled={off}>
                  {t(`ps.transport.${tr}`)}{off ? ` (${t("ps.desktopOnly")})` : ""}
                </option>
              );
            })}
          </select>
        </Field>

        <Field id={ids.width} label={t("ps.width")}>
          <select id={ids.width} style={inputStyle} value={cfg.width_mm === 58 || cfg.width_mm === 80 ? String(cfg.width_mm) : ""}
            onChange={(e) => update({ width_mm: e.target.value === "58" ? 58 : e.target.value === "80" ? 80 : null })}>
            <option value="">{t("ps.widthAuto")}</option>
            <option value="58">58 mm</option>
            <option value="80">80 mm</option>
          </select>
        </Field>
      </div>

      {electron && needsPrinter && (
        <Field id={ids.printer} label={t("ps.printer")}
          error={missing ? t("ps.printerMissing", { name: cfg.printer ?? "" }) : null}
          hint={printers === null ? t("ps.printersLoading") : printers.length === 0 ? t("ps.printersNone") : undefined}>
          <select id={ids.printer} style={inputStyle} value={cfg.printer ?? ""}
            aria-invalid={missing || undefined}
            aria-describedby={missing ? `${ids.printer}-err` : undefined}
            onChange={(e) => update({ printer: e.target.value || undefined })}>
            <option value="">{cfg.transport === "system" ? t("ps.printerDefault") : t("ps.printerChoose")}</option>
            {missing && <option value={cfg.printer}>{cfg.printer}</option>}
            {(printers ?? []).map((p) => (
              <option key={p.name} value={p.name}>{p.displayName || p.name}{p.isDefault ? ` (${t("ps.isDefault")})` : ""}</option>
            ))}
          </select>
        </Field>
      )}

      {cfg.transport === "escpos_lan" && (
        <div style={{ display: "flex", flexWrap: "wrap", gap }}>
          <Field id={ids.host} label={t("ps.host")} error={hostErr ? t("ps.hostInvalid") : null}>
            <input id={ids.host} style={inputStyle} value={host} inputMode="decimal" autoComplete="off" spellCheck={false}
              placeholder="192.168.1.50" aria-invalid={hostErr || undefined}
              aria-describedby={hostErr ? `${ids.host}-err` : undefined}
              onChange={(e) => { setHost(e.target.value); setHostErr(false); }} onBlur={commitHost} />
          </Field>
          <Field id={ids.port} label={t("ps.port")} error={portErr ? t("ps.portInvalid") : null}>
            <input id={ids.port} style={inputStyle} value={port} inputMode="numeric" autoComplete="off"
              aria-invalid={portErr || undefined} aria-describedby={portErr ? `${ids.port}-err` : undefined}
              onChange={(e) => { setPort(e.target.value.replace(/\D/g, "").slice(0, 5)); setPortErr(false); }} onBlur={commitPort} />
          </Field>
        </div>
      )}

      {escpos && (
        <>
          <Field id={ids.profile} label={t("ps.profile")} hint={t("ps.profileNote")}>
            <select id={ids.profile} style={inputStyle} value={cfg.profile_id} aria-describedby={`${ids.profile}-hint`}
              onChange={(e) => update({ profile_id: e.target.value })}>
              {Object.values(PROFILES).map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
            </select>
          </Field>
          <div style={{ display: "flex", flexWrap: "wrap", gap }}>
            <Field id={ids.cut} label={t("ps.cut")}>
              <select id={ids.cut} style={inputStyle} value={cfg.overrides?.cut ?? ""} onChange={(e) => setOverride("cut", e.target.value)}>
                <option value="">{t("ps.byModel", { value: t(`ps.cut.${model.cut}`) })}</option>
                {(["none", "partial", "full"] as const).map((v) => <option key={v} value={v}>{t(`ps.cut.${v}`)}</option>)}
              </select>
            </Field>
            <Field id={ids.qr} label={t("ps.qr")}>
              <select id={ids.qr} style={inputStyle} value={cfg.overrides?.qr ?? ""} onChange={(e) => setOverride("qr", e.target.value)}>
                <option value="">{t("ps.byModel", { value: t(`ps.qr.${model.qr}`) })}</option>
                {(["native", "raster", "none"] as const).map((v) => <option key={v} value={v}>{t(`ps.qr.${v}`)}</option>)}
              </select>
            </Field>
          </div>
        </>
      )}

      <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
        <button type="button" className="btn btn-ghost" onClick={testPrint} disabled={busy} aria-busy={busy || undefined}
          style={{ fontSize: 13, padding: "8px 14px" }}>
          {busy ? t("ps.testing") : t("ps.test")}
        </button>
        <div role="status" aria-live="polite" data-testid="printer-setup-result"
          style={{ fontSize: 13, minWidth: 0, overflowWrap: "anywhere", color: result ? (result.ok ? "var(--green)" : "var(--red)") : "var(--muted)" }}>
          {result ? result.text : saved ? t("ps.saved") : ""}
          {result?.detail ? <span style={{ display: "block", fontSize: 11.5, color: "var(--muted)" }}>{result.detail}</span> : null}
        </div>
      </div>
    </div>
  );
}
