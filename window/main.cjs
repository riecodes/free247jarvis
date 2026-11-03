// The Jarvis window: only a frame around the page voice.mjs serves. It opens without taking the keyboard, and stays
// out of screen shares and recordings (CAPTION_VISIBLE=1 shows it there). Its minimize, maximize and close buttons
// are drawn over the page's header, in the page's colors, and the header drags it. Closing it closes only the window:
// the voice is another process and goes on. POST /window (voice.mjs) opens it again, or brings it to the front.
const { app, BrowserWindow, nativeTheme } = require('electron')

const URL = `http://127.0.0.1:${process.env.VOICE_PORT || 8790}/window`
const HEADER = 45 // px: the page's header (46) less its bottom border, which stays in sight
const overlay = () => nativeTheme.shouldUseDarkColors
  ? { color: '#14161a', symbolColor: '#eceef1', height: HEADER }
  : { color: '#f6f7f9', symbolColor: '#16181d', height: HEADER }

if (!app.requestSingleInstanceLock()) app.quit()
else app.whenReady().then(() => {
  const win = new BrowserWindow({
    width: 480, height: 600, minWidth: 280, minHeight: 240, show: false, autoHideMenuBar: true, title: 'Jarvis',
    backgroundColor: '#14161a', titleBarStyle: 'hidden', titleBarOverlay: overlay(),
    trafficLightPosition: { x: 16, y: 16 }, // macOS: its three buttons at the left, centered on the header
    webPreferences: { sandbox: true, contextIsolation: true },
  })
  // macOS draws its own buttons in its own colors, and can't recolor them.
  if (process.platform !== 'darwin') nativeTheme.on('updated', () => win.setTitleBarOverlay(overlay()))
  win.setContentProtection(process.env.CAPTION_VISIBLE !== '1')
  win.once('ready-to-show', () => win.showInactive())
  // A second copy quits at once. Started by a restart of the voice it changes nothing; asked for (--show), the window comes up.
  app.on('second-instance', (event, argv) => {
    if (!argv.includes('--show')) return
    if (win.isMinimized()) win.restore()
    win.show()
    win.focus()
  })
  // The voice may still be starting; once loaded, the page reconnects by itself.
  const load = () => win.loadURL(URL).catch(() => setTimeout(load, 2000))
  load()
  app.on('window-all-closed', () => app.quit())
})
