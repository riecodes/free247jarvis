// When the voice may interrupt: which listener command a boss reply goes out as, and what asks for a held line.
const FRESH = 90_000 // a reply this soon after the request: the user is waiting for it, even in a call

// listen: the line opens the follow-up window. `end` is say without it; an older line without it is simply a tell,
// since the wake word's wait for a reply (REPLY_WAIT) has run out by then. A question nobody prompted is a late too:
// the user can answer it without the wake word, unless a call is on.
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
