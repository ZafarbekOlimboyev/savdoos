import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  LotReceivingEditor, MAX_LOTS, emptyLot, fromMilli, hasIssue, lotLineState, lotSummary,
  lotsPayload, milli, qtyText, tooManyDecimals, type LotDraft,
} from "@/components/LotReceivingEditor";
import { renderApp } from "./util";

// PARTIYA MUHARRIRI — sof funksiyalar va ekran xulqi.
//
// ⚠️  Bu yerda SERVER QOIDALARI sinalmaydi (ular backend testlarida). Bu yerda
//     sinaladigan narsa: operator ekranda nimani ko'radi va serverga NIMA ketadi.

const L = (qty: string, over: Partial<LotDraft> = {}): LotDraft =>
  ({ key: "k" + qty + (over.expiry || "") + (over.batch || ""), qty, expiry: "", batch: "", ...over });

describe("milli — miqdor BUTUN ming ulushda", () => {
  it("oddiy sonlar", () => {
    expect(milli("10")).toBe(10_000);
    expect(milli("1.235")).toBe(1235);
    expect(milli("0.001")).toBe(1);
    expect(milli(1.5)).toBe(1500);
  });

  it("vergul kasr ajratgichi sifatida qabul qilinadi", () => {
    expect(milli("1,5")).toBe(1500);
    expect(milli(" 2,25 ")).toBe(2250);
  });

  it("terilish holatlari: «.5» va «1.»", () => {
    expect(milli(".5")).toBe(500);
    expect(milli("1.")).toBe(1000);
  });

  it("UCHTADAN ORTIQ kasr — RAD (server ham aynan shunday)", () => {
    expect(milli("1.2345")).toBeNull();
    expect(milli("0.0005")).toBeNull();
    expect(tooManyDecimals("1.2345")).toBe(true);
    expect(tooManyDecimals("1.234")).toBe(false);
  });

  it("bo'sh, manfiy, nol va texnik yozuvlar — RAD", () => {
    for (const v of ["", "   ", "0", "-1", "abc", "1e3", "1.2.3", null, undefined]) {
      expect(milli(v as any)).toBeNull();
    }
  });

  it("server chegarasi (1e9) dan katta — RAD", () => {
    expect(milli("1000000000")).toBe(1e12);
    expect(milli("1000000001")).toBeNull();
  });

  it("fromMilli — ortiqcha nollarsiz", () => {
    expect(fromMilli(1235)).toBe("1.235");
    expect(fromMilli(10_000)).toBe("10");
    expect(fromMilli(500)).toBe("0.5");
  });

  it("qtyText — vergul nuqtaga, ortiqcha belgilar tashlanadi", () => {
    expect(qtyText("1,5")).toBe("1.5");
    expect(qtyText("1.2.3")).toBe("1.23");
    expect(qtyText("a1b2")).toBe("12");
  });
});

describe("lotLineState — qator va partiyalar mos kelishi", () => {
  it("0.1 + 0.2 = 0.3 (float qo'shuvda 0.30000000000000004 edi)", () => {
    const st = lotLineState("0.3", [L("0.1"), L("0.2")]);
    expect(st.sumMilli).toBe(300);
    expect(st.diffMilli).toBe(0);
    expect(st.ok).toBe(true);
  });

  it("1.235 = 0.617 + 0.618", () => {
    const st = lotLineState("1.235", [L("0.617"), L("0.618")]);
    expect(st.ok).toBe(true);
  });

  it("mos kelmasa — «mismatch» va farq ming ulushda", () => {
    const st = lotLineState("10", [L("6"), L("3")]);
    expect(hasIssue(st, "mismatch")).toBe(true);
    expect(st.diffMilli).toBe(1000);
    expect(st.ok).toBe(false);
  });

  it("uchtadan ortiq kasr — «decimals», «mismatch» EMAS", () => {
    const st = lotLineState("1.235", [L("1.2345")]);
    expect(hasIssue(st, "decimals")).toBe(true);
    expect(hasIssue(st, "mismatch")).toBe(false);   // avval miqdorni tuzatish kerak
    expect(st.diffMilli).toBeNull();
  });

  it("qator miqdori xato bo'lsa — «lineQty»", () => {
    const st = lotLineState("", [L("5")]);
    expect(hasIssue(st, "lineQty")).toBe(true);
    expect(st.firstBad).toEqual({ key: null, field: "line" });
  });

  it("partiyasiz — «qty»", () => {
    expect(hasIssue(lotLineState("5", []), "qty")).toBe(true);
  });

  it("muddat kuzatilsa — sanasiz partiya «expiryMissing»", () => {
    const st = lotLineState("5", [L("5")], { track_expiry: true });
    expect(hasIssue(st, "expiryMissing")).toBe(true);
    expect(st.firstBad?.field).toBe("expiry");
  });

  it("muddat BIZNES sanasidan oldin — «expiryPast»; sana NOMA'LUM bo'lsa TEKSHIRILMAYDI", () => {
    const lots = [L("5", { expiry: "2026-09-16" })];
    expect(hasIssue(lotLineState("5", lots, { track_expiry: true }, "2026-09-17"), "expiryPast")).toBe(true);
    // Chegara SAXIY: biznes sanasining O'ZI qabul qilinadi (server ham shunday).
    expect(lotLineState("5", [L("5", { expiry: "2026-09-17" })], { track_expiry: true }, "2026-09-17").ok).toBe(true);
    // Biznes sanasi noma'lum (ruxsat yo'q) — brauzer sanasi bo'yicha TAXMIN QILMAYMIZ.
    expect(hasIssue(lotLineState("5", lots, { track_expiry: true }, null), "expiryPast")).toBe(false);
  });

  it("muddat kuzatilmasa — sana TALAB qilinmaydi", () => {
    expect(lotLineState("5", [L("5")], { track_expiry: false }).ok).toBe(true);
  });

  it("chegaradan ortiq partiya — «tooMany»", () => {
    const many = Array.from({ length: MAX_LOTS + 1 }, (_, i) => L("1", { batch: "b" + i }));
    expect(hasIssue(lotLineState(String(MAX_LOTS + 1), many), "tooMany")).toBe(true);
  });
});

describe("lotsPayload — serverga AYNAN nima ketadi", () => {
  it("narx va tashqi kod HECH QACHON yuborilmaydi; bo'sh partiya raqami tashlanadi", () => {
    const out = lotsPayload([L("6", { batch: "  A-1  " }), L("4", { batch: "   " })], false);
    expect(out).toEqual([{ qty: 6, batch_number: "A-1" }, { qty: 4 }]);
    expect(JSON.stringify(out)).not.toContain("unit_cost");
    expect(JSON.stringify(out)).not.toContain("external_lot_id");
  });

  it("muddat FAQAT kuzatiladigan tovarda ketadi", () => {
    const lots = [L("5", { expiry: "2026-12-01" })];
    expect(lotsPayload(lots, true)).toEqual([{ qty: 5, expiry_date: "2026-12-01" }]);
    expect(lotsPayload(lots, false)).toEqual([{ qty: 5 }]);   // FIFO'da sana 400 berardi
  });

  it("kasr miqdor ANIQ qaytadi", () => {
    expect(lotsPayload([L("0.617"), L("0.618")], false)).toEqual([{ qty: 0.617 }, { qty: 0.618 }]);
  });

  it("lotSummary — tasdiqlangan qatorda ko'rinadigan matn", () => {
    expect(lotSummary([L("6"), L("4", { expiry: "2026-10-01" })])).toBe("6 + 4 · 2026-10-01");
  });
});

// ── KOMPONENT ────────────────────────────────────────────────────────────────

function Host({ trackExpiry = false, bizDate = null as string | null, lineQty = "10",
                onSubmit = () => {} }) {
  const [lots, setLots] = useState<LotDraft[]>([emptyLot(lineQty)]);
  return (
    <form onSubmit={(e) => { e.preventDefault(); onSubmit(); }}>
      <LotReceivingEditor
        product={{ id: "p1", name: "Sut 1L", unit_code: "dona", track_expiry: trackExpiry }}
        lineQty={lineQty} lots={lots} onChange={setLots} bizDate={bizDate} />
      <button type="submit">yuborish</button>
    </form>
  );
}

describe("LotReceivingEditor — ekran", () => {
  it("yig'indi JONLI e'lon qilinadi (role=status, aria-live)", async () => {
    const u = userEvent.setup();
    renderApp(<Host />, { lang: "ru" });
    const sum = screen.getByTestId("lots-sum");
    expect(sum).toHaveAttribute("aria-live", "polite");
    expect(sum).toHaveTextContent("10 / 10");

    await u.clear(screen.getByTestId("lots-qty-0"));
    await u.type(screen.getByTestId("lots-qty-0"), "6");
    expect(sum).toHaveTextContent("6 / 10");
    expect(sum).toHaveTextContent(/осталось 4/);
  });

  it("partiya qo'shiladi va o'chiriladi (oxirgisi o'chirilmaydi)", async () => {
    const u = userEvent.setup();
    renderApp(<Host />, { lang: "ru" });
    expect(screen.getByTestId("lots-remove-0")).toBeDisabled();

    await u.click(screen.getByTestId("lots-add"));
    expect(screen.getAllByTestId("lots-row")).toHaveLength(2);
    await u.type(screen.getByTestId("lots-qty-1"), "4");
    expect(screen.getByTestId("lots-sum")).toHaveTextContent(/лишнее 4/);

    await u.click(screen.getByTestId("lots-remove-1"));
    expect(screen.getAllByTestId("lots-row")).toHaveLength(1);
  });

  it("«Qolganini yozish» farqni OXIRGI partiyaga yozadi", async () => {
    const u = userEvent.setup();
    renderApp(<Host />, { lang: "ru" });
    await u.clear(screen.getByTestId("lots-qty-0"));
    await u.type(screen.getByTestId("lots-qty-0"), "6");
    await u.click(screen.getByTestId("lots-add"));
    await u.type(screen.getByTestId("lots-qty-1"), "3");
    await u.click(screen.getByTestId("lots-fill"));
    expect(screen.getByTestId("lots-qty-1")).toHaveValue("4");
    expect(screen.getByTestId("lots-sum")).toHaveTextContent("10 / 10");
    // Farq yo'q — tugma ham yo'q (bosadigan narsa qolmadi)
    expect(screen.queryByTestId("lots-fill")).toBeNull();
  });

  it("ENTER hujjatni YUBORMAYDI — keyingi maydonga o'tadi", async () => {
    const u = userEvent.setup();
    const submit = vi.fn();
    renderApp(<Host trackExpiry bizDate="2026-09-17" onSubmit={submit} />, { lang: "ru" });
    const qty = screen.getByTestId("lots-qty-0");
    qty.focus();
    await u.keyboard("{Enter}");
    expect(submit).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(screen.getByTestId("lots-expiry-0"));
    await u.keyboard("{Enter}");
    expect(document.activeElement).toBe(screen.getByTestId("lots-batch-0"));
    expect(submit).not.toHaveBeenCalled();
  });

  it("muddat maydoni FAQAT kuzatiladigan tovarda va biznes sanasidan oldin bo'lmaydi", () => {
    const { unmount } = renderApp(<Host trackExpiry bizDate="2026-09-17" />, { lang: "ru" });
    const d = screen.getByTestId("lots-expiry-0");
    expect(d).toHaveAttribute("min", "2026-09-17");
    expect(screen.getByTestId("lots-bizdate")).toHaveTextContent("2026-09-17");
    expect(screen.getByRole("alert")).toHaveTextContent(/срок/i);   // sana hali yo'q
    unmount();

    renderApp(<Host />, { lang: "ru" });
    expect(screen.queryByTestId("lots-expiry-0")).toBeNull();
    expect(screen.getByTestId("lots")).toHaveTextContent(/срок для этого товара не ведётся/i);
  });

  it("TOR ekran: qator o'ralib ketadi (gorizontal scroll yo'q)", () => {
    renderApp(<Host />, { lang: "ru" });
    const row = screen.getAllByTestId("lots-row")[0];
    expect(row.style.flexWrap).toBe("wrap");
    // Maydonlar qisqara oladi — `min-width: 0` bo'lmasa flex element kesilmay,
    // konteyneri esa gorizontal scroll berardi.
    expect((row.firstElementChild as HTMLElement).style.minWidth).toBe("0");
  });
});
