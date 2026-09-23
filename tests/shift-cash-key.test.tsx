import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Shift } from "@/screens/Shift";
import { mockApi, renderApp, type Call } from "./util";

// KASSA AMALINING IDEMPOTENTLIK KALITI SMENAGA BOG'LIQ (Phase 5G, FX2-A).
//
// ⚠️  Server tomonida `client_uuid` noyobligi endi JADVAL BO'YLAB
//     (`ux_cashmov_client_uuid_all`): bitta kalit — bitta kassa harakati.
//     Kalitni smena almashgandan keyin ham ushlab qolish server uchun
//     «boshqa amalga ishlatilgan kalit» degani (409 IDEMPOTENCY_KEY_REUSED).
//     Shu bois ekran smena o'zgarganda kalitni yangilaydi. Javob yo'qolgan
//     holatdagi TAKROR esa AYNI kalit bilan ketishi SHART — u o'sha amalni
//     bildiradi va serverdagi dedup uni ikki marta yozmaydi.
//
//     Bu yerda server qoidalari SINALMAYDI (ularning hakami
//     `tests/test_mobile_parity*.py`) — faqat ekran NIMA yuborishi.

const shift = (id: string) => ({
  id, opened_at: "2026-09-24T06:00:00Z", opening_cash: 500000,
  cashier: "Kassir", branch: "Asosiy", till_id: null, terminal_id: null,
});

function routes(state: { cur: any }, onCash: (c: Call) => any): [RegExp, any][] {
  return [
    [/\/shifts\/current/, () => state.cur],
    [/\/shifts\/[^/]+\/summary/, { sales_total: 0, cash_total: 0, expected_cash: 500000, movements: [] }],
    [/\/shifts\/[^/]+\/cash$/, onCash],
    [/\/tills/, { available: false, tills: [] }],
    [/\/safes/, { available: false, safes: [] }],
    [/./, {}],
  ];
}

async function qoshish(amount = "") {
  if (amount) await userEvent.type(screen.getByPlaceholderText(/summa|сумма/i), amount);
  await userEvent.click(screen.getByTestId("cashop-submit"));
}

describe("POS smena: kassa amali kaliti", () => {
  it("javob yo'qolganda TAKROR AYNI kalit bilan ketadi", async () => {
    const state = { cur: shift("s1") };
    let n = 0;
    const calls = mockApi(routes(state, () => {
      n += 1;
      return n === 1 ? { __status: 502, detail: "Bad gateway" } : { ok: true };
    }));
    renderApp(<Shift />);
    await screen.findByTestId("cashop-submit");
    await qoshish("70000");
    await waitFor(() => expect(calls.filter((c) => /\/cash$/.test(c.url)).length).toBe(1));
    await qoshish();           // summa saqlanib qoladi — kassir qayta bosadi
    await waitFor(() => expect(calls.filter((c) => /\/cash$/.test(c.url)).length).toBe(2));
    const [a, b] = calls.filter((c) => /\/cash$/.test(c.url));
    expect(b.body.client_uuid).toBe(a.body.client_uuid);
    expect(b.body.amount).toBe(70000);
  });

  it("smena almashsa kalit YANGILANADI (eski kalit yangi smenaga kirmaydi)", async () => {
    const state = { cur: shift("s1") };
    const calls = mockApi(routes(state, () => ({ __status: 502, detail: "Bad gateway" })));
    renderApp(<Shift />);
    await screen.findByTestId("cashop-submit");
    await qoshish("70000");
    await waitFor(() => expect(calls.filter((c) => /\/cash$/.test(c.url)).length).toBe(1));
    const eski = calls.filter((c) => /\/cash$/.test(c.url))[0].body.client_uuid;

    state.cur = shift("s2");     // smena yopildi, yangisi ochildi
    await userEvent.click(screen.getByTestId("cashop-payin"));   // qayta render + load
    await waitFor(async () => {
      await qoshish();
      const yuborilgan = calls.filter((c) => /\/cash$/.test(c.url));
      expect(yuborilgan.length).toBeGreaterThan(1);
      expect(yuborilgan[yuborilgan.length - 1].body.client_uuid).not.toBe(eski);
    });
  });
});
