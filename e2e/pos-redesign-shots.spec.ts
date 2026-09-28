// Phase 7 — kassa redizayni: HAQIQIY brauzer skrinshotlari + klaviatura shartnomasi.
//
// ⚠️  BU SPEC BIZNES XULQINI O'ZGARTIRMAYDI: u faqat tayyor UI'ni suratga oladi va
//     MAVJUD yorliqlar (F2/F4/F6/F7) hamon ishlashini tasdiqlaydi. Maketdagi yorliq
//     yozuvlari (F3/F5–F11/Enter) ATAYLAB sinalmaydi — ular vizual namuna edi.
import { expect, test } from "@playwright/test";
import { POS, posBootstrap } from "./helpers";

const SHOTS = "test-results/redesign";

/** Katalogni ochib, berilgan nomdagi mahsulotni savatga qo'shadi va katalogni yopadi. */
async function addProduct(page: import("@playwright/test").Page, name: string) {
  await page.getByTestId("open-catalog").click();
  await expect(page.getByTestId("catalog-overlay")).toBeVisible();
  await page.getByText(name, { exact: true }).first().click();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("catalog-overlay")).toHaveCount(0);
}

test.describe("Phase 7 kassa redizayni", () => {
  test.beforeEach(async ({ page }) => {
    await posBootstrap(page);
    await page.setViewportSize({ width: 1366, height: 768 });
  });

  test("B: bo'sh savat — 1366x768", async ({ page }) => {
    await expect(page.getByTestId("cart-list")).toBeVisible();
    // Doimiy mahsulot gridi BO'LMASLIGI shart (asosiy talab)
    await expect(page.getByTestId("catalog-product")).toHaveCount(0);
    // Pastda AYNAN to'rt amal
    await expect(page.locator("footer button")).toHaveCount(4);
    // To'lov tugmasi ko'rinadi (1366x768 da kesilmaydi)
    await expect(page.getByTestId("pay-go")).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/B-empty-1366x768.png` });
  });

  test("C: katalog vaqtinchalik ochiladi", async ({ page }) => {
    await page.getByTestId("open-catalog").click();
    await expect(page.getByTestId("catalog-overlay")).toBeVisible();
    await expect(page.getByTestId("catalog-product").first()).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/C-catalog-1366x768.png` });
    // Escape yopadi va savat ekrani QAYTADI
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("catalog-overlay")).toHaveCount(0);
    await expect(page.getByTestId("cart-list")).toBeVisible();
  });

  test("A: 4 qatorli savat — 1366x768 va boshqa o'lchamlar", async ({ page }) => {
    for (const n of ["Coca-Cola 0.5L", "Non", "Kefir", "Pepsi 0.5L"]) await addProduct(page, n);
    await expect(page.getByTestId("cart-row")).toHaveCount(4);
    await expect(page.getByTestId("pay-go")).toBeEnabled();

    await page.screenshot({ path: `${SHOTS}/A-cart4-1366x768.png` });
    for (const [w, h] of [[1440, 900], [1920, 1080]] as const) {
      await page.setViewportSize({ width: w, height: h });
      // To'lov tugmasi HAR o'lchamda ko'rinadi (sahifa umuman scroll qilinmaydi)
      await expect(page.getByTestId("pay-go")).toBeVisible();
      await page.screenshot({ path: `${SHOTS}/A-cart4-${w}x${h}.png` });
    }
  });

  test("MAVJUD yorliqlar saqlangan: F2 qidiruv, F4 to'lov, F6/F7 savat", async ({ page }) => {
    await addProduct(page, "Non");

    // F2 — qidiruvga fokus
    await page.keyboard.press("F2");
    await expect(page.getByTestId("pos-search")).toBeFocused();

    // F4 — to'lov oynasi (savat bo'sh emas)
    await page.keyboard.press("F4");
    await expect(page.getByText(/СУММА ОПЛАТЫ/i)).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByText(/СУММА ОПЛАТЫ/i)).toHaveCount(0);

    // F6 — yangi (parallel) savat: tab paydo bo'ladi, faol savat BO'SH
    await page.keyboard.press("F6");
    await expect(page.getByTestId("cart-tab")).toHaveCount(2);
    await expect(page.getByTestId("cart-row")).toHaveCount(0);

    // F7 — keyingi savatga o'tish: birinchi savat qatori QAYTADI
    await page.keyboard.press("F7");
    await expect(page.getByTestId("cart-row")).toHaveCount(1);
  });

  test("pastki panel: tanlovsiz o'chirilgan, tanlangach ishlaydi", async ({ page }) => {
    await addProduct(page, "Non");
    // Qator tanlanmagan — «Miqdor» va «Qatorni olib tashlash» O'CHIRILGAN
    await expect(page.getByTestId("act-qty")).toBeDisabled();
    await expect(page.getByTestId("act-remove")).toBeDisabled();

    await page.getByTestId("cart-row").first().click();
    await expect(page.getByTestId("act-qty")).toBeEnabled();
    await expect(page.getByTestId("act-remove")).toBeEnabled();

    // Qatorni olib tashlash — AYNAN tanlangan qator ketadi
    await page.getByTestId("act-remove").click();
    await expect(page.getByTestId("cart-row")).toHaveCount(0);
  });

  test("o'ng paneldagi usul MAVJUD to'lov oynasini o'sha usul bilan ochadi", async ({ page }) => {
    await addProduct(page, "Non");
    const total = (await page.getByTestId("cart-total").innerText()).replace(/\D/g, "");
    await page.getByTestId("pay-cash").click();
    await expect(page.getByText(/СУММА ОПЛАТЫ/i)).toBeVisible();
    // Naqd qatori avtomatik jamiga to'ldirilgan (chip bosilgandek) — ikkinchi to'lov yo'li YO'Q
    await expect(page.locator(`input[inputmode="numeric"][value="${total}"]`)).toHaveCount(1);
  });
});
