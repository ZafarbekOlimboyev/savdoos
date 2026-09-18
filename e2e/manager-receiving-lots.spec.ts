import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { managerLogin, MANAGER } from "./helpers";

// Manager — KIRIM EKRANI × PARTIYA (Phase 5C, B2).
//
// Ma'lumot API orqali TAYYORLANADI (kuzatuvni yoqish), so'ng kirim HAQIQIY
// brauzerda bosib chiqiladi va natija YANA API orqali tekshiriladi: partiya
// haqiqatan tug'ildimi, qaysi hujjat va qaysi ta'minotchidan.
//
// ⚠️  KUZATUVSIZ KIRIM — BIRINCHI SINOV. Production'da hali birorta kuzatuvli
//     tovar yo'q; bu oqim bir bayt ham o'zgarmasligi shart.

const API = "http://127.0.0.1:8000/api/v1";
const uuid = () => crypto.randomUUID();
const iso = (d: Date) => d.toISOString().slice(0, 10);

interface Ctx {
  token: string; tag: string; supName: string;
  fifoId: string; fifoName: string;
  expId: string; expName: string;
  plainId: string; plainName: string;
}
let ctx: Ctx;

async function api(req: APIRequestContext, method: "get" | "post", path: string, token?: string, data?: unknown) {
  const r = await req[method](API + path, {
    headers: token ? { Authorization: "Bearer " + token } : {},
    data: data as any,
  });
  expect(r.ok(), `${method.toUpperCase()} ${path} -> ${r.status()} ${await r.text()}`).toBeTruthy();
  return r.json();
}

async function setup(req: APIRequestContext): Promise<Ctx> {
  const auth = await api(req, "post", "/auth/login/password", undefined,
    { phone: "+998901234567", password: "demo1234" });
  const token = auth.access_token || auth.token;
  const tag = "RCV" + Math.random().toString(36).slice(2, 6).toUpperCase();

  const made = await api(req, "post", "/products/bulk", token, {
    items: [
      { name: `${tag} guruch`, sell_price: 14000, buy_price: 9000, unit_code: "kg", stock: 0 },
      { name: `${tag} qatiq`, sell_price: 12000, buy_price: 7000, unit_code: "dona", stock: 0 },
      { name: `${tag} choy`, sell_price: 20000, buy_price: 12000, unit_code: "dona", stock: 0 },
    ],
  });
  const [fifo, exp, plain] = made;
  // ⚠️  TA'MINOTCHI ANIQ YARATILADI. Ro'yxat bo'sh bo'lsa tanlagichning 1-bandi
  //     «＋ Yangi beruvchi» bo'lib chiqadi va indeks bo'yicha tanlash butun
  //     ekranni modal bilan to'sib qo'yadi.
  const sups = await api(req, "get", "/suppliers", token);
  const sup = sups[0] || await api(req, "post", "/suppliers", token, { name: `${tag} ta'minotchi` });
  await api(req, "post", "/lots/timezone/confirm", token, {});
  await api(req, "post", "/lots/enable", token,
    { product_id: fifo.id, reason: "e2e: kirim UI (FIFO)", track_expiry: false });
  await api(req, "post", "/lots/enable", token,
    { product_id: exp.id, reason: "e2e: kirim UI (muddat)", track_expiry: true });
  return {
    token, tag, supName: sup.name,
    fifoId: fifo.id, fifoName: fifo.name,
    expId: exp.id, expName: exp.name,
    plainId: plain.id, plainName: plain.name,
  };
}

test.beforeAll(async ({ request }) => { ctx = await setup(request); });

/** Xaridlar -> «Новый приход» + bitta bo'sh qator. */
async function openKirim(page: Page) {
  await managerLogin(page);
  await page.goto(`${MANAGER}/#/xaridlar`);
  await page.getByRole("button", { name: /Новый приход/ }).click();
  await page.getByRole("button", { name: "Добавить товар" }).click();
}

/** Mavjud tovarni taklif ro'yxatidan tanlaydi va qatorni to'ldiradi.
 *
 *  ⚠️  Taklif QATORI bosiladi, ichidagi matn emas: nom uzun bo'lsa u
 *      `text-overflow: ellipsis` bilan nolgacha qisqarib, bosib bo'lmas
 *      element bo'lib qoladi (tor ekranda har doim). */
async function pickProduct(page: Page, id: string, name: string, qty: string) {
  await page.getByPlaceholder("Название товара").last().fill(name.slice(0, 9));
  await page.getByTestId(`recv-sug-${id}`).click();
  // Kategoriya: `products/bulk` uni bermaydi, kirim esa TALAB qiladi.
  await page.locator("main select").nth(1).selectOption({ index: 1 });
  await page.getByTestId("recv-qty-1").fill(qty);
}

async function lots(request: APIRequestContext, q: string) {
  const d = await api(request, "get", `/lots/batches?q=${encodeURIComponent(q)}&limit=50`, ctx.token);
  return d.lots as any[];
}

test.describe("Manager — partiyali kirim", () => {
  test("1. KUZATUVSIZ tovar: `lots` YUBORILMAYDI (bugungi payload)", async ({ page }) => {
    await openKirim(page);
    await pickProduct(page, ctx.plainId, ctx.plainName, "4");
    await page.getByTitle("Подтвердить").click();
    const wait = page.waitForRequest((r) => r.url().includes("/receiving/commit") && r.method() === "POST");
    await page.getByTestId("recv-save").click();
    const body = (await wait).postDataJSON();
    expect(body.items).toHaveLength(1);
    expect(body.items[0].product_id).toBe(ctx.plainId);
    expect(body.items[0].qty).toBe(4);
    expect("lots" in body.items[0]).toBe(false);
    await expect(page.getByText("Приходные документы").first()).toBeVisible({ timeout: 15_000 });
  });

  test("2. KUZATUVLI (FIFO): ikki partiya yoziladi, provenans TO'LIQ", async ({ page, request }) => {
    await openKirim(page);
    // Ta'minotchi ANIQ tanlanadi — partiya provenansi shuni ko'rsatishi shart.
    await page.locator("main select").first().selectOption({ label: ctx.supName });
    await pickProduct(page, ctx.fifoId, ctx.fifoName, "10");

    await expect(page.getByTestId("recv-lots-1")).toBeVisible();
    await page.getByTestId("recv-lots-1-qty-0").fill("6");
    await page.getByTestId("recv-lots-1-batch-0").fill(`${ctx.tag}-A`);
    await expect(page.getByTestId("recv-lots-1-sum")).toContainText("осталось 4");
    await page.getByTestId("recv-lots-1-add").click();
    await page.getByTestId("recv-lots-1-qty-1").fill("4");
    await page.getByTestId("recv-lots-1-batch-1").fill(`${ctx.tag}-B`);
    await expect(page.getByTestId("recv-lots-1-sum")).toContainText("10 / 10");

    await page.getByTitle("Подтвердить").click();
    const wait = page.waitForRequest((r) => r.url().includes("/receiving/commit") && r.method() === "POST");
    await page.getByTestId("recv-save").click();
    const body = (await wait).postDataJSON();
    expect(body.items[0].lots).toEqual([
      { qty: 6, batch_number: `${ctx.tag}-A` },
      { qty: 4, batch_number: `${ctx.tag}-B` },
    ]);
    await expect(page.getByText("Приходные документы").first()).toBeVisible({ timeout: 15_000 });

    // SERVER TOMONI: partiyalar haqiqatan tug'ildi va hujjatga bog'landi.
    const rows = (await lots(request, ctx.tag)).filter((l) => l.product_id === ctx.fifoId);
    expect(rows).toHaveLength(2);
    expect(rows.map((l) => l.remaining_qty).sort((a, b) => a - b)).toEqual([4, 6]);
    for (const l of rows) {
      expect(l.source_type).toBe("receiving");
      expect(l.supplier).toBe(ctx.supName);
      expect(l.unit_cost).toBe(9000);          // qator narxi partiyaga TUSHDI
      const d = await api(request, "get", `/lots/batches/${l.id}`, ctx.token);
      expect(d.source.receiving_id).not.toBeNull();
      expect(d.source.purchase).not.toBeNull();
    }
  });

  test("3. MUDDATLI tovar: sana MAJBURIY va partiyaga yoziladi", async ({ page, request }) => {
    await openKirim(page);
    await pickProduct(page, ctx.expId, ctx.expName, "5");
    await expect(page.getByTestId("recv-lots-1-expiry-0")).toBeVisible();

    // Sanasiz — tasdiqlanmaydi
    await page.getByTitle("Подтвердить").click();
    await expect(page.getByTestId("recv-error")).toContainText(/срок/i);

    const d = new Date(); d.setDate(d.getDate() + 90);
    await page.getByTestId("recv-lots-1-expiry-0").fill(iso(d));
    await page.getByTestId("recv-lots-1-batch-0").fill(`${ctx.tag}-EXP`);
    await page.getByTitle("Подтвердить").click();
    await page.getByTestId("recv-save").click();
    await expect(page.getByText("Приходные документы").first()).toBeVisible({ timeout: 15_000 });

    const rows = (await lots(request, `${ctx.tag}-EXP`));
    expect(rows).toHaveLength(1);
    expect(rows[0].expiry_date).toBe(iso(d));
    expect(rows[0].remaining_qty).toBe(5);
  });

  test("4. yig'indi mos kelmasa — qator tasdiqlanmaydi, hujjat YUBORILMAYDI", async ({ page }) => {
    await openKirim(page);
    // 1-qator: KUZATUVSIZ va tasdiqlangan — hujjatda summa bo'lsin (tugma ochiq).
    await pickProduct(page, ctx.plainId, ctx.plainName, "2");
    await page.getByTitle("Подтвердить").click();
    // 2-qator: KUZATUVLI, partiyalar yig'indisi mos kelmaydi.
    await page.getByRole("button", { name: "Добавить товар" }).click();
    await page.getByPlaceholder("Название товара").last().fill(ctx.fifoName.slice(0, 9));
    await page.getByTestId(`recv-sug-${ctx.fifoId}`).click();
    // 1-qator TASDIQLANGAN -> uning tanlagichlari YO'Q: [ta'minotchi, kategoriya, birlik].
    await page.locator("main select").nth(1).selectOption({ index: 1 });
    await page.getByTestId("recv-qty-2").fill("7");
    await page.getByTestId("recv-lots-2-qty-0").fill("3");
    await page.getByTitle("Подтвердить").click();
    await expect(page.getByTestId("recv-error")).toContainText(/Сумма партий не равна/i);

    let sent = 0;
    page.on("request", (r) => { if (r.url().includes("/receiving/commit")) sent += 1; });
    // Tasdiqlanmagan PARTIYALI qator jimgina tushib qolmaydi — saqlash TO'XTAYDI.
    await page.getByTestId("recv-save").click();
    await expect(page.getByTestId("recv-error")).toContainText(/не подтверждена/i);
    expect(sent).toBe(0);

    // Tuzatilgach — o'tadi.
    await page.getByTestId("recv-lots-2-fill").click();
    await expect(page.getByTestId("recv-lots-2-qty-0")).toHaveValue("7");
    await page.getByTitle("Подтвердить").click();
    const wait = page.waitForRequest((r) => r.url().includes("/receiving/commit") && r.method() === "POST");
    await page.getByTestId("recv-save").click();
    const body = (await wait).postDataJSON();
    expect(body.items).toHaveLength(2);
    expect(body.items[1].lots).toEqual([{ qty: 7 }]);
  });

  test("5. TOR ekran (390px) + FAQAT KLAVIATURA: Enter hujjatni yubormaydi", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 780 });
    await openKirim(page);
    await pickProduct(page, ctx.fifoId, ctx.fifoName, "2");

    let sent = 0;
    page.on("request", (r) => { if (r.url().includes("/receiving/commit")) sent += 1; });

    // Qator miqdoridan Tab bilan partiya maydoniga tushamiz (oraliqda birlik tanlagichi).
    await page.getByTestId("recv-qty-1").focus();
    await page.keyboard.press("Tab");
    await page.keyboard.press("Tab");
    const qty = page.getByTestId("recv-lots-1-qty-0");
    await expect(qty).toBeFocused();
    await page.keyboard.press("Control+a");
    await page.keyboard.type("2");
    // Enter — SAQLAMAYDI, keyingi maydonga o'tadi
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("recv-lots-1-batch-0")).toBeFocused();
    await page.keyboard.type(`${ctx.tag}-KB`);
    expect(sent).toBe(0);

    // Fokus halqasi KO'RINADI (inline `outline: none` qaytmasin)
    const ring = await page.evaluate(() => {
      const st = getComputedStyle(document.activeElement as HTMLElement);
      return { style: st.outlineStyle, width: parseFloat(st.outlineWidth || "0") };
    });
    expect(ring.style).not.toBe("none");
    expect(ring.width).toBeGreaterThanOrEqual(1);

    // Muharrirning O'ZI tor ekranda o'ralib ketadi (ichida gorizontal scroll YO'Q).
    // ⚠️  Kirim JADVALI (8 ustun) telefon uchun mo'ljallanmagan — Manager desktop
    //     ilovasi; bu yerda aynan MUHARRIR o'lchanadi.
    const over = await page.getByTestId("recv-lots-1").evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(over).toBeLessThanOrEqual(1);
  });
});

// ── PHASE 5D — QABULNI TUZATISH / BEKOR QILISH (Manager oqimi) ───────────────
//
// ⚠️  HUJJAT API ORQALI YARATILADI, TUZATISH ESA BRAUZERDA BOSILADI. Maqsad —
//     operator ko'radigan yo'lni o'lchash: tugma ko'rinadimi, kogortalar
//     ro'yxatlanadimi, tasdiq oynasi chiqadimi va server HAQIQATAN kogortani
//     `void` qilib, qoldiqni qaytaradimi.
test.describe("Manager — qabulni tuzatish", () => {
  test("6. TEGILMAGAN qabul bekor qilinadi: kogorta `void`, qoldiq qaytadi", async ({ page, request }) => {
    const batch = `${ctx.tag}-CORR`;
    const rec = await api(request, "post", "/receiving/commit", ctx.token, {
      items: [{ product_id: ctx.fifoId, qty: 7, unit_cost: 9000,
                lots: [{ qty: 7, batch_number: batch }] }],
      source: "manual", payment: "cash", client_uuid: uuid(),
    });
    expect(rec.receiving_id).toBeTruthy();
    // ⚠️  `q` MAHSULOT nomi bo'yicha qidiradi (partiya raqami bo'yicha emas):
    //     qidiruv tegi bilan olinadi, kerakli kogorta esa raqami bo'yicha tanlanadi.
    const before = (await lots(request, ctx.tag)).find((l) => l.batch_number === batch);
    expect(before.remaining_qty).toBe(7);

    await managerLogin(page);
    await page.goto(`${MANAGER}/#/xaridlar`);
    // Eng yangi hujjat — ro'yxatning birinchi qatori.
    await page.locator("table tbody tr").first().click();
    await expect(page.getByTestId("kd-correct")).toBeVisible({ timeout: 15_000 });
    await page.getByTestId("kd-correct").click();
    await expect(page.getByTestId("corr-modal")).toBeVisible();

    await page.getByTestId("corr-reason").fill("e2e: nakladnoyda xato miqdor");
    await page.getByTestId(`corr-rev-${before.id}`).fill("7");
    await page.getByTestId("corr-submit").click();
    // DESTRUKTIV TASDIQ — bir bosishda bajarilmaydi.
    await expect(page.getByTestId("confirm")).toBeVisible();
    await page.getByTestId("confirm-ok").click();
    await expect(page.getByTestId("corr-modal")).toBeHidden({ timeout: 15_000 });

    // SERVER TOMONI: kogorta `void`, qoldiq 0, KELGAN miqdor esa SAQLANADI.
    const after = (await api(request, "get",
      `/lots/batches?q=${encodeURIComponent(ctx.tag)}&status=void&limit=50`, ctx.token)).lots
      .find((l: any) => l.batch_number === batch);
    expect(after).toBeTruthy();
    expect(after.remaining_qty).toBe(0);
    expect(after.received_qty).toBe(7);
    expect(after.status).toBe("void");
  });
});
