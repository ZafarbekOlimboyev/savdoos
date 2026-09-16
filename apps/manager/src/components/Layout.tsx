import type { ReactNode } from "react";
import { useT } from "@/lib/i18n";
import { Sidebar } from "./Sidebar";

export function Layout({ children }: { children: ReactNode }) {
  const t = useT();
  return (
    <div className="app">
      {/* ⚠️  KLAVIATURA UCHUN BIRINCHI TO'XTASH. Yon panelda ~20 havola bor —
          ularsiz Tab bilan kelgan operator har ekranda o'sha ro'yxatni boshdan
          kezib chiqishi kerak edi. Sichqonchada ko'rinmaydi (`.skip-link`). */}
      <a href="#main" className="skip-link">{t("a11y.skipToContent")}</a>
      <Sidebar />
      {children}
    </div>
  );
}
