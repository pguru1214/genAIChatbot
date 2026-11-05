import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ChevronDown, Plane, Ticket } from 'lucide-react'
import { ease } from './ui'

export type Trip = { id: string; destination: string; answer: string; mode: string }
const preview = 3

export function Sidebar({ trips, busy, activeId, onOpen }: { trips: Trip[]; busy: boolean; activeId?: string; onOpen: (trip: Trip) => void }) {
  const [all, setAll] = useState(false)
  const visible = all ? trips : trips.slice(0, preview)
  return <aside>
    <div className="stars" aria-hidden />
    <motion.a className="brand" href="/" initial={{ opacity: 0, x: -12 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: .6, ease }}>
      <motion.span className="brand-mark" whileHover={{ rotate: -18, scale: 1.08 }}><Plane size={18} /></motion.span>
      TripWeave
    </motion.a>
    <p className="tagline">A little curiosity.<br />A better journey.</p>

    <h2><Ticket size={13} /> Your journeys</h2>
    {trips.length === 0 && <p className="empty">Your saved plans will appear here, stamped and ready to revisit.</p>}
    <nav>
      <AnimatePresence initial={false}>
        {visible.map((trip, i) => <motion.button key={trip.id} layout disabled={busy} className={'trip' + (trip.id === activeId ? ' active' : '')} onClick={() => onOpen(trip)}
          initial={{ opacity: 0, x: -16 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0 }} transition={{ delay: Math.min(i, 8) * .05, duration: .45, ease }}
          whileHover={busy ? undefined : { x: 4 }} whileTap={busy ? undefined : { scale: .98 }}>
          <span className="trip-code">{code(trip.destination)}</span>
          <span className="trip-body"><span className="trip-name">{trip.destination}</span><span className="trip-mode">{trip.mode} plan</span></span>
        </motion.button>)}
      </AnimatePresence>
    </nav>
    {trips.length > preview && <button className="more" onClick={() => setAll(v => !v)} aria-expanded={all}>
      {all ? 'Show less' : `View all ${trips.length} journeys`}
      <motion.span animate={{ rotate: all ? 180 : 0 }} style={{ display: 'inline-flex' }}><ChevronDown size={14} /></motion.span>
    </button>}

    <div className="aside-note">
      <div className="globe" aria-hidden><span /></div>
      Built with Gemini, LangGraph &amp; LangChain.<br />Three specialists. One travel companion.
    </div>
  </aside>
}

/** Airport-style three-letter code for a destination, e.g. "Jaipur, India" → "JAI". */
function code(destination: string) {
  return (destination.replace(/[^a-z]/gi, '').slice(0, 3) || 'TRP').toUpperCase()
}
