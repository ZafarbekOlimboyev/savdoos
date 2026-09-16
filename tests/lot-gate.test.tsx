import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { Sidebar } from "../apps/manager/src/components/Sidebar";
import { Qoldiq } from "@/screens/Qoldiq";
import { invalidateAvailability } from "@/components/lotui";
import { useAuth } from "@/store/auth";
import { availability, mockApi, renderApp } from "./util";

// ⚠️  DARVOZA QARORI SERVERDA. UI `tracked_products > 0` ni O'ZI hisoblasa,
//     u «huquqi bor, lekin hali yoqmagan» do'konni ham, o'chirilgan mahsulot
//     ortidagi OCHIQ QARZNI ham yashirardi — pul ekrandan g'oyib bo'lardi.
function login(perms: string[]) {
  useAuth.setState({
    token: "t",
    employee: {
      id: "e1", full_name: "Sardor", role_code: "omborchi", role_name: "Omborchi",
      status: "active", permissions: perms,
    } as any,
  });
}

describe("Partiya bo'limi darvozasi", () => {
  it("server YOPIQ desa menyuda bo'lim YO'Q", async () => {
    login(["ombor.view", "ombor.edit"]);
    invalidateAvailability();
    const calls = mockApi([[/\/lots\/availability/, availability({ tracked_products: 0, has_lot_data: false, section_visible: false, activation_allowed: false })]]);
    renderApp(<Sidebar />);
    // ⚠️  JAVOB KELGANINI KUTAMIZ. Aks holda sinov menyuni hali «standart yopiq»
    //     holatida tekshirib, server nima deyishidan qat'i nazar yashil bo'lardi.
    await waitFor(() => expect(calls.some((c) => c.url.includes("/lots/availability"))).toBe(true));
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByText("Partiyalar")).toBeNull();
    expect(screen.queryByText("Aniqlanmagan qoldiq")).toBeNull();
  });

  it("kuzatuv hali YOQILMAGAN, lekin YOQISH MUMKIN bo'lsa bo'lim KO'RINADI", async () => {
    login(["ombor.view", "ombor.edit"]);
    invalidateAvailability();
    mockApi([[/\/lots\/availability/, availability({ tracked_products: 0, has_lot_data: false, section_visible: true })]]);
    renderApp(<Sidebar />);
    await waitFor(() => screen.getByText("Partiyalar"));
    expect(screen.getByText("Yaroqlilik muddati")).toBeInTheDocument();
  });

  it("ruxsati yo'q xodimga bo'lim KO'RINMAYDI (server ochiq desa ham)", async () => {
    login(["sotuvlar.view"]);
    invalidateAvailability();
    const calls = mockApi([[/\/lots\/availability/, availability({ section_visible: true })]]);
    renderApp(<Sidebar />);
    await waitFor(() => expect(calls.some((c) => c.url.includes("/lots/availability"))).toBe(true));
    await new Promise((r) => setTimeout(r, 50));
    // Server «ko'rinadi» dedi, lekin xodimda `ombor.view` yo'q — menyu baribir YO'Q.
    expect(screen.queryByText("Partiyalar")).toBeNull();
  });

  it("kuzatuv o'chgan, lekin OCHIQ QARZ qolgan bo'lsa ekran ochiq qoladi", async () => {
    login(["ombor.view"]);
    invalidateAvailability();
    mockApi([
      [/\/lots\/availability/, availability({ tracked_products: 0, has_lot_data: true, section_visible: true })],
      [/\/lots\/shortfalls/, { count: 1, total_cogs_variance: 0, total_provisional_exposure: 0,
        shortfalls: [{ id: "s1", product_id: "p1", product: "Sut", branch_id: "b1", qty: 4, resolved_qty: 0,
                       open_qty: 4, returned_qty: 0, returned_unattributed_on_hand: 0, unit_cost: 1000,
                       cogs_variance: 0, provisional_exposure: 4000, reason: null, created_at: null }] }],
    ]);
    renderApp(<Qoldiq />);
    await waitFor(() => screen.getByTestId("sf-row-s1"));
    expect(screen.queryByTestId("lot-dormant")).toBeNull();
  });

  it("kuzatuv ham, ma'lumot ham yo'q bo'lsa ekran «hali yoqilmagan» deydi", async () => {
    login(["ombor.view"]);
    invalidateAvailability();
    mockApi([[/\/lots\/availability/, availability({ tracked_products: 0, has_lot_data: false, section_visible: true, activation_allowed: false, can_enable: false })]]);
    renderApp(<Qoldiq />);
    await waitFor(() => screen.getByTestId("lot-dormant"));
  });
});
