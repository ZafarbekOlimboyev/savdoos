import { test, expect } from "@playwright/test";
import { posLogin } from "./helpers";

// POS — kassirning asosiy ish oqimlari (eng kritik sikllar).

test.describe("POS", () => {
  test("PIN login -> katalog ochiladi", async ({ page }) => {
    await posLogin(page);
    await expect(page.getByText("Oltin Do'kon")).toBeVisible();
  });

  test("to'liq sotuv: mahsulot -> naqd -> muvaffaqiyat", async ({ page }) => {
    await posLogin(page);
    // Katalogdan Suv 1L (qoldiq 120) — kartani bosamiz
    await page.getByText("Suv 1L", { exact: true }).first().click();
    await expect(page.getByText("Корзина")).toBeVisible();
    await page.getByRole("button", { name: /ЗАВЕРШИТЬ ОПЛАТУ/ }).click();
    // To'lov oynasi: usul tanlanmaguncha "Завершить оплату" o'chiq bo'lishi SHART
    await expect(page.getByText("СУММА ОПЛАТЫ")).toBeVisible();
    const finish = page.getByRole("button", { name: "Завершить оплату", exact: true });
    await expect(finish).toBeDisabled();
    await page.getByRole("button", { name: "Наличные", exact: true }).last().click();
    await expect(finish).toBeEnabled();
    await finish.click();
    // Muvaffaqiyat: chek raqami + "Новая продажа"
    await expect(page.getByText("Продажа успешно завершена")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("button", { name: /Новая продажа/ })).toBeVisible();
  });

  test("smena: ochish -> sotuv kutilganga qo'shiladi -> kam sanash farqi", async ({ page }) => {
    await posLogin(page);
    await page.goto("http://localhost:5199/#/smena");
    // Ochish (100 000)
    await page.getByPlaceholder("0").fill("100000");
    await page.getByRole("button", { name: "Открыть смену" }).click();
    await expect(page.getByText("Ожидаемая наличность")).toBeVisible({ timeout: 15_000 });
    // Yopish: 95 000 sanadik -> farq -5 000 ko'rinishi kerak
    await page.getByRole("button", { name: /Закрыть смену/ }).first().click();
    await expect(page.getByText("Пересчитанная наличность")).toBeVisible();
    await page.locator('div[style*="position: fixed"] input, input').last().fill("95000");
    await page.getByRole("button", { name: /Закрыть смену и Z-отчёт/ }).click();
    await expect(page.getByText("Смена закрыта")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/−\s?5\s?000/)).toBeVisible();
  });

  test("qaytarishlar sahifasi ochiladi va so'nggi cheklar ko'rinadi", async ({ page }) => {
    await posLogin(page);
    await page.goto("http://localhost:5199/#/qaytarishlar");
    await expect(page.getByText("ПОСЛЕДНИЕ ПРОДАЖИ")).toBeVisible();
  });
});
