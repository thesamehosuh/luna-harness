import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'
import { useEffect, useState } from 'react'

import { Button } from '../../../web/src/components/ui/Button'

type Preferences = {
  installed: boolean
  launch_at_login: boolean | null
  startup_error: string | null
  keep_in_background: boolean
  start_companion: boolean
  tray_available: boolean
}

export default function DesktopControls({ runtimeBusy, preview = false }: { runtimeBusy: boolean; preview?: boolean }) {
  const [preferences, setPreferences] = useState<Preferences | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [detail, setDetail] = useState('')

  useEffect(() => {
    if (preview) {
      setPreferences({ installed: true, launch_at_login: false, startup_error: null, keep_in_background: false, start_companion: false, tray_available: true })

      return
    }

    let disposed = false
    let cleanup: (() => void) | undefined
    void invoke<Preferences>('luna_desktop_preferences').then(value => {
      if (!disposed) { setPreferences(value) }
    }).catch(reason => { if (!disposed) { setError(String(reason)) } })
    void listen<Preferences>('luna-preferences-changed', event => setPreferences(event.payload))
      .then(stop => { if (disposed) { stop() } else { cleanup = stop } })

    return () => { disposed = true; cleanup?.() }
  }, [runtimeBusy, preview])

  const change = async (key: 'launch_at_login' | 'keep_in_background' | 'start_companion', value: boolean) => {
    setBusy(true)
    setError('')

    try { if (preview) {setPreferences(previous => previous && { ...previous, [key]: value });} else {setPreferences(await invoke<Preferences>('luna_set_desktop_preferences', { patch: { [key]: value } }))} }
    catch (reason) { setError(String(reason)) }
    finally { setBusy(false) }
  }

  const companion = async (action: 'start' | 'stop') => {
    setBusy(true)
    setError('')
    setDetail(action === 'start' ? 'Starting companion…' : 'Stopping companion…')

    try {
      if (preview) {return}
      await invoke('luna_companion', { action })
      setDetail(action === 'start' ? 'Companion is running.' : 'Companion is stopped.')
    }
    catch (reason) { setError(String(reason)); setDetail('') }
    finally { setBusy(false) }
  }

  return <div className="launcher-preferences space-y-4 text-left text-sm">
    {preferences && <>
      <label className="flex items-center gap-2"><input checked={preferences.launch_at_login ?? false} disabled={busy || runtimeBusy || !preferences.installed || !!preferences.startup_error} onChange={event => void change('launch_at_login', event.target.checked)} type="checkbox" />Launch Luna when I sign in</label>
      <label className="flex items-center gap-2"><input checked={preferences.keep_in_background} disabled={busy || runtimeBusy || !preferences.tray_available} onChange={event => void change('keep_in_background', event.target.checked)} type="checkbox" />Keep Luna running when I close its window</label>
      <label className="flex items-center gap-2"><input checked={preferences.start_companion} disabled={busy || runtimeBusy || !preferences.installed} onChange={event => void change('start_companion', event.target.checked)} type="checkbox" />Start my companion when Luna opens</label>
      <p className="text-xs leading-6 text-muted-foreground">The companion stays connected to your chat apps in the background. You can also control it from the dashboard’s System page.</p>
      {!preferences.tray_available && <p className="text-xs text-muted-foreground">A system tray is unavailable on this desktop. Closing Luna will quit the launcher.</p>}
      {preferences.startup_error && <p role="alert">Launch at login is unavailable: {preferences.startup_error}</p>}
      <div className="flex flex-wrap gap-3">
        <Button disabled={busy || runtimeBusy || !preferences.installed} onClick={() => void companion('start')} outlined size="sm">Start companion</Button>
        <Button disabled={busy || runtimeBusy || !preferences.installed} onClick={() => void companion('stop')} outlined size="sm">Stop companion</Button>
        <Button disabled={busy || runtimeBusy} ghost onClick={() => { if (!preview) {void invoke('luna_open').catch(reason => setError(String(reason)))} }} outlined size="sm">Open dashboard</Button>
        <Button disabled={busy || runtimeBusy} ghost onClick={() => { if (!preview) {void invoke('luna_quit').catch(reason => setError(String(reason)))} }} outlined size="sm">Quit Luna</Button>
      </div>
    </>}
    {detail && <p aria-live="polite">{detail}</p>}
    {error && <p className="text-destructive" role="alert">{error}</p>}
  </div>
}
