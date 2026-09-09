import { test, expect } from "@playwright/test";
import { managerLogin, MANAGER } from "./helpers";

// Manager — YANGI savdogar uchun "Kassalar" sozlash ekrani.
//
// e2e backend SQLite'da ishlaydi va cash quyi tizimi FAQAT Postgres'da, shu bois /cash-setup
// 400 qaytaradi. Shu bois oqim tarmoq javobini almashtirib (route interception) sinaladi —
// ekran mantiqi server holatiga bog'liq emas.

const BR = "33333333-3333-3333-3333-333333333333";

function setupBody(tills: number, safes: number) {
  return {
    state: tills ? "POS_READY" : "CASH_SETUP_REQUIRED",
    ledger_native: true,
    cash_setup_complete: tills > 0,
    question: "Har filialda BUGUN nechta REAL fizik kassa (yashik) bor?",
    branches: [{
      branch_id: BR, code: "F01", name: "Asosiy filial",
      active_tills: tills, active_safes: safes,
      state: tills ? "POS_READY" : "CASH_SETUP_REQUIRED",
      can_open_cash_shift: tills > 0, collection_available: safes > 0,
    }],
  };
}

function till(code: string, active = true) {
  return { id: `id-${code}`, branch_id: BR, type: "TILL", code, label: null,
           terminal_id: null, currency: "UZS", status: active ? "ACTIVE" : "ARCHIVED", active };
}

async function mount(page: any, tills: number, safes: number, tillRows: unknown[]) {
  await page.route("**/api/v1/cash-setup", (r: any) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(setupBody(tills, safes)) }));
  await page.route("**/api/v1/tills**", (r: any) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(tillRows) }));
  await page.route("**/api/v1/safes**", (r: any) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(safes ? [till("SAFE")] : []) }));
  await managerLogin(page);
  await page.goto(`${MANAGER}/#/kassalar`);
}

test.describe("Manager — Kassalar sozlash", () => {
  test("kassasiz do'kon: aniq savol ko'rsatiladi, migration atamalari YO'Q", async ({ page }) => {
    await mount(page, 0, 0, []);
    await expect(page.getByTestId("cash-setup-banner")).toBeVisible();
    await expect(page.getByText(/нечта REAL физик касса|nechta REAL fizik kassa/i)).toBeVisible();
    // Savdogar migration ichki tushunchalarini KO'RMAYDI
    for (const w of ["cutover", "T0", "backfill", "historical_till_unknown", "shadow"]) {
      await expect(page.getByText(new RegExp(w, "i"))).toHaveCount(0);
    }
  });

  test("kassalar ro'yxati va yangi kassa qo'shish maydoni", async ({ page }) => {
    await mount(page, 2, 0, [till("TILL-01"), till("TILL-02")]);
    await expect(page.getByTestId("till-TILL-01")).toBeVisible();
    await expect(page.getByTestId("till-TILL-02")).toBeVisible();
    await expect(page.getByTestId("cash-setup-banner")).toHaveCount(0);   // sozlash tugallangan

    let sent: any = null;
    await page.route("**/api/v1/tills", async (route: any) => {
      if (route.request().method() === "POST") {
        sent = JSON.parse(route.request().postData() || "{}");
        return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(till("TILL-03")) });
      }
      return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
    });
    await page.getByTestId("new-till-F01").fill("TILL-03");
    await page.getByRole("button", { name: /Добавить кассу|Kassa qo/i }).first().click();
    await expect.poll(() => sent?.code).toBe("TILL-03");
    expect(sent.branch_id).toBe(BR);
  });

  test("SAFE ixtiyoriy: avtomatik yaratilmaydi, savol beriladi", async ({ page }) => {
    await mount(page, 1, 0, [till("TILL-01")]);
    await expect(page.getByTestId("add-safe-F01")).toBeVisible();          // taklif, avto EMAS
    await expect(page.getByTestId("safe-F01")).toHaveCount(0);
    await expect(page.getByText(/сейф НЕ обязателен|Seyf MAJBURIY EMAS/i)).toBeVisible();

    let posted = false;
    await page.route("**/api/v1/safes", async (route: any) => {
      if (route.request().method() === "POST") { posted = true;
        return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(till("SAFE")) }); }
      return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
    });
    await page.getByTestId("add-safe-F01").click();
    await expect.poll(() => posted).toBe(true);
  });
});
