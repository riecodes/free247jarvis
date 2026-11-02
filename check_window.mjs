// Runs voice.mjs on a spare port and checks what the window gets. A stub stands in for the listener, so there is no
// sound and no mic, and nothing reaches the live voice or its log.
// node check_window.mjs
import { spawn, spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { hostname } from 'node:os'
import { join } from 'node:path'
import { createInterface } from 'node:readline'
import { fileURLToPath } from 'node:url'
import assert from 'node:assert'
import { AGES, ageWords, latestLines, matchLine, shortlist, withFacts } from './rules.mjs'

// Placeholders fill from live values, the live values come along marked newer, and an unknown one stays for the guard.
const known = withFacts('{price} lang, {nope}', { price: '₱499' })
assert(known.startsWith('₱499 lang, {nope}') && known.includes('price: ₱499') && known.includes('newer'), known)
assert.strictEqual(withFacts('{price} lang', {}), '{price} lang')

// Notes that fit all go, as they are. Past that: those that share words with the question, then what they link to.
const small = [{ name: 'a', text: 'one' }, { name: 'b', text: 'two' }]
assert.strictEqual(shortlist(small, 'anything'), 'one\n\ntwo')
const big = [
  { name: 'refund', text: 'Refunds in 7 days. See [[Payment methods]].' }, { name: 'Payment methods', text: 'GCash.' },
  { name: 'filler', text: 'x'.repeat(30) }, { name: 'huge refund', text: 'refund '.repeat(10) },
]
const picked = shortlist(big, 'what is the refund policy', 60)
assert(picked.includes('Refunds in 7 days') && picked.includes('GCash') && !picked.includes('xxx') && !picked.includes('refund refund'), picked)
assert.strictEqual(shortlist(big, 'nothing matches this', 60), '')

// The status bank: the newest line per topic across both machines' files, old ones out, and bad lines skipped.
const at = ago => new Date(Date.now() - ago * 60_000).toISOString()
const row = (topic, text, ago, waiting = false) => JSON.stringify({ topic, text, at: at(ago), waiting })
const lines = latestLines([`${row('vlog', 'Old vlog line.', 30)}\nnot json\n${row('course', 'The course tests pass.', 5)}`, `${row('vlog', 'The vlog is rendering.', 2)}\n${row('ancient', 'Too old.', 13 * 60)}`])
assert.deepStrictEqual(lines.map(e => e.text).sort(), ['The course tests pass.', 'The vlog is rendering.'])
assert.strictEqual(matchLine(lines, "How's the vlog going?")?.topic, 'vlog')
assert.strictEqual(matchLine(lines, 'tapos na ba yung vlogs')?.topic, 'vlog')
assert.strictEqual(matchLine(lines, "what's the status of the course")?.topic, 'course')
for (const none of ['status', "what's the status?", 'how is the webinar going', 'are the tests fine']) assert.strictEqual(matchLine(lines, none), null, none)
for (const [m, words] of [[0, 'As of just now.'], [1.5, 'As of a minute ago.'], [2.5, 'As of two minutes ago.'], [9, 'As of five minutes ago.'], [70, 'As of an hour ago.'], [700, 'As of six hours ago.']]) {
  assert.strictEqual(ageWords(m * 60_000), words)
  assert(AGES.includes(words), words)
}

const PORT = 8797
const HERE = fileURLToPath(new URL('.', import.meta.url))
const TMP = join(HERE, 'tmp', 'check')
mkdirSync(TMP, { recursive: true })
const STUB = join(TMP, 'stub.py'), STARTS = join(TMP, 'starts.txt'), LOG = join(TMP, 'voice.log')
rmSync(STARTS, { force: true })
// The mic's name, then more events than the replay holds: a window that opens later must still get the name.
writeFileSync(STUB, `import sys\nopen(${JSON.stringify(STARTS)}, "a").write("x")\nprint('{"event":"state","on":true,"mic":"Test Mic"}', flush=True)
for _ in range(250):\n    print('{"event":"peak","word":"x","score":0.1,"level":1}', flush=True)
print('{"event":"caption","text":"No window yet"}', flush=True)
watching = 0
for line in sys.stdin:
    watching += line.strip() == "watch on"
    if line.strip() == "watch on" and watching == 2:
        print('{"event":"caption","text":"Plain note"}', flush=True)
        print('{"event":"caption","text":"Are you there","looking":true}', flush=True)
        print('{"event":"caption","text":"Needs you","remind":true}', flush=True)
`)
const before = readFileSync(join(HERE, 'tmp', 'voice.log'), 'utf8').length
const CLAIMS = join(TMP, 'claims'), ENV_COPY = join(TMP, 'env')
writeFileSync(ENV_COPY, 'GROQ_API_KEY=secret\r\nGREETING=\r\n# a comment\r\n')
rmSync(CLAIMS, { recursive: true, force: true })
mkdirSync(CLAIMS)
const start = (port = PORT, mic = 'off', stdout = 'ignore') => spawn('node', ['voice.mjs'], {
  cwd: HERE, stdio: ['pipe', stdout, 'ignore'],
  env: { ...process.env, VOICE_PORT: String(port), VOICE_MIC: mic, VOICE_WINDOW: 'off', VOICE_LISTENER: STUB, VOICE_LOG: LOG, VOICE_TOAST: 'off', VOICE_SHARED: CLAIMS, VOICE_ENV: ENV_COPY },
})
const voice = start()
let second, third
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
  assert(sent.some(e => e.event === 'state' && e.mic === 'Test Mic'), 'the mic name was lost from the replay')

  // Notes go in the window. A notification only with no window open, for "are you there", or for a line that needs them.
  await until('Are you there')
  const toasts = () => readFileSync(LOG, 'utf8').split('\n').filter(l => / toast: /.test(l)).map(l => l.split(' toast: ')[1])
  for (let i = 0; i < 25 && !toasts().includes('Needs you'); i++) await sleep(100)
  assert.deepStrictEqual(toasts().slice(-3), ['No window yet', 'Are you there', 'Needs you'], toasts().join('|'))
  assert(seen.includes('Plain note'), 'a note must reach the window')
  await sleep(100)
  assert(!seen.includes('Needs you'), 'a reminder is already in the window as the reply')
  assert.match(html, /id="mic"/)
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
  const micFrom = host => new Promise((resolve, reject) => {
    import('node:http').then(({ get }) => get(url('/mic'), { headers: { Host: host } }, r => {
      let b = ''
      r.on('data', d => (b += d))
      r.on('end', () => resolve(b))
    }).on('error', reject))
  })
  assert.strictEqual(await micFrom('evil.example'), 'ok')
  assert.strictEqual(await micFrom(`127.0.0.1:${PORT}`), 'off')

  // A web page can't post to the boss: a browser adds an Origin to every POST, and another Host is refused too.
  const { request } = await import('node:http')
  const post = (path, headers) => new Promise((resolve, reject) => {
    request(url(path), { method: 'POST', headers }, r => { r.resume(); resolve(r.statusCode) })
      .on('error', reject).end('page')
  })
  for (const path of ['/', '/heard', '/mic']) {
    assert.strictEqual(await post(path, { Origin: 'https://evil.example' }), 403, path)
    assert.strictEqual(await post(path, { Origin: 'null' }), 403, path)
    assert.strictEqual(await post(path, { Host: 'evil.example' }), 403, path)
  }
  assert.strictEqual(await post('/', { Origin: `http://127.0.0.1:${PORT}` }), 200)

  // Settings: listed with their values and never a key, saved in .env beside its other lines, and refused from a web page.
  const settings = await (await fetch(url('/settings'))).json()
  assert(settings.some(s => s.key === 'GREETING' && s.value === 'on') && !JSON.stringify(settings).includes('secret'))
  const setting = (key, value, headers = {}) => fetch(url('/settings'), { method: 'POST', headers, body: JSON.stringify({ key, value }) }).then(r => r.status)
  assert.strictEqual(await setting('GREETING', 'off'), 200)
  assert.strictEqual(await setting('FOLLOWUP_SECONDS', '20'), 200)
  assert.strictEqual(await setting('GROQ_API_KEY', 'stolen'), 400)
  assert.strictEqual(await setting('GREETING', 'off\nGROQ_API_KEY=stolen'), 400)
  assert.strictEqual(await setting('FOLLOWUP_SECONDS', '-1'), 400)
  assert.strictEqual(await post('/settings', { Origin: 'https://evil.example' }), 403)
  assert.strictEqual(readFileSync(ENV_COPY, 'utf8'), 'GROQ_API_KEY=secret\r\nGREETING=off\r\n# a comment\r\nFOLLOWUP_SECONDS=20\r\n')
  assert((await (await fetch(url('/settings'))).json()).some(s => s.key === 'GREETING' && s.value === 'off'))
  assert.match(html, /id="panel"/)

  // This check's lines stay out of the live log.
  const live = readFileSync(join(HERE, 'tmp', 'voice.log'), 'utf8').slice(before)
  assert(!/heard \(http\): (first|second)/.test(live), 'check lines reached the live log')
  assert(readFileSync(LOG, 'utf8').includes('heard (http): first'))

  // The router, end to end with a stand-in Jev: progress finds the worker's line, from either machine, with its age; a topic
  // with no line, or a plain status, doesn't use the bank. Lines and ages are rendered ahead, and what waits is passed on.
  const { createServer } = await import('node:http')
  let jevSays = 'progress'
  const jev = createServer((req, res) => {
    req.resume()
    req.on('end', () => res.end(JSON.stringify({ answers: { kind: { choice: jevSays, probabilities: { [jevSays]: 0.95 } } } })))
  }).listen(0, '127.0.0.1')
  await new Promise(r => jev.once('listening', r))
  const BANK = join(TMP, 'bankclaims'), IN = join(TMP, 'bank.in')
  rmSync(BANK, { recursive: true, force: true })
  mkdirSync(join(BANK, 'OtherPC'), { recursive: true })
  rmSync(IN, { force: true })
  writeFileSync(join(BANK, 'OtherPC', 'status.jsonl'), `${row('vlog', 'The vlog is rendering.', 2.5)}\n`)
  const STUB2 = join(TMP, 'stub2.py')
  writeFileSync(STUB2, `import sys\nfor line in sys.stdin:\n    open(${JSON.stringify(IN)}, "a", encoding="utf-8").write(line)\n`)
  const port3 = PORT + 2
  const router = spawn('node', ['voice.mjs'], {
    cwd: HERE, stdio: ['pipe', 'ignore', 'ignore'],
    env: { ...process.env, VOICE_PORT: String(port3), VOICE_MIC: 'off', VOICE_WINDOW: 'off', VOICE_LISTENER: STUB2, VOICE_LOG: LOG, VOICE_TOAST: 'off',
      VOICE_SHARED: BANK, VOICE_ENV: ENV_COPY, VOICE_JEV_URL: `http://127.0.0.1:${jev.address().port}/`, TYPESAFE_API_KEY: 'stand-in', VOICE_TITLE: 'Sir' },
  })
  const heard = async text => {
    for (let i = 0; i < 50; i++) {
      try { return await fetch(`http://127.0.0.1:${port3}/heard`, { method: 'POST', body: text }) } catch { await sleep(200) }
    }
    throw new Error('no router')
  }
  const toListener = () => existsSync(IN) ? readFileSync(IN, 'utf8') : ''
  try {
    await heard('how is the vlog going')
    for (let i = 0; i < 40 && !/As of/.test(toListener().replace(/bank .*\n/g, '')); i++) await sleep(100)
    assert.match(toListener(), /^end Sir, the vlog is rendering\. As of two minutes ago\.$/m, toListener())
    assert.match(toListener(), /^bank Sir, the vlog is rendering\.$/m)
    assert.match(toListener(), /^bank As of forty-five minutes ago\.$/m)
    // Your own machine's line, marked waiting, arrives within a few seconds, ready to follow a greeting.
    assert.strictEqual(spawnSync('node', ['progress.mjs', '--waiting', 'draft', 'The draft is ready'], { cwd: HERE, env: { ...process.env, VOICE_SHARED: BANK } }).status, 0)
    for (let i = 0; i < 70 && !/^waiting /m.test(toListener()); i++) await sleep(100)
    assert.match(toListener(), /^waiting \["Sir, the draft is ready\."\]$/m, toListener())
    assert.match(toListener(), /^bank Sir, the draft is ready\.$/m)
    const before2 = toListener().length
    await heard('how is the webinar going')  // nothing on it: the orch
    await sleep(300)
    assert(!/^(end|say) /m.test(toListener().slice(before2)), toListener().slice(before2))
    jevSays = 'status'
    await heard("what's the status")  // no topic: the sessions' own summary as before
    await sleep(300)
    assert(!/vlog/.test(toListener().slice(before2).replace(/^bank .*$/gm, '')), toListener().slice(before2))
  } finally {
    router.stdin.end()
    router.kill()
    jev.close()
  }

  // One voice across two PCs. The latest claim holds it, and an old one still counts: a PC booting late must not speak.
  const claimBy = (host, when) => {
    mkdirSync(join(CLAIMS, host), { recursive: true })
    writeFileSync(join(CLAIMS, host, 'jarvis.json'), JSON.stringify({ claimed: new Date(when).toISOString() }))
  }
  const mine = join(CLAIMS, hostname(), 'jarvis.json')
  const port2 = PORT + 1
  const micState = async () => (await fetch(`http://127.0.0.1:${port2}/mic`)).text()
  const up = async () => {
    for (let i = 0; i < 50; i++) { try { return await micState() } catch { await sleep(200) } }
    throw new Error('no voice')
  }
  const stop = async () => {
    third.stdin.end()
    third.kill()
    await sleep(500)
  }
  // Nobody has claimed it: on, and this PC holds it now.
  third = start(port2, '')
  assert.strictEqual(await up(), 'on')
  assert(existsSync(mine), 'the first voice to start claims it')
  await stop()
  // Held elsewhere, days ago: starts closed and says nothing, by the reply tool or the router.
  rmSync(mine)
  claimBy('OtherPC', Date.now() - 5 * 86400_000)
  third = start(port2, '', 'pipe')
  assert.strictEqual(await up(), 'off')
  assert(!existsSync(mine), 'starting must not take the voice from the other PC')
  const replies = createInterface({ input: third.stdout })[Symbol.asyncIterator]()
  const rpc = async (id, method, params) => {
    third.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n')
    return JSON.parse((await replies.next()).value)
  }
  await rpc(1, 'initialize', { protocolVersion: '2025-03-26', capabilities: {}, clientInfo: { name: 'check', version: '1' } })
  const said = await rpc(2, 'tools/call', { name: 'reply', arguments: { text: 'ghost line' } })
  assert.match(said.result.content[0].text, /Not spoken: Jarvis is on OtherPC/)
  assert(!readFileSync(LOG, 'utf8').includes('reply: ghost line'))
  // "jarvis on" here moves it, even with the other PC's clock ahead; then the other PC taking it back closes the mic.
  claimBy('OtherPC', Date.now() + 60_000)
  await fetch(`http://127.0.0.1:${port2}/mic`, { method: 'POST', body: 'on' })
  assert.strictEqual(await micState(), 'on')
  assert(Date.parse(JSON.parse(readFileSync(mine, 'utf8')).claimed) > Date.now() + 59_000)
  await sleep(3500)
  assert.strictEqual(await micState(), 'on', 'its own claim keeps it')
  claimBy('OtherPC', Date.now() + 120_000)
  for (let i = 0; i < 40 && (await micState()) === 'on'; i++) await sleep(100)
  assert.strictEqual(await micState(), 'off', 'the other PC took it, so this mic closes')
  await stop()
  // Holding the latest claim, it starts on as always, without claiming again.
  const before2 = readFileSync(mine, 'utf8')
  claimBy('OtherPC', Date.now() - 86400_000)
  third = start(port2, '')
  assert.strictEqual(await up(), 'on')
  assert.strictEqual(readFileSync(mine, 'utf8'), before2)
  console.log('ok')
} finally {
  second?.kill()
  third?.kill()
  voice.stdin.end()
  voice.kill()
}
