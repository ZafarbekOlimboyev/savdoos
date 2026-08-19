import { createHashRouter, Navigate, Outlet } from "react-router-dom";
import { useAuth } from "@/store/auth";
import { Login } from "@/screens/Login";
import { Dashboard } from "@/screens/Dashboard";
import { Products } from "@/screens/Products";
import { Sales } from "@/screens/Sales";
import { Purchases } from "@/screens/Purchases";
import { Reports } from "@/screens/Reports";
import { Customers } from "@/screens/Customers";
import { Returns } from "@/screens/Returns";
import { Employees } from "@/screens/Employees";
import { Shift } from "@/screens/Shift";
import { Settings } from "@/screens/Settings";
import { Audit } from "@/screens/Audit";
import { Scales } from "@/screens/Scales";
import { Layout } from "./components/Layout";

function Protected() {
  const token = useAuth((s) => s.token);
  if (!token) return <Navigate to="/login" replace />;
  return (
    <Layout>
      <Outlet />
    </Layout>
  );
}

export const router = createHashRouter([
  { path: "/login", element: <Login /> },
  {
    path: "/",
    element: <Protected />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: "mahsulotlar", element: <Products /> },
      { path: "sotuvlar", element: <Sales /> },
      { path: "xaridlar", element: <Purchases /> },
      { path: "hisobotlar", element: <Reports /> },
      { path: "mijozlar", element: <Customers /> },
      { path: "qaytarishlar", element: <Returns /> },
      { path: "xodimlar", element: <Employees /> },
      { path: "audit", element: <Audit /> },
      { path: "smena", element: <Shift /> },
      { path: "tarozilar", element: <Scales /> },
      { path: "sozlamalar", element: <Settings /> },
    ],
  },
]);
