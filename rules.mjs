// When the voice may interrupt: which listener command a boss reply goes out as, and what asks for a held line.
const FRESH = 90_000 // a reply this soon after the request: the user is waiting for it, even in a call

// listen: the line opens the follow-up window. `end` is say without it; an older line without it is simply a tell.
// A question nobody prompted is a late too: the user can answer it without the wake word, unless a call is on.
export function verbFor(askedAt, listen = true, now = Date.now()) {
  if (askedAt && now - askedAt <= FRESH) return listen ? 'say' : 'end'
  return listen ? 'late' : 'tell'
}

// An answer to a question: "Q8 A", "p1 b", a bare letter or number, "B. Okay", or a recitation ("A, B, C, D").
// These go straight to the boss. The router called such answers unclear and said "Say that again?" (2026-10-30).
export function isAnswer(text) {
  return /\b[a-z]\W*\d{1,2}\W*[a-z]\b/i.test(text) || /^\W*\d{1,2}\W*$/.test(text) ||
    /^\W*[a-z]\s*([.,!?:;]|$)/i.test(text) || (text.match(/\b[a-z0-9]\b/gi) ?? []).length >= 4
}

// "Hello? Are you there?": checking that it's there, not a request. Whole short utterances only, so "hello, how do I
// fix this" or a long line with "hear me" in it is not one.
export function isLooking(text) {
  const said = text.toLowerCase().replace(/[^\w\s']/g, ' ').trim()
  return said.split(/\s+/).length <= 8 && (/^((hello|hi|hey|helo|jarvis|claude|okay|ok)\s*)+$/.test(said) ||
    /\b(are you there|you there|you still there|can you hear|do you hear|hear me|anyone there|you listening|andyan ka|nandyan ka|nandiyan ka|naririnig mo)\b/.test(said))
}

// Too long to be a cut-off fragment: never "Say that again?", the boss decides.
export const isLong = text => text.trim().split(/\s+/).length >= 6

// A sound of listening, right after a line that asked nothing: people don't answer those, and "Say that again?" was wrong.
export const isFiller = text => /^(hm+|mm+|mm hmm|mhm|uh huh|uh+|um+|ah+|oh+|okay|ok|alright|all right|right|damn|wow|nice|i see|got it)$/
  .test(text.toLowerCase().replace(/[^\w\s]/g, ' ').replace(/\s+/g, ' ').trim())

// By default only a line that asks something opens the window: an acknowledgment ends the exchange.
export const asksSomething = text => /\?|\b(say|pick|choose|tell me)\b/i.test(text)

// Short on purpose: "what's the update on the dentaria deploy?" is a request for the boss, not for the held line.
export function asksForHeld(text) {
  const said = text.toLowerCase().replace(/[^\w\s']/g, '').trim()
  return said.split(/\s+/).length <= 6 &&
    (/\b(what|what's|whats|ano|anong|give|tell|read|sabihin)\b.*\b(update|updates|message|balita)\b/.test(said) ||
      /^(the )?updates?$|^go ahead$|^what is it$|^what was that$|^ano (yun|yon|iyon)$/.test(said))
}

// The notes worth sending to Haiku: all of them when they fit, else the ones sharing the most words with the question
// (a word in a note's name counts more), then the notes those link to with [[name]], which is how graphify and
// Obsidian tie them together. notes: [{ name, text }]. ponytail: words, not meaning, so a Taglish question can miss an
// English note; embeddings if that shows up.
const FIT = 8000
export function shortlist(notes, question, fit = FIT) {
  const all = notes.map(n => n.text).join('\n\n')
  if (all.length <= fit) return all
  const words = new Set(question.toLowerCase().match(/\w{3,}/g) ?? [])
  const hits = text => (text.toLowerCase().match(/\w{3,}/g) ?? []).filter((w, i, a) => words.has(w) && a.indexOf(w) === i).length
  const ranked = notes.map(n => [hits(n.name) * 5 + hits(n.text), n]).filter(([score]) => score).sort((a, b) => b[0] - a[0]).map(([, n]) => n)
  const byName = new Map(notes.map(n => [n.name.toLowerCase(), n]))
  const linked = ranked.flatMap(n => [...n.text.matchAll(/\[\[([^\]|#]+)/g)].map(m => byName.get(m[1].trim().toLowerCase()))).filter(Boolean)
  const picked = []
  let size = 0
  for (const n of new Set([...ranked, ...linked])) {
    if (size + n.text.length > fit) continue
    picked.push(`# ${n.name}\n${n.text}`)
    size += n.text.length
  }
  return picked.join('\n\n')
}

// The notes with their {placeholders} filled, then the live values themselves: a note can go stale ("no schedule yet"
// with a webinar tonight), so they are marked as newer. A placeholder with no value stays, and the answer then passes
// to the boss.
export function withFacts(notes, facts) {
  const filled = notes.replace(/\{(\w+)\}/g, (all, key) => facts[key] ?? all)
  const lines = Object.entries(facts).map(([k, v]) => `${k}: ${v}`).join('\n')
  return lines ? `${filled}\n\nLive values, newer than the notes above; they win where the two differ:\n${lines}` : filled
}

// The status bank: workers' spoken progress lines (progress.mjs), one file per machine in the folder the PCs sync.
const BANK_HOURS = 12 // an older line isn't news
const NOT_TOPIC = new Set(`status update progress how hows what whats is are the a an of on with to for and it its going doing
  done finished ready yet still now so far about any news tell me give say please jarvis sir ba na yung ang sa ng po ano kumusta
  tapos naba do does did can you your my our that this there`.split(/\s+/))
const topicWords = text => (text.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? []).filter(w => !NOT_TOPIC.has(w))
const sameWord = (a, b) => a === b || (Math.min(a.length, b.length) >= 4 && (a.startsWith(b) || b.startsWith(a)))

export const bankFile = (shared, host, here, exists) => exists(shared) ? `${shared}/${host}/status.jsonl` : `${here}/tmp/status.jsonl`

// The newest line per topic across the machines' files' text.
export function latestLines(files, now = Date.now()) {
  const latest = new Map()
  for (const text of files) {
    for (const line of text.split('\n')) {
      let e
      try { e = JSON.parse(line) } catch { continue }
      const at = Date.parse(e.at)
      if (!e.topic || !e.text || !at || now - at > BANK_HOURS * 3600_000) continue
      if (!latest.has(e.topic) || latest.get(e.topic).at < at) latest.set(e.topic, { ...e, at })
    }
  }
  return [...latest.values()]
}

// The line this question is about: a word of its topic, or two of its words. Otherwise none, and the orch answers.
export function matchLine(lines, said) {
  const asked = topicWords(said)
  let best = null, bestScore = 0
  for (const e of lines) {
    const hit = list => list.filter(w => asked.some(a => sameWord(a, w))).length
    const inTopic = hit(topicWords(e.topic)), score = inTopic * 2 + hit(topicWords(e.text))
    if ((inTopic || score >= 2) && (score > bestScore || (score === bestScore && e.at > best.at))) [best, bestScore] = [e, score]
  }
  return best
}

// Every age it can say, so they can all be rendered ahead.
const AGE_STEPS = [[2, 'two minutes'], [3, 'three minutes'], [5, 'five minutes'], [10, 'ten minutes'], [15, 'fifteen minutes'],
  [20, 'twenty minutes'], [30, 'thirty minutes'], [45, 'forty-five minutes'], [60, 'an hour'], [120, 'two hours'], [180, 'three hours'],
  [360, 'six hours']]
const JUST_NOW = 'As of just now.', ONE_MINUTE = 'As of a minute ago.'
export const AGES = [JUST_NOW, ONE_MINUTE, ...AGE_STEPS.map(([, w]) => `As of ${w} ago.`)]
export function ageWords(ms) {
  const minutes = ms / 60_000
  if (minutes < 1) return JUST_NOW
  if (minutes < 2) return ONE_MINUTE
  return `As of ${AGE_STEPS.filter(([m]) => m <= minutes).at(-1)[1]} ago.`
}

// Said the moment real work goes to the orch. Each is rendered once and kept, so it plays at once.
export const ACKS = ['On it.', 'Got it.', 'On it now.', 'Working on it.', 'Sure, on it.', 'Right away.', 'Leave it with me.',
  'One moment.', 'Will do.', 'Sure thing.', 'Okay, working on it.', 'Coming right up.', 'Let me handle that.', 'Okay, on it.',
  'Give me a moment.', 'Let me check.', 'Starting now.', 'Okay, give me a sec.', 'Right, on it.', 'Already on it.']

// `recent` plus a line from `pool` that isn't among the last half of them, so it doesn't sound canned; the line is last.
export function fresh(pool, recent, random = Math.random) {
  const left = pool.filter(a => !recent.includes(a))
  const line = left[Math.floor(random() * left.length)] ?? pool[0]
  return [...recent, line].slice(-Math.max(1, Math.floor(pool.length / 2)))
}
