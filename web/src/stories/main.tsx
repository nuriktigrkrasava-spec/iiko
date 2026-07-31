import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import Stories from './Stories'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Stories />
  </StrictMode>,
)
