// Runs voice.mjs on a spare port with its mic closed and checks what the window gets. No sound, no mic, no boss.
// node check_window.mjs
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import assert from 'node:assert'

const PORT = 8797
const HERE = fileURLToPath(new URL('.', import.meta.url))
const voice = spawn('node', ['voice.mjs'], {
  cwd: HERE, stdio: ['pipe', 'ignore', 'ignore'],
  env: { ...process.env, VOICE_PORT: String(PORT), VOICE_MIC: 'off', VOICE_WINDOW: 'off' },
})
const url = path => `http://127.0.0.1:${PORT}${path}`

try {
  for (let i = 0; ; i++) {
    try { await fetch(url('/')); break } catch (e) {
      if (i > 50) throw e
      await new Promise(r => setTimeout(r, 200))
    }
  }

  const page = await fetch(url('/window'))
  assert.match(page.headers.get('content-type'), /text\/html/)
  assert.match(await page.text(), /EventSource\('\/events'\)/)

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
  console.log('ok')
} finally {
  voice.stdin.end()
  voice.kill()
}
