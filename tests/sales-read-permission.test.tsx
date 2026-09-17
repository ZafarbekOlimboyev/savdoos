import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QoldiqTafsilot } from "@/screens/QoldiqTafsilot";
import { Returns } from "@/screens/Returns";
import { invalidateAvailability } from "@/components/lotui";
import { mockApi, renderApp } from "./util";

/**
 * SOTUV HUJJATI RUXSATI — UI TOMONI.
 *
 * ⚠️  Server qoidasining o'zi backend testlarida (`test_sales_read_permissions.py`).
 *     Bu yerda faqat UI serverning «ruxsat yo'q» javobini «hujjat yo'q» bilan
 *     ADASHTIRMASLIGI tekshiriladi: ikkalasida ham qiymat null yoki xato keladi.
 */

const SALE = {
  sale_id: "s1", sale_item_id: "si1", receipt_no: "#12", sold_at: "2026-09-10T08:00:00+00:00",
  qty: 10, unit_price: 15000, provisional_qty: 10, cashier: "Dilnoza",
};

const DETAIL = {
  id: "sf1", product_id: "p1", product: "Sut 1L", branch_id: "b1", branch: "Asosiy",
  unit_code: "dona", business_date: "2026-09-16",
  qty: 10, resolved_qty: 0, open_qty: 10, returned_qty: 0,
  returned_unattributed_on_hand: 0, resolved_real_qty: 0, netted_qty: 0,
  unit_cost: 10000, resolved_cost: 0, cogs_variance: 0, provisional_exposure: 100000,
  closed: false, reason: null, created_at: "2026-09-10T08:00:00+00:00",
  sale: SALE, redacted: { sales: false },
  resolutions: [], candidate_lots: [],
};

// Server sotuv ruxsatisiz shunday javob beradi: KALITLAR qoladi, qiymatlar null.
const YOPIQ_SALE = { ...SALE, sale_id: null, sale_item_id: null, receipt_no: null, unit_price: null, cashier: null };

function mountSf(detail: any) {
  invalidateAvailability();
  mockApi([[/\/lots\/shortfalls\/sf1/, detail]]);
  renderApp(<QoldiqTafsilot id="sf1" canWrite={false} onClose={() => {}} onChanged={() => {}} />);
}

describe("Qarz tafsiloti — chek raqami ruxsat bilan yopilganda", () => {
  it("ruxsatsiz null «Ruxsat yo'q» deb ko'rsatiladi, «—» emas", async () => {
    mountSf({ ...DETAIL, sale: YOPIQ_SALE, redacted: { sales: true } });
    const el = await screen.findByTestId("sf-receipt");
    expect(el.textContent || "").toMatch(/^Ruxsat yo'q · /);
    expect(el.textContent || "").not.toMatch(/^—/);
    // Kassir ham yopiq — satr umuman chizilmaydi.
    expect(screen.queryByText("Dilnoza")).toBeNull();
  });

  it("ruscha interfeysda ham tarjima qilingan belgi chiqadi", async () => {
    invalidateAvailability();
    mockApi([[/\/lots\/shortfalls\/sf1/, { ...DETAIL, sale: YOPIQ_SALE, redacted: { sales: true } }]]);
    renderApp(<QoldiqTafsilot id="sf1" canWrite={false} onClose={() => {}} onChanged={() => {}} />, { lang: "ru" });
    const el = await screen.findByTestId("sf-receipt");
    expect(el.textContent || "").toMatch(/^Скрыто \(нет прав\) · /);
  });

  it("NEGATIV NAZORAT: ruxsat BOR, chek raqami haqiqatan yo'q — «—» qoladi", async () => {
    mountSf({ ...DETAIL, sale: { ...SALE, receipt_no: null }, redacted: { sales: false } });
    const el = await screen.findByTestId("sf-receipt");
    expect(el.textContent || "").toMatch(/^— · /);
  });

  it("eski server (bayroqsiz) — «—», ruxsat belgisi o'ylab topilmaydi", async () => {
    const { redacted: _r, ...eski } = DETAIL;
    mountSf({ ...eski, sale: { ...SALE, receipt_no: null } });
    const el = await screen.findByTestId("sf-receipt");
    expect(el.textContent || "").toMatch(/^— · /);
  });

  it("to'liq ruxsatda chek raqami va kassir ko'rinadi", async () => {
    mountSf(DETAIL);
    const el = await screen.findByTestId("sf-receipt");
    expect(el.textContent || "").toMatch(/^#12 · /);
    expect(screen.getByText("Dilnoza")).toBeInTheDocument();
  });
});

const RUXSAT_403 = { __status: 403, detail: "Ruxsat yo'q: sotuvlar.view / hisobot.view" };

async function findReceipt(findRes: any, lang: "uz" | "ru") {
  const u = userEvent.setup();
  const calls = mockApi([
    [/\/sales\/find/, findRes],
    [/\/sales\?limit=8/, []],
  ]);
  renderApp(<Returns />, { lang });
  const input = screen.getByRole("textbox");
  await u.type(input, "#1288{Enter}");
  await waitFor(() => expect(calls.some((c) => c.url.includes("/sales/find"))).toBe(true));
  return calls;
}

describe("Qaytarish — chek qidiruvida 403", () => {
  it("403 da serverning RUXSAT xabari ko'rsatiladi, «chek topilmadi» emas (ru)", async () => {
    await findReceipt(RUXSAT_403, "ru");
    expect(await screen.findByText("Нет доступа: sotuvlar.view / hisobot.view")).toBeInTheDocument();
    expect(screen.queryByText("Чек не найден")).toBeNull();
  });

  it("403 — o'zbekcha interfeysda asl matn", async () => {
    await findReceipt(RUXSAT_403, "uz");
    expect(await screen.findByText("Ruxsat yo'q: sotuvlar.view / hisobot.view")).toBeInTheDocument();
    expect(screen.queryByText("Chek topilmadi")).toBeNull();
  });

  it("NEGATIV NAZORAT: 404 avvalgidek «chek topilmadi»", async () => {
    await findReceipt({ __status: 404, detail: "Chek topilmadi" }, "ru");
    expect(await screen.findByText("Чек не найден")).toBeInTheDocument();
    expect(screen.queryByText(/Нет доступа/)).toBeNull();
  });

  it("boshqa xato (500) ham avvalgidek «chek topilmadi» — faqat 403 ajratiladi", async () => {
    await findReceipt({ __status: 500, detail: "Internal Server Error" }, "ru");
    expect(await screen.findByText("Чек не найден")).toBeInTheDocument();
    expect(screen.queryByText("Internal Server Error")).toBeNull();
  });

  it("qidiruv so'rovi AYNAN kiritilgan raqam bilan yuboriladi", async () => {
    const calls = await findReceipt(RUXSAT_403, "uz");
    const f = calls.find((c) => c.url.includes("/sales/find"))!;
    expect(decodeURIComponent(f.url)).toContain("q=#1288");
  });
});
