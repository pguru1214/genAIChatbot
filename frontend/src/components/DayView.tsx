import { useRef, type ReactNode } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ArrowRight, BedDouble, ChevronLeft, ChevronRight, CloudRain, CloudSun, Coffee, ExternalLink, Footprints, Hotel, Landmark, MapPin, RefreshCw, SlidersHorizontal, Sun, TriangleAlert, UtensilsCrossed } from 'lucide-react'
import type { Activity, ScheduleDay, ServiceDay, StructuredPlan, TransportMode } from '../types'
import { formatDate, minutes, shortName } from '../lib/trip'
import { MealsBlock, ReviewCard, ServiceFooter, StaysBlock, localTime, type FoodStaysState } from './FoodStays'
import { modeIcon, modeLabel } from './RouteJourney'
import { Notice, ease } from './ui'

export function DayStrip({ days, current, onPick }: { days: ScheduleDay[]; current: number; onPick: (day: number) => void }) {
  return <div className="day-strip" role="tablist" aria-label="Trip days">
    {days.map((d, i) => {
      const on = d.day === current
      return <motion.button key={d.day} role="tab" aria-selected={on} className={'day-chip' + (on ? ' on' : '') + (d.status === 'needs_review' ? ' flag' : '')} onClick={() => onPick(d.day)}
        initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * .05, duration: .35, ease }} whileTap={{ scale: .96 }}>
        {on && <motion.span layoutId="day-chip-bg" className="day-chip-bg" transition={{ type: 'spring', stiffness: 420, damping: 34 }} />}
        <span className="day-chip-inner">
          <span className="day-chip-num">Day {d.day}{d.status === 'needs_review' && <TriangleAlert size={11} />}</span>
          <span className="day-chip-base">{shortName(d.base)}</span>
          <span className="day-chip-meta">{formatDate(d.date, { weekday: 'short', day: 'numeric' })}{d.weather?.available && d.weather.max_c != null && <> · {Math.round(d.weather.max_c)}°</>}</span>
        </span>
      </motion.button>
    })}
  </div>
}

export function DayDetail({ day, service, plan, fs, mode, total, onPick, onPrefs }: {
  day: ScheduleDay; service?: ServiceDay; plan?: StructuredPlan; fs: FoodStaysState; mode: TransportMode; total: number
  onPick: (day: number) => void; onPrefs: () => void
}) {
  // Slide in from the side the traveller is moving towards.
  const previous = useRef(day.day)
  const direction = day.day >= previous.current ? 1 : -1
  previous.current = day.day
  const legs = plan?.travel_legs.filter(l => l.day === day.day) ?? []
  const items = day.status === 'needs_review' ? day.unscheduled_options ?? [] : day.activities
  const visits = items.filter(a => a.kind === 'visit').length

  return <AnimatePresence mode="wait" custom={direction} initial={false}>
    <motion.article key={day.day} className="day" custom={direction}
      initial={{ opacity: 0, x: 28 * direction }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 * direction }} transition={{ duration: .32, ease }}>
      <header className="day-head">
        <span className="day-num"><small>Day</small>{String(day.day).padStart(2, '0')}</span>
        <div className="day-title">
          <strong>{formatDate(day.date, { weekday: 'long', day: 'numeric', month: 'long' }) || `Day ${day.day}`}</strong>
          <span><MapPin size={13} /> {day.base}</span>
        </div>
        <Weather day={day} />
      </header>

      {service?.journey && <Journey mode={mode} title="Travel day" journey={service.journey} />}
      {legs.map(leg => <div className="journey-card" key={leg.title}>
        <span className="journey-icon">{modeIcon(mode, 18)}</span>
        <div><strong>{leg.title}</strong><span>{minutes(leg.duration_minutes)} (estimate) · {leg.timing_note}</span></div>
      </div>)}
      {day.status === 'needs_review' && day.review_note && <Notice>{day.review_note}</Notice>}

      <Section tone="sights" icon={<Landmark size={16} />} title="Attractions" sub={visits ? `${visits} ${visits === 1 ? 'stop' : 'stops'}${day.status === 'needs_review' ? ' · optional' : ''}` : undefined}>
        {items.length ? <Timeline items={items} optional={day.status === 'needs_review'} /> : <p className="muted">No activities planned for this day.</p>}
      </Section>

      <Section tone="food" icon={<UtensilsCrossed size={16} />} title="Food" sub={service ? `${service.meals.length} meals` : undefined}
        action={<button className="mini-btn" onClick={onPrefs}><SlidersHorizontal size={13} /> Preferences</button>}>
        {fs.dirty && <p className="dirty-note" role="status">Preferences changed. <button className="text-btn" onClick={() => void fs.refresh()} disabled={fs.busy}>Update suggestions</button></p>}
        {service ? <MealsBlock day={service} fs={fs} /> : <LoadServices fs={fs} what="restaurants near each stop" />}
      </Section>

      <Section tone="stay" icon={<Hotel size={16} />} title="Stay" sub={service ? `near ${shortName(service.base)}` : undefined}>
        {service ? <StaysBlock day={service} fs={fs} /> : <LoadServices fs={fs} what="places to stay near your base" />}
      </Section>

      {service?.return_journey?.journey && <Journey mode={mode} title="Journey home" journey={service.return_journey.journey} />}
      {service?.return_notice && <p className="service-note">{service.return_notice}</p>}
      <ReviewCard fs={fs} />

      <nav className="day-nav">
        <button className="ghost-btn" disabled={day.day <= 1} onClick={() => onPick(day.day - 1)}><ChevronLeft size={15} /> Day {day.day - 1 || ''}</button>
        <span>{day.day} / {total}</span>
        <button className="ghost-btn" disabled={day.day >= total} onClick={() => onPick(day.day + 1)}>Day {day.day < total ? day.day + 1 : ''} <ChevronRight size={15} /></button>
      </nav>
      {day.day === total && <ServiceFooter fs={fs} />}
    </motion.article>
  </AnimatePresence>
}

function Section({ tone, icon, title, sub, action, children }: { tone: string; icon: ReactNode; title: string; sub?: string; action?: ReactNode; children: ReactNode }) {
  return <motion.section className={'day-section ' + tone} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .4, ease, delay: .08 }}>
    <header><span className="section-icon">{icon}</span><h4>{title}</h4>{sub && <span className="section-sub">{sub}</span>}{action}</header>
    {children}
  </motion.section>
}

function Weather({ day }: { day: ScheduleDay }) {
  const w = day.weather
  if (!w?.available) return null
  const rainy = (w.rain_probability ?? 0) >= 50
  return <div className={'weather-pill' + (rainy ? ' rain' : '')} title={`Open-Meteo forecast for ${w.location}`}>
    <motion.span animate={rainy ? { y: [0, 2, 0] } : { rotate: 360 }} transition={rainy ? { repeat: Infinity, duration: 1.6 } : { repeat: Infinity, duration: 18, ease: 'linear' }}>
      {rainy ? <CloudRain size={18} /> : (w.rain_probability ?? 0) >= 25 ? <CloudSun size={18} /> : <Sun size={18} />}
    </motion.span>
    <span><b>{w.min_c != null && w.max_c != null ? `${Math.round(w.min_c)}–${Math.round(w.max_c)}°C` : '—'}</b>{w.rain_probability != null && <small>{w.rain_probability}% rain</small>}</span>
  </div>
}

function Journey({ mode, title, journey }: { mode: TransportMode; title: string; journey: NonNullable<ServiceDay['journey']> }) {
  return <motion.div className="journey-card" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .35, ease }}>
    <span className="journey-icon">{modeIcon(mode, 18)}</span>
    <div>
      <strong>{title} · {modeLabel(mode)}</strong>
      <span className="journey-route">{shortName(journey.origin)} <ArrowRight size={12} /> {shortName(journey.destination)}</span>
      <span>Leave {localTime(journey.departure)} · arrive {localTime(journey.arrival)} · {Math.round(journey.distance_km)} km · {minutes(journey.duration_minutes)}</span>
      <em>{journey.timing_basis}</em>
    </div>
    <a className="mini-btn" href={journey.route_url} target="_blank" rel="noreferrer">Route <ExternalLink size={12} /></a>
  </motion.div>
}

const kindIcon: Record<Activity['kind'], ReactNode> = {
  visit: <Landmark size={14} />, transfer: <Footprints size={14} />, meal: <UtensilsCrossed size={14} />, break: <Coffee size={14} />, 'check-in': <BedDouble size={14} />,
}

function Timeline({ items, optional }: { items: Activity[]; optional: boolean }) {
  return <ol className="timeline">
    <motion.span className="timeline-line" initial={{ scaleY: 0 }} animate={{ scaleY: 1 }} transition={{ duration: .9, ease, delay: .15 }} />
    {items.map((a, i) => {
      const minor = a.kind !== 'visit'
      return <motion.li key={i} className={'tl-item ' + a.kind + (minor ? ' minor' : '')}
        initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: .15 + i * .06, duration: .35, ease }}>
        <span className="tl-time">{a.start ?? ''}</span>
        <span className="tl-dot">{kindIcon[a.kind]}</span>
        {minor
          ? <div className="tl-minor"><span>{a.title}</span><small>{minutes(a.duration_minutes)}</small></div>
          : <div className="tl-card">
            <div className="tl-card-head"><strong>{a.title}</strong><span className="tl-dur">{optional ? 'Optional · ' : ''}{minutes(a.duration_minutes)}</span></div>
            <p>{a.description}</p>
            {a.start && a.end && <span className="tl-range">{a.start} – {a.end}</span>}
          </div>}
      </motion.li>
    })}
  </ol>
}

function LoadServices({ fs, what }: { fs: FoodStaysState; what: string }) {
  if (!fs.available) return <p className="muted">Food and stay suggestions are available once a full itinerary is saved.</p>
  return <div className="load-services">
    <p>Find {what}, using free map data.</p>
    {fs.error && <Notice tone="error" role="alert">{fs.error}</Notice>}
    <button className="primary small" disabled={fs.busy} onClick={() => void fs.refresh()}>{fs.busy ? <><span className="spinner" /> Searching…</> : <><RefreshCw size={14} /> Load suggestions</>}</button>
  </div>
}
