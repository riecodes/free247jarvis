// When the voice may interrupt: which listener command a boss reply goes out as, and what asks for a held line.
const FRESH = 90_000 // a reply this soon after the request: the user is waiting for it, even in a call

// listen: the line opens the follow-up window. `end` is say without it; an older line without it is simply a tell,
// since the wake word's wait for a reply (REPLY_WAIT) has run out by then. A question nobody prompted is a late too:
// the user can answer it without the wake word, unless a call is on.
export function verbFor(askedAt, listen = true, now = Date.now()) {
  if (askedAt && now - askedAt <= FRESH) return listen ? 'say' : 'end'
  return listen ? 'late' : 'tell'
}

// By default only a line that asks something opens the window: an acknowledgment ends the exchange.
export const asksSomething = text => /\?|\b(say|pick|choose|tell me)\b/i.test(text)

// Short on purpose: "what's the update on the dentaria deploy?" is a request for the boss, not for the held line.
export function asksForHeld(text) {
  const said = text.toLowerCase().replace(/[^\w\s']/g, '').trim()
  return said.split(/\s+/).length <= 6 &&
    (/\b(what|what's|whats|ano|anong|give|tell|read|sabihin)\b.*\b(update|updates|message|balita)\b/.test(said) ||
      /^(the )?updates?$|^go ahead$|^what is it$|^what was that$|^ano (yun|yon|iyon)$/.test(said))
}
