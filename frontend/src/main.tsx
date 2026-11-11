import React from 'react'
import ReactDOM from 'react-dom/client'
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
