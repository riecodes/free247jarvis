#!/usr/bin/env node
// Lets go of the voice before this PC powers off (the /shutdown skill; not /restart, a reboot comes back). Closes this
// mic and marks this PC's claim released, so the other PC's voice opens its mic: at once if it is running, else when
// it starts. Prints "held" when this PC had the voice, else "not held".
//   node release.mjs
import { existsSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { hostname } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { claimAt } from './rules.mjs'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const SHARED = process.env.VOICE_SHARED || join(HERE, '..', '.leases')
const PORT = Number(process.env.VOICE_PORT || 8790)
const read = host => { try { return readFileSync(join(SHARED, host, 'jarvis.json'), 'utf8') } catch { return '' } }
const hosts = existsSync(SHARED) ? readdirSync(SHARED) : []
const me = hosts.find(h => h.toLowerCase() === hostname().toLowerCase()) ?? hostname()
const mine = claimAt(read(me))
const held = mine > 0 && hosts.every(h => h === me || claimAt(read(h)) < mine)
if (mine) writeFileSync(join(SHARED, me, 'jarvis.json'), JSON.stringify({ ...JSON.parse(read(me)), released: new Date().toISOString(), by: 'shutdown' }))
try { await fetch(`http://127.0.0.1:${PORT}/mic`, { method: 'POST', body: 'off', signal: AbortSignal.timeout(2000) }) } catch {}
console.log(held ? 'held' : 'not held')
