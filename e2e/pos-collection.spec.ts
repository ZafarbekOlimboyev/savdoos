import { test, expect } from "@playwright/test";
import { posLogin, POS } from "./helpers";

// POS — inkassa (TILL -> SAFE). Manzil SEYF AYNAN tanlanadi; server sukut bo'yicha seyf
// TANLAMAYDI va seyf yo'q bo'lsa bir oyoqli OUT yozilmasin.
//
// e2e backend SQLite'da (cash quyi tizimi YO'Q), shu bois oqim tarmoq javobini almashtirib
// sinaladi — server holatiga bog'liq emas.

const SAFES = "**/api/v1/safes**";
const TILLS = "**/api/v1/tills**";
const SHIFT = "44444444-4444-4444-4444-444444444444";
const BR = "33333333-3333-3333-3333-333333333333";
const S1 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
const S2 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb";

function acct(id: string, code: string, type: "TILL" | "SAFE") {
  return { id, branch_id: BR, type, code, label: null, terminal_id: null,
           currency: "UZS", status: "ACTIVE", active: true };
}

/** Ochiq smenali POS holatini taqlid qiladi va berilgan seyflar ro'yxatini beradi. */
async function openShiftWith(page: any, safes: unknown[]) {
  await page.route(TILLS, (r: any) =>
    r.fulfill({ status: 200, contentType: "application/json",
                body: JSON.stringify([acct("11111111-1111-1111-1111-111111111111", "TILL-01", "TILL")]) }));
  await page.route(SAFES, (r: any) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(safes) }));
  await page.route("**/api/v1/shifts/current", (r: any) =>
    r.fulfill({ status: 200, contentType: "application/json",
                body: JSON.stringify({ id: SHIFT, opened_at: new Date().toISOString(), opening_cash: 100000 }) }));
  await page.route(`**/api/v1/shifts/${SHIFT}/summary`, (r: any) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      opening: 100000, total_sales: 0, receipts: 0, by_method: {}, naqd_sales: 0,
      payin: 0, payout: 0, expected: 100000, opened_at: new Date().toISOString(), ops: [] }) }));
  await posLogin(page);
  await page.goto(`${POS}/#/smena`);
  await expect(page.getByTestId("cashop-collection")).toBeVisible({ timeout: 20_000 });
}

function captureCash(page: any, sink: { body: any }) {
  return page.route(`**/api/v1/shifts/${SHIFT}/cash`, async (route: any) => {
    sink.body = JSON.parse(route.request().postData() || "{}");
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
  });
}

test.describe("POS — inkassa (TILL -> SAFE)", () => {
  // A) 0 SEYF -> amal bloklanadi, hech qanday so'rov ketmaydi
  test("A: 0 seyf -> inkassa bloklanadi", async ({ page }) => {
    await openShiftWith(page, []);
    await page.getByTestId("cashop-collection").click();
    await expect(page.getByTestId("safe-none")).toBeVisible();
    await expect(page.getByTestId("cashop-submit")).toBeDisabled();
    await expect(page.getByTestId("safe-select")).toHaveCount(0);
  });

  // B) 1 SEYF -> ko'rinadi/oldindan tanlanadi, LEKIN aniq UUID yuboriladi
  test("B: 1 seyf -> aynan safe UUID yuboriladi", async ({ page }) => {
    await openShiftWith(page, [acct(S1, "SAFE-01", "SAFE")]);
    await page.getByTestId("cashop-collection").click();
    await expect(page.getByTestId("safe-single")).toBeVisible();

    const sink: { body: any } = { body: null };
    await captureCash(page, sink);
    await page.locator('input[placeholder]').nth(0).fill("40000");
    await page.getByTestId("cashop-submit").click();
    await expect.poll(() => sink.body?.destination_safe_id).toBe(S1);
    expect(sink.body.type).toBe("collection");
    expect(sink.body.amount).toBe(40000);
  });

  // C) 2 SEYF -> birinchisi AVTOMATIK tanlanmaydi
  test("C: 2 seyf -> avto tanlash YO'Q, operator tanlaydi", async ({ page }) => {
    await openShiftWith(page, [acct(S1, "SAFE-01", "SAFE"), acct(S2, "SAFE-02", "SAFE")]);
    await page.getByTestId("cashop-collection").click();
    const sel = page.getByTestId("safe-select");
    await expect(sel).toBeVisible();
    await expect(sel).toHaveValue("");
    await expect(page.getByTestId("cashop-submit")).toBeDisabled();

    const sink: { body: any } = { body: null };
    await captureCash(page, sink);
    await sel.selectOption(S2);
    await page.locator('input[placeholder]').nth(0).fill("25000");
    await expect(page.getByTestId("cashop-submit")).toBeEnabled();
    await page.getByTestId("cashop-submit").click();
    await expect.poll(() => sink.body?.destination_safe_id).toBe(S2);
  });

  // Boshqa amallarda seyf so'ralmaydi (inkassa UI faqat inkassada chiqadi)
  test("payin/expense seyf tanlashni talab qilmaydi", async ({ page }) => {
    await openShiftWith(page, []);
    for (const k of ["payin", "payout", "expense"]) {
      await page.getByTestId(`cashop-${k}`).click();
      await expect(page.getByTestId("safe-none")).toHaveCount(0);
      await expect(page.getByTestId("cashop-submit")).toBeEnabled();
    }
  });
});
