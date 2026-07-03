"use client";
import { useState } from "react";
import { ChevronRight, Pencil, Check, X, AlertTriangle } from "lucide-react";
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

  const criticals = flags.filter((f) => ["CRITICAL_RED_FLAG", "RED_FLAG"].includes(f.flag_type));

  const startEdit = (entry: QAEntry) => {
    setEditingId(entry.question_id);
    setDraft(entry.answer);
    setSaveError("");
  };

  const cancelEdit = () => { setEditingId(null); setDraft(""); setSaveError(""); };

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
    <div className="space-y-5 fade-up">
      {/* Header card */}
      <div className="bg-white border border-gray-100 rounded-2xl p-6 text-center">
        <div className="w-12 h-12 bg-brand-light rounded-2xl flex items-center justify-center mx-auto mb-3">
          <svg viewBox="0 0 24 24" className="w-6 h-6 text-brand" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 12l2 2 4-4" /><rect x="3" y="3" width="18" height="18" rx="3" />
          </svg>
        </div>
        <h2 className="text-xl font-bold text-gray-900">Review Your Responses</h2>
        <p className="text-gray-500 text-sm mt-1.5">
          Check what you shared. Tap <strong className="font-semibold text-gray-700">Edit</strong> on any answer to correct it before we generate your clinical notes.
        </p>
      </div>

      {/* Clinical alerts */}
      {criticals.length > 0 && (
        <div className="bg-red-50 border border-red-200 rounded-2xl p-4 space-y-2">
          <div className="flex items-center gap-2 mb-1">
            <AlertTriangle className="w-4 h-4 text-red-500 flex-shrink-0" />
            <h3 className="text-sm font-bold text-red-700">Clinical Alerts</h3>
          </div>
          {criticals.map((f, i) => <FlagBadge key={i} flag={f} />)}
        </div>
      )}

      {/* Q&A list */}
      <div className="bg-white border border-gray-100 rounded-2xl divide-y divide-gray-100 max-h-[560px] overflow-y-auto">
        {entries.map((entry, i) => (
          <div key={entry.question_id} className="px-5 py-4 first:pt-5 last:pb-5">
            <div className="flex items-start justify-between gap-3 mb-2">
              <p className="text-xs font-bold text-gray-300 uppercase tracking-widest pt-0.5">Q{i + 1}</p>
              {editingId !== entry.question_id && (
                <button
                  onClick={() => startEdit(entry)}
                  className="flex items-center gap-1 text-xs text-brand hover:text-brand-dark font-semibold px-2 py-1 rounded-lg hover:bg-brand-light transition-all flex-shrink-0"
                >
                  <Pencil className="w-3 h-3" />
                  Edit
                </button>
              )}
            </div>

            <p className="font-semibold text-gray-800 text-sm mb-2 leading-snug">{entry.question_text}</p>

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
                {saveError && <p className="text-xs text-red-600 font-medium">{saveError}</p>}
                <div className="flex gap-2">
                  <button
                    onClick={() => saveEdit(entry.question_id)}
                    disabled={saving || !draft.trim()}
                    className={clsx(
                      "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all",
                      saving || !draft.trim()
                        ? "bg-gray-100 text-gray-300 cursor-not-allowed"
                        : "bg-brand text-white hover:bg-brand-dark active:scale-95"
                    )}
                  >
                    <Check className="w-3 h-3" />
                    {saving ? "Saving…" : "Save"}
                  </button>
                  <button
                    onClick={cancelEdit}
                    disabled={saving}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-gray-500 hover:bg-gray-100 transition-all"
                  >
                    <X className="w-3 h-3" />
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <p className="text-gray-600 text-sm leading-relaxed pl-3 border-l-2 border-brand/20">
                {entry.answer}
              </p>
            )}
          </div>
        ))}

        {entries.length === 0 && (
          <p className="text-gray-400 text-sm px-5 py-6">No answers recorded.</p>
        )}
      </div>

      <button
        className="btn-primary w-full py-4 text-sm flex items-center justify-center gap-2"
        onClick={onProceed}
        disabled={editingId !== null}
      >
        Continue to Analysis
        <ChevronRight className="w-4 h-4" />
      </button>
      {editingId !== null && (
        <p className="text-xs text-center text-gray-400">Save or cancel your edit before continuing.</p>
      )}
    </div>
  );
}
