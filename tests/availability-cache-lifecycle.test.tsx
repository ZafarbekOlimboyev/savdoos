import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, waitFor } from "@testing-library/react";
import { Sidebar } from "../apps/manager/src/components/Sidebar";
import { invalidateAvailability } from "@/components/lotui";
import { useAuth } from "@/store/auth";
import { availability, mockApi, renderApp, type Call } from "./util";

// ═══ PARTIYA KO'RINISHI KESHI — LIFECYCLE ════════════════════════════════════
//
// NUQSON. `useAvailability` keshi MODUL-GLOBAL (`components/lotui.tsx:257`,
// TTL 60 s) va u na xodimga, na do'konga bog'langan. `invalidateAvailability()`
// (`lotui.tsx:265`) mavjud, lekin uni PRODUCTION kodining birorta joyi
// chaqirmagan — faqat testlar. Uzoq yashaydigan Electron jarayonida (kassa
// terminali kun bo'yi ochiq) xodim A chiqib, xodim B kirganda B 60 sekundgacha
// A ning bo'lim ko'rinishini MEROS olardi.
//
// Tuzatish: `store/auth.ts` dagi IKKI lifecycle nuqtasiga ulandi —
//   · `logout()`  — chiqish;
//   · `setAuth()` — kirish / kontekst almashishi (logout qilinmasdan boshqa
//                   hisobga o'tish: kassir almashuvi, boshqa tenant).
// Ikkisi ham LAZY import bilan: `lotui` -> `lib/api` -> `store/auth` sikli
// statik bo'lmasin (`store/shift` va `lib/sync` bilan AYNI naqsh).
//
// ⚠️  ISBOT USULI — SPY EMAS, EFFEKT. ESM eksportiga `vi.spyOn` ishonchsiz va
//     `auth.ts` funksiyani dinamik import'dan DESTRUKTURLAB chaqiradi, ya'ni
//     namespace spy'i baribir ushlamasligi mumkin. Shu bois chaqiruv HAQIQATAN
//     bo'lganini KUZATILADIGAN natija bilan isbotlaymiz: TTL (60 s) ICHIDA
//     qayta so'rov yuborilishi. `tests/sidebar-lot-gating.test.tsx` dagi C2
//     aynan teskarisini qulflaydi — bekor qilinmasa TTL ichida tarmoqqa
//     CHIQILMAYDI. Ya'ni qayta so'rovning O'ZI `invalidateAvailability()`
//     ishlaganining dalili.

const A_PERMS = ["ombor.view", "ombor.edit"];      // partiya bo'limini ko'radi
const B_PERMS = ["sotuvlar.view"];                 // ko'rmaydi

const emp = (id: string, perms: string[]) => ({
  id, full_name: id === "e1" ? "Xodim A" : "Xodim B",
  role_code: "omborchi", role_name: "Omborchi", status: "active", permissions: perms,
} as any);

const LOT_ROWS = ["Partiyalar", "Yaroqlilik muddati", "Inventarizatsiya",
                  "Hisobdan chiqarish", "Aniqlanmagan qoldiq"];
const shown = () => LOT_ROWS.filter((n) => screen.queryByText(n) !== null);
const avCalls = (c: Call[]) => c.filter((x) => x.url.includes("/lots/availability")).length;

//  ⚠️  BEKOR QILISH ASINXRON. `auth.ts` dagi chaqiruv LAZY `import()` ichida
//      (sikl sababi — yuqoridagi izoh), ya'ni u mikrotask navbatida bajariladi.
//      `logout()`/`setAuth()` dan keyin DARHOL mount qilsak, Sidebar keshni
//      bekor qilinmasidan OLDIN o'qib oladi. Haqiqiy ilovada bu oyna yopiq:
//      `logout` -> token null -> `<Protected/>` Login'ga yuboradi -> Sidebar
//      UNMOUNT bo'ladi va keyingi mount faqat `setAuth` dan ko'p tick keyin
//      sodir bo'ladi. Testda esa navbatni ATAYLAB bo'shatamiz — vaqtga
//      bog'liq, "ba'zida yashil" test yozmaslik uchun.
const tick = () => new Promise((r) => setTimeout(r, 0));

beforeEach(() => {
  invalidateAvailability();
  localStorage.clear();
  vi.restoreAllMocks();
});
afterEach(() => cleanup());

describe("L — kesh lifecycle nuqtalariga ULANGAN", () => {
  it("L1. `logout()` keshni bekor qiladi → TTL ichida ham QAYTA so'raladi", async () => {
    useAuth.setState({ token: "t", employee: emp("e1", A_PERMS) });
    const calls = mockApi([[/\/lots\/availability/, availability({ section_visible: true })]]);
    renderApp(<Sidebar />);
    await waitFor(() => expect(shown()).toEqual(LOT_ROWS));
    const oldin = avCalls(calls);
    expect(oldin).toBeGreaterThan(0);
    cleanup();

    useAuth.getState().logout();
    await tick();
    renderApp(<Sidebar />);
    //  C2: bekor qilinmasa bu so'rov BO'LMASDI (TTL 60 s hali o'tmagan).
    await waitFor(() => expect(avCalls(calls)).toBeGreaterThan(oldin));
  });

  it("L2. `setAuth()` ham bekor qiladi (logout'SIZ kontekst almashishi)", async () => {
    useAuth.setState({ token: "t", employee: emp("e1", A_PERMS) });
    const calls = mockApi([[/\/lots\/availability/, availability({ section_visible: true })]]);
    renderApp(<Sidebar />);
    await waitFor(() => expect(shown()).toEqual(LOT_ROWS));
    const oldin = avCalls(calls);
    cleanup();

    //  Chiqmasdan boshqa hisobga o'tish — kassir almashuvi / boshqa tenant.
    useAuth.getState().setAuth("t2", emp("e2", A_PERMS));
    await tick();
    renderApp(<Sidebar />);
    await waitFor(() => expect(avCalls(calls)).toBeGreaterThan(oldin));
  });
});

describe("M — XODIM A → B: eskirgan ko'rinish MEROS BO'LMAYDI", () => {
  it("M1. A (bo'lim ochiq) → logout → B (ruxsatsiz): qatorlar YO'Q", async () => {
    //  ── A: bo'lim ochiq, javob keshga tushadi ──
    useAuth.setState({ token: "t", employee: emp("e1", A_PERMS) });
    const aCalls = mockApi([[/\/lots\/availability/, availability({ section_visible: true })]]);
    renderApp(<Sidebar />);
    await waitFor(() => expect(shown()).toEqual(LOT_ROWS));
    expect(avCalls(aCalls)).toBeGreaterThan(0);
    cleanup();

    //  ── chiqish → kirish: B uchun server «ko'rinmaydi» deydi ──
    useAuth.getState().logout();
    await tick();
    useAuth.getState().setAuth("t2", emp("e2", B_PERMS));
    await tick();
    const bCalls = mockApi([[/\/lots\/availability/, availability({ section_visible: false })]]);
    renderApp(<Sidebar />);
    await waitFor(() => expect(avCalls(bCalls)).toBeGreaterThan(0));
    await new Promise((r) => setTimeout(r, 40));
    //  ⚠️  ASOSIY TASDIQ: B xodim A ning ko'rinishini MEROS OLMADI.
    expect(shown()).toEqual([]);
  });

  it("M2. A → B: server OCHIQ desa ham B ning RUXSATI yo'q → qatorlar YO'Q", async () => {
    //  Ikki qatlam (kesh + ruxsat) mustaqil ishlashini ajratib ko'rsatadi:
    //  kesh yangilandi, lekin qaror B ning o'z ruxsatiga tayanadi.
    useAuth.setState({ token: "t", employee: emp("e1", A_PERMS) });
    const calls = mockApi([[/\/lots\/availability/, availability({ section_visible: true })]]);
    renderApp(<Sidebar />);
    await waitFor(() => expect(shown()).toEqual(LOT_ROWS));
    cleanup();

    useAuth.getState().logout();
    await tick();
    useAuth.getState().setAuth("t2", emp("e2", B_PERMS));
    await tick();
    renderApp(<Sidebar />);
    await waitFor(() => expect(avCalls(calls)).toBeGreaterThan(1));
    await new Promise((r) => setTimeout(r, 40));
    expect(shown()).toEqual([]);
  });
});
