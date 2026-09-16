import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { managerLogin, MANAGER } from "./helpers";

// Manager — PARTIYA / MUDDAT / QARZ ekranlari (Phase 4B).
//
// Ma'lumot API orqali TAYYORLANADI (kuzatuvni yoqish, kirim, offline sotuv), so'ng
// oqimlar HAQIQIY brauzerda bosib chiqiladi. Stub yo'q: ekran nimani ko'rsatsa,
// server haqiqatan shuni qaytargan bo'ladi.

const API = "http://127.0.0.1:8000/api/v1";
const uuid = () => crypto.randomUUID();
const iso = (d: Date) => d.toISOString().slice(0, 10);

interface Ctx { token: string; tag: string; aId: string; aName: string; bId: string; bName: string }
let ctx: Ctx;

async function api(req: APIRequestContext, method: "get" | "post", path: string, token?: string, data?: unknown) {
  const r = await req[method](API + path, {
    headers: token ? { Authorization: "Bearer " + token } : {},
    data: data as any,
  });
  expect(r.ok(), `${method.toUpperCase()} ${path} -> ${r.status()} ${await r.text()}`).toBeTruthy();
  return r.json();
}

/**
 * O'Z mahsulotlarini yaratadi va ularga partiya kuzatuvini yoqadi.
 *
 * ⚠️  DEMO MAHSULOTLARI ISHLATILMAYDI. Ularni POS sinovlari sotadi/qaytaradi va
 *     partiya qoldig'i sinov o'rtasida o'zgarib ketardi — sinov mahsulotni emas,
 *     fayllar tartibini o'lchardi.
 *
 * ⚠️  HAR YURISHDA YANGI BELGI (`tag`). Playwright test yiqilsa WORKER'ni qayta
 *     ishga tushiradi va `beforeAll` QAYTA bajariladi; belgi bo'lmasa ikkinchi
 *     to'plam birinchisi bilan aralashib, tanlagichlar ikki elementga tushardi.
 */
async function setup(req: APIRequestContext): Promise<Ctx> {
  const auth = await api(req, "post", "/auth/login/password", undefined,
    { phone: "+998901234567", password: "demo1234" });
  const token = auth.access_token || auth.token;
  const tag = "LOT" + Math.random().toString(36).slice(2, 6).toUpperCase();

  const made = await api(req, "post", "/products/bulk", token, {
    items: [
      { name: `${tag} sut`, sell_price: 12000, buy_price: 7000, unit_code: "dona", stock: 0 },
      { name: `${tag} non`, sell_price: 6000, buy_price: 4000, unit_code: "dona", stock: 0 },
    ],
  });
  const [a, b] = made;
  const suppliers = await api(req, "get", "/suppliers", token);
  const supplierId = suppliers[0]?.id
    || (await api(req, "post", "/suppliers", token, { name: "E2E ta'minotchi" })).id;

  await api(req, "post", "/lots/timezone/confirm", token, {});
  await api(req, "post", "/lots/enable", token,
    { product_id: a.id, reason: "e2e partiya ekranlari", track_expiry: true });
  await api(req, "post", "/lots/enable", token,
    { product_id: b.id, reason: "e2e qarz oqimi", track_expiry: false });

  const recv = (pid: string, qty: number, cost: number, batch: string, expiry?: string) =>
    api(req, "post", "/receiving/commit", token, {
      items: [{ product_id: pid, qty, unit_cost: cost, unit: "dona",
                lots: [{ qty, unit_cost: cost, batch_number: batch, ...(expiry ? { expiry_date: expiry } : {}) }] }],
      supplier_id: supplierId, payment: "credit", client_uuid: uuid(), source: "manual",
    });

  const soon = new Date(); soon.setDate(soon.getDate() + 3);
  const later = new Date(); later.setDate(later.getDate() + 200);
  await recv(a.id, 8, 7000, `${tag}-SOON`, iso(soon));
  await recv(a.id, 5, 9000, `${tag}-LATER`, iso(later));

  // ANIQLANMAGAN QOLDIQ: offline chek qoldiqdan ko'p sotadi -> qarz ochiladi.
  await recv(b.id, 3, 4000, `${tag}-BOR`);
  await api(req, "post", "/sync/push", token, {
    sales: [{ client_uuid: uuid(), payment_method: "cash",
              items: [{ product_id: b.id, qty: 7, unit_price: 6000 }],
              given_amount: 1_000_000 }],
  });
  // Qarzni yopish uchun keyin keladigan haqiqiy partiya
  await recv(b.id, 10, 6000, `${tag}-QARZ`);
  return { token, tag, aId: a.id, aName: a.name, bId: b.id, bName: b.name };
}

test.beforeAll(async ({ request }) => { ctx = await setup(request); });

async function open(page: Page, hash: string) {
  await managerLogin(page);
  await page.goto(`${MANAGER}/#/${hash}`);
}

test.describe("Manager — partiya ekranlari", () => {
  test("1. kuzatuv yoqilgach Ombor menyusida partiya bo'limlari paydo bo'ladi", async ({ page }) => {
    await managerLogin(page);
    // Yon panel — dashboard kartalari ham shu nomda bo'lishi mumkin, shu bois ANIQ joy.
    const nav = page.locator("aside.sidebar");
    await expect(nav.getByRole("link", { name: "Партии" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Срок годности" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Неопознанный остаток" })).toBeVisible();
  });

  test("2. partiyalar ro'yxati serverdan keladi va qidiruv SERVERDA filtrlaydi", async ({ page }) => {
    await open(page, "partiyalar");
    await expect(page.getByTestId("lot-total")).toBeVisible();
    await expect(page.getByText(`${ctx.tag}-SOON`)).toBeVisible();
    await expect(page.getByText(`${ctx.tag}-LATER`)).toBeVisible();

    const req = page.waitForRequest((r) => r.url().includes("/lots/batches") && r.url().includes(encodeURIComponent(`${ctx.tag}-SOON`)));
    await page.getByTestId("lot-search").fill(`${ctx.tag}-SOON`);
    await req;
    await expect(page.getByText(`${ctx.tag}-LATER`)).toHaveCount(0);
  });

  test("3. partiya tafsilotida MANBA va TARIX ko'rinadi", async ({ page }) => {
    await open(page, "partiyalar");
    await page.getByText(`${ctx.tag}-SOON`).first().click();
    await expect(page.getByTestId("lot-drawer")).toBeVisible();
    await expect(page.getByText("Откуда пришло")).toBeVisible();
    await expect(page.getByTestId("lot-drawer")).toContainText("С прихода");
    await expect(page.getByTestId("lot-history")).toBeVisible();
  });

  test("4. muddat ekrani: kartalar va «o'zi yo'qolmaydi» ogohlantirishi", async ({ page }) => {
    await open(page, "muddat");
    await expect(page.getByTestId("expiry-notice")).toContainText("сам из остатка не исчезает");
    await expect(page.getByTestId("exp-card-within_7_days")).toBeVisible();
    await page.getByTestId("exp-card-within_7_days").click();
    await expect(page.getByText(`${ctx.tag}-SOON`)).toBeVisible();
    await expect(page.getByText(`${ctx.tag}-LATER`)).toHaveCount(0);   // 200 kunlik guruhga tushmaydi
  });

  test("5. hisobdan chiqarish TASDIQSIZ bajarilmaydi", async ({ page }) => {
    const qty = async (p2: typeof page) => {
      await p2.goto(`${MANAGER}/#/partiyalar`);
      await p2.getByTestId("lot-search").fill(`${ctx.tag}-SOON`);
      // ⚠️  `.first()` EMAS: qidiruv KECHIKTIRILGAN (debounce) va filtr qo'llanmasdan
      //     oldin birinchi qator BOSHQA partiya bo'lishi mumkin — sinov o'sha
      //     partiyaning qoldig'ini o'lchab, yolg'on natija berardi.
      const r = p2.locator('[data-testid^="lot-row-"]').filter({ hasText: `${ctx.tag}-SOON` });
      await expect(r).toHaveCount(1);
      return (await r.locator("td").nth(3).textContent() || "").replace(/[^\d.]/g, "");
    };
    await managerLogin(page);
    const before = await qty(page);

    await page.goto(`${MANAGER}/#/hisobdan-chiqarish`);
    await page.getByTestId("wo-product-input").fill(ctx.aName);
    await page.getByTestId(`wo-product-opt-${ctx.aId}`).click();
    const row = page.locator('[data-testid^="wo-lot-"]').filter({ hasText: `${ctx.tag}-SOON` });
    await expect(row).toBeVisible();
    await row.locator("input").fill("1");
    await page.getByTestId("wo-submit").click();
    await expect(page.getByTestId("confirm")).toContainText("уменьшит остаток");
    await page.getByTestId("confirm-cancel").click();

    expect(await qty(page)).toBe(before);   // BEKOR qilindi -> qoldiq o'zgarmadi
  });

  test("6. hisobdan chiqarish tasdiqlangach partiya qoldig'i KAMAYADI", async ({ page }) => {
    await open(page, "partiyalar");
    await page.getByTestId("lot-search").fill(`${ctx.tag}-LATER`);
    const row = page.locator('[data-testid^="lot-row-"]').filter({ hasText: `${ctx.tag}-LATER` });
    await expect(row).toHaveCount(1);
    const qtyBefore = Number((await row.locator("td").nth(3).textContent() || "0").replace(/[^\d.]/g, ""));

    await page.goto(`${MANAGER}/#/hisobdan-chiqarish`);
    await page.getByTestId("wo-product-input").fill(ctx.aName);
    await page.getByTestId(`wo-product-opt-${ctx.aId}`).click();
    const woRow = page.locator('[data-testid^="wo-lot-"]').filter({ hasText: `${ctx.tag}-LATER` });
    await woRow.locator("input").fill("2");
    await page.getByTestId("wo-submit").click();
    await page.getByTestId("confirm-ok").click();
    await expect(page.getByTestId("writeoff-done")).toBeVisible();

    await page.goto(`${MANAGER}/#/partiyalar`);
    await page.getByTestId("lot-search").fill(`${ctx.tag}-LATER`);
    const after = page.locator('[data-testid^="lot-row-"]').filter({ hasText: `${ctx.tag}-LATER` });
    await expect(after).toHaveCount(1);
    await expect.poll(async () =>
      Number((await after.locator("td").nth(3).textContent() || "0").replace(/[^\d.]/g, ""))
    ).toBe(qtyBefore - 2);
  });
});

test.describe("Manager — sanoq, qarz va mobil", () => {
  test("7. inventarizatsiya: SANALMAGAN partiya tegilmaydi", async ({ page }) => {
    await open(page, "inventarizatsiya");
    await page.getByTestId("cnt-product-input").fill(ctx.aName);
    await page.getByTestId(`cnt-product-opt-${ctx.aId}`).click();
    const soon = page.locator('[data-testid^="cnt-lot-"]').filter({ hasText: `${ctx.tag}-SOON` });
    await expect(soon).toBeVisible();
    const others = page.locator('[data-testid^="cnt-diff-"]').filter({ hasText: "не трогаем" });
    await expect(others.first()).toBeVisible();
    await soon.locator("input").fill("6");                 // 8 -> 6
    await expect(page.locator('[data-testid^="cnt-diff-"]').filter({ hasText: "-2" })).toBeVisible();
    await page.getByTestId("cnt-submit").click();
    await page.getByTestId("confirm-ok").click();
    await expect(page.getByTestId("count-done")).toBeVisible();

    await page.goto(`${MANAGER}/#/partiyalar`);
    await page.getByTestId("lot-search").fill(`${ctx.tag}-SOON`);
    const soonRow = page.locator('[data-testid^="lot-row-"]').filter({ hasText: `${ctx.tag}-SOON` });
    await expect(soonRow).toHaveCount(1);
    await expect(soonRow).toContainText("6 dona");
  });

  test("8. inventarizatsiya: javondan topilgan YANGI partiya «Tuzatish» bo'lib qo'shiladi", async ({ page }) => {
    await open(page, "inventarizatsiya");
    await page.getByTestId("cnt-product-input").fill(ctx.aName);
    await page.getByTestId(`cnt-product-opt-${ctx.aId}`).click();
    await page.getByTestId("cnt-add-new").click();
    await page.getByTestId("cnt-new-qty").fill("4");
    await page.getByTestId("cnt-new-batch").fill(`${ctx.tag}-TOPILDI`);
    await page.getByTestId("cnt-new-cost").fill("8000");
    const d = new Date(); d.setDate(d.getDate() + 60);
    await page.getByTestId("cnt-new-expiry").fill(d.toISOString().slice(0, 10));
    await page.getByTestId("cnt-submit").click();
    await page.getByTestId("confirm-ok").click();
    await expect(page.getByTestId("count-done")).toBeVisible();

    await page.goto(`${MANAGER}/#/partiyalar`);
    await page.getByTestId("lot-search").fill(`${ctx.tag}-TOPILDI`);
    const row = page.locator('[data-testid^="lot-row-"]').filter({ hasText: `${ctx.tag}-TOPILDI` });
    await expect(row).toHaveCount(1);
    await expect(row).toContainText("Корректировка");
  });

  test("9. aniqlanmagan qoldiq ro'yxati va tafsiloti (qaysi chekdan)", async ({ page }) => {
    await open(page, "aniqlanmagan-qoldiq");
    await expect(page.getByTestId("sf-explain")).toContainText("офлайн");
    const row = page.locator('[data-testid^="sf-row-"]').filter({ hasText: ctx.bName });
    await expect(row).toBeVisible();
    await row.click();
    await expect(page.getByTestId("sf-drawer")).toBeVisible();
    await expect(page.getByText("Из какого чека")).toBeVisible();
    await expect(page.getByTestId("sf-drawer")).toContainText("ПРИБЛИЗИТЕЛЬНО");
  });

  test("10. qarzni haqiqiy partiyaga bog'lash — natija OPERATOR tilida", async ({ page }) => {
    await open(page, "aniqlanmagan-qoldiq");
    await page.locator('[data-testid^="sf-row-"]').filter({ hasText: ctx.bName }).click();
    const cand = page.locator('[data-testid^="sf-cand-"]').filter({ hasText: `${ctx.tag}-QARZ` });
    await expect(cand).toBeVisible();
    await cand.locator("input").fill("2");
    await expect(page.getByTestId("sf-summary")).toContainText("2 шт. будет привязано");
    await page.getByTestId("sf-submit").click();
    await page.getByTestId("confirm-ok").click();
    const res = page.getByTestId("sf-result");
    await expect(res).toBeVisible();
    await expect(res).toContainText("2 шт. привязано к реальной партии");
    await expect(res).toContainText("осталось неопознанным");
  });

  test("11. dashboard kartasi muddat ekraniga olib boradi", async ({ page }) => {
    await managerLogin(page);
    const card = page.getByTestId("lot-alert-alertSoon");
    await expect(card).toBeVisible();
    await card.click();
    await expect(page).toHaveURL(/#\/muddat/);
    await expect(page.getByTestId("expiry-notice")).toBeVisible();
  });

  test("12. mobil 390px: kartalar ko'rinadi va GORIZONTAL scroll yo'q", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 780 });
    await open(page, "partiyalar");
    await expect(page.locator('[data-testid^="lot-card-"]').first()).toBeVisible();
    await expect(page.locator('[data-testid^="lot-row-"]')).toHaveCount(0);
    const overflow = await page.evaluate(() =>
      document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    // Yon panel ikonkalarga qisqargan — kontent uchun joy qoladi
    const w = await page.locator("aside.sidebar").evaluate((el) => el.getBoundingClientRect().width);
    expect(w).toBeLessThan(80);
  });
});
