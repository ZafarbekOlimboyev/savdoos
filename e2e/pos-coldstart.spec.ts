import { test, expect } from "@playwright/test";
import { POS, freshContext, posBootstrap, uiLogout } from "./helpers";

// POS SOVUQ START — kassir autentifikatsiyasining to'liq hayot sikli.
//
// ⚠️  NEGA BU TEST BOR. PIN login endi `employee_id` talab qiladi (bir so'rov = bitta
//     bcrypt), ya'ni POS avval kassirni TANLASHI kerak. Kassirlar ro'yxati esa
//     ANONIM olinmaydi. Shu sababli "ro'yxat uchun token kerak, token uchun ro'yxat
//     kerak" degan AYLANMA BOG'LIQLIK xavfi paydo bo'ladi.
//
//     Sikl YO'Q, chunki bootstrap kredensiali BOSHQA: `POST /auth/login/password`
//     telefon + parol bilan ishlaydi va `employee_id` ni ham, ro'yxatni ham
//     TALAB QILMAYDI. Quyidagi testlar aynan shuni har bir holat uchun isbotlaydi.
//
// ⚠️  KESH XAVFSIZLIK CHEGARASI EMAS. localStorage'dagi ro'yxat faqat QULAYLIK:
//     serverda har login `employee_id` ni kompaniya/faollik/imtiyoz bo'yicha
//     mustaqil tekshiradi. Buni "soxta kassir" testi isbotlaydi.

const ADMIN_PHONE = "+998901234567";

test.describe("POS sovuq start", () => {
  test("A+B: butunlay toza qurilma — sozlanmagan holat ko'rsatiladi, parol yo'li ochiq", async ({ page }) => {
    await freshContext(page);
    await page.goto(`${POS}/#/login`);

    // Toza qurilmada PIN-pad KO'RSATILMAYDI (tanlanadigan kassir yo'q).
    await expect(page.getByText("Устройство ещё не настроено")).toBeVisible();
    await expect(page.getByText("Введите PIN-код")).toHaveCount(0);

    // Bootstrap yo'li mavjud va u `employee_id` TALAB QILMAYDI.
    await expect(page.getByRole("button", { name: "Администратор? Вход по паролю" })).toBeVisible();
  });

  test("A: aktivatsiya -> chiqish -> kassir tanlash -> PIN -> savdo oqimi", async ({ page }) => {
    await freshContext(page);

    // 1) Ega paroli bilan aktivatsiya: ro'yxat shu yerda keshlanadi.
    await posBootstrap(page);

    // 2) Ega chiqadi (F holati) — kesh SAQLANADI.
    await uiLogout(page);
    await expect(page.getByText("Выберите кассира")).toBeVisible({ timeout: 15_000 });

    // 3) Ega ro'yxatda KO'RINMAYDI — u PIN yo'lidan kira olmaydi.
    await expect(page.getByRole("button", { name: /Sardor/ })).toHaveCount(0);

    // 4) Kassir tanlanadi -> PIN -> katalog.
    await page.getByRole("button", { name: /Dilnoza/ }).click();
    await expect(page.getByText("Введите PIN-код")).toBeVisible();
    for (const d of ["1", "1", "1", "1"]) {
      await page.getByRole("button", { name: d, exact: true }).first().click();
    }
    await expect(page.getByPlaceholder(/поиск|F2/i).or(page.getByText("Онлайн"))).toBeVisible({ timeout: 20_000 });

    // 5) Kassir HAQIQIY savdo oqimiga kira oladi.
    await page.getByText("Suv 1L", { exact: true }).first().click();
    await expect(page.getByText("Корзина")).toBeVisible();
  });

  test("C: token muddati tugadi — kesh saqlanadi, kassir qayta kira oladi", async ({ page }) => {
    await freshContext(page);
    await posBootstrap(page);
    await uiLogout(page);

    // Kassir kiradi
    await page.getByRole("button", { name: /Dilnoza/ }).click();
    for (const d of ["1", "1", "1", "1"]) {
      await page.getByRole("button", { name: d, exact: true }).first().click();
    }
    await expect(page.getByPlaceholder(/поиск|F2/i).or(page.getByText("Онлайн"))).toBeVisible({ timeout: 20_000 });

    // Token yaroqsiz bo'lib qoladi (muddat tugashi / server tomonda bekor qilinishi).
    await page.evaluate(() => localStorage.removeItem("savdoos-auth"));
    await page.reload();

    // Qurilma "sozlanmagan" holatga QAYTMAYDI — ro'yxat joyida, kassir o'zi kira oladi.
    await expect(page.getByText("Выберите кассира")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Устройство ещё не настроено")).toHaveCount(0);
  });

  test("E: kassir almashtirish — ro'yxatga qaytib, boshqa xodim tanlanadi", async ({ page }) => {
    await freshContext(page);
    await posBootstrap(page);
    await uiLogout(page);

    await page.getByRole("button", { name: /Dilnoza/ }).click();
    await expect(page.getByText("Введите PIN-код")).toBeVisible();

    // "Boshqa kassir" — ro'yxatga qaytish
    await page.getByRole("button", { name: "Другой кассир" }).click();
    await expect(page.getByText("Выберите кассира")).toBeVisible();

    // Ro'yxatda PIN'i bor boshqa xodimlar ham bor (menejer/omborchi — imtiyozsiz).
    await expect(page.getByRole("button", { name: /Dilnoza/ })).toBeVisible();
  });

  test("kesh XAVFSIZLIK CHEGARASI EMAS: soxta employee_id server tomonda rad etiladi", async ({ page }) => {
    await freshContext(page);
    await posBootstrap(page);
    await uiLogout(page);
    await expect(page.getByText("Выберите кассира")).toBeVisible({ timeout: 15_000 });

    // Hujumchi keshdagi ro'yxatni O'ZI o'ylab topgan xodimga almashtiradi.
    // `server`/`code` doirasi HAQIQIY keshdan olinadi — ya'ni kesh tekshiruvi
    // chetlab o'tilgan, endi butun yuk SERVER tomonda.
    await page.evaluate(() => {
      const raw = JSON.parse(localStorage.getItem("savdoos_pin_roster") || "{}");
      raw.items = [{ id: "00000000-0000-4000-8000-000000000001", full_name: "SOXTA Kassir" }];
      localStorage.setItem("savdoos_pin_roster", JSON.stringify(raw));
    });
    await page.reload();

    await page.getByRole("button", { name: /SOXTA Kassir/ }).click();
    await expect(page.getByText("Введите PIN-код")).toBeVisible();
    for (const d of ["1", "1", "1", "1"]) {
      await page.getByRole("button", { name: d, exact: true }).first().click();
    }
    // Katalog OCHILMAYDI — server 401 qaytaradi, POS login ekranida qoladi.
    await expect(page.getByPlaceholder(/поиск|F2/i)).toHaveCount(0);
    await expect(page).toHaveURL(/#\/login/);
  });

  test("xato do'kon kodi terilgan qurilma aktivatsiyadan keyin O'ZINI TUZATADI", async ({ page }) => {
    // ⚠️  Ilgari: sozlamaga xato kod terilsa, parol logini baribir o'tardi (server
    //     kodni tekshirmaydi), lekin keyin HAR BIR PIN login o'sha xato kod bilan
    //     ketib DOIM 401 berardi — kassirlar ro'yxati esa ekranda to'g'ri turardi.
    await freshContext(page);
    await page.goto(`${POS}/#/login`);
    await page.getByTitle(/Настройки сервера|server/i).click();
    await page.getByPlaceholder("Код магазина").fill("butunlay-boshqa-kod");
    await page.getByRole("button", { name: "Сохранить" }).click();

    await posBootstrap(page);          // parol bilan aktivatsiya → kod serverdan tuzatiladi
    await uiLogout(page);

    await page.getByRole("button", { name: /Dilnoza/ }).click();
    for (const d of ["1", "1", "1", "1"]) {
      await page.getByRole("button", { name: d, exact: true }).first().click();
    }
    await expect(page.getByPlaceholder(/поиск|F2/i).or(page.getByText("Онлайн"))).toBeVisible({ timeout: 20_000 });
  });

  test("anonim chaqiruvchi xodimlar ro'yxatini OLA OLMAYDI", async ({ request }) => {
    // Backend e2e/start_backend.py orqali shu manzilda turadi (playwright.config.ts).
    const api = "http://127.0.0.1:8000/api/v1";

    for (const path of ["/auth/pin-roster", "/employees", "/auth/pin-roster?company_code=demo"]) {
      const r = await request.get(api + path);
      expect([401, 403], `${path} -> ${r.status()}`).toContain(r.status());
      const body = await r.text();
      expect(body).not.toContain("Dilnoza");
      expect(body).not.toContain(ADMIN_PHONE);
    }
  });
});
