import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './ui.css'
import './encyclopedia.css'
import './page-layout.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
