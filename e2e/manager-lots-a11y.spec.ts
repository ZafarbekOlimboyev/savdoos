import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { managerLogin, MANAGER } from "./helpers";

// Manager — PARTIYA EKRANLARI: KLAVIATURA, FOKUS va O'LCHAM isboti (Phase 4B.1).
//
// ⚠️  BU SINOV «ko'rinishi chiroyli» ni emas, ISHLAY OLISHNI o'lchaydi: sichqonchasiz
//     operator amalni bajara oladimi, fokus qayerda turgani KO'RINADIMI va 390px
//     ekranda sahifa yon tomonga SURILADIMI.

const API = "http://127.0.0.1:8000/api/v1";
const uuid = () => crypto.randomUUID();
const iso = (d: Date) => d.toISOString().slice(0, 10);

interface Ctx { tag: string; aId: string; aName: string }
let ctx: Ctx;

async function api(req: APIRequestContext, method: "get" | "post", path: string, token?: string, data?: unknown) {
  const r = await req[method](API + path, {
    headers: token ? { Authorization: "Bearer " + token } : {},
    data: data as any,
  });
  expect(r.ok(), `${method.toUpperCase()} ${path} -> ${r.status()} ${await r.text()}`).toBeTruthy();
  return r.json();
}

test.beforeAll(async ({ request }) => {
  const auth = await api(request, "post", "/auth/login/password", undefined,
    { phone: "+998901234567", password: "demo1234" });
  const token = auth.access_token || auth.token;
  const tag = "A11Y" + Math.random().toString(36).slice(2, 6).toUpperCase();
  const [a] = await api(request, "post", "/products/bulk", token, {
    items: [{ name: `${tag} sut`, sell_price: 12000, buy_price: 7000, unit_code: "dona", stock: 0 }],
  });
  const sups = await api(request, "get", "/suppliers", token);
  const supplierId = sups[0]?.id || (await api(request, "post", "/suppliers", token, { name: "A11Y" })).id;
  await api(request, "post", "/lots/timezone/confirm", token, {});
  const r = await request.post(API + "/lots/enable", {
    headers: { Authorization: "Bearer " + token },
    data: { product_id: a.id, reason: "a11y sinovi", track_expiry: true },
  });
  expect(r.ok() || r.status() === 409, await r.text()).toBeTruthy();
  const soon = new Date(); soon.setDate(soon.getDate() + 4);
  await api(request, "post", "/receiving/commit", token, {
    items: [{ product_id: a.id, qty: 9, unit_cost: 7000, unit: "dona",
              lots: [{ qty: 9, unit_cost: 7000, batch_number: `${tag}-1`, expiry_date: iso(soon) }] }],
    supplier_id: supplierId, payment: "credit", client_uuid: uuid(), source: "manual",
  });
  ctx = { tag, aId: a.id, aName: a.name };
});

/** Sahifa GORIZONTAL surilmasligi — har ekranda bir xil o'lchov. */
async function noSideScroll(page: Page) {
  const overflow = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, "sahifa yon tomonga suriladi").toBeLessThanOrEqual(1);
}

async function open(page: Page, hash: string) {
  await page.goto(`${MANAGER}/#/${hash}`);
  await expect(page.locator("main#main")).toBeVisible();
}

test.describe("Mobil 390px — hamma partiya ekrani", () => {
  test.use({ viewport: { width: 390, height: 780 } });

  test("beshta ekranda ham gorizontal scroll YO'Q va jadval o'rniga kartalar", async ({ page }) => {
    await managerLogin(page);
    for (const hash of ["partiyalar", "muddat", "inventarizatsiya", "hisobdan-chiqarish", "aniqlanmagan-qoldiq"]) {
      await open(page, hash);
      await noSideScroll(page);
    }
    await open(page, "partiyalar");
    await expect(page.locator('[data-testid^="lot-card-"]').first()).toBeVisible();
    await expect(page.locator('[data-testid^="lot-row-"]')).toHaveCount(0);
  });

  test("tafsilot oynasi ham 390px da surilmaydi", async ({ page }) => {
    await managerLogin(page);
    await open(page, "partiyalar");
    await page.locator('[data-testid^="lot-card-"]').first().click();
    await expect(page.getByTestId("lot-drawer")).toBeVisible();
    await noSideScroll(page);
  });

  test("hisobdan chiqarish tasdig'i 390px da to'liq ko'rinadi", async ({ page }) => {
    await managerLogin(page);
    await open(page, "hisobdan-chiqarish");
    await page.getByTestId("wo-product-input").fill(ctx.aName);
    await page.getByTestId(`wo-product-opt-${ctx.aId}`).click();
    const row = page.locator('[data-testid^="wo-lot-"]').first();
    await expect(row).toBeVisible();
    await row.locator("input").fill("1");
    await page.getByTestId("wo-submit").click();
    const box = page.getByTestId("confirm");
    await expect(box).toBeVisible();
    await noSideScroll(page);
    const w = await box.evaluate((el) => el.getBoundingClientRect().width);
    expect(w).toBeLessThanOrEqual(390);
    await page.getByTestId("confirm-cancel").click();
  });
});

test.describe("Desktop 1440px", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("jadval, filtrlar va tafsilot oynasi bir ekranda", async ({ page }) => {
    await managerLogin(page);
    await open(page, "partiyalar");
    await expect(page.locator('[data-testid^="lot-row-"]').first()).toBeVisible();
    await expect(page.getByTestId("lot-search")).toBeVisible();
    await expect(page.getByTestId("f-sort")).toBeVisible();
    await noSideScroll(page);
    await page.locator('[data-testid^="lot-open-"]').first().click();
    await expect(page.getByTestId("lot-drawer")).toBeVisible();
    await noSideScroll(page);
  });
});

test.describe("Klaviatura va fokus", () => {
  test("fokus halqasi KO'RINADI (inline outline:none qaytmasin)", async ({ page }) => {
    await managerLogin(page);
    await open(page, "partiyalar");
    await page.getByTestId("lot-search").focus();
    const ring = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement;
      const st = getComputedStyle(el);
      return { style: st.outlineStyle, width: parseFloat(st.outlineWidth || "0") };
    });
    expect(ring.style).not.toBe("none");
    expect(ring.width).toBeGreaterThanOrEqual(1);
  });

  test("tafsilot oynasi: fokus ICHKARIGA kiradi, TUZOQDA qoladi, Escape yopadi", async ({ page }) => {
    await managerLogin(page);
    await open(page, "partiyalar");
    const opener = page.locator('[data-testid^="lot-open-"]').first();
    await opener.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("lot-drawer")).toBeVisible();

    const inside = () => page.evaluate(() =>
      !!document.querySelector('[data-testid="lot-drawer"]')?.contains(document.activeElement));
    await expect.poll(inside).toBe(true);
    for (let i = 0; i < 25; i++) await page.keyboard.press("Tab");
    expect(await inside(), "Tab oynadan CHIQIB ketdi").toBe(true);

    await page.keyboard.press("Escape");
    await expect(page.getByTestId("lot-drawer")).toHaveCount(0);
    // Fokus qaysi qatordan kelgan bo'lsa — o'sha yerga qaytadi.
    await expect.poll(() => page.evaluate(() =>
      document.activeElement?.getAttribute("data-testid") || "")).toContain("lot-open-");
  });

  test("hisobdan chiqarishni SICHQONCHASIZ bajarib bo'ladi", async ({ page }) => {
    await managerLogin(page);
    await open(page, "hisobdan-chiqarish");
    await page.getByTestId("wo-product-input").focus();
    await page.keyboard.type(ctx.aName);
    const opt = page.getByTestId(`wo-product-opt-${ctx.aId}`);
    await expect(opt).toBeVisible();
    await opt.focus();
    await page.keyboard.press("Enter");

    const qty = page.locator('[data-testid^="wo-qty-"]').first();
    await expect(qty).toBeVisible();
    await qty.focus();
    await page.keyboard.type("1");
    await page.getByTestId("wo-submit").focus();
    await page.keyboard.press("Enter");

    // Tasdiq oynasi ochildi va fokus uning ICHIDA
    await expect(page.getByTestId("confirm")).toBeVisible();
    await expect.poll(() => page.evaluate(() =>
      !!document.querySelector('[data-testid="confirm"]')?.contains(document.activeElement))).toBe(true);
    await page.getByTestId("confirm-ok").focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("writeoff-done")).toBeVisible();
  });

  test("skip-link klaviaturada birinchi to'xtash bo'lib chiqadi", async ({ page }) => {
    await managerLogin(page);
    await open(page, "partiyalar");
    await page.evaluate(() => (document.activeElement as HTMLElement)?.blur());
    await page.keyboard.press("Tab");
    const cls = await page.evaluate(() => document.activeElement?.className || "");
    expect(cls).toContain("skip-link");
  });
});

test.describe("Ekran o'quvchi uchun ma'no", () => {
  test("nishonlar MATN bilan ham gapiradi, jadvalda sarlavha bor", async ({ page }) => {
    await managerLogin(page);
    await open(page, "partiyalar");
    const badge = page.locator('[data-testid^="cost-"]').first();
    await expect(badge).toBeVisible();
    expect((await badge.innerText()).trim().length).toBeGreaterThan(2);
    await expect(badge).toHaveAttribute("title", /.+/);
    // Jadval semantikasi: caption + scope (qator `role="button"` EMAS)
    await expect(page.locator("table caption").first()).toHaveCount(1);
    await expect(page.locator('tr[role="button"]')).toHaveCount(0);
    // Tanlangan filtr aria bilan e'lon qilinadi
    await expect(page.getByTestId("f-expiry-any")).toHaveAttribute("aria-pressed", "true");
  });

  test("tafsilot oynasi dialog sifatida e'lon qilinadi", async ({ page }) => {
    await managerLogin(page);
    await open(page, "partiyalar");
    await page.locator('[data-testid^="lot-open-"]').first().click();
    const dlg = page.getByTestId("lot-drawer");
    await expect(dlg).toHaveAttribute("aria-modal", "true");
    await expect(dlg).toHaveAttribute("role", "dialog");
    await expect(dlg).toHaveAttribute("aria-label", /.+/);
  });
});
