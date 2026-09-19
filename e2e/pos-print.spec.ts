import { test, expect, type Page } from "@playwright/test";
import { posLogin, POS } from "./helpers";

// POS — chek chop etish (Phase 5F). Haqiqiy printer o'rniga "virtual printer": sahifa skriptlaridan
// OLDIN `window.__BINOS_VIRTUAL_PRINTER__` e'lon qilinadi (addInitScript) — printing.ts uni ko'rsa
// chizilgan chekni (HTML + bloklar) shunga beradi va brauzer chop etish oynasi OCHILMAYDI.
//
// Chek SERVER DTO'sidan (`GET /sales/{id}/receipt`) chiziladi, jurnal (`/print-jobs`) ham haqiqiy
// backend'da. Faqat "Sotuvlarim" ro'yxati almashtiriladi: u OCHIQ smena talab qiladi, smena ochish esa
// keyingi spec'lar (pos.spec smena testi) holatini buzardi — ro'yxatga AYNAN shu sotuv qatori beriladi.

interface Captured { kind: string; html: string | null; copy: { kind: string; no?: number } | null }

async function installVirtualPrinter(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __printed?: unknown[]; __BINOS_VIRTUAL_PRINTER__?: unknown };
    w.__printed = w.__printed || [];
    w.__BINOS_VIRTUAL_PRINTER__ = (req: { kind: string; html?: string; copy: unknown }) => {
      w.__printed!.push({ kind: req.kind, html: req.html ?? null, copy: req.copy ?? null });
      return { ok: true };
    };
  });
}

const printedList = (page: Page) =>
  page.evaluate(() => ((window as unknown as { __printed?: unknown[] }).__printed || []) as unknown[]) as Promise<Captured[]>;

test.describe("POS — chek chop etish (virtual printer)", () => {
  test("naqd sotuv -> chop etish (raqamli ASL chek) -> Sotuvlarim'dan NUSXA", async ({ page }) => {
    await installVirtualPrinter(page);
    await posLogin(page);

    // ── Sotuv (pos.spec bilan bir xil oqim) ──
    await page.getByText("Suv 1L", { exact: true }).first().click();
    await page.getByRole("button", { name: /ЗАВЕРШИТЬ ОПЛАТУ/ }).click();
    await expect(page.getByText("СУММА ОПЛАТЫ")).toBeVisible();
    await page.getByRole("button", { name: "Наличные", exact: true }).last().click();
    const saleResp = page.waitForResponse((r) => r.url().endsWith("/api/v1/sales") && r.request().method() === "POST");
    await page.getByRole("button", { name: "Завершить оплату", exact: true }).click();
    const sale = await (await saleResp).json();
    await expect(page.getByText("Продажа успешно завершена")).toBeVisible({ timeout: 20_000 });
    expect(typeof sale.id).toBe("string");
    expect(String(sale.receipt_no)).toMatch(/^#\d+$/);

    // Ekrandagi chek raqami = server raqami.
    await expect(page.locator("div.tabular", { hasText: "Чек №" })).toContainText(sale.receipt_no);
    // auto_print o'chiq (standart) — o'zi chop etmaydi.
    expect(await printedList(page)).toHaveLength(0);

    // ── Qo'lda chop etish: ASL chek ──
    const printBtn = page.getByTestId("pos-print");
    await expect(printBtn).toHaveText(/Печать чека/);
    await printBtn.click();
    await expect(page.getByTestId("print-status")).toHaveText("Чек напечатан", { timeout: 20_000 });
    const first = await printedList(page);
    expect(first).toHaveLength(1);
    expect(first[0].kind).toBe("html");
    expect(first[0].copy).toEqual({ kind: "ORIGINAL" });
    expect(first[0].html).toContain(sale.receipt_no);
    expect(first[0].html).toContain("#");
    expect(first[0].html).not.toContain("КОПИЯ");
    // Printer holati sotuvga ta'sir qilmaydi — "Новая продажа" ishlaydi.
    await expect(printBtn).toHaveText(/Печать копии/);
    await page.getByRole("button", { name: /Новая продажа/ }).click();
    await expect(page.getByText("Продажа успешно завершена")).toHaveCount(0);

    // ── Sotuvlarim: shu sotuv qatori (ochiq smena talabisiz), qolgani haqiqiy backend ──
    const row = {
      id: sale.id, receipt_no: sale.receipt_no, sold_at: sale.sold_at, method: "cash",
      item_count: 1, total: Number(sale.total),
    };
    await page.route(/\/api\/v1\/sales\?limit=100/, (r) =>
      r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([row]) }));
    await page.route(/\/api\/v1\/sales\/summary/, (r) =>
      r.fulfill({ status: 200, contentType: "application/json",
                  body: JSON.stringify({ count: 1, total: row.total, by_method: { cash: row.total } }) }));
    await page.goto(`${POS}/#/sotuvlarim`);
    const reprint = page.getByTestId("sotuvlarim-print");
    await expect(reprint).toBeVisible({ timeout: 20_000 });
    // Bu qurilmada ASL chek chop etilgan — tugma nusxa deydi.
    await expect(reprint).toHaveText(/Печать копии/);
    const before = (await printedList(page)).length; // sahifa qayta yuklangan bo'lsa 0
    await reprint.click();
    await expect(page.getByTestId("print-status")).toHaveText("Копия #1 напечатана", { timeout: 20_000 });
    const after = await printedList(page);
    expect(after).toHaveLength(before + 1);
    const copy = after[after.length - 1];
    expect(copy.copy).toEqual({ kind: "REPRINT", no: 1 });
    expect(copy.html).toContain("*** КОПИЯ #1 ***");
    expect(copy.html).toContain(sale.receipt_no);
  });
});
