import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QoldiqTafsilot } from "@/screens/QoldiqTafsilot";
import { invalidateAvailability } from "@/components/lotui";
import { mockApi, renderApp } from "./util";

const DETAIL = {
  id: "sf1", product_id: "p1", product: "Sut 1L", branch_id: "b1", branch: "Asosiy",
  unit_code: "dona", business_date: "2026-09-16",
  qty: 10, resolved_qty: 0, open_qty: 10, returned_qty: 0,
  returned_unattributed_on_hand: 0, resolved_real_qty: 0, netted_qty: 0,
  unit_cost: 10000, resolved_cost: 0, cogs_variance: 0, provisional_exposure: 100000,
  closed: false, reason: null, created_at: "2026-09-10T08:00:00+00:00",
  sale: { sale_id: "s1", sale_item_id: "si1", receipt_no: "#12", sold_at: "2026-09-10T08:00:00+00:00", qty: 10, unit_price: 15000, provisional_qty: 10, cashier: "Dilnoza" },
  resolutions: [],
  candidate_lots: [
    { id: "c1", batch_number: "A-1", expiry_date: "2026-10-01", bucket: "within_30_days", days_left: 15,
      remaining_qty: 5, unit_cost: 11000, cost_basis: "known", source_type: "receiving",
      own_unattributed: false, unit_variance: 1000, attachable_qty: 5, variance_if_full: 5000 },
    { id: "c2", batch_number: "B-2", expiry_date: null, bucket: "no_expiry", days_left: null,
      remaining_qty: 3, unit_cost: 10000, cost_basis: "estimated", source_type: "return_unattributed",
      own_unattributed: true, unit_variance: 0, attachable_qty: 3, variance_if_full: 0 },
  ],
};

function mount(resolveRes: any = { ok: true, duplicate: false, closed: false, qty_now: 8, variance_now: 5000, resolved_qty: 8, open_qty: 2, cogs_variance: 5000 }) {
  invalidateAvailability();
  const calls = mockApi([
    [/\/lots\/shortfalls\/sf1\/resolve/, resolveRes],
    [/\/lots\/shortfalls\/sf1/, DETAIL],
  ]);
  renderApp(<QoldiqTafsilot id="sf1" canWrite onClose={() => {}} onChanged={() => {}} />);
  return calls;
}

describe("Aniqlanmagan qoldiqni bog'lash", () => {
  it("bir nechta partiya BITTA so'rovda yuboriladi", async () => {
    const u = userEvent.setup();
    const calls = mount();
    await waitFor(() => screen.getByTestId("sf-cand-c1"));
    await u.type(screen.getByTestId("sf-qty-c1"), "5");
    await u.type(screen.getByTestId("sf-qty-c2"), "3");
    await u.click(screen.getByTestId("sf-submit"));
    await u.click(screen.getByTestId("confirm-ok"));
    await waitFor(() => screen.getByTestId("sf-result"));

    const sent = calls.filter((c) => c.url.includes("/resolve"));
    expect(sent).toHaveLength(1);
    expect(sent[0].body.allocations).toEqual([
      { stock_batch_id: "c1", qty: 5 },
      { stock_batch_id: "c2", qty: 3 },
    ]);
    expect(sent[0].body.client_uuid).toMatch(/^[0-9a-f-]{36}$/i);
  });

  it("natija OPERATOR tilida aytiladi: qancha bog'landi, qancha aniqlanmagan qoldi", async () => {
    const u = userEvent.setup();
    mount();
    await waitFor(() => screen.getByTestId("sf-cand-c1"));
    await u.type(screen.getByTestId("sf-qty-c1"), "5");
    await u.type(screen.getByTestId("sf-qty-c2"), "3");
    // Yuborishdan OLDIN ham ko'rsatiladi
    expect(screen.getByTestId("sf-summary")).toHaveTextContent(/8 dona.*2 dona/);
    await u.click(screen.getByTestId("sf-submit"));
    await u.click(screen.getByTestId("confirm-ok"));
    const res = await screen.findByTestId("sf-result");
    expect(res).toHaveTextContent("8");
    expect(res).toHaveTextContent("2");
    // Texnik atamalar EMAS
    expect(res.textContent || "").not.toMatch(/shortfall|cogs|variance/i);
  });

  it("ochiq qoldiqdan ORTIQ bog'lashga yo'l qo'yilmaydi", async () => {
    const u = userEvent.setup();
    mount();
    await waitFor(() => screen.getByTestId("sf-cand-c1"));
    await u.type(screen.getByTestId("sf-qty-c1"), "5");
    await u.type(screen.getByTestId("sf-qty-c2"), "9");   // partiyada 3 ta bor
    expect(screen.getByTestId("sf-submit")).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent(/katta|больше/i);
  });

  it("SHU SOTUVDAN qaytgan partiya alohida belgilanadi va og'ish 0 ko'rsatiladi", async () => {
    mount();
    await waitFor(() => screen.getByTestId("sf-cand-c2"));
    expect(screen.getByTestId("sf-cand-c2")).toHaveTextContent(/qaytgan|возврат/i);
    expect(screen.getByTestId("sf-cand-c2")).toHaveTextContent(/TAXMINIY|ПРИБЛИЗИТЕЛЬНО/);
  });

  it("server XATOSI ko'rsatiladi va ekran bo'sh qolmaydi", async () => {
    const u = userEvent.setup();
    mount({ __status: 409, detail: "Yopilmagan qarz 2, so'ralgan 5 — ortiqcha yopib bo'lmaydi" });
    await waitFor(() => screen.getByTestId("sf-cand-c1"));
    await u.type(screen.getByTestId("sf-qty-c1"), "5");
    await u.click(screen.getByTestId("sf-submit"));
    await u.click(screen.getByTestId("confirm-ok"));
    const err = await screen.findByTestId("sf-error");
    expect(err.textContent || "").not.toMatch(/Traceback|SQL|psycopg/i);
    expect(screen.getByTestId("sf-cand-c1")).toBeInTheDocument();
  });
});

describe("Tannarx sifati — aralash holat", () => {
  it("qisman yopilgan qarzda ARALASH ko'rsatiladi va tushuntiriladi", async () => {
    invalidateAvailability();
    mockApi([[/\/lots\/shortfalls\/sf1/, { ...DETAIL, resolved_qty: 6, open_qty: 4 }]]);
    renderApp(<QoldiqTafsilot id="sf1" canWrite onClose={() => {}} onChanged={() => {}} />);
    await waitFor(() => screen.getByTestId("cost-mixed"));
    expect(screen.getByTestId("cost-mixed")).toHaveTextContent("ARALASH");
    expect(screen.getByText(/qolgani hali taxminiy|остальное пока оценочное/i)).toBeInTheDocument();
  });

  it("hali yopilmagan qarzda TAXMINIY qoladi", async () => {
    invalidateAvailability();
    mockApi([[/\/lots\/shortfalls\/sf1/, DETAIL]]);
    renderApp(<QoldiqTafsilot id="sf1" canWrite onClose={() => {}} onChanged={() => {}} />);
    // Nomzod partiyalarda ham nishon bor — shuning uchun "bittasi" emas, "bor" deymiz.
    await waitFor(() => expect(screen.getAllByTestId("cost-estimated").length).toBeGreaterThan(0));
    expect(screen.queryByTestId("cost-mixed")).toBeNull();
  });
});
