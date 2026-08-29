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

  test("Server xatosi RU tilga tarjima qilinadi (noto'g'ri parol)", async ({ page }) => {
    // Til RU. Noto'g'ri parol -> server "Telefon yoki parol noto'g'ri" (uz) qaytaradi,
    // ekranda RU tarjimasi ko'rinishi kerak (translateServerError).
    await page.addInitScript(() => {
      try { localStorage.setItem("savdoos_lang", "ru"); localStorage.removeItem("savdoos-auth"); } catch { /* */ }
    });
    await page.goto(`${MANAGER}/#/login`);
    await page.locator("input").first().fill("+998901234567");
    await page.locator('input[type="password"]').fill("noto-gri-parol");
    await page.getByRole("button", { name: "Войти" }).click();
    await expect(page.getByText("Неверный телефон или пароль")).toBeVisible({ timeout: 10_000 });
    // O'zbekcha asl matn ekranda QOLMASLIGI kerak
    await expect(page.getByText("Telefon yoki parol")).toHaveCount(0);
  });

  test("Kirim: yangi mahsulotga barcode (dona) / PLU (kg) majburiy + avto-kategoriya", async ({ page }) => {
    await managerLogin(page);
    await page.goto(`${MANAGER}/#/xaridlar`);
    await page.getByRole("button", { name: /Новый приход/ }).click();
    await page.getByRole("button", { name: "Добавить товар" }).click();

    // Yangi nom (katalogda "Suv 1L" bor -> "suv" so'zi orqali kategoriya taxmin qilinadi)
    const name = page.getByPlaceholder("Название товара");
    await name.fill("Suv 1L Premium");
    await name.blur();

    // Kategoriya AVTO to'lgan bo'lishi kerak (bo'sh "" emas)
    const catSel = page.locator('main select').filter({ hasText: "— категория —" }).first();
    await expect(catSel).not.toHaveValue("", { timeout: 10_000 });

    // Narx/miqdor to'ldiramiz — kod tekshiruvigacha yetib borish uchun
    const nums = page.locator('main input[placeholder="0"]');
    await nums.nth(0).fill("5000");
    await nums.nth(1).fill("7000");
    await nums.nth(2).fill("10");

    // 1) dona + barcode bo'sh -> tasdiqlashda xato
    const confirm = page.getByTitle("Подтвердить");
    await confirm.click();
    await expect(page.getByText("Введите или отсканируйте штрих-код")).toBeVisible();

    // 2) birlik kg -> katak PLU'ga aylanadi, PLU'siz yana xato
    await page.locator('main select:has(option[value="kg"])').selectOption("kg");
    await expect(page.getByPlaceholder("PLU (обяз.)")).toBeVisible();
    await confirm.click();
    await expect(page.getByText("Введите PLU код весов")).toBeVisible();

    // 3) PLU kiritilgach tasdiqlanadi va kirim saqlanadi
    await page.getByPlaceholder("PLU (обяз.)").fill("4501");
    await confirm.click();
    await expect(page.getByText("Введите PLU код весов")).toHaveCount(0);
    await page.getByRole("button", { name: "Сохранить приход" }).click();
    await expect(page.getByText("Приходные документы").first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/KIR-\d+/).first()).toBeVisible();
  });
});
