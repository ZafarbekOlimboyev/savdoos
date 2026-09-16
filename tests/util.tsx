import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { render } from "@testing-library/react";
import { vi } from "vitest";
import { useLang } from "@/store/lang";

export interface Call { url: string; method: string; body: any }

/**
 * Tarmoqni almashtiradi: HAR so'rov yozib olinadi, javob esa `routes` dagi
 * birinchi MOS naqsh bo'yicha beriladi.
 *
 * ⚠️  Sinov serverni taqlid qiladi, lekin uning QOIDALARINI emas: bu yerda
 *     tekshiriladigan narsa — UI serverga NIMA yuborayotgani va javobni
 *     qanday ko'rsatayotgani. Server qoidalarining o'zi backend testlarida.
 */
export function mockApi(routes: [RegExp, any | ((c: Call) => any)][]): Call[] {
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
        if (value && value.__status && value.__status >= 400) {
          return new Response(JSON.stringify({ detail: value.detail }), {
            status: value.__status, headers: { "Content-Type": "application/json" },
          });
        }
        return new Response(JSON.stringify(value), {
          status: 200, headers: { "Content-Type": "application/json" },
        });
      }
    }
    return new Response(JSON.stringify({ detail: "mock: " + call.url }), { status: 404 });
  }));
  return calls;
}

export function renderApp(ui: ReactElement, opts: { lang?: "uz" | "ru"; route?: string } = {}) {
  useLang.getState().set(opts.lang || "uz");
  return render(<MemoryRouter initialEntries={[opts.route || "/"]}>{ui}</MemoryRouter>);
}

export const availability = (over: Record<string, any> = {}) => ({
  activation_allowed: true, environment: "dev", schema_ready: true, schema_problem_count: 0,
  tracked_products: 3,
  permissions: { view: true, edit: true, settings: true, reports: true, purchases: true },
  can_enable: true, can_write: true,
  branches: [{ id: "b1", name: "Asosiy", timezone: "Asia/Tashkent", timezone_supported: true, timezone_confirmed: true }],
  supported_timezones: ["Asia/Tashkent"],
  ...over,
});

export const lot = (over: Record<string, any> = {}) => ({
  id: "l1", branch_id: "b1", branch: "Asosiy", product_id: "p1", product: "Sut 1L",
  unit_code: "dona", batch_number: "A-1", expiry_date: "2026-10-01",
  bucket: "within_30_days", expired: false, days_left: 15,
  received_qty: 10, remaining_qty: 6, unit_cost: 12000, value: 72000,
  cost_basis: "known", status: "open", source_type: "receiving",
  supplier_id: "s1", supplier: "Ta'minotchi", received_at: "2026-09-01T10:00:00+00:00",
  ...over,
});

export const lotList = (lots: any[]) => ({
  total: lots.length, limit: 50, offset: 0,
  business_dates: { b1: "2026-09-16" }, lots,
});
