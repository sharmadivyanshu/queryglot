import { createRoot } from 'react-dom/client'
import '../ui/tokens.css'
import './tailwind.css'
import '../widget/panel.css'
import App from './App'

const rootElement = document.getElementById('root')

if (rootElement) {
  createRoot(rootElement).render(<App />)
}
