import { useEffect } from "react";
import { startFleetHeartbeat } from "@/lib/fleet";

/** Qurilma telemetriyasini yoqadi (versiya + offline navbat sonlari).
 *  Hech narsa chizmaydi va hech qachon xato ko'tarmaydi — kassa ishiga ta'sir qilmaydi. */
export function FleetHeartbeat() {
  useEffect(() => startFleetHeartbeat(), []);
  return null;
}
