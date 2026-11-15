import { useEffect, useRef, useState, type ReactNode } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { BedDouble, Check, Coffee, ExternalLink, Globe, MapPin, Moon, Phone, RefreshCw, SlidersHorizontal, Soup, UtensilsCrossed, X } from 'lucide-react'
import type { MealReference, Plan, PlaceReference, Result, ServiceDay, ServicePreferences } from '../types'
import { Notice, ease } from './ui'

const defaults: ServicePreferences = { transport_mode: 'unspecified', departure_time: null, return_departure_time: null, dietary: 'any', cuisine: '', accessibility: false, stay_preference: 'any' }
type Review = { place: string; arrival: string; onward_departure: string; onward_arrival: string; detour_minutes: number; extends_trip: boolean; notice: string }
export const localTime = (value: string) => new Date(value).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' })
const distance = (m: number) => m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`

/** Food & stay suggestions for a plan: preferences, refresh, meal choices and overnight reviews. */
export function useFoodStays(plan: Plan | null, onUpdate: (result: Result) => void) {
  const data = plan?.result?.food_stays
  const saved = { ...defaults, ...data?.preferences }
  const [prefs, setPrefs] = useState<ServicePreferences>(saved)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [review, setReview] = useState<Review | null>(null)
  const pending = useRef<AbortController | null>(null)
  useEffect(() => () => pending.current?.abort(), [])
  useEffect(() => { setPrefs({ ...defaults, ...plan?.result?.food_stays?.preferences }); setReview(null); setError('') }, [plan?.result?.trip_id, data?.retrieved_at])
  const dirty = JSON.stringify(prefs) !== JSON.stringify(saved)
  const tripId = plan?.result?.trip_id

  async function refresh() {
    if (!tripId || busy) return
    const controller = new AbortController(); pending.current = controller
    setBusy(true); setError(''); setReview(null)
    try {
      const response = await fetch(`/api/trips/${tripId}/food-stays`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(prefs), signal: controller.signal })
      if (!response.ok) throw new Error(response.status === 422 ? 'Generate a new daily itinerary before loading these suggestions.' : 'Could not refresh suggestions. Check the backend and try again.')
      onUpdate(await response.json())
    } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Could not load suggestions.') }
    finally { if (!controller.signal.aborted) setBusy(false) }
  }

  function chooseMeal(day: number, meal: string, placeId: string) {
    if (!plan?.result || !data) return
    onUpdate({ ...plan.result, food_stays: { ...data, days: data.days.map(d => d.day !== day ? d : {
      ...d, meals: d.meals.map(m => m.meal === meal ? { ...m, selected_place_id: placeId } : m),
    }) } })
  }

  async function reviewStop(day: number, place: PlaceReference, leg: 'outbound' | 'return' = 'outbound') {
    if (busy || dirty || !tripId) return
    const controller = new AbortController(); pending.current = controller
    setBusy(true); setError(''); setReview(null)
    try {
      const response = await fetch(`/api/trips/${tripId}/overnight-review`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
        body: JSON.stringify({ choice: { day, place_id: place.id, leg }, preferences: prefs }) })
      if (!response.ok) throw new Error('The stop could not be reverified. Refresh suggestions before trying again.')
      setReview(await response.json())
    } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Could not review this stop.') }
    finally { if (!controller.signal.aborted) setBusy(false) }
  }

  return { data, prefs, setPrefs, busy, error, review, setReview, dirty, refresh, chooseMeal, reviewStop, available: !!tripId && !plan?.result?.action }
}
export type FoodStaysState = ReturnType<typeof useFoodStays>

/** Collapsible preference form shared by every day. */
export function PreferencesPanel({ fs, open, onClose }: { fs: FoodStaysState; open: boolean; onClose: () => void }) {
  const { prefs, setPrefs, busy } = fs
  return <AnimatePresence initial={false}>
    {open && <motion.form className="prefs" onSubmit={e => { e.preventDefault(); void fs.refresh() }}
      initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: .35, ease }}>
      <div className="prefs-inner">
        <header><SlidersHorizontal size={15} /><strong>Food & stay preferences</strong><button type="button" className="icon-btn small" aria-label="Close preferences" onClick={onClose}><X size={15} /></button></header>
        <div className="details-grid">
          <label className="field">Food preference<select disabled={busy} value={prefs.dietary} onChange={e => setPrefs({ ...prefs, dietary: e.target.value as ServicePreferences['dietary'] })}><option value="any">Any</option><option value="vegetarian">Vegetarian</option><option value="vegan">Vegan</option></select></label>
          <label className="field">Cuisine (optional)<input maxLength={100} disabled={busy} value={prefs.cuisine} placeholder="e.g. seafood, indian" onChange={e => setPrefs({ ...prefs, cuisine: e.target.value })} /></label>
          <label className="field">Accommodation<select disabled={busy} value={prefs.stay_preference} onChange={e => setPrefs({ ...prefs, stay_preference: e.target.value as ServicePreferences['stay_preference'] })}><option value="any">Any</option><option value="hotel">Hotel</option><option value="guest_house">Guest house</option><option value="hostel">Hostel</option><option value="apartment">Apartment</option></select></label>
          <label className="field">Travel mode<select value={prefs.transport_mode} disabled={busy} onChange={e => setPrefs({ ...prefs, transport_mode: e.target.value as ServicePreferences['transport_mode'] })}>
            <option value="unspecified">Not chosen</option><option value="car/taxi">Car / taxi</option><option value="train">Train</option><option value="bus">Bus</option><option value="flight">Flight</option>
          </select></label>
          <label className="field">Road departure (travel days)<input type="time" disabled={busy || prefs.transport_mode !== 'car/taxi'} value={prefs.departure_time ?? ''} onChange={e => setPrefs({ ...prefs, departure_time: e.target.value || null })} /></label>
          <label className="field">Return departure (last day)<input type="time" disabled={busy || prefs.transport_mode !== 'car/taxi'} value={prefs.return_departure_time ?? ''} onChange={e => setPrefs({ ...prefs, return_departure_time: e.target.value || null })} /></label>
        </div>
        <label className="service-checkbox"><input type="checkbox" disabled={busy} checked={prefs.accessibility} onChange={e => setPrefs({ ...prefs, accessibility: e.target.checked })} /> Require listed wheelchair access</label>
        <p className="muted">Road estimates include meal and rest allowances, without live traffic. Prices are not available, so check budget fit with each place.</p>
        <button className="primary small" disabled={busy || !fs.available} type="submit">{busy ? <><span className="spinner" /> Checking free sources…</> : <><RefreshCw size={14} /> Update suggestions</>}</button>
      </div>
    </motion.form>}
  </AnimatePresence>
}

const mealIcon = (meal: string) => /breakfast/i.test(meal) ? <Coffee size={16} /> : /lunch/i.test(meal) ? <Soup size={16} /> : <UtensilsCrossed size={16} />

export function MealsBlock({ day, fs }: { day: ServiceDay; fs: FoodStaysState }) {
  if (!day.meals.length) return <p className="muted">No meal stops for this day.</p>
  return <div className="meals">{day.meals.map((meal, i) => <Meal key={meal.meal} meal={meal} index={i} onChoose={id => fs.chooseMeal(day.day, meal.meal, id)} disabled={fs.busy || fs.dirty} />)}</div>
}

function Meal({ meal, index, onChoose, disabled }: { meal: MealReference; index: number; onChoose: (id: string) => void; disabled: boolean }) {
  return <motion.div className="meal" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * .06, duration: .4, ease }}>
    <header className="meal-head">
      <span className="meal-icon">{mealIcon(meal.meal)}</span>
      <div><strong>{meal.meal}</strong><span>{meal.location}</span></div>
      <time>{meal.start}–{meal.end}</time>
    </header>
    {meal.notice && <p className="service-note">{meal.notice}</p>}
    {meal.places.length > 0 ? <div className="place-strip">{meal.places.map(place => <PlaceCard key={place.id} place={place} tone="food"
      picked={meal.selected_place_id === place.id}
      action={<button className={'pick' + (meal.selected_place_id === place.id ? ' on' : '')} disabled={disabled} aria-pressed={meal.selected_place_id === place.id} onClick={() => onChoose(place.id)}>
        {meal.selected_place_id === place.id ? <><Check size={13} /> Chosen</> : 'Choose'}</button>} />)}
    </div> : <p className="muted">No listed places nearby for this meal.</p>}
    <a className="service-link" href={meal.search_url} target="_blank" rel="noreferrer">More food options on the map <ExternalLink size={12} /></a>
  </motion.div>
}

export function StaysBlock({ day, fs }: { day: ServiceDay; fs: FoodStaysState }) {
  return <div className="stays">
    {day.stay_notice && <p className="service-note">{day.stay_notice}</p>}
    {day.destination_stays.length > 0
      ? <div className="place-strip">{day.destination_stays.map(place => <PlaceCard key={place.id} place={place} tone="stay" />)}</div>
      : <p className="muted">No listed stays found near {day.base}.</p>}
    <a className="service-link" href={day.stay_search_url} target="_blank" rel="noreferrer">More stays on the map <ExternalLink size={12} /></a>
    <Overnight day={day} fs={fs} />
    {day.return_journey && <Overnight day={day.return_journey} fs={fs} leg="return" />}
  </div>
}

function Overnight({ day, fs, leg = 'outbound' }: { day: ServiceDay; fs: FoodStaysState; leg?: 'outbound' | 'return' }) {
  if (!day.overnight.places.length) return null
  return <div className="overnight">
    <h5><Moon size={14} /> {leg === 'return' ? 'Return route' : 'On the road'}: stops if you arrive after 10 PM</h5>
    {day.overnight.reason && <p className="muted">{day.overnight.reason}</p>}
    <div className="place-strip">{day.overnight.places.map(place => <PlaceCard key={place.id} place={place} tone="stay"
      action={<button className="pick" disabled={fs.busy || fs.dirty} onClick={() => void fs.reviewStop(day.day, place, leg)}>Review stop</button>} />)}</div>
  </div>
}

export function ReviewCard({ fs }: { fs: FoodStaysState }) {
  const review = fs.review
  return <AnimatePresence>{review && <motion.section className="overnight-review" role="status" initial={{ opacity: 0, scale: .97 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }}>
    <header><BedDouble size={16} /><strong>{review.place}</strong><button className="icon-btn small" aria-label="Close review" onClick={() => fs.setReview(null)}><X size={15} /></button></header>
    <p>Estimated check-in <b>{localTime(review.arrival)}</b>. Leave again <b>{localTime(review.onward_departure)}</b>, arriving <b>{localTime(review.onward_arrival)}</b>.</p>
    <p>Road detour: about {review.detour_minutes} minutes.</p>
    {review.extends_trip && <Notice>This alternative goes beyond your trip dates. Change the duration before using it.</Notice>}
    <p className="muted">{review.notice}</p>
  </motion.section>}</AnimatePresence>
}

export function PlaceCard({ place, tone, picked, action }: { place: PlaceReference; tone: 'food' | 'stay'; picked?: boolean; action?: ReactNode }) {
  const tags = [place.cuisine?.split(/[;,]/).slice(0, 2).join(' · '), ...place.amenities.slice(0, 2)].filter(Boolean)
  return <motion.article className={'place ' + tone + (picked ? ' picked' : '')} layout whileHover={{ y: -3 }} transition={{ type: 'spring', stiffness: 400, damping: 28 }}>
    <div className="place-top">
      <span className="place-icon">{tone === 'food' ? <UtensilsCrossed size={14} /> : <BedDouble size={14} />}</span>
      <span className="place-dist"><MapPin size={11} />{distance(place.distance_m)}</span>
    </div>
    <strong className="place-name">{place.name}</strong>
    <p className="place-addr">{place.address}</p>
    {tags.length > 0 && <div className="place-tags">{tags.map(t => <span key={t}>{t}</span>)}</div>}
    <p className="place-hours">{place.opening_hours ? place.opening_hours : 'Hours not listed'}</p>
    {place.arrival && <p className="place-hours">Arrive ~{localTime(place.arrival)} · detour {place.detour_minutes} min</p>}
    <div className="place-links">
      <a href={place.url} target="_blank" rel="noreferrer" aria-label={`${place.name} on map`}><MapPin size={13} /></a>
      {place.website && <a href={place.website} target="_blank" rel="noreferrer" aria-label={`${place.name} website`}><Globe size={13} /></a>}
      {place.phone && <a href={`tel:${place.phone}`} aria-label={`Call ${place.name}`}><Phone size={13} /></a>}
      {action}
    </div>
  </motion.article>
}

export function ServiceFooter({ fs }: { fs: FoodStaysState }) {
  if (!fs.data) return null
  return <footer className="service-attribution">
    <p>{fs.data.limitations}</p>
    <p>Retrieved {localTime(fs.data.retrieved_at)}. Choices last for this page session. <a href="https://www.geoapify.com/" target="_blank" rel="noreferrer">Powered by Geoapify</a> · <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap contributors</a></p>
  </footer>
}
