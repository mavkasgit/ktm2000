/**
 * Guard изоляции e2e от публичных (боевых) хостов.
 * E2E-набор разрешено гонять только против приватных адресов —
 * локального dev/test-окружения. Любой публичный хост (прод-сервер,
 * публичный IP, домен) — ошибка в playwright.config.ts перед стартом.
 */

function ipv4ToNumber(ip: string): number | null {
  const parts = ip.split(".").map(Number);
  if (parts.length !== 4 || parts.some((p) => Number.isNaN(p) || p < 0 || p > 255)) {
    return null;
  }
  return ((parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]) >>> 0;
}

function isPrivateIpv4(ip: string): boolean {
  const n = ipv4ToNumber(ip);
  if (n === null) return false;
  const high = n >>> 24;
  if (high === 127) return true; // 127.0.0.0/8 loopback
  if (high === 10) return true; // 10.0.0.0/8
  const second = n >>> 16;
  if (second >= 0xac10 && second <= 0xac1f) return true; // 172.16.0.0/12
  if (second === 0xc0a8) return true; // 192.168.0.0/16
  return false;
}

export function isPrivateHost(url: string): boolean {
  // Допускаем scheme-less значения (localhost:5172, 192.168.1.10:8012) —
  // приватный хост без схемы не должен ронять прогон сырым TypeError.
  const withScheme = url.includes("://") ? url : `http://${url}`;
  const hostname = new URL(withScheme).hostname.replace(/^\[|\]$/g, "").toLowerCase();
  if (hostname === "localhost" || hostname.endsWith(".localhost")) return true;
  if (hostname === "::1") return true;
  if (hostname.endsWith(".local")) return true;
  if (/^\d+\.\d+\.\d+\.\d+$/.test(hostname)) return isPrivateIpv4(hostname);
  return false;
}