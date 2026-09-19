import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as fs from "fs";
import * as path from "path";
import { ReceiptSettings } from "@/screens/ReceiptSettings";
import { Settings } from "@/screens/Settings";
import { RECEIPT_UI } from "@/lib/i18nReceipt";
import { _resetPrintRuntime } from "@/lib/printing";
import { useAuth } from "@/store/auth";
import { BUILTIN_TEMPLATE, sampleReceipt, type SampleKind } from "@/receipt";
import type { VirtualPrintRequest } from "@/print/bridge";
import { mockApi, renderApp, type Call } from "./util";

// `printTestReceipt` o'zi ishlaydi (virtual printer sinovi), faqat ekran uzatgan argumentlar yozib olinadi.
const testPrintArgs = vi.hoisted(() => [] as unknown[][]);
vi.mock("@/lib/printing", async (importOriginal) => {
  const orig = await importOriginal<typeof import("@/lib/printing")>();
  return {
    ...orig,
    printTestReceipt: (...a: Parameters<typeof orig.printTestReceipt>) => {
      testPrintArgs.push(a);
      return orig.printTestReceipt(...a);
    },
  };
});

const ZWSP = String.fromCharCode(0x200b);

// Phase 5F F3: Manager «Chek» sozlamalari — doira (kompaniya/filial), meros va «standartga qaytarish»,
// avto-saqlash tanasi, faqat-ko'rish rejimi, logo tekshiruvi, jonli oldindan ko'rish (XSS qochirilgan),
// sinov chop etish (faqat GET) va kirish imkoniyati (label/switch/aria-live).
//
// ⚠️  Server QOIDALARI bu yerda emas (backend `test_receipt_settings.py`): soxta server faqat
//     merosni (filial → kompaniya → standart) va null = o'chirish semantikasini takrorlaydi —
//     tekshiriladigan narsa UI NIMA yuborayotgani va javobni QANDAY ko'rsatayotgani.

type Row = Record<string, unknown>;
const BUILTIN_ALL: Row = { ...BUILTIN_TEMPLATE, printer: null, logo_id: null, qr_url: null };
const BRANCHES = [{ id: "b1", name: "Asosiy" }, { id: "b2", name: "Chilonzor" }];
const STORE_INFO = { name: "Oltin Do'kon", address: "Toshkent, Navoiy 1", phone: "+998 71 200 00 00", stir: "305123456" };
const TINY_PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAAAAADhZOFXAAAADklEQVR4nGNgYGBgYGAAAAAHAAHU1Z1ZAAAAAElFTkSuQmCC";

interface Srv {
  company: Row;
  branches: Record<string, Row>;
  logos: Record<string, { id: string; branch_id: string | null }>;
  scope: { company_editable: boolean; branch_editable: boolean };
  failPut?: { __status: number; detail: string } | null;
  /** Filialga cheklangan xodim: haqiqiy server kabi `scope=company` namunasi — 403. */
  restricted?: boolean;
}

function merge(row: Row, patch: Row): Row {
  const out = { ...row };
  for (const [k, v] of Object.entries(patch)) {
    if (v === null) delete out[k];
    else out[k] = v;
  }
  return out;
}

function layer(base: Row, row: Row | undefined): Row {
  const out = { ...base };
  for (const [k, v] of Object.entries(row ?? {})) if (v !== null && v !== undefined) out[k] = v;
  return out;
}

function logoOut(id: string, branch_id: string | null) {
  const v = (w: number) => ({ width: w, height: 16, png_data_uri: TINY_PNG, raster_b64: btoa("\0".repeat((w / 8) * 16)) });
  return { id, sha256: "ab".repeat(32), mime: "image/png", width: 64, height: 16, byte_size: 99, branch_id, variants: { "58": v(64), "80": v(96) } };
}

/** Kichik soxta server: meros, null = maydonni o'chirish, filial nomi va logo havolasi. */
function fakeServer(over: Partial<Srv> = {}) {
  const srv: Srv = {
    company: {}, branches: {}, logos: {},
    scope: { company_editable: true, branch_editable: true }, failPut: null, ...over,
  };
  const viewOf = (bid: string | null) => {
    const eff = layer(layer(BUILTIN_ALL, srv.company), bid ? srv.branches[bid] : undefined);
    const branch = bid ? BRANCHES.find((b) => b.id === bid)! : null;
    const logoId = typeof eff.logo_id === "string" ? eff.logo_id : null;
    const logo = logoId && srv.logos[logoId] ? logoOut(logoId, srv.logos[logoId].branch_id) : null;
    return {
      scope: { branch_id: bid, company_editable: srv.scope.company_editable, branch_editable: bid !== null && srv.scope.branch_editable },
      branches: BRANCHES,
      company: { ...srv.company },
      branch: bid ? (srv.branches[bid] ? { ...srv.branches[bid] } : null) : null,
      effective: eff,
      store: {
        name: (eff.store_display_name as string) || STORE_INFO.name,
        branch_name: branch?.name ?? null,
        address: (eff.address as string) || STORE_INFO.address,
        phone: (eff.phone as string) || STORE_INFO.phone,
        stir: STORE_INFO.stir,
      },
      logo,
    };
  };
  const url = (c: Call) => new URL(c.url, "http://x");
  const routes: [RegExp, any][] = [
    [/\/receipt\/settings/, (c: Call) => {
      if (c.method === "PUT") {
        if (srv.failPut) return srv.failPut;
        const bid = c.body.branch_id ?? null;
        if (bid) srv.branches[bid] = merge(srv.branches[bid] ?? {}, c.body.value);
        else srv.company = merge(srv.company, c.body.value);
        return viewOf(bid);
      }
      return viewOf(url(c).searchParams.get("branch_id"));
    }],
    [/\/receipt\/logos/, (c: Call) => {
      if (c.method === "GET") {
        const lid = url(c).pathname.split("/").pop() ?? "";
        return srv.logos[lid] ? logoOut(lid, srv.logos[lid].branch_id) : { __status: 404, detail: "Logo topilmadi" };
      }
      const id = "11111111-2222-5333-8444-555555555555";
      srv.logos[id] = { id, branch_id: c.body.branch_id ?? null };
      return logoOut(id, c.body.branch_id ?? null);
    }],
    [/\/receipt\/sample/, (c: Call) => {
      const u = url(c);
      if (u.searchParams.get("scope") === "company" && srv.restricted) {
        return { __status: 403, detail: "Ruxsat yo'q: kompaniya chek shablonini faqat barcha filiallarga kirish huquqi bor xodim o'zgartiradi" };
      }
      // Haqiqiy server kabi: scope=company — faqat kompaniya qatori; branch_id'siz — xodim filiali (b1)
      // ustamasi bilan. Qaysi qatlamdan qurilgani birinchi mahsulot nomida ko'rinadi.
      const bid = u.searchParams.get("scope") === "company" ? null : (u.searchParams.get("branch_id") ?? "b1");
      const eff = layer(layer(BUILTIN_ALL, srv.company), bid ? srv.branches[bid] : undefined);
      const dto = sampleReceipt((u.searchParams.get("kind") || "sale") as SampleKind, { ...STORE_INFO, branch_name: "Asosiy" }, eff as any);
      dto.lines[0] = { ...dto.lines[0], name: `SAMPLE:${bid ?? "company"}` };
      if (eff.qr_mode === "store_url" && typeof eff.qr_url === "string") {
        dto.qr = { kind: "store_url", payload: eff.qr_url, size: 21, matrix: Array(21).fill("10".repeat(10) + "1") };
      }
      return dto;
    }],
    [/\/receipt\/profile/, { __status: 503, detail: "x" }],
  ];
  const calls = mockApi(routes);
  return { srv, calls };
}

const writes = (calls: Call[]) => calls.filter((c) => c.method !== "GET");
const puts = (calls: Call[]) => calls.filter((c) => c.method === "PUT" && c.url.includes("/receipt/settings"));

function login(role = "ega", permissions = ["sozlamalar.view", "sozlamalar.edit"]) {
  useAuth.setState({
    token: "tok",
    employee: { id: "emp-1", full_name: "Test", role_code: role, role_name: role, status: "active", permissions, company_code: "c1" },
  });
}

async function frame() {
  const f = (await screen.findByTestId("rs-preview-frame")) as HTMLIFrameElement;
  return f;
}
const srcdoc = () => (screen.getByTestId("rs-preview-frame") as HTMLIFrameElement).getAttribute("srcdoc") || "";

beforeEach(() => {
  _resetPrintRuntime();
  testPrintArgs.length = 0;
  login();
});

afterEach(() => {
  delete window.__BINOS_VIRTUAL_PRINTER__;
  useAuth.setState({ token: null, employee: null });
});

describe("ReceiptSettings — ko'rinish va kirish imkoniyati", () => {
  it("ru: bo'limlar, switch roli/holati, iframe sarlavhasi va sandbox", async () => {
    fakeServer({ company: { show_till: true } });
    renderApp(<ReceiptSettings />, { lang: "ru" });
    expect(await screen.findByRole("heading", { name: "Логотип" })).toBeInTheDocument();
    for (const h of ["Данные магазина на чеке", "Что печатать на чеке", "Ширина бумаги", "Конец чека и печать", "Принтер этого компьютера", "Предпросмотр"]) {
      expect(screen.getByRole("heading", { name: h })).toBeInTheDocument();
    }
    const till = screen.getByRole("switch", { name: "Номер кассы" });
    expect(till).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("switch", { name: "Имя покупателя" })).toHaveAttribute("aria-checked", "false");
    expect(screen.getByRole("switch", { name: "Имя кассира" })).toHaveAttribute("aria-checked", "true");
    const f = await frame();
    expect(f).toHaveAttribute("title", "Образец чека, 80 мм");
    expect(f.getAttribute("sandbox")).toBe("");
    expect(screen.getByLabelText("Для каких чеков")).toHaveValue("");
    // Qurilma printeri — ichma-ich (o'z sarlavhasisiz), sinov tugmasi nomlari ajralib turadi.
    expect(screen.getByTestId("printer-setup")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Напечатать этот образец" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Напечатать тестовый чек" })).toBeInTheDocument();
  });

  it("uz: tarjima va do'kon maydonlarida meros qiymat (placeholder)", async () => {
    fakeServer();
    renderApp(<ReceiptSettings />, { lang: "uz" });
    const name = (await screen.findByLabelText("Chekdagi do‘kon nomi")) as HTMLInputElement;
    expect(name.value).toBe("");
    expect(name.placeholder).toBe("Oltin Do'kon");
    expect((screen.getByLabelText("Manzil") as HTMLInputElement).placeholder).toBe("Toshkent, Navoiy 1");
    expect((screen.getByLabelText("Pastki matn") as HTMLTextAreaElement).placeholder).toBe("Xaridingiz uchun rahmat!");
    expect(screen.getByRole("switch", { name: "Qator chegirmalari" })).toHaveAttribute("aria-checked", "true");
  });

  it("har input/select/textarea'ning bog'langan label'i bor; status qatorlari aria-live", async () => {
    fakeServer({ company: { qr_mode: "store_url", qr_url: "https://oltin.uz" } });
    const { container } = renderApp(<ReceiptSettings />, { lang: "ru" });
    await frame();
    const fields = Array.from(container.querySelectorAll("input, select, textarea")) as HTMLInputElement[];
    expect(fields.length).toBeGreaterThan(10);
    for (const el of fields) {
      const labelled = (el.labels && el.labels.length > 0) || el.getAttribute("aria-label") || el.getAttribute("aria-labelledby");
      expect(labelled, `label yo'q: ${el.outerHTML.slice(0, 120)}`).toBeTruthy();
    }
    for (const sw of screen.getAllByRole("switch")) {
      expect(sw).toHaveAttribute("aria-checked");
      expect(sw).toHaveAccessibleName();
    }
    for (const id of ["rs-status", "rs-logo-status", "rs-test-result"]) {
      expect(screen.getByTestId(id)).toHaveAttribute("aria-live", "polite");
    }
    expect(screen.getByLabelText("Ссылка для QR")).toHaveValue("https://oltin.uz");
  });
});

describe("ReceiptSettings — avto-saqlash tanasi va doira", () => {
  it("kompaniya doirasi: switch darhol PUT {branch_id: null, value: {show_till: true}}", async () => {
    const { calls } = fakeServer();
    const user = userEvent.setup();
    renderApp(<ReceiptSettings />, { lang: "ru" });
    const till = await screen.findByRole("switch", { name: "Номер кассы" });
    await user.click(till);
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toEqual({ branch_id: null, value: { show_till: true } });
    await waitFor(() => expect(till).toHaveAttribute("aria-checked", "true"));
    // Label bosilganda ham almashadi (katta bosish maydoni).
    await user.click(screen.getByText("Скидки по строкам"));
    await waitFor(() => expect(puts(calls)).toHaveLength(2));
    expect(puts(calls)[1].body).toEqual({ branch_id: null, value: { show_discount: false } });
  });

  it("filial doirasi: ?branch_id so'raladi, meros belgisi, o'zgartirish filialga, «Вернуть стандарт» → null", async () => {
    const { srv, calls } = fakeServer({ company: { show_till: true, footer: "Kompaniya rahmati" } });
    const user = userEvent.setup();
    renderApp(<ReceiptSettings />, { lang: "ru" });
    await screen.findByRole("switch", { name: "Номер кассы" });
    await user.selectOptions(screen.getByLabelText("Для каких чеков"), "b2");
    await waitFor(() => expect(calls.some((c) => c.method === "GET" && c.url.includes("/receipt/settings?branch_id=b2"))).toBe(true));
    const till = await screen.findByRole("switch", { name: "Номер кассы" });
    expect(till).toHaveAttribute("aria-checked", "true"); // kompaniyadan meros
    expect(screen.getByTestId("rs-inherited-show_till")).toHaveTextContent("Из компании");
    expect((screen.getByLabelText("Нижний текст") as HTMLTextAreaElement).placeholder).toBe("Kompaniya rahmati");

    await user.click(till);
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toEqual({ branch_id: "b2", value: { show_till: false } });
    expect(srv.branches.b2).toEqual({ show_till: false });
    expect(srv.company.show_till).toBe(true); // kompaniya qatoriga tegilmagan
    const reset = await screen.findByRole("button", { name: "Номер кассы: вернуть стандарт" });
    await user.click(reset);
    await waitFor(() => expect(puts(calls)).toHaveLength(2));
    expect(puts(calls)[1].body).toEqual({ branch_id: "b2", value: { show_till: null } });
    await waitFor(() => expect(screen.getByTestId("rs-inherited-show_till")).toBeInTheDocument());
    expect(screen.getByRole("switch", { name: "Номер кассы" })).toHaveAttribute("aria-checked", "true");
  });

  it("matn faqat maydondan chiqqanda saqlanadi; bo'sh matn — null (meros)", async () => {
    const { calls } = fakeServer({ company: { header: "Eski shior" } });
    const user = userEvent.setup();
    renderApp(<ReceiptSettings />, { lang: "ru" });
    const header = (await screen.findByLabelText("Верхний текст (слоган)")) as HTMLTextAreaElement;
    expect(header.value).toBe("Eski shior");
    await user.clear(header);
    await user.type(header, "Yangi shior");
    expect(puts(calls)).toHaveLength(0);
    await user.tab();
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toEqual({ branch_id: null, value: { header: "Yangi shior" } });
    // O'zgarmagan qiymatda qayta blur — so'rov yo'q.
    await user.click(header);
    await user.tab();
    expect(puts(calls)).toHaveLength(1);
    await user.clear(header);
    await user.tab();
    await waitFor(() => expect(puts(calls)).toHaveLength(2));
    expect(puts(calls)[1].body).toEqual({ branch_id: null, value: { header: null } });
  });

  it("filialga biriktirilgan admin: kompaniya doirasi yopiq — o'z filiali avtomatik ochiladi", async () => {
    login("administrator", ["sozlamalar.view", "sozlamalar.edit"]);
    const { calls } = fakeServer({ scope: { company_editable: false, branch_editable: true } });
    const user = userEvent.setup();
    renderApp(<ReceiptSettings />, { lang: "ru" });
    await waitFor(() => expect(screen.getByLabelText("Для каких чеков")).toHaveValue("b1"));
    const till = await screen.findByRole("switch", { name: "Номер кассы" });
    expect(till).toBeEnabled();
    await user.click(till);
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body.branch_id).toBe("b1");
    // Kompaniya doirasiga qaytsa — faqat ko'rish va sababi aytiladi.
    await user.selectOptions(screen.getByLabelText("Для каких чеков"), "");
    expect(await screen.findByTestId("rs-readonly")).toHaveTextContent("Стандарт компании может менять только сотрудник с доступом ко всем филиалам");
    expect(screen.getByRole("switch", { name: "Номер кассы" })).toBeDisabled();
  });

  it("menejer (sozlamalar.edit yo'q): hamma maydon yopiq, izoh bor, hech qanday yozish yo'q", async () => {
    login("menejer", ["sozlamalar.view"]);
    const { calls } = fakeServer({ scope: { company_editable: false, branch_editable: false } });
    const user = userEvent.setup();
    renderApp(<ReceiptSettings />, { lang: "ru" });
    expect(await screen.findByTestId("rs-readonly")).toHaveTextContent("У вас нет права изменять настройки чека");
    expect(screen.getByLabelText("Для каких чеков")).toHaveValue(""); // avtomatik filialga o'tmaydi
    for (const sw of screen.getAllByRole("switch")) expect(sw).toBeDisabled();
    expect(screen.getByLabelText("Нижний текст")).toBeDisabled();
    expect(screen.getByLabelText("Название магазина на чеке")).toBeDisabled();
    expect(screen.getByLabelText("Количество копий")).toBeDisabled();
    expect(screen.getByTestId("rs-width-58")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Загрузить логотип" })).toBeDisabled();
    await user.click(screen.getByRole("switch", { name: "Номер кассы" }));
    await user.click(screen.getByTestId("rs-width-58"));
    // Ko'rish vositalari (namuna turi) ishlaydi — ular hech narsa yozmaydi.
    await user.click(screen.getByTestId("rs-sample-return"));
    await waitFor(() => expect(srcdoc()).toContain("ВОЗВРАТ"));
    expect(writes(calls)).toHaveLength(0);
  });

  it("tez ketma-ket ikki almashtirgich: PUT'lar NAVBATDA (bir vaqtda bittadan), tartib saqlanadi", async () => {
    const { srv, calls } = fakeServer();
    const inner = globalThis.fetch;
    const gates: (() => void)[] = [];
    let open = 0;
    let maxOpen = 0;
    vi.stubGlobal("fetch", vi.fn(async (u: string, o: RequestInit = {}) => {
      if ((o.method || "GET").toUpperCase() !== "PUT") return inner(u, o);
      open += 1;
      maxOpen = Math.max(maxOpen, open);
      await new Promise<void>((r) => gates.push(r));
      try { return await inner(u, o); } finally { open -= 1; }
    }));
    const user = userEvent.setup();
    renderApp(<ReceiptSettings />, { lang: "ru" });
    const till = await screen.findByRole("switch", { name: "Номер кассы" });
    const disc = screen.getByRole("switch", { name: "Скидки по строкам" });
    await user.click(till);
    await user.click(disc);
    // Optimistik: ikkalasi darhol ko'rinadi, lekin serverga hozircha bitta so'rov.
    expect(till).toHaveAttribute("aria-checked", "true");
    expect(disc).toHaveAttribute("aria-checked", "false");
    await waitFor(() => expect(gates).toHaveLength(1));
    gates[0]();
    await waitFor(() => expect(gates).toHaveLength(2));
    // Birinchi javob (faqat show_till) ikkinchi optimistik qiymatni bosib ketmaydi.
    expect(disc).toHaveAttribute("aria-checked", "false");
    gates[1]();
    await waitFor(() => expect(puts(calls)).toHaveLength(2));
    expect(puts(calls).map((c) => c.body.value)).toEqual([{ show_till: true }, { show_discount: false }]);
    expect(maxOpen).toBe(1);
    expect(srv.company).toEqual({ show_till: true, show_discount: false });
    await waitFor(() => expect(disc).toHaveAttribute("aria-checked", "false"));
    expect(till).toHaveAttribute("aria-checked", "true");
  });

  it("saqlash xatosi: tarjima qilingan sabab aria-live'da, qiymat server holatiga qaytadi, Topbar «не сохранено»", async () => {
    // Settings orqali: Topbar holati ham tekshiriladi.
    const { srv, calls } = fakeServerWithSettings();
    srv.failPut = { __status: 403, detail: "Ruxsat yo'q: kompaniya chek shablonini faqat barcha filiallarga kirish huquqi bor xodim o'zgartiradi" };
    const user = userEvent.setup();
    renderApp(<Settings />, { lang: "ru" });
    await user.click(await screen.findByRole("button", { name: "Чек и принтер" }));
    const till = await screen.findByRole("switch", { name: "Номер кассы" });
    const getsBefore = calls.filter((c) => c.method === "GET" && c.url.includes("/receipt/settings")).length;
    await user.click(till);
    await waitFor(() => expect(screen.getByTestId("rs-status")).toHaveTextContent(
      "Не сохранено: Нет доступа: шаблон чека компании может менять только сотрудник с доступом ко всем филиалам"));
    await waitFor(() => expect(till).toHaveAttribute("aria-checked", "false"));
    await waitFor(() => expect(screen.getByTestId("settings-save-state")).toHaveTextContent("Не сохранено"));
    // Xatodan keyin server holati qayta o'qiladi (SB-020).
    await waitFor(() => expect(calls.filter((c) => c.method === "GET" && c.url.includes("/receipt/settings")).length).toBe(getsBefore + 1));
    // Keyingi muvaffaqiyatli saqlash xato matnini tozalaydi.
    srv.failPut = null;
    await user.click(till);
    await waitFor(() => expect(till).toHaveAttribute("aria-checked", "true"));
    await waitFor(() => expect(screen.getByTestId("rs-status")).toHaveTextContent(""));
    await waitFor(() => expect(screen.getByTestId("settings-save-state")).toHaveTextContent("Изменения сохраняются автоматически"));
  });
});

describe("Settings ?tab=receipt (chop etish xatosidagi «Printer sozlamasi» havolasi)", () => {
  it("chek tabi to'g'ridan-to'g'ri ochiladi; noma'lum tab — umumiy", async () => {
    fakeServerWithSettings();
    const { unmount } = renderApp(<Settings />, { lang: "ru", route: "/sozlamalar?tab=receipt" });
    expect(await screen.findByRole("switch", { name: "Номер кассы" })).toBeInTheDocument();
    unmount();
    fakeServerWithSettings();
    renderApp(<Settings />, { lang: "ru", route: "/sozlamalar?tab=nope" });
    await waitFor(() => expect(screen.queryByRole("switch", { name: "Номер кассы" })).toBeNull());
  });
});

/** Settings ekrani uchun: `/settings` va `/payments/config` + chek soxta serveri. */
function fakeServerWithSettings(over: Partial<Srv> = {}) {
  const inner = fakeServer(over);
  const receiptFetch = globalThis.fetch;
  const json = (v: unknown) => new Response(JSON.stringify(v), { status: 200, headers: { "Content-Type": "application/json" } });
  vi.stubGlobal("fetch", vi.fn(async (u: string, opts: RequestInit = {}) => {
    const s = String(u);
    if (/\/api\/v1\/settings$/.test(s)) {
      const method = (opts.method || "GET").toUpperCase();
      inner.calls.push({ url: s, method, body: opts.body ? JSON.parse(String(opts.body)) : null });
      return json(method === "PUT" ? {} : { store_info: { name: "Oltin" } });
    }
    if (/\/api\/v1\/payments\/config$/.test(s)) return json({ xpay_enabled: false });
    return receiptFetch(u, opts);
  }));
  return inner;
}

describe("ReceiptSettings — oldindan ko'rish", () => {
  it("pastki matn yozilayotganda (saqlashdan OLDIN) ko'rinishda chiqadi; XSS qochiriladi", async () => {
    const { calls } = fakeServer();
    const user = userEvent.setup();
    renderApp(<ReceiptSettings />, { lang: "ru" });
    await frame();
    expect(srcdoc()).toContain("Спасибо за покупку!"); // standart pastki matn
    const footer = screen.getByLabelText("Нижний текст");
    await user.type(footer, "Rahmat, yana keling");
    expect(srcdoc()).toContain("Rahmat, yana keling");
    expect(puts(calls)).toHaveLength(0);

    await user.clear(footer);
    fireEvent.change(footer, { target: { value: `<img src=x onerror=alert(1)>"><script>alert(2)</script>` } });
    const html = srcdoc();
    // Uzun satr so'z chegarasida bo'linadi — qismlar alohida tekshiriladi.
    expect(html).toContain("&lt;img src=x");
    expect(html).toContain("onerror=alert(1)&gt;&quot;&gt;&lt;script&gt;alert(2)&lt;/script&gt;");
    expect(html).not.toContain("<img src=x");
    expect(html).not.toContain("<script>");
    expect(html).toContain("Content-Security-Policy");
  });

  it("58/80: sozlama PUT {width_mm: 58} va ko'rinish kengligi; ko'rinishning o'z tanlovi hech narsa yozmaydi", async () => {
    const { calls } = fakeServer();
    const user = userEvent.setup();
    renderApp(<ReceiptSettings />, { lang: "ru" });
    const f = await frame();
    expect(f).toHaveAttribute("data-width-mm", "80");
    expect(srcdoc()).toMatch(/@page \{ size: 80mm \d+mm; margin: 0 \}/);
    await user.click(screen.getByTestId("rs-width-58"));
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toEqual({ branch_id: null, value: { width_mm: 58 } });
    expect(screen.getByTestId("rs-preview-frame")).toHaveAttribute("data-width-mm", "58");
    expect(srcdoc()).toMatch(/@page \{ size: 58mm \d+mm; margin: 0 \}/);
    expect(screen.getByTestId("rs-preview-frame")).toHaveAttribute("title", "Образец чека, 58 мм");

    await user.click(screen.getByTestId("rs-preview-width-80"));
    expect(screen.getByTestId("rs-preview-frame")).toHaveAttribute("data-width-mm", "80");
    expect(puts(calls)).toHaveLength(1);
    // Shablon kengligi o'zgarsa — ko'rinish yana shablonga ergashadi.
    await user.click(screen.getByTestId("rs-width-80"));
    await user.click(screen.getByTestId("rs-width-58"));
    await waitFor(() => expect(screen.getByTestId("rs-preview-frame")).toHaveAttribute("data-width-mm", "58"));
  });

  it("namuna har tur uchun serverdan BIR MARTA; qoralamadagi shtrix-kod/xaridor darhol ko'rinadi", async () => {
    const { calls } = fakeServer();
    const user = userEvent.setup();
    renderApp(<ReceiptSettings />, { lang: "ru" });
    await frame();
    expect(srcdoc()).not.toContain("CODE128");
    await user.click(screen.getByRole("switch", { name: "Штрихкод чека (для сканирования при возврате)" }));
    await waitFor(() => expect(srcdoc()).toContain('aria-label="CODE128"'));
    await user.click(screen.getByTestId("rs-sample-long"));
    await waitFor(() => expect(srcdoc()).toContain("120"));
    await user.click(screen.getByTestId("rs-sample-sale"));
    await user.click(screen.getByTestId("rs-sample-long"));
    const sampleGets = calls.filter((c) => c.url.includes("/receipt/sample"));
    expect(sampleGets.map((c) => new URL(c.url, "http://x").searchParams.get("kind"))).toEqual(["sale", "long"]);
  });

  it("server namunasi yo'q — mahalliy namuna va izoh", async () => {
    mockApi([
      [/\/receipt\/settings/, fakeView()],
      [/\/receipt\/sample/, { __status: 503, detail: "x" }],
    ]);
    renderApp(<ReceiptSettings />, { lang: "ru" });
    await frame();
    expect(screen.getByTestId("rs-preview-local")).toHaveTextContent("Не удалось получить образец с сервера");
    expect(srcdoc()).toContain("TEST");
  });

  it("sinov chop etish: virtual printer, TEST banneri va FAQAT GET so'rovlar", async () => {
    const { calls } = fakeServer();
    const printed: VirtualPrintRequest[] = [];
    window.__BINOS_VIRTUAL_PRINTER__ = (req) => { printed.push(req); return { ok: true }; };
    const user = userEvent.setup();
    renderApp(<ReceiptSettings />, { lang: "ru" });
    await frame();
    await user.click(screen.getByTestId("rs-sample-mixed"));
    await user.click(screen.getByRole("button", { name: "Напечатать этот образец" }));
    await waitFor(() => expect(screen.getByTestId("rs-test-result")).toHaveTextContent("Тестовый чек напечатан"));
    expect(printed).toHaveLength(1);
    expect(printed[0].kind).toBe("html");
    expect(printed[0].html).toContain("*** TEST PRINT ***");
    const sampleCall = calls.filter((c) => c.url.includes("/receipt/sample")).pop()!;
    expect(new URL(sampleCall.url, "http://x").searchParams.get("kind")).toBe("mixed");
    expect(writes(calls)).toHaveLength(0);
  });
});

describe("ReceiptSettings — QR", () => {
  it("do'kon havolasi rejimi havolasiz saqlanmaydi; havola kiritilgach ikkalasi birga ketadi", async () => {
    const { calls } = fakeServer();
    const user = userEvent.setup();
    renderApp(<ReceiptSettings />, { lang: "ru" });
    await user.selectOptions(await screen.findByLabelText("QR-код"), "store_url");
    expect(await screen.findByRole("alert")).toHaveTextContent("Введите ссылку");
    expect(puts(calls)).toHaveLength(0);
    const url = screen.getByLabelText("Ссылка для QR");
    await user.type(url, "javascript:alert(1)");
    await user.tab();
    expect(await screen.findByRole("alert")).toHaveTextContent("Ссылка должна начинаться с http:// или https://");
    expect(puts(calls)).toHaveLength(0);
    await user.clear(url);
    await user.type(url, "https://oltin.uz/chek");
    await user.tab();
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toEqual({ branch_id: null, value: { qr_url: "https://oltin.uz/chek", qr_mode: "store_url" } });
    // Saqlangan QR bilan server namunasi qayta so'raladi (matritsa serverda yasaladi).
    await waitFor(() => expect(calls.filter((c) => c.url.includes("/receipt/sample")).length).toBe(2));
  });
});

describe("ReceiptSettings — QR havolasi: ko'rinmas belgilar va filial merosi", () => {
  it("havolada ko'rinmas (Cf) belgi — maydonda «yaroqsiz», saqlanmaydi (aks holda QR jimgina chiqmasdi)", async () => {
    const { calls } = fakeServer();
    const user = userEvent.setup();
    renderApp(<ReceiptSettings />, { lang: "ru" });
    await user.selectOptions(await screen.findByLabelText("QR-код"), "store_url");
    const url = screen.getByLabelText("Ссылка для QR");
    for (const cf of [ZWSP, String.fromCharCode(0xad), String.fromCharCode(0x2060), String.fromCharCode(0x202e)]) {
      await user.clear(url);
      await user.type(url, "https://t.me/shop" + cf);
      await user.tab();
      expect(await screen.findByRole("alert")).toHaveTextContent("Ссылка должна начинаться с http:// или https://");
      expect(puts(calls)).toHaveLength(0);
    }
    await user.clear(url);
    await user.type(url, "https://t.me/shop");
    await user.tab();
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toEqual({ branch_id: null, value: { qr_url: "https://t.me/shop", qr_mode: "store_url" } });
  });

  it("saqlangan (eski) havolani layout rad etsa (qr_invalid) — ko'rinishda alohida izoh, QR yo'q", async () => {
    fakeServer({ company: { qr_mode: "store_url", qr_url: "https://oltin.uz/" + ZWSP } });
    renderApp(<ReceiptSettings />, { lang: "ru" });
    await frame();
    expect(await screen.findByTestId("rs-preview-qr-note")).toHaveTextContent("QR-код не будет напечатан");
    expect(srcdoc()).not.toContain('aria-label="QR"');
  });

  it("yaroqli saqlangan havola — QR chiqadi, izoh yo'q", async () => {
    fakeServer({ company: { qr_mode: "store_url", qr_url: "https://oltin.uz/" } });
    renderApp(<ReceiptSettings />, { lang: "ru" });
    await frame();
    await waitFor(() => expect(srcdoc()).toContain('aria-label="QR"'));
    expect(screen.queryByTestId("rs-preview-qr-note")).toBeNull();
  });

  it("filial: o'z havolasini bo'shatish — PUT {qr_url: null} (kompaniya havolasi meros); kompaniyada — «kiriting»", async () => {
    const { srv, calls } = fakeServer({
      company: { qr_mode: "store_url", qr_url: "https://company.uz" }, branches: { b2: { qr_url: "https://branch.uz" } },
    });
    const user = userEvent.setup();
    renderApp(<ReceiptSettings />, { lang: "ru" });
    await screen.findByLabelText("Ссылка для QR");
    await user.selectOptions(screen.getByLabelText("Для каких чеков"), "b2");
    const url = await screen.findByDisplayValue("https://branch.uz");
    await user.clear(url);
    await user.tab();
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toEqual({ branch_id: "b2", value: { qr_url: null } });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(srv.branches.b2).toEqual({});
    await waitFor(() => expect(screen.getByTestId("rs-inherited-qr_url")).toBeInTheDocument());
    expect((screen.getByLabelText("Ссылка для QR") as HTMLInputElement).placeholder).toBe("https://company.uz");

    // Kompaniya doirasida meros qatlami yo'q — bo'sh havola store_url rejimida saqlanmaydi.
    await user.selectOptions(screen.getByLabelText("Для каких чеков"), "");
    const cu = await screen.findByDisplayValue("https://company.uz");
    await user.clear(cu);
    await user.tab();
    expect(await screen.findByRole("alert")).toHaveTextContent("Введите ссылку");
    expect(puts(calls)).toHaveLength(1);
  });

  it("filial: havola bo'shatilgan (hali saqlanmagan) holda rejim qayta store_url — kompaniya havolasi meros, «kiriting» emas", async () => {
    const { calls } = fakeServer({
      company: { qr_mode: "store_url", qr_url: "https://company.uz" }, branches: { b2: { qr_url: "https://branch.uz" } },
    });
    const user = userEvent.setup();
    renderApp(<ReceiptSettings />, { lang: "ru" });
    await screen.findByLabelText("Ссылка для QR");
    await user.selectOptions(screen.getByLabelText("Для каких чеков"), "b2");
    const url = await screen.findByDisplayValue("https://branch.uz");
    // Fokus o'zgarmaydi (blur yo'q) — bo'sh qiymat faqat mahalliy qoralamada.
    fireEvent.change(url, { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("QR-код"), { target: { value: "none" } });
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toEqual({ branch_id: "b2", value: { qr_mode: "none" } });
    fireEvent.change(screen.getByLabelText("QR-код"), { target: { value: "store_url" } });
    await waitFor(() => expect(puts(calls)).toHaveLength(2));
    expect(puts(calls)[1].body).toEqual({ branch_id: "b2", value: { qr_mode: "store_url", qr_url: null } });
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("ReceiptSettings — chek tili filialda", () => {
  it("kompaniya tili aniq bo'lsa filialda «kassa tili» varianti yo'q (null = meros); meros — «вернуть стандарт»", async () => {
    const { calls } = fakeServer({ company: { lang: "ru" } });
    const user = userEvent.setup();
    renderApp(<ReceiptSettings />, { lang: "ru" });
    const opts = () => Array.from((screen.getByLabelText("Язык чека") as HTMLSelectElement).options).map((o) => o.value);
    await screen.findByLabelText("Язык чека");
    expect(opts()).toContain(""); // kompaniya doirasida — bor
    await user.selectOptions(screen.getByLabelText("Для каких чеков"), "b2");
    await waitFor(() => expect(screen.getByTestId("rs-inherited-lang")).toBeInTheDocument());
    expect(opts()).not.toContain("");
    expect(opts()).toEqual(expect.arrayContaining(["uz", "uzc", "ru", "ky"]));
    expect(screen.getByLabelText("Язык чека")).toHaveValue("ru");
    await user.selectOptions(screen.getByLabelText("Язык чека"), "uz");
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toEqual({ branch_id: "b2", value: { lang: "uz" } });
    await user.click(await screen.findByRole("button", { name: "Язык чека: вернуть стандарт" }));
    await waitFor(() => expect(puts(calls)).toHaveLength(2));
    expect(puts(calls)[1].body).toEqual({ branch_id: "b2", value: { lang: null } });
    await waitFor(() => expect(screen.getByLabelText("Язык чека")).toHaveValue("ru"));

    // Kompaniya tili «kassa tili» (null) bo'lsa — filialda ham shu variant (meros aynan shu).
    await user.selectOptions(screen.getByLabelText("Для каких чеков"), "");
    await waitFor(() => expect(screen.getByLabelText("Язык чека")).toHaveValue("ru"));
    await user.selectOptions(screen.getByLabelText("Язык чека"), "");
    await waitFor(() => expect(puts(calls)).toHaveLength(3));
    expect(puts(calls)[2].body).toEqual({ branch_id: null, value: { lang: null } });
    await user.selectOptions(screen.getByLabelText("Для каких чеков"), "b2");
    await waitFor(() => expect(screen.getByTestId("rs-inherited-lang")).toBeInTheDocument());
    expect(opts()).toContain("");
  });
});

describe("ReceiptSettings — kompaniya doirasining namunasi", () => {
  it("kompaniya doirasi: namuna va sinov chop etish scope=company (xodim filiali ustamasi emas); filialda — branch_id", async () => {
    const { calls } = fakeServer({ company: { footer: "Rahmat!" }, branches: { b1: { footer: "Filial A", width_mm: 58 } } });
    const printed: VirtualPrintRequest[] = [];
    window.__BINOS_VIRTUAL_PRINTER__ = (req) => { printed.push(req); return { ok: true }; };
    const user = userEvent.setup();
    renderApp(<ReceiptSettings />, { lang: "ru" });
    await frame();
    await waitFor(() => expect(srcdoc()).toContain("SAMPLE:company"));
    const sampleQ = () => calls.filter((c) => c.url.includes("/receipt/sample")).map((c) => new URL(c.url, "http://x").searchParams);
    expect(sampleQ()[0].get("scope")).toBe("company");
    expect(sampleQ()[0].get("branch_id")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Напечатать этот образец" }));
    await waitFor(() => expect(screen.getByTestId("rs-test-result")).toHaveTextContent("Тестовый чек напечатан"));
    expect(testPrintArgs[testPrintArgs.length - 1]).toEqual(["sale", { scope: "company", dto: expect.objectContaining({ test: true }) }]);

    await user.selectOptions(screen.getByLabelText("Для каких чеков"), "b2");
    await waitFor(() => expect(srcdoc()).toContain("SAMPLE:b2"));
    const b2 = sampleQ().find((q) => q.get("branch_id") === "b2")!;
    expect(b2.get("scope")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Напечатать этот образец" }));
    await waitFor(() => expect(testPrintArgs.length).toBe(2));
    expect(testPrintArgs[1]).toEqual(["sale", { branch_id: "b2", dto: expect.objectContaining({ test: true }) }]);
    expect(writes(calls)).toHaveLength(0);
  });
});

describe("ReceiptSettings — sinov chop etish = ko'rinish (R10)", () => {
  const LID = "aaaaaaaa-bbbb-5ccc-8ddd-eeeeeeeeeeee";
  const body = (html: string) => /<body>([\s\S]*)<\/body>/.exec(html)?.[1] ?? "";
  const sampleCalls = (calls: Call[]) => calls.filter((c) => c.url.includes("/receipt/sample"));

  it("qoralama (saqlanmagan) footer, logo, QR, shtrix-kod: qog'oz tanasi ko'rinish tanasi bilan AYNAN bir xil", async () => {
    const { calls } = fakeServer({
      company: { logo_id: LID, qr_mode: "store_url", qr_url: "https://oltin.uz/", show_barcode: true },
      logos: { [LID]: { id: LID, branch_id: null } },
      // Xodim filiali (b1) ustamasi — kompaniya doirasidagi qog'ozga TUSHMASLIGI kerak.
      branches: { b1: { footer: "Filial A", width_mm: 58 } },
    });
    const printed: VirtualPrintRequest[] = [];
    window.__BINOS_VIRTUAL_PRINTER__ = (req) => { printed.push(req); return { ok: true }; };
    const user = userEvent.setup();
    renderApp(<ReceiptSettings />, { lang: "ru" });
    await frame();
    await waitFor(() => expect(srcdoc()).toContain('aria-label="QR"'));
    await waitFor(() => expect(srcdoc()).toContain(TINY_PNG));
    // Saqlanmagan qoralama — faqat ko'rinishda (blur yo'q, PUT yo'q).
    fireEvent.change(screen.getByLabelText("Нижний текст"), { target: { value: "Qoralama rahmati" } });
    await waitFor(() => expect(srcdoc()).toContain("Qoralama rahmati"));
    await user.click(screen.getByRole("button", { name: "Напечатать этот образец" }));
    await waitFor(() => expect(screen.getByTestId("rs-test-result")).toHaveTextContent("Тестовый чек напечатан"));
    expect(printed).toHaveLength(1);
    const paper = body(printed[0].html ?? "");
    expect(paper).toContain("Qoralama rahmati");
    expect(paper).not.toContain("Filial A");
    expect(paper).toContain(TINY_PNG);
    expect(paper).toBe(body(srcdoc()));
    // Chop etish ko'rinish DTO'sini oldi — namuna qayta so'ralmadi (kompaniya doirasida ham).
    expect(testPrintArgs[0]).toEqual(["sale", expect.objectContaining({ scope: "company", dto: expect.objectContaining({ test: true }) })]);
    expect(sampleCalls(calls)).toHaveLength(1);
    expect(writes(calls)).toHaveLength(0);
  });

  it("ko'rinish kengligi (58) tanlansa — qog'oz ham 58 mm, ko'rinish bilan bir xil", async () => {
    fakeServer();
    const printed: VirtualPrintRequest[] = [];
    window.__BINOS_VIRTUAL_PRINTER__ = (req) => { printed.push(req); return { ok: true }; };
    const user = userEvent.setup();
    renderApp(<ReceiptSettings />, { lang: "ru" });
    await frame();
    await user.click(screen.getByTestId("rs-preview-width-58"));
    await waitFor(() => expect(screen.getByTestId("rs-preview-frame")).toHaveAttribute("data-width-mm", "58"));
    await user.click(screen.getByRole("button", { name: "Напечатать этот образец" }));
    await waitFor(() => expect(printed).toHaveLength(1));
    expect(printed[0].doc.width_mm).toBe(58);
    expect(body(printed[0].html ?? "")).toBe(body(srcdoc()));
  });

  it("filialga cheklangan (faqat ko'rish) xodim kompaniya doirasida: scope=company so'ralmaydi, «server namunasi olinmadi» yo'q, qog'oz = ko'rinish", async () => {
    login("menejer", ["sozlamalar.view"]);
    const { calls } = fakeServer({
      restricted: true, scope: { company_editable: false, branch_editable: false },
      company: { footer: "Kompaniya rahmati", qr_mode: "store_url", qr_url: "https://oltin.uz/" },
      branches: { b1: { footer: "Filial A" } },
    });
    const printed: VirtualPrintRequest[] = [];
    window.__BINOS_VIRTUAL_PRINTER__ = (req) => { printed.push(req); return { ok: true }; };
    const user = userEvent.setup();
    renderApp(<ReceiptSettings />, { lang: "ru" });
    await frame();
    await waitFor(() => expect(srcdoc()).toContain("Kompaniya rahmati"));
    expect(screen.getByLabelText("Для каких чеков")).toHaveValue("");
    expect(screen.queryByTestId("rs-preview-local")).toBeNull(); // nosozlik deb ko'rsatilmaydi
    expect(screen.queryByTestId("rs-preview-qr-note")).toBeNull(); // QR saqlangan — "saqlang" deyilmaydi
    await user.click(screen.getByTestId("rs-sample-return"));
    await waitFor(() => expect(srcdoc()).toContain("ВОЗВРАТ"));
    await user.click(screen.getByRole("button", { name: "Напечатать этот образец" }));
    await waitFor(() => expect(printed).toHaveLength(1));
    const paper = body(printed[0].html ?? "");
    expect(paper).toContain("Kompaniya rahmati");
    expect(paper).not.toContain("Filial A"); // xodim filiali ustamasi emas
    expect(paper).toBe(body(srcdoc()));
    expect(calls.some((c) => c.url.includes("scope=company"))).toBe(false);
    expect(writes(calls)).toHaveLength(0);
  });
});

describe("ReceiptSettings — «Qator chegirmalari» (R15)", () => {
  it.each([
    { lang: "uz" as const, label: "Qator chegirmalari", note: "Butun chekka berilgan chegirma har doim chiqadi" },
    { lang: "ru" as const, label: "Скидки по строкам", note: "Скидка на весь чек печатается всегда" },
  ])("$lang: yorliq qator chegirmalari haqida; umumiy chegirma doim chiqishi izohda", async ({ lang, label, note }) => {
    fakeServer();
    renderApp(<ReceiptSettings />, { lang });
    const sw = await screen.findByRole("switch", { name: label });
    expect(sw).toHaveAccessibleDescription(expect.stringContaining(note));
  });

  it("4 tilda yorliq", () => {
    expect(RECEIPT_UI.uz["rs.show_discount"]).toBe("Qator chegirmalari");
    expect(RECEIPT_UI.ru["rs.show_discount"]).toBe("Скидки по строкам");
    expect(RECEIPT_UI.ky["rs.show_discount"]).toBe("Сап боюнча арзандатуулар");
    expect(RECEIPT_UI.uzc["rs.show_discount"]).toBe("Қатор чегирмалари");
  });
});

describe("Settings «Umumiy» — do'kon ma'lumotlari doirasi (R3)", () => {
  const storeInputs = () => ["Название магазина", "Филиал", "Адрес", "Телефон", "ИНН"];

  it("filialga cheklangan admin (company_editable=false): do'kon maydonlari faqat o'qish, izoh bor, PUT yo'q", async () => {
    login("administrator", ["sozlamalar.view", "sozlamalar.edit"]);
    const { calls } = fakeServerWithSettings({ scope: { company_editable: false, branch_editable: true } });
    const user = userEvent.setup();
    renderApp(<Settings />, { lang: "ru" });
    const note = await screen.findByTestId("settings-store-readonly");
    expect(note).toHaveTextContent("Данные магазина печатаются на чеках всех филиалов — изменить их может только сотрудник с доступом ко всем филиалам");
    for (const l of storeInputs()) {
      const el = screen.getByLabelText(l) as HTMLInputElement;
      expect(el.readOnly, l).toBe(true);
      expect(el).toHaveAttribute("aria-describedby", note.id);
    }
    const name = screen.getByLabelText("Название магазина") as HTMLInputElement;
    expect(name.value).toBe("Oltin");
    await user.type(name, "X");
    await user.tab();
    expect(name.value).toBe("Oltin");
    expect(calls.filter((c) => c.method === "PUT")).toHaveLength(0);
  });

  it("cheklovsiz admin: maydonlar tahrirlanadi va saqlanadi; izoh yo'q", async () => {
    const { calls } = fakeServerWithSettings();
    const user = userEvent.setup();
    renderApp(<Settings />, { lang: "ru" });
    const name = (await screen.findByLabelText("Название магазина")) as HTMLInputElement;
    await waitFor(() => expect(calls.some((c) => c.url.includes("/receipt/settings"))).toBe(true));
    expect(name.readOnly).toBe(false);
    await user.type(name, "X");
    await user.tab();
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1));
    expect(calls.find((c) => c.method === "PUT")!.body).toEqual({ key: "store_info", value: { name: "OltinX" } });
    expect(screen.queryByTestId("settings-store-readonly")).toBeNull();
  });

  it("doira olinmasa (eski server) — tahrir ochiq; server 403 qaytarsa maydonlar yopiladi va sababi aytiladi", async () => {
    const puts: Call[] = [];
    const json = (v: unknown, status = 200) => new Response(JSON.stringify(v), { status, headers: { "Content-Type": "application/json" } });
    vi.stubGlobal("fetch", vi.fn(async (u: string, o: RequestInit = {}) => {
      const s = String(u);
      if (/\/api\/v1\/settings$/.test(s) && (o.method || "GET") === "PUT") {
        puts.push({ url: s, method: "PUT", body: JSON.parse(String(o.body)) });
        return new Response(JSON.stringify({ detail: "Ruxsat yo'q: kompaniya chek shablonini faqat barcha filiallarga kirish huquqi bor xodim o'zgartiradi" }),
          { status: 403, headers: { "Content-Type": "application/json", "X-Error-Code": "RECEIPT_SCOPE_COMPANY_FORBIDDEN" } });
      }
      if (/\/api\/v1\/settings$/.test(s)) return json({ store_info: { name: "Oltin" } });
      if (/\/payments\/config$/.test(s)) return json({ xpay_enabled: false });
      return json({ detail: "Not Found" }, 404);
    }));
    const user = userEvent.setup();
    renderApp(<Settings />, { lang: "ru" });
    const name = (await screen.findByLabelText("Название магазина")) as HTMLInputElement;
    expect(name.readOnly).toBe(false);
    await user.type(name, "X");
    await user.tab();
    await waitFor(() => expect(puts).toHaveLength(1));
    expect(await screen.findByTestId("settings-store-readonly")).toBeInTheDocument();
    await waitFor(() => expect(name.readOnly).toBe(true));
  });
});

describe("ReceiptSettings — logo", () => {
  const pngBytes = () => new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13, 73, 72, 68, 82, 1, 2, 3, 4]);
  const input = () => screen.getByTestId("rs-logo-file") as HTMLInputElement;
  const pick = (file: File) => fireEvent.change(input(), { target: { files: [file] } });

  it("GIF (turi) va 2 MB dan katta fayl mijozda rad etiladi — serverga yuborilmaydi", async () => {
    const { calls } = fakeServer();
    renderApp(<ReceiptSettings />, { lang: "ru" });
    await screen.findByRole("heading", { name: "Логотип" });
    expect(input()).toHaveAttribute("accept", "image/png,image/jpeg,image/webp");
    expect(screen.getByLabelText("Файл логотипа")).toBe(input());

    pick(new File([new Uint8Array([0x47, 0x49, 0x46, 0x38, 0x39, 0x61])], "a.gif", { type: "image/gif" }));
    await waitFor(() => expect(screen.getByTestId("rs-logo-status")).toHaveTextContent("Логотип может быть только PNG, JPEG или WebP"));
    pick(new File([new Uint8Array(2 * 1024 * 1024 + 1)], "big.png", { type: "image/png" }));
    await waitFor(() => expect(screen.getByTestId("rs-logo-status")).toHaveTextContent("Файл логотипа слишком большой (не более 2 МБ)"));
    // PNG deb e'lon qilingan, ichi HTML (poliglot/soxta kengaytma) — sehrli bayt tekshiruvi.
    pick(new File(["<html><script>alert(1)</script></html>"], "fake.png", { type: "image/png" }));
    await waitFor(() => expect(screen.getByTestId("rs-logo-status")).toHaveTextContent("Логотип может быть только PNG, JPEG или WebP"));
    expect(writes(calls)).toHaveLength(0);
  });

  it("PNG: POST /receipt/logos (base64, doira bilan), keyin PUT logo_id; 58/80 ko'rinishi va chekda", async () => {
    const { calls } = fakeServer();
    renderApp(<ReceiptSettings />, { lang: "ru" });
    await frame();
    pick(new File([pngBytes()], "logo.png", { type: "image/png" }));
    await waitFor(() => expect(screen.getByTestId("rs-logo-status")).toHaveTextContent("Логотип сохранён"));
    const w = writes(calls);
    expect(w.map((c) => `${c.method} ${new URL(c.url, "http://x").pathname.replace(/^.*\/api\/v1/, "")}`)).toEqual([
      "POST /receipt/logos", "PUT /receipt/settings",
    ]);
    expect(w[0].body).toEqual({ branch_id: null, data_b64: Buffer.from(pngBytes()).toString("base64") });
    expect(w[1].body).toEqual({ branch_id: null, value: { logo_id: "11111111-2222-5333-8444-555555555555" } });
    expect(screen.getByRole("img", { name: "Логотип на чеке 58 мм" })).toHaveAttribute("src", TINY_PNG);
    expect(screen.getByRole("img", { name: "Логотип на чеке 80 мм" })).toBeInTheDocument();
    await waitFor(() => expect(srcdoc()).toContain(TINY_PNG));
    // Olib tashlash — logo_id: null.
    await userEvent.setup().click(screen.getByRole("button", { name: "Убрать логотип" }));
    await waitFor(() => expect(puts(calls)).toHaveLength(2));
    expect(puts(calls)[1].body).toEqual({ branch_id: null, value: { logo_id: null } });
    await waitFor(() => expect(screen.queryByRole("img", { name: "Логотип на чеке 58 мм" })).toBeNull());
  });
});

describe("ReceiptSettings — filial logosi", () => {
  it("kompaniya logosi filialda meros; filialga yuklash branch_id bilan; «вернуть стандарт» → logo_id: null", async () => {
    const LID = "aaaaaaaa-bbbb-5ccc-8ddd-eeeeeeeeeeee";
    const { calls } = fakeServer({ company: { logo_id: LID }, logos: { [LID]: { id: LID, branch_id: null } } });
    const user = userEvent.setup();
    renderApp(<ReceiptSettings />, { lang: "ru" });
    await screen.findByRole("img", { name: "Логотип на чеке 80 мм" });
    await user.selectOptions(screen.getByLabelText("Для каких чеков"), "b2");
    expect(await screen.findByText("Используется логотип компании")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Логотип на чеке 58 мм" })).toBeInTheDocument();
    // Meros logoni filialdan «olib tashlab» bo'lmaydi (faqat ko'rsatishni o'chirish yoki o'z logosi).
    expect(screen.queryByRole("button", { name: "Логотип: вернуть стандарт" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Убрать логотип" })).toBeNull();

    const png = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2, 3]);
    fireEvent.change(screen.getByTestId("rs-logo-file"), { target: { files: [new File([png], "f.png", { type: "image/png" })] } });
    await waitFor(() => expect(screen.getByTestId("rs-logo-status")).toHaveTextContent("Логотип сохранён"));
    const w = writes(calls);
    expect(w[0].body.branch_id).toBe("b2");
    expect(w[1].body).toEqual({ branch_id: "b2", value: { logo_id: "11111111-2222-5333-8444-555555555555" } });
    expect(screen.queryByText("Используется логотип компании")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Логотип: вернуть стандарт" }));
    await waitFor(() => expect(puts(calls)).toHaveLength(2));
    expect(puts(calls)[1].body).toEqual({ branch_id: "b2", value: { logo_id: null } });
    expect(await screen.findByText("Используется логотип компании")).toBeInTheDocument();
  });
});

describe("Settings — «Chek va printer» bo'limi va tor ekran", () => {
  it("receipt bo'limi ReceiptSettings'ni ko'rsatadi; eski printer tanlovi va printReceipt yo'q", async () => {
    fakeServerWithSettings();
    const user = userEvent.setup();
    renderApp(<Settings />, { lang: "ru" });
    const tab = await screen.findByRole("button", { name: "Чек и принтер" });
    expect(tab).toHaveAttribute("aria-pressed", "false");
    await user.click(tab);
    expect(tab).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByTestId("receipt-settings")).toBeInTheDocument();
    expect(screen.getByTestId("settings-save-state")).toHaveAttribute("aria-live", "polite");
    await user.click(screen.getByRole("switch", { name: "Номер кассы" }));
    await waitFor(() => expect(screen.getByTestId("settings-save-state")).toHaveTextContent("Изменения сохраняются автоматически"));

    const src = fs.readFileSync(path.resolve(__dirname, "../packages/shared/src/screens/Settings.tsx"), "utf8");
    expect(src).not.toMatch(/printReceipt|PrinterSelect|@\/lib\/receipt"/);
  });

  it("tor ekran (<=760px): bo'limlar ro'yxati kontent ustida gorizontal qator", async () => {
    const orig = window.matchMedia;
    window.matchMedia = ((q: string) => ({
      matches: /max-width:\s*760px/.test(q), media: q, onchange: null,
      addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
    })) as any;
    try {
      fakeServerWithSettings();
      renderApp(<Settings />, { lang: "ru" });
      const nav = await screen.findByTestId("settings-tabs");
      expect(nav.style.overflowX).toBe("auto");
      expect(nav.style.width).toBe("");
      expect(within(nav).getAllByRole("button")).toHaveLength(6);
      expect(within(nav).getByRole("button", { name: "Тариф" })).toBeInTheDocument();
    } finally {
      window.matchMedia = orig;
    }
  });
});

describe("i18n — rs.* kalitlari", () => {
  it("4 tilda bir xil kalitlar, bo'sh qiymat yo'q, o'zgaruvchilar mos", () => {
    const langs = ["uz", "ru", "ky", "uzc"] as const;
    const keys = Object.keys(RECEIPT_UI.uz).sort();
    expect(keys.length).toBeGreaterThan(60);
    for (const l of langs) {
      expect(Object.keys(RECEIPT_UI[l]).sort(), l).toEqual(keys);
      for (const k of keys) {
        const v = RECEIPT_UI[l][k];
        expect(v.trim(), `${l}:${k}`).not.toBe("");
        const vars = (s: string) => (s.match(/\{\w+\}/g) || []).sort().join(",");
        expect(vars(v), `${l}:${k}`).toBe(vars(RECEIPT_UI.uz[k]));
      }
    }
    // ky — haqiqiy qirg'izcha (rus nusxasi emas).
    expect(RECEIPT_UI.ky["rs.previewTitle"]).not.toBe(RECEIPT_UI.ru["rs.previewTitle"]);
  });
});

function fakeView(over: Row = {}) {
  return {
    scope: { branch_id: null, company_editable: true, branch_editable: false },
    branches: BRANCHES, company: {}, branch: null, effective: { ...BUILTIN_ALL },
    store: { name: "Oltin Do'kon", branch_name: null, address: null, phone: null, stir: null },
    logo: null, ...over,
  };
}
