import { useCallback, useEffect, useRef, useState } from "react"
import { Button } from "@shared/ui/button"
import { Badge } from "@shared/ui/badge"
import { Spinner } from "@shared/ui/spinner"
import { Phone, AlertTriangle, CheckCircle2, XCircle } from "lucide-react"
import { useStudyConversation } from "@/hooks/useStudyConversation"
import { api, type ScenarioInfo } from "@/api"

function fmt(s: number) {
  const m = Math.floor(s / 60), r = s % 60
  return `${m}:${r.toString().padStart(2, "0")}`
}

type Phase = "ready" | "connecting" | "active" | "processing" | "error"

export function ScenarioCall({ code, scenario, onDone }: {
  code: string
  scenario: ScenarioInfo
  onDone: () => void
}) {
  const conv = useStudyConversation()
  const [phase, setPhase] = useState<Phase>("ready")
  const [remaining, setRemaining] = useState(scenario.time_limit_s)
  const [errMsg, setErrMsg] = useState<string | null>(null)
  const sessionIdRef = useRef<string | null>(null)

  // Reflect the conversation status into the call phase.
  useEffect(() => {
    if (conv.status === "active" && phase === "connecting") setPhase("active")
    if (conv.status === "error" && (phase === "connecting" || phase === "active")) {
      setErrMsg(conv.error || "Could not connect to the assistant.")
      setPhase("error")
    }
  }, [conv.status, conv.error, phase])

  // Countdown while the call is active.
  useEffect(() => {
    if (phase !== "active") return
    const t = setInterval(() => setRemaining(r => Math.max(0, r - 1)), 1000)
    return () => clearInterval(t)
  }, [phase])

  const startCall = useCallback(async () => {
    setErrMsg(null)
    setPhase("connecting")
    try {
      const { session_id } = await api.sessionStart(code, scenario.scenario_order)
      sessionIdRef.current = session_id
      await conv.start(session_id)
    } catch (e: any) {
      setErrMsg(e?.message || "Could not start the call.")
      setPhase("error")
    }
  }, [code, scenario.scenario_order, conv])

  const endCall = useCallback(async (reason: string) => {
    setPhase("processing")
    const sid = sessionIdRef.current
    try {
      const arts = await conv.stopAndAssemble()
      if (sid) {
        await api.saveSession(sid, arts)
        await api.sessionEnd(sid, reason)
      }
      onDone()
    } catch (e: any) {
      setErrMsg("Saving failed: " + (e?.message || e) + ". You can continue.")
      setPhase("error")
    }
  }, [conv, onDone])

  const statusBadge = () => {
    if (conv.error) return <Badge variant="destructive">Connection error</Badge>
    if (phase === "active") return <Badge>Connected</Badge>
    if (phase === "connecting") return <Badge variant="secondary">Connecting…</Badge>
    return <Badge variant="secondary">Not connected</Badge>
  }

  return (
    <div className="grid gap-5 md:grid-cols-[1fr_320px]">
      {/* Persistent scenario card — visible the entire interaction */}
      <div className="rounded-xl border bg-card p-5">
        <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Scenario {scenario.scenario_order}
        </div>
        <Field label="Your role" value={scenario.role} />
        <Field label="Task goal" value={scenario.task_goal} />
        <Field label="Relevant facts" value={scenario.relevant_facts} />
        <Field label="Success criteria" value={scenario.success_criteria} />
      </div>

      {/* Call controls */}
      <div className="flex flex-col gap-4 rounded-xl border bg-card p-5">
        <div className="flex items-center justify-between">
          {statusBadge()}
          <span className="font-mono text-lg tabular-nums">{fmt(remaining)}</span>
        </div>

        {phase === "ready" && (
          <Button className="w-full gap-2" onClick={startCall}>
            <Phone className="size-4" /> Start Call
          </Button>
        )}

        {phase === "connecting" && (
          <div className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
            <Spinner /> Connecting to the assistant…
          </div>
        )}

        {phase === "active" && (
          <div className="flex flex-col gap-2">
            <p className="text-center text-sm text-muted-foreground">Speak with the assistant. End the call when you are done.</p>
            <Button className="w-full gap-2" onClick={() => endCall("goal_reached")}>
              <CheckCircle2 className="size-4" /> End Call — goal reached
            </Button>
            <Button variant="secondary" className="w-full gap-2" onClick={() => endCall("give_up")}>
              <XCircle className="size-4" /> End Call — give up
            </Button>
          </div>
        )}

        {phase === "processing" && (
          <div className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
            <Spinner /> Saving your session…
          </div>
        )}

        {errMsg && <p className="text-sm text-destructive">{errMsg}</p>}
        {phase === "error" && (
          <div className="flex flex-col gap-2">
            <Button variant="secondary" className="w-full" onClick={startCall}>Try again</Button>
            <Button variant="ghost" className="w-full" onClick={onDone}>Skip / continue</Button>
          </div>
        )}

        {phase !== "processing" && phase !== "error" && (
          <Button
            variant="ghost"
            className="mt-2 w-full gap-2 text-muted-foreground"
            onClick={() => endCall("technical_problem")}
            disabled={phase === "ready"}
          >
            <AlertTriangle className="size-4" /> Technical problem
          </Button>
        )}
      </div>
    </div>
  )
}

function Field({ label, value }: { label: string; value: string }) {
  if (!value) return null
  return (
    <div className="mb-3">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className="whitespace-pre-wrap text-sm">{value}</div>
    </div>
  )
}
