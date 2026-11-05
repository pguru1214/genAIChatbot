import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ChevronDown, MessageSquareText, PanelLeftClose, Plane, Plus, SlidersHorizontal, Ticket } from 'lucide-react'
import type { ConversationSummary, Trip } from '../types'
import { ease } from './ui'

const preview = 3

export function Sidebar({ mode, chats, activeChat, trips, activeTrip, busy, onNew, onQuickPlan, onChat, onTrip, onClose }: {
  mode: string; chats: ConversationSummary[]; activeChat?: string; trips: Trip[]; activeTrip?: string; busy: boolean
  onNew: () => void; onQuickPlan: () => void; onChat: (id: string) => void; onTrip: (trip: Trip) => void; onClose: () => void
}) {
  return <aside className="sidebar">
    <div className="stars" aria-hidden />
    <div className="side-top">
      <a className="brand" href="/">
        <motion.span className="brand-mark" whileHover={{ rotate: -18, scale: 1.08 }}><Plane size={17} /></motion.span>TripWeave
      </a>
      <button className="side-icon" aria-label="Hide sidebar" onClick={onClose}><PanelLeftClose size={18} /></button>
    </div>

    <motion.button className="new-trip" onClick={onNew} disabled={busy} whileHover={{ y: -1 }} whileTap={{ scale: .98 }}><Plus size={17} /> New trip</motion.button>
    <button className="side-link" onClick={onQuickPlan}><SlidersHorizontal size={15} /> Quick plan with a form</button>

    <div className="side-scroll">
      <Section title="Recent chats" icon={<MessageSquareText size={13} />} empty="Your conversations will appear here." count={chats.length}>
        {limit => chats.slice(0, limit).map((chat, i) => <Row key={chat.id} i={i} active={chat.id === activeChat} disabled={busy} onClick={() => onChat(chat.id)}>
          <span className="row-title">{chat.title || 'Untitled trip'}</span>
        </Row>)}
      </Section>
      <Section title="Saved itineraries" icon={<Ticket size={13} />} empty="Finished plans are stamped and kept here." count={trips.length}>
        {limit => trips.slice(0, limit).map((trip, i) => <Row key={trip.id} i={i} active={trip.id === activeTrip} disabled={busy} onClick={() => onTrip(trip)}>
          <span className="trip-code">{code(trip.destination)}</span>
          <span className="row-body"><span className="row-title">{trip.destination}</span><span className="row-sub">{trip.mode} plan</span></span>
        </Row>)}
      </Section>
    </div>

    <div className="side-foot">
      <span className={'badge ' + mode}><span className="pulse" />{mode} mode</span>
      <p>Gemini · LangGraph · LangChain<br />Your travel companion for India.</p>
    </div>
  </aside>
}

function Section({ title, icon, empty, count, children }: { title: string; icon: React.ReactNode; empty: string; count: number; children: (limit: number) => React.ReactNode }) {
  const [all, setAll] = useState(false)
  return <section className="side-section">
    <h2>{icon}{title}</h2>
    {count === 0 ? <p className="side-empty">{empty}</p> : <nav><AnimatePresence initial={false}>{children(all ? count : preview)}</AnimatePresence></nav>}
    {count > preview && <button className="more" onClick={() => setAll(v => !v)} aria-expanded={all}>
      {all ? 'Show less' : `View all ${count}`}
      <motion.span animate={{ rotate: all ? 180 : 0 }} style={{ display: 'inline-flex' }}><ChevronDown size={14} /></motion.span>
    </button>}
  </section>
}

function Row({ i, active, disabled, onClick, children }: { i: number; active: boolean; disabled: boolean; onClick: () => void; children: React.ReactNode }) {
  return <motion.button layout className={'side-row' + (active ? ' active' : '')} disabled={disabled} onClick={onClick} aria-current={active || undefined}
    initial={{ opacity: 0, x: -12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0 }} transition={{ delay: Math.min(i, 6) * .04, duration: .4, ease }}>
    {children}
  </motion.button>
}

/** Airport-style three-letter code for a destination, e.g. "Jaipur, India" → "JAI". */
function code(destination: string) {
  return (destination.replace(/[^a-z]/gi, '').slice(0, 3) || 'TRP').toUpperCase()
}
