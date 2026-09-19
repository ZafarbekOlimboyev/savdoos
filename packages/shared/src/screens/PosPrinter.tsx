// POS: shu kassa kompyuterining chek printeri (Phase 5F).
//
// ⚠️  POS va Manager — ALOHIDA Electron ilovalar (har birining o'z localStorage'i): Manager'da tanlangan
//     printer kassaga yetib bormaydi. Deyarli har chek shu kompyuterdan chiqadi — sozlama shu yerda.
// Sozlama qurilmada (lib/printerConfig.ts), serverga yozilmaydi; sinov cheki faqat GET so'rovlar.
import { Topbar } from "@/components/ui";
import { PrinterSetup } from "@/components/PrinterSetup";
import { useT } from "@/lib/i18n";

export function PosPrinter() {
  const t = useT();
  return (
    <main className="main">
      <Topbar title={t("nav.printer")} />
      <div className="scroll" style={{ flex: 1, padding: "24px 28px 32px" }}>
        <div className="card" style={{ maxWidth: 760 }}>
          <PrinterSetup />
        </div>
      </div>
    </main>
  );
}
