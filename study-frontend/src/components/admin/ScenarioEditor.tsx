import { useMemo, useState } from "react"
import { Button } from "@shared/ui/button"
import { Input } from "@shared/ui/input"
import { adminApi } from "@/api"

type Preset = "natural" | "vc" | "natural_vc" | "vc_natural"

function scheduleFromPreset(preset: Preset, engine: string, target: string, switchS: number): any[] {
  if (preset === "natural") return [{ mode: "natural", start_s: 0, end_s: null }]
  if (preset === "vc") return [{ mode: "vc", engine, target_ref: target, start_s: 0, end_s: null }]
  if (preset === "natural_vc") return [
    { mode: "natural", start_s: 0, end_s: switchS },
    { mode: "vc", engine, target_ref: target, start_s: switchS, end_s: null }]
  return [
    { mode: "vc", engine, target_ref: target, start_s: 0, end_s: switchS },
    { mode: "natural", start_s: switchS, end_s: null }]
}

function presetFromSchedule(schedule: any[]): { preset: Preset; engine: string; target: string; switchS: number } {
  const segs = schedule || []
  const vc = segs.find(s => s.mode === "vc") || {}
  const engine = vc.engine || "meanvc"
  const target = vc.target_ref || ""
  if (segs.length <= 1) {
    const only = segs[0]?.mode || "natural"
    return { preset: only === "vc" ? "vc" : "natural", engine, target, switchS: 25 }
  }
  const first = segs[0]?.mode
  const switchS = segs[0]?.end_s ?? 25
  return { preset: first === "natural" ? "natural_vc" : "vc_natural", engine, target, switchS }
}

export function ScenarioEditor({ token, studyId, scenario, index, voices, engines, targets, onChange }: any) {
  const [open, setOpen] = useState(false)
  const card = scenario.scenario_card || {}
  const init = useMemo(() => presetFromSchedule(scenario.voice_schedule), [scenario.id])

  const [title, setTitle] = useState(scenario.title || "")
  const [role, setRole] = useState(card.role || "")
  const [goal, setGoal] = useState(card.task_goal || "")
  const [facts, setFacts] = useState(card.relevant_facts || "")
  const [success, setSuccess] = useState(card.success_criteria || "")
  const [prompt, setPrompt] = useState(scenario.system_prompt || "")
  const [voicePrompt, setVoicePrompt] = useState(scenario.voice_prompt || voices[0] || "NATF2.pt")
  const [timeLimit, setTimeLimit] = useState(scenario.time_limit_s || 300)
  const [preset, setPreset] = useState<Preset>(init.preset)
  const [engine, setEngine] = useState(init.engine)
  const [target, setTarget] = useState(init.target)
  const [switchS, setSwitchS] = useState(init.switchS)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const needsTarget = preset !== "natural"
  const needsSwitch = preset === "natural_vc" || preset === "vc_natural"
  const engineTargets = targets.filter((t: any) => t.engine === engine)

  const save = async () => {
    if (needsTarget && !target) { setErr("Pick a target voice for this VC scenario."); return }
    setBusy(true); setErr(null)
    try {
      await adminApi.updateScenario(token, studyId, scenario.id, {
        order_idx: scenario.order_idx ?? index, title,
        scenario_card: { role, task_goal: goal, relevant_facts: facts, success_criteria: success },
        system_prompt: prompt, voice_prompt: voicePrompt, time_limit_s: Number(timeLimit),
        voice_schedule: scheduleFromPreset(preset, engine, target, Number(switchS)),
      })
      onChange()
    } catch (e: any) { setErr(e?.message || String(e)) } finally { setBusy(false) }
  }

  return (
    <div className="rounded-lg border">
      <button className="flex w-full items-center justify-between px-4 py-3 text-left" onClick={() => setOpen(o => !o)}>
        <span className="font-medium">{index + 1}. {title || "Untitled scenario"}</span>
        <span className="text-xs text-muted-foreground">{preset.replace("_", "→")}{needsTarget ? ` · ${engine}` : ""}</span>
      </button>
      {open && (
        <div className="flex flex-col gap-3 border-t p-4">
          <Field label="Title"><Input value={title} onChange={e => setTitle(e.target.value)} /></Field>
          <Field label="Participant role"><Input value={role} onChange={e => setRole(e.target.value)} /></Field>
          <Field label="Task goal"><Textarea value={goal} onChange={setGoal} /></Field>
          <Field label="Relevant facts"><Textarea value={facts} onChange={setFacts} /></Field>
          <Field label="Success criteria"><Textarea value={success} onChange={setSuccess} /></Field>
          <Field label="System prompt (hidden from participant)"><Textarea value={prompt} onChange={setPrompt} /></Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Assistant voice">
              <Select value={voicePrompt} onChange={setVoicePrompt} options={voices} />
            </Field>
            <Field label="Time limit (s)">
              <Input type="number" value={timeLimit} onChange={e => setTimeLimit(Number(e.target.value))} />
            </Field>
          </div>

          <div className="rounded-md border p-3">
            <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">Voice schedule</div>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Field label="Mode">
                <Select value={preset} onChange={v => setPreset(v as Preset)}
                  options={["natural", "vc", "natural_vc", "vc_natural"]}
                  labels={{ natural: "Natural only", vc: "VC only", natural_vc: "Natural → VC", vc_natural: "VC → Natural" }} />
              </Field>
              {needsTarget && (
                <Field label="Engine"><Select value={engine} onChange={v => { setEngine(v); setTarget("") }} options={engines} /></Field>
              )}
              {needsTarget && (
                <Field label="Target voice">
                  <Select value={target} onChange={setTarget}
                    options={engineTargets.map((t: any) => t.ref)}
                    labels={Object.fromEntries(engineTargets.map((t: any) => [t.ref, `${t.ref} (${t.speaker_id})`]))}
                    placeholder="Select target" />
                </Field>
              )}
              {needsSwitch && (
                <Field label="Switch at (s)"><Input type="number" value={switchS} onChange={e => setSwitchS(Number(e.target.value))} /></Field>
              )}
            </div>
            {needsTarget && engineTargets.length === 0 && (
              <p className="mt-2 text-xs text-destructive">No {engine} targets uploaded — add one in the Targets tab.</p>
            )}
          </div>

          {err && <p className="text-sm text-destructive">{err}</p>}
          <div className="flex gap-2">
            <Button size="sm" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save scenario"}</Button>
            <Button size="sm" variant="ghost" onClick={async () => { await adminApi.deleteScenario(token, studyId, scenario.id); onChange() }}>Delete</Button>
          </div>
        </div>
      )}
    </div>
  )
}

function Field({ label, children }: { label: string; children: any }) {
  return <div className="flex flex-col gap-1"><label className="text-xs text-muted-foreground">{label}</label>{children}</div>
}
function Textarea({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return <textarea className="min-h-[60px] w-full rounded-md border bg-background px-3 py-2 text-sm"
    value={value} onChange={e => onChange(e.target.value)} />
}
function Select({ value, onChange, options, labels, placeholder }: {
  value: string; onChange: (v: string) => void; options: string[]; labels?: Record<string, string>; placeholder?: string
}) {
  return (
    <select className="w-full rounded-md border bg-background px-2 py-2 text-sm" value={value} onChange={e => onChange(e.target.value)}>
      {placeholder && <option value="">{placeholder}</option>}
      {options.map(o => <option key={o} value={o}>{labels?.[o] ?? o}</option>)}
    </select>
  )
}
