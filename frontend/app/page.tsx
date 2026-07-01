"use client";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { getToken } from "@/lib/api";

export default function Home() {
  const router = useRouter();
  useEffect(() => {
    getToken()
      .then(() => router.replace("/patients"))
      .catch(() => router.replace("/login"));
  }, [router]);
  return null;
}
