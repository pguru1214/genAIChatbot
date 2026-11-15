import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ArrowUpRight, Backpack, Check, ChevronDown, FileText, Lightbulb, Route, Wallet } from 'lucide-react'
import type { Plan, TransportMode } from '../types'
import { RichText } from './RichText'
import { modeIcon, modeLabel } from './RouteJourney'
import { ease } from './ui'
import { TransportSearch } from './TransportSearch'
import { planDays, planDetails } from '../lib/trip'

export function Overview({ plan, mode, suggested, onMode }: { plan: Plan; mode: TransportMode; suggested: TransportMode; onMode: (m: TransportMode) => void }) {
  const sp = plan.result?.structured_plan
  const [packed, setPacked] = useState<Set<number>>(new Set())
  const [fullText, setFullText] = useState(!sp)
  const currency = String(plan.result?.request?.currency ?? plan.details?.currency ?? 'INR')
  const budgetTotal = sp?.budget_allocation.reduce((s, b) => s + b.amount, 0) ?? 0
  const maxBudget = Math.max(...(sp?.budget_allocation.map(b => b.amount) ?? [1]), 1)
  const fmt = (n: number) => n.toLocaleString('en-IN')

  return <div className="overview">
    {sp && <>
      <motion.p className="overview-lead" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .45, ease }}>{sp.overview}</motion.p>

      <Block icon={<Route size={16} />} title="Getting there" tone="sights">
        <p className="muted">{sp.recommended_mode}</p>
        <div className="mode-cards">{sp.transport_options.map((o, i) => {
          const on = o.mode === mode
          return <motion.button type="button" key={o.mode + i} className={'mode-card' + (on ? ' on' : '')} onClick={() => onMode(o.mode)} aria-pressed={on}
            initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * .07, duration: .4, ease }} whileHover={{ y: -3 }}>
            <span className="mode-card-head"><span className="mode-card-icon">{modeIcon(o.mode, 17)}</span><strong>{modeLabel(o.mode)}</strong>{suggested === o.mode && <i>Suggested</i>}</span>
            <span className="mode-card-route">{o.route}</span>
            <span className="mode-card-facts"><b>{o.duration_estimate}</b><b>{o.cost_estimate}</b></span>
            <span className="mode-card-best">{o.best_for}</span>
          </motion.button>
        })}</div>
        <p className="muted small">Durations and costs are unverified estimates. Check services before booking.</p>
        <TransportSearch mode={mode} details={planDetails(plan, {})} days={planDays(plan)} />
      </Block>

      <Block icon={<Wallet size={16} />} title="Budget plan" tone="food" sub={`${currency} ${fmt(budgetTotal)}`}>
        <div className="budget">{sp.budget_allocation.map((b, i) => <div className="budget-row" key={b.category}>
          <span className="budget-label">{b.category}</span>
          <span className="budget-track"><motion.span className="budget-fill" style={{ '--h': `${(i * 37) % 360}` } as React.CSSProperties}
            initial={{ width: 0 }} animate={{ width: `${(b.amount / maxBudget) * 100}%` }} transition={{ delay: .2 + i * .08, duration: .9, ease }} /></span>
          <span className="budget-amt">{fmt(b.amount)}</span>
        </div>)}</div>
        <p className="muted small">Planning targets, not quotes.</p>
      </Block>

      <Block icon={<Backpack size={16} />} title="Packing list" tone="stay" sub={`${packed.size}/${sp.packing_list.length} packed`}>
        <ul className="packing">{sp.packing_list.map((item, i) => {
          const on = packed.has(i)
          return <motion.li key={item} initial={{ opacity: 0, scale: .9 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: i * .03 }}>
            <button type="button" className={on ? 'on' : ''} aria-pressed={on} onClick={() => setPacked(s => { const n = new Set(s); if (on) n.delete(i); else n.add(i); return n })}>
              <span className="check">{on && <motion.span initial={{ scale: 0 }} animate={{ scale: 1 }}><Check size={12} /></motion.span>}</span>{item}
            </button>
          </motion.li>
        })}</ul>
      </Block>

      {sp.notes.length > 0 && <Block icon={<Lightbulb size={16} />} title="Good to know" tone="neutral">
        <ul className="notes">{sp.notes.map(n => <li key={n}>{n}</li>)}</ul>
      </Block>}
    </>}

    {!!plan.result?.connectivity?.verification_links.length && <div className="sources">{plan.result.connectivity.verification_links.map(link =>
      <a key={link.url} href={link.url} target="_blank" rel="noreferrer">{link.label}<ArrowUpRight size={13} /></a>)}</div>}

    {sp && <button type="button" className="text-btn" onClick={() => setFullText(v => !v)} aria-expanded={fullText}>
      <FileText size={14} /> {fullText ? 'Hide' : 'Show'} full plan text <ChevronDown size={14} style={{ rotate: fullText ? '180deg' : '0deg', transition: 'rotate .25s' }} /></button>}
    <AnimatePresence initial={false}>{fullText && <motion.div className="full-text" initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: .35, ease }}>
      {plan.streaming && <div className="stream-status"><span className="spinner dark" /> {plan.status || 'Weaving your plan…'}</div>}
      {plan.answer ? <RichText text={plan.answer} variant="plan" /> : !plan.streaming && <p className="muted">This plan has no itinerary text.</p>}
      {plan.streaming && plan.answer && <span className="caret" />}
    </motion.div>}</AnimatePresence>
  </div>
}

function Block({ icon, title, sub, tone, children }: { icon: React.ReactNode; title: string; sub?: string; tone: string; children: React.ReactNode }) {
  return <motion.section className={'day-section ' + tone} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .4, ease }}>
    <header><span className="section-icon">{icon}</span><h4>{title}</h4>{sub && <span className="section-sub">{sub}</span>}</header>
    {children}
  </motion.section>
}
