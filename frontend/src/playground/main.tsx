import { createRoot } from 'react-dom/client'
import '../ui/tokens.css'

const rootElement = document.getElementById('root')

if (rootElement) {
  createRoot(rootElement).render(<div className="qg-light">queryglot</div>)
}
