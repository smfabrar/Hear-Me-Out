import { useState } from "react"
import { Button } from "@shared/ui/button"
import { Input } from "@shared/ui/input"
import { adminApi } from "@/api"

const SECTIONS = ["consent", "background", "post", "final"] as const
const TYPES = ["text", "textarea", "number", "radio", "select", "switch", "scale"]
type Section = typeof SECTIONS[number]
type Item = Record<string, any>

let _uid = 0
const newId = () => `q_${Date.now()}_${_uid++}`

export function QuestionnaireBuilder({ token, studyId, questionnaires, onChange }: {
  token: string; studyId: number; questionnaires: Record<string, Item[]>; onChange: () => void
}) {
  const [q, setQ] = useState<Record<string, Item[]>>(() => ({
    consent: [...(questionnaires.consent || [])],
    background: [...(questionnaires.background || [])],
    post: [...(questionnaires.post || [])],
    final: [...(questionnaires.final || [])],
  }))
  const [active, setActive] = useState<Section>("consent")
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const items = q[active] || []
  const setItems = (updater: (a: Item[]) => Item[]) => setQ(prev => ({ ...prev, [active]: updater(prev[active] || []) }))
  const update = (i: number, patch: Item) => setItems(a => a.map((it, j) => j === i ? { ...it, ...patch } : it))
  const move = (i: number, dir: -1 | 1) => setItems(a => {
    const j = i + dir; if (j < 0 || j >= a.length) return a
    const c = [...a];[c[i], c[j]] = [c[j], c[i]]; return c
  })

  const save = async () => {
    setBusy(true); setMsg(null)
    try { await adminApi.setQuestionnaires(token, studyId, q); setMsg("Saved"); onChange() }
    catch (e: any) { setMsg(e?.message || String(e)) } finally { setBusy(false) }
  }

  return (
    <div>
      <div className="mb-4 flex gap-1">
        {SECTIONS.map(s => (
          <button key={s} onClick={() => setActive(s)}
            className={`rounded-md px-3 py-1.5 text-sm capitalize ${active === s ? "bg-primary text-primary-foreground" : "border"}`}>
            {s} <span className="opacity-60">({(q[s] || []).length})</span>
          </button>
        ))}
      </div>

      <div className="flex flex-col gap-3">
        {items.map((it, i) => (
          <div key={it.id || i} className="rounded-lg border p-3">
            <div className="mb-2 flex items-center gap-2">
              <select className="rounded-md border bg-background px-2 py-1 text-sm" value={it.type || "text"}
                onChange={e => update(i, { type: e.target.value })}>
                {TYPES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
              <label className="flex items-center gap-1 text-xs">
                <input type="checkbox" checked={!!it.required} onChange={e => update(i, { required: e.target.checked })} /> required
              </label>
              <div className="ml-auto flex gap-1">
                <Button size="sm" variant="ghost" onClick={() => move(i, -1)}>↑</Button>
                <Button size="sm" variant="ghost" onClick={() => move(i, 1)}>↓</Button>
                <Button size="sm" variant="ghost" onClick={() => setItems(a => a.filter((_, j) => j !== i))}>✕</Button>
              </div>
            </div>
            <Input value={it.label || ""} placeholder="Question label" onChange={e => update(i, { label: e.target.value })} />
            {(it.type === "radio" || it.type === "select") && (
              <Input className="mt-2" placeholder="Options (comma separated)"
                value={(it.options || []).join(", ")}
                onChange={e => update(i, { options: e.target.value.split(",").map(s => s.trim()).filter(Boolean) })} />
            )}
            {(it.type === "number" || it.type === "scale") && (
              <div className="mt-2 flex gap-2">
                <Input type="number" className="w-24" placeholder="min" value={it.min ?? ""} onChange={e => update(i, { min: e.target.value === "" ? undefined : Number(e.target.value) })} />
                <Input type="number" className="w-24" placeholder="max" value={it.max ?? ""} onChange={e => update(i, { max: e.target.value === "" ? undefined : Number(e.target.value) })} />
                {it.type === "scale" && <>
                  <Input className="flex-1" placeholder="min label" value={it.min_label ?? ""} onChange={e => update(i, { min_label: e.target.value })} />
                  <Input className="flex-1" placeholder="max label" value={it.max_label ?? ""} onChange={e => update(i, { max_label: e.target.value })} />
                </>}
              </div>
            )}
          </div>
        ))}
        <Button variant="secondary" onClick={() => setItems(a => [...a, { id: newId(), type: "text", label: "", required: false }])}>
          + Add question
        </Button>
      </div>

      <div className="mt-4 flex items-center gap-3">
        <Button disabled={busy} onClick={save}>{busy ? "Saving…" : "Save questionnaires"}</Button>
        {msg && <span className="text-sm text-muted-foreground">{msg}</span>}
      </div>
    </div>
  )
}
