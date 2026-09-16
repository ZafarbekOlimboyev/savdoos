import { describe, expect, it } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Products } from "@/screens/Products";
import { mockApi, renderApp, type Call } from "./util";

// ⚠️  KUZATUVLI TOVARDA `expiry_date` MUZLAGAN. Holat ustuni allaqachon
//     `productExpiry` ni o'qiydi; muddat katagi va tahrir formasi ham AYNI
//     qoidaga bo'ysunmasa, bitta qatorda «Yaxshi» holat yonida qizil, eskirgan
//     sana turadi — bir ma'noli ikki xil muddat.
const OLD = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
const LATER = new Date(Date.now() + 200 * 86400000).toISOString().slice(0, 10);
const dmy = (d: string) => d.split("-").reverse().join(".");

const prod = (over: Record<string, any> = {}) => ({
  id: "p1", article_code: "A-1", sku: null, name: "Sut 1L", category_id: null,
  base_buy_price: 50, base_sell_price: 100, stock: 5, min_stock: 0, unit_code: "dona",
  expiry_date: null, track_lots: false, barcodes: [], ...over,
});
const full = (over: Record<string, any> = {}) => ({
  ...prod(over), profit_unit: 50, margin_pct: 50,
  sales_7d: { qty: 0, revenue: 0, profit: 0 }, sales_30d: { qty: 0, revenue: 0, profit: 0 },
  last_sold_at: null, month_in: 0, month_out: 0, is_weighted: false, plu_code: null,
  scale_sync: false, created_by_name: "Ega", created_at: null,
});

function mount(list: any[], detail?: any) {
  const calls = mockApi([
    [/\/products\/p1$/, (c: Call) => (c.method === "PATCH" ? { ok: true } : detail)],
    [/\/products(\?|$)/, list],
    [/\/inventory\/movements/, []],
    [/\/categories/, []],
    [/\/suppliers/, []],
  ]);
  renderApp(<Products />);
  return calls;
}

async function openEdit() {
  const u = userEvent.setup();
  await u.click(await screen.findByText("Sut 1L"));
  await waitFor(() => expect(screen.getAllByText("Sut 1L").length).toBeGreaterThan(0));
  await u.click(await screen.findByRole("button", { name: /Tahrirlash/ }));
  await screen.findByText("Mahsulotni tahrirlash");
  return u;
}

describe("Mahsulotlar — kuzatuvli tovarda muzlagan muddat ko'rinmaydi", () => {
  it("jadval katagi: kuzatuvli — «Partiyalarda», kuzatuvsiz — o'z sanasi", async () => {
    mount([prod({ id: "p1", expiry_date: OLD, track_lots: true, track_expiry: true }),
           prod({ id: "p2", name: "Non", expiry_date: LATER })]);
    const tracked = await screen.findByTestId("prod-expiry-p1");
    expect(tracked).toHaveTextContent("Partiyalarda");
    expect(tracked).not.toHaveTextContent(dmy(OLD));
    // NEGATIV NAZORAT: kuzatuvsiz tovar katagi sanani HAMON ko'rsatadi.
    expect(screen.getByTestId("prod-expiry-p2")).toHaveTextContent(dmy(LATER));
    // Muzlagan o'tgan sana «Muddati o'tgan» sanog'iga ham tushmaydi.
    const row = tracked.closest("tr")!;
    expect(within(row).queryByText("Muddati o'tgan")).toBeNull();
  });

  it("tahrir formasi: kuzatuvli tovarda sana maydoni YO'Q va PATCH muddatni yubormaydi", async () => {
    const calls = mount([prod({ expiry_date: OLD, track_lots: true, track_expiry: true })],
                        full({ expiry_date: OLD, track_lots: true, track_expiry: true }));
    const u = await openEdit();
    expect(screen.getByTestId("edit-expiry-lots")).toHaveTextContent("Muddat partiyalarda yuritiladi");
    expect(screen.queryByTestId("edit-expiry")).toBeNull();
    await u.click(screen.getByRole("button", { name: "Saqlash" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    const patch = calls.find((c) => c.method === "PATCH")!;
    expect(patch.body).not.toHaveProperty("expiry_date");
  });

  it("muddat kuzatuvisiz yoqilgan tovar: «Partiyalarda» DEYILMAYDI — partiyalarda ham sana yo'q", async () => {
    const calls = mount([prod({ expiry_date: OLD, track_lots: true, track_expiry: false })],
                        full({ expiry_date: OLD, track_lots: true, track_expiry: false }));
    const cell = await screen.findByTestId("prod-expiry-p1");
    expect(cell).toHaveTextContent("—");
    expect(cell).not.toHaveTextContent("Partiyalarda");
    expect(cell).not.toHaveTextContent(dmy(OLD));
    const u = await openEdit();
    const note = screen.getByTestId("edit-expiry-lots");
    expect(note).toHaveTextContent("Bu tovarda muddat kuzatilmaydi");
    expect(note).not.toHaveTextContent("partiyalarda");
    await u.click(screen.getByRole("button", { name: "Saqlash" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(calls.find((c) => c.method === "PATCH")!.body).not.toHaveProperty("expiry_date");
  });

  it("NEGATIV NAZORAT: kuzatuvsiz tovarda sana maydoni bor va PATCH uni yuboradi", async () => {
    const calls = mount([prod({ expiry_date: LATER })], full({ expiry_date: LATER }));
    const u = await openEdit();
    expect(screen.getByTestId("edit-expiry")).toHaveValue(LATER);
    expect(screen.queryByTestId("edit-expiry-lots")).toBeNull();
    await u.click(screen.getByRole("button", { name: "Saqlash" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(calls.find((c) => c.method === "PATCH")!.body.expiry_date).toBe(LATER);
  });
});
