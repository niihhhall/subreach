import React, { useState, Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'
import { BrowserRouter, Routes, Route, useLocation } from 'react-router-dom'
import { Icon } from '@iconify/react'
import { Sidebar } from './components/layout/Sidebar'
import { Header } from './components/layout/Header'
import { ConnectionScreen } from './components/auth/ConnectionScreen'
import { useLeads } from './hooks/useLeads'
import { useRealtime } from './hooks/useRealtime'
import { hasValidConfig, updateSupabaseConfig, disconnect } from './lib/api'

// Pages
import Overview from './pages/Overview'
import Leads from './pages/Leads'
import Review from './pages/Review'
import Handoffs from './pages/Handoffs'
import AgentPerformance from './pages/AgentPerformance'
import Scout from './pages/Scout'
import Accounts from './pages/Accounts'

// Error Boundary Component
class ErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean, error: Error | null }> {
  constructor(props: { children: ReactNode }) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("Uncaught error:", error, errorInfo)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-bg-base flex flex-col items-center justify-center p-6">
          <div className="card p-8 lg:p-10 max-w-xl w-full animate-fade-up">
            <div className="w-12 h-12 rounded-2xl bg-red-50 border border-red-100 flex items-center justify-center mb-6">
              <Icon icon="solar:danger-triangle-bold" width="24" style={{ color: '#dc2626' }} />
            </div>
            <h1 className="text-2xl font-bold text-ink mb-2 tracking-tight">Something went wrong</h1>
            <p className="text-sm text-ink-muted mb-6">An unexpected error occurred in the application core.</p>
            <div className="bg-bg-elevated p-5 rounded-xl border border-border mb-8 overflow-auto max-h-60">
              <code className="text-xs text-red-500">{this.state.error?.toString()}</code>
            </div>
            <button
              onClick={() => {
                localStorage.clear()
                window.location.href = '/'
              }}
              className="btn-premium w-full"
            >
              Reset & Reconnect
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

const AppContent: React.FC = () => {
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)
  const [isCollapsed, setIsCollapsed] = useState(() => {
    return localStorage.getItem('sidebar_collapsed') === 'true'
  })
  const [isConnectedToSupabase, setIsConnectedToSupabase] = useState(hasValidConfig())

  const toggleCollapse = () => {
    setIsCollapsed(prev => {
      const next = !prev
      localStorage.setItem('sidebar_collapsed', String(next))
      return next
    })
  }

  const isConfigured = isConnectedToSupabase

  // Hooks are called but internal logic in hooks now respects connection state
  const { leads, isLoading, refetch } = useLeads()
  const { isConnected, lastUpdated } = useRealtime(refetch)
  const location = useLocation()

  if (!isConfigured) {
    return (
      <ConnectionScreen
        onConnect={(url, key) => {
          updateSupabaseConfig(url, key)
          setIsConnectedToSupabase(true)
        }}
      />
    )
  }

  const getTitle = () => {
    switch (location.pathname) {
      case '/': return 'Overview'
      case '/leads': return 'Leads'
      case '/review': return 'Review Queue'
      case '/handoffs': return 'Handoffs'
      case '/scout': return 'Subreddit Scout'
      case '/performance': return 'Performance'
      case '/accounts': return 'Accounts'
      default: return 'Reddit Outreach'
    }
  }

  const handleLogout = () => {
    disconnect()
    window.location.reload()
  }

  return (
    <div className="h-screen flex overflow-hidden bg-bg-base font-sans selection:bg-brand/20 selection:text-ink relative">
      <div className="neural-overlay" />

      <Sidebar
        isOpen={isSidebarOpen}
        setIsOpen={setIsSidebarOpen}
        onLogout={handleLogout}
        isCollapsed={isCollapsed}
        onToggleCollapse={toggleCollapse}
      />

      <main className="flex-1 flex flex-col min-w-0 overflow-hidden relative z-10">
        <title>MarkEye | Lead Intelligence Dashboard</title>
        <Header
          title={getTitle()}
          isConnected={isConnected}
          lastUpdated={lastUpdated}
          leadsCount={leads.length}
          onToggleMenu={() => setIsSidebarOpen(true)}
        />

        <div className="flex-1 overflow-y-auto custom-scrollbar bg-transparent">
          <Routes>
            <Route path="/" element={<Overview leads={leads} isLoading={isLoading} />} />
            <Route path="/leads" element={<Leads leads={leads} isLoading={isLoading} refetch={refetch} />} />
            <Route path="/review" element={<Review />} />
            <Route path="/handoffs" element={<Handoffs leads={leads} isLoading={isLoading} />} />
            <Route path="/accounts" element={<Accounts />} />
            <Route path="/scout" element={<Scout />} />
            <Route path="/performance" element={<AgentPerformance />} />
          </Routes>
        </div>
      </main>
    </div>
  )
}


const App: React.FC = () => {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <AppContent />
      </BrowserRouter>
    </ErrorBoundary>
  )
}

export default App
