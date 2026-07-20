// Study API client. Participant calls are same-origin (served by app-api).
// Admin calls carry the X-Study-Admin-Token header.

const BASE = "/api/study";

async function jpost(path: string, body: unknown, headers: Record<string, string> = {}) {
  const r = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw await asError(r);
  return r.json();
}

async function asError(r: Response): Promise<Error> {
  let detail = `HTTP ${r.status}`;
  try {
    const d = await r.json();
    if (d?.detail) detail = d.detail;
  } catch { /* ignore */ }
  const e = new Error(detail) as Error & { status?: number };
  e.status = r.status;
  return e;
}

// ---------- participant ----------
export interface ScenarioInfo {
  scenario_order: number;
  scenario_id: string;
  role: string;
  task_goal: string;
  relevant_facts: string;
  success_criteria: string;
  time_limit_s: number;
}

export interface RunState {
  status: "not_started" | "in_progress" | "submitted" | "expired";
  current_step?: Record<string, any>;
  completed?: Record<string, any>;
  remaining_seconds?: number;
  attempt?: number;
}

export interface EnterResult {
  participant_id: string;
  study_name: string;
  scenarios: ScenarioInfo[];
  questionnaires?: Record<string, any[]>;
  run: RunState;
}

export const api = {
  enter: (code: string): Promise<EnterResult> => jpost("/enter", { code }),
  runStart: (code: string, mode: "resume" | "restart") => jpost("/run/start", { code, mode }),
  prepareStatus: () => fetch(`${BASE}/run/prepare/status`).then(r => r.json()),
  progress: (code: string, current_step: Record<string, any>, completed: Record<string, any>) =>
    jpost("/run/progress", { code, current_step, completed }),
  sessionStart: (code: string, scenario_order: number) =>
    jpost("/session/start", { code, scenario_order }),
  sessionEnd: (sessionId: string, reason: string) =>
    jpost(`/session/${sessionId}/end`, { reason }),
  questionnaire: (sessionId: string | null, code: string, kind: string, payload: Record<string, any>) =>
    jpost(`/session/${sessionId ?? "none"}/questionnaire`, { code, kind, payload }),
  submit: (code: string) => jpost("/run/submit", { code }),

  async saveSession(sessionId: string, arts: {
    participant?: Blob | null;
    participant_raw?: Blob | null;
    model?: Blob | null;
    merged?: Blob | null;
    transcript?: unknown;
    metrics?: unknown;
    audiobox_available?: boolean;
  }) {
    const fd = new FormData();
    if (arts.participant) fd.append("participant", arts.participant, "participant.wav");
    if (arts.participant_raw) fd.append("participant_raw", arts.participant_raw, "participant_raw.wav");
    if (arts.model) fd.append("model", arts.model, "model.wav");
    if (arts.merged) fd.append("merged", arts.merged, "merged.wav");
    fd.append("transcript", JSON.stringify(arts.transcript ?? null));
    fd.append("metrics", JSON.stringify(arts.metrics ?? null));
    fd.append("audiobox_available", String(!!arts.audiobox_available));
    const r = await fetch(`${BASE}/session/${sessionId}/save`, { method: "POST", body: fd });
    if (!r.ok) throw await asError(r);
    return r.json();
  },
};

// ---------- admin ----------
export function adminHeaders(token: string) {
  return { "X-Study-Admin-Token": token };
}

export const adminApi = {
  getConfig: (token: string) =>
    fetch(`${BASE}/config`, { headers: adminHeaders(token) }).then(async r => {
      if (!r.ok) throw await asError(r);
      return r.json();
    }),
  putConfig: (token: string, config: unknown) => jpost("/config", config, adminHeaders(token)),
  activate: (token: string) => jpost("/activate", {}, adminHeaders(token)),
  stopEngine: (token: string) => jpost("/stop-engine", {}, adminHeaders(token)),
  generate: (token: string, count: number) => jpost("/participants/generate", { count }, adminHeaders(token)),
  runs: (token: string) => fetch(`${BASE}/runs`, { headers: adminHeaders(token) }).then(r => r.json()),
  sessions: (token: string) => fetch(`${BASE}/sessions`, { headers: adminHeaders(token) }).then(r => r.json()),
  async uploadTarget(token: string, ref: string, speakerId: string, label: string, file: File) {
    const fd = new FormData();
    fd.append("wav", file);
    fd.append("ref", ref);
    fd.append("speaker_id", speakerId);
    fd.append("label", label);
    const r = await fetch(`${BASE}/targets`, { method: "POST", headers: adminHeaders(token), body: fd });
    if (!r.ok) throw await asError(r);
    return r.json();
  },
  exportUrl: (format: "json" | "zip") => `${BASE}/export?format=${format}`,
};
