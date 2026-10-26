import './styles.css'

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import App from './app.tsx'
import { watchTheme } from './theme'

// Paint Sakura Dusk first, then follow the dashboard's saved theme and font.
createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>
  )

// Theme I/O must never delay the first useful screen.
if (!(import.meta.env.DEV && new URLSearchParams(location.search).has('preview'))) {void watchTheme()}
