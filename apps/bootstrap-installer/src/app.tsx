import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { ArrowRight, Check, ChevronDown, Download, LoaderCircle, Minus, RefreshCw, Settings2, ShieldCheck, Square, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { LunaMark } from '../../../web/src/components/LunaMark'
import { Button } from '../../../web/src/components/ui/Button'

import DesktopControls from './desktop-controls'
import { formatBytes, type LauncherProgress, progressStep } from './progress'

type Status = { installed: boolean; update_available: boolean; force_setup: boolean; background_launch: boolean; version?: string; available?: string }
const steps = ['Download Luna', 'Prepare your environment', 'Set up the chat runtime', 'Open your dashboard']
const preview = import.meta.env.DEV ? new URLSearchParams(location.search).get('preview') : null

// All character, connection and memory setup stays in the dashboard.
export default function App() {
  const [status, setStatus] = useState<Status | null>(null)
  const [busy, setBusy] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [repair, setRepair] = useState(false)
  const [progress, setProgress] = useState<LauncherProgress | null>(null)
  const [error, setError] = useState('')
  const [settings, setSettings] = useState(preview === 'settings')
  const [elapsed, setElapsed] = useState(0)
  const settingsRef = useRef<HTMLDivElement>(null)
  const settingsButtonRef = useRef<HTMLButtonElement>(null)
  const starting = useRef(false)
  const autoStarted = useRef(false)

  const start = useCallback(async (forceRepair = false) => {
    if (starting.current) {return}
    starting.current = true
    setBusy(true)
    setCancelling(false)
    setError('')
    setElapsed(0)
    setProgress({ stage: 'checking', detail: 'Checking your installation…' })

    try { await invoke('luna_start', { repair: forceRepair }) }
    catch (reason) {
      setError(String(reason))

      // Setup may have finished before opening the dashboard failed.
      try { setStatus(await invoke<Status>('luna_status')) } catch { /* retain last status */ }
    } finally { starting.current = false; setBusy(false); setCancelling(false) }
  }, [])

  useEffect(() => {
    if (preview) {
      setStatus({ installed: preview === 'installed' || preview === 'settings', update_available: false, force_setup: false, background_launch: false, available: 'Preview' })

      if (preview === 'download' || preview === 'setup') {
        setBusy(true)
        setProgress(preview === 'download' ? { stage: 'download', detail: 'Downloading the verified Luna runtime', completed_bytes: 42_000_000, total_bytes: 96_000_000, bytes_per_second: 2_800_000 } : { stage: 'dependencies', detail: 'Installing Python and Luna’s dependencies…' })
      }

      if (preview === 'error') {setError('The download was interrupted. Check your connection, then try again to resume.')}

      return
    }

    let disposed = false
    const cleanups: Array<() => void> = []

    const subscribe = async () => {
      const listeners = await Promise.all([
        listen<LauncherProgress>('luna-progress', event => setProgress(event.payload)),
        listen('luna-repair-requested', () => { setRepair(true); setStatus(value => value && { ...value, installed: true }); setError(''); setProgress(null) }),
        listen('luna-backend-lost', () => { setBusy(false); setError('The dashboard stopped. Try opening it again.'); setStatus(value => value && { ...value, installed: true }) }),
        listen<string>('luna-controls-error', event => setError(event.payload)),
      ])

      if (disposed) { listeners.forEach(stop => stop());

 return }

      cleanups.push(...listeners)
      const value = await invoke<Status>('luna_status')

      if (disposed) {return}
      setStatus(value)
      setRepair(value.force_setup)

      if (!autoStarted.current && value.installed && (!value.update_available || value.background_launch) && !value.force_setup) {
        autoStarted.current = true
        void start()
      }
    }

    void subscribe().catch(reason => { if (!disposed) {setError(String(reason))} })

    return () => { disposed = true; cleanups.forEach(stop => stop()) }
  }, [start])

  useEffect(() => {
    if (!busy) {return}
    const started = Date.now()
    const tick = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000)

    return () => clearInterval(tick)
  }, [busy])


  useEffect(() => {
    if (!settings) {return}
    settingsRef.current?.querySelector<HTMLElement>('button, input:not([disabled])')?.focus()

    const dismiss = (event: PointerEvent) => {
      if (!settingsRef.current?.contains(event.target as Node) && !settingsButtonRef.current?.contains(event.target as Node)) {setSettings(false)}
    }

    const keyboard = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setSettings(false); settingsButtonRef.current?.focus() }

      if (event.key === 'Tab') {
        const items = Array.from(settingsRef.current?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled])') ?? [])
        const first = items[0], last = items.at(-1)

        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
      }
    }

    document.addEventListener('pointerdown', dismiss)
    document.addEventListener('keydown', keyboard)

    return () => { document.removeEventListener('pointerdown', dismiss); document.removeEventListener('keydown', keyboard) }
  }, [settings])

  const cancel = async () => {
    setCancelling(true)

    try { await invoke('luna_cancel') } catch (reason) { setError(String(reason)); setCancelling(false) }
  }

  const installing = !status?.installed || repair || status.update_available
  const step = progressStep(progress?.stage)
  const fraction = progress?.total_bytes ? Math.min(1, (progress.completed_bytes ?? 0) / progress.total_bytes) : null
  const eta = progress?.bytes_per_second && progress.total_bytes ? Math.ceil((progress.total_bytes - (progress.completed_bytes ?? 0)) / progress.bytes_per_second) : null
  const heading = busy ? installing ? 'Making room for your companion.' : 'Welcome back.' : repair ? 'A fresh start for the runtime.' : status?.update_available ? 'A new Luna is ready.' : status?.installed ? 'Welcome back.' : 'A little space for someone new.'

  return <div className="launcher-shell">
    <div className="launcher-window-handle" data-tauri-drag-region>
      <div className="launcher-window-actions">
        <WindowButton label="Minimize" onClick={() => void getCurrentWindow().minimize()}><Minus /></WindowButton>
        <WindowButton label="Maximize" onClick={() => void getCurrentWindow().toggleMaximize()}><Square /></WindowButton>
        <WindowButton close label="Close" onClick={() => void getCurrentWindow().close()}><X /></WindowButton>
      </div>
    </div>
    <main className="launcher-body">
      <div className="launcher-intro">
        <div className="launcher-brand"><LunaMark className="size-9 text-primary" /><span>Luna <small>Harness</small></span></div>
        <div aria-hidden="true" className="launcher-portrait"><LunaMark /></div>
      </div>
      <div className="launcher-content">
        <div className="launcher-main-content">
          <h1 className="launcher-heading">{heading}</h1>
          <p className="launcher-description">{repair ? 'Reinstall Luna’s files while keeping your character, connections and memories. Stop your companion in System first.' : status?.update_available ? 'Update the runtime, then carry on where you left off. Your personal data stays here.' : status?.installed ? 'Your dashboard is right here. Settle in.' : 'Luna sets everything up here. Then you’ll choose a model and bring your companion to life.'}</p>

          {busy && <section aria-label="Setup progress" className="launcher-progress">
            <div className="flex items-start justify-between gap-4"><p className="text-sm font-medium" role="status">{cancelling ? 'Stopping safely…' : progress?.detail || 'Preparing Luna…'}</p><span className="shrink-0 text-xs tabular-nums text-muted-foreground">{Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, '0')}</span></div>
            <div aria-label={progress?.stage === 'download' ? 'Runtime download' : 'Current setup step'} aria-valuemax={100} aria-valuemin={0} aria-valuenow={fraction === null ? undefined : Math.round(fraction * 100)} className="launcher-progress-track" role="progressbar">
              <div className={fraction === null ? 'is-pending' : ''} style={{ width: fraction === null ? '100%' : `${fraction * 100}%` }} />
            </div>
            {fraction !== null && <div className="flex flex-wrap justify-between gap-2 text-xs tabular-nums text-muted-foreground"><span>{formatBytes(progress?.completed_bytes ?? 0)} of {formatBytes(progress?.total_bytes ?? 0)}</span><span>{progress?.bytes_per_second ? `${formatBytes(progress.bytes_per_second)}/s` : ''}{eta && eta > 0 ? ` · About ${eta < 60 ? `${eta}s` : `${Math.ceil(eta / 60)} min`} left` : ''}</span></div>}
            {installing && <ol className="launcher-step-list">{steps.map((label, index) => <li data-state={index < step ? 'done' : index === step ? 'current' : 'pending'} key={label}><span className="launcher-step-icon">{index < step ? <Check /> : index === step ? <LoaderCircle className="animate-spin" /> : <span />}</span><span>{label}</span></li>)}</ol>}
          </section>}

          {error && <div className="launcher-error" role="alert"><h2 className="mb-2 text-sm font-semibold">Luna needs a moment</h2><p className="text-sm leading-6">{error}</p><p className="mt-3 text-xs text-muted-foreground">Your character and memories are safe. Retry to continue setup.</p></div>}

          <div className="launcher-primary-actions">{busy ? <Button disabled={cancelling || !!preview} onClick={() => void cancel()} outlined>{cancelling ? 'Stopping…' : 'Cancel'}</Button> : <Button className="launcher-primary" disabled={(!status && !error) || !!preview} onClick={() => void start(repair || !!status?.update_available)} suffix={error ? <RefreshCw /> : installing ? <Download /> : <ArrowRight />}>{!status && !error ? 'Checking installation…' : error ? 'Try again' : repair ? 'Repair Luna' : status?.update_available ? 'Install update' : status?.installed ? 'Open Luna' : 'Install Luna'}</Button>}
            {!busy && status?.installed && (repair || status.update_available || error) && <Button disabled={!!preview} ghost onClick={() => void start(false)}>Open current version</Button>}
          </div>
          {!busy && !error && !status?.installed && <p className="launcher-reassurance"><ShieldCheck className="size-4" />Verified downloads. Your data stays on your computer.</p>}
          {!busy && error && !repair && <Button disabled={!!preview} ghost onClick={() => { setRepair(true); setError(''); setProgress(null) }} size="sm">Repair installation</Button>}
        </div>
        <footer className="launcher-footer"><span>{status?.available ? `Luna ${status.available}` : 'Luna Harness'}</span><div className="launcher-settings-anchor">
          <Button aria-controls="launcher-settings" aria-expanded={settings} aria-haspopup="dialog" ghost onClick={() => setSettings(value => !value)} prefix={<Settings2 />} ref={settingsButtonRef} size="sm" suffix={<ChevronDown className={settings ? '' : 'rotate-180'} />}>Launcher settings</Button>
          {settings && <div aria-label="Launcher settings" className="launcher-settings" id="launcher-settings" ref={settingsRef} role="dialog">
            <div className="launcher-settings-heading"><h2>Launcher settings</h2><Button aria-label="Close launcher settings" ghost onClick={() => { setSettings(false); settingsButtonRef.current?.focus() }} size="icon"><X /></Button></div>
            <DesktopControls preview={!!preview} runtimeBusy={busy} />
          </div>}
        </div></footer>
      </div>
    </main>
  </div>
}

function WindowButton({ label, onClick, close = false, children }: { label: string; onClick: () => void; close?: boolean; children: React.ReactNode }) {
  return <button aria-label={label} className={`launcher-window-button${close ? ' is-close' : ''}`} onClick={preview ? undefined : onClick} type="button">{children}</button>
}
