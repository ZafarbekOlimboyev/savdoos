import { beforeEach, describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { POSKassa } from "@/screens/POSKassa";
import { CACHE, cacheSet } from "@/lib/offline";
import { useAuth } from "@/store/auth";
import { useCart } from "@/store/cart";
import { mockApi, renderApp } from "./util";

// HAQIQIY SKANER YO'LI (do'kondagi nuqson, v0.7.1-store.3).
//
// Fizik skaner — bu klaviatura: u barkod belgilarini teradi va oxirida Enter yuboradi.
// Kassir mahsulotni GRID'dan bosib qo'shsa, o'sha tugma DOM fokusida qoladi. Keyingi skanda
// raqamlar hech qayerga tushmaydi (tugma matn qabul qilmaydi), oxirgi Enter esa FOKUSDAGI
// TUGMANI bosadi — ya'ni skanerlangan tovar emas, oldin bosilgan tovar yana qo'shiladi.
//
// Shu bois:
//   savat bo'sh  + FANTA skani -> hech narsa (fokusda tugma yo'q)
//   savat [COLA] + FANTA skani -> COLA x2 (COLA tugmasi fokusda), FANTA YO'Q
//
// INVARIANT: fizik skan FAQAT O'SHA skandan hal bo'lgan mahsulotni o'zgartirishi mumkin.

const COLA = {
  id: "p-cola", article_code: "COLA-1", name: "Cola", category_id: null,
  base_sell_price: 12000, stock: 50, barcodes: ["4780000001114"],
  plu_code: null, is_weighted: false, sold_qty: 10, is_active: true,
};
const FANTA = {
  id: "p-fanta", article_code: "FANTA-1", name: "Fanta", category_id: null,
  base_sell_price: 11000, stock: 40, barcodes: ["4780000002227"],
  plu_code: null, is_weighted: false, sold_qty: 5, is_active: true,
};
const CATALOG = [COLA, FANTA];

const items = () => useCart.getState().items;
const qty = (id: string) => items().find((i) => i.id === id)?.qty ?? 0;

/** Fizik skaner: belgilarni HOZIRGI fokusga teradi va Enter bilan tugatadi. */
async function physicalScan(user: ReturnType<typeof userEvent.setup>, code: string) {
  await user.keyboard(code + "{Enter}");
}

/** Kassir grid'dan mahsulotni BOSIB qo'shadi — tugma fokusda qoladi (do'kondagi holat). */
async function clickProduct(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.click(await screen.findByRole("button", { name: new RegExp(name) }));
}

beforeEach(() => {
  mockApi([
    [/\/products\b/, () => CATALOG],
    [/\/categories\b/, () => []],
    [/\/settings\b/, () => ({})],
    [/./, {}],
  ]);
  useCart.setState({ carts: [[]], active: 0, items: [] });
  useAuth.setState({
    token: "tok",
    employee: {
      id: "emp-1", full_name: "Dilnoza", role_code: "kassir", role_name: "Kassir",
      status: "active", branch_name: "Chilonzor filiali", permissions: ["kassa.sell"],
    },
  } as never);
  cacheSet(CACHE.products, CATALOG);
  cacheSet(CACHE.cats, []);
});

describe("Fizik skaner: skan FAQAT o'z mahsulotini o'zgartiradi", () => {
  it("1. savat bo'sh + B skani → [B x1]", async () => {
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await screen.findByRole("button", { name: /Cola/ });
    await physicalScan(user, FANTA.barcodes[0]);
    await waitFor(() => expect(items()).toHaveLength(1));
    expect(items()[0].id).toBe(FANTA.id);
    expect(qty(FANTA.id)).toBe(1);
  });

  it("2. DO'KONDAGI HOLAT: savat [A x1] (bosib qo'shilgan) + B skani → [A x1, B x1]", async () => {
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await clickProduct(user, "Cola");                 // COLA tugmasi endi FOKUSDA
    await waitFor(() => expect(qty(COLA.id)).toBe(1));
    await physicalScan(user, FANTA.barcodes[0]);
    await waitFor(() => expect(qty(FANTA.id)).toBe(1));
    expect(qty(COLA.id)).toBe(1);                     // COLA TEGILMAYDI
    expect(items()).toHaveLength(2);
  });

  it("3. savat [A x1, B x1] + B skani → [A x1, B x2]", async () => {
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await clickProduct(user, "Cola");
    await clickProduct(user, "Fanta");
    await physicalScan(user, FANTA.barcodes[0]);
    await waitFor(() => expect(qty(FANTA.id)).toBe(2));
    expect(qty(COLA.id)).toBe(1);
  });

  it("4. savat [A x1, B x1] + A skani → [A x2, B x1]", async () => {
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await clickProduct(user, "Cola");
    await clickProduct(user, "Fanta");                // FANTA tugmasi fokusda
    await physicalScan(user, COLA.barcodes[0]);
    await waitFor(() => expect(qty(COLA.id)).toBe(2));
    expect(qty(FANTA.id)).toBe(1);
  });

  it("5. savat [A x1] + A skani → [A x2]", async () => {
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await clickProduct(user, "Cola");
    await physicalScan(user, COLA.barcodes[0]);
    await waitFor(() => expect(qty(COLA.id)).toBe(2));
    expect(items()).toHaveLength(1);
  });

  it("6. savat [A x1] + NOMA'LUM barkod → [A x1] (oshmaydi)", async () => {
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await clickProduct(user, "Cola");
    await physicalScan(user, "4780000009999");
    await new Promise((r) => setTimeout(r, 150));
    expect(qty(COLA.id)).toBe(1);
    expect(items()).toHaveLength(1);
  });

  it("7. savat [A x1] + BUZUQ 27-etiketka → [A x1] (oshmaydi)", async () => {
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await clickProduct(user, "Cola");
    await physicalScan(user, "2700537004265");        // nazorat raqami buzuq
    await new Promise((r) => setTimeout(r, 150));
    expect(qty(COLA.id)).toBe(1);
    expect(items()).toHaveLength(1);
  });

  it("8. oxirgi qator o'chirilgach, savat bo'sh + B skani → [B x1]", async () => {
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await clickProduct(user, "Cola");
    await waitFor(() => expect(items()).toHaveLength(1));
    useCart.getState().remove(COLA.id);
    await waitFor(() => expect(items()).toHaveLength(0));
    await physicalScan(user, FANTA.barcodes[0]);
    await waitFor(() => expect(qty(FANTA.id)).toBe(1));
    expect(items()).toHaveLength(1);
  });

  it("9. savat tozalangach + B skani → [B x1]", async () => {
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await clickProduct(user, "Cola");
    await clickProduct(user, "Fanta");
    useCart.getState().clear();
    await waitFor(() => expect(items()).toHaveLength(0));
    await physicalScan(user, FANTA.barcodes[0]);
    await waitFor(() => expect(qty(FANTA.id)).toBe(1));
    expect(items()).toHaveLength(1);
  });

  it("10. ketma-ket A va B skani (bo'sh savatdan) → A x1, B x1", async () => {
    const user = userEvent.setup();
    renderApp(<POSKassa />);
    await screen.findByRole("button", { name: /Cola/ });
    await physicalScan(user, COLA.barcodes[0]);
    await waitFor(() => expect(qty(COLA.id)).toBe(1));
    await physicalScan(user, FANTA.barcodes[0]);
    await waitFor(() => expect(qty(FANTA.id)).toBe(1));
    expect(qty(COLA.id)).toBe(1);
    expect(items()).toHaveLength(2);
  });
});
