// Rebuilds the orb bundle inside ../index.html (one file, no server change): node orb/build.mjs
import { execFileSync } from 'node:child_process'
import { readFileSync, unlinkSync, writeFileSync } from 'node:fs'
const here = new URL('.', import.meta.url), page = new URL('../index.html', import.meta.url)
execFileSync('npx', ['--yes', 'esbuild', 'entry.ts', '--bundle', '--minify', '--format=iife', '--target=chrome120', '--outfile=orb.min.js'], { cwd: here, shell: true, stdio: 'inherit' })
const code = readFileSync(new URL('orb.min.js', here), 'utf8').trim()
const html = readFileSync(page, 'utf8').replace(/(  \/\/ orb:bundle\n)[\s\S]*?(  \/\/ orb:bundle-end)/, (_, a, b) => `${a}${code}\n${b}`)
writeFileSync(page, html)
unlinkSync(new URL('orb.min.js', here))
