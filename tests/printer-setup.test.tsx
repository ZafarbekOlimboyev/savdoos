import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PrinterSetup } from "@/components/PrinterSetup";
import { _resetPrintRuntime } from "@/lib/printing";
import { PRINTER_CONFIG_KEY, readPrinterConfig } from "@/lib/printerConfig";
import { CACHE, cacheSet } from "@/lib/offline";
import { useAuth } from "@/store/auth";
import { BUILTIN_TEMPLATE, sampleReceipt } from "@/receipt";
import type { VirtualPrintRequest } from "@/print/bridge";
import { mockApi, renderApp } from "./util";

// Phase 5F F2: qurilma printeri sozlamasi — holatlar, saqlash (qurilmada, server kalitisiz), LAN tekshiruvi,
// sinov cheki (faqat GET) va kirish imkoniyati (label/aria-live).

const stored = () => JSON.parse(localStorage.getItem(PRINTER_CONFIG_KEY) || "null");

function electron(printers = [
  { name: "XP-80C", displayName: "XP-80C", isDefault: true },
  { name: "Microsoft Print to PDF", displayName: "Microsoft Print to PDF", isDefault: false },
]) {
  const b = {
    listPrinters: vi.fn(async () => printers),
    print: vi.fn(async () => ({ ok: true })),
    printHtml: vi.fn(async () => ({ ok: true })),
    printEscPos: vi.fn(async () => ({ ok: true })),
  };
  window.savdoosPrint = b as never;
  return b;
}

let printed: VirtualPrintRequest[] = [];

beforeEach(() => {
  _resetPrintRuntime();
  printed = [];
  useAuth.setState({
    token: "tok",
    employee: { id: "emp-1", full_name: "Ega", role_code: "ega", role_name: "Ega", status: "active", permissions: [] },
  });
});

afterEach(() => {
  delete window.savdoosPrint;
  delete window.__BINOS_VIRTUAL_PRINTER__;
  useAuth.setState({ token: null, employee: null });
});

describe("PrinterSetup — brauzer (Electron yo'q)", () => {
  it("uz: faqat brauzer rejimi tanlanadi, ilova rejimlari o'chiq va izohli", () => {
    renderApp(<PrinterSetup />);
    const sel = screen.getByLabelText("Ulanish turi") as HTMLSelectElement;
    expect(sel.value).toBe("browser");
    const opts = Array.from(sel.options);
    expect(opts.map((o) => o.value)).toEqual(["system", "escpos_lan", "escpos_spooler", "browser"]);
    for (const o of opts.slice(0, 3)) {
      expect(o.disabled).toBe(true);
      expect(o.textContent).toContain("faqat SavdoOS ilovasida");
    }
    expect(screen.getByText(/Brauzerda chek oddiy chop etish oynasi orqali chiqadi/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Printer")).toBeNull();
    expect(screen.getByText("Ushbu kompyuter printeri")).toBeInTheDocument();
  });

  it("ru tarjimasi", () => {
    renderApp(<PrinterSetup />, { lang: "ru" });
    expect(screen.getByLabelText("Способ подключения")).toBeInTheDocument();
    expect(screen.getByLabelText("Ширина бумаги")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Напечатать тестовый чек" })).toBeInTheDocument();
  });

  it("kenglik tanlovi darhol QURILMADA saqlanadi (server nom maydonisiz kalit), holat e'lon qilinadi", async () => {
    const user = userEvent.setup();
    renderApp(<PrinterSetup />);
    await user.selectOptions(screen.getByLabelText("Qog'oz kengligi"), "58");
    expect(stored()).toMatchObject({ transport: "browser", width_mm: 58, profile_id: "generic80" });
    expect(Object.keys(localStorage).filter((k) => k.startsWith(PRINTER_CONFIG_KEY))).toEqual([PRINTER_CONFIG_KEY]);
    expect(screen.getByRole("status")).toHaveTextContent("Saqlandi (shu kompyuterda)");
    await user.selectOptions(screen.getByLabelText("Qog'oz kengligi"), "");
    expect(stored().width_mm).toBeNull();
  });

  it("compact: sarlavha va izoh yashirin", () => {
    renderApp(<PrinterSetup compact />);
    expect(screen.queryByText("Ushbu kompyuter printeri")).toBeNull();
    expect(screen.getByLabelText("Ulanish turi")).toBeInTheDocument();
  });

  it("sinov cheki brauzerda: iframe'ga yuboriladi, natija 'yuborildi' (tasdiqlanmagan)", async () => {
    const calls = mockApi([[/\/receipt\/sample/, sampleReceipt("sale")], [/\/receipt\/profile/, { __status: 503, detail: "x" }]]);
    const printSpy = vi.fn();
    const orig = document.body.appendChild.bind(document.body);
    vi.spyOn(document.body, "appendChild").mockImplementation((node: any) => {
      const r = orig(node);
      if (node instanceof HTMLIFrameElement) {
        (node.contentWindow as any).print = printSpy;
        (node.contentWindow as any).focus = vi.fn();
      }
      return r;
    });
    const user = userEvent.setup();
    renderApp(<PrinterSetup />);
    await user.click(screen.getByRole("button", { name: "Sinov chekini chop etish" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Sinov cheki chop etish oynasiga yuborildi"));
    expect(printSpy).toHaveBeenCalledTimes(1);
    expect(calls.every((c) => c.method === "GET")).toBe(true);
  });
});

describe("PrinterSetup — Electron ilovasi", () => {
  it("tizim printeri: OS ro'yxati, standart belgisi; tanlov saqlanadi", async () => {
    electron();
    const user = userEvent.setup();
    renderApp(<PrinterSetup />);
    const sel = screen.getByLabelText("Ulanish turi") as HTMLSelectElement;
    expect(sel.value).toBe("system");
    expect(Array.from(sel.options).every((o) => !o.disabled)).toBe(true);
    const printer = (await screen.findByLabelText("Printer")) as HTMLSelectElement;
    await waitFor(() => expect(printer.options).toHaveLength(3));
    expect(Array.from(printer.options).map((o) => o.textContent)).toEqual([
      "Standart printer (Windows)", "XP-80C (standart)", "Microsoft Print to PDF",
    ]);
    await user.selectOptions(printer, "XP-80C");
    expect(stored()).toMatchObject({ transport: "system", printer: "XP-80C" });
    await user.selectOptions(printer, "");
    expect(stored().printer).toBeUndefined();
  });

  it("eski kompaniya sozlamasidagi printer bir marta ko'chiriladi; bu kompyuterda yo'q bo'lsa ogohlantiradi", async () => {
    electron();
    cacheSet(CACHE.settings, { receipt: { printer: "Eski-Printer" } });
    renderApp(<PrinterSetup />);
    const printer = (await screen.findByLabelText("Printer")) as HTMLSelectElement;
    expect(stored()).toMatchObject({ transport: "system", printer: "Eski-Printer" });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Tanlangan printer bu kompyuterda topilmadi: Eski-Printer");
    expect(printer).toHaveAttribute("aria-invalid", "true");
    expect(printer.value).toBe("Eski-Printer");
    // Ko'chirish bir martalik: kompaniya sozlamasi o'zgarsa ham qurilma sozlamasi o'zgarmaydi.
    cacheSet(CACHE.settings, { receipt: { printer: "Boshqa" } });
    expect(readPrinterConfig().printer).toBe("Eski-Printer");
  });

  it("LAN: faqat xususiy IPv4 va 9100–9109; noto'g'ri qiymat SAQLANMAYDI va aria-invalid", async () => {
    electron();
    const user = userEvent.setup();
    renderApp(<PrinterSetup />);
    await user.selectOptions(screen.getByLabelText("Ulanish turi"), "escpos_lan");
    expect(stored().transport).toBe("escpos_lan");
    expect(screen.queryByLabelText("Printer")).toBeNull();
    const host = screen.getByLabelText("Printer IP manzili");
    const port = screen.getByLabelText("Port") as HTMLInputElement;
    expect(port.value).toBe("9100");

    await user.type(host, "8.8.8.8");
    await user.tab();
    expect(host).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("alert")).toHaveTextContent("Faqat mahalliy tarmoq IP manzili");
    expect(stored().host).toBeUndefined();

    await user.clear(host);
    await user.type(host, "192.168.1.50");
    await user.tab();
    expect(host).not.toHaveAttribute("aria-invalid");
    expect(stored().host).toBe("192.168.1.50");

    await user.clear(port);
    await user.type(port, "80");
    await user.tab();
    expect(screen.getByRole("alert")).toHaveTextContent("Port 9100 dan 9109 gacha bo'lishi kerak");
    expect(stored().port).toBe(9100); // oldingi yaroqli qiymat (ko'rsatilgan standart) o'zgarmadi
    await user.clear(port);
    await user.type(port, "9101");
    await user.tab();
    expect(stored().port).toBe(9101);
  });

  it("ESC/POS: model, kesish va QR o'zgartirishlari (model bo'yicha = o'zgartirish yo'q)", async () => {
    electron();
    const user = userEvent.setup();
    renderApp(<PrinterSetup />);
    await user.selectOptions(screen.getByLabelText("Ulanish turi"), "escpos_spooler");
    expect(await screen.findByLabelText("Printer")).toBeInTheDocument();
    expect(screen.getByText(/haqiqiy qurilmada sinalmagan/)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Printer modeli"), "xprinter58");
    expect(stored().profile_id).toBe("xprinter58");
    const cut = screen.getByLabelText("Qog'ozni kesish") as HTMLSelectElement;
    expect(cut.options[0].textContent).toBe("Model bo'yicha (Kesgich yo'q)"); // xprinter58 preseti: kesgichsiz
    await user.selectOptions(cut, "none");
    expect(stored().overrides).toEqual({ cut: "none" });
    await user.selectOptions(screen.getByLabelText("QR kod"), "raster");
    expect(stored().overrides).toEqual({ cut: "none", qr: "raster" });
    await user.selectOptions(cut, "");
    expect(stored().overrides).toEqual({ qr: "raster" });
  });

  it("sinov cheki: virtual printer, FAQAT GET so'rovlar, natija aria-live hududida", async () => {
    electron();
    window.__BINOS_VIRTUAL_PRINTER__ = (req) => { printed.push(req); return { ok: true }; };
    const calls = mockApi([
      [/\/receipt\/sample/, sampleReceipt("sale")],
      [/\/receipt\/profile/, { etag: "e", branch_id: "b", effective: { ...BUILTIN_TEMPLATE }, store: { name: "Do'kon", branch_name: null, address: null, phone: null, stir: null }, logo: null, store_qr: null }],
    ]);
    const user = userEvent.setup();
    renderApp(<PrinterSetup />);
    await user.click(screen.getByRole("button", { name: "Sinov chekini chop etish" }));
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-live", "polite");
    await waitFor(() => expect(status).toHaveTextContent("Sinov cheki chop etildi"));
    expect(printed).toHaveLength(1);
    expect(printed[0].html).toContain("TEST PRINT");
    expect(calls.length).toBeGreaterThan(0);
    expect(calls.filter((c) => c.method !== "GET")).toEqual([]);
  });

  it("sinov cheki xatosi: tarjima qilingan sabab + texnik tafsilot", async () => {
    electron();
    window.__BINOS_VIRTUAL_PRINTER__ = () => ({ ok: false, code: "PAPER_OUT", error: "DLE EOT 4: 0x72" });
    mockApi([[/\/receipt\/sample/, sampleReceipt("sale")], [/\/receipt\/profile/, { __status: 503, detail: "x" }]]);
    const user = userEvent.setup();
    renderApp(<PrinterSetup />, { lang: "ru" });
    await user.click(screen.getByRole("button", { name: "Напечатать тестовый чек" }));
    const status = screen.getByRole("status");
    await waitFor(() => expect(status).toHaveTextContent("Не напечатано: в принтере закончилась бумага"));
    expect(within(status).getByText("DLE EOT 4: 0x72")).toBeInTheDocument();
  });

  it("kirish imkoniyati: har bir maydonning yorlig'i bor (label htmlFor), id'lar noyob", async () => {
    electron();
    const user = userEvent.setup();
    const { container } = renderApp(<><PrinterSetup /><PrinterSetup compact /></>);
    for (const sel of screen.getAllByLabelText("Ulanish turi")) await user.selectOptions(sel, "escpos_lan");
    const fields = Array.from(container.querySelectorAll("select, input")) as (HTMLSelectElement | HTMLInputElement)[];
    expect(fields.length).toBeGreaterThanOrEqual(12);
    for (const f of fields) expect(f.labels?.length, f.id).toBe(1);
    const ids = fields.map((f) => f.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(container.querySelector('[data-testid="printer-setup"]')).toHaveClass("lot-screen"); // fokus halqasi
  });
});
