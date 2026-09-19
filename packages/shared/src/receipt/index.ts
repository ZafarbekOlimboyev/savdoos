// Chek kutubxonasi (Phase 5F) — sof TypeScript: renderer VA Electron main jarayonida bir xil ishlaydi.
// ⚠️  Faqat nisbiy importlar; `@/`, React, DOM, localStorage, zustand taqiqlangan (types.ts izohiga qarang).
export * from "./types";
export { GENERIC_PROFILE_ID, PROFILES, profileFor } from "./profiles";
export {
  fmtMoney, fmtQty, currencyLabel, decMul, decAdd, decSub, decCmp, decRound, decSum, decNeg, decIsZero, isDecimal,
} from "./format";
export { RECEIPT_LABELS, labelsFor, methodLabel, type Labels } from "./labels";
export { cleanText, cleanLine, charWidth, strWidth, wrapText, center, pairLines } from "./text";
export { layoutReceipt, normalizeTemplate, MAX_TEMPLATE_LINES, MAX_TEMPLATE_CHARS } from "./layout";
export { renderHtml, escapeHtml, docHeightMm, pageSizeMm, type HtmlPageMode } from "./html";
export {
  encodeEscPos, parseEscPos, describeEscPos, scrubRealtime, ESCPOS_WHITELIST, type EscPosCommand, type EscPosResult,
} from "./escpos";
export { encodeText, decodeText, CODEPAGE_HIGH, TRANSLIT, type CodepageName } from "./codepage";
export { sampleReceipt, type SampleKind } from "./sample";
export { provisionalSaleReceipt, offlineNumber, type ProvisionalInput } from "./provisional";
export { code128Modules } from "./code128";
export { base64Decode, base64Encode, isBase64 } from "./b64";
export { docToText } from "./plain";
