import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Compass, MessageCircle } from 'lucide-react'
import { readEvents } from './lib/sse'
import { Backdrop, ease } from './components/ui'
import { Hero } from './components/Hero'
import { Sidebar, type Trip } from './components/Sidebar'
import { QuickPlanner, type Planner } from './components/QuickPlanner'
import { Notebook, type Result } from './components/Notebook'
import { ConversationPanel, type Details } from './components/ConversationPanel'
import { TripDetails } from './components/TripDetails'
import { useToast } from './components/Toasts'

const wide = () => typeof window !== 'undefined' && window.innerWidth >= 1200

export function App() {
  const [destination, setDestination] = useState('Jaipur, Rajasthan, India')
  const [message, setMessage] = useState('Plan a relaxed trip with historical attractions and a packing checklist.')
  const [days, setDays] = useState(3)
  const [date, setDate] = useState('')
  const [mode, setMode] = useState('connecting')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('Ready for your next adventure')
  const [answer, setAnswer] = useState('')
  const [result, setResult] = useState<Result | null>(null)
  const [trips, setTrips] = useState<Trip[]>([])
  const [failure, setFailure] = useState('')
  const [chatOpen, setChatOpen] = useState(wide)
  const [chatBusy, setChatBusy] = useState(false)
  // Accordion: only one of the canvas panels is open at a time.
  const [panel, setPanel] = useState<'details' | 'planner' | null>('details')
  const toast = useToast()
  const [planDays, setPlanDays] = useState(0)
  const [details, setDetails] = useState<Details>({})
  const busyRef = useRef(false)
  busyRef.current = busy
  const canvasRef = useRef<HTMLDivElement>(null)

  async function refresh() {
    const response = await fetch('/api/trips')
    if (!response.ok) throw new Error('Could not load saved trips')
    setTrips(await response.json())
  }
  useEffect(() => {
    fetch('/api/health').then(r => { if (!r.ok) throw new Error(); return r.json() }).then(d => setMode(d.mode)).catch(() => { setMode('offline'); setStatus('Start the FastAPI backend on port 8000'); toast({ title: 'Backend is offline', message: 'Start the FastAPI backend on port 8000, then refresh.' }) })
    refresh().catch(() => {})
  }, [])

  async function run(intent = 'auto') {
    if (busy) return
    const saved = result
    setFailure('')
    setBusy(true); setAnswer(''); setResult(null); setPlanDays(days); setStatus('Connecting to agents…')
    try {
      const response = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        message, destination, days, start_date: date || null,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, intent,
        trip_id: ['email', 'calendar'].includes(intent) ? saved?.trip_id : null,
      }) })
      if (!response.ok) throw new Error(response.status === 422 ? 'Check your destination, dates, and message.' : 'The backend could not accept this request.')
      let completed = false
      await readEvents(response, (event, data) => {
        if (event === 'progress') setStatus(data.message)
        if (event === 'answer_delta') setAnswer(previous => previous + data.text)
        if (event === 'completed') { completed = true; setResult(data.result); setStatus('Plan saved · Workflow complete') }
        if (event === 'error') throw new Error(data.message)
      })
      if (!completed) throw new Error('Connection ended before completion. Check saved trips before retrying.')
      await refresh()
    } catch (error) {
      const description = error instanceof Error ? error.message : 'Request failed'
      setStatus('Your request needs attention'); setFailure(description)
      toast({ title: 'We could not finish your request', message: `${description.replace(/[.!?]?$/, ".")} For location issues, use city, region and country, for example “Jaipur, Rajasthan, India”, or ask the guide in the chat for guided clarification.` })
    }
    finally { setBusy(false) }
  }

  function show(next: { destination: string; days?: number; answer: string; result: Result }) {
    setDestination(next.destination); if (next.days) setDays(next.days)
    setPlanDays(next.days ?? 0)
    setAnswer(next.answer); setResult(next.result); setFailure('')
    const top = canvasRef.current?.getBoundingClientRect().top ?? 0
    if (top < 0 || top > window.innerHeight * .6) canvasRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
  function openTrip(trip: Trip) {
    show({ destination: trip.destination, answer: trip.answer, result: { ...trip, trip_id: trip.id, agent_trace: [] } })
    setStatus(`Saved ${trip.mode} plan`)
  }

  const planner: Planner = { destination, setDestination, message, setMessage, days, setDays, date, setDate, busy, status, failure, run }

  return <div className={'layout' + (chatOpen ? ' chat-open' : '')}>
    <Backdrop />
    <Sidebar trips={trips} busy={busy} activeId={result?.trip_id} onOpen={openTrip} />
    <main>
      <Hero mode={mode} />
      <div ref={canvasRef} className="canvas">
        <Notebook destination={destination} days={planDays} answer={answer} result={result} busy={busy} run={intent => void run(intent)} />
        <TripDetails details={details} setDetails={setDetails} busy={chatBusy} mode={mode} open={panel === 'details'} onToggle={() => setPanel(p => p === 'details' ? null : 'details')} />
        <QuickPlanner p={planner} mode={mode} open={panel === 'planner'} onToggle={() => setPanel(p => p === 'planner' ? null : 'planner')} />
      </div>
      <footer>Local development starter · Verify travel details before departure · Not for public deployment</footer>
    </main>

    {/* The chat stays mounted while minimized so an in-flight turn keeps streaming. */}
    <motion.div className="chat-dock" inert={!chatOpen} aria-hidden={!chatOpen}
      initial={false} animate={chatOpen ? { x: 0, opacity: 1, scale: 1 } : { x: 40, opacity: 0, scale: .96 }}
      transition={{ type: 'spring', stiffness: 260, damping: 30 }} style={{ pointerEvents: chatOpen ? 'auto' : 'none' }}>
      <ConversationPanel mode={mode} details={details} setDetails={setDetails} onSaved={() => { void refresh().catch(() => {}) }} onBusy={setChatBusy} onClose={() => setChatOpen(false)}
        onResult={(details, plan) => { if (!busyRef.current) show({ destination: String(details.destination ?? plan.trip_id), days: Number(details.days) || undefined, answer: plan.answer, result: plan }) }} />
    </motion.div>
    <AnimatePresence>
      {chatOpen && <motion.div key="scrim" className="scrim" onClick={() => setChatOpen(false)} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} />}
    </AnimatePresence>

    <AnimatePresence>
      {!chatOpen && <motion.button key="launcher" className="launcher" onClick={() => setChatOpen(true)} aria-label="Open trip chat"
        initial={{ opacity: 0, scale: .6, y: 20 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: .6, y: 20 }} transition={{ duration: .35, ease }}
        whileHover={{ scale: 1.05 }} whileTap={{ scale: .95 }}>
        <span className="launcher-icon">{chatBusy ? <motion.span animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 2, ease: 'linear' }} style={{ display: 'inline-flex' }}><Compass size={22} /></motion.span> : <MessageCircle size={22} />}</span>
        <span className="launcher-text">{chatBusy ? 'Guide is working…' : 'Plan with the guide'}</span>
      </motion.button>}
    </AnimatePresence>
  </div>
}
