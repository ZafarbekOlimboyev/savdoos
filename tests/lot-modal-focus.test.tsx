// R6.9 — `busy` PAYTIDA FOKUS MODALDAN CHIQIB KETMASLIGI.
//
// ⚠️  NEGA BU TEST BOR (raqib tekshiruvi topilmasi). `useModalFocus`
//     effekti `[ref, onClose, active]` ga bog'langan, `Confirm` esa
//     `onClose` ni HAR RENDERDA yangi arrow sifatida uzatadi
//     (`lotui.tsx:224`). Shu bois `busy` `true` bo'lганda effekt QAYTA
//     ishga tushadi:
//       1. cleanup `prev.focus()` qilib fokusni FON elementiga qaytaradi;
//       2. yangi effekt `focusables()` ni o'qiydi — ikkala tugma
//          `disabled`, ro'yxat BO'SH; zaxira `ref.current?.focus()` esa
//          ishlamaydi, chunki `<div role="alertdialog">` da `tabIndex` yo'q.
//     Natijada fokus fon tugmasida qoladi va Enter bosilsa IKKINCHI
//     modal ochiladi — ekranda ikki `aria-modal` dialog.
//
//     Ilgari bu ekranda BITTA oyna bo'lgani uchun oqibat ko'rinmasdi;
//     R6.9 ikkinchi oynani (server darvozasi) qo'shdi va u ko'rindi.
import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Hisobdan } from "@/screens/Hisobdan";
import { invalidateAvailability } from "@/components/lotui";
import { availability, lot, lotList, mockApi, renderApp } from "./util";

const LOTS = lotList([lot({ id: "l1", batch_number: "A-1", remaining_qty: 6, unit_cost: 12000 })]);

function mount(writeoffRes: any) {
  invalidateAvailability();
  const calls = mockApi([
    [/\/lots\/availability/, availability()],
    [/\/lots\/batches/, LOTS],
    [/\/products\?/, [{ id: "p1", name: "Sut 1L", unit_code: "dona", stock: 10 }]],
    [/\/inventory\/writeoff/, writeoffRes],
  ]);
  renderApp(<Hisobdan />);
  return calls;
}

async function pickAndOpen(u: ReturnType<typeof userEvent.setup>) {
  await u.type(screen.getByTestId("wo-product-input"), "Sut");
  await waitFor(() => screen.getByTestId("wo-product-opt-p1"), { timeout: 3000 });
  await u.click(screen.getByTestId("wo-product-opt-p1"));
  await waitFor(() => screen.getByTestId("wo-lot-l1"));
  await u.type(screen.getByTestId("wo-qty-l1"), "2");
  await u.click(screen.getByTestId("wo-submit"));
}

describe("R6.9 — modal fokus qopqoni", () => {
  it("so'rov ketayotganda fokus MODAL ICHIDA qoladi", async () => {
    const u = userEvent.setup();
    let resolve!: (v: any) => void;
    const pending = new Promise((r) => (resolve = r));
    mount(() => pending);
    await pickAndOpen(u);

    const modal = screen.getByTestId("confirm");
    await u.click(screen.getByTestId("confirm-ok"));   // busy -> true

    //  ⚠️  Fokus MODAL ICHIDA bo'lishi SHART. Fon elementiga ko'chsa,
    //      bir Enter ikkinchi modalni ochadi.
    await waitFor(() =>
      expect(modal.contains(document.activeElement)).toBe(true),
    );
    resolve({ ok: true });
    await waitFor(() => expect(screen.queryByTestId("confirm")).toBeNull());
  });

  it("DARVOZA oynasi tasdiqlanayotganda Enter IKKINCHI modalni OCHMAYDI", async () => {
    //  ⚠️  AYNAN RAQIB TOPGAN SSENARIY. Darvoza oynasi ochiq, operator
    //      tasdiqladi, so'rov yo'lda. Fokus fon tugmasiga ko'chsa, bitta
    //      Enter `ask` oynasini ochadi va ekranda IKKI `aria-modal`
    //      dialog turadi — klaviatura va ekran o'quvchi uchun buzilgan holat.
    const u = userEvent.setup();
    let resolve!: (v: any) => void;
    const pending = new Promise((r) => (resolve = r));
    let i = 0;
    const seq = [
      { __status: 409, __headers: { "X-Error-Code": "WRITEOFF_DUPLICATE_SUSPECTED" },
        detail: "Bu hisobdan chiqarish shu filialda yaqinda allaqachon yozilgan." },
      pending,
    ];
    mount(() => seq[Math.min(i++, seq.length - 1)]);
    await pickAndOpen(u);
    await u.click(screen.getByTestId("confirm-ok"));
    await waitFor(() => screen.getByTestId("wo-dup"));

    const dup = screen.getByTestId("wo-dup");
    await u.click(screen.getByTestId("wo-dup-ok"));     // busy -> true

    // Fokus darvoza oynasi ICHIDA qolishi SHART.
    await waitFor(() => expect(dup.contains(document.activeElement)).toBe(true));

    await u.keyboard("{Enter}");
    await u.keyboard("{Enter}");
    const modals = document.querySelectorAll('[role="alertdialog"][aria-modal="true"]');
    expect(modals.length).toBe(1);

    resolve({ ok: true });
  });
});
