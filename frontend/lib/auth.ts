/**
 * Auth state: user in memory (survives re-renders), refresh token in a JS cookie
 * (survives page reloads, 7-day expiry). Access token stays in memory only.
 */

export interface User {
  id: string;
  email: string;
  name: string;
}

const RT_COOKIE = "kuvaka_rt";
const RT_MAX_AGE = 7 * 24 * 60 * 60; // 7 days in seconds

let _user: User | null = null;

export function setUser(u: User | null): void {
  _user = u;
}

export function getUser(): User | null {
  return _user;
}

export function isAuthenticated(): boolean {
  return _user !== null;
}

export function saveRefreshToken(token: string): void {
  if (typeof document === "undefined") return;
  document.cookie = `${RT_COOKIE}=${encodeURIComponent(token)}; max-age=${RT_MAX_AGE}; path=/; SameSite=Lax`;
}

export function loadRefreshToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(new RegExp(`(?:^|;\\s*)${RT_COOKIE}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

export function clearAuth(): void {
  _user = null;
  if (typeof document === "undefined") return;
  document.cookie = `${RT_COOKIE}=; max-age=0; path=/`;
}
