import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'
import { getCurrentWindow } from '@tauri-apps/api/window'

import { migrateThemeName } from '../../../web/src/themes/aliases'
import { BUILTIN_THEMES, defaultTheme } from '../../../web/src/themes/presets'
import { indexUserThemeDefs } from '../../../web/src/themes/theme-list'
import { applyTheme, setFontOverride } from '../../../web/src/themes/theme-runtime'
import type { ThemeListResponse } from '../../../web/src/themes/types'

// Sakura Dusk is the default before saved preferences arrive in either window.
applyTheme(defaultTheme)

export async function watchTheme(): Promise<void> {
  let refreshing = false
  let previous = ''

  const refresh = async () => {
    if (refreshing) { return }
    refreshing = true

    try {
      const report = await invoke<{ themes: ThemeListResponse; font: string }>('luna_desktop_appearance')
      const revision = JSON.stringify(report)

      if (revision === previous) { return }
      const definitions = indexUserThemeDefs(report.themes.themes ?? [])
      const name = migrateThemeName(report.themes.active ?? 'sakura-dusk', new Set(Object.keys(definitions)))
      const theme = BUILTIN_THEMES[name] ?? definitions[name] ?? defaultTheme
      setFontOverride(report.font ?? 'theme')
      applyTheme(theme)
      previous = revision
      await invoke('luna_window_appearance', { dark: theme.colorScheme !== 'light' })
    } catch {
      // The bundled fallback still works while a backend is starting or stopped.
    } finally { refreshing = false }
  }

  await refresh()
  await listen('luna-dashboard-ready', () => void refresh())
  await getCurrentWindow().onFocusChanged(({ payload }) => { if (payload) { void refresh() } })
  window.setInterval(() => void refresh(), 5000)
}
