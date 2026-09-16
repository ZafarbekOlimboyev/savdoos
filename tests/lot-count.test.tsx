import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Inventarizatsiya } from "@/screens/Inventarizatsiya";
import { invalidateAvailability } from "@/components/lotui";
import { availability, lot, lotList, mockApi, renderApp } from "./util";

const LOTS = lotList([
  lot({ id: "l1", batch_number: "A-1", remaining_qty: 6, expiry_date: "2026-10-01" }),
  lot({ id: "l2", batch_number: "B-2", remaining_qty: 4, expiry_date: "2026-11-01" }),
]);

function mount() {
  invalidateAvailability();
  const calls = mockApi([
    [/\/lots\/availability/, availability()],
    [/\/lots\/batches/, LOTS],
    [/\/products\?/, [{ id: "p1", name: "Sut 1L", unit_code: "dona", stock: 10 }]],
    [/\/inventory\/count/, { ok: true, changed: 1, results: [{ product: "Sut 1L", product_id: "p1", old: 10, counted: 9, diff: -1, lots: { decrements: [], surpluses: [], created: [{ stock_batch_id: "n1", qty: 3, unit_cost: 5000, batch_no: "YANGI", expiry_date: "2026-12-01", source_type: "adjustment" }] } }] }],
  ]);
  renderApp(<Inventarizatsiya />);
  return calls;
}

async function pick(u: ReturnType<typeof userEvent.setup>) {
  await u.type(screen.getByTestId("cnt-product-input"), "Sut");
  await waitFor(() => screen.getByTestId("cnt-product-opt-p1"), { timeout: 3000 });
  await u.click(screen.getByTestId("cnt-product-opt-p1"));
  await waitFor(() => screen.getByTestId("cnt-lot-l1"));
}

describe("Partiya darajasidagi inventarizatsiya", () => {
  it("SANALMAGAN partiya yuborilmaydi va NOL deb tushunilmaydi", async () => {
    const u = userEvent.setup();
    const calls = mount();
    await pick(u);
    await u.type(screen.getByTestId("cnt-qty-l1"), "5");    // faqat A-1 sanaldi

    // Ekran ochiq aytadi: ikkinchi partiya TEGILMAYDI.
    expect(screen.getByTestId("cnt-diff-l2")).toHaveTextContent(/tegilmaydi|не трогаем/i);
    // Jami = tegilmagan 4 + sanalgan 5 = 9
    expect(screen.getByTestId("cnt-summary")).toHaveTextContent("9");

    await u.click(screen.getByTestId("cnt-submit"));
    await u.click(screen.getByTestId("confirm-ok"));
    await waitFor(() => screen.getByTestId("count-done"));

    const sent = calls.filter((c) => c.url.includes("/inventory/count"));
    expect(sent).toHaveLength(1);
    expect(sent[0].body.items[0].counted).toBe(9);
    expect(sent[0].body.items[0].lots).toEqual([{ stock_batch_id: "l1", counted: 5 }]);
  });

  it("FARQ har partiya uchun alohida ko'rsatiladi", async () => {
    const u = userEvent.setup();
    mount();
    await pick(u);
    await u.type(screen.getByTestId("cnt-qty-l1"), "4");   // 6 -> 4
    await u.type(screen.getByTestId("cnt-qty-l2"), "7");   // 4 -> 7
    expect(screen.getByTestId("cnt-diff-l1")).toHaveTextContent("-2");
    expect(screen.getByTestId("cnt-diff-l2")).toHaveTextContent("+3");
  });

  it("javondan topilgan YANGI partiya o'z muddati va narxi bilan yuboriladi", async () => {
    const u = userEvent.setup();
    const calls = mount();
    await pick(u);
    await u.click(screen.getByTestId("cnt-add-new"));
    await u.type(screen.getByTestId("cnt-new-qty"), "3");
    await u.type(screen.getByTestId("cnt-new-batch"), "YANGI");
    await u.type(screen.getByTestId("cnt-new-cost"), "5000");
    const date = screen.getByTestId("cnt-new-expiry") as HTMLInputElement;
    await u.clear(date);
    await u.type(date, "2026-12-01");

    await u.click(screen.getByTestId("cnt-submit"));
    await u.click(screen.getByTestId("confirm-ok"));
    await waitFor(() => screen.getByTestId("count-done"));

    const body = calls.filter((c) => c.url.includes("/inventory/count"))[0].body;
    expect(body.items[0].new_lots).toEqual([
      { qty: 3, unit_cost: 5000, batch_no: "YANGI", expiry_date: "2026-12-01", reason: undefined },
    ]);
    // Jami = tegilmagan 10 + yangi 3
    expect(body.items[0].counted).toBe(13);
    expect(screen.getByTestId("count-done")).toHaveTextContent("1");   // 1 ta yangi partiya
  });

  it("muddat kuzatiladigan tovarda MUDDATSIZ yangi partiya ogohlantiradi", async () => {
    const u = userEvent.setup();
    mount();
    await pick(u);
    await u.click(screen.getByTestId("cnt-add-new"));
    await u.type(screen.getByTestId("cnt-new-qty"), "2");
    expect(screen.getByRole("alert")).toHaveTextContent(/muddatini ko'rsating|укажите срок/i);
  });
});
