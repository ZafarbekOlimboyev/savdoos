import { test, expect } from "@playwright/test";
import { managerLogin, posLogin, MANAGER, POS } from "./helpers";

// §23 — NAQD qarz to'lovi FAQAT ochiq smenada.
//
// Server smenasiz naqd to'lovni AYNAN kassa (TILL/SAFE) ko'rsatilmasa RAD ETADI, mijozda esa
// kassa tanlash oynasi YO'Q. Ilgari bu holat faqat urinishdan KEYIN, tushunarsiz texnik xato
// bo'lib chiqardi ("CASH_CUSTODY_ACCOUNT_REQUIRED_AFTER_CUTOVER: 'debt_payment': ...").
// Endi shart OLDINDAN va do'kon egasi tilida tushuntiriladi, tugma esa o'chiq turadi.

const CUSTOMERS = "**/api/v1/customers**";

const CUSTOMER = {
  id: "77777777-7777-7777-7777-777777777777",
  code: "M001",
  full_name: "Qarzdor Mijoz",
  phone: null,
  credit_balance: 250000,
  loyalty_points: 0,
  group_id: null,
  is_active: true,
};

/** Mijozlar ro'yxatini almashtiradi (e2e backend SQLite — cash quyi tizimi yo'q). */
async function stubCustomers(page: any) {
  // Tafsilot (aniqroq naqsh) AVVAL ro'yxatdan oldin qo'yiladi.
  await page.route("**/api/v1/customers/*/detail", (r: any) =>
    r.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ transactions: [], payments: [] }),
    }));
  // Ro'yxat — YALANG'OCH massiv (screen `Customer[]` kutadi)
  await page.route(CUSTOMERS, (r: any) =>
    r.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify([CUSTOMER]),
    }));
}

/** Mijozni tanlab, "Qarzni yopish" modalini ochadi. */
async function openPayModal(page: any, base: string) {
  await page.goto(`${base}/#/mijozlar`);
  await page.getByText(CUSTOMER.full_name).first().click();
  await page.getByRole("button", { name: /Погасить долг/i }).first().click();
}

test.describe("Naqd qarz to'lovi — smena sharti", () => {
  // A) SMENASIZ (Manager: smena tushunchasi umuman yo'q) -> tugma O'CHIQ + tushuntirish
  test("A: smenasiz -> tugma o'chiq, sabab tushuntiriladi", async ({ page }) => {
    await stubCustomers(page);
    await managerLogin(page);
    await openPayModal(page, MANAGER);

    // Sabab KO'RINADI va u texnik xato kodi EMAS
    const notice = page.getByTestId("pay-needs-shift");
    await expect(notice).toBeVisible();
    await expect(notice).not.toContainText("CASH_CUSTODY");
    await expect(notice).toContainText(/смена|smena/i);

    // Tugma O'CHIQ — ya'ni server xatosigacha BORMAYDI
    await expect(page.getByTestId("pay-submit")).toBeDisabled();
  });

  // B) OCHIQ SMENA -> odatiy oqim ishlaydi
  //
  // Smena identity'si REAL oqim bilan hosil qilinadi (POS Smena ekranida kassa tanlab ochish) —
  // localStorage'ga qo'lda yozib bo'lmaydi, chunki auth store login paytida identity'ni ATAYLAB
  // tozalaydi (RC13 — boshqa kassirning kassasi meros qolmasin).
  test("B: ochiq smena -> to'lov yuboriladi", async ({ page }) => {
    const TILL = "11111111-1111-1111-1111-111111111111";
    const BR = "33333333-3333-3333-3333-333333333333";

    await page.route("**/api/v1/tills**", (r: any) =>
      r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([{
        id: TILL, branch_id: BR, type: "TILL", code: "TILL-01", label: "TILL-01",
        terminal_id: null, currency: "UZS", status: "ACTIVE", active: true }]) }));
    const SH = "44444444-4444-4444-4444-444444444444";
    // /shifts/current DINAMIK: ochishdan OLDIN smena yo'q, KEYIN ochiq. Aks holda ekran
    // ochish formasida qolib ketardi va `setShiftIdentity` HECH QACHON chaqirilmasdi.
    let opened = false;
    await page.route("**/api/v1/shifts/current", (r: any) =>
      r.fulfill({ status: 200, contentType: "application/json",
                  body: opened
                    ? JSON.stringify({ id: SH, opened_at: new Date().toISOString(), opening_cash: 0 })
                    : "null" }));
    await page.route(`**/api/v1/shifts/${SH}/summary`, (r: any) =>
      r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        opening: 0, total_sales: 0, receipts: 0, by_method: {}, naqd_sales: 0,
        payin: 0, payout: 0, expected: 0, opened_at: new Date().toISOString(), ops: [] }) }));
    await page.route("**/api/v1/shifts/open", (r: any) => {
      opened = true;
      return r.fulfill({ status: 200, contentType: "application/json",
                         body: JSON.stringify({ id: SH }) });
    });

    // DIQQAT — TARTIB MUHIM: Playwright OXIRGI mos route'ni birinchi ishlatadi.
    // `stubCustomers` keng naqshli ("**/api/v1/customers**") va to'lov URL'iga ham mos keladi,
    // shu bois to'lov route'i UNDAN KEYIN ro'yxatga olinishi shart.
    await stubCustomers(page);

    let sent: any = null;
    await page.route(`**/api/v1/customers/*/payments`, async (r: any) => {
      sent = JSON.parse(r.request().postData() || "{}");
      await r.fulfill({ status: 200, contentType: "application/json", body: "{}" });
    });

    // Smenani HAQIQIY oqim bilan ochamiz -> useShift to'ladi
    await posLogin(page);
    await page.goto(`${POS}/#/smena`);
    await expect(page.getByTestId("shift-open")).toBeVisible({ timeout: 20_000 });
    await page.getByTestId("shift-open").click();

    // Smena ochilgani tasdiqlansin (store to'lgan bo'lsin), keyin mijozlarga o'tamiz.
    await expect(page.getByTestId("shift-open")).toHaveCount(0, { timeout: 20_000 });

    // Hash navigatsiya: sahifa QAYTA YUKLANMAYDI, shu bois smena store'i SAQLANADI.
    await page.goto(`${POS}/#/mijozlar`);
    await page.getByText(CUSTOMER.full_name).first().click();
    await page.getByRole("button", { name: /Погасить долг/i }).first().click();

    // Tushuntirish CHIQMAYDI, tugma FAOL
    await expect(page.getByTestId("pay-needs-shift")).toHaveCount(0);
    await expect(page.getByTestId("pay-submit")).toBeEnabled();

    await page.getByPlaceholder(/сумма|summa/i).first().fill("50000");
    await page.getByTestId("pay-submit").click();
    await expect.poll(() => sent?.amount).toBe(50000);
    expect(sent.method).toBe("cash");
  });
});
