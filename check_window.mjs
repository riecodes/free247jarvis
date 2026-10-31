// Runs voice.mjs on a spare port and checks what the window gets. A stub stands in for the listener, so there is no
// sound and no mic, and nothing reaches the live voice or its log.
// node check_window.mjs
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import assert from 'node:assert'
import { withFacts } from './rules.mjs'

// Placeholders fill from live values, the live values come along marked newer, and an unknown one stays for the guard.
const known = withFacts('{price} lang, {nope}', { price: '₱499' })
assert(known.startsWith('₱499 lang, {nope}') && known.includes('price: ₱499') && known.includes('newer'), known)
assert.strictEqual(withFacts('{price} lang', {}), '{price} lang')

const PORT = 8797
const HERE = fileURLToPath(new URL('.', import.meta.url))
const TMP = join(HERE, 'tmp', 'check')
mkdirSync(TMP, { recursive: true })
const STUB = join(TMP, 'stub.py'), STARTS = join(TMP, 'starts.txt'), LOG = join(TMP, 'voice.log')
rmSync(STARTS, { force: true })
writeFileSync(STUB, `import sys\nopen(${JSON.stringify(STARTS)}, "a").write("x")\nfor _ in sys.stdin:\n    pass\n`)
const before = readFileSync(join(HERE, 'tmp', 'voice.log'), 'utf8').length
const start = () => spawn('node', ['voice.mjs'], {
  cwd: HERE, stdio: ['pipe', 'ignore', 'ignore'],
  env: { ...process.env, VOICE_PORT: String(PORT), VOICE_MIC: 'off', VOICE_WINDOW: 'off', VOICE_LISTENER: STUB, VOICE_LOG: LOG },
})
const voice = start()
let second
const url = path => `http://127.0.0.1:${PORT}${path}`
const sleep = ms => new Promise(r => setTimeout(r, ms))

try {
  for (let i = 0; ; i++) {
    try { await fetch(url('/')); break } catch (e) {
      if (i > 50) throw e
      await sleep(200)
    }
  }
  for (let i = 0; i < 25 && !existsSync(STARTS); i++) await sleep(200)

  // A second voice on the same port starts no ears: two would talk over each other.
  second = start()
  await sleep(2500)
  assert.strictEqual(readFileSync(STARTS, 'utf8'), 'x', 'a second voice started its own listener')
  second.stdin.end()
  second.kill()

  const page = await fetch(url('/window'))
  assert.match(page.headers.get('content-type'), /text\/html/)
  const html = await page.text()
  assert.match(html, /EventSource\('\/events'\)/)
  assert(!/<audio|new Audio|AudioContext|speechSynthesis/.test(html), 'the window must never make a sound')

  // With nothing to replay yet, the stream still opens at once (it hung here until the first event).
  const empty = await fetch(url('/events'), { signal: AbortSignal.timeout(3000) })
  assert.match(empty.headers.get('content-type'), /text\/event-stream/)
  await empty.body.cancel()

  // A typed request is passed on, and a watcher that connects later still gets it, then new ones as they come.
  await fetch(url('/'), { method: 'POST', body: 'first' })
  const events = await fetch(url('/events'))
  assert.match(events.headers.get('content-type'), /text\/event-stream/)
  const reader = events.body.getReader()
  let seen = ''
  const until = async word => {
    const stop = Date.now() + 5000
    while (!seen.includes(word)) {
      assert(Date.now() < stop, `no ${word} in ${seen}`)
      seen += new TextDecoder().decode((await reader.read()).value)
    }
  }
  await until('"first"')
  await fetch(url('/'), { method: 'POST', body: 'second' })
  await until('"second"')
  const sent = seen.split('\n').filter(l => l.startsWith('data: ')).map(l => JSON.parse(l.slice(6)))
  assert(sent.some(e => e.event === 'sent' && e.text === 'first' && e.via === 'http'), seen)
  reader.cancel()

  // Another Host: a web page pointing its own domain at this machine gets neither the page nor the events.
  const raw = await new Promise((resolve, reject) => {
    import('node:http').then(({ get }) => get(url('/events'), { headers: { Host: 'evil.example' } }, r => {
      let b = ''
      r.on('data', d => (b += d))
      r.on('end', () => resolve(b))
    }).on('error', reject))
  })
  assert.strictEqual(raw, 'ok')

  // This check's lines stay out of the live log.
  const live = readFileSync(join(HERE, 'tmp', 'voice.log'), 'utf8').slice(before)
  assert(!/heard \(http\): (first|second)/.test(live), 'check lines reached the live log')
  assert(readFileSync(LOG, 'utf8').includes('heard (http): first'))
  console.log('ok')
} finally {
  second?.kill()
  voice.stdin.end()
  voice.kill()
}
