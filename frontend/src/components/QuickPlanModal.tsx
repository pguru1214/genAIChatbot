import { useEffect } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ArrowUpRight, CalendarDays, MapPin, Minus, Plus, SlidersHorizontal, X } from 'lucide-react'
import { Notice, ease } from './ui'

export type QuickForm = {
  destination: string; setDestination: (v: string) => void
  origin: string; setOrigin: (v: string) => void
  budget: string; setBudget: (v: string) => void
  currency: string; setCurrency: (v: string) => void
  dayStart: string; setDayStart: (v: string) => void
  dayEnd: string; setDayEnd: (v: string) => void
  message: string; setMessage: (v: string) => void
  days: number; setDays: (v: number) => void
  date: string; setDate: (v: string) => void
}
const inspirations = ['Jaipur, Rajasthan, India', 'Goa, India', 'Kerala, India', 'Mysuru, Karnataka, India', 'Hyderabad, Telangana, India']

export function QuickPlanModal({ open, form: f, busy, mode, onClose, onSubmit }: { open: boolean; form: QuickForm; busy: boolean; mode: string; onClose: () => void; onSubmit: () => void }) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  return <AnimatePresence>
    {open && <motion.div className="modal-scrim" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <motion.form className="modal" role="dialog" aria-modal="true" aria-labelledby="quick-title" onSubmit={e => { e.preventDefault(); onSubmit() }}
        initial={{ opacity: 0, y: 30, scale: .96 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 20, scale: .97 }} transition={{ duration: .4, ease }}>
        <header className="modal-head">
          <span className="form-icon"><SlidersHorizontal size={17} /></span>
          <div><h2 id="quick-title">Quick plan</h2><p>Fill in the essentials and get an itinerary in one go, no back-and-forth.</p></div>
          <button type="button" className="icon-btn" aria-label="Close" onClick={onClose}><X size={18} /></button>
        </header>
        <div className="modal-body">
          <p className="muted">If omitted: departure in seven days, total budget ₹50,000 and sightseeing 10 AM–6 PM. Tell the guide in chat to change these.</p>
          <label className="field">Starting city
            <span className="input-wrap"><MapPin size={16} /><input required maxLength={200} value={f.origin} onChange={e => f.setOrigin(e.target.value)} placeholder="For example, Hyderabad" /></span>
          </label>
          <label className="field">Where in India? State, district or city
            <span className="input-wrap"><MapPin size={16} /><input autoFocus required maxLength={200} value={f.destination} onChange={e => f.setDestination(e.target.value)} /></span>
          </label>
          <div className="chips" aria-label="Destination ideas">
            {inspirations.map(place => <button type="button" key={place} className={'chip' + (place === f.destination ? ' on' : '')} onClick={() => f.setDestination(place)}>{place.split(',')[0]}</button>)}
          </div>
          <div className="modal-row">
            <label className="field">Departure
              <span className="input-wrap"><CalendarDays size={16} /><input type="date" value={f.date} onChange={e => f.setDate(e.target.value)} /></span>
            </label>
            <label className="field">Days
              <span className="stepper">
                <button type="button" aria-label="Fewer days" disabled={f.days <= 1} onClick={() => f.setDays(Math.max(1, f.days - 1))}><Minus size={14} /></button>
                <input type="number" min={1} max={7} required value={f.days} onChange={e => f.setDays(Number(e.target.value))} />
                <button type="button" aria-label="More days" disabled={f.days >= 7} onClick={() => f.setDays(Math.min(7, f.days + 1))}><Plus size={14} /></button>
              </span>
            </label>
          </div>
          <label className="field">What does your ideal trip look like?
            <textarea required maxLength={4000} value={f.message} onChange={e => f.setMessage(e.target.value)} />
          </label>
          <div className="modal-row">
            <label className="field">Total trip budget<input maxLength={200} value={f.budget} onChange={e => f.setBudget(e.target.value)} placeholder="50000" /></label>
            <label className="field">Currency<input maxLength={30} value={f.currency} onChange={e => f.setCurrency(e.target.value)} placeholder="INR" /></label>
          </div>
          <div className="modal-row">
            <label className="field">Daily start<input required type="time" value={f.dayStart} onChange={e => f.setDayStart(e.target.value)} /></label>
            <label className="field">Daily finish<input required type="time" value={f.dayEnd} onChange={e => f.setDayEnd(e.target.value)} /></label>
          </div>
          {mode === 'demo' && <Notice>Demo mode uses illustrative sample data—not live forecasts or researched attractions. Configure the backend for live mode.</Notice>}
        </div>
        <footer className="modal-foot">
          <span className="hint">Weather · Places · Itinerary</span>
          <button type="button" className="ghost-btn" onClick={onClose}>Cancel</button>
          <motion.button className="primary" disabled={busy || mode === 'offline'} type="submit" whileHover={{ scale: 1.03 }} whileTap={{ scale: .97 }}>
            {busy ? <><span className="spinner" /> Weaving your plan…</> : <>Create itinerary <ArrowUpRight size={17} /></>}
          </motion.button>
        </footer>
      </motion.form>
    </motion.div>}
  </AnimatePresence>
}
