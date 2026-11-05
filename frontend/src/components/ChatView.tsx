import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ArrowUp, ChevronDown, Compass, Landmark, Map as MapIcon, Menu, Mountain, PanelRightClose, PanelRightOpen, RotateCcw, Sparkles, UserRound, UtensilsCrossed } from 'lucide-react'
import type { ConversationState } from '../hooks/useConversation'
import { RichText } from './RichText'
import { Notice, ease } from './ui'

const suggestions = [
  { icon: <Landmark size={18} />, title: 'History & food', prompt: 'Plan a three-day Jaipur trip. I enjoy history and local food.' },
  { icon: <Sparkles size={18} />, title: 'Kerala escape', prompt: 'Plan five relaxed days in Kerala with backwaters and local food.' },
  { icon: <Mountain size={18} />, title: 'Temples & heritage', prompt: 'Plan three days in Mysuru, Karnataka for temples and palaces.' },
  { icon: <UtensilsCrossed size={18} />, title: 'Beaches & seafood', prompt: 'Four relaxed days in Goa, India with beaches and seafood.' },
]
const places = ['India', 'Kerala', 'Goa', 'Jaipur', 'Mysuru', 'Hyderabad']

export function ChatView({ conv, mode, sidebarOpen, panelOpen, onMenu, onTogglePanel, onShowPlan, onQuickPlan }: {
  conv: ConversationState; mode: string; sidebarOpen: boolean; panelOpen: boolean
  onMenu: () => void; onTogglePanel: () => void; onShowPlan: () => void; onQuickPlan: () => void
}) {
  const { view, busy, status, outgoing } = conv
  const logRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    const log = logRef.current
    // The welcome screen starts at the top; only follow the conversation once it exists.
    if (log && (view?.messages.length || outgoing)) log.scrollTo({ top: log.scrollHeight, behavior: 'smooth' })
  }, [view?.messages.length, busy, outgoing])
  // Grow the composer with its content, up to a comfortable height.
  useEffect(() => {
    const el = inputRef.current
    if (el) { el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, 200) + 'px' }
  }, [conv.message])

  const title = conv.list.find(c => c.id === view?.id)?.title || (view ? 'Trip conversation' : 'New trip')
  const empty = !view?.messages.length && !outgoing
  const planAnswer = view?.result?.answer

  return <section className="chat" aria-label="Trip conversation">
    <header className="pane-head">
      {!sidebarOpen && <button className="icon-btn" aria-label="Show sidebar" onClick={onMenu}><Menu size={18} /></button>}
      <div className="pane-title">
        <strong>{title}</strong>
        <span className={busy ? 'live' : ''}>{busy ? status : view?.pending ? 'Waiting for your answer' : 'TripWeave guide'}</span>
      </div>
      <button className="ghost-btn panel-toggle" onClick={onTogglePanel} aria-pressed={panelOpen}>
        {panelOpen ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}<span>{panelOpen ? 'Hide trip' : 'Show trip'}</span>
      </button>
    </header>

    <div className="chat-log" ref={logRef} role="log" aria-label="Trip messages" aria-live="polite">
      <div className="chat-column">
        {empty ? <Welcome busy={busy} onPick={prompt => { conv.setMessage(prompt); inputRef.current?.focus() }} onQuickPlan={onQuickPlan} /> : <>
          <AnimatePresence initial={false}>
            {view?.messages.map((entry, index) => entry.role === 'assistant' && entry.content === planAnswer
              ? <PlanReady key={index} text={entry.content} onOpen={onShowPlan} />
              : <Message key={index} role={entry.role} content={entry.content} />)}
            {outgoing && <Message key={view?.messages.length ?? 0} role="user" content={outgoing} />}
            {busy && <motion.div key="typing" className="msg assistant" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
              <span className="avatar guide"><Compass size={15} /></span>
              <div className="typing"><span className="dots"><span /><span /><span /></span>
                <AnimatePresence mode="wait"><motion.em key={status} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}>{status}</motion.em></AnimatePresence></div>
            </motion.div>}
          </AnimatePresence>
        </>}
      </div>
    </div>

    <form className="composer" onSubmit={e => { e.preventDefault(); void conv.send() }}>
      <div className="chat-column">
        <AnimatePresence>
          {view?.pending && <motion.div className="pending" role="status" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
            <span className="pending-tag">Question for you</span>
            <p>{view.pending.question}</p>
            {!!view.pending.choices?.length && <div className="chips" aria-label="Choose your destination">{view.pending.choices.map(choice =>
              <button key={choice} type="button" className="chip" disabled={busy} onClick={() => void conv.send(choice, { destination: choice })}>{choice}</button>)}</div>}
            {['budget', 'currency', 'interests', 'companions'].includes(view.pending.field) && conv.details.destination && conv.details.start_date && conv.details.days &&
              <div className="chips"><button type="button" className="chip accent" disabled={busy} onClick={() => void conv.send('Build my plan using flexible preferences for any missing optional details.', {
                budget: conv.details.budget || 'flexible', currency: conv.details.currency || 'not specified', interests: conv.details.interests || 'general sightseeing', companions: conv.details.companions || 'not specified',
              })}><Sparkles size={14} /> Build my plan with flexible preferences</button></div>}
          </motion.div>}
        </AnimatePresence>
        <div className="composer-box">
          <label htmlFor="chat-message" className="sr-only">{view?.pending ? 'Your answer' : view?.recoverable ? 'Correct the trip details, or retry the saved turn' : 'Tell me about your trip'}</label>
          <textarea id="chat-message" ref={inputRef} rows={1} disabled={busy} maxLength={4000} value={conv.message} onChange={e => conv.setMessage(e.target.value)}
            placeholder={view?.pending ? 'Type your answer…' : 'Where would you like to go? Tell me dates, days and what you enjoy…'}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void conv.send() } }} />
          <motion.button className="send" disabled={!conv.canSend} aria-label={view?.recoverable ? 'Retry saved turn' : 'Send message'} whileHover={conv.canSend ? { scale: 1.06 } : undefined} whileTap={conv.canSend ? { scale: .92 } : undefined}>
            {busy ? <span className="spinner" /> : view?.recoverable && !conv.message.trim() ? <RotateCcw size={18} /> : <ArrowUp size={19} />}
          </motion.button>
        </div>
        <p className="composer-hint">Enter to send · Shift+Enter for a new line{conv.hasEdits && ' · Edited trip details will be sent with your next message'}</p>
        {mode === 'demo' && <Notice>Demo mode uses sample travel content and a limited parser. Use the Trip details tab to test the full flow without Gemini.</Notice>}
      </div>
    </form>
  </section>
}

function Welcome({ busy, onPick, onQuickPlan }: { busy: boolean; onPick: (prompt: string) => void; onQuickPlan: () => void }) {
  const [index, setIndex] = useState(0)
  useEffect(() => { const t = setInterval(() => setIndex(i => (i + 1) % places.length), 2600); return () => clearInterval(t) }, [])
  return <motion.div className="welcome" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .6, ease }}>
    <motion.span className="welcome-mark" animate={{ rotate: [0, 14, -10, 0] }} transition={{ duration: 6, repeat: Infinity, ease: 'easeInOut' }}><Compass size={26} /></motion.span>
    <h1>Less planning.<br />More <span className="rotator"><AnimatePresence mode="wait">
      <motion.em key={places[index]} initial={{ y: '60%', opacity: 0, filter: 'blur(6px)' }} animate={{ y: 0, opacity: 1, filter: 'blur(0px)' }} exit={{ y: '-60%', opacity: 0, filter: 'blur(6px)' }} transition={{ duration: .5, ease }}>{places[index]}.</motion.em>
    </AnimatePresence></span></h1>
    <p>Explore India, one journey at a time. Choose a state, district or city. I will research tourism sources and build a day-by-day itinerary with a packing list.</p>
    <div className="starters">{suggestions.map((s, i) =>
      <motion.button key={s.title} type="button" className="starter" disabled={busy} onClick={() => onPick(s.prompt)}
        initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: .15 + i * .07, duration: .45, ease }} whileHover={{ y: -3 }} whileTap={{ scale: .98 }}>
        <span className="starter-icon">{s.icon}</span><strong>{s.title}</strong><span>{s.prompt}</span>
      </motion.button>)}</div>
    <button type="button" className="text-btn" onClick={onQuickPlan}>Prefer a form? Use quick plan →</button>
  </motion.div>
}

function Message({ role, content }: { role: string; content: string }) {
  const user = role === 'user'
  const long = !user && content.length > 900
  const [expanded, setExpanded] = useState(false)
  return <motion.div className={'msg ' + (user ? 'user' : 'assistant')} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .4, ease }}>
    <span className={'avatar ' + (user ? 'me' : 'guide')}>{user ? <UserRound size={15} /> : <Compass size={15} />}</span>
    <div className="msg-body">
      {user ? <p>{content}</p> : <div className={long && !expanded ? 'clamped' : ''}><RichText text={content} /></div>}
      {long && <button className="text-btn" onClick={() => setExpanded(v => !v)}>{expanded ? 'Show less' : 'Show more'} <ChevronDown size={14} style={{ rotate: expanded ? '180deg' : '0deg' }} /></button>}
    </div>
  </motion.div>
}

/** The finished itinerary lives in the trip panel; the chat shows a compact card pointing to it. */
function PlanReady({ text, onOpen }: { text: string; onOpen: () => void }) {
  const preview = text.replace(/\s+/g, ' ').slice(0, 180)
  return <motion.div className="msg assistant" initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .4, ease }}>
    <span className="avatar guide"><Compass size={15} /></span>
    <div className="plan-ready">
      <span className="plan-ready-icon"><MapIcon size={20} /></span>
      <div><strong>Your itinerary is ready</strong><p>{preview}{text.length > 180 && '…'}</p></div>
      <motion.button type="button" className="primary small" onClick={onOpen} whileHover={{ scale: 1.03 }} whileTap={{ scale: .97 }}>Open itinerary</motion.button>
    </div>
  </motion.div>
}
