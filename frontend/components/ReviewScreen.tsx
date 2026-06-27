"use client";
import { useState } from "react";
import { ChevronRight, Pencil, Check, X } from "lucide-react";
import type { ClinicalFlag, QAEntry } from "@/lib/types";
import { api } from "@/lib/api";
import FlagBadge from "./FlagBadge";
import clsx from "clsx";

interface Props {
  sessionId: string;
  qaLog: QAEntry[];
  flags: ClinicalFlag[];
  onProceed: () => void;
}

export default function ReviewScreen({ sessionId, qaLog, flags, onProceed }: Props) {
  const [entries, setEntries] = useState<QAEntry[]>(qaLog);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");

  const criticals = flags.filter((f) =>
    ["CRITICAL_RED_FLAG", "RED_FLAG"].includes(f.flag_type)
  );

  const startEdit = (entry: QAEntry) => {
    setEditingId(entry.question_id);
    setDraft(entry.answer);
    setSaveError("");
  };

  const cancelEdit = () => {
    setEditingId(null);
    setDraft("");
    setSaveError("");
  };

  const saveEdit = async (questionId: string) => {
    if (!draft.trim()) return;
    setSaving(true);
    setSaveError("");
    try {
      await api.editAnswer(sessionId, questionId, draft.trim());
      setEntries((prev) =>
        prev.map((e) => e.question_id === questionId ? { ...e, answer: draft.trim() } : e)
      );
      setEditingId(null);
    } catch {
      setSaveError("Failed to save. Please try again.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6 fade-up">
      <div className="card text-center">
        <div className="text-4xl mb-3">📋</div>
        <h2 className="text-xl font-bold text-gray-800">Review Your Responses</h2>
        <p className="text-gray-500 text-sm mt-1">
          Check what you shared. Tap <strong>Edit</strong> on any answer to correct it before we generate your clinical notes.
        </p>
      </div>

      {criticals.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-gray-600 uppercase tracking-wide">
            🚨 Clinical Alerts
          </h3>
          {criticals.map((f, i) => <FlagBadge key={i} flag={f} />)}
        </div>
      )}

      <div className="card divide-y divide-gray-100 max-h-[560px] overflow-y-auto">
        {entries.map((entry, i) => (
          <div key={entry.question_id} className="py-4 first:pt-0 last:pb-0">
            <div className="flex items-start justify-between gap-3 mb-2">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide pt-0.5">
                Q{i + 1}
              </p>
              {editingId !== entry.question_id && (
                <button
                  onClick={() => startEdit(entry)}
                  className="flex items-center gap-1 text-xs text-indigo-600 hover:text-indigo-800 font-medium px-2 py-1 rounded-lg hover:bg-indigo-50 transition-all shrink-0"
                >
                  <Pencil className="w-3 h-3" />
                  Edit
                </button>
              )}
            </div>

            <p className="font-semibold text-gray-800 mb-2 leading-snug">
              {entry.question_text}
            </p>

            {editingId === entry.question_id ? (
              <div className="space-y-2">
                <textarea
                  className="input-field w-full resize-none text-sm"
                  rows={3}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  autoFocus
                  disabled={saving}
                />
                {saveError && (
                  <p className="text-xs text-red-600">{saveError}</p>
                )}
                <div className="flex gap-2">
                  <button
                    onClick={() => saveEdit(entry.question_id)}
                    disabled={saving || !draft.trim()}
                    className={clsx(
                      "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all",
                      saving || !draft.trim()
                        ? "bg-slate-100 text-slate-400 cursor-not-allowed"
                        : "bg-indigo-600 text-white hover:bg-indigo-700 active:scale-95"
                    )}
                  >
                    <Check className="w-3 h-3" />
                    {saving ? "Saving…" : "Save"}
                  </button>
                  <button
                    onClick={cancelEdit}
                    disabled={saving}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-600 hover:bg-slate-100 transition-all"
                  >
                    <X className="w-3 h-3" />
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <p className="text-gray-600 text-sm leading-relaxed pl-3 border-l-2 border-indigo-200">
                {entry.answer}
              </p>
            )}
          </div>
        ))}

        {entries.length === 0 && (
          <p className="text-gray-400 text-sm py-4">No answers recorded.</p>
        )}
      </div>

      <button
        className="btn-primary w-full py-4 text-base flex items-center justify-center gap-2"
        onClick={onProceed}
        disabled={editingId !== null}
      >
        Continue to Analysis
        <ChevronRight className="w-5 h-5" />
      </button>
      {editingId !== null && (
        <p className="text-xs text-center text-slate-400">Save or cancel your edit before continuing.</p>
      )}
    </div>
  );
}
