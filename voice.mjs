#!/usr/bin/env node
// The "voice" channel: the boss session loads this MCP server, which pushes spoken requests into the
// session and speaks the boss's replies. It runs listener.py (wake word, speech to text, Kokoro) as a child
// and also takes typed requests on POST http://127.0.0.1:8790/, so anything local can talk to the boss.
// Everything it hears and says is logged to tmp/voice.log.
import { spawn } from 'node:child_process'
import { appendFileSync, mkdirSync } from 'node:fs'
import { createServer } from 'node:http'
import { createInterface } from 'node:readline'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { Server } from '@modelcontextprotocol/sdk/server/index.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const PORT = Number(process.env.VOICE_PORT || 8790)
const PYTHON = join(HERE, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
mkdirSync(join(HERE, 'tmp'), { recursive: true })
const log = line => appendFileSync(join(HERE, 'tmp', 'voice.log'), `${new Date().toISOString()} ${line}\n`)

const mcp = new Server(
  { name: 'voice', version: '1.0.0' },
  {
    capabilities: { experimental: { 'claude/channel': {} }, tools: {} },
    instructions:
      'Spoken requests from the user arrive as <channel source="voice">, already turned into text (English, ' +
      'Tagalog or Taglish, with the odd speech-to-text mistake). Act on each one, then answer it out loud with ' +
      'exactly one call to the reply tool: one or two short spoken sentences, no markdown.',
  },
)

mcp.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [{
    name: 'reply',
    description: 'Say something out loud to the user (Kokoro voice). Plain spoken sentences only: no markdown, code, or long paths.',
    inputSchema: {
      type: 'object',
      properties: { text: { type: 'string', description: 'What to say, one or two short sentences' } },
      required: ['text'],
    },
  }],
}))

mcp.setRequestHandler(CallToolRequestSchema, async req => {
  if (req.params.name !== 'reply') throw new Error(`unknown tool: ${req.params.name}`)
  const text = String(req.params.arguments?.text ?? '').replace(/\s+/g, ' ').trim()
  log(`reply: ${text}`)
  if (text) ears.stdin.write(`say ${text}\n`)
  return { content: [{ type: 'text', text: 'Speaking.' }] }
})

async function push(text, via) {
  log(`heard (${via}): ${text}`)
  await mcp.notification({ method: 'notifications/claude/channel', params: { content: text, meta: { via } } })
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
    if (e.event === 'heard') push(e.text, 'mic')
    else log(`listener ${e.event}${e.text || e.message ? `: ${e.text || e.message}` : ''}`)
  })
  ears.on('exit', code => {
    log(`listener exited (${code})`)
    if (!quitting) setTimeout(startEars, 5000)
  })
  if (process.env.VOICE_MIC !== 'off') ears.stdin.write('on\n')
}
startEars()

createServer((req, res) => {
  if (req.method === 'GET') return res.end('ok')  // health check
  let body = ''
  req.on('data', d => (body += d))
  req.on('end', async () => {
    if (body.trim()) await push(body.trim(), 'http')
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
