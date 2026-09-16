import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Muddat } from "@/screens/Muddat";
import { LotDrawer } from "@/screens/PartiyaTafsilot";
import { invalidateAvailability } from "@/components/lotui";
import { availability, lot, lotList, mockApi, renderApp } from "./util";

const ALERTS = {
  expiry: {
    expired: { lots: 2, qty: 7, value_at_risk: 84000 },
    expires_today: { lots: 1, qty: 3, value_at_risk: 30000 },
    within_7_days: { lots: 4, qty: 12, value_at_risk: 140000 },
    within_30_days: { lots: 9, qty: 40, value_at_risk: 400000 },
  },
  shortfalls: { open_count: 1, open_qty: 2, provisional_exposure_max: 20000 },
  cost_quality: { estimated_lots: 1, unknown_cost_lots: 0, tracked_products: 3 },
  business_dates: { b1: "2026-09-16" }, branches: 1,
};

const EXPIRED = lotList([lot({ id: "x1", bucket: "expired", expired: true, days_left: -3, expiry_date: "2026-09-13" })]);

function mountExpiry() {
  invalidateAvailability();
  const calls = mockApi([
    [/\/lots\/availability/, availability()],
    [/\/lots\/alerts/, ALERTS],
    [/\/lots\/batches/, EXPIRED],
  ]);
  renderApp(<Muddat />);
  return calls;
}

const DETAIL = {
  ...lot({ id: "l1" }),
  track_lots: true, track_expiry: true, business_date: "2026-09-16",
  created_at: null, updated_at: null,
  source: { type: "receiving", receiving_id: "r1", purchase_item_id: null, external_lot_id: null,
    receiving: { id: "r1", source: "manual", created_at: "2026-09-01T09:00:00+00:00", committed_at: "2026-09-01T10:00:00+00:00" },
    purchase: null },
  totals: { sold_qty: 4, returned_qty: 0, movement_qty: 0, resolved_qty: 0 },
  sales: [{ sale_id: "s1", receipt_no: "#12", sold_at: "2026-09-02T10:00:00+00:00", qty: 4, unit_cost: 12000 }],
  returns: [], movements: [], resolutions: [],
};

describe("Yaroqlilik muddati", () => {
  it("muddati o'tgan tovar O'ZI yo'qolmasligi ochiq aytiladi", async () => {
    mountExpiry();
    await waitFor(() => screen.getByTestId("expiry-notice"));
    expect(screen.getByTestId("expiry-notice")).toHaveTextContent(/o'zi yo'qolmaydi|сам из остатка не исчезает/i);
  });

  it("kartalar SANOQ va XAVF summasini ko'rsatadi, bosilganda guruh o'zgaradi", async () => {
    const u = userEvent.setup();
    const calls = mountExpiry();
    await waitFor(() => screen.getByTestId("exp-card-expired"));
    expect(screen.getByTestId("exp-card-expired")).toHaveTextContent("2");
    expect(screen.getByTestId("exp-card-within_7_days")).toHaveTextContent("4");

    await u.click(screen.getByTestId("exp-card-within_7_days"));
    await waitFor(() => {
      const last = [...calls].reverse().find((c) => c.url.includes("/lots/batches"))!.url;
      expect(last).toContain("expiry=within_7_days");
    });
  });

  it("muddati o'tgan qatorda hisobdan chiqarish yo'li bor", async () => {
    mountExpiry();
    await waitFor(() => screen.getByTestId("exp-row-x1"));
    expect(screen.getByTestId("exp-writeoff-x1")).toBeInTheDocument();
    expect(screen.getByTestId("bucket-expired")).toHaveTextContent(/3/);   // 3 kun oldin
  });
});

describe("Partiya tafsiloti", () => {
  it("MANBA hujjati va TARIX ko'rsatiladi", async () => {
    invalidateAvailability();
    mockApi([[/\/lots\/batches\/l1/, DETAIL]]);
    renderApp(<LotDrawer id="l1" canWrite onClose={() => {}} onWriteoff={() => {}} onCount={() => {}} />);
    await waitFor(() => screen.getByTestId("lot-drawer"));
    expect(await screen.findByText(/Qayerdan keldi|Откуда пришло/i)).toBeInTheDocument();
    expect(screen.getByTestId("lot-history")).toHaveTextContent("#12");
    expect(screen.getByTestId("lot-history")).toHaveTextContent("−4");
    expect(screen.getByTestId("drawer-writeoff")).toBeInTheDocument();
  });

  it("yozuv yopiq bo'lsa tafsilotda amal tugmalari YO'Q", async () => {
    invalidateAvailability();
    mockApi([[/\/lots\/batches\/l1/, DETAIL]]);
    renderApp(<LotDrawer id="l1" canWrite={false} onClose={() => {}} onWriteoff={() => {}} onCount={() => {}} />);
    await waitFor(() => screen.getByTestId("lot-drawer"));
    await screen.findByTestId("lot-history");
    expect(screen.queryByTestId("drawer-writeoff")).toBeNull();
    expect(screen.queryByTestId("drawer-count")).toBeNull();
  });
});
