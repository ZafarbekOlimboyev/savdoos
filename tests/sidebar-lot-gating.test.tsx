import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, waitFor } from "@testing-library/react";
import { Sidebar } from "../apps/manager/src/components/Sidebar";
import { Inventarizatsiya } from "@/screens/Inventarizatsiya";
import { invalidateAvailability } from "@/components/lotui";
import { useAuth } from "@/store/auth";
import { availability, mockApi, renderApp } from "./util";

// ═══ SIDEBAR PARTIYA DARVOZASI — MAVJUD QAMROVNING BO'SHLIQLARI ══════════════
//
// ⚠️  `tests/lot-gate.test.tsx` ALLAQACHON quyidagilarni qulflaydi, shu bois
//     bu fayl ularni TAKRORLAMAYDI:
//       · server `section_visible: false` desa menyuda bo'lim yo'q;
//       · hali yoqilmagan, lekin yoqish MUMKIN bo'lsa bo'lim ko'rinadi;
//       · `ombor.view` umuman yo'q xodimga ko'rinmaydi;
//       · ochiq qarz bo'lsa ekran ishlaydi / bo'lmasa `lot-dormant`.
//     Server FORMULASI ham pinlangan — `apps/server/tests/test_lot_review_4b1.py`
//     `test_BOLIM_KORINISHI_formulasi_HAQIQAT_JADVALI` (5 holatli haqiqat jadvali).
//     Bu fayl FAQAT qolgan bo'shliqlarni yopadi.
//
// ⚠️  HOZIRGI XULQ QULFLANADI, o'zgartirilmaydi. Ikki joy ATAYLAB farq qiladi
//     va bu mahsulot qarorini talab qiladi (shu taskda TEGILMAYDI):
//        menyu  : can_view ∧ (tracked>0 ∨ has_data ∨ allowed)   ← `allowed` BOR
//        ekranlar: tracked>0 ∨ has_data                          ← `allowed` YO'Q
//     Ya'ni menyuda qator KO'RINISHI ekran ISHLAYDI degani EMAS. `D1` shuni
//     bitta testda yozib qo'yadi.

function login(perms: string[]) {
  useAuth.setState({
    token: "t",
    employee: {
      id: "e1", full_name: "Sardor", role_code: "omborchi", role_name: "Omborchi",
      status: "active", permissions: perms,
    } as any,
  });
}

/** Partiya bo'limining BESH qatori — `Sidebar.tsx:74` LOT_KEYS tartibida. */
const LOT_ROWS = ["Partiyalar", "Yaroqlilik muddati", "Inventarizatsiya",
                  "Hisobdan chiqarish", "Aniqlanmagan qoldiq"];
const shown = () => LOT_ROWS.filter((n) => screen.queryByText(n) !== null);

/** Javob kelib bo'lgandan keyin o'lchash — aks holda test «standart yopiq»ni ko'radi. */
async function settled(calls: ReturnType<typeof mockApi>) {
  await waitFor(() => expect(calls.some((c) => c.url.includes("/lots/availability"))).toBe(true));
  await new Promise((r) => setTimeout(r, 50));
}

beforeEach(() => {
  invalidateAvailability();
  vi.useRealTimers();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("A — HAR BANDNING O'Z RUXSATI (`ITEM_PERM` bir xil EMAS)", () => {
  it("A1. `ombor.view` bor, `ombor.edit` YO'Q → BESHDAN TO'RTTASI ko'rinadi", async () => {
    //  ⚠️  `Sidebar.tsx:66`: `hisobdan` → `ombor.edit`, qolgan to'rttasi →
    //      `ombor.view`. Ya'ni besh qator `lotsOn` bo'yicha bitta blok, lekin
    //      RUXSAT bo'yicha EMAS. Mavjud testlar ikki ruxsatni birga berib
    //      bu assimetriyani hech qachon o'lchamagan.
    login(["ombor.view"]);
    const calls = mockApi([[/\/lots\/availability/, availability({ section_visible: true })]]);
    renderApp(<Sidebar />);
    await settled(calls);
    expect(shown()).toEqual(["Partiyalar", "Yaroqlilik muddati", "Inventarizatsiya",
                             "Aniqlanmagan qoldiq"]);
    expect(screen.queryByText("Hisobdan chiqarish")).toBeNull();
  });

  it("A2. ikki ruxsat ham bor → BESHTASI ham ko'rinadi", async () => {
    login(["ombor.view", "ombor.edit"]);
    const calls = mockApi([[/\/lots\/availability/, availability({ section_visible: true })]]);
    renderApp(<Sidebar />);
    await settled(calls);
    expect(shown()).toEqual(LOT_ROWS);
  });

  it("A3. `ombor.edit` bor, `ombor.view` YO'Q → faqat `Hisobdan chiqarish`", async () => {
    //  Teskari assimetriya: `hisobdan` o'tadi, qolgan to'rttasi o'tmaydi.
    login(["ombor.edit"]);
    const calls = mockApi([[/\/lots\/availability/, availability({ section_visible: true })]]);
    renderApp(<Sidebar />);
    await settled(calls);
    expect(shown()).toEqual(["Hisobdan chiqarish"]);
  });

  it("A4. server YOPIQ desa ruxsat BORLIGI ham ochmaydi (ikki shart AND)", async () => {
    login(["ombor.view", "ombor.edit"]);
    const calls = mockApi([[/\/lots\/availability/, availability({
      tracked_products: 0, has_lot_data: false, section_visible: false, activation_allowed: false })]]);
    renderApp(<Sidebar />);
    await settled(calls);
    expect(shown()).toEqual([]);
    //  Partiyaga aloqasi yo'q qator JOYIDA — darvoza FAQAT `LOT_KEYS` ga tegadi.
    //  `Dashboard` ataylab tanlandi: u `ITEM_PERM` da yo'q, ya'ni ruxsatdan
    //  MUSTAQIL ko'rinadi (`Sidebar.tsx:35` + :61 izohi) — shu bois bu tasdiq
    //  faqat darvozani o'lchaydi, ruxsat sozlamasini emas.
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
  });
});

describe("D — MENYUDA KO'RINISH ≠ EKRAN ISHLAYDI", () => {
  it("D1. `allowed=true, tracked=0, has_data=false`: menyuda BOR, ekran DORMANT", async () => {
    //  ⚠️  Aynan staging/dev holati (`lot_policy` MODE_ENV → `allowed=true`).
    //      Menyu `allowed` ni hisobga oladi, ekran esa YO'Q — shu bois qator
    //      bosilganda `lot-dormant` chiqadi. Menyuni «ochish» bu holatni
    //      O'ZGARTIRMAYDI: ekran gardi alohida predikatda.
    login(["ombor.view", "ombor.edit"]);
    const AV = availability({
      tracked_products: 0, has_lot_data: false,
      section_visible: true,            // server: menyuda ko'rsat
      activation_allowed: true, can_enable: true,
    });
    const calls = mockApi([
      [/\/lots\/availability/, AV],
      [/\/lots\/batches/, { lots: [], count: 0 }],
    ]);
    renderApp(<Sidebar />);
    await settled(calls);
    //  1) menyuda BOR
    expect(screen.getByText("Inventarizatsiya")).toBeInTheDocument();
    cleanup();
    //  2) ayni javob bilan EKRAN esa dormant
    renderApp(<Inventarizatsiya />);
    await waitFor(() => expect(screen.getByTestId("lot-dormant")).toBeInTheDocument());
  });
});

describe("C — SOVUQ START / XATO / ESKI KESH uch holati FARQLANADI", () => {
  it("C1. SOVUQ START va so'rov YIQILDI → fail-closed, beshtasi ham YO'Q", async () => {
    login(["ombor.view", "ombor.edit"]);
    const calls = mockApi([[/\/lots\/availability/, { __status: 500, detail: "server xatosi" }]]);
    renderApp(<Sidebar />);
    await settled(calls);
    //  Kesh bo'sh edi, javob kelmadi → `data` null → `lotsOn` false.
    expect(shown()).toEqual([]);
  });

  it("C2. ESKI KESH (TTL ichida): qayta mount TARMOQQA CHIQMAYDI", async () => {
    login(["ombor.view", "ombor.edit"]);
    const calls = mockApi([[/\/lots\/availability/, availability({ section_visible: true })]]);
    renderApp(<Sidebar />);
    await settled(calls);
    expect(shown()).toEqual(LOT_ROWS);
    const avoldin = calls.filter((c) => c.url.includes("/lots/availability")).length;
    cleanup();
    //  Ayni jarayonda qayta mount — `_cache` TTL (60s) ichida.
    renderApp(<Sidebar />);
    await waitFor(() => expect(screen.getByText("Partiyalar")).toBeInTheDocument());
    await new Promise((r) => setTimeout(r, 30));
    expect(calls.filter((c) => c.url.includes("/lots/availability")).length).toBe(avoldin);
  });

  it("C3. MUVAFFAQIYATDAN KEYINGI xato: qatorlar ESKI ma'lumot bilan KO'RINIB QOLADI", async () => {
    //  ⚠️  HOZIRGI XULQ — qulflanadi, tuzatilmaydi (mahsulot qarori).
    //      `_cache` muddati o'tganda ham O'CHIRILMAYDI (`lotui.tsx:257-286`:
    //      `setData` faqat muvaffaqiyat shoxida), shu bois qayta mount
    //      `useState(_cache ? _cache.data : null)` orqali ESKI ma'lumot bilan
    //      boshlanadi va yiqilgan so'rov faqat `setErr` qiladi. Natijada
    //      «tarmoq yo'q» holatida menyu eski holatni ko'rsatib turadi.
    login(["ombor.view", "ombor.edit"]);
    const ok = mockApi([[/\/lots\/availability/, availability({ section_visible: true })]]);
    renderApp(<Sidebar />);
    await settled(ok);
    expect(shown()).toEqual(LOT_ROWS);
    cleanup();
    //  TTL dan o'tkazamiz va endi so'rov YIQILADI.
    const hozir = Date.now();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(hozir + 61_000);
    const bad = mockApi([[/\/lots\/availability/, { __status: 503, detail: "tarmoq yo'q" }]]);
    renderApp(<Sidebar />);
    await settled(bad);
    //  Qatorlar YO'QOLMAYDI — eski kesh ko'rsatilmoqda.
    expect(shown()).toEqual(LOT_ROWS);
  });
});
