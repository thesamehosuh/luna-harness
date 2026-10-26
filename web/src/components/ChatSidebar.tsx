/** Model controls and a passive subscriber to the real chat's events.
 * No throwaway agent/session is created for dashboard chrome. */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { AlertCircle, ChevronDown, Cpu, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { ModelPickerDialog } from '@/components/ModelPickerDialog'
import { ModelReloadConfirm } from '@/components/ModelReloadConfirm'
import { ReasoningPicker } from '@/components/ReasoningPicker'
import { EventsFeedClient } from '@/lib/eventsFeedClient'
import { api } from '@/lib/api'
import { errorMessage } from '@/lib/api-error'
import { EVENTS_MAX_RECONNECT_ATTEMPTS, eventsGaveUpMessage, eventsReconnectDelayMs, eventsReconnectingMessage, eventsRejectedMessage, isEventsAuthRejection, isEventsAuthRejectionMessage, shouldRetryEventsClose } from '@/lib/events-reconnect'
import { credentialWarning } from '@/lib/chat-sidebar-banner'
import { titleFromSessionInfoPayload } from '@/lib/chat-title'
import { cn } from '@/lib/utils'

type SessionInfo = { model?: string; provider?: string; credential_warning?: string; title?: string; stored_session_id?: string }
interface ChatSidebarProps {
  channel: string
  profile?: string
  className?: string
  isActive?: boolean
  onDashboardNewSessionRequest?: () => void
  onSessionTitleChange?: (title: string | null) => void
  onSessionIdChange?: (id: string) => void
  onAssistantResponse?: (text: string) => void
}

export function ChatSidebar({ channel, profile, className, isActive = true, onDashboardNewSessionRequest, onSessionTitleChange, onSessionIdChange, onAssistantResponse }: ChatSidebarProps) {
  const navigate = useNavigate()
  const feed = useMemo(() => new EventsFeedClient(), [])
  const [info, setInfo] = useState<SessionInfo>({})
  const [effectiveModel, setEffectiveModel] = useState('')
  const [supportsReasoning, setSupportsReasoning] = useState(false)
  const [picker, setPicker] = useState(false)
  const [revision, setRevision] = useState(0)
  const [notice, setNotice] = useState('')
  const [feedError, setFeedError] = useState('')
  const [error, setError] = useState('')
  const [pendingModel, setPendingModel] = useState<string | null>(null)
  const callbacks = useRef({ onDashboardNewSessionRequest, onSessionTitleChange, onSessionIdChange, onAssistantResponse })
  callbacks.current = { onDashboardNewSessionRequest, onSessionTitleChange, onSessionIdChange, onAssistantResponse }

  const refresh = useCallback(() => setRevision(value => value + 1), [])
  useEffect(() => {
    if (!isActive) return
    let disposed = false
    api.getModelInfo(profile).then(value => {
      if (disposed) return
      setEffectiveModel(value.model)
      setSupportsReasoning(!!value.capabilities?.supports_reasoning)
    }).catch(() => { /* real session info remains available */ })
    return () => { disposed = true }
  }, [profile, channel, revision, isActive])

  useEffect(() => {
    let disposed = false
    let retry: ReturnType<typeof setTimeout> | undefined
    let attempts = 0
    let opening = false
    let terminalClose = false
    setInfo({})
    setFeedError('')
    const schedule = () => {
      if (disposed || retry || terminalClose) return
      if (attempts >= EVENTS_MAX_RECONNECT_ATTEMPTS) { setFeedError(eventsGaveUpMessage()); return }
      const delay = eventsReconnectDelayMs(attempts++)
      setFeedError(eventsReconnectingMessage(delay))
      retry = setTimeout(() => { retry = undefined; void connect() }, delay)
    }
    const connect = async () => {
      if (disposed || opening) return
      opening = true
      try { await feed.connect(channel) }
      catch { if (!disposed) schedule() }
      finally { opening = false }
    }
    const offClose = feed.onClose(code => {
      if (disposed) return
      if (!shouldRetryEventsClose(code)) terminalClose = true
      if (code !== undefined && isEventsAuthRejection(code)) { setFeedError(eventsRejectedMessage(code)); return }
      if (shouldRetryEventsClose(code)) schedule()
    })
    const offState = feed.onState(state => {
      if (!disposed && state === 'open') { attempts = 0; setFeedError('') }
    })
    const offInfo = feed.on('session.info', event => {
      const payload = event.payload as SessionInfo
      setInfo(payload)
      const title = titleFromSessionInfoPayload(payload)
      if (title !== undefined) callbacks.current.onSessionTitleChange?.(title)
      if (payload.stored_session_id) callbacks.current.onSessionIdChange?.(payload.stored_session_id)
    })
    const offNew = feed.on('dashboard.new_session_requested', () => callbacks.current.onDashboardNewSessionRequest?.())
    const offComplete = feed.on('message.complete', event => {
      if (typeof event.payload?.text === 'string' && event.payload.text.trim()) callbacks.current.onAssistantResponse?.(event.payload.text)
    })
    void connect()
    return () => { disposed = true; if (retry) clearTimeout(retry); offClose(); offState(); offInfo(); offNew(); offComplete(); feed.close() }
  }, [feed, channel, profile, revision])

  const model = info.model || effectiveModel || ''
  const credential = credentialWarning(info.credential_warning)?.message
  const warning = credential || error || feedError
  return <div className={cn('chat-model-controls', className)}>
    <div className="flex min-w-0 flex-wrap items-center gap-2">
      <Button ghost size="sm" aria-label="Choose chat model" onClick={() => setPicker(true)} className="max-w-full gap-2 px-2 font-medium" title={model || 'Choose a model'}><Cpu className="size-4 text-primary" /><span className="max-w-64 truncate">{model.split('/').at(-1) || 'Choose a model'}</span><ChevronDown className="size-3.5 text-muted-foreground" /></Button>
      {supportsReasoning && <ReasoningPicker currentModel={model} profile={profile} refreshKey={revision} onChanged={() => setNotice('Reasoning saved. Start a new chat to use it.')} />}
    </div>
    {(notice || warning) && <div role={warning ? 'alert' : 'status'} className={cn('chat-control-notice', warning && 'text-warning')}><AlertCircle className="mt-0.5 size-4 shrink-0" /><span className="flex-1">{warning || notice}</span>{warning ? <Button ghost size="xs" onClick={credential || error ? () => navigate('/controls#model') : isEventsAuthRejectionMessage(feedError) ? () => window.location.reload() : refresh} prefix={!credential && !error ? <RefreshCw /> : undefined}>{credential || error ? 'Connections' : isEventsAuthRejectionMessage(feedError) ? 'Reload' : 'Reconnect'}</Button> : <Button ghost size="xs" onClick={() => { setNotice(''); callbacks.current.onDashboardNewSessionRequest?.() }}>New chat</Button>}</div>}
    {picker && <ModelPickerDialog alwaysGlobal onFreeModelSelected={() => { refresh(); setNotice("Free model saved. Start a new chat to use it."); }} loader={() => api.getModelOptions(profile)} onClose={() => setPicker(false)} onApply={async ({ provider, model: next, confirmExpensiveModel }) => {
      try {
        const result = await api.setModelAssignment({ scope: 'main', provider, model: next, confirm_expensive_model: confirmExpensiveModel }, profile)
        if (!result.confirm_required) { refresh(); setNotice(''); setPendingModel(next.split('/').at(-1) || next) }
        return result
      } catch (reason) { setError(errorMessage(reason)); throw reason }
    }} />}
    <ModelReloadConfirm model={pendingModel} onCancel={() => { setNotice(`Model saved as ${pendingModel}. Start a new chat to use it.`); setPendingModel(null) }} onConfirm={() => { setPendingModel(null); callbacks.current.onDashboardNewSessionRequest?.() }} />
  </div>
}
