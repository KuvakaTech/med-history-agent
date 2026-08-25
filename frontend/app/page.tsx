"use client";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { getToken } from "@/lib/api";
import { adminApi } from "@/lib/ticketing-api";

const FALLBACK_HOSPITAL_SLUG = "berasia";

export default function Home() {
  const router = useRouter();
  useEffect(() => {
    getToken()
      .then(async (token) => {
        try {
          const payload = JSON.parse(atob(token.split(".")[1]));
          if (payload.role === "hospital_admin" || payload.role === "super_admin") {
            const hospital = await adminApi.getCurrentHospital(token, payload.hospital_id);
            router.replace(`/checkin/${hospital.slug}/`);
            return;
          }
        } catch {
          // fall through to default slug below
        }
        router.replace(`/checkin/${FALLBACK_HOSPITAL_SLUG}/`);
      })
      .catch(() => router.replace("/dashboard"));
  }, [router]);
  return null;
}
