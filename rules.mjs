// When the voice may interrupt: which listener command a boss reply goes out as, and what asks for a held line.
const FRESH = 90_000 // a reply this soon after the request: the user is waiting for it, even in a call
const ASKED = 15 * 60_000 // later than this it is no longer the answer to that request

export function verbFor(askedAt, now = Date.now()) {
  if (!askedAt || now - askedAt > ASKED) return 'tell'
  return now - askedAt > FRESH ? 'late' : 'say'
}

// Short on purpose: "what's the update on the dentaria deploy?" is a request for the boss, not for the held line.
export function asksForHeld(text) {
  const said = text.toLowerCase().replace(/[^\w\s']/g, '').trim()
  return said.split(/\s+/).length <= 6 &&
    (/\b(what|what's|whats|ano|anong|give|tell|read|sabihin)\b.*\b(update|updates|message|balita)\b/.test(said) ||
      /^(the )?updates?$|^go ahead$|^what is it$|^what was that$|^ano (yun|yon|iyon)$/.test(said))
}
