import React from 'react'
import ReactDOM from 'react-dom/client'
import '@fontsource/noto-serif-sc/500.css'
import '@fontsource/noto-serif-sc/700.css'
import './index.css'

async function boot() {
  if (import.meta.env.VITE_USE_MOCK === '1') {
    const { installMock } = await import('./mocks')
    installMock()
  }
  const { App } = await import('./App')
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  )
}
boot()
