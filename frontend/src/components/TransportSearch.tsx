import { useEffect, useMemo, useState } from 'react'
import { ArrowRight, ArrowUpRight, CalendarDays, Clock, RefreshCw, SlidersHorizontal } from 'lucide-react'
import type { Details, ScheduleDay, TransportMode } from '../types'
import { minutes, shortName } from '../lib/trip'

type Point = { code: string; name: string; city?: string; state?: string }
type ClassReport = { class_code: string; status: string; text: string; fare: number | null; updated_at: string | null; available_count?: number | null }
type Offer = { id: string; name: string; service_number: string; origin_code: string; destination_code: string; origin_name?: string; destination_name?: string; departure: string | null; arrival: string | null; arrival_time?: string; duration_minutes: number | null; price: number | null; currency: string; data_kind: string; transfers?: number | null; booking_url: string; classes: string[]; availability_summary: ClassReport[]; found_at?: string | null }
type Search = { mode: string; origin: string; destination: string; date: string; passengers: number; origin_code: string | null; destination_code: string | null }
type Results = { status: string; mode: string; origin: string; destination: string; date: string; offers: Offer[]; origin_points: Point[]; destination_points: Point[]; origin_code: string | null; destination_code: string | null; notice: string; fare_basis: string; provider: string | null; retrieved_at: string; links: { label: string; url: string }[] }
type Availability = { status: string; classes: ClassReport[]; retrieved_at: string; notice: string }
type Leg = { key: string; label: string; origin: string; destination: string; date: string }

// Page-memory only: mode/tab changes reuse the same checked results. Reloading
// clears them; no provider keys or journey data go into browser storage.
const cache = new Map<string, { expires: number; result: Promise<Results> }>()
async function loadSearch(query: Search, refresh = false): Promise<Results> {
  const key = JSON.stringify(query), found = cache.get(key)
  if (!refresh && found && found.expires > Date.now()) return found.result
  const result = fetch('/api/transport/search', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: key })
    .then(async response => {
      if (!response.ok) throw new Error(response.status === 401 ? 'Your access session expired. Refresh the page and sign in again.' : response.status === 422 ? 'Choose a future journey date within the next year and valid station or airport codes.' : 'Transport search could not finish. Please try again.')
      return response.json() as Promise<Results>
    })
  cache.set(key, { expires: Date.now() + 120000, result })
  while (cache.size > 40) cache.delete(cache.keys().next().value!)
  result.catch(() => { if (cache.get(key)?.result === result) cache.delete(key) })
  return result
}

const dateTime = (value: string | null | undefined) => value ? new Date(value).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }) : 'Not supplied'
const fare = (amount: number | null, currency: string) => amount == null ? 'Fare not supplied' : new Intl.NumberFormat('en-IN', { style: 'currency', currency, maximumFractionDigits: 0 }).format(amount)
const today = () => new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' })

export function TransportSearch({ mode, details, days }: { mode: TransportMode; details: Details; days: ScheduleDay[] }) {
  const origin = String(details.origin ?? '').trim()
  const legs = useMemo(() => {
    const output: Leg[] = []
    let previous = origin
    for (const day of days) {
      if (previous && day.base && previous.toLowerCase() !== day.base.toLowerCase()) output.push({ key: `day-${day.day}`, label: day.day === 1 ? 'Outward journey' : `Day ${day.day} transfer`, origin: previous, destination: day.base, date: day.date || String(details.start_date ?? '') })
      previous = day.base
    }
    if (previous && origin && previous.toLowerCase() !== origin.toLowerCase()) output.push({ key: 'return', label: 'Return journey', origin: previous, destination: origin, date: days[days.length - 1]?.date || String(details.start_date ?? '') })
    return output
  }, [origin, days.map(d => `${d.day}|${d.base}|${d.date}`).join('~'), details.start_date])
  const [legKey, setLegKey] = useState('')
  const leg = legs.find(l => l.key === legKey) ?? legs[0]
  const [options, setOptions] = useState({ scope: '', point_mode: '', date: '', passengers: 1, origin_code: '', destination_code: '' })
  const scope = `${leg?.key}:${leg?.origin}:${leg?.destination}`
  const active = options.scope === scope ? options : { scope, point_mode: '', date: leg?.date ?? '', passengers: options.passengers, origin_code: '', destination_code: '' }
  const [draft, setDraft] = useState({ origin: '', destination: '' })
  const [advanced, setAdvanced] = useState(false)
  const [results, setResults] = useState<Results | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const [sort, setSort] = useState('price')
  const supported = ['flight', 'train', 'bus'].includes(mode)
  const query: Search | null = supported && leg && active.date ? { mode, origin: leg.origin, destination: leg.destination, date: active.date, passengers: active.passengers, origin_code: active.point_mode === mode ? active.origin_code || null : null, destination_code: active.point_mode === mode ? active.destination_code || null : null } : null
  const queryKey = JSON.stringify(query)
  useEffect(() => { setDraft({ origin: '', destination: '' }); setAdvanced(false) }, [scope, mode])
  useEffect(() => {
    if (!query) { setResults(null); setBusy(false); setError(''); return }
    let current = true
    setBusy(true); setError(''); setResults(null)
    void loadSearch(query).then(data => {
      if (!current) return
      setResults(data)
      if (data.status === 'choose_points') setAdvanced(true)
      // When a connected provider returns outward results, warm only the return
      // search. Other transfers load on demand to preserve free request quotas.
      if (data.status === 'results' && leg?.key !== 'return') {
        const home = legs.find(l => l.key === 'return')
        if (home && home.date >= today()) void loadSearch({ ...query, origin: home.origin, destination: home.destination, date: home.date, origin_code: null, destination_code: null }).catch(() => {})
      }
    }).catch(e => { if (current) setError(e instanceof Error ? e.message : 'Transport search failed.') })
      .finally(() => { if (current) setBusy(false) })
    return () => { current = false }
  }, [queryKey, revision])
  const offers = [...(results?.offers ?? [])].sort((a, b) => sort === 'duration'
    ? (a.duration_minutes ?? Infinity) - (b.duration_minutes ?? Infinity)
    : (a.price ?? Infinity) - (b.price ?? Infinity))
  if (!supported) return null
  if (!origin || !leg) return <p className="transport-note">Add a starting city and a different destination to compare services for your dates.</p>
  const label = mode === 'flight' ? 'Flight fares' : mode === 'train' ? 'Trains for your date' : 'Bus searches'
  return <section className="transport-search" aria-label={label}>
    <header className="transport-head"><h4>{label}</h4><span className={'transport-badge ' + (mode === 'flight' ? 'cached' : '')}>{mode === 'flight' ? 'Cached fares' : mode === 'train' ? 'Provider schedules' : 'Booking links'}</span></header>
    <div className="transport-controls">
      <label className="field">Journey<select value={leg.key} onChange={e => { setLegKey(e.target.value); setRevision(0) }}>{legs.map(l => <option value={l.key} key={l.key}>{l.label}</option>)}</select></label>
      <label className="field">Travel date<input type="date" min={today()} value={active.date} onChange={e => { setOptions({ ...active, date: e.target.value }); setRevision(0) }} /></label>
      <label className="field">Travellers<select value={active.passengers} onChange={e => { setOptions({ ...active, passengers: Number(e.target.value) }); setRevision(0) }}>{[1, 2, 3, 4, 5, 6].map(n => <option key={n} value={n}>{n}</option>)}</select></label>
    </div>
    <p className="transport-route">{shortName(leg.origin)} <ArrowRight size={13} /> {shortName(leg.destination)}</p>
    <p className="muted small">{active.date} · India local time · Journey times exclude station/airport transfers. Search-date changes do not change your itinerary.</p>
    {mode !== 'bus' && <button className="text-btn" type="button" onClick={() => setAdvanced(v => !v)} aria-expanded={advanced}><SlidersHorizontal size={13} /> {mode === 'train' ? 'Change stations' : 'Change airports'}</button>}
    {advanced && <form className="transport-points" onSubmit={e => { e.preventDefault(); setOptions({ ...active, point_mode: mode, origin_code: draft.origin.trim().toUpperCase(), destination_code: draft.destination.trim().toUpperCase() }); setRevision(0) }}>
      <label className="field">{mode === 'train' ? 'Boarding station code' : 'Departure IATA code'}<input maxLength={8} value={draft.origin} placeholder={results?.origin_code || 'Automatic'} list="transport-origin-points" onChange={e => setDraft({ ...draft, origin: e.target.value })} /><datalist id="transport-origin-points">{results?.origin_points.map(p => <option key={p.code} value={p.code}>{p.name}{p.state ? `, ${p.state}` : ''}</option>)}</datalist></label>
      <label className="field">{mode === 'train' ? 'Arrival station code' : 'Arrival IATA code'}<input maxLength={8} value={draft.destination} placeholder={results?.destination_code || 'Automatic'} list="transport-destination-points" onChange={e => setDraft({ ...draft, destination: e.target.value })} /><datalist id="transport-destination-points">{results?.destination_points.map(p => <option key={p.code} value={p.code}>{p.name}{p.state ? `, ${p.state}` : ''}</option>)}</datalist></label>
      <button className="ghost-btn" type="submit" disabled={busy}>Search selected points</button>
    </form>}
    {busy && <p className="transport-note" role="status"><span className="spinner dark" /> Checking free sources for this journey…</p>}
    {error && <p className="transport-note error" role="alert">{error}</p>}
    {results && <>
      <p className="transport-note" role="status">{results.notice}</p>
      {!!offers.length && <div className="transport-result-head"><span>{offers.length} returned {offers.length === 1 ? 'option' : 'options'}</span><label>Sort <select aria-label="Sort transport results" value={sort} onChange={e => setSort(e.target.value)}><option value="price">Lowest reported fare</option><option value="duration">Shortest journey</option></select></label></div>}
      <div className="transport-offers">{offers.map(offer => <OfferCard key={queryKey + offer.id} offer={offer} date={active.date} mode={mode} />)}</div>
      <div className="transport-links">{results.links.map(link => <a key={link.url} href={link.url} target="_blank" rel="noreferrer">{link.label}<ArrowUpRight size={13} /></a>)}</div>
      <footer className="transport-footer"><p>{results.fare_basis}</p><span>{results.provider ? `Source: ${results.provider} · ` : ''}Checked {dateTime(results.retrieved_at)}</span></footer>
    </>}
    {mode !== 'bus' && <button type="button" className="text-btn" disabled={busy || !query} onClick={() => { cache.delete(queryKey); setRevision(v => v + 1) }}><RefreshCw size={13} /> Refresh results</button>}
  </section>
}

function OfferCard({ offer, date, mode }: { offer: Offer; date: string; mode: TransportMode }) {
  const [travelClass, setTravelClass] = useState(offer.classes.includes('SL') ? 'SL' : offer.classes[0] ?? '')
  const [seats, setSeats] = useState<Availability | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function checkSeats() {
    setBusy(true); setError(''); setSeats(null)
    try {
      const response = await fetch('/api/transport/train-availability', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ train_number: offer.service_number, origin_code: offer.origin_code, destination_code: offer.destination_code, date, travel_class: travelClass }) })
      if (!response.ok) throw new Error('Availability could not be checked. Please confirm with IRCTC.')
      setSeats(await response.json())
    } catch (e) { setError(e instanceof Error ? e.message : 'Availability check failed.') }
    finally { setBusy(false) }
  }
  return <article className="transport-offer">
    <header><strong>{offer.name}</strong><span>{fare(offer.price, offer.currency)}{offer.price != null && ' / adult'}</span></header>
    <p className="transport-route">{offer.origin_name || offer.origin_code} <ArrowRight size={12} /> {offer.destination_name || offer.destination_code}</p>
    <div className="transport-times"><span><CalendarDays size={13} /> {dateTime(offer.departure)}</span><span><ArrowRight size={12} /> {offer.arrival ? dateTime(offer.arrival) : offer.arrival_time ? `${offer.arrival_time} · date unverified` : 'Arrival not supplied'}</span></div>
    <p className="muted small"><Clock size={12} /> {offer.duration_minutes == null ? 'Duration not supplied' : minutes(offer.duration_minutes)}{mode === 'flight' && ` · ${offer.transfers == null ? 'Stops not supplied' : offer.transfers === 0 ? 'Nonstop' : `${offer.transfers} stop(s)`}`}</p>
    {mode === 'flight' && <p className="transport-note">Cached fare; confirm price and seats before booking.{offer.found_at ? ` Found ${dateTime(offer.found_at)}.` : ' Original search time was not supplied.'}</p>}
    {offer.availability_summary.map(report => <p className="muted small" key={report.class_code}>{report.class_code}: {report.text || report.status} · reported {dateTime(report.updated_at)} · may be outdated</p>)}
    {mode === 'train' && !!offer.classes.length && <div className="transport-seat-check"><label>Class <select value={travelClass} onChange={e => { setTravelClass(e.target.value); setSeats(null) }} disabled={busy}>{offer.classes.map(c => <option value={c} key={c}>{c}</option>)}</select></label><button type="button" className="ghost-btn" disabled={busy || !travelClass} onClick={() => void checkSeats()}>{busy ? 'Checking…' : 'Check seats'}</button></div>}
    {error && <p className="transport-note error" role="alert">{error}</p>}
    {seats && <div className="transport-availability" role="status"><p>{seats.notice}</p>{seats.classes.map(c => <p key={c.class_code}><strong>{c.class_code}: {c.text || c.status}</strong> · {fare(c.fare, 'INR')}<br />Source updated {dateTime(c.updated_at)} · checked {dateTime(seats.retrieved_at)}</p>)}</div>}
    <a className="service-link" href={offer.booking_url} target="_blank" rel="noreferrer">{mode === 'train' ? 'Verify and book on IRCTC' : 'Check this fare on Aviasales'} <ArrowUpRight size={13} /></a>
  </article>
}
