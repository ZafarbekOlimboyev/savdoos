import { Page, expect } from "@playwright/test";

export const MANAGER = "http://localhost:5198";
export const POS = "http://localhost:5199";

/** Deterministik muhit: til RU, eski sessiya tozalanadi. */
export async function freshContext(page: Page) {
  await page.addInitScript(() => {
    try {
      localStorage.setItem("savdoos_lang", "ru");
      localStorage.removeItem("savdoos-auth");
    } catch {
      /* ignore */
    }
  });
}

/** Manager: telefon+parol bilan kirish (demo admin). */
export async function managerLogin(page: Page) {
  await freshContext(page);
  await page.goto(`${MANAGER}/#/login`);
  const phone = page.locator("input").first();
  await phone.fill("+998901234567");
  await page.locator('input[type="password"]').fill("demo1234");
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page.getByText("Панель управления")).toBeVisible();
}

/** POS: PIN 1111 (demo kassir Dilnoza). Bitta kompaniya — do'kon kodi shart emas. */
export async function posLogin(page: Page) {
  await freshContext(page);
  await page.goto(`${POS}/#/login`);
  await expect(page.getByText("Введите PIN-код")).toBeVisible();
  for (const d of ["1", "1", "1", "1"]) {
    await page.getByRole("button", { name: d, exact: true }).first().click();
  }
  // Katalog ochilishi = login muvaffaqiyatli
  await expect(page.getByPlaceholder(/поиск|F2/i).or(page.getByText("Онлайн"))).toBeVisible({ timeout: 20_000 });
}
