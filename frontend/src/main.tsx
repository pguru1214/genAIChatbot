import React from 'react'
import { createRoot } from 'react-dom/client'
import { MotionConfig } from 'motion/react'
import './style.css'
import { App } from './App'
import { ToastProvider } from './components/Toasts'

createRoot(document.getElementById('root')!).render(<React.StrictMode>
  <MotionConfig reducedMotion="user"><ToastProvider><App /></ToastProvider></MotionConfig>
</React.StrictMode>)
