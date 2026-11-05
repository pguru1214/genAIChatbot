import { useEffect, useRef, useState } from 'react'
import { readEvents } from '../lib/sse'
import { useToast } from '../components/Toasts'
import type { Conversation, ConversationSummary, Details } from '../types'

const storageKey = 'tripweave-conversation'

/** Guided conversation state: history, the active conversation, and streaming turns. */
export function useConversation({ mode, onSaved }: { mode: string; onSaved: () => void }) {
  const [view, setView] = useState<Conversation | null>(null)
  const [list, setList] = useState<ConversationSummary[]>([])
  const [message, setMessage] = useState('')
  const [details, setDetails] = useState<Details>({})
  const [busy, setBusy] = useState(true)
  const [status, setStatus] = useState('Loading your conversation…')
  const [failed, setFailed] = useState(false)
  const sending = useRef(false)
  // The traveller's message, shown immediately until the server echoes the conversation back.
  const [outgoing, setOutgoing] = useState('')
  const toast = useToast()
  useEffect(() => { if (failed) toast({ title: 'The guide hit a snag', message: status }) }, [failed, status])

  function apply(data: Conversation) {
    setView(data); setDetails(data.details)
    try { localStorage.setItem(storageKey, data.id) } catch { /* Server history remains available. */ }
  }
  async function refreshList() {
    const response = await fetch('/api/conversations')
    if (!response.ok) throw new Error('Could not load conversations. Check that the backend is running.')
    const data: ConversationSummary[] = await response.json()
    setList(data); return data
  }
  async function open(id: string) {
    const response = await fetch(`/api/conversations/${id}`)
    if (!response.ok) throw new Error('Could not reopen this conversation.')
    const data: Conversation = await response.json()
    apply(data); return data
  }
  useEffect(() => {
    let active = true
    void (async () => {
      try {
        const conversations = await refreshList()
        let saved: string | null = null
        try { saved = localStorage.getItem(storageKey) } catch { /* Optional convenience. */ }
        const restored = active && saved && conversations.some(c => c.id === saved) ? await open(saved) : null
        if (active) setStatus(restored?.pending ? 'Your trip is waiting for clarification. Answer the question below.' : 'Tell me about your trip, or continue where you left off.')
      } catch (error) { if (active) { setFailed(true); setStatus(String(error)) } }
      finally { if (active) setBusy(false) }
    })()
    return () => { active = false }
  }, [])

  const hasEdits = Object.entries(details).some(([key, value]) => value !== '' && value !== view?.details[key])
  async function send(reply?: string, chosenDetails: Details = {}) {
    const submitted = reply ?? message.trim()
    if (busy || sending.current || (!submitted && !view?.recoverable && !hasEdits)) return
    sending.current = true
    const lastUser = view?.messages.slice().reverse().find(m => m.role === 'user')?.content
    const repeatFailed = view?.recoverable && submitted === lastUser && !hasEdits &&
      Object.entries(chosenDetails).every(([key, value]) => value === view.details[key])
    setBusy(true); setFailed(false); setStatus('Checking your trip details…'); setOutgoing(repeatFailed ? '' : submitted || (hasEdits ? 'Apply trip details' : 'Retry saved turn'))
    let current = view
    try {
      if (!current) {
        const response = await fetch('/api/conversations', { method: 'POST' })
        if (!response.ok) throw new Error('Could not start a conversation')
        const { id } = await response.json()
        current = { id, details: {}, messages: [], pending: null, checkpoint_id: null, recoverable: false }
        apply(current)
      }
      const response = await fetch(`/api/conversations/${current.id}/messages`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
          message: submitted || (hasEdits ? 'Apply trip details' : 'Retry saved turn'), checkpoint_id: current.checkpoint_id,
          details: { ...Object.fromEntries(Object.entries(details).filter(([key, value]) => value !== '' && value !== current!.details[key])), ...chosenDetails },
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        }),
      })
      if (!response.ok) throw new Error(response.status === 409 ? 'Conversation changed or is busy. Reopen it before sending again.' : response.status === 422 ? 'Check the details: valid dates, an IANA time zone, and 1–7 days are required.' : 'Could not accept this message.')
      setMessage('')
      let complete = false
      await readEvents(response, (event, data) => {
        if (event === 'progress') setStatus(data.message)
        if (event === 'conversation') { apply(data.conversation); setOutgoing('') }
        if (event === 'completed') complete = true
        if (event === 'error') throw new Error(data.message)
      })
      if (!complete) throw new Error('Connection interrupted. Reopen to check your saved progress.')
      setMessage(''); setStatus('Progress saved. You can continue after refreshing.')
      await refreshList(); onSaved()
    } catch (error) {
      setFailed(true); setStatus(error instanceof TypeError && /fetch|network|load failed/i.test(error.message)
        ? 'The connection to the backend was interrupted. Your message is kept or saved in this conversation. Reopen it before retrying.'
        : error instanceof Error ? error.message : 'Unable to complete this turn')
      if (current) {
        try {
          const restored = await open(current.id)
          // A dropped stream can arrive after the graph has already persisted a
          // new question. Show that durable question instead of an obsolete error.
          if (restored.pending && restored.checkpoint_id !== current.checkpoint_id) {
            setFailed(false); setStatus('Your progress was restored. Please answer the clarification question.')
          } else if (restored.result && !restored.recoverable && restored.checkpoint_id !== current.checkpoint_id) {
            setFailed(false); setStatus('Your completed plan was restored from the saved conversation.')
            onSaved()
          }
          await refreshList()
        } catch { /* Keep the actionable error when restoration is unavailable. */ }
      }
    } finally { sending.current = false; setBusy(false); setOutgoing('') }
  }

  function choose(id: string) {
    setMessage(''); setFailed(false)
    if (!id) { setView(null); setDetails({}); setStatus('Ready for a new journey.'); try { localStorage.removeItem(storageKey) } catch { /* Optional. */ } }
    else { setBusy(true); void open(id).then(() => setStatus('Conversation restored.')).catch(error => { setFailed(true); setStatus(String(error)) }).finally(() => setBusy(false)) }
  }

  const canSend = !busy && mode !== 'offline' && (!!message.trim() || !!view?.recoverable || hasEdits)
  return { view, list, message, setMessage, details, setDetails, busy, status, outgoing, hasEdits, canSend, send, choose }
}
export type ConversationState = ReturnType<typeof useConversation>
