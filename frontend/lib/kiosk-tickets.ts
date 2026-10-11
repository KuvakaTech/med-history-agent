// Ticket desk for the Gwalior Nagar Seva grievance kiosk.
//
// The kiosk backend stores a grievance per session but has no notion of who
// owns it, so officer ownership, the L1 -> L2 -> L3 escalation ladder and the
// closure log all live here on the client. Escalation level is *derived* from
// elapsed time against the department SLA (never stored), so it stays
// consistent without any background job having to tick it forward.
"use client";

import type { KioskAdminSession, KioskCentre } from "./kiosk-admin-types";

export const TICKET_CENTRE_SLUG = "gwalior-nagar-seva";

/** The ticket desk replaces the plain session table only for this kiosk. */
export function isTicketCentre(centre?: KioskCentre | null): boolean {
  return !!centre && centre.slug === TICKET_CENTRE_SLUG;
}

// ── Departments ───────────────────────────────────────────────

export type TicketLevel = 1 | 2 | 3;

export interface Department {
  key: string;
  label: string;
  labelHi: string;
  /** Hours an officer at one level gets before the ticket escalates. */
  slaHours: number;
}

export const DEPARTMENTS: Department[] = [
  { key: "water", label: "Jal Pradaay / PHE", labelHi: "जल प्रदाय", slaHours: 12 },
  { key: "sewer", label: "Sewer / Drainage", labelHi: "सीवर एवं नाली", slaHours: 24 },
  { key: "sanitation", label: "Health / Sanitation", labelHi: "स्वास्थ्य एवं सफाई", slaHours: 24 },
  { key: "electrical", label: "Electrical (GMC)", labelHi: "विद्युत शाखा", slaHours: 24 },
  { key: "roads", label: "Engineering / PWD", labelHi: "अभियांत्रिकी", slaHours: 48 },
  { key: "animal", label: "Animal Control", labelHi: "पशु नियंत्रण", slaHours: 24 },
  { key: "encroachment", label: "Encroachment Cell", labelHi: "अतिक्रमण शाखा", slaHours: 72 },
  { key: "building", label: "Building / Town Planning", labelHi: "भवन अनुज्ञा", slaHours: 72 },
  { key: "garden", label: "Udyan (Garden)", labelHi: "उद्यान शाखा", slaHours: 48 },
  { key: "fire", label: "Fire (GMC)", labelHi: "अग्निशमन", slaHours: 4 },
  { key: "certificates", label: "Janm-Mrityu Cell", labelHi: "जन्म-मृत्यु शाखा", slaHours: 48 },
  { key: "revenue", label: "Revenue / Market", labelHi: "राजस्व एवं बाज़ार", slaHours: 72 },
  { key: "welfare", label: "Welfare Cell", labelHi: "कल्याण शाखा", slaHours: 72 },
  { key: "smartcity", label: "Smart City / ICCC", labelHi: "स्मार्ट सिटी", slaHours: 48 },
  { key: "publichealth", label: "Health / Malaria Cell", labelHi: "जन स्वास्थ्य", slaHours: 24 },
  { key: "unassigned", label: "To Be Assigned", labelHi: "आवंटन शेष", slaHours: 48 },
];

const DEPT_BY_KEY: Record<string, Department> = Object.fromEntries(
  DEPARTMENTS.map((d) => [d.key, d])
);

// Keyword routing — the agent writes `category` / `department_tag` as free text
// (Hindi, Hinglish or English), so match on substrings rather than an enum.
const ROUTING: Array<{ dept: string; words: string[] }> = [
  { dept: "water", words: ["water", "jal", "paani", "nal ", "tanker", "pipeline", "phe"] },
  { dept: "sewer", words: ["sewer", "drain", "naali", "nala", "manhole", "chamber", "waterlog"] },
  {
    dept: "sanitation",
    words: ["garbage", "kachra", "safai", "sanitation", "dustbin", "malba", "toilet", "shauchalay"],
  },
  { dept: "electrical", words: ["street", "light", "khamba", "pole", "electric", "bijli", "vidyut"] },
  {
    dept: "roads",
    words: ["road", "sadak", "gaddha", "pothole", "footpath", "digging", "khudai", "divider", "pwd", "engineering"],
  },
  {
    dept: "animal",
    words: ["animal", "stray", "kutte", "dog", "cattle", "gaay", "saand", "suar", "bandar", "gaushala"],
  },
  { dept: "encroachment", words: ["encroach", "atikraman", "kabza", "thela", "gumti"] },
  { dept: "building", words: ["building", "nirmaan", "construction", "naksha", "jarjar", "town planning"] },
  { dept: "garden", words: ["tree", "ped ", "park", "udyan", "garden", "jhula"] },
  { dept: "fire", words: ["fire", "aag", "gas leak", "agnishaman"] },
  {
    dept: "certificates",
    words: ["certificate", "praman", "janm", "birth", "mrityu", "death", "vivah", "marriage"],
  },
  {
    dept: "revenue",
    words: ["revenue", "tax", "kar ", "bill", "licence", "license", "hoarding", "market", "haat", "gumasta", "sampatti"],
  },
  { dept: "welfare", words: ["welfare", "pension", "awas", "sambal", "svanidhi", "scheme", "yojana", "kalyan"] },
  { dept: "smartcity", words: ["smart", "cctv", "wi-fi", "wifi", "iccc", "parking", "city bus", "shelter"] },
  { dept: "publichealth", words: ["machhar", "mosquito", "fogging", "dengue", "malaria", "public health"] },
];

export function departmentFor(session: KioskAdminSession): Department {
  const g = (session.grievance ?? {}) as Record<string, unknown>;
  const haystack = [g.department_tag, g.category, g.sub_category, session.session_summary]
    .filter((v): v is string => typeof v === "string")
    .join(" ")
    .toLowerCase();

  for (const route of ROUTING) {
    if (route.words.some((w) => haystack.includes(w))) return DEPT_BY_KEY[route.dept];
  }
  return DEPT_BY_KEY.unassigned;
}

// ── Officer roster ────────────────────────────────────────────

export interface Officer {
  id: string;
  name: string;
  designation: string;
  level: TicketLevel;
  department: string;
}

/** L1 is a pool (field staff); L2 and L3 are single post-holders per wing. */
const ROSTER: Record<string, { l1: string[]; l2: string; l3: string }> = {
  water: { l1: ["A. K. Mishra", "S. Tomar", "R. Namdev"], l2: "P. K. Shrivastava", l3: "Dr. N. Bhadauria" },
  sewer: { l1: ["D. Sahu", "M. Rathore"], l2: "P. K. Shrivastava", l3: "Dr. N. Bhadauria" },
  sanitation: { l1: ["V. Chaturvedi", "P. Kol", "S. Jatav"], l2: "R. S. Parihar", l3: "Dr. N. Bhadauria" },
  electrical: { l1: ["R. Pandey", "M. Khan"], l2: "V. Agrawal", l3: "Er. S. K. Gupta" },
  roads: { l1: ["N. Dubey", "P. Singh", "A. Rawat"], l2: "Er. K. Shukla", l3: "Er. S. K. Gupta" },
  animal: { l1: ["H. Bagri", "J. Verma"], l2: "R. S. Parihar", l3: "Dr. N. Bhadauria" },
  encroachment: { l1: ["S. Yadav", "M. Prajapati"], l2: "A. Chouhan", l3: "Er. S. K. Gupta" },
  building: { l1: ["G. Sharma", "T. Batham"], l2: "A. Chouhan", l3: "Er. S. K. Gupta" },
  garden: { l1: ["B. Kushwah"], l2: "R. S. Parihar", l3: "Dr. N. Bhadauria" },
  fire: { l1: ["Station Officer, Phoolbagh"], l2: "A. Chouhan", l3: "Er. S. K. Gupta" },
  certificates: { l1: ["Counter Clerk, Janm-Mrityu"], l2: "S. Dixit", l3: "Smt. A. Sikarwar" },
  revenue: { l1: ["K. Shivhare", "U. Jain"], l2: "S. Dixit", l3: "Smt. A. Sikarwar" },
  welfare: { l1: ["L. Baghel"], l2: "S. Dixit", l3: "Smt. A. Sikarwar" },
  smartcity: { l1: ["ICCC Duty Engineer"], l2: "V. Agrawal", l3: "Er. S. K. Gupta" },
  publichealth: { l1: ["Malaria Inspector, Zone 2"], l2: "R. S. Parihar", l3: "Dr. N. Bhadauria" },
  unassigned: { l1: ["Duty Officer, Control Room"], l2: "A. Chouhan", l3: "Er. S. K. Gupta" },
};

export const LEVEL_DESIGNATION: Record<TicketLevel, { en: string; hi: string }> = {
  1: { en: "Sub-Engineer / Field Officer", hi: "उप अभियंता" },
  2: { en: "Zonal Officer", hi: "क्षेत्राधिकारी" },
  3: { en: "Additional Commissioner", hi: "अपर आयुक्त" },
};

function hash(text: string): number {
  let h = 0;
  for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) >>> 0;
  return h;
}

function officerAt(dept: Department, level: TicketLevel, seed: string): Officer {
  const wing = ROSTER[dept.key] ?? ROSTER.unassigned;
  const name =
    level === 1 ? wing.l1[hash(seed) % wing.l1.length] : level === 2 ? wing.l2 : wing.l3;
  return makeOfficer(dept.key, level, name);
}

// ── Local closure / escalation overrides ──────────────────────

const STORE_KEY = "gwalior_ticket_desk_v1";

export interface TicketOverride {
  closed_at?: string;
  closed_by?: string;
  closure_note?: string;
}

export type OverrideStore = Record<string, TicketOverride>;

export function readOverrides(): OverrideStore {
  if (typeof window === "undefined") return {};
  try {
    return JSON.parse(window.localStorage.getItem(STORE_KEY) || "{}") as OverrideStore;
  } catch {
    return {};
  }
}

export function writeOverride(sessionId: string, patch: TicketOverride | null): OverrideStore {
  const store = readOverrides();
  if (patch === null) delete store[sessionId];
  else store[sessionId] = { ...store[sessionId], ...patch };
  window.localStorage.setItem(STORE_KEY, JSON.stringify(store));
  return store;
}

// ── Ticket derivation ─────────────────────────────────────────

export interface EscalationEvent {
  fromLevel: TicketLevel;
  toLevel: TicketLevel;
  at: number;
  reason: string;
}

export interface Ticket {
  session: KioskAdminSession;
  ticketNo: string;
  department: Department;
  /** Hours each level gets — halved for urgent grievances. */
  slaHours: number;
  level: TicketLevel;
  assignee: Officer;
  ladder: Officer[];
  urgent: boolean;
  ward: string | null;
  summary: string;
  filedAt: number | null;
  /** When the current holder runs out of time (ms epoch); null once closed. */
  dueAt: number | null;
  /** Negative once the SLA is breached. */
  msRemaining: number;
  overdue: boolean;
  closed: boolean;
  closedAt: string | null;
  closureNote: string | null;
  closedBy: string | null;
  escalations: EscalationEvent[];
}

function grievanceOf(s: KioskAdminSession): Record<string, unknown> {
  return (s.grievance ?? {}) as Record<string, unknown>;
}

function wardOf(s: KioskAdminSession): string | null {
  const g = grievanceOf(s);
  for (const key of ["complaint_address", "residential_address"]) {
    const addr = g[key] as Record<string, unknown> | undefined;
    const ward = addr?.gp_ward ?? addr?.village_mohalla;
    if (typeof ward === "string" && ward.trim()) return ward.trim();
  }
  return null;
}

export function buildTicket(
  s: KioskAdminSession,
  override: TicketOverride | undefined,
  now: number
): Ticket {
  const g = grievanceOf(s);
  const department = departmentFor(s);
  const urgent = String(g.urgency ?? "").toLowerCase().includes("urgent");
  const slaHours = urgent ? Math.max(2, department.slaHours / 2) : department.slaHours;
  const slaMs = slaHours * 3600_000;

  const filedAt = s.started_at ? new Date(s.started_at).getTime() : null;
  const closedAt = override?.closed_at ?? null;
  const closed = !!closedAt;
  const endMs = closedAt ? new Date(closedAt).getTime() : now;
  const elapsed = filedAt ? Math.max(0, endMs - filedAt) : 0;

  // Pure function of elapsed time: an unresolved ticket climbs the ladder by
  // itself, and a closed one keeps the level it was closed at.
  const level = Math.min(3, 1 + Math.floor(elapsed / slaMs)) as TicketLevel;

  const ladder: Officer[] = ([1, 2, 3] as TicketLevel[]).map((lvl) =>
    officerAt(department, lvl, s.session_id)
  );
  const assignee = ladder[level - 1];

  const escalations: EscalationEvent[] = [];
  for (let lvl = 2; lvl <= level; lvl++) {
    escalations.push({
      fromLevel: (lvl - 1) as TicketLevel,
      toLevel: lvl as TicketLevel,
      at: (filedAt ?? endMs) + (lvl - 1) * slaMs,
      reason: `${slaHours}h SLA at L${lvl - 1} breached — auto-escalated`,
    });
  }
  // L3 is the last rung — the clock stops there instead of escalating further.
  const dueAt = closed || filedAt === null ? null : filedAt + level * slaMs;
  const msRemaining = dueAt === null ? 0 : dueAt - now;

  return {
    session: s,
    ticketNo: s.complaint_number || `DRAFT-${s.session_id.slice(0, 6).toUpperCase()}`,
    department,
    slaHours,
    level,
    assignee,
    ladder,
    urgent,
    ward: wardOf(s),
    summary: s.session_summary || s.grievance_summary || "—",
    filedAt,
    dueAt,
    msRemaining,
    overdue: !closed && dueAt !== null && msRemaining < 0,
    closed,
    closedAt,
    closureNote: override?.closure_note ?? null,
    closedBy: override?.closed_by ?? null,
    escalations,
  };
}

export function formatDuration(ms: number): string {
  const abs = Math.abs(ms);
  const hours = Math.floor(abs / 3600_000);
  const minutes = Math.floor((abs % 3600_000) / 60_000);
  if (hours >= 24) return `${Math.floor(hours / 24)}d ${hours % 24}h`;
  if (hours >= 1) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

/**
 * Time left with the current holder. Only an L3 ticket can read as overdue —
 * below that the clock running out is an escalation, not a breach.
 */
export function slaLabel(t: Ticket): string {
  if (t.closed) return "Closed";
  if (t.dueAt === null) return "—";
  if (t.msRemaining < 0) return `Overdue by ${formatDuration(t.msRemaining)}`;
  return `${formatDuration(t.msRemaining)} left`;
}

/** One officer plus their workload. */
export interface OfficerLane {
  officer: Officer;
  departmentLabel: string;
  open: number;
  overdue: number;
  closed: number;
  total: number;
  /** True for officers added from the desk rather than the standing roster. */
  custom: boolean;
}

// ── Officer directory ─────────────────────────────────────────

const CUSTOM_OFFICERS_KEY = "gwalior_custom_officers_v1";

export interface CustomOfficer {
  id: string;
  name: string;
  level: TicketLevel;
  department: string;
}

/** Officers the desk added by hand, on top of the standing GMC roster. */
export function readCustomOfficers(): CustomOfficer[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = JSON.parse(window.localStorage.getItem(CUSTOM_OFFICERS_KEY) || "[]");
    return Array.isArray(raw) ? (raw as CustomOfficer[]) : [];
  } catch {
    return [];
  }
}

function saveCustomOfficers(list: CustomOfficer[]): CustomOfficer[] {
  window.localStorage.setItem(CUSTOM_OFFICERS_KEY, JSON.stringify(list));
  return list;
}

export function addCustomOfficer(officer: Omit<CustomOfficer, "id">): CustomOfficer[] {
  const id = `custom:${officer.department}:${officer.level}:${officer.name}`;
  const list = readCustomOfficers().filter((o) => o.id !== id);
  return saveCustomOfficers([...list, { ...officer, id }]);
}

export function removeCustomOfficer(id: string): CustomOfficer[] {
  return saveCustomOfficers(readCustomOfficers().filter((o) => o.id !== id));
}

export interface RosterEntry {
  officer: Officer;
  /** Every wing this officer covers — L2/L3 posts serve more than one. */
  departments: string[];
}

/** Every officer on the ladder, whether or not they currently hold a ticket. */
export function fullRoster(custom: CustomOfficer[] = []): RosterEntry[] {
  const entries = new Map<string, RosterEntry>();

  const add = (departmentKey: string, level: TicketLevel, name: string, id?: string) => {
    const base = makeOfficer(departmentKey, level, name);
    const officer = id ? { ...base, id } : base;
    const existing = entries.get(officer.id);
    if (existing) {
      if (!existing.departments.includes(departmentKey)) existing.departments.push(departmentKey);
      return;
    }
    entries.set(officer.id, { officer, departments: [departmentKey] });
  };

  for (const dept of DEPARTMENTS) {
    const wing = ROSTER[dept.key] ?? ROSTER.unassigned;
    for (const name of wing.l1) add(dept.key, 1, name);
    add(dept.key, 2, wing.l2);
    add(dept.key, 3, wing.l3);
  }
  for (const c of custom) add(c.department, c.level, c.name, c.id);

  return [...entries.values()];
}

/**
 * Officer identity is the post holder, not the wing: one L2/L3 officer covers
 * several departments, so the id must not include the department or their
 * tickets would split across duplicate entries.
 */
function makeOfficer(departmentKey: string, level: TicketLevel, name: string): Officer {
  return {
    id: `L${level}:${name}`,
    name,
    designation: LEVEL_DESIGNATION[level].en,
    level,
    department: departmentKey,
  };
}

export function departmentLabel(key: string): string {
  return (DEPT_BY_KEY[key] ?? DEPT_BY_KEY.unassigned).label;
}

/** "Jal Pradaay / PHE · Sewer +2" — keeps multi-wing officers readable. */
export function wingsLabel(keys: string[]): string {
  const labels = keys.map(departmentLabel);
  if (labels.length <= 2) return labels.join(" · ");
  return `${labels.slice(0, 2).join(" · ")} +${labels.length - 2}`;
}

/**
 * The full ladder with each officer's workload counted from the live tickets.
 * Officers with nothing assigned still appear, so L2 and L3 are never empty.
 */
export function officerLanes(tickets: Ticket[], custom: CustomOfficer[] = []): OfficerLane[] {
  const lanes = new Map<string, OfficerLane>();
  for (const entry of fullRoster(custom)) {
    lanes.set(entry.officer.id, {
      officer: entry.officer,
      departmentLabel: wingsLabel(entry.departments),
      open: 0,
      overdue: 0,
      closed: 0,
      total: 0,
      custom: entry.officer.id.startsWith("custom:"),
    });
  }

  for (const t of tickets) {
    const lane = lanes.get(t.assignee.id) ?? {
      officer: t.assignee,
      departmentLabel: t.department.label,
      open: 0,
      overdue: 0,
      closed: 0,
      total: 0,
      custom: false,
    };
    lane.total += 1;
    if (t.closed) lane.closed += 1;
    else {
      lane.open += 1;
      if (t.overdue) lane.overdue += 1;
    }
    lanes.set(t.assignee.id, lane);
  }

  return [...lanes.values()].sort(
    (a, b) =>
      a.officer.level - b.officer.level ||
      b.open - a.open ||
      b.total - a.total ||
      a.officer.name.localeCompare(b.officer.name)
  );
}
