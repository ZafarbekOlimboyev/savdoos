import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { Dashboard } from "@/screens/Dashboard";
import { invalidateAvailability } from "@/components/lotui";
import { availability, mockApi, renderApp } from "./util";

// ⚠️  IKKI MANBA, BITTA EKRAN. Eski «E'tibor» bloki MAHSULOT ustunidan
//     (`products.expiry_date`), yangi kartalar esa PARTIYADAN (`/lots/alerts`)
//     sanaydi. Kuzatuv yoqilgach mahsulot ustuni MUZLAB qoladi — shu bois u
//     kuzatuvli tovarni UMUMAN sanamasligi shart.
const YESTERDAY = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
const NEXT_YEAR = new Date(Date.now() + 300 * 86400000).toISOString().slice(0, 10);

const OV = {
  period: "week", tz_hours: 5, kpi: { sales: 0, profit: 0, tx: 0, avg_check: 0 },
  delta: { sales: null, profit: null, tx: null, avg: null }, series: [], payments: [],
  credit_total: 0, top_products: [], cashiers: [], recent: [], branches: [], branch_count: 1,
  vat_on: false, vat_rate: 0,
};
const DASH = { debt: { total: 0, debtors: 0, paid_today: 0 }, low_stock: [] };
const ALERTS = {
  expiry: {
    expired: { lots: 3, qty: 12, value_at_risk: 100 },
    expires_today: { lots: 0, qty: 0, value_at_risk: 0 },
    within_7_days: { lots: 0, qty: 0, value_at_risk: 0 },
    within_30_days: { lots: 0, qty: 0, value_at_risk: 0 },
  },
  shortfalls: { open_count: 0, open_qty: 0, provisional_exposure_max: 0 },
  cost_quality: { estimated_lots: 0, unknown_cost_lots: 0, tracked_products: 1 },
  business_dates: {}, branches: 1,
};

function mount(products: any[], opts: { hist?: boolean } = {}) {
  invalidateAvailability();
  mockApi([
    [/\/settings/, opts.hist ? { history_1c: { source: "1C", from: "2025-01-01", to: "2025-12-31", revenue: 1, returns: 0, net: 1, purchases: 0, sales_rows: 1, buy_rows: 0, by_month: [], by_kassa: [], suppliers: [] } } : {}],
    [/\/reports\/overview/, OV],
    [/\/reports\/dashboard/, DASH],
    [/\/reports\/cashflow/, { in: { naqd_savdo: 0, qarz_qaytdi: 0, qoshimcha: 0, jami: 0 }, out: { xarajat: 0, inkassatsiya: 0, qaytarish: 0, beruvchiga: 0, jami: 0 }, opening: 0, kassada: 0 }],
    [/\/lots\/availability/, availability({ tracked_products: 1, section_visible: true, has_lot_data: true })],
    [/\/lots\/alerts/, ALERTS],
    [/\/products/, products],
  ]);
  renderApp(<Dashboard />);
}

const p = (over: any = {}) => ({ stock: 5, min_stock: 2, expiry_date: null, track_lots: false, ...over });

describe("Dashboard — muddat ikki marta sanalmasin", () => {
  it("KUZATUVSIZ mahsulot eski blokda sanaladi", async () => {
    mount([p({ expiry_date: YESTERDAY })]);
    await waitFor(() => expect(screen.getByTestId("att-expired")).toHaveTextContent("1"));
  });

  it("KUZATUVLI mahsulotning muzlagan sanasi eski blokka TUSHMAYDI", async () => {
    // Tovar kuzatuvga o'tgan: katalogdagi sana eski, haqiqat esa partiyalarda.
    mount([p({ expiry_date: YESTERDAY, track_lots: true })]);
    await waitFor(() => screen.getByTestId("lot-alert-cards"));
    // Kuzatuvsiz muddatli tovar qolmagani uchun plitkalar UMUMAN chizilmaydi.
    await waitFor(() => expect(screen.queryByTestId("att-expired")).toBeNull());
    expect(screen.getByTestId("lot-alert-alertExpired")).toHaveTextContent("3");
  });

  it("ARALASH katalogda eski blok FAQAT kuzatuvsizni sanaydi", async () => {
    mount([p({ expiry_date: YESTERDAY }), p({ expiry_date: YESTERDAY, track_lots: true }),
           p({ expiry_date: NEXT_YEAR, track_lots: true })]);
    // Mahsulotlar kelguncha plitka «0» bilan turadi — AYNAN «1» kelishini kutamiz (2 emas).
    await waitFor(() => expect(screen.getByTestId("att-expired")).toHaveTextContent("1"));
    // Kartalar ALOHIDA so'rovdan keladi — ular kelishini kutamiz.
    await waitFor(() => screen.getByTestId("lot-alert-alertExpired"));
    expect(screen.getByTestId("lot-alert-alertExpired")).toHaveTextContent("3");
  });

  it("partiyasiz kuzatuvli tovarda ham eski blok JIM turadi", async () => {
    mount([p({ expiry_date: YESTERDAY, track_lots: true, stock: 0 })]);
    await waitFor(() => screen.getByTestId("lot-alert-cards"));
    await waitFor(() => expect(screen.queryByTestId("att-expired")).toBeNull());
  });

  it("1C TARIXI rejimida ham partiya kartalari ko'rinadi", async () => {
    // ⚠️  Aynan birinchi jonli mijozda dashboard «tarix» rejimida ochiladi.
    mount([p({ track_lots: true })], { hist: true });
    await waitFor(() => screen.getByTestId("lot-alert-cards"));
    expect(screen.getByTestId("lot-alert-alertExpired")).toBeInTheDocument();
  });
});

describe("Dashboard — kuzatuvsiz do'konda ESKI xulq o'zgarmaydi", () => {
  it("birorta kuzatuvli tovar YO'Q bo'lsa muddat plitkalari AVVALGIDEK turadi (muddatsiz katalogda ham)", async () => {
    // Bugungi production (Fayzan): hech bir mahsulot kuzatuvli emas, ko'pida muddat yo'q.
    invalidateAvailability();
    mockApi([
      [/\/settings/, {}],
      [/\/reports\/overview/, OV],
      [/\/reports\/dashboard/, DASH],
      [/\/reports\/cashflow/, { in: { naqd_savdo: 0, qarz_qaytdi: 0, qoshimcha: 0, jami: 0 }, out: { xarajat: 0, inkassatsiya: 0, qaytarish: 0, beruvchiga: 0, jami: 0 }, opening: 0, kassada: 0 }],
      [/\/lots\/availability/, availability({ tracked_products: 0, has_lot_data: false, section_visible: false })],
      [/\/products/, [p({}), p({})]],
    ]);
    renderApp(<Dashboard />);
    await waitFor(() => screen.getByTestId("att-expired"));
    expect(screen.getByTestId("att-soon")).toHaveTextContent("0");
    expect(screen.getByTestId("att-expired")).toHaveTextContent("0");
    // Partiya kartalari kuzatuvsiz do'konda UMUMAN yo'q
    expect(screen.queryByTestId("lot-alert-cards")).toBeNull();
  });
});
