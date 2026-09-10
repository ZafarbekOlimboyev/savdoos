import { Page, expect } from "@playwright/test";

export const MANAGER = "http://localhost:5198";
export const POS = "http://localhost:5199";

/** Deterministik muhit: til RU, qurilma BUTUNLAY toza (sessiya ham, kassir keshi ham). */
export async function freshContext(page: Page) {
  await page.addInitScript(() => {
    try {
      localStorage.setItem("savdoos_lang", "ru");
      // ⚠️  BIR MARTALIK tozalash. `addInitScript` HAR sahifa yuklanishida ishlaydi;
      //     agar tozalash shartsiz bo'lsa, testning o'rtasidagi har reload qurilmani
      //     yana "sozlanmagan" holatga qaytarib, aynan tekshirilayotgan oqimni buzardi.
      if (!sessionStorage.getItem("__e2e_wiped")) {
        sessionStorage.setItem("__e2e_wiped", "1");
        localStorage.removeItem("savdoos-auth");
        // Kassirlar keshi ham tozalanadi — har test QURILMA SOZLANMAGAN holatdan
        // boshlansin. Aks holda testlar "allaqachon sozlangan" holatga suyanib,
        // sovuq startni (fresh install) hech qachon tekshirmasdi.
        localStorage.removeItem("savdoos_pin_roster");
      }
    } catch {
      /* ignore */
    }
  });
}

/**
 * POS qurilmasini AKTIVATSIYA qiladi: ega/admin paroli bilan bir marta kiriladi va
 * kassirlar ro'yxati shu qurilmada keshlanadi.
 *
 * ⚠️  NEGA KERAK. PIN login endi `employee_id` talab qiladi (bitta bcrypt), demak
 *     POS avval kassirni tanlashi kerak. Ro'yxat esa ANONIM olinmaydi — uni faqat
 *     autentifikatsiyalangan chaqiruvchi oladi. Parol bilan kirish esa `employee_id`
 *     talab qilmaydi — shuning uchun aylanma bog'liqlik (circular dependency) YO'Q.
 */
export async function posBootstrap(page: Page) {
  await page.goto(`${POS}/#/login`);
  await expect(page.getByText("Устройство ещё не настроено")).toBeVisible();
  await page.getByRole("button", { name: "Администратор? Вход по паролю" }).click();
  await page.locator("input").first().fill("+998901234567");
  await page.locator('input[type="password"]').fill("demo1234");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  // Admin ichkariga kirdi = /auth/pin-roster chaqirildi va kesh to'ldi.
  await expect(page.getByPlaceholder(/поиск|F2/i).or(page.getByText("Онлайн"))).toBeVisible({ timeout: 20_000 });
}

/**
 * UI orqali chiqish — haqiqiy logout oqimi (store tozalanadi, serverga /auth/logout ketadi).
 *
 * Kassa ekrani ("/") to'liq ekran: yon panel u yerda ko'rinmaydi (Layout.tsx FULLSCREEN).
 * Shu bois yon panel doimiy bo'lgan sahifaga o'tib, "Chiqish" tugmasi bosiladi.
 */
export async function uiLogout(page: Page) {
  await page.goto(`${POS}/#/sotuvlarim`);
  await page.getByText("Выход", { exact: false }).first().click();
  await expect(page).toHaveURL(/#\/login/, { timeout: 15_000 });
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

/**
 * POS: kassir sifatida kirish — SOVUQ STARTDAN boshlab to'liq oqim.
 *   toza qurilma → admin paroli bilan aktivatsiya → sessiya tugadi →
 *   kassirni TANLASH → PIN 1111 (demo kassir Dilnoza) → katalog.
 */
export async function posLogin(page: Page) {
  await freshContext(page);
  await posBootstrap(page);

  // Admin chiqadi (haqiqiy UI oqimi) — kassirlar keshi SAQLANIB qolishi kerak.
  await uiLogout(page);

  await expect(page.getByText("Выберите кассира")).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: /Dilnoza/ }).click();
  await expect(page.getByText("Введите PIN-код")).toBeVisible();
  for (const d of ["1", "1", "1", "1"]) {
    await page.getByRole("button", { name: d, exact: true }).first().click();
  }
  // Katalog ochilishi = login muvaffaqiyatli
  await expect(page.getByPlaceholder(/поиск|F2/i).or(page.getByText("Онлайн"))).toBeVisible({ timeout: 20_000 });
}
