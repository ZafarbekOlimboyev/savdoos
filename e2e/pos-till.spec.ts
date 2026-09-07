import { test, expect } from "@playwright/test";
import { posLogin, POS } from "./helpers";

// POS — AYNAN kassa (TILL) identifikatsiyasi.
//
// MUHIM: e2e backend SQLite'da ishlaydi va cash quyi tizimi FAQAT Postgres'da mavjud, shu bois
// bu yerda `/tills` 400 qaytaradi. Shu holat ALOHIDA sinaladi: POS eski yo'l bilan (till_id'siz)
// ishlashda davom etishi SHART. Kassa TANLASH oqimining o'zi (0/1/N) tarmoq javobini
// almashtirib (route interception) sinaladi — server holatiga bog'liq emas.

const TILLS = "**/api/v1/tills**";
const A = "11111111-1111-1111-1111-111111111111";
const B = "22222222-2222-2222-2222-222222222222";
const BR = "33333333-3333-3333-3333-333333333333";
const NEW_SHIFT = "44444444-4444-4444-4444-444444444444";

function till(id: string, code: string, branch_id = BR) {
  return {
    id, branch_id, type: "TILL", code, label: `TILL code=${code} terminal=NONE`,
    terminal_id: null, currency: "UZS", status: "ACTIVE", active: true,
  };
}

function tillsRoute(page: any, body: unknown, status = 200) {
  return page.route(TILLS, (r: any) =>
    r.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) }));
}

/** Smena ochish so'rovini ushlaymiz va yuborilgan payload'ni qaytaramiz. */
function captureOpen(page: any, sink: { body: any }) {
  return page.route("**/api/v1/shifts/open", async (route: any) => {
    sink.body = JSON.parse(route.request().postData() || "{}");
    await route.fulfill({ status: 200, contentType: "application/json",
                          body: JSON.stringify({ id: NEW_SHIFT }) });
  });
}

async function gotoShift(page: any) {
  await posLogin(page);
  await page.goto(`${POS}/#/smena`);
  // Ochish formasi ko'rinsin (demo seed'da smena yopiq).
  await expect(page.getByTestId("shift-open")).toBeVisible({ timeout: 20_000 });
}

test.describe("POS — AYNAN kassa (TILL)", () => {
  // ═══ A) 0 ta ACTIVE kassa -> smena ochish BLOKLANADI ═══════════════════════
  test("A: 0 TILL -> ochish bloklanadi va sabab ko'rinadi", async ({ page }) => {
    await tillsRoute(page, []);
    await gotoShift(page);
    await expect(page.getByTestId("till-none")).toBeVisible();
    await expect(page.getByTestId("shift-open")).toBeDisabled();
  });

  // ═══ B + D) 1 ta kassa -> ko'rinadi va AYNAN id so'rovga tushadi ══════════
  test("B/D: 1 TILL -> ko'rinadi va aynan till_id yuboriladi", async ({ page }) => {
    await tillsRoute(page, [till(A, "TILL-01")]);
    await gotoShift(page);
    await expect(page.getByTestId("till-single")).toHaveText("TILL-01");

    const sink: { body: any } = { body: null };
    await captureOpen(page, sink);
    await page.getByTestId("shift-open").click();
    // ASOSIY: server "yagona kassa" degan TAXMINGA tayanmaydi — id ANIQ yuboriladi.
    await expect.poll(() => sink.body?.till_id).toBe(A);
  });

  // ═══ C) 2+ kassa -> jimgina BIRINCHISI tanlanmaydi ════════════════════════
  test("C: 2 TILL -> avto tanlash YO'Q, operator tanlaydi", async ({ page }) => {
    await tillsRoute(page, [till(A, "TILL-01"), till(B, "TILL-02")]);
    await gotoShift(page);
    const sel = page.getByTestId("till-select");
    await expect(sel).toBeVisible();
    await expect(sel).toHaveValue("");                       // birinchisi AVTOMATIK tanlanmagan
    await expect(page.getByTestId("shift-open")).toBeDisabled();

    const sink: { body: any } = { body: null };
    await captureOpen(page, sink);
    await sel.selectOption(B);                               // kassir TILL-02 ni tanladi
    await expect(page.getByTestId("shift-open")).toBeEnabled();
    await page.getByTestId("shift-open").click();
    await expect.poll(() => sink.body?.till_id).toBe(B);
  });

  // ═══ E + F) tanlov saqlanadi va smena ichida O'ZGARMAYDI ══════════════════
  test("E/F: till_id smena holatida saqlanadi, smena ichida almashmaydi", async ({ page }) => {
    await tillsRoute(page, [till(A, "TILL-01"), till(B, "TILL-02")]);
    await gotoShift(page);
    // Smena OCHIQ holatini ham taqlid qilamiz — aks holda ekran ochish formasida qolardi
    // (biz /shifts/open ni mock qildik, haqiqiy backend'da smena yaratilmadi).
    let opened = false;
    await page.route("**/api/v1/shifts/current", (route: any) =>
      route.fulfill({ status: 200, contentType: "application/json",
                      body: opened
                        ? JSON.stringify({ id: NEW_SHIFT, opened_at: new Date().toISOString(),
                                           opening_cash: 0 })
                        : "null" }));
    await page.route(`**/api/v1/shifts/${NEW_SHIFT}/summary`, (route: any) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        opening: 0, total_sales: 0, receipts: 0, by_method: {}, naqd_sales: 0, payin: 0,
        payout: 0, expected: 0, opened_at: new Date().toISOString(), ops: [] }) }));

    const sink: { body: any } = { body: null };
    await captureOpen(page, sink);
    await page.getByTestId("till-select").selectOption(B);
    await page.getByTestId("shift-open").click();
    await expect.poll(() => sink.body?.till_id).toBe(B);
    opened = true;

    const read = () => page.evaluate(() => {
      try { return JSON.parse(localStorage.getItem("savdoos-shift") || "{}")?.state?.current || null; }
      catch { return null; }
    });
    await expect.poll(read).not.toBeNull();
    const saved = await read();
    expect(saved.till_id).toBe(B);                           // E: identity saqlandi
    expect(saved.branch_id).toBe(BR);
    expect(saved.shift_id).toBe(NEW_SHIFT);

    // F: smena ochiq ekan, kassa tanlash boshqaruvi UMUMAN yo'q -> almashtirib bo'lmaydi
    await expect(page.getByTestId("till-select")).toHaveCount(0);
    await expect(page.getByTestId("till-single")).toHaveCount(0);
  });

  // ═══ G) ARCHIVED kassa tanlanadigan ro'yxatda BO'LMAYDI ═══════════════════
  test("G: arxivlangan kassa ro'yxatga tushmaydi (active_only=true)", async ({ page }) => {
    let url = "";
    await page.route(TILLS, async (route: any) => {
      url = route.request().url();
      // Server FAQAT ACTIVE qaytaradi — arxivlangan mijozga UMUMAN yetib kelmaydi.
      await route.fulfill({ status: 200, contentType: "application/json",
                            body: JSON.stringify([till(A, "TILL-01")]) });
    });
    await gotoShift(page);
    await expect.poll(() => url).toContain("active_only=true");
    await expect(page.getByTestId("till-single")).toHaveText("TILL-01");
    await expect(page.getByText("TILL-OLD")).toHaveCount(0);
  });

  // ═══ H) filial izolyatsiyasi (mine=true) ══════════════════════════════════
  test("H: ro'yxat joriy filial bilan cheklanadi (mine=true)", async ({ page }) => {
    let url = "";
    await page.route(TILLS, async (route: any) => {
      url = route.request().url();
      await route.fulfill({ status: 200, contentType: "application/json",
                            body: JSON.stringify([till(A, "TILL-01")]) });
    });
    await gotoShift(page);
    await expect.poll(() => url).toContain("mine=true");
  });

  // ═══ cash-disabled server (SQLite/dev) -> eski yo'l ISHLAYDI ══════════════
  test("cash quyi tizimi yo'q -> kassa tanlash yo'q, smena ochilaveradi", async ({ page }) => {
    await tillsRoute(page, { detail: "Cash quyi tizimi yoqilmagan (Postgres + cash schema kerak)" }, 400);
    await gotoShift(page);
    await expect(page.getByTestId("till-none")).toHaveCount(0);
    await expect(page.getByTestId("till-select")).toHaveCount(0);
    await expect(page.getByTestId("shift-open")).toBeEnabled();   // BLOKLANMAYDI

    const sink: { body: any } = { body: null };
    await captureOpen(page, sink);
    await page.getByTestId("shift-open").click();
    await expect.poll(() => sink.body).not.toBeNull();
    expect(sink.body.till_id).toBeUndefined();   // TILL tushunchasi yo'q -> maydon YUBORILMAYDI
  });
});
