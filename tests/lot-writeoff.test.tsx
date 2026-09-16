import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Hisobdan } from "@/screens/Hisobdan";
import { invalidateAvailability } from "@/components/lotui";
import { availability, lot, lotList, mockApi, renderApp } from "./util";

const LOTS = lotList([
  lot({ id: "l1", batch_number: "A-1", remaining_qty: 6, unit_cost: 12000 }),
  lot({ id: "l2", batch_number: "B-2", remaining_qty: 4, unit_cost: 9000, bucket: "expired", expired: true, days_left: -3 }),
]);

function mount(over: Record<string, any> = {}) {
  invalidateAvailability();
  const calls = mockApi([
    [/\/lots\/availability/, availability(over)],
    [/\/lots\/batches/, LOTS],
    [/\/products\?/, [{ id: "p1", name: "Sut 1L", unit_code: "dona", stock: 10 }]],
    [/\/inventory\/writeoff/, { ok: true }],
  ]);
  renderApp(<Hisobdan />);
  return calls;
}

async function pickProduct(u: ReturnType<typeof userEvent.setup>) {
  await u.type(screen.getByTestId("wo-product-input"), "Sut");
  await waitFor(() => screen.getByTestId("wo-product-opt-p1"), { timeout: 3000 });
  await u.click(screen.getByTestId("wo-product-opt-p1"));
  await waitFor(() => screen.getByTestId("wo-lot-l1"));
}

describe("Hisobdan chiqarish", () => {
  it("TASDIQLAMAGUNCHA serverga hech narsa yuborilmaydi va matn AYNAN ogohlantiradi", async () => {
    const u = userEvent.setup();
    const calls = mount();
    await pickProduct(u);
    await u.type(screen.getByTestId("wo-qty-l2"), "2");
    await u.click(screen.getByTestId("wo-submit"));

    // Modal ochildi — lekin so'rov KETMADI.
    expect(screen.getByTestId("confirm")).toBeInTheDocument();
    expect(screen.getByText(/qoldiqni kamaytiradi va qaytarib bo'lmaydigan audit yozuvi/i)).toBeInTheDocument();
    expect(calls.some((c) => c.url.includes("/inventory/writeoff"))).toBe(false);

    // Bekor qilinsa ham yuborilmaydi.
    await u.click(screen.getByTestId("confirm-cancel"));
    expect(screen.queryByTestId("confirm")).toBeNull();
    expect(calls.some((c) => c.url.includes("/inventory/writeoff"))).toBe(false);
  });

  it("tasdiqlangach AYNAN tanlangan partiyalar yuboriladi", async () => {
    const u = userEvent.setup();
    const calls = mount();
    await pickProduct(u);
    await u.type(screen.getByTestId("wo-qty-l1"), "3");
    await u.type(screen.getByTestId("wo-qty-l2"), "1");
    await u.click(screen.getByTestId("wo-submit"));
    await u.click(screen.getByTestId("confirm-ok"));

    await waitFor(() => screen.getByTestId("writeoff-done"));
    const sent = calls.filter((c) => c.url.includes("/inventory/writeoff"));
    expect(sent).toHaveLength(1);
    expect(sent[0].body.qty).toBe(4);
    expect(sent[0].body.lots).toEqual([
      { stock_batch_id: "l1", qty: 3 },
      { stock_batch_id: "l2", qty: 1 },
    ]);
    expect(sent[0].body.client_uuid).toMatch(/^[0-9a-f-]{36}$/i);
  });

  it("SO'ROV KETAYOTGANDA qayta bosilsa IKKINCHI so'rov ketmaydi", async () => {
    // Server sekin javob beradi — aynan shu oraliqda operator yana bosadi.
    const u = userEvent.setup();
    invalidateAvailability();
    const calls = mockApi([
      [/\/lots\/availability/, availability()],
      [/\/lots\/batches/, LOTS],
      [/\/products\?/, [{ id: "p1", name: "Sut 1L", unit_code: "dona", stock: 10 }]],
      [/\/inventory\/writeoff/, () => new Promise((r) => setTimeout(() => r({ ok: true }), 250))],
    ]);
    renderApp(<Hisobdan />);
    await pickProduct(u);
    await u.type(screen.getByTestId("wo-qty-l1"), "2");
    await u.click(screen.getByTestId("wo-submit"));
    const ok = screen.getByTestId("confirm-ok");
    await u.click(ok);
    expect(ok).toBeDisabled();                 // ikkinchi bosish IMKONSIZ
    await u.click(ok, { pointerEventsCheck: 0 });
    await waitFor(() => screen.getByTestId("writeoff-done"), { timeout: 3000 });
    expect(calls.filter((c) => c.url.includes("/inventory/writeoff"))).toHaveLength(1);
  });

  it("partiya qoldig'idan ORTIQ miqdor yuborishga yo'l qo'yilmaydi", async () => {
    const u = userEvent.setup();
    mount();
    await pickProduct(u);
    await u.type(screen.getByTestId("wo-qty-l2"), "9");   // qoldiq 4
    expect(screen.getByTestId("wo-submit")).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent(/partiya qoldig'idan katta|больше остатка/i);
  });

  it("yozuv huquqi yo'q bo'lsa SABABI aytiladi va tugma yopiq", async () => {
    const u = userEvent.setup();
    mount({ can_write: false, permissions: { view: true, edit: false, settings: false, reports: true, purchases: false } });
    await pickProduct(u);
    expect(await screen.findByTestId("write-closed")).toHaveTextContent(/huquqi yo'q|нет прав/i);
    await u.type(screen.getByTestId("wo-qty-l1"), "1");
    expect(screen.getByTestId("wo-submit")).toBeDisabled();
  });
});

describe("Miqdor aniqligi (server bilan bir xil yaxlitlash)", () => {
  it("q3 — ROUND_HALF_UP, ikkilik xatosiz (0.5005 -> 0.501, 1.1+2.2 -> 3.3)", async () => {
    const { q3 } = await import("@/lib/lots");
    expect(q3("0.5005")).toBe(0.501);          // n*1000 bilan 0.5 chiqardi
    expect(q3(1.1 + 2.2)).toBe(3.3);
    expect(q3("12.3456")).toBe(12.346);
    expect(q3(1e-7)).toBe(0);                  // «1e-7» ko'rinishi
    expect(q3("")).toBe(0);
  });

  it("har partiya AVVAL yaxlitlanib yuboriladi — jami yaxlitlangan qismlar yig'indisi", async () => {
    const u = userEvent.setup();
    const calls = mount();
    await pickProduct(u);
    await u.type(screen.getByTestId("wo-qty-l1"), "0.5005");
    await u.click(screen.getByTestId("wo-submit"));
    await u.click(screen.getByTestId("confirm-ok"));
    await waitFor(() => screen.getByTestId("writeoff-done"));
    const body = calls.filter((c) => c.url.includes("/inventory/writeoff"))[0].body;
    expect(body.lots[0].qty).toBe(0.501);
    expect(body.qty).toBe(0.501);              // server bilan AYNAN bir xil
  });
});
