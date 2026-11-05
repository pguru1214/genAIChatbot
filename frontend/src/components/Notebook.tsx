import { motion } from 'motion/react'
import { CalendarPlus, Mail, Sparkles } from 'lucide-react'
import { Notice, Sources, ease, type Evidence } from './ui'

export type Result = { answer: string; agent_trace: string[]; trip_id: string; research?: { evidence: Evidence[]; errors: string[] }; action?: { kind: string }; proposal_id?: string }

/** The itinerary canvas: streams the current plan. */
export function Notebook({ destination, days, answer, result, busy, run }: { destination: string; days: number; answer: string; result: Result | null; busy: boolean; run: (intent: string) => void }) {
  if (!answer) return null

  return <motion.section key={result?.trip_id ?? 'streaming'} className="card answer" initial={{ opacity: 0, y: 24, scale: .985 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ duration: .6, ease }}>
    <div className="ticket-head">
      <div><span className="eyebrow">Your travel notebook</span><h3>{destination}</h3></div>
      {days > 0 && <span className="stamp"><Sparkles size={14} /> {days} {days === 1 ? 'day' : 'days'}</span>}
    </div>
    <div className="answer-text">{answer}{busy && <span className="caret" />}</div>
    {result && <>
      {result.agent_trace?.length > 0 && <div className="agents">{result.agent_trace.map((name, i) =>
        <motion.span key={name} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: .1 + i * .08 }}>{name}</motion.span>)}</div>}
      {result.research?.errors.map(error => <Notice key={error}>{error}</Notice>)}
      <Sources evidence={result.research?.evidence} />
      {!result.action && <div className="actions">
        <motion.button disabled={busy} onClick={() => run('email')} whileHover={{ y: -2 }} whileTap={{ scale: .97 }}><Mail size={15} /> Preview email</motion.button>
        <motion.button disabled={busy} onClick={() => run('calendar')} whileHover={{ y: -2 }} whileTap={{ scale: .97 }}><CalendarPlus size={15} /> Preview calendar export</motion.button>
      </div>}
      {result.action && <Notice>Preview only. Google OAuth and execution are not connected. No email or calendar event was created.</Notice>}
    </>}
  </motion.section>
}
