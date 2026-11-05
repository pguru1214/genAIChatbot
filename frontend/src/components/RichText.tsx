import { Fragment, type ReactNode } from 'react'

type Block = { kind: 'day' | 'heading' | 'para'; text: string } | { kind: 'list'; items: string[] }

/**
 * Renders agent text as readable structure: "Day N" sections, headings, bullet lists
 * and **bold**. Plain text without markers still renders as paragraphs.
 */
export function RichText({ text, variant = 'chat' }: { text: string; variant?: 'chat' | 'plan' }) {
  return <div className={'rich ' + variant}>{parse(text).map((block, i) => {
    if (block.kind === 'list') return <ul key={i}>{block.items.map((item, j) => <li key={j}>{inline(item)}</li>)}</ul>
    if (block.kind === 'day') return <h4 key={i} className="day"><span>{block.text.match(/\d+/)?.[0]}</span>{inline(block.text.replace(/:$/, ''))}</h4>
    if (block.kind === 'heading') return <h4 key={i}>{inline(block.text)}</h4>
    return <p key={i}>{inline(block.text)}</p>
  })}</div>
}

function parse(text: string): Block[] {
  // Agents sometimes return a whole plan on one line; break before day and checklist markers.
  const normalized = text.replace(/\s+(\**(?:Day|DAY)\s+\d+\b)/g, '\n$1').replace(/\s+(\**Packing (?:checklist|list)\**:)/gi, '\n$1')
  const blocks: Block[] = []
  for (const raw of normalized.split(/\r?\n/)) {
    const line = raw.trim()
    if (!line) continue
    const bullet = line.match(/^(?:[-*•]|\d+[.)])\s+(.*)/)
    if (bullet) {
      const last = blocks[blocks.length - 1]
      if (last?.kind === 'list') last.items.push(bullet[1]); else blocks.push({ kind: 'list', items: [bullet[1]] })
      continue
    }
    const clean = line.replace(/^#{1,6}\s*/, '')
    const day = clean.match(/^\**(Day\s+\d+[^:*]*:?)\**\s*:?\s*(.*)$/i)
    if (day) {
      blocks.push({ kind: 'day', text: day[1].trim() })
      if (day[2]) blocks.push({ kind: 'para', text: day[2] })
      continue
    }
    const label = clean.match(/^\**([A-Z][^.:!?]{2,40}):\**\s*(.*)$/)
    if (/^#{1,6}\s/.test(line) || (label && !label[2])) { blocks.push({ kind: 'heading', text: clean.replace(/\*\*/g, '').replace(/:$/, '') }); continue }
    if (label && /checklist|packing|tips|budget|notes/i.test(label[1])) {
      blocks.push({ kind: 'heading', text: label[1].replace(/\*\*/g, '') })
      // Comma-separated checklists read better as bullets.
      const items = label[2].split(/,\s*(?![^()]*\))/).map(s => s.replace(/\.$/, '').trim()).filter(Boolean)
      blocks.push(items.length > 2 ? { kind: 'list', items } : { kind: 'para', text: label[2] })
      continue
    }
    blocks.push({ kind: 'para', text: clean })
  }
  return blocks
}

/** **bold** and leading "Morning:"-style labels. */
function inline(text: string): ReactNode {
  const parts: ReactNode[] = []
  const lead = text.match(/^((?:Early |Late )?(?:Morning|Afternoon|Evening|Night|Breakfast|Lunch|Dinner|Note|Tip)[^:]{0,24}:)\s*(.*)$/i)
  if (lead) { parts.push(<strong key="lead" className="lead">{lead[1]}</strong>, ' '); text = lead[2] }
  text.split(/(\*\*[^*]+\*\*)/g).forEach((piece, i) => {
    parts.push(piece.startsWith('**') && piece.endsWith('**') ? <strong key={i}>{piece.slice(2, -2)}</strong> : <Fragment key={i}>{piece}</Fragment>)
  })
  return parts
}
