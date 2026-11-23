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
import { AGES, ageWords, asksYesNo, yesNoLead, isFiller, latestLines, leadFor, matchLine, shortlist, withFacts, withTitle } from './rules.mjs'

for (const said of ['Hmm.', 'Mm-hmm.', 'Okay', 'Damn', 'Got it.']) assert(isFiller(said), said)
for (const said of ['Yes', 'Go', 'Okay, send it', 'What?', 'Hello']) assert(!isFiller(said), said)

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
for (const yes of ["Have you completed the Dentaria? That's a question.", 'is the vlog done', 'So, did the course tests pass?', 'Jarvis, are the tests fine'])
  assert(asksYesNo(yes), yes)
for (const how of ["How's the vlog going?", "what's the status of the course", 'tapos na ba yung vlogs', "So what's your answer on have you completed it"])
  assert(!asksYesNo(how), how)
// A yes or no to the status leads with the answer to what it asks (2026-11-12: "eating tokens?" got only the counts).
const tokens = 'Do I have, do you have any pending that needs my confirm and is eating tokens? No.'
assert.strictEqual(yesNoLead(tokens, 0, 2), 'No, nothing is running')
assert.strictEqual(yesNoLead(tokens, 1, 0), 'Yes')
assert.strictEqual(yesNoLead('is anything waiting on me', 3, 0), 'No, nothing is waiting on you')
assert.strictEqual(yesNoLead('do I have anything pending', 0, 1), 'Yes')
assert.strictEqual(yesNoLead("what's pending", 0, 1), '')
for (const [m, words] of [[0, 'As of just now.'], [1.5, 'As of a minute ago.'], [2.5, 'As of two minutes ago.'], [9, 'As of five minutes ago.'], [70, 'As of an hour ago.'], [700, 'As of six hours ago.']]) {
  assert.strictEqual(ageWords(m * 60_000), words)
  assert(AGES.includes(words), words)
}

// "Sir" once, at the start or the end, the same each time for the same words, and never twice.
const sirs = ['Done.', 'The vlog is rendering.', 'Should I ship it?', "I'm with you.", 'The draft is ready.', 'CPD is green.'].map(t => withTitle(t, 'Sir'))
assert(sirs.some(t => t.startsWith('Sir, ')) && sirs.some(t => t.endsWith(', sir.')) && sirs.every(t => (t.match(/sir/gi) ?? []).length === 1), sirs.join(' | '))
assert(sirs.includes('Should I ship it, sir?') || sirs.includes('Sir, should I ship it?'))
assert(!sirs.some(t => /Sir, i'm|Sir, cPD/.test(t)), sirs.join(' | '))
for (const t of ['Sir, done.', 'Done, sir.', 'Yes sir, it works.']) assert.strictEqual(withTitle(t, 'Sir'), t)
assert.strictEqual(withTitle('Done.', ''), 'Done.')
assert.strictEqual(withTitle('The vlog is rendering.', 'Sir'), withTitle('The vlog is rendering.', 'Sir'))

const PORT = Number(process.env.CHECK_PORT) || 8797  // CHECK_PORT: another app holds 8797 to 8799 (a wrangler dev server)
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
  assert(!/innerHTML/.test(html), 'words from speech and other sessions never go in as HTML')

  // How the window lays out a message, and keeps live words past the 15 s each batch covers.
  const [, format] = html.match(/\/\/ format:start[^\n]*\n([\s\S]*?)\/\/ format:end/)
  const { stitch, parse, spokenChoices, asks, yesNo } = new Function(`${format}; return { stitch, parse, spokenChoices, asks, yesNo }`)()
  assert.strictEqual(stitch('', 'one two'), 'one two')
  assert.strictEqual(stitch('one two three four five', 'three four five six seven'), 'one two three four five six seven')
  assert.strictEqual(stitch('tell the course session to', 'The course session, to fix it'), 'tell the course session to fix it')
  assert.strictEqual(stitch('one two three', 'two three'), 'one two three')  // nothing new: nothing lost
  assert.strictEqual(stitch('one two', 'nine ten eleven'), 'one two nine ten eleven')
  let grown = ''
  const speech = Array.from({ length: 400 }, (_, i) => `w${i}`)
  for (let end = 40; end <= 400; end += 13) grown = stitch(grown, speech.slice(Math.max(0, end - 40), end).join(' '))
  grown = stitch(grown, speech.slice(-40).join(' '))
  assert.strictEqual(grown.split(' ').length, 400, 'a long request keeps all its words')

  const rows = spokenChoices('Ship it now? A yes, or B not yet.')
  assert.deepStrictEqual(rows, { intro: 'Ship it now?', items: [{ h: 'A', text: 'yes' }, { h: 'B', text: 'not yet.' }] })
  assert.strictEqual(spokenChoices('Sir, one of them: A, B, or C?'), null)
  assert.strictEqual(spokenChoices('A fix is ready and the B side passed.')?.items.length ?? 0, 2)  // ponytail: reads as choices; display only, nothing spoken changes
  assert.strictEqual(spokenChoices('Plan A failed, so plan B it is.'), null)
  assert.strictEqual(spokenChoices('Nothing to choose here.'), null)
  assert.deepStrictEqual(parse('Pick one:\nA. Ship\nB. Wait\n\nC. Drop').map(b => b.t), ['p', 'choices'])
  assert.strictEqual(parse('Pick one:\nA. Ship\nB. Wait\n\nC. Drop')[1].items.length, 3)
  assert.deepStrictEqual(parse('A. Alone').map(b => b.t), ['p'])
  assert.deepStrictEqual(parse('One\n\nTwo\n- a\n- b\n1. c\n```\nx | y\n```\n| h | i |\n|---|---|\n| 1 | 2 |\n# Head').map(b => b.t),
    ['p', 'p', 'ul', 'ol', 'code', 'table', 'h'])
  assert.deepStrictEqual(parse('| h | i |\n|---|---|\n| 1 | 2 |')[0].rows, [['h', 'i'], ['1', '2']])
  // Buttons: only on a reply that asks; Yes and No for a plain yes-or-no question as its last sentence.
  assert(asks('Ship it now? A yes, or B not yet.') && asks('Say A or B.') && !asks('A fix is ready and the B side passed.'))
  for (const q of ['Sir, should I ship it?', 'Done. Do you want the PDF too?', 'Is that okay?']) assert(yesNo(q), q)
  for (const q of ['Ship it or wait?', 'Which one?', 'It shipped.', 'Should I ship it? It is ready.']) assert(!yesNo(q), q)

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
  for (const path of ['/', '/heard', '/choice', '/resend-last', '/window', '/mic']) {
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
  // The mic and output pickers: this machine's devices, freshly listed, and only a name or '' (Windows default) is saved.
  const devs = (await (await fetch(url('/settings'))).json()).filter(s => s.device)
  assert.deepStrictEqual(devs.map(s => [s.key, s.value, Array.isArray(s.choices)]), [['MIC_DEVICE', '', true], ['OUTPUT_DEVICE', '', true]])
  assert.strictEqual(await setting('OUTPUT_DEVICE', 'Speakers (Realtek(R) Audio)'), 200)
  assert.strictEqual(await setting('OUTPUT_DEVICE', 'A $& B'), 200)  // saved as typed, not read as a replace pattern
  assert(readFileSync(ENV_COPY, 'utf8').includes('OUTPUT_DEVICE=A $& B\r\n'))
  assert.strictEqual(await setting('OUTPUT_DEVICE', 'Speakers (Realtek(R) Audio)'), 200)
  assert.strictEqual(await setting('MIC_DEVICE', ''), 200)
  assert.strictEqual(await setting('MIC_DEVICE', 'x\nGROQ_API_KEY'), 400)
  assert.strictEqual(await setting('MIC_DEVICE', '-3'), 400)  // an old window's number box
  assert.strictEqual(await setting('MIC_DEVICE', 7), 400)
  assert(readFileSync(ENV_COPY, 'utf8').endsWith('FOLLOWUP_SECONDS=20\r\nOUTPUT_DEVICE=Speakers (Realtek(R) Audio)\r\nMIC_DEVICE=\r\n'))
  assert.match(html, /id="panel"/)

  // This check's lines stay out of the live log.
  const live = readFileSync(join(HERE, 'tmp', 'voice.log'), 'utf8').slice(before)
  assert(!/heard \(http\): (first|second)/.test(live), 'check lines reached the live log')
  assert(readFileSync(LOG, 'utf8').includes('heard (http): first'))

  // The router, end to end with a stand-in Jev: progress finds the worker's line, from either machine, with its age; a topic
  // with no line, or a plain status, doesn't use the bank. Lines and ages are rendered ahead, and what waits is passed on.
  const { createServer } = await import('node:http')
  let jevSays = 'progress', haikuCalls = 0, asked = 0  // asked: of Jev or Haiku, either one
  // Also a stand-in Haiku, at /haiku: with the board it knows only "research", and says NOT_IN_NOTES to anything else.
  const jev = createServer((req, res) => {
    let body = ''
    req.on('data', d => { body += d })
    asked++
    if (req.url === '/haiku') haikuCalls++
    req.on('end', () => {
      const ask = req.url === '/haiku' ? JSON.parse(body) : null
      const board = ask?.system.includes('<board>'), research = /research/.test(ask?.messages[0].content ?? '')
      // Room talk: told it may pass on words not said to it, it does.
      const room = !board && ask?.system.includes('NOT_FOR_ME') && /hahaha/i.test(ask?.messages[0].content ?? '')
      res.end(JSON.stringify(ask ? { content: [{ type: 'text', text: room ? 'NOT_FOR_ME' : board && !research ? 'NOT_IN_NOTES' : board ? 'Sir, the research session is idle.' : 'On it, sir.' }] }
        : { answers: { kind: { choice: jevSays, probabilities: { [jevSays]: 0.95 } },
          ...(jevSays === 'chat' && /thanks/.test(JSON.parse(body).state?.heard ?? '') && { canned: { choice: 'thanks', probabilities: { thanks: 0.95 } } }) } }))
    })
  }).listen(0, '127.0.0.1')
  await new Promise(r => jev.once('listening', r))
  const BANK = join(TMP, 'bankclaims'), IN = join(TMP, 'bank.in')
  rmSync(BANK, { recursive: true, force: true })
  mkdirSync(join(BANK, 'OtherPC'), { recursive: true })
  rmSync(IN, { force: true })
  writeFileSync(join(BANK, 'OtherPC', 'status.jsonl'), `${row('vlog', 'The vlog is rendering.', 2.5)}\n`)
  const STUB2 = join(TMP, 'stub2.py')
  // It writes down what the voice tells it; when the mic goes on, it says the rest of a request (FAST_END's `more`).
  writeFileSync(STUB2, `import sys\nfor line in sys.stdin:\n    open(${JSON.stringify(IN)}, "a", encoding="utf-8").write(line)
    if line.strip() == "on":\n        print('{"event":"heard","text":"and tell me when it is live","more":true}', flush=True)\n`)
  const port3 = PORT + 2
  const router = spawn('node', ['voice.mjs'], {
    cwd: HERE, stdio: ['pipe', 'pipe', 'ignore'],
    env: { ...process.env, VOICE_PORT: String(port3), VOICE_MIC: 'off', VOICE_WINDOW: 'off', VOICE_LISTENER: STUB2, VOICE_LOG: LOG, VOICE_TOAST: 'off',
      VOICE_SHARED: BANK, VOICE_ENV: ENV_COPY, VOICE_JEV_URL: `http://127.0.0.1:${jev.address().port}/`, TYPESAFE_API_KEY: 'stand-in', VOICE_TITLE: 'Sir',
      VOICE_HAIKU_URL: `http://127.0.0.1:${jev.address().port}/haiku`, ANTHROPIC_API_KEY: 'stand-in' },
  })
  const heard = async text => {
    for (let i = 0; i < 50; i++) {
      try { return await fetch(`http://127.0.0.1:${port3}/heard`, { method: 'POST', body: text }) } catch { await sleep(200) }
    }
    throw new Error('no router')
  }
  const toListener = () => existsSync(IN) ? readFileSync(IN, 'utf8') : ''
  const toLines = () => toListener().split(/\r?\n/)
  try {
    await heard('how is the vlog going')
    for (let i = 0; i < 40 && !/As of/.test(toListener().replace(/bank .*\n/g, '')); i++) await sleep(100)
    const vlog = withTitle('The vlog is rendering.', 'Sir'), draft = withTitle('The draft is ready.', 'Sir')
    assert(toLines().includes(`ack ${vlog} As of two minutes ago.`), toListener())  // ahead of older news, no window
    assert(toLines().includes(`bank ${vlog}`))
    assert.match(toListener(), /^bank As of forty-five minutes ago\.$/m)
    // Your own machine's line, marked waiting, arrives within a few seconds, ready to follow a greeting.
    assert.strictEqual(spawnSync('node', ['progress.mjs', '--waiting', 'draft', 'The draft is ready'], { cwd: HERE, env: { ...process.env, VOICE_SHARED: BANK } }).status, 0)
    for (let i = 0; i < 70 && !/^waiting /m.test(toListener()); i++) await sleep(100)
    assert(toLines().includes(`waiting ${JSON.stringify([draft])}`), toListener())
    assert(toLines().includes(`bank ${draft}`))
    const before2 = toListener().length
    const sentAt = Date.now()
    await heard('how is the webinar going')  // nothing on it: the orch, and nothing said here, so only the orch replies
    await heard('A')  // an answer goes straight to the orch, also unsaid
    // Asked again: the line didn't answer it. A yes or no: the status line doesn't give one. Both go to the orch, unsaid.
    await heard("so what's the latest on the vlog")
    await heard('Is the draft ready?')
    await sleep(600)
    assert.match(readFileSync(LOG, 'utf8'), /router: bank found vlog, but asked again: the orch answers/)
    assert.match(readFileSync(LOG, 'utf8'), /router: bank found draft, but a yes or no: the orch answers/)
    // Only the webinar asked Haiku, with the board, which didn't settle it: so the orch answers, and nothing is said here.
    assert(!/^(ack|end|say|ask|late|tell) /m.test(toListener().slice(before2)) && haikuCalls === 1, [haikuCalls, toListener().slice(before2)])
    // Each went on to the orch: `routed boss`, so the greeting's reminder doesn't play as if it were the answer.
    assert.strictEqual(toListener().slice(before2).match(/^routed boss$/gm)?.length, 4, toListener().slice(before2))
    assert.match(toListener().slice(0, before2), /^routed$/m)  // the bank answered the first one itself
    assert(Date.now() - sentAt < 2500)
    assert.match(readFileSync(LOG, 'utf8'), /heard \(mic\): how is the webinar going\n.*\n.*router: bank has nothing/)
    jevSays = 'status'
    await heard("what's the status")  // no topic: the sessions' own summary as before, with what waits on the user
    await sleep(300)
    assert(!/vlog/.test(toListener().slice(before2).replace(/^bank .*$/gm, '')), toListener().slice(before2))
    assert(/^ack .*Waiting on you: The draft is ready\b/m.test(toListener().slice(before2)), toListener().slice(before2))
    const before4 = toListener().length
    jevSays = 'progress'
    await heard("what's waiting on me")  // every waiting line, not one topic's
    await sleep(300)
    assert(/^ack .*Waiting on you: The draft is ready\b/m.test(toListener().slice(before4)), toListener().slice(before4))
    // It read the waiting lines: `routed told`, so the greeting's reminder doesn't say one again (2026-11-12, 07:55).
    assert.match(toListener().slice(before4), /^routed told$/m)
    // A session with no line of its own: Haiku answers from the board, without the orch.
    const before6 = toListener().length
    await heard('how is the research going')
    await sleep(300)
    assert.match(toListener().slice(before6), /^ack Sir, the research session is idle\.$/m)
    // Small talk with a set answer: Jev's second question settles it, and Haiku isn't asked.
    const calls = haikuCalls
    jevSays = 'chat'
    await heard('thanks for that')
    await sleep(300)
    assert(/^ack .*you're welcome/im.test(toListener().slice(before6)) && haikuCalls === calls, toListener().slice(before6))
    // Room talk, not said to Jarvis (2026-11-20, 15:42): nothing said, and nothing to the orch.
    const before7 = toListener().length
    await heard('Oh! Hindi ko alam. Secret conversation eh. Hahaha.')
    await sleep(300)
    assert(!/^(ack|ask|say|routed boss)/m.test(toListener().slice(before7)) && /^routed$/m.test(toListener().slice(before7)), toListener().slice(before7))
    assert.match(readFileSync(LOG, 'utf8'), /router: room talk, not said to Jarvis/)
    // A yes or no: the answer first, then the counts. This machine's real sessions, so either answer.
    const before5 = toListener().length
    jevSays = 'status'
    await heard('is anything running')
    await sleep(300)
    assert.match(toListener().slice(before5), /^ack (Sir, )?(yes|no, nothing is running)\. \S+ sessions?: /im)
    // A choice clicked in the window: it closes the listening window, and goes on as if said.
    const r = await fetch(`http://127.0.0.1:${port3}/choice`, { method: 'POST', body: 'A' })
    assert.strictEqual(r.status, 200)
    for (let i = 0; i < 20 && !/^clicked$/m.test(toListener()); i++) await sleep(100)
    assert.match(toListener(), /^clicked$/m)
    assert.match(readFileSync(LOG, 'utf8'), / clicked: A\n/)
    // The last thing said, sent again: the listener has it.
    assert.strictEqual((await fetch(`http://127.0.0.1:${port3}/resend-last`, { method: 'POST' })).status, 200)
    for (let i = 0; i < 20 && !/^resend$/m.test(toListener()); i++) await sleep(100)
    assert.match(toListener(), /^resend$/m)
    // An orch reply that could pass for the answer to a newer request: its re goes along as the lead (after a tab) for the
    // listener to say if the user asks something new first; with a second request already in, it's said with it at once.
    const out = createInterface({ input: router.stdout })[Symbol.asyncIterator]()
    const call = async (id, method, params) => {
      router.stdin.write(`${JSON.stringify({ jsonrpc: '2.0', id, method, params })}\n`)
      for (;;) { const m = JSON.parse((await out.next()).value); if (m.id === id) return m }
    }
    await call(1, 'initialize', { protocolVersion: '2025-03-26', capabilities: {}, clientInfo: { name: 'check', version: '1' } })
    const reply = (id, args) => call(id, 'tools/call', { name: 'reply', arguments: args })
    await reply(2, { text: 'Clearing.', listen: false })
    jevSays = 'work'
    const before8 = toListener().length
    await heard('tell the course session to ship')
    await reply(3, { text: 'Sent it to the course session.', re: 'the course', listen: false })
    await heard('deploy dentease')
    await heard('and the vlog?')
    await reply(4, { text: 'Deployed it.', re: 'dentease.', listen: false })
    await heard('one more')
    await heard('and another')
    const unnamed = await reply(5, { text: 'Done.', listen: false })
    await reply(6, { text: 'About the vlog: it renders.', re: 'the vlog', listen: false })
    await sleep(200)
    const said8 = toListener().slice(before8).split(/\r?\n/).filter(l => /^(end|tell) /.test(l))
    assert.match(said8[0], /^end [^\t]*course session[^\t]*\tAbout the course:$/, said8.join(' | '))  // one request in: the lead goes along
    assert.match(said8[1], /^end About dentease: [^\t]*deployed it[^\t]*$/i, said8.join(' | '))  // a second came in first: said at once
    assert.match(said8[2], /^end Done[^\t]*\tAbout your earlier request:$/, said8.join(' | '))  // two in, no topic: only if needed
    assert.match(unnamed.result.content[0].text, /pass re/)
    assert.match(said8[3], /^tell About the vlog: it renders[^\t]*$/, said8.join(' | '))  // it named its topic itself
    // FAST_END: a request went out as soon as its words were whole, and the user went on. The rest (more) skips the
    // router, where half a sentence could pass for room talk, and reaches the orch with the first part beside it.
    await heard('deploy the course site')
    const asked9 = asked
    await fetch(`http://127.0.0.1:${port3}/mic`, { method: 'POST', body: 'on' })
    const rest = (async () => {
      for (;;) {
        const m = JSON.parse((await out.next()).value)
        if (m.method === 'notifications/claude/channel' && /went on after a pause/.test(m.params.content)) return m.params.content
      }
    })()
    const got = await Promise.race([rest, sleep(5000).then(() => '')])
    assert.match(got, /just before, "deploy the course site", was taken as a whole request then[^)]*\) and tell me when it is live\n/, got)
    assert.strictEqual(asked, asked9, 'the rest of a request is not sorted again')
  } finally {
    router.stdin.end()
    router.kill()
    jev.close()
  }

  // The lead an orch reply may open with: its topic, else what it is; none when it names its topic itself.
  assert.strictEqual(leadFor('Noted, sir.', 'the MacBook ideas'), 'About the MacBook ideas:')
  assert.strictEqual(leadFor('Noted, sir.', 'dentease. '), 'About dentease:')
  assert.strictEqual(leadFor('Noted, sir.'), 'About your earlier request:')
  assert.strictEqual(leadFor('Dentease is done.', '', false), 'Separately:')
  assert.strictEqual(leadFor('About the mix-up, sir: they came late.', 'the mix-up'), '')

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
  // Each request carries the board, so the orch needn't look it up.
  await fetch(`http://127.0.0.1:${port2}/`, { method: 'POST', body: 'board check' })
  const pushed = JSON.parse((await replies.next()).value)
  assert(pushed.method === 'notifications/claude/channel' && /^board check\n\n\(From the voice, so no lookup is needed for this: sessions on this PC: .*Workers' newest progress lines: /s
    .test(pushed.params.content), JSON.stringify(pushed))
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
  // Before this PC powers off (/shutdown), release.mjs closes its mic and marks its claim released.
  const release = spawnSync('node', ['release.mjs'], { cwd: HERE, encoding: 'utf8', env: { ...process.env, VOICE_SHARED: CLAIMS, VOICE_PORT: String(port2) } })
  assert.strictEqual(release.stdout.trim(), 'held', release.stderr)
  assert.strictEqual(await micState(), 'off')
  assert(JSON.parse(readFileSync(mine, 'utf8')).released)
  await stop()
  // The other PC released its claim, which is still the latest: a voice starting here opens its mic and claims it.
  rmSync(mine)
  const releasedBy = (host, when) => writeFileSync(join(CLAIMS, host, 'jarvis.json'),
    JSON.stringify({ claimed: new Date(when).toISOString(), released: new Date().toISOString(), by: 'shutdown' }))
  releasedBy('OtherPC', Date.now() + 60_000)
  third = start(port2, '')
  assert.strictEqual(await up(), 'on')
  assert(existsSync(mine), 'a released claim counts as none, so this PC claims it')
  await stop()
  // Running closed while the other PC holds it, and that PC releases it: the mic opens here, and this PC claims it.
  rmSync(mine)
  claimBy('OtherPC', Date.now())
  third = start(port2, '')
  assert.strictEqual(await up(), 'off')
  releasedBy('OtherPC', Date.now())
  for (let i = 0; i < 50 && (await micState()) === 'off'; i++) await sleep(100)
  assert.strictEqual(await micState(), 'on', 'the other PC let go, so the voice moves here')
  assert(existsSync(mine))
  await stop()
  // An unreadable claim (a sync swapping the file in) is not a release: the mic stays closed.
  rmSync(mine)
  claimBy('OtherPC', Date.now())
  third = start(port2, '')
  assert.strictEqual(await up(), 'off')
  writeFileSync(join(CLAIMS, 'OtherPC', 'jarvis.json'), '{"claim')
  await sleep(3500)
  assert.strictEqual(await micState(), 'off')
  assert(!existsSync(mine))
  console.log('ok')
} finally {
  second?.kill()
  third?.kill()
  voice.stdin.end()
  voice.kill()
}
