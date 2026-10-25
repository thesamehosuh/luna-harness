import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'
import { useEffect, useRef, useState } from 'react'

import { LunaMark } from '../../../web/src/components/LunaMark'
import { Button } from '../../../web/src/components/ui/Button'

import DesktopControls from './desktop-controls'

// Configuration lives in the dashboard. This screen only owns runtime setup.
export default function App() {
  const once = useRef(false)
  const [busy, setBusy] = useState(false)
  const [installed, setInstalled] = useState(false)
  const [repair, setRepair] = useState(false)
  const [update, setUpdate] = useState(false)
  const [detail, setDetail] = useState('The harness for your own AI companion.')
  const [error, setError] = useState('')
  const starting = useRef(false)

  const start = async (forceRepair = false) => {
    if (starting.current) {return}
    starting.current = true
    setBusy(true)
    setError('')

    try { await invoke('luna_start', { repair: forceRepair }) }
    catch (reason) { setError(String(reason)); setDetail('Your personal data stays here. Retry when you’re ready.') }
    finally { starting.current = false; setBusy(false) }
  }

  useEffect(() => {
    const cleanups: Array<() => void> = []
    let disposed = false
    void listen<{ stage: string; detail: string }>('luna-progress', event => setDetail(event.payload.detail))
      .then(cleanup => { if (disposed) {cleanup();} else {cleanups.push(cleanup)} })

    if (!once.current) {
    once.current = true
    void invoke<{ installed: boolean; update_available: boolean; force_setup: boolean; background_launch: boolean }>('luna_status').then(status => {
      setInstalled(status.installed)
      setUpdate(status.update_available)
      setRepair(status.force_setup)

      if (status.installed && (!status.update_available || status.background_launch) && !status.force_setup) {void start()}
    }).catch(reason => setError(String(reason)))
    }

    void listen('luna-repair-requested', () => { setRepair(true); setInstalled(true); setError(''); setDetail('Repair downloads a verified runtime and keeps your character, connections and history. Stop your gateway in System before repairing.') }).then(cleanup => { if (disposed) {cleanup();} else {cleanups.push(cleanup)} })
    void listen('luna-backend-lost', () => { setBusy(false); setError('The dashboard stopped. Open Luna again to reconnect.'); setInstalled(true) }).then(cleanup => { if (disposed) {cleanup();} else {cleanups.push(cleanup)} })
    void listen<string>('luna-controls-error', event => setError(event.payload)).then(cleanup => { if (disposed) { cleanup() } else { cleanups.push(cleanup) } })

    return () => { disposed = true; cleanups.forEach(cleanup => cleanup()) }
  }, [])

  return (
    <main className="flex h-full flex-col items-center gap-4 overflow-y-auto bg-background px-12 py-8 text-center text-foreground">
      <LunaMark className="size-14 text-primary" />
      <h1 className="launcher-display text-4xl tracking-tight">Luna</h1>
      <p aria-live="polite" className="max-w-md text-base text-muted-foreground">{detail}</p>
      {!installed && !busy && !error && <p className="max-w-md text-sm text-muted-foreground">Luna will download its runtime. You’ll choose a character and chat model in the dashboard. Memory is optional.</p>}
      {error && <p className="max-w-lg text-sm text-destructive" role="alert">{error}</p>}
      {busy ? <Button  onClick={() => void invoke('luna_cancel')} outlined>Cancel</Button> :
        <Button className="min-w-40" onClick={() => void start(repair || update)}>{error ? 'Try again' : repair ? 'Repair runtime' : update ? 'Install update' : installed ? 'Open Luna' : 'Install Luna'}</Button>}
      {!busy && installed && (repair || update || error) && <Button ghost onClick={() => void start(false)} outlined size="sm">Open current version</Button>}
      {!busy && error && !repair && <Button ghost onClick={() => { setRepair(true); setError(''); setDetail('Repair the runtime while keeping your personal data. Stop the gateway first, if it is running.') }} outlined size="sm">Repair runtime</Button>}
      <DesktopControls runtimeBusy={busy} />
    </main>
  )
}
