/** Reads a server-sent event stream, calling `onEvent` for every `event:`/`data:` frame. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function readEvents(response: Response, onEvent: (event: string | undefined, data: any) => void) {
  if (!response.body) throw new Error('Streaming is unavailable in this browser')
  const reader = response.body.getReader(), decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let boundary: number
    while ((boundary = buffer.indexOf('\n\n')) >= 0) {
      const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2)
      const event = frame.split('\n').find(l => l.startsWith('event: '))?.slice(7)
      const raw = frame.split('\n').find(l => l.startsWith('data: '))?.slice(6)
      if (raw) onEvent(event, JSON.parse(raw))
    }
  }
}
