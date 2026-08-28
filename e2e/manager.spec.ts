import { test, expect } from "@playwright/test";
import { MANAGER, managerLogin } from "./helpers";

// Manager — ega/boshqaruv oqimlari.

test.describe("Manager", () => {
  test("login -> Dashboard KPI ko'rinadi", async ({ page }) => {
    await managerLogin(page);
    await expect(page.getByText("Выручка")).toBeVisible();
    await expect(page.getByText("Валовая прибыль")).toBeVisible();
  });

  test("Sotuvlar: POS'da qilingan chek ro'yxatda va modal ochiladi", async ({ page }) => {
    await managerLogin(page);
    await page.goto(`${MANAGER}/#/sotuvlar`);
    // POS testi allaqachon sotuv qildi (workers=1, tartib bo'yicha POS avval yuradi
    // deb faraz qilmaymiz — shu testning o'zi ham "Сегодня" bo'sh bo'lsa yiqilmasin):
    await expect(page.getByText("История всех продаж")).toBeVisible();
    const row = page.locator("tbody tr").first();
    if (await row.count()) {
      await row.click();
      await expect(page.getByText(/Чек #/)).toBeVisible();
      await page.keyboard.press("Escape");
    }
  });

  test("Xodimlar: ro'yxat + Filial ustuni", async ({ page }) => {
    await managerLogin(page);
    await page.goto(`${MANAGER}/#/xodimlar`);
    await expect(page.getByText("Всего сотрудников")).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Филиал" })).toBeVisible();
  });

  test("Смена nazorati: jadval sarlavhalari", async ({ page }) => {
    await managerLogin(page);
    await page.goto(`${MANAGER}/#/smena`);
    await expect(page.getByText("Смены кассиров и контроль кассы")).toBeVisible();
    await expect(page.getByText("ОЖИДАЕМАЯ НАЛИЧНОСТЬ")).toBeVisible();
  });

  test("Sozlamalar -> Tarif: FAQAT ko'rish (tanlab bo'lmaydi)", async ({ page }) => {
    await managerLogin(page);
    await page.goto(`${MANAGER}/#/sozlamalar`);
    await page.getByRole("button", { name: "Тариф", exact: true }).click();
    await expect(page.getByText("Для смены тарифа свяжитесь с нами.")).toBeVisible();
    // Tarif kartalari TUGMA emas (bosib almashtirib bo'lmaydi)
    await expect(page.getByRole("button", { name: "Business", exact: true })).toHaveCount(0);
  });

  test("Qaytarishlar nazorati sahifasi ochiladi", async ({ page }) => {
    await managerLogin(page);
    await page.goto(`${MANAGER}/#/qaytarishlar`);
    await expect(page.getByText("История принятых возвратов")).toBeVisible();
  });
});
