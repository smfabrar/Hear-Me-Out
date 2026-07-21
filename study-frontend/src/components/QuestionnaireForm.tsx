import { useState } from "react"
import { Button } from "@shared/ui/button"
import { cn } from "@shared/lib/utils"

export interface QItem {
  id: string
  type: "text" | "textarea" | "number" | "radio" | "select" | "switch" | "scale"
  label: string
  required?: boolean
  options?: string[]
  min?: number
  max?: number
  min_label?: string
  max_label?: string
  placeholder?: string
}

type Answers = Record<string, unknown>

function isAnswered(item: QItem, v: unknown): boolean {
  if (item.type === "switch") return v === true
  return v !== undefined && v !== null && v !== ""
}

function fieldError(item: QItem, v: unknown): string | null {
  if (item.required && !isAnswered(item, v)) return "This question is required."
  if (item.type === "number" && v !== undefined && v !== null && v !== "") {
    const n = Number(v)
    if (Number.isNaN(n)) return "Enter a number."
    if (item.min !== undefined && n < item.min) return `Must be ≥ ${item.min}.`
    if (item.max !== undefined && n > item.max) return `Must be ≤ ${item.max}.`
  }
  return null
}

export function QuestionnaireForm({
  title, items, onSubmit, submitLabel = "Continue", busy = false,
}: {
  title: string
  items: QItem[]
  onSubmit: (answers: Answers) => void
  submitLabel?: string
  busy?: boolean
}) {
  const [answers, setAnswers] = useState<Answers>({})
  const [showErrors, setShowErrors] = useState(false)
  const set = (id: string, v: unknown) => setAnswers(a => ({ ...a, [id]: v }))

  const submit = () => {
    if (items.some(i => fieldError(i, answers[i.id]))) { setShowErrors(true); return }
    onSubmit(answers)
  }

  return (
    <div className="mx-auto w-full max-w-2xl">
      <h2 className="mb-5 text-xl font-semibold tracking-tight">{title}</h2>
      <div className="flex flex-col gap-6">
        {items.map(item => {
          const v = answers[item.id]
          const err = showErrors ? fieldError(item, v) : null
          return (
            <div key={item.id} className={cn("rounded-lg border p-4", err && "border-destructive")}>
              <label className="mb-3 block text-sm font-medium">
                {item.label}{item.required && <span className="text-destructive"> *</span>}
              </label>
              <QuestionInput item={item} value={v} onChange={(nv) => set(item.id, nv)} />
              {err && <p className="mt-2 text-xs text-destructive">{err}</p>}
            </div>
          )
        })}
        {items.length === 0 && <p className="text-sm text-muted-foreground">No questions.</p>}
      </div>
      <div className="mt-6 flex justify-end">
        <Button onClick={submit} disabled={busy}>{busy ? "Saving…" : submitLabel}</Button>
      </div>
    </div>
  )
}

function QuestionInput({ item, value, onChange }: {
  item: QItem; value: unknown; onChange: (v: unknown) => void
}) {
  if (item.type === "scale") {
    const min = item.min ?? 1, max = item.max ?? 7
    const nums = Array.from({ length: Math.max(0, max - min + 1) }, (_, i) => min + i)
    return (
      <div>
        <div className="flex flex-wrap gap-2">
          {nums.map(n => (
            <button key={n} type="button" onClick={() => onChange(n)}
              className={cn("h-10 w-10 rounded-md border text-sm font-medium transition-colors",
                value === n ? "border-primary bg-primary text-primary-foreground" : "hover:bg-accent")}>{n}</button>
          ))}
        </div>
        {(item.min_label || item.max_label) && (
          <div className="mt-1 flex justify-between text-xs text-muted-foreground">
            <span>{item.min_label}</span><span>{item.max_label}</span>
          </div>
        )}
      </div>
    )
  }

  if (item.type === "radio") {
    return (
      <div className="flex flex-col gap-2">
        {(item.options ?? []).map(opt => (
          <button key={opt} type="button" onClick={() => onChange(opt)}
            className={cn("rounded-md border px-3 py-2 text-left text-sm transition-colors",
              value === opt ? "border-primary bg-primary/10" : "hover:bg-accent")}>{opt}</button>
        ))}
      </div>
    )
  }

  if (item.type === "select") {
    return (
      <select className="w-full rounded-md border bg-background px-3 py-2 text-sm"
        value={(value as string) ?? ""} onChange={e => onChange(e.target.value)}>
        <option value="" disabled>Select…</option>
        {(item.options ?? []).map(opt => <option key={opt} value={opt}>{opt}</option>)}
      </select>
    )
  }

  if (item.type === "switch") {
    return (
      <button type="button" onClick={() => onChange(value !== true)}
        className={cn("flex items-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors",
          value === true ? "border-primary bg-primary/10" : "hover:bg-accent")}>
        <span className={cn("flex h-4 w-4 items-center justify-center rounded border",
          value === true && "border-primary bg-primary text-primary-foreground")}>{value === true ? "✓" : ""}</span>
        I agree
      </button>
    )
  }

  if (item.type === "number") {
    return (
      <input type="number" className="w-40 rounded-md border bg-background px-3 py-2 text-sm"
        value={(value as string) ?? ""} min={item.min} max={item.max}
        placeholder={item.placeholder} onChange={e => onChange(e.target.value)} />
    )
  }

  if (item.type === "textarea") {
    return (
      <textarea className="min-h-[90px] w-full rounded-md border bg-background px-3 py-2 text-sm"
        value={(value as string) ?? ""} placeholder={item.placeholder ?? "Your answer…"}
        onChange={e => onChange(e.target.value)} />
    )
  }

  // text (single line)
  return (
    <input type="text" className="w-full rounded-md border bg-background px-3 py-2 text-sm"
      value={(value as string) ?? ""} placeholder={item.placeholder ?? "Your answer…"}
      onChange={e => onChange(e.target.value)} />
  )
}
