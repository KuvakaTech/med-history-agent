"use client";
import type {
  KioskAdminSession,
  KioskAdminSessionDetail,
  KioskCentre,
} from "./kiosk-admin-types";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
const API_V2 = `${BASE}/api/v2`;

async function adminReq<T>(
  method: string,
  path: string,
  token: string,
  body?: unknown
): Promise<T> {
  const res = await fetch(`${API_V2}/kiosk-admin${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export const kioskAdminApi = {
  listCentres: (token: string) =>
    adminReq<{ centres: KioskCentre[] }>("GET", "/centres", token),

  getCurrentCentre: (token: string, centre_id?: string | null) => {
    const q = centre_id ? `?centre_id=${centre_id}` : "";
    return adminReq<KioskCentre>("GET", `/centre${q}`, token);
  },

  createCentre: (
    token: string,
    data: {
      slug: string;
      name: string;
      default_language?: string;
      prompt_file?: string;
      complaint_prefix?: string;
    }
  ) => adminReq<KioskCentre>("POST", "/centres", token, data),

  getStats: (token: string, centre_id?: string) => {
    const q = centre_id ? `?centre_id=${centre_id}` : "";
    return adminReq<{
      date_ist: string;
      today: { total: number; completed: number; partial: number; active: number };
      all_time: { total: number; completed: number };
    }>("GET", `/stats${q}`, token);
  },

  listSessions: (
    token: string,
    params?: {
      centre_id?: string;
      status?: string;
      complaint?: string;
      phone?: string;
      include_deleted?: boolean;
      date_from?: string;
      date_to?: string;
      limit?: number;
    }
  ) => {
    const qs = new URLSearchParams();
    if (params?.centre_id) qs.set("centre_id", params.centre_id);
    if (params?.status) qs.set("status", params.status);
    if (params?.complaint) qs.set("complaint", params.complaint);
    if (params?.phone) qs.set("phone", params.phone);
    if (params?.include_deleted) qs.set("include_deleted", "true");
    if (params?.date_from) qs.set("date_from", params.date_from);
    if (params?.date_to) qs.set("date_to", params.date_to);
    if (params?.limit) qs.set("limit", String(params.limit));
    const q = qs.toString() ? `?${qs.toString()}` : "";
    return adminReq<{ sessions: KioskAdminSession[]; count: number }>(
      "GET",
      `/sessions${q}`,
      token
    );
  },

  getSession: (token: string, sessionId: string, centre_id?: string | null) => {
    const q = centre_id ? `?centre_id=${centre_id}` : "";
    return adminReq<KioskAdminSessionDetail>(
      "GET",
      `/sessions/${sessionId}${q}`,
      token
    );
  },

  createAdminUser: (
    token: string,
    data: {
      email: string;
      name: string;
      password: string;
      role: "centre_admin" | "super_admin";
      centre_id?: string;
    }
  ) =>
    adminReq<{
      id: string;
      email: string;
      name: string;
      role: string;
      centre_id?: string | null;
    }>("POST", "/users", token, data),
};
