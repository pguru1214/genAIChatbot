import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { readEvents } from './lib/sse'
import { Backdrop } from './components/ui'
import { Sidebar } from './components/Sidebar'
import { ChatView } from './components/ChatView'
import { TripPanel } from './components/TripPanel'
import { QuickPlanModal } from './components/QuickPlanModal'
import { useToast } from './components/Toasts'
import { useConversation } from './hooks/useConversation'
import type { Plan, Trip } from './types'

const narrow = () => typeof window !== 'undefined' && window.innerWidth < 1100

export function App() {
  const toast = useToast()
  const [mode, setMode] = useState('connecting')
  const [trips, setTrips] = useState<Trip[]>([])
  async function refresh() {
    const response = await fetch('/api/trips')
    if (!response.ok) throw new Error('Could not load saved trips')
    setTrips(await response.json())
  }
  useEffect(() => {
    fetch('/api/health').then(r => { if (!r.ok) throw new Error(); return r.json() }).then(d => setMode(d.mode))
      .catch(() => { setMode('offline'); toast({ title: 'Backend is offline', message: 'Start the FastAPI backend on port 8000, then refresh.' }) })
    refresh().catch(() => {})
  }, [])

  const conv = useConversation({ mode, onSaved: () => { void refresh().catch(() => {}) } })

  // Layout state.
  const [sidebarOpen, setSidebarOpen] = useState(() => !narrow())
  const [panelOpen, setPanelOpen] = useState(true)
  const [mobileView, setMobileView] = useState<'chat' | 'plan'>('chat')
  const [unseen, setUnseen] = useState(false)
  const [quickOpen, setQuickOpen] = useState(false)

  // Quick plan form.
  const [destination, setDestination] = useState('Jaipur, Rajasthan, India')
  const [origin, setOrigin] = useState('')
  const [budget, setBudget] = useState('50000')
  const [currency, setCurrency] = useState('INR')
  const [dayStart, setDayStart] = useState('10:00')
  const [dayEnd, setDayEnd] = useState('18:00')
  const [message, setMessage] = useState('Plan a relaxed trip with historical attractions and a packing checklist.')
  const [days, setDays] = useState(3)
  const [date, setDate] = useState('')
  const [quickBusy, setQuickBusy] = useState(false)

  // The panel shows a pinned plan (quick plan or saved trip) or else the active chat's plan.
  const [pinned, setPinned] = useState<Plan | null>(null)
  const chatResult = conv.view?.result
  const chatPlan: Plan | null = chatResult?.answer ? {
    key: 'chat-' + chatResult.trip_id + ':' + chatResult.answer.length, source: 'chat', result: chatResult, answer: chatResult.answer,
    destination: String(conv.view?.details.destination ?? 'Your trip'), days: Number(conv.view?.details.days) || 0,
  } : null
  const plan = pinned ?? chatPlan
  useEffect(() => { if (chatPlan && !quickBusy) setPinned(null) }, [chatPlan?.key])
  useEffect(() => { if (plan && mobileView === 'chat') setUnseen(true) }, [plan?.key])

  function showPlan() { setPanelOpen(true); setMobileView('plan'); setUnseen(false) }
  function closeSidebarIfNarrow() { if (narrow()) setSidebarOpen(false) }

  async function run(intent = 'auto') {
    if (quickBusy) return
    const previous = pinned, source = plan
    const action = intent === 'email' || intent === 'calendar'
    const dest = action && source ? source.destination : destination
    const length = action && source?.days ? source.days : days
    setQuickBusy(true); setQuickOpen(false); showPlan()
    setPinned({ key: 'quick-' + Date.now(), source: 'quick', destination: dest, days: length, answer: '', result: null, streaming: true, status: 'Connecting to agents…' })
    try {
      const response = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        message, destination: dest, origin: origin || null, days: length, start_date: date || null,
        budget, currency, day_start: dayStart, day_end: dayEnd,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, intent,
        trip_id: action ? source?.result?.trip_id : null,
      }) })
      if (!response.ok) throw new Error(response.status === 422 ? 'Check your destination, dates, and message.' : 'The backend could not accept this request.')
      let completed = false
      await readEvents(response, (event, data) => {
        if (event === 'progress') setPinned(p => p && { ...p, status: data.message })
        if (event === 'answer_delta') setPinned(p => p && { ...p, answer: p.answer + data.text })
        if (event === 'completed') { completed = true; setPinned(p => p && { ...p, result: data.result, details: data.result.request, streaming: false }) }
        if (event === 'error') throw new Error(data.message)
      })
      if (!completed) throw new Error('Connection ended before completion. Check saved trips before retrying.')
      await refresh()
    } catch (error) {
      const description = error instanceof Error ? error.message : 'Request failed'
      toast({ title: 'We could not finish your request', message: `${description.replace(/[.!?]?$/, '.')} For location issues, use city, region and country, for example “Jaipur, Rajasthan, India”, or ask the guide in the chat for guided clarification.` })
      setPinned(p => p?.answer ? { ...p, streaming: false } : previous)
    } finally { setQuickBusy(false) }
  }

  return <div className="app" data-sidebar={sidebarOpen ? 'open' : 'closed'} data-panel={panelOpen ? 'open' : 'closed'} data-view={mobileView}>
    <Backdrop />
    <AnimatePresence initial={false}>
      {sidebarOpen && <motion.div key="sidebar" className="sidebar-wrap" initial={{ x: -280, opacity: 0 }} animate={{ x: 0, opacity: 1 }} exit={{ x: -280, opacity: 0 }} transition={{ type: 'spring', stiffness: 300, damping: 34 }}>
        <Sidebar mode={mode} chats={conv.list} activeChat={pinned ? undefined : conv.view?.id} trips={trips} activeTrip={plan?.source === 'saved' ? plan.result?.trip_id : undefined} busy={conv.busy}
          onClose={() => setSidebarOpen(false)}
          onNew={() => { conv.choose(''); setPinned(null); setMobileView('chat'); closeSidebarIfNarrow() }}
          onQuickPlan={() => { setQuickOpen(true); closeSidebarIfNarrow() }}
          onChat={id => { conv.choose(id); setPinned(null); setMobileView('chat'); closeSidebarIfNarrow() }}
          onTrip={trip => { void (async () => {
            try {
              const response = await fetch(`/api/trips/${trip.id}`)
              if (!response.ok) throw new Error('Could not open saved trip')
              const saved = await response.json()
              setPinned({ key: 'saved-' + trip.id, source: 'saved', destination: saved.destination, days: Number(saved.details.days) || 0,
                answer: saved.result.answer, result: saved.result, details: saved.details })
              showPlan(); closeSidebarIfNarrow()
            } catch { toast({ title: 'Could not open saved trip', message: 'Please retry.' }) }
          })() }} />
      </motion.div>}
      {sidebarOpen && <motion.div key="side-scrim" className="side-scrim" onClick={() => setSidebarOpen(false)} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} />}
    </AnimatePresence>

    <div className="workspace">
      <div className="mobile-switch" role="tablist" aria-label="View">
        {(['chat', 'plan'] as const).map(v => <button key={v} role="tab" aria-selected={mobileView === v} onClick={() => v === 'plan' ? showPlan() : setMobileView('chat')}>
          <span>{v === 'chat' ? 'Chat' : 'Trip'}{v === 'plan' && unseen && <i className="dot" />}</span>
        </button>)}
      </div>
      <ChatView conv={conv} mode={mode} sidebarOpen={sidebarOpen} panelOpen={panelOpen} onMenu={() => setSidebarOpen(true)}
        onTogglePanel={() => setPanelOpen(v => !v)} onShowPlan={showPlan} onQuickPlan={() => setQuickOpen(true)} />
      <AnimatePresence initial={false}>
        {panelOpen && <motion.div key="panel" className="panel-wrap" initial={{ opacity: 0, x: 40 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 40 }} transition={{ type: 'spring', stiffness: 280, damping: 32 }}>
          <TripPanel plan={plan} conv={conv} actionBusy={quickBusy} onAction={intent => void run(intent)} onClose={() => { setPanelOpen(false); setMobileView('chat') }} />
        </motion.div>}
      </AnimatePresence>
    </div>

    <QuickPlanModal open={quickOpen} busy={quickBusy} mode={mode} onClose={() => setQuickOpen(false)} onSubmit={() => void run()}
      form={{ destination, setDestination, origin, setOrigin, budget, setBudget, currency, setCurrency,
        dayStart, setDayStart, dayEnd, setDayEnd, message, setMessage, days, setDays, date, setDate }} />
  </div>
}
