import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'

type Trip = { id: string; destination: string; answer: string; mode: string }
type Evidence = { id: string; provider: string; url: string | null }
type Result = { answer: string; agent_trace: string[]; trip_id: string; research?: { evidence: Evidence[]; errors: string[] }; action?: { kind: string }; proposal_id?: string }

function App() {
  const [destination, setDestination] = useState('Jaipur')
  const [message, setMessage] = useState('Plan a relaxed trip with historical attractions and a packing checklist.')
  const [days, setDays] = useState(3)
  const [date, setDate] = useState('')
  const [mode, setMode] = useState('connecting')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('Ready for your next adventure')
  const [answer, setAnswer] = useState('')
  const [result, setResult] = useState<Result | null>(null)
  const [trips, setTrips] = useState<Trip[]>([])

  async function refresh() {
    const response = await fetch('/api/trips')
    if (!response.ok) throw new Error('Could not load saved trips')
    setTrips(await response.json())
  }
  useEffect(() => {
    fetch('/api/health').then(r => { if (!r.ok) throw new Error(); return r.json() }).then(d => setMode(d.mode)).catch(() => { setMode('offline'); setStatus('Start the FastAPI backend on port 8000') })
    refresh().catch(() => {})
  }, [])

  async function run(intent = 'auto') {
    if (busy) return
    const saved = result
    setBusy(true); setAnswer(''); setResult(null); setStatus('Connecting to agents…')
    try {
      const response = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        message, destination, days, start_date: date || null,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, intent,
        trip_id: ['email', 'calendar'].includes(intent) ? saved?.trip_id : null,
      }) })
      if (!response.ok) throw new Error(response.status === 422 ? 'Check your destination, dates, and message.' : 'The backend could not accept this request.')
      if (!response.body) throw new Error('Streaming is unavailable in this browser')
      const reader = response.body.getReader(), decoder = new TextDecoder()
      let buffer = '', completed = false
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let boundary: number
        while ((boundary = buffer.indexOf('\n\n')) >= 0) {
          const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2)
          const event = frame.split('\n').find(l => l.startsWith('event: '))?.slice(7)
          const raw = frame.split('\n').find(l => l.startsWith('data: '))?.slice(6)
          if (!raw) continue
          const data = JSON.parse(raw)
          if (event === 'progress') setStatus(data.message)
          if (event === 'answer_delta') setAnswer(previous => previous + data.text)
          if (event === 'completed') { completed = true; setResult(data.result); setStatus('Plan saved · Workflow complete') }
          if (event === 'error') throw new Error(data.message)
        }
      }
      if (!completed) throw new Error('Connection ended before completion. Check saved trips before retrying.')
      await refresh()
    } catch (error) { setStatus(error instanceof Error ? error.message : 'Request failed') }
    finally { setBusy(false) }
  }

  return <div className="layout">
    <aside><a className="brand" href="/">✳ TripWeave</a><p className="muted">A little curiosity.<br/>A better journey.</p>
      <h2>Your journeys</h2>{trips.length === 0 && <p className="muted">Your saved plans will appear here.</p>}
      <nav>{trips.map(trip => <button disabled={busy} className="trip" key={trip.id} onClick={() => { setDestination(trip.destination); setAnswer(trip.answer); setResult({ ...trip, trip_id: trip.id, agent_trace: [] }); setStatus(`Saved ${trip.mode} plan`) }}>↗ {trip.destination}<span>{trip.mode}</span></button>)}</nav>
      <div className="aside-note">Built with Gemini, LangGraph & LangChain.<br/>Three specialists. One travel companion.</div>
    </aside>
    <main><header><span className="eyebrow">YOUR NEXT CHAPTER STARTS HERE</span><span className={'badge ' + mode}>{mode} mode</span></header>
      <div className="planner-intro"><h1>Less planning. <em>More possibility.</em></h1><p className="intro">Your next journey starts with a few details. We’ll take it from here.</p></div>
      <form onSubmit={event => { event.preventDefault(); void run() }}>
        <div className="form-heading"><h2>A journey, made for you</h2><span>THE DETAILS MAKE THE DIFFERENCE</span></div>
        <div className="fields"><label>Where to?<input required maxLength={200} value={destination} onChange={e => setDestination(e.target.value)} /></label>
          <label>Departure<input type="date" value={date} onChange={e => setDate(e.target.value)} /></label>
          <label>Days<input type="number" min={1} max={7} required value={days} onChange={e => setDays(Number(e.target.value))} /></label></div>
        <label>What does your ideal trip look like?<textarea required maxLength={4000} value={message} onChange={e => setMessage(e.target.value)} /></label>
        <div className="form-footer"><span>Weather · Places · Itineraries</span><button disabled={busy || mode === 'offline'} type="submit">{busy ? 'Weaving your plan…' : 'Explore my trip ↗'}</button></div>
      </form>
      <p className="status" role="status" aria-live="polite">{busy ? '◌ ' : '• '}{status}</p>
      {mode === 'demo' && <p className="notice">Demo mode uses illustrative sample data—not live forecasts or researched attractions. Configure the backend for live mode.</p>}
      {answer && <section className="answer"><div className="eyebrow">YOUR TRAVEL NOTEBOOK</div><div className="answer-text">{answer}</div>
        {result && <><div className="agents">{result.agent_trace.map(name => <span key={name}>{name}</span>)}</div>
          {result.research?.errors.map(error => <p className="notice" key={error}>{error}</p>)}
          <div className="sources">{result.research?.evidence.filter(e => e.url).map(e => <a key={e.id} href={e.url!} target="_blank" rel="noreferrer">{e.provider} ↗</a>)}</div>
          {!result.action && <div className="actions"><button disabled={busy} onClick={() => void run('email')}>Preview email</button><button disabled={busy} onClick={() => void run('calendar')}>Preview calendar export</button></div>}
          {result.action && <p className="notice">Preview only. Google OAuth and execution are not connected. No email or calendar event was created.</p>}
        </>}
      </section>}
      <footer>Local development starter · Verify travel details before departure · Not for public deployment</footer>
    </main>
  </div>
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>)
