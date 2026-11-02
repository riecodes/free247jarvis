#!/usr/bin/env node
// A worker's spoken progress line, for the status bank: Jarvis renders it ahead, and plays it when the user asks how that
// topic is going, with its age, and no turn of the orch.
//   node progress.mjs vlog "The vlog is rendering, about five minutes left."
//   node progress.mjs --waiting vlog "The vlog draft is ready for your review."   (it may remind the user, once in a while)
// A newer line on the same topic replaces the old one, and a line without --waiting ends the wait.
import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { hostname } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { bankFile } from './rules.mjs'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const KEEP = 200 // lines kept in the file
const args = process.argv.slice(2)
const waiting = args[0] === '--waiting'
if (waiting) args.shift()
const [topic, ...words] = args
const text = words.join(' ').replace(/\s+/g, ' ').trim().slice(0, 240)
if (!topic?.trim() || !text) {
  console.error('Use: node progress.mjs [--waiting] <topic> "<one short spoken line>"')
  process.exit(2)
}
const file = bankFile(process.env.VOICE_SHARED || join(HERE, '..', '.leases'), hostname(), HERE, existsSync)
mkdirSync(dirname(file), { recursive: true })
const line = JSON.stringify({ topic: topic.trim().toLowerCase(), text: /[.!?]$/.test(text) ? text : `${text}.`, waiting, at: new Date().toISOString() })
appendFileSync(file, `${line}\n`)
const lines = readFileSync(file, 'utf8').trim().split('\n')
if (lines.length > KEEP) writeFileSync(file, `${lines.slice(-KEEP).join('\n')}\n`)
console.log('saved')
