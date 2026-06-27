import type { ClinicalFlag } from "@/lib/types";
import clsx from "clsx";

const MAP: Record<string, { cls: string; icon: string; label: string }> = {
  CRITICAL_RED_FLAG: { cls: "flag-critical", icon: "🚨", label: "Critical" },
  RED_FLAG: { cls: "flag-red", icon: "🔴", label: "Red Flag" },
  IMPORTANT: { cls: "flag-important", icon: "⚠️", label: "Important" },
  NOTE: { cls: "flag-note", icon: "📌", label: "Note" },
};

export default function FlagBadge({ flag }: { flag: ClinicalFlag }) {
  const meta = MAP[flag.flag_type] ?? MAP.IMPORTANT;
  return (
    <div className={meta.cls}>
      <span className="mr-1">{meta.icon}</span>
      <strong>{meta.label}: </strong>
      {flag.description}
    </div>
  );
}
