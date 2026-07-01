/**
 * In-memory auth state — survives React re-renders but not page reloads.
 * Page reload triggers /auth/refresh via the httpOnly cookie (7-day session).
 */

export interface User {
  id: string;
  email: string;
  name: string;
}

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

export function clearAuth(): void {
  _user = null;
}
