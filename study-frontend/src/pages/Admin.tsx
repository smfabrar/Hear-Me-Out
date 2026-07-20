import { useCallback, useEffect, useState, type ReactNode } from "react"
import { Button } from "@shared/ui/button"
import { Input } from "@shared/ui/input"
import { Spinner } from "@shared/ui/spinner"
import { Badge } from "@shared/ui/badge"
import { adminApi } from "@/api"

const TOKEN_KEY = "study_admin_token"

export function Admin() {
  const [token, setToken] = useState(localStorage.getItem(TOKEN_KEY) || "")
  const [authed, setAuthed] = useState(false)
  const [configText, setConfigText] = useState("")
  const [targets, setTargets] = useState<any[]>([])
  const [participants, setParticipants] = useState<any[]>([])
  const [runs, setRuns] = useState<any[]>([])
  const [sessions, setSessions] = useState<any[]>([])
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async (tok: string) => {
    setErr(null)
    const cfg = await adminApi.getConfig(tok)
    setConfigText(JSON.stringify(cfg.config, null, 2))
    setTargets(cfg.targets || [])
    setParticipants(cfg.participants || [])
    setAuthed(true)
    localStorage.setItem(TOKEN_KEY, tok)
    try {
      setRuns((await adminApi.runs(tok)).runs || [])
      setSessions((await adminApi.sessions(tok)).sessions || [])
    } catch { /* ignore */ }
  }, [])

  useEffect(() => { if (token) load(token).catch(e => setErr(e.message)) }, []) // eslint-disable-line

  const withBusy = async (fn: () => Promise<any>, ok?: string) => {
    setBusy(true); setErr(null); setMsg(null)
    try { await fn(); if (ok) setMsg(ok); await load(token) }
    catch (e: any) { setErr(e?.message || String(e)) }
    finally { setBusy(false) }
  }

  if (!authed) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 px-4">
        <h1 className="text-xl font-semibold">Study admin</h1>
        <div className="flex w-full max-w-sm gap-2">
          <Input type="password" value={token} onChange={e => setToken(e.target.value)}
                 placeholder="Admin token" onKeyDown={e => e.key === "Enter" && load(token).catch(x => setErr(x.message))} />
          <Button onClick={() => load(token).catch(e => setErr(e.message))}>Sign in</Button>
        </div>
        {err && <p className="text-sm text-destructive">{err}</p>}
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold">Study admin</h1>
        <div className="flex items-center gap-2">
          <a href={adminApi.exportUrl("json") + `&_t=${Date.now()}`}
             onClick={(e) => { e.preventDefault(); downloadWithToken(adminApi.exportUrl("json"), token, "study_export.json") }}>
            <Button variant="secondary" size="sm">Export JSON</Button>
          </a>
          <a href={adminApi.exportUrl("zip")}
             onClick={(e) => { e.preventDefault(); downloadWithToken(adminApi.exportUrl("zip"), token, "study_export.zip") }}>
            <Button variant="secondary" size="sm">Export ZIP</Button>
          </a>
        </div>
      </div>

      {msg && <p className="mb-3 text-sm text-primary">{msg}</p>}
      {err && <p className="mb-3 text-sm text-destructive">{err}</p>}

      <Section title="Study control">
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => withBusy(() => adminApi.activate(token), "Study activated")} disabled={busy}>Activate study</Button>
          <Button variant="secondary" onClick={() => withBusy(() => adminApi.stopEngine(token), "Engine stopped")} disabled={busy}>Stop VC engine</Button>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          The VC engine starts automatically when a participant begins a run (not here).
        </p>
      </Section>

      <Section title="Configuration (JSON)">
        <p className="mb-2 text-xs text-muted-foreground">
          Edit conditions (scenario cards, system prompts, voice_mode, target_ref, steps, time limits) and questionnaires.
        </p>
        <textarea className="h-80 w-full rounded-md border bg-background p-3 font-mono text-xs"
                  value={configText} onChange={e => setConfigText(e.target.value)} />
        <div className="mt-2">
          <Button disabled={busy} onClick={() => withBusy(async () => {
            const parsed = JSON.parse(configText)
            await adminApi.putConfig(token, parsed)
          }, "Configuration saved")}>Save configuration</Button>
        </div>
      </Section>

      <Section title="Target voices">
        <TargetUpload token={token} onDone={() => load(token)} />
        <ul className="mt-3 space-y-1 text-sm">
          {targets.map(t => (
            <li key={t.id} className="flex items-center gap-2">
              <Badge variant="secondary">{t.ref}</Badge>
              <span>{t.label}</span>
              <span className="text-xs text-muted-foreground">
                {t.engine_target_id ? `loaded: ${t.engine_target_id}` : "not loaded"}
              </span>
            </li>
          ))}
          {targets.length === 0 && <li className="text-sm text-muted-foreground">No targets uploaded.</li>}
        </ul>
      </Section>

      <Section title="Participants">
        <ParticipantGen token={token} onDone={() => load(token)} />
        <div className="mt-3 max-h-48 overflow-auto rounded-md border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left"><tr><th className="p-2">ID</th><th className="p-2">Code</th></tr></thead>
            <tbody>
              {participants.map(p => (
                <tr key={p.participant_id} className="border-t">
                  <td className="p-2">{p.participant_id}</td>
                  <td className="p-2 font-mono">{p.code}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Runs & sessions">
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <h3 className="mb-1 text-sm font-medium">Runs</h3>
            <div className="max-h-64 overflow-auto rounded-md border text-sm">
              <table className="w-full">
                <thead className="bg-muted/50 text-left"><tr><th className="p-2">Participant</th><th className="p-2">Status</th><th className="p-2">Left</th></tr></thead>
                <tbody>
                  {runs.map((r, i) => (
                    <tr key={i} className="border-t">
                      <td className="p-2">{r.participant_id}</td>
                      <td className="p-2"><Badge variant={r.status === "submitted" ? "default" : r.status === "expired" ? "destructive" : "secondary"}>{r.status}</Badge></td>
                      <td className="p-2 tabular-nums">{r.remaining_seconds ? `${Math.floor(r.remaining_seconds / 60)}m` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <div>
            <h3 className="mb-1 text-sm font-medium">Sessions</h3>
            <div className="max-h-64 overflow-auto rounded-md border text-sm">
              <table className="w-full">
                <thead className="bg-muted/50 text-left"><tr><th className="p-2">Session</th><th className="p-2">Cond.</th><th className="p-2">End</th></tr></thead>
                <tbody>
                  {sessions.map((s) => (
                    <tr key={s.session_id} className="border-t">
                      <td className="p-2 font-mono text-xs">{s.session_id}</td>
                      <td className="p-2">{s.voice_condition}</td>
                      <td className="p-2 text-xs">{s.end_reason || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </Section>

      {busy && <div className="fixed bottom-4 right-4"><Spinner /></div>}
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mb-6 rounded-xl border bg-card p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">{title}</h2>
      {children}
    </section>
  )
}

function TargetUpload({ token, onDone }: { token: string; onDone: () => void }) {
  const [ref, setRef] = useState("")
  const [speaker, setSpeaker] = useState("")
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  return (
    <div className="flex flex-wrap items-end gap-2">
      <div><label className="text-xs">Ref</label><Input value={ref} onChange={e => setRef(e.target.value)} placeholder="vc1" className="w-24" /></div>
      <div><label className="text-xs">Speaker ID</label><Input value={speaker} onChange={e => setSpeaker(e.target.value)} placeholder="p225" className="w-28" /></div>
      <input type="file" accept="audio/*" onChange={e => setFile(e.target.files?.[0] || null)} className="text-sm" />
      <Button size="sm" disabled={busy || !ref || !file} onClick={async () => {
        if (!file) return
        setBusy(true); setErr(null)
        try { await adminApi.uploadTarget(token, ref, speaker || ref, file.name, file); setRef(""); setSpeaker(""); setFile(null); onDone() }
        catch (e: any) { setErr(e?.message || String(e)) } finally { setBusy(false) }
      }}>Upload</Button>
      {err && <span className="text-xs text-destructive">{err}</span>}
    </div>
  )
}

function ParticipantGen({ token, onDone }: { token: string; onDone: () => void }) {
  const [count, setCount] = useState(5)
  const [busy, setBusy] = useState(false)
  return (
    <div className="flex items-end gap-2">
      <div><label className="text-xs">Count</label><Input type="number" value={count} onChange={e => setCount(Number(e.target.value))} className="w-24" /></div>
      <Button size="sm" disabled={busy} onClick={async () => {
        setBusy(true)
        try { await adminApi.generate(token, count); onDone() } finally { setBusy(false) }
      }}>Generate codes</Button>
    </div>
  )
}

async function downloadWithToken(url: string, token: string, filename: string) {
  const r = await fetch(url, { headers: { "X-Study-Admin-Token": token } })
  const blob = await r.blob()
  const a = document.createElement("a")
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  URL.revokeObjectURL(a.href)
}
