import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Partiyalar } from "@/screens/Partiyalar";
import { invalidateAvailability } from "@/components/lotui";
import { availability, lot, lotList, mockApi, renderApp } from "./util";

const MANY = lotList(Array.from({ length: 50 }, (_, i) => lot({ id: "l" + i, batch_number: "B" + i })));
const BIG = { ...MANY, total: 137 };

function mount(over: Record<string, any> = {}, batches: any = BIG, lang: "uz" | "ru" = "uz") {
  invalidateAvailability();
  const calls = mockApi([
    [/\/lots\/availability/, availability(over)],
    [/\/lots\/batches/, batches],
  ]);
  renderApp(<Partiyalar />, { lang });
  return calls;
}

const lastBatches = (calls: { url: string }[]) =>
  [...calls].reverse().find((c) => c.url.includes("/lots/batches"))!.url;

describe("Partiyalar ro'yxati", () => {
  it("filtr, qidiruv va tartib SERVERGA yuboriladi (brauzerda saralanmaydi)", async () => {
    const u = userEvent.setup();
    const calls = mount();
    await waitFor(() => screen.getByTestId("lot-row-l0"));

    await u.click(screen.getByTestId("f-expiry-expired"));
    await waitFor(() => expect(lastBatches(calls)).toContain("expiry=expired"));

    await u.selectOptions(screen.getByTestId("f-sort"), "value:desc");
    await waitFor(() => expect(lastBatches(calls)).toContain("sort=value"));
    expect(lastBatches(calls)).toContain("order=desc");

    await u.type(screen.getByTestId("lot-search"), "A-1");
    await waitFor(() => expect(lastBatches(calls)).toContain("q=A-1"), { timeout: 3000 });
  });

  it("SAHIFALASH serverda: keyingi sahifa offset bilan so'raladi", async () => {
    const u = userEvent.setup();
    const calls = mount();
    await waitFor(() => screen.getByTestId("lot-row-l0"));
    expect(screen.getByTestId("lot-total")).toHaveTextContent("137");
    expect(lastBatches(calls)).toContain("limit=50");

    await u.click(screen.getByTestId("page-next"));
    await waitFor(() => expect(lastBatches(calls)).toContain("offset=50"));
    // Filtr o'zgarsa 1-sahifaga qaytadi (aks holda bo'sh sahifa ko'rinardi)
    await u.click(screen.getByTestId("f-expiry-expired"));
    await waitFor(() => expect(lastBatches(calls)).not.toContain("offset=50"));
  });

  it("XATO holati boshi berk ko'cha emas — qayta urinish so'rovni takrorlaydi", async () => {
    const u = userEvent.setup();
    invalidateAvailability();
    let fail = true;
    const calls = mockApi([
      [/\/lots\/availability/, availability()],
      [/\/lots\/batches/, () => (fail ? { __status: 500, detail: "Server xatosi" } : BIG)],
    ]);
    renderApp(<Partiyalar />, { lang: "uz" });
    await waitFor(() => screen.getByTestId("state-error"));
    fail = false;
    await u.click(screen.getByTestId("state-retry"));
    await waitFor(() => screen.getByTestId("lot-row-l0"));
    expect(calls.filter((c) => c.url.includes("/lots/batches")).length).toBeGreaterThanOrEqual(2);
  });

  it("kuzatuv yoqilmagan do'konda ekran ISHLAYOTGANDEK ko'rinmaydi", async () => {
    mount({ tracked_products: 0, can_enable: false });
    await waitFor(() => screen.getByTestId("lot-dormant"));
    expect(screen.queryByTestId("lot-search")).toBeNull();
  });

  it("tannarx sifati RANG bilan emas, MATN bilan ham aytiladi", async () => {
    mount({}, lotList([
      lot({ id: "k", cost_basis: "known" }),
      lot({ id: "e", cost_basis: "estimated" }),
      lot({ id: "n", cost_basis: "unknown", unit_cost: 0, value: 0 }),
    ]));
    await waitFor(() => screen.getByTestId("lot-row-k"));
    expect(screen.getByTestId("cost-known")).toHaveTextContent("ANIQ");
    expect(screen.getByTestId("cost-estimated")).toHaveTextContent("TAXMINIY");
    expect(screen.getByTestId("cost-unknown")).toHaveTextContent("NOMA'LUM");
    // Tushuntirish tooltip'da — «taxminiy» so'zi nimani anglatishi ayon
    expect(screen.getByTestId("cost-estimated")).toHaveAttribute("title", expect.stringContaining("taxmin"));
  });

  it("server xatosi RU tilida TARJIMA qilinadi (xom o'zbekcha matn emas)", async () => {
    invalidateAvailability();
    mockApi([
      [/\/lots\/availability/, availability()],
      [/\/lots\/batches/, { __status: 400, detail: "Noma'lum tartib: narx" }],
    ]);
    renderApp(<Partiyalar />, { lang: "ru" });
    const box = await screen.findByTestId("state-error");
    expect(box).toHaveTextContent("Неизвестная сортировка: narx");
  });
});
