import { useEffect, useState, type ReactNode } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { BookOpen, CalendarDays, CalendarPlus, Check, Clock, Coins, Heart, Link2, Mail, MapPin, PanelRightClose, Timer, Users, Wallet } from 'lucide-react'
import type { ConversationState } from '../hooks/useConversation'
import type { Plan } from '../types'
import { RichText } from './RichText'
import { RouteArt } from './RouteArt'
import { Notice, Sources, ease } from './ui'

type Tab = 'itinerary' | 'details' | 'sources'
const sourceLabel = { chat: 'From this chat', quick: 'Quick plan', saved: 'Saved itinerary' }
const fields: { key: string; label: string; icon: ReactNode; wide?: boolean }[] = [
  { key: 'destination', label: 'Destination', icon: <MapPin size={15} />, wide: true },
  { key: 'start_date', label: 'Departure date', icon: <CalendarDays size={15} /> },
  { key: 'days', label: 'Days (1–7)', icon: <Timer size={15} /> },
  { key: 'budget', label: 'Total budget', icon: <Wallet size={15} /> },
  { key: 'currency', label: 'Currency', icon: <Coins size={15} /> },
  { key: 'interests', label: 'Interests', icon: <Heart size={15} />, wide: true },
  { key: 'companions', label: 'Travelling with', icon: <Users size={15} /> },
  { key: 'timezone', label: 'Trip time zone', icon: <Clock size={15} /> },
]

export function TripPanel({ plan, conv, actionBusy, onAction, onClose }: { plan: Plan | null; conv: ConversationState; actionBusy: boolean; onAction: (intent: string) => void; onClose: () => void }) {
  const [tab, setTab] = useState<Tab>('itinerary')
  // A newly arrived plan always opens on the itinerary.
  useEffect(() => { if (plan) setTab('itinerary') }, [plan?.key])
  const evidence = plan?.result?.research?.evidence ?? []
  const sourceCount = evidence.filter(e => e.url).length + (plan?.result?.research?.errors.length ?? 0)
  const known = fields.filter(f => conv.details[f.key] !== undefined && conv.details[f.key] !== '').length
  const tabs: { id: Tab; label: string; badge?: string }[] = [
    { id: 'itinerary', label: 'Itinerary' },
    { id: 'details', label: 'Trip details', badge: `${known}/${fields.length}` },
    { id: 'sources', label: 'Sources', badge: sourceCount ? String(sourceCount) : undefined },
  ]

  return <section className="trip-panel" aria-label="Trip">
    <header className="pane-head panel-head">
      <div className="pane-title">
        <strong>{plan?.destination || (conv.details.destination ? String(conv.details.destination) : 'Your trip')}</strong>
        <span>{plan ? sourceLabel[plan.source] : 'Itinerary appears here once it is ready'}{plan && plan.days > 0 && ` · ${plan.days} ${plan.days === 1 ? 'day' : 'days'}`}</span>
      </div>
      <button className="icon-btn panel-close" aria-label="Hide trip panel" onClick={onClose}><PanelRightClose size={18} /></button>
    </header>
    <div className="tabs" role="tablist">
      {tabs.map(t => <button key={t.id} role="tab" aria-selected={tab === t.id} className="tab" onClick={() => setTab(t.id)}>
        {tab === t.id && <motion.span layoutId="tab-underline" className="tab-line" transition={{ type: 'spring', stiffness: 420, damping: 34 }} />}
        {t.label}{t.badge && <span className="tab-badge">{t.badge}</span>}
      </button>)}
    </div>

    <div className="panel-body">
      <AnimatePresence mode="wait">
        <motion.div key={tab} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: .25, ease }}>
          {tab === 'itinerary' && (plan ? <Itinerary plan={plan} /> : <EmptyItinerary />)}
          {tab === 'details' && <DetailsForm conv={conv} />}
          {tab === 'sources' && <div className="sources-tab">
            {plan?.result?.agent_trace?.length ? <><h4 className="panel-sub">Specialists involved</h4><div className="agents">{plan.result.agent_trace.map(name => <span key={name}>{name}</span>)}</div></> : null}
            {plan?.result?.research?.errors.map(error => <Notice key={error}>{error}</Notice>)}
            {evidence.some(e => e.url) ? <><h4 className="panel-sub">References</h4><Sources evidence={evidence} /></> : <div className="panel-empty"><Link2 size={22} /><p>Sources used for the itinerary will be listed here.</p></div>}
          </div>}
        </motion.div>
      </AnimatePresence>
    </div>

    {tab === 'itinerary' && plan?.result && <footer className="panel-actions">
      {plan.result.action
        ? <Notice>Preview only. Google OAuth and execution are not connected. No email or calendar event was created.</Notice>
        : <>
          <motion.button className="ghost-btn" disabled={actionBusy} onClick={() => onAction('email')} whileTap={{ scale: .97 }}><Mail size={15} /> Preview email</motion.button>
          <motion.button className="ghost-btn" disabled={actionBusy} onClick={() => onAction('calendar')} whileTap={{ scale: .97 }}><CalendarPlus size={15} /> Calendar export</motion.button>
        </>}
    </footer>}
  </section>
}

function Itinerary({ plan }: { plan: Plan }) {
  return <article className="itinerary">
    {plan.streaming && <div className="stream-status"><span className="spinner dark" /> {plan.status || 'Weaving your plan…'}</div>}
    {plan.answer ? <RichText text={plan.answer} variant="plan" /> : !plan.streaming && <p className="muted">This plan has no itinerary text.</p>}
    {plan.streaming && plan.answer && <span className="caret" />}
  </article>
}

function EmptyItinerary() {
  const steps = ['Tell the guide where, when and what you enjoy', 'Answer any quick follow-up questions', 'Get a day-by-day itinerary with a packing list']
  return <div className="empty-itinerary">
    <RouteArt />
    <h3>Your itinerary will appear here</h3>
    <ol className="steps">{steps.map((s, i) => <motion.li key={s} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: .3 + i * .1 }}><span>{i + 1}</span>{s}</motion.li>)}</ol>
  </div>
}

function DetailsForm({ conv }: { conv: ConversationState }) {
  const { details, setDetails, busy } = conv
  return <div className="details-form">
    <p className="muted">The guide fills these in as you chat. Edit anything here and it is applied with your next message. For a new destination, start a new trip.</p>
    <div className="details-grid">
      {fields.map(({ key, label, icon, wide }) => <label className={'field' + (wide ? ' wide' : '')} key={key}>{label}
        <span className="input-wrap">{icon}<input disabled={busy} type={key === 'days' ? 'number' : key === 'start_date' ? 'date' : 'text'} min={key === 'days' ? 1 : undefined} max={key === 'days' ? 7 : undefined} maxLength={key === 'interests' ? 500 : 200}
          value={details[key] ?? ''} onChange={e => setDetails({ ...details, [key]: key === 'days' && e.target.value ? Number(e.target.value) : e.target.value })} /></span>
      </label>)}
    </div>
    <AnimatePresence>{conv.hasEdits && <motion.div className="apply-bar" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
      <span><BookOpen size={15} /> You have unsent changes</span>
      <button className="primary small" disabled={busy} onClick={() => void conv.send()}><Check size={15} /> Apply in chat</button>
    </motion.div>}</AnimatePresence>
  </div>
}
