import { useCallback, useMemo, useState } from "react";
import { createHashRouter, Navigate, Outlet, type RouteObject } from "react-router-dom";
import { useAuth } from "@/store/auth";
import { LoginPin } from "@/screens/LoginPin";
import { POSKassa } from "@/screens/POSKassa";
import { Sotuvlarim } from "@/screens/Sotuvlarim";
import { Returns } from "@/screens/Returns";
import { Customers } from "@/screens/Customers";
import { Shift } from "@/screens/Shift";
import { PosPrinter } from "@/screens/PosPrinter";
import { AutoLogout } from "@/components/AutoLogout";
import { FleetHeartbeat } from "@/components/FleetHeartbeat";
import { PrinterSetupLinkContext, type PrinterSetupLink } from "@/components/PrintStatus";
import { PrinterSetupDialog } from "@/components/PrinterSetup";
import { Layout } from "./components/Layout";

function Protected() {
  const token = useAuth((s) => s.token);
  // Chop etish xatosidagi «Printer sozlamasi» POS'da OYNADA ochiladi (sahifaga o'tilmaydi): sotuv/qaytarish
  // muvaffaqiyat ekrani chekning yagona "Qayta urinish" joyi — u o'chib ketsa chekni POS'da chop etib bo'lmasdi.
  const [printerOpen, setPrinterOpen] = useState(false);
  const closePrinter = useCallback(() => setPrinterOpen(false), []);
  const printerSetup = useMemo<PrinterSetupLink>(() => ({ perm: null, open: () => setPrinterOpen(true) }), []);
  if (!token) return <Navigate to="/login" replace />;
  return (
    <PrinterSetupLinkContext.Provider value={printerSetup}>
      <Layout>
        <FleetHeartbeat />
        <AutoLogout />
        <Outlet />
      </Layout>
      {printerOpen && <PrinterSetupDialog onClose={closePrinter} />}
    </PrinterSetupLinkContext.Provider>
  );
}

// Marshrutlar alohida eksport — sinov ularni xotiradagi router bilan AYNAN shu ro'yxatdan ko'taradi.
export const routes: RouteObject[] = [
  { path: "/login", element: <LoginPin /> },
  {
    path: "/",
    element: <Protected />,
    children: [
      { index: true, element: <POSKassa /> },
      { path: "sotuvlarim", element: <Sotuvlarim /> },
      { path: "qaytarishlar", element: <Returns /> },
      { path: "mijozlar", element: <Customers /> },
      { path: "smena", element: <Shift /> },
      // Shu kassa kompyuterining printeri (qurilma sozlamasi — POS va Manager alohida ilova).
      { path: "printer", element: <PosPrinter /> },
    ],
  },
];

export const router = createHashRouter(routes);
