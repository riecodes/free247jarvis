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
