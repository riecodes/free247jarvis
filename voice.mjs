#!/usr/bin/env node
// The "voice" channel: the boss session loads this MCP server, which pushes spoken requests into the
// session and speaks the boss's replies. It runs listener.py (wake word, speech to text, voice) as a child
// and also takes typed requests on POST http://127.0.0.1:8790/, so anything local can talk to the boss.
// Everything it hears and says is logged to tmp/voice.log.
// With a TypeSafe key in .env, a router answers quick requests itself, without a turn of the boss (see route).
import { spawn } from 'node:child_process'
import { appendFileSync, existsSync, mkdirSync, readFileSync, readdirSync } from 'node:fs'
import { createServer } from 'node:http'
import { homedir } from 'node:os'
import { createInterface } from 'node:readline'
import { basename, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { Server } from '@modelcontextprotocol/sdk/server/index.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js'
import { asksForHeld, asksSomething, isAnswer, isLong, verbFor } from './rules.mjs'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const PORT = Number(process.env.VOICE_PORT || 8790)
const PYTHON = join(HERE, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
mkdirSync(join(HERE, 'tmp'), { recursive: true })
const log = line => appendFileSync(join(HERE, 'tmp', 'voice.log'), `${new Date().toISOString()} ${line}\n`)
// The pro voice (VOICE_ENGINE=elevenlabs, from start.ps1 -Engine or .env) speaks Filipino well, so it answers
// in Taglish; Kokoro's British voice only says English words, so the free voice answers in plain English.
// .env next to this file, first line wins as in listener.py; real environment variables win over it.
const env = { ...process.env }
const dotenv = existsSync(join(HERE, '.env')) ? readFileSync(join(HERE, '.env'), 'utf8') : ''
for (const [, k, v] of dotenv.matchAll(/^([A-Z][A-Z0-9_]*)=(.*)$/gm)) env[k] ??= v.trim().replace(/^"(.*)"$/, '$1')
const pro = /^elevenlabs$/i.test(env.VOICE_ENGINE ?? '')
// VOICE_TITLE=Sir: every spoken line opens with it ("Sir, the course session needs you.").
const TITLE = env.VOICE_TITLE?.trim() ?? ''
// The listener's rising chime after a reply that asks something says the mic is open again (FOLLOWUP_SECONDS), so no spoken cue here.
const titled = text => !TITLE || !text || text.toLowerCase().startsWith(TITLE.toLowerCase()) ? text
  : `${TITLE}, ${text[0].toLowerCase()}${text.slice(1)}`
const SPEAK = (TITLE ? `Start every spoken reply with "${TITLE},". ` : '') +
  'Write times, numbers and dates as English words, the way they are said ("nine seventeen PM", "October ' +
  'twenty-six"), never in Spanish or Tagalog numbers.' +
  (pro ? ' Whatever language the request is in, answer in everyday Taglish: an English sentence with common ' +
    'Tagalog words mixed in ("Sige, sent ko na sa course session"), never deep or formal Tagalog.'
    : ' Whatever language the request is in, answer in plain English only, with no Tagalog or Taglish ' +
    'words at all (not even "na", "po" or "sige"): the voice can only say English.')

// A key from .env: NAME=..., or NAME_FILE= a file that holds the key alone or a NAME=... line (another app's .env).
function secret(name) {
  const path = env[`${name}_FILE`]
  if (env[name] || !path || !existsSync(path)) return env[name] ?? ''
  const text = readFileSync(path, 'utf8')
  return (text.match(new RegExp(`^${name}=(.*)$`, 'm'))?.[1] ?? text).trim().replace(/^"(.*)"$/, '$1')
}

const mcp = new Server(
  { name: 'voice', version: '1.0.0' },
  {
    capabilities: { experimental: { 'claude/channel': {} }, tools: {} },
    instructions:
      'Spoken requests from the user arrive as <channel source="voice">, already turned into text (English, ' +
      'Tagalog or Taglish, with the odd speech-to-text mistake). Act on each one, then answer it out loud with ' +
      'exactly one call to the reply tool: one or two short spoken sentences, no markdown. The mic reopens after ' +
      'a reply only when it asks the user something; when the user just answered your question, your ' +
      'acknowledgment ends the exchange, so pass listen: false if its wording could read as asking. ' + SPEAK,
  },
)

mcp.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [{
    name: 'reply',
    description: 'Say something out loud to the user. Plain spoken sentences only: no markdown, code, or long paths.',
    inputSchema: {
      type: 'object',
      properties: {
        text: { type: 'string', description: 'What to say, one or two short sentences' },
        listen: {
          type: 'boolean',
          description: 'Keep the mic open a few seconds after this reply. Default: only when the line asks something ' +
            '(a question, or "say ..."). False on an acknowledgment of an answer the user just gave.',
        },
      },
      required: ['text'],
    },
  }],
}))

mcp.setRequestHandler(CallToolRequestSchema, async req => {
  if (req.params.name !== 'reply') throw new Error(`unknown tool: ${req.params.name}`)
  const text = titled(String(req.params.arguments?.text ?? '').replace(/\s+/g, ' ').trim())
  log(`reply: ${text}`)
  if (text) {
    ears.stdin.write(`${verbFor(askedAt, req.params.arguments?.listen ?? asksSomething(text))} ${text}\n`)
    askedAt = 0 // one reply answers the request; later lines are the boss's own news
  }
  return { content: [{ type: 'text', text: 'Speaking.' }] }
})

async function push(text, via) {
  log(`heard (${via}): ${text}`)
  await send(text, via)
}

let askedAt = 0 // when the boss last got a spoken request it has not answered yet
const held = [] // lines not said because of a call, until the user asks for them
const send = (text, via) => {
  if (via === 'mic') askedAt = Date.now()
  return mcp.notification({ method: 'notifications/claude/channel', params: { content: text, meta: { via } } })
}

// The router, for spoken requests. With TYPESAFE_API_KEY in .env, Jev (TypeSafe's classifier) sorts each one, and
// quick ones are answered here, about a second after they're heard, without a turn of the boss: the sessions'
// status, small talk (Claude Haiku, with ANTHROPIC_API_KEY), and speech that isn't a clear request ("Say that
// again?"). Everything else, and everything without a key, goes to the boss as before.
const JEV_URL = 'https://api.typesafe.ai/v1/systemone'
const JEV_MIN = 0.7 // Jev less sure than this: the boss gets it
const HAIKU = 'claude-haiku-5-5'
const KINDS = {
  status: 'Asks how the Claude Code sessions or terminals are doing overall: status, who is busy or idle, what ' +
    'finished, who or what needs the user. Not a request about one named session.',
  chat: 'Small talk or a quick question that needs no session and no action on the computer: a greeting, ' +
    'thanks, how are you, a joke, the time or date, a general fact.',
  unclear: 'Not a clear request: cut off mid-sentence, garbled words, or speech not meant for the assistant ' +
    '(a TV, someone else talking).',
  work: 'Anything else: a task or message for a session or terminal, a short answer to a question just asked ' +
    '(a letter such as "A", yes, no, sige), opening terminals or apps, or anything that changes something.',
}

async function route(text) {
  log(`heard (mic): ${text}`)
  if (held.length && asksForHeld(text)) return answer(held.splice(0).join(' '))
  if (isAnswer(text)) return send(text, 'mic')
  const key = secret('TYPESAFE_API_KEY')
  let kind = 'work', p = 1
  if (key) {
    const t = Date.now()
    try {
      const r = await fetch(JEV_URL, {
        method: 'POST',
        headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json', 'User-Agent': 'free247jarvis/1' },
        body: JSON.stringify({
          model: 'jev-latest',
          state: { heard: text },
          questions: {
            kind: {
              type: 'choice', criteria: KINDS,
              instructions: 'The user said `heard` to a voice assistant that runs their Claude Code sessions (speech ' +
                'to text, so English, Tagalog or Taglish, sometimes misheard). What kind of request is it?',
            },
          },
        }),
        signal: AbortSignal.timeout(3000),
      })
      const jev = r.ok ? (await r.json()).answers?.kind : null
      if (jev?.choice) [kind, p] = [jev.choice, jev.probabilities?.[jev.choice] ?? 0]
      else log(`router: Jev returned ${r.status}`)
    } catch (e) {
      log(`router: Jev failed: ${e.message}`)
    }
    log(`router: ${kind} ${p.toFixed(2)} in ${Date.now() - t} ms`)
  }
  // Jev unsure: the boss decides ("Sino ang may kailangan sa akin?" scored status 0.67, and asking again was wrong).
  if (p < JEV_MIN || (kind === 'unclear' && isLong(text))) kind = 'work'
  if (kind === 'unclear') return answer(pro ? 'Sorry, ano ulit?' : 'Say that again?', true)
  const quick = kind === 'status' ? status() : kind === 'chat' ? await chat(text) : ''
  if (quick) return answer(quick)
  await send(text, 'mic')
}

// Says it without the boss; `listen` then records the next sentence without the wake word.
function answer(text, listen = false) {
  text = titled(text)
  log(`reply (router): ${text}`)
  ears.stdin.write(`${asksSomething(text) ? 'say' : 'end'} ${text}\n${listen ? 'listen\n' : ''}`)
}

const NUMBERS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten']
const count = (n, what) => `${NUMBERS[n] ?? n} ${what}`

// The live sessions from Claude Code's own files, ~/.claude/sessions/<pid>.json, except the boss (our parent).
function status() {
  const dir = join(homedir(), '.claude', 'sessions')
  const live = readdirSync(dir).flatMap(f => {
    try {
      const s = JSON.parse(readFileSync(join(dir, f), 'utf8'))
      process.kill(s.pid, 0) // throws when that process is gone
      return s.pid === process.ppid ? [] : [s]
    } catch { return [] }
  })
  if (!live.length) return ''
  // By the name the user gave it, else by its folder: "the course session".
  const label = s => (s.nameSource === 'user' ? s.name : `the ${basename(s.cwd)} session`)
  const waiting = live.filter(s => s.status === 'waiting')
  const busy = live.filter(s => s.status === 'busy' || s.status === 'shell').length
  const counts = [busy && count(busy, 'working'), live.length - busy - waiting.length && count(live.length - busy - waiting.length, 'idle'),
    waiting.length && count(waiting.length, 'waiting')].filter(Boolean).join(', ')
  const needs = waiting.map(s => `${label(s)} needs you: ${(s.waitingFor || 'an answer').split(/\s+/).slice(0, 6).join(' ')}.`)
  const sessions = count(live.length, live.length === 1 ? 'session' : 'sessions')
  return pro
    ? `May ${sessions}: ${counts}. ${needs.join(' ') || 'Walang naghihintay sa yo.'}`
    : `${sessions[0].toUpperCase() + sessions.slice(1)}: ${counts}. ${needs.join(' ') || 'Nothing needs you.'}`
}

async function chat(text) {
  const key = secret('ANTHROPIC_API_KEY')
  if (!key) return ''
  const now = new Date().toLocaleString('en-US', { weekday: 'long', month: 'long', day: 'numeric', hour: 'numeric', minute: '2-digit' })
  try {
    const r = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json' },
      body: JSON.stringify({
        model: HAIKU, max_tokens: 150,
        system: `You are Jarvis, the voice of the user's Claude Code assistant on their Windows PC. Answer out loud in one ` +
          `or two short spoken sentences, no markdown and no emoji. It is ${now} now. ${SPEAK}`,
        messages: [{ role: 'user', content: text }],
      }),
      signal: AbortSignal.timeout(6000),
    })
    const data = await r.json()
    if (!r.ok) log(`router: Haiku returned ${r.status}: ${data.error?.message ?? ''}`)
    return r.ok ? (data.content?.[0]?.text ?? '').replace(/\s+/g, ' ').trim() : ''
  } catch (e) {
    log(`router: Haiku failed: ${e.message}`)
    return ''
  }
}

// The listener: commands in on stdin, one JSON event per stdout line. It restarts if it dies.
let ears
let quitting = false
function startEars() {
  ears = spawn(PYTHON, [join(HERE, 'listener.py')], { cwd: HERE, stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true })
  ears.on('error', e => log(`listener failed to start: ${e.message}`))
  ears.stdin.on('error', e => log(`listener stdin: ${e.message}`))
  ears.stderr.on('data', d => appendFileSync(join(HERE, 'tmp', 'listener.log'), d))
  createInterface({ input: ears.stdout }).on('line', line => {
    let e
    try { e = JSON.parse(line) } catch { return log(`listener: ${line}`) }
    if (e.event === 'heard') route(e.text).catch(err => (log(`router: ${err.message}`), send(e.text, 'mic')))
    else if (e.event === 'held') (held.push(e.text), log(`held for after the call: ${e.text}`))
    else if (e.event === 'peak') log(`wake peak: ${e.word} ${e.score}${e.busy ? ' (busy)' : ''}`)
    else log(`listener ${e.event}${e.text || e.message ? `: ${e.text || e.message}` : ''}`)
  })
  ears.on('exit', code => {
    log(`listener exited (${code})`)
    if (!quitting) setTimeout(startEars, 5000)
  })
  if (mic) ears.stdin.write('on\n')
}
// VOICE_MIC=off starts with the microphone closed; POST on or off to /mic opens or closes it, no restart needed.
let mic = process.env.VOICE_MIC !== 'off'
startEars()

// POST /: a typed request for the boss. POST /heard: as if spoken (through the router). POST /mic: on or off.
createServer((req, res) => {
  if (req.method === 'GET') return res.end(req.url === '/mic' ? (mic ? 'on' : 'off') : 'ok')  // health check
  let body = ''
  req.on('data', d => (body += d))
  req.on('end', async () => {
    const text = body.trim()
    if (req.url === '/mic' && /^(on|off)$/.test(text)) {
      mic = text === 'on'
      log(`mic ${text}`)
      ears.stdin.write(`${text}\n`)
    } else if (req.url === '/heard' && text) await route(text)
    else if (text) await push(text, 'http')
    res.end('ok')
  })
}).on('error', e => log(`http ${PORT}: ${e.message}`)).listen(PORT, '127.0.0.1')

// Claude Code exits by closing our stdin; the listener then sees its own stdin close and quits too.
function quit() {
  quitting = true
  ears.kill()
  process.exit(0)
}
mcp.onclose = quit
process.stdin.on('end', quit)
await mcp.connect(new StdioServerTransport())
log('voice channel up')
