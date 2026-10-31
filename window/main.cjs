// The Jarvis window: only a frame around the page voice.mjs serves. It opens without taking the keyboard, and stays
// out of screen shares and recordings like the caption does (CAPTION_VISIBLE=1 shows it there).
const { app, BrowserWindow } = require('electron')

const URL = `http://127.0.0.1:${process.env.VOICE_PORT || 8790}/window`

if (!app.requestSingleInstanceLock()) app.quit()
else app.whenReady().then(() => {
  const win = new BrowserWindow({
    width: 420, height: 600, minWidth: 280, minHeight: 240, show: false, autoHideMenuBar: true, title: 'Jarvis',
    backgroundColor: '#14161a',
    webPreferences: { sandbox: true, contextIsolation: true },
  })
  win.setContentProtection(process.env.CAPTION_VISIBLE !== '1')
  win.once('ready-to-show', () => win.showInactive())
  // The voice may still be starting; once loaded, the page reconnects by itself.
  const load = () => win.loadURL(URL).catch(() => setTimeout(load, 2000))
  load()
  app.on('window-all-closed', () => app.quit())
})
