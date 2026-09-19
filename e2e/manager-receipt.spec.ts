import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import * as zlib from "zlib";
import { managerLogin, MANAGER } from "./helpers";

// Manager — «Chek va printer» sozlamalari (Phase 5F): HAQIQIY backend + brauzer.
//
// ⚠️  KOMPANIYA shabloni o'zgartiriladi (pastki matn, kenglik, logo) — boshqa spec'lar (POS chop
//     etish) standart chekka tayanadi. Shu bois oldin va keyin API orqali STANDARTGA qaytariladi
//     (maydonlar `null` = meros), sinov tartibiga bog'liq bo'lib qolmasin.
// ⚠️  Chop etish — VIRTUAL printer (`window.__BINOS_VIRTUAL_PRINTER__`, addInitScript): brauzer
//     chop etish oynasi ochilmaydi, chiqqan HTML esa aynan ushlanadi.

const API = "http://127.0.0.1:8000/api/v1";
const TAG = "E2E" + Math.random().toString(36).slice(2, 6).toUpperCase();

async function api(req: APIRequestContext, method: "get" | "put", path: string, token?: string, data?: unknown) {
  const r = await req[method](API + path, {
    headers: token ? { Authorization: "Bearer " + token } : {},
    data: data as any,
  });
  expect(r.ok(), `${method.toUpperCase()} ${path} -> ${r.status()} ${await r.text()}`).toBeTruthy();
  return r.json();
}

async function login(req: APIRequestContext): Promise<string> {
  const r = await req.post(API + "/auth/login/password", { data: { phone: "+998901234567", password: "demo1234" } });
  expect(r.ok(), await r.text()).toBeTruthy();
  const j = await r.json();
  return j.access_token || j.token;
}

/** Kompaniya chek shablonini standartga qaytaradi (null = maydon o'chadi, BUILTIN ishlaydi). */
async function restoreDefaults(req: APIRequestContext) {
  const token = await login(req);
  await api(req, "put", "/receipt/settings", token, {
    branch_id: null,
    value: { footer: null, header: null, width_mm: null, logo_id: null, show_logo: null, show_barcode: null },
  });
}

// ── haqiqiy PNG (Pillow ochadigan): 96×48 kulrang, markazda qora to'rtburchak ────────────
const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();
function crc32(buf: Buffer): number {
  let c = 0xffffffff;
  for (const b of buf) c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}
function chunk(type: string, data: Buffer): Buffer {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const td = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(td));
  return Buffer.concat([len, td, crc]);
}
function makePng(w: number, h: number): Buffer {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0);
  ihdr.writeUInt32BE(h, 4);
  ihdr[8] = 8; // 8 bit
  ihdr[9] = 0; // kulrang
  const raw = Buffer.alloc((w + 1) * h, 255);
  for (let y = 0; y < h; y++) {
    raw[y * (w + 1)] = 0; // filtr: yo'q
    for (let x = 0; x < w; x++) {
      if (x >= w / 4 && x < (3 * w) / 4 && y >= h / 4 && y < (3 * h) / 4) raw[y * (w + 1) + 1 + x] = 0;
    }
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr), chunk("IDAT", zlib.deflateSync(raw)), chunk("IEND", Buffer.alloc(0)),
  ]);
}

/** Sahifa GORIZONTAL surilmasligi (boshqa mobil spec'lar bilan bir xil o'lchov). */
async function noSideScroll(page: Page) {
  const overflow = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, "sahifa yon tomonga suriladi").toBeLessThanOrEqual(1);
}

async function openReceiptTab(page: Page) {
  await page.goto(`${MANAGER}/#/sozlamalar`);
  await page.getByRole("button", { name: "Чек и принтер", exact: true }).click();
  await expect(page.getByTestId("receipt-settings")).toBeVisible();
  await expect(page.getByTestId("rs-preview-frame")).toBeAttached({ timeout: 15_000 });
}

/** Virtual printer: har chop etish so'rovi `window.__e2ePrints` ga yoziladi va «chop etildi» qaytadi. */
async function virtualPrinter(page: Page) {
  await page.addInitScript(() => {
    const w = window as any;
    w.__e2ePrints = [];
    w.__BINOS_VIRTUAL_PRINTER__ = (req: any) => {
      w.__e2ePrints.push({ kind: req.kind, html: String(req.html ?? ""), width: req.doc?.width_mm ?? null });
      return { ok: true };
    };
  });
}

test.beforeAll(async ({ request }) => { await restoreDefaults(request); });
test.afterAll(async ({ request }) => { await restoreDefaults(request); });

test.describe("Chek sozlamalari — desktop", () => {
  test("pastki matn ko'rinishda (saqlashdan oldin) va serverda; 58/80 kenglik; PNG logo; sinov chop etish yozmaydi", async ({ page, request }) => {
    await virtualPrinter(page);
    await managerLogin(page);
    await openReceiptTab(page);
    await noSideScroll(page);

    const frame = page.getByTestId("rs-preview-frame");
    await expect(frame).toHaveAttribute("title", "Образец чека, 80 мм");
    await expect(frame).toHaveAttribute("sandbox", "");

    // 1) Pastki matn: yozilayotganda ko'rinish yangilanadi, maydondan chiqqanda saqlanadi.
    const footerText = `Rahmat ${TAG}`;
    const footer = page.getByLabel("Нижний текст");
    await footer.fill(footerText);
    await expect(frame).toHaveAttribute("srcdoc", new RegExp(footerText));
    await expect(page.frameLocator('[data-testid="rs-preview-frame"]').getByText(footerText)).toBeVisible();
    const saved = page.waitForResponse((r) => r.url().includes("/receipt/settings") && r.request().method() === "PUT");
    await footer.blur();
    const put = await saved;
    expect(put.ok()).toBeTruthy();
    expect(put.request().postDataJSON()).toEqual({ branch_id: null, value: { footer: footerText } });
    const token = await login(request);
    const server = await api(request, "get", "/receipt/settings", token);
    expect(server.company.footer).toBe(footerText);
    await expect(page.getByTestId("settings-save-state")).toHaveText("Изменения сохраняются автоматически");

    // 2) 58/80: sozlama saqlanadi va ko'rinish torayadi.
    const w80 = (await frame.boundingBox())!.width;
    const widthSaved = page.waitForResponse((r) => r.url().includes("/receipt/settings") && r.request().method() === "PUT");
    await page.getByTestId("rs-width-58").click();
    expect((await widthSaved).request().postDataJSON()).toEqual({ branch_id: null, value: { width_mm: 58 } });
    await expect(frame).toHaveAttribute("data-width-mm", "58");
    await expect(frame).toHaveAttribute("srcdoc", /size: 58mm auto/);
    await expect(frame).toHaveAttribute("title", "Образец чека, 58 мм");
    const w58 = (await frame.boundingBox())!.width;
    expect(w58).toBeLessThan(w80);
    // Ko'rinishning o'z kenglik tanlovi hech narsa yozmaydi.
    await page.getByTestId("rs-preview-width-80").click();
    await expect(frame).toHaveAttribute("data-width-mm", "80");
    await page.getByTestId("rs-preview-width-58").click();
    await expect(frame).toHaveAttribute("data-width-mm", "58");

    // 3) PNG logo: yuklanadi, 58/80 nuqtali ko'rinishi va chek namunasida chiqadi.
    const uploaded = page.waitForResponse((r) => r.url().includes("/receipt/logos") && r.request().method() === "POST");
    await page.getByTestId("rs-logo-file").setInputFiles({ name: "logo.png", mimeType: "image/png", buffer: makePng(96, 48) });
    expect([200, 201]).toContain((await uploaded).status());
    await expect(page.getByTestId("rs-logo-status")).toHaveText("Логотип сохранён");
    await expect(page.getByRole("img", { name: "Логотип на чеке 58 мм" })).toBeVisible();
    await expect(page.getByRole("img", { name: "Логотип на чеке 80 мм" })).toBeVisible();
    await expect(frame).toHaveAttribute("srcdoc", /<img alt="" src="data:image\/png;base64,/);
    const afterLogo = await api(request, "get", "/receipt/settings", token);
    expect(typeof afterLogo.company.logo_id).toBe("string");
    expect(afterLogo.logo?.id).toBe(afterLogo.company.logo_id);

    // 4) Sinov chop etish: virtual printer, TEST banneri, saqlangan pastki matn — va HECH QANDAY yozish.
    const writes: string[] = [];
    const onReq = (r: import("@playwright/test").Request) => {
      const m = r.method();
      const u = r.url();
      if (m === "GET" || m === "HEAD" || m === "OPTIONS" || !u.includes("/api/v1/")) return;
      if (u.includes("/fleet/heartbeat")) return; // ilova fon yurak urishi — chop etishga aloqasi yo'q
      writes.push(`${m} ${u}`);
    };
    page.on("request", onReq);
    await page.getByRole("button", { name: "Напечатать этот образец" }).click();
    await expect(page.getByTestId("rs-test-result")).toHaveText("Тестовый чек напечатан");
    const prints = await page.evaluate(() => (window as any).__e2ePrints as { kind: string; html: string; width: number }[]);
    page.off("request", onReq);
    expect(prints).toHaveLength(1);
    expect(prints[0].kind).toBe("html");
    expect(prints[0].html).toContain("*** TEST PRINT ***");
    expect(prints[0].html).toContain(footerText);
    expect(prints[0].html).toContain("size: 58mm auto");
    expect(writes, "sinov chop etish yozish so'rovi yubordi").toEqual([]);
  });

  test("XSS pastki matn ko'rinishda qochirilgan matn bo'lib chiqadi (skript yo'q)", async ({ page }) => {
    await managerLogin(page);
    await openReceiptTab(page);
    const evil = `<img src=x onerror=alert(1)> ${TAG}`;
    await page.getByLabel("Нижний текст").fill(evil);
    const frame = page.getByTestId("rs-preview-frame");
    await expect(frame).toHaveAttribute("srcdoc", /&lt;img src=x/);
    const doc = (await frame.getAttribute("srcdoc")) || "";
    expect(doc).not.toContain("<img src=x");
    // Saqlanmaydi — standart holat keyingi spec'larga ta'sir qilmasin.
    await page.getByLabel("Нижний текст").fill("");
  });
});

test.describe("Chek sozlamalari — mobil 390px", () => {
  test.use({ viewport: { width: 390, height: 780 } });

  test("Sozlamalar va «Чек и принтер» yon tomonga surilmaydi; bo'limlar qatori tepada; ko'rinish sig'adi", async ({ page }) => {
    await managerLogin(page);
    await page.goto(`${MANAGER}/#/sozlamalar`);
    await expect(page.getByTestId("settings-tabs")).toBeVisible();
    await noSideScroll(page);
    await openReceiptTab(page);
    await noSideScroll(page);

    // Bo'limlar ro'yxati kontent USTIDA (yonida emas).
    const tabs = (await page.getByTestId("settings-tabs").boundingBox())!;
    const content = (await page.getByTestId("receipt-settings").boundingBox())!;
    expect(tabs.y + tabs.height).toBeLessThanOrEqual(content.y + 1);

    // `.app` toshib chiqqanni kesadi (hujjat o'lchovi buni ko'rmaydi) — shu bois <main> va kontent
    // paneli ham alohida o'lchanadi.
    const mainOverflow = await page.locator("main").first().evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(mainOverflow, "<main> yon tomonga toshadi").toBeLessThanOrEqual(1);
    const inner = await page.locator("main .scroll").first().evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(inner, "kontent paneli yon tomonga suriladi").toBeLessThanOrEqual(1);

    // Chek ko'rinishi ekranga sig'adigan qilib kichraytiriladi.
    const frame = page.getByTestId("rs-preview-frame");
    await frame.scrollIntoViewIfNeeded();
    const box = (await frame.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(390);

    // Kalit maydonlar label orqali topiladi (kirish imkoniyati) va tor ekranda ham ishlaydi.
    await expect(page.getByLabel("Нижний текст")).toBeVisible();
    await expect(page.getByRole("switch", { name: "Номер кассы" })).toBeVisible();
    await page.getByTestId("rs-sample-long").click();
    await expect(frame).toHaveAttribute("srcdoc", /Superuzunmahsulot/); // serverning 120 qatorli namunasi
    await noSideScroll(page);
  });
});
