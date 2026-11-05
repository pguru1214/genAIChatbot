import { AnimatePresence, motion } from 'motion/react'
import { ArrowUpRight, CalendarDays, ChevronDown, MapPin, Minus, Plus, SlidersHorizontal } from 'lucide-react'
import { Notice, Status, ease } from './ui'

export type Planner = {
  destination: string; setDestination: (v: string) => void
  message: string; setMessage: (v: string) => void
  days: number; setDays: (v: number) => void
  date: string; setDate: (v: string) => void
  busy: boolean; status: string; failure: string
  run: (intent?: string) => Promise<void>
}

const inspirations = ['Jaipur, Rajasthan, India', 'Kyoto, Japan', 'Lisbon, Portugal', 'Cape Town, South Africa', 'Queenstown, New Zealand']

export function QuickPlanner({ p, mode, open, onToggle }: { p: Planner; mode: string; open: boolean; onToggle: () => void }) {
  return <div className="planner">
    <motion.div className="card form-card" layout initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .6, ease }}>
      <button type="button" className="form-heading" aria-expanded={open} onClick={onToggle}>
        <span className="form-title"><span className="form-icon"><SlidersHorizontal size={16} /></span><span><span className="form-name">Quick planner</span><small>Prefer a form? Fill in the details and we take it from here.</small></span></span>
        <motion.span animate={{ rotate: open ? 180 : 0 }} className="toggle-icon"><ChevronDown size={18} /></motion.span>
      </button>
      <AnimatePresence initial={false}>
        {open && <motion.form key="form" onSubmit={e => { e.preventDefault(); void p.run() }} initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: .45, ease }} className="form-body">
          <div className="fields">
            <label className="field">Where to?
              <span className="input-wrap"><MapPin size={16} /><input required maxLength={200} value={p.destination} onChange={e => p.setDestination(e.target.value)} /></span>
            </label>
            <label className="field">Departure
              <span className="input-wrap"><CalendarDays size={16} /><input type="date" value={p.date} onChange={e => p.setDate(e.target.value)} /></span>
            </label>
            <label className="field">Days
              <span className="stepper">
                <button type="button" aria-label="Fewer days" disabled={p.days <= 1} onClick={() => p.setDays(Math.max(1, p.days - 1))}><Minus size={14} /></button>
                <input type="number" min={1} max={7} required value={p.days} onChange={e => p.setDays(Number(e.target.value))} />
                <button type="button" aria-label="More days" disabled={p.days >= 7} onClick={() => p.setDays(Math.min(7, p.days + 1))}><Plus size={14} /></button>
              </span>
            </label>
          </div>
          <div className="chips" aria-label="Destination ideas">
            {inspirations.map(place => <motion.button type="button" key={place} className={'chip' + (place === p.destination ? ' on' : '')} onClick={() => p.setDestination(place)} whileHover={{ y: -2 }} whileTap={{ scale: .95 }}>
              {place.split(',')[0]}
            </motion.button>)}
          </div>
          <label className="field">What does your ideal trip look like?
            <textarea required maxLength={4000} value={p.message} onChange={e => p.setMessage(e.target.value)} />
          </label>
          <div className="form-footer">
            <span className="hint">Weather · Places · Itineraries</span>
            <motion.button className="primary" disabled={p.busy || mode === 'offline'} type="submit" whileHover={{ scale: 1.03 }} whileTap={{ scale: .97 }}>
              {p.busy ? <><span className="spinner" /> Weaving your plan…</> : <>Explore my trip <ArrowUpRight size={17} /></>}
            </motion.button>
          </div>
        </motion.form>}
      </AnimatePresence>
    </motion.div>

    <Status busy={p.busy} failed={!!p.failure}>{p.status}</Status>
    {mode === 'demo' && <Notice>Demo mode uses illustrative sample data—not live forecasts or researched attractions. Configure the backend for live mode.</Notice>}
  </div>
}
