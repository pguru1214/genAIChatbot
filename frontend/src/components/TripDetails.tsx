import { AnimatePresence, motion } from 'motion/react'
import { CalendarDays, ChevronDown, Clock, Coins, Heart, MapPin, Timer, Users, Wallet } from 'lucide-react'
import type { ReactNode } from 'react'
import type { Details } from './ConversationPanel'
import { ease } from './ui'

const fields: { key: string; label: string; icon: ReactNode; wide?: boolean }[] = [
  { key: 'destination', label: 'Destination', icon: <MapPin size={15} />, wide: true },
  { key: 'start_date', label: 'Departure date', icon: <CalendarDays size={15} /> },
  { key: 'days', label: 'Days (1–7)', icon: <Timer size={15} /> },
  { key: 'budget', label: 'Total budget (or flexible)', icon: <Wallet size={15} /> },
  { key: 'currency', label: 'Currency', icon: <Coins size={15} /> },
  { key: 'interests', label: 'Interests', icon: <Heart size={15} />, wide: true },
  { key: 'companions', label: 'Travelling with', icon: <Users size={15} /> },
  { key: 'timezone', label: 'Trip time zone', icon: <Clock size={15} /> },
]

/** What the guide knows about the chat trip; edits are sent with the next chat message. */
export function TripDetails({ details, setDetails, busy, mode, open, onToggle }: { details: Details; setDetails: (d: Details) => void; busy: boolean; mode: string; open: boolean; onToggle: () => void }) {
  const known = fields.filter(f => details[f.key] !== undefined && details[f.key] !== '').length
  return <motion.section className="card details-card" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .6, ease }}>
    <button type="button" className="details-head" aria-expanded={open} onClick={onToggle}>
      <span>
        <span className="eyebrow">Review or edit trip details {mode === 'demo' && '· recommended in demo mode'}</span>
        <span className="details-title">Your trip at a glance</span>
      </span>
      <span className="details-meta"><span className="progress" aria-label={`${known} of ${fields.length} details known`}>
        <svg viewBox="0 0 36 36"><circle cx="18" cy="18" r="15" className="track" />
          <motion.circle cx="18" cy="18" r="15" className="fill" initial={false} animate={{ pathLength: known / fields.length }} transition={{ duration: .8, ease }} /></svg>
        <span>{known}/{fields.length}</span>
      </span>
      <motion.span animate={{ rotate: open ? 180 : 0 }} className="toggle-icon"><ChevronDown size={18} /></motion.span></span>
    </button>
    <AnimatePresence initial={false}>
    {open && <motion.div key="body" className="details-body" initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: .45, ease }}>
    <p className="muted">Filled in as you chat. Edits override your message and go with your next chat message. For a new destination, start a new journey.</p>
    <div className="details-grid">
      {fields.map(({ key, label, icon, wide }) => <label className={'field' + (wide ? ' wide' : '')} key={key}>{label}
        <span className="input-wrap">{icon}<input disabled={busy} type={key === 'days' ? 'number' : key === 'start_date' ? 'date' : 'text'} min={key === 'days' ? 1 : undefined} max={key === 'days' ? 7 : undefined} maxLength={key === 'interests' ? 500 : 200}
          value={details[key] ?? ''} onChange={e => setDetails({ ...details, [key]: key === 'days' && e.target.value ? Number(e.target.value) : e.target.value })} /></span>
      </label>)}
    </div>
    </motion.div>}
    </AnimatePresence>
  </motion.section>
}
