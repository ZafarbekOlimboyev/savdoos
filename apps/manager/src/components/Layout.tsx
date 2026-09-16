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
      {/* ⚠️  `href="#main"` ISHLATILMAYDI: ilova HASH-router'da, brauzer bu havolani
          `#/main` yo'li deb tushunib, butun Manager'ni «sahifa topilmadi» xatosiga
          almashtirardi. Shu bois tugma — manzilga tegmasdan fokusni ko'chiradi. */}
      <button type="button" className="skip-link"
              onClick={() => {
                const m = document.querySelector<HTMLElement>("main");
                if (m) {
                  if (!m.hasAttribute("tabindex")) m.setAttribute("tabindex", "-1");
                  m.focus();
                  m.scrollIntoView({ block: "start" });
                }
              }}>
        {t("a11y.skipToContent")}
      </button>
      <Sidebar />
      {children}
    </div>
  );
}
