import { createHashRouter, Navigate, Outlet } from "react-router-dom";
import { useAuth } from "@/store/auth";
import { Login } from "@/screens/Login";
import { POSKassa } from "@/screens/POSKassa";
import { Sotuvlarim } from "@/screens/Sotuvlarim";
import { Returns } from "@/screens/Returns";
import { Customers } from "@/screens/Customers";
import { Shift } from "@/screens/Shift";
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
      { index: true, element: <POSKassa /> },
      { path: "sotuvlarim", element: <Sotuvlarim /> },
      { path: "qaytarishlar", element: <Returns /> },
      { path: "mijozlar", element: <Customers /> },
      { path: "smena", element: <Shift /> },
    ],
  },
]);
