import type { ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { NavDrawer } from "./NavDrawer";

// Dizayn: Kassa ekrani to'liq ekran (sidebar drawer sifatida, hamburger orqali);
// Sotuvlarim/Smena va boshqalar — doimiy sidebar (232px).
const FULLSCREEN = ["/"];

export function Layout({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const fullscreen = FULLSCREEN.includes(pathname);
  return (
    <div className="app">
      {!fullscreen && <Sidebar />}
      {children}
      <NavDrawer />
    </div>
  );
}
