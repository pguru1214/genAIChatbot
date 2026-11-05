import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ArrowUp, ChevronDown, Compass, Minus, RotateCcw, UserRound } from 'lucide-react'
import { readEvents } from '../lib/sse'
import { Notice, ease } from './ui'
import { useToast } from './Toasts'
import type { Result } from './Notebook'

export type Details = Record<string, string | number>
type View = { id: string; details: Details; messages: { role: string; content: string }[]; pending: { field: string; question: string; choices?: string[] } | null; checkpoint_id: string | null; recoverable: boolean; result?: Result | null }
const storageKey = 'tripweave-conversation'
const suggestions = [
  'Plan a three-day Jaipur trip. I enjoy history and local food.',
  'A slow, romantic long weekend in Lisbon with great viewpoints.',
  'Five days in Kyoto for temples, gardens and tea houses.',
]

export function ConversationPanel({ mode, details, setDetails, onSaved, onResult, onBusy, onClose }: { mode: string; details: Details; setDetails: (details: Details) => void; onSaved: () => void; onResult: (details: Details, result: Result) => void; onBusy: (busy: boolean) => void; onClose: () => void }) {
  const [view, setView] = useState<View | null>(null)
  const [list, setList] = useState<{ id: string; title: string }[]>([])
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(true)
  const [status, setStatus] = useState('Loading your conversation…')
  const [failed, setFailed] = useState(false)
  // The traveller's message, shown immediately until the server echoes the conversation back.
  const [outgoing, setOutgoing] = useState('')
  const toast = useToast()
  useEffect(() => { if (failed) toast({ title: 'The guide hit a snag', message: status }) }, [failed, status])
  const logRef = useRef<HTMLDivElement>(null)
  const shown = useRef<string | undefined>(undefined)
  useEffect(() => { onBusy(busy) }, [busy])

  function apply(data: View) {
    setView(data); setDetails(data.details)
    // Surface a finished plan on the itinerary canvas once per trip.
    const resultKey = data.result?.answer ? data.result.trip_id + ':' + data.result.answer : undefined
    if (data.result?.answer && resultKey !== shown.current) { shown.current = resultKey; onResult(data.details, data.result) }
    try { localStorage.setItem(storageKey, data.id) } catch { /* Server history remains available. */ }
  }
  async function refreshList() {
    const response = await fetch('/api/conversations')
    if (!response.ok) throw new Error('Could not load conversations. Check that the backend is running.')
    const data: { id: string; title: string }[] = await response.json()
    setList(data); return data
  }
  async function open(id: string) {
    const response = await fetch(`/api/conversations/${id}`)
    if (!response.ok) throw new Error('Could not reopen this conversation.')
    const data: View = await response.json()
    apply(data); return data
  }
  useEffect(() => {
    let active = true
    void (async () => {
      try {
        const conversations = await refreshList()
        let saved: string | null = null
        try { saved = localStorage.getItem(storageKey) } catch { /* Optional convenience. */ }
        const restored = active && saved && conversations.some(c => c.id === saved) ? await open(saved) : null
        if (active) setStatus(restored?.pending ? 'Your trip is waiting for clarification. Answer the question below.' : 'Tell me about your trip, or continue where you left off.')
      } catch (error) { if (active) { setFailed(true); setStatus(String(error)) } }
      finally { if (active) setBusy(false) }
    })()
    return () => { active = false }
  }, [])
  useEffect(() => {
    const log = logRef.current
    if (log) log.scrollTo({ top: log.scrollHeight, behavior: 'smooth' })
  }, [view?.messages.length, busy, outgoing])

  const hasEdits = Object.entries(details).some(([key, value]) => value !== '' && value !== view?.details[key])
  async function send(reply?: string, chosenDetails: Details = {}) {
    const submitted = reply ?? message.trim()
    if (busy || (!submitted && !view?.recoverable && !hasEdits)) return
    setBusy(true); setFailed(false); setStatus('Checking your trip details…'); setOutgoing(submitted || (hasEdits ? 'Apply trip details' : 'Retry saved turn'))
    let current = view
    try {
      if (!current) {
        const response = await fetch('/api/conversations', { method: 'POST' })
        if (!response.ok) throw new Error('Could not start a conversation')
        const { id } = await response.json()
        current = { id, details: {}, messages: [], pending: null, checkpoint_id: null, recoverable: false }
        apply(current)
      }
      const response = await fetch(`/api/conversations/${current.id}/messages`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
          message: submitted || (hasEdits ? 'Apply trip details' : 'Retry saved turn'), checkpoint_id: current.checkpoint_id,
          details: { ...Object.fromEntries(Object.entries(details).filter(([key, value]) => value !== '' && value !== current!.details[key])), ...chosenDetails },
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        }),
      })
      if (!response.ok) throw new Error(response.status === 409 ? 'Conversation changed or is busy. Reopen it before sending again.' : response.status === 422 ? 'Check the details: valid dates, an IANA time zone, and 1–7 days are required.' : 'Could not accept this message.')
      setMessage('')
      let complete = false
      await readEvents(response, (event, data) => {
        if (event === 'progress') setStatus(data.message)
        if (event === 'conversation') { apply(data.conversation); setOutgoing('') }
        if (event === 'completed') complete = true
        if (event === 'error') throw new Error(data.message)
      })
      if (!complete) throw new Error('Connection interrupted. Reopen to check your saved progress.')
      setMessage(''); setStatus('Progress saved. You can continue after refreshing.')
      await refreshList(); onSaved()
    } catch (error) {
      setFailed(true); setStatus(error instanceof Error ? error.message : 'Unable to complete this turn')
      if (current) {
        try {
          const restored = await open(current.id)
          // A dropped stream can arrive after the graph has already persisted a
          // new question. Show that durable question instead of an obsolete error.
          if (restored.pending && restored.checkpoint_id !== current.checkpoint_id) {
            setFailed(false); setStatus('Your progress was restored. Please answer the clarification question.')
          } else if (restored.result && !restored.recoverable && restored.checkpoint_id !== current.checkpoint_id) {
            setFailed(false); setStatus('Your completed plan was restored from the saved conversation.')
            onSaved()
          }
          await refreshList()
        } catch { /* Keep the actionable error when restoration is unavailable. */ }
      }
    } finally { setBusy(false); setOutgoing('') }
  }

  function choose(id: string) {
    setMessage(''); setFailed(false)
    if (!id) { setView(null); setDetails({}); setStatus('Ready for a new journey.'); try { localStorage.removeItem(storageKey) } catch { /* Optional. */ } }
    else { setBusy(true); void open(id).then(() => setStatus('Conversation restored.')).catch(error => { setFailed(true); setStatus(String(error)) }).finally(() => setBusy(false)) }
  }

  const empty = !view?.messages.length
  const canSend = !busy && mode !== 'offline' && (!!message.trim() || !!view?.recoverable || hasEdits)

  return <section className="guided" aria-label="Guided trip conversation">
    <div className="chat-top">
      <div className="chat-title"><span className="avatar guide"><Compass size={17} /></span><strong>TripWeave guide</strong></div>
      <label className="select-wrap"><span className="sr-only">Continue a conversation</span>
        <select disabled={busy} value={view?.id || ''} onChange={e => choose(e.target.value)}>
          <option value="">✦ New journey</option>{list.map(c => <option key={c.id} value={c.id}>{c.title} · {c.id.slice(0, 6)}</option>)}
        </select><ChevronDown size={15} />
      </label>
      <motion.button type="button" className="icon-btn" aria-label="Minimize chat" onClick={onClose} whileHover={{ scale: 1.08 }} whileTap={{ scale: .92 }}><Minus size={17} /></motion.button>
    </div>

    <div className="chat-history" ref={logRef} role="log" aria-label="Trip messages" aria-live="polite">
      {empty && <Bubble role="assistant" content="Tell me about your next trip. I will ask for anything missing before creating your itinerary and packing list." />}
      <AnimatePresence initial={false}>
        {view?.messages.map((entry, index) => <Bubble key={index} role={entry.role} content={entry.content} />)}
        {outgoing && <Bubble key={view?.messages.length ?? 0} role="user" content={outgoing} />}
        {busy && view && <motion.div key="typing" className="chat-row assistant" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
          <span className="avatar guide"><Compass size={15} /></span>
          <div className="bubble typing"><span className="dots"><span /><span /><span /></span><AnimatePresence mode="wait"><motion.em key={status} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}>{status}</motion.em></AnimatePresence></div>
        </motion.div>}
      </AnimatePresence>
      {empty && !busy && <div className="suggestions">
        {suggestions.map((s, i) => <motion.button type="button" key={s} className="chip" onClick={() => setMessage(s)} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: .2 + i * .08 }} whileHover={{ y: -2 }} whileTap={{ scale: .97 }}>{s}</motion.button>)}
      </div>}
    </div>


    <form className="composer" onSubmit={e => { e.preventDefault(); void send() }}>
      {view?.pending && <div className="notice" role="status"><strong>Waiting for your answer</strong><p>{view.pending.question}</p></div>}
      {!!view?.pending?.choices?.length && <div className="suggestions" aria-label="Choose your destination">{view.pending.choices.map(choice => <button key={choice} type="button" className="chip" disabled={busy} onClick={() => void send(choice, { destination: choice })}>{choice}</button>)}</div>}
      {view?.pending && ['budget', 'currency', 'interests', 'companions'].includes(view.pending.field) && details.destination && details.start_date && details.days && <div className="suggestions"><button type="button" className="chip" disabled={busy} onClick={() => void send('Build my plan using flexible preferences for any missing optional details.', {
        budget: details.budget || 'flexible', currency: details.currency || 'not specified', interests: details.interests || 'general sightseeing', companions: details.companions || 'not specified',
      })}>Build my plan with flexible preferences</button></div>}
      <label htmlFor="chat-message" className="composer-label">{view?.pending ? 'Your answer' : view?.recoverable ? 'Correct the trip details, or retry the saved turn' : 'Tell me about your trip'}</label>
      <div className="composer-box">
        <textarea id="chat-message" disabled={busy} maxLength={4000} value={message} onChange={e => setMessage(e.target.value)} placeholder="Plan a three-day Jaipur trip. I enjoy history and local food."
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send() } }} />
        <motion.button className="send" disabled={!canSend} aria-label={view?.recoverable ? 'Retry saved turn' : 'Send message'} whileHover={canSend ? { scale: 1.08 } : undefined} whileTap={canSend ? { scale: .92 } : undefined}>
          {busy ? <span className="spinner" /> : view?.recoverable && !message.trim() ? <RotateCcw size={18} /> : <ArrowUp size={19} />}
        </motion.button>
      </div>
      <span className="hint composer-hint">Enter to send · Shift+Enter for a new line</span>
    </form>
    {mode === 'demo' && <Notice>Demo mode uses sample travel content and a limited parser. Use the trip details card to test the full flow without Gemini.</Notice>}
  </section>
}

function Bubble({ role, content }: { role: string; content: string }) {
  const user = role === 'user'
  return <motion.div className={'chat-row ' + (user ? 'user' : 'assistant')}
    initial={{ opacity: 0, y: 14, scale: .97 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ duration: .45, ease }}>
    <span className={'avatar ' + (user ? 'me' : 'guide')}>{user ? <UserRound size={15} /> : <Compass size={15} />}</span>
    <div className="bubble"><strong>{user ? 'You' : 'TripWeave'}</strong><p>{content}</p></div>
  </motion.div>
}
