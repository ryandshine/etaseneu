/**
 * Centralized Date and Timezone Helpers for Asia/Jakarta (WIB)
 */

/**
 * Returns a new Date object representing the current instant.
 */
export function getCurrentDateWIB(): Date {
  return new Date();
}

/**
 * Formats a Date object to YYYY-MM-DD string in Asia/Jakarta (WIB) timezone.
 */
export function formatDateWIB(date: Date): string {
  const formatter = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Jakarta",
    year: "numeric",
    month: "2-digit",
    day: "2-digit"
  });
  const parts = formatter.formatToParts(date);
  const year = parts.find((p) => p.type === "year")?.value ?? "";
  const month = parts.find((p) => p.type === "month")?.value ?? "";
  const day = parts.find((p) => p.type === "day")?.value ?? "";
  return `${year}-${month}-${day}`;
}

/**
 * Returns the current date as a YYYY-MM-DD string in Asia/Jakarta (WIB) timezone.
 */
export function getTodayWIB(): string {
  return formatDateWIB(getCurrentDateWIB());
}

/**
 * Formats an ISO date string to DD-MM-YYYY HH:MM WIB string in Asia/Jakarta (WIB) timezone.
 */
export function formatDateTimeWIB(dateStr: string | null | undefined): string {
  if (!dateStr) return "-";
  const parsed = new Date(dateStr);
  if (Number.isNaN(parsed.getTime())) return "-";
  try {
    const formatter = new Intl.DateTimeFormat("en-US", {
      timeZone: "Asia/Jakarta",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false
    });
    const parts = formatter.formatToParts(parsed);
    const year = parts.find((p) => p.type === "year")?.value ?? "";
    const month = parts.find((p) => p.type === "month")?.value ?? "";
    const day = parts.find((p) => p.type === "day")?.value ?? "";
    const hour = parts.find((p) => p.type === "hour")?.value ?? "";
    const minute = parts.find((p) => p.type === "minute")?.value ?? "";
    return `${day}-${month}-${year} ${hour}:${minute} WIB`;
  } catch {
    return dateStr;
  }
}
