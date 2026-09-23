import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { Shift } from "@/screens/Shift";
import { mockApi, renderApp, type Call } from "./util";

// KASSA AMALINING IDEMPOTENTLIK KALITI QORALAMAGA BOG'LIQ (Phase 5G, FX2-A + FX3-B).
//
// ⚠️  Server tomonida `client_uuid` noyobligi endi JADVAL BO'YLAB
//     (`ux_cashmov_client_uuid_all`): bitta kalit — bitta kassa harakati.
//     Kalitni BOSHQA amalga (boshqa summa/tur/izoh/seyf, yoki boshqa smena)
//     olib o'tish server uchun «band kalit» degani (409 IDEMPOTENCY_KEY_REUSED)
//     va u holda HECH NARSA yozilmaydi.
//
//     Shu bois kalit QORALAMADAN olinadi (mobil `DraftUuid` shartnomasi):
//       · AYNI qoralama -> AYNI kalit  (javob yo'qolganda takror XAVFSIZ);
//       · qoralama o'zgarsa -> YANGI kalit (bu BOSHQA amal);
//       · muvaffaqiyat yoki 409 «kalit band» -> kalit BEKOR (keyingi amal yangisini oladi).
//
//     Bu yerda server qoidalari SINALMAYDI (ularning hakami
//     `tests/test_mobile_parity*.py`) — faqat ekran NIMA yuborishi.

const shift = (id: string) => ({
  id, opened_at: "2026-09-24T06:00:00Z", opening_cash: 500000,
  cashier: "Kassir", branch: "Asosiy", till_id: null, terminal_id: null,
});

const safe = (id: string, code: string) => ({
  id, branch_id: "b1", type: "SAFE", code, label: null, terminal_id: null,
  currency: "UZS", status: "ACTIVE", active: true,
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

/**
 * `mockApi` bilan bir xil, LEKIN javob sarlavhasini ham bera oladi:
 * barqaror xato kodi (`X-Error-Code`) matndan TASHQARIDA keladi va
 * `api.ts` uni `err.code` ga biriktiradi — 409 `IDEMPOTENCY_KEY_REUSED`
 * ni matn tarjimasidan MUSTAQIL ravishda tanish uchun shu kerak.
 */
function mockApiWithCodes(routes: [RegExp, any | ((c: Call) => any)][]): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, opts: RequestInit = {}) => {
    const call: Call = {
      url: String(url),
      method: (opts.method || "GET").toUpperCase(),
      body: opts.body ? JSON.parse(String(opts.body)) : null,
    };
    calls.push(call);
    for (const [re, res] of routes) {
      if (re.test(call.url)) {
        const value = typeof res === "function" ? await res(call) : res;
        const headers: Record<string, string> = { "Content-Type": "application/json" };
        if (value && value.__code) headers["X-Error-Code"] = value.__code;
        if (value && value.__status && value.__status >= 400) {
          return new Response(JSON.stringify({ detail: value.detail }), { status: value.__status, headers });
        }
        return new Response(JSON.stringify(value), { status: 200, headers });
      }
    }
    return new Response(JSON.stringify({ detail: "mock: " + call.url }), { status: 404 });
  }));
  return calls;
}

const cashCalls = (calls: Call[]) => calls.filter((c) => /\/cash$/.test(c.url));

async function qoshish(amount = "") {
  if (amount) await userEvent.type(screen.getByPlaceholderText(/summa|сумма/i), amount);
  await userEvent.click(screen.getByTestId("cashop-submit"));
}

async function qaytaYoz(amount: string) {
  const input = screen.getByPlaceholderText(/summa|сумма/i);
  await userEvent.clear(input);
  await userEvent.type(input, amount);
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
    await waitFor(() => expect(cashCalls(calls).length).toBe(1));
    await qoshish();           // summa saqlanib qoladi — kassir qayta bosadi
    await waitFor(() => expect(cashCalls(calls).length).toBe(2));
    const [a, b] = cashCalls(calls);
    expect(b.body.client_uuid).toBe(a.body.client_uuid);
    expect(b.body.amount).toBe(70000);
  });

  it("smena almashsa kalit YANGILANADI (eski kalit yangi smenaga kirmaydi)", async () => {
    const state = { cur: shift("s1") };
    const calls = mockApi(routes(state, () => ({ __status: 502, detail: "Bad gateway" })));
    renderApp(<Shift />);
    await screen.findByTestId("cashop-submit");
    await qoshish("70000");
    await waitFor(() => expect(cashCalls(calls).length).toBe(1));
    const eski = cashCalls(calls)[0].body.client_uuid;

    state.cur = shift("s2");     // smena yopildi, yangisi ochildi
    await userEvent.click(screen.getByTestId("cashop-payin"));   // qayta render + load
    await waitFor(async () => {
      await qoshish();
      const yuborilgan = cashCalls(calls);
      expect(yuborilgan.length).toBeGreaterThan(1);
      expect(yuborilgan[yuborilgan.length - 1].body.client_uuid).not.toBe(eski);
    });
  });

  // ── FX3-B.2: bitta yo'qolgan javob keyingi BOSHQA amalni bloklamasin ──────
  it("qoralama TAHRIRLANSA kalit YANGILANADI (boshqa summa = BOSHQA amal)", async () => {
    const state = { cur: shift("s1") };
    let n = 0;
    const calls = mockApi(routes(state, () => {
      n += 1;
      return n === 1 ? { __status: 502, detail: "Bad gateway" } : { ok: true };
    }));
    renderApp(<Shift />);
    await screen.findByTestId("cashop-submit");
    await qoshish("70000");
    await waitFor(() => expect(cashCalls(calls).length).toBe(1));

    await qaytaYoz("150000");     // kassir summani TUZATDI — bu boshqa amal
    await qoshish();
    await waitFor(() => expect(cashCalls(calls).length).toBe(2));
    const [a, b] = cashCalls(calls);
    expect(b.body.amount).toBe(150000);
    expect(b.body.client_uuid).not.toBe(a.body.client_uuid);
  });

  it("TUR almashtirilsa kalit YANGILANADI (kirim -> xarajat)", async () => {
    const state = { cur: shift("s1") };
    const calls = mockApi(routes(state, () => ({ __status: 502, detail: "Bad gateway" })));
    renderApp(<Shift />);
    await screen.findByTestId("cashop-submit");
    await qoshish("70000");
    await waitFor(() => expect(cashCalls(calls).length).toBe(1));

    await userEvent.click(screen.getByTestId("cashop-expense"));
    await qoshish();
    await waitFor(() => expect(cashCalls(calls).length).toBe(2));
    const [a, b] = cashCalls(calls);
    expect(b.body.type).toBe("expense");
    expect(b.body.client_uuid).not.toBe(a.body.client_uuid);
  });

  it("IZOH o'zgarsa kalit YANGILANADI", async () => {
    const state = { cur: shift("s1") };
    const calls = mockApi(routes(state, () => ({ __status: 502, detail: "Bad gateway" })));
    renderApp(<Shift />);
    await screen.findByTestId("cashop-submit");
    await qoshish("70000");
    await waitFor(() => expect(cashCalls(calls).length).toBe(1));

    await userEvent.type(screen.getByPlaceholderText(/izoh|примеч/i), "Obed");
    await qoshish();
    await waitFor(() => expect(cashCalls(calls).length).toBe(2));
    const [a, b] = cashCalls(calls);
    expect(b.body.reason).toBe("Obed");
    expect(b.body.client_uuid).not.toBe(a.body.client_uuid);
  });

  it("INKASSA: boshqa seyf tanlansa kalit YANGILANADI (manzil moddiy)", async () => {
    const state = { cur: shift("s1") };
    const r = routes(state, () => ({ __status: 502, detail: "Bad gateway" }));
    r[4] = [/\/safes/, [safe("sf-a", "SEYF-1"), safe("sf-b", "SEYF-2")]];
    const calls = mockApi(r);
    renderApp(<Shift />);
    await screen.findByTestId("cashop-submit");
    await userEvent.click(screen.getByTestId("cashop-collection"));
    await screen.findByTestId("safe-select");
    await userEvent.selectOptions(screen.getByTestId("safe-select"), "sf-a");
    await qoshish("1000000");
    await waitFor(() => expect(cashCalls(calls).length).toBe(1));

    await userEvent.selectOptions(screen.getByTestId("safe-select"), "sf-b");
    await qoshish();
    await waitFor(() => expect(cashCalls(calls).length).toBe(2));
    const [a, b] = cashCalls(calls);
    expect(a.body.destination_safe_id).toBe("sf-a");
    expect(b.body.destination_safe_id).toBe("sf-b");
    expect(b.body.client_uuid).not.toBe(a.body.client_uuid);
  });

  it("AYNI seyf qayta tanlansa kalit SAQLANADI (o'sha amalning takrori)", async () => {
    const state = { cur: shift("s1") };
    const r = routes(state, () => ({ __status: 502, detail: "Bad gateway" }));
    r[4] = [/\/safes/, [safe("sf-a", "SEYF-1"), safe("sf-b", "SEYF-2")]];
    const calls = mockApi(r);
    renderApp(<Shift />);
    await screen.findByTestId("cashop-submit");
    await userEvent.click(screen.getByTestId("cashop-collection"));
    await screen.findByTestId("safe-select");
    await userEvent.selectOptions(screen.getByTestId("safe-select"), "sf-a");
    await qoshish("1000000");
    await waitFor(() => expect(cashCalls(calls).length).toBe(1));

    await userEvent.selectOptions(screen.getByTestId("safe-select"), "sf-a");
    await qoshish();
    await waitFor(() => expect(cashCalls(calls).length).toBe(2));
    const [a, b] = cashCalls(calls);
    expect(b.body.client_uuid).toBe(a.body.client_uuid);
  });

  // ── FX3-B.1: 409 «kalit band» dan keyin kassir YO'LDA DAVOM ETA OLSIN ────
  it("409 IDEMPOTENCY_KEY_REUSED dan keyin YANGI kalit beriladi", async () => {
    const state = { cur: shift("s1") };
    let n = 0;
    const calls = mockApiWithCodes(routes(state, () => {
      n += 1;
      return n === 1
        ? { __status: 409, __code: "IDEMPOTENCY_KEY_REUSED",
            detail: "IDEMPOTENCY_KEY_REUSED: bu kassa amali YOZILMADI" }
        : { ok: true };
    }));
    renderApp(<Shift />);
    await screen.findByTestId("cashop-submit");
    await qoshish("70000");
    await waitFor(() => expect(cashCalls(calls).length).toBe(1));

    await qoshish();          // kassir xato matnini o'qib AYNI amalni qayta kiritadi
    await waitFor(() => expect(cashCalls(calls).length).toBe(2));
    const [a, b] = cashCalls(calls);
    expect(b.body.amount).toBe(70000);
    expect(b.body.client_uuid).not.toBe(a.body.client_uuid);
    // ... va u O'TDI: forma tozalandi, xato yo'q
    await waitFor(() => expect((screen.getByPlaceholderText(/summa|сумма/i) as HTMLInputElement).value).toBe(""));
  });

  // ── FX3-B.3: AYNI amal ataylab IKKI MARTA kiritilsa — IKKI yozuv ─────────
  it("muvaffaqiyatdan keyin kalit YANGILANADI — aynan bir xil amal ikki marta yoziladi", async () => {
    const state = { cur: shift("s1") };
    const calls = mockApi(routes(state, () => ({ ok: true })));
    renderApp(<Shift />);
    await screen.findByTestId("cashop-submit");
    await qoshish("50000");
    await waitFor(() => expect(cashCalls(calls).length).toBe(1));
    await waitFor(() => expect((screen.getByPlaceholderText(/summa|сумма/i) as HTMLInputElement).value).toBe(""));

    await qoshish("50000");   // AYNI amal, ataylab ikkinchi marta
    await waitFor(() => expect(cashCalls(calls).length).toBe(2));
    const [a, b] = cashCalls(calls);
    expect(a.body.amount).toBe(50000);
    expect(b.body.amount).toBe(50000);
    expect(b.body.client_uuid).not.toBe(a.body.client_uuid);
  });

  it("server «duplicate» desa forma jimgina tozalanmaydi — kassirga aytiladi", async () => {
    const state = { cur: shift("s1") };
    const calls = mockApi(routes(state, () => ({ ok: true, duplicate: true })));
    renderApp(<Shift />);
    await screen.findByTestId("cashop-submit");
    await qoshish("50000");
    await waitFor(() => expect(cashCalls(calls).length).toBe(1));
    expect(await screen.findByTestId("cashop-replay")).toBeTruthy();
  });

  // ── FX3-B.3: natija NOMA'LUM bo'lib smena almashsa — jimgina tashlab ketilmaydi ──
  it("natija noma'lum bo'lib smena almashsa kassir OGOHLANTIRILADI", async () => {
    const state = { cur: shift("s1") };
    const calls = mockApi(routes(state, () => ({ __status: 502, detail: "Bad gateway" })));
    renderApp(<Shift />);
    await screen.findByTestId("cashop-submit");
    await qoshish("70000");
    await waitFor(() => expect(cashCalls(calls).length).toBe(1));
    expect(screen.queryByTestId("cashop-carry")).toBeNull();

    state.cur = shift("s2");     // smena almashdi — oldingi urinish natijasi NOMA'LUM qoldi
    await userEvent.click(screen.getByTestId("cashop-payin"));
    await waitFor(async () => {
      await qoshish();
      expect(screen.queryByTestId("cashop-carry")).not.toBeNull();
    });
  });

  it("aniq rad javobi (4xx) ogohlantirish qoldirmaydi — hech narsa yozilmagani MA'LUM", async () => {
    const state = { cur: shift("s1") };
    const calls = mockApi(routes(state, () => ({ __status: 400, detail: "Kassada yetarli naqd yo'q (mavjud: 0)" })));
    renderApp(<Shift />);
    await screen.findByTestId("cashop-submit");
    await qoshish("70000");
    await waitFor(() => expect(cashCalls(calls).length).toBe(1));

    state.cur = shift("s2");
    await userEvent.click(screen.getByTestId("cashop-payin"));
    await waitFor(async () => {
      await qoshish();
      expect(cashCalls(calls).length).toBeGreaterThan(1);
    });
    expect(screen.queryByTestId("cashop-carry")).toBeNull();
  });
});
