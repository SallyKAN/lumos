/**
 * App 主组件
 *
 * 应用主布局，整合所有组件
 * 采用 OpenClaw 风格的 Shell 布局
 */

import { useState, useCallback, useEffect, Component, ReactNode } from 'react';
import { ChatPanel } from './components/ChatPanel';
import { SessionSidebar } from './components/SessionSidebar';
import { SkillPanel } from './components/SkillPanel';
import { ToolPanel } from './components/ToolPanel';
import { StatusBar } from './components/StatusBar';
import { UserQuestionModal } from './components/UserQuestionModal';
import { useWebSocket } from './hooks';
import { useSessionStore, useChatStore, useTodoStore } from './stores';

// 错误边界组件
interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class ErrorBoundary extends Component<
  { children: ReactNode },
  ErrorBoundaryState
> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('React Error:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex items-center justify-center h-screen bg-bg text-text p-8">
          <div className="max-w-2xl card">
            <h1 className="text-2xl font-bold text-danger mb-4">
              应用加载出错
            </h1>
            <p className="text-text-muted mb-4">
              {this.state.error?.message || '未知错误'}
            </p>
            <pre className="bg-secondary p-4 rounded-lg text-sm overflow-auto max-h-64 font-mono">
              {this.state.error?.stack}
            </pre>
            <button
              onClick={() => window.location.reload()}
              className="btn primary mt-4"
            >
              刷新页面
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

// 服务端配置
interface ServerConfig {
  provider: string;
  model: string | null;
  api_base: string | null;
  has_api_key: boolean;
}

// 主题切换组件
function ThemeToggle() {
  const [theme, setTheme] = useState(() => {
    return localStorage.getItem('theme') || 'light';
  });

  const toggleTheme = (newTheme: string) => {
    setTheme(newTheme);
    localStorage.setItem('theme', newTheme);
    if (newTheme === 'light') {
      document.documentElement.setAttribute('data-theme', 'light');
    } else {
      document.documentElement.removeAttribute('data-theme');
    }
  };

  const themeIndex = theme === 'dark' ? 0 : theme === 'system' ? 1 : 2;

  return (
    <div className="theme-toggle">
      <div className="theme-toggle__track" style={{ '--theme-index': themeIndex } as React.CSSProperties}>
        <div className="theme-toggle__indicator" />
        <button
          className={`theme-toggle__button ${theme === 'dark' ? 'active' : ''}`}
          onClick={() => toggleTheme('dark')}
          title="深色模式"
        >
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
          </svg>
        </button>
        <button
          className={`theme-toggle__button ${theme === 'system' ? 'active' : ''}`}
          onClick={() => toggleTheme('system')}
          title="跟随系统"
        >
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
            <line x1="8" y1="21" x2="16" y2="21" />
            <line x1="12" y1="17" x2="12" y2="21" />
          </svg>
        </button>
        <button
          className={`theme-toggle__button ${theme === 'light' ? 'active' : ''}`}
          onClick={() => toggleTheme('light')}
          title="浅色模式"
        >
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="5" />
            <line x1="12" y1="1" x2="12" y2="3" />
            <line x1="12" y1="21" x2="12" y2="23" />
            <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
            <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
            <line x1="1" y1="12" x2="3" y2="12" />
            <line x1="21" y1="12" x2="23" y2="12" />
            <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
            <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
          </svg>
        </button>
      </div>
    </div>
  );
}

// 会话 ID 持久化
const SESSION_STORAGE_KEY = 'lumos_current_session';

function getStoredSessionId(): string | null {
  try {
    return localStorage.getItem(SESSION_STORAGE_KEY);
  } catch {
    return null;
  }
}

function storeSessionId(sessionId: string | null) {
  try {
    if (sessionId && sessionId !== 'new') {
      localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
    } else {
      localStorage.removeItem(SESSION_STORAGE_KEY);
    }
  } catch {
    // ignore
  }
}

function AppContent() {
  // 优先使用存储的会话 ID，避免每次刷新创建新会话
  const [sessionId, setSessionId] = useState<string>(() => {
    const stored = getStoredSessionId();
    return stored || 'new';
  });
  const [activeNav, setActiveNav] = useState<'chat' | 'skills'>('chat');
  const [serverConfig, setServerConfig] = useState<ServerConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [initialConnect, setInitialConnect] = useState(true);
  const { setCurrentSession, setSessions } = useSessionStore();
  const { clearMessages, isProcessing } = useChatStore();
  const { clearTodos } = useTodoStore();

  // 获取服务端配置（只执行一次）
  useEffect(() => {
    const fetchConfig = async () => {
      try {
        // 使用相对路径，通过 Vite proxy 转发
        const response = await fetch('/api/config');
        if (response.ok) {
          const config = await response.json();
          console.log('Server config:', config);
          setServerConfig(config);
          setConfigError(null);
        } else {
          setServerConfig({ provider: 'openai', model: null, api_base: null, has_api_key: false });
          setConfigError(`后端配置接口错误 (${response.status})，已使用默认配置`);
        }
      } catch (error) {
        console.error('Failed to fetch config:', error);
        // 使用默认配置
        setServerConfig({ provider: 'openai', model: null, api_base: null, has_api_key: false });
        setConfigError('无法连接后端配置接口，已使用默认配置');
      }
    };
    fetchConfig();
  }, []);

  // WebSocket 连接 - 使用服务端配置的 provider
  const {
    isConnected,
    sendMessage,
    interrupt,
    pause,
    resume,
    switchMode,
    sendUserAnswer,
  } = useWebSocket({
    sessionId,
    provider: serverConfig?.provider || 'openai',
    onConnect: (payload) => {
      console.log('Connected to session:', payload.session_id);
      setSessionId(payload.session_id);
      storeSessionId(payload.session_id);
      // 每次连接成功后都刷新会话列表，确保新会话出现在侧边栏
      fetchSessions();
      if (initialConnect) {
        setInitialConnect(false);
      }
    },
    onDisconnect: () => {
      console.log('Disconnected');
    },
    onError: (error) => {
      console.error('WebSocket error:', error);
    },
  });

  // 获取会话列表
  const fetchSessions = useCallback(async () => {
    try {
      const response = await fetch('/api/sessions?limit=20');
      if (response.ok) {
        const data = await response.json();
        setSessions(data.sessions || []);
      }
    } catch (error) {
      console.error('Failed to fetch sessions:', error);
    }
  }, [setSessions]);

  // 新建会话
  const handleNewSession = useCallback(() => {
    // 清除旧会话的消息和Todo
    clearMessages();
    clearTodos();
    setSessionId('new');
    setCurrentSession(null);
    storeSessionId(null);
  }, [clearMessages, clearTodos, setCurrentSession]);

  // 切换模式
  const handleSwitchMode = useCallback((mode: string) => {
    switchMode(mode);
  }, [switchMode]);

  const handleNavigate = useCallback((nav: 'chat' | 'skills') => {
    setActiveNav(nav);
  }, []);

  return (
    <div className="shell">
      {/* Topbar */}
      <header className="topbar">
        <div className="flex items-center gap-4">
          <div className="brand">
            <img src="/logo.png" alt="Lumos" className="brand-logo-img" />
            <div className="brand-text">
              <span className="brand-title">Jiuwen Bot</span>
              <span className="brand-sub">AI Assistant</span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* 连接状态 */}
          <div className="pill">
            <span className={`statusDot ${isConnected ? 'ok' : ''}`} />
            <span className="mono text-sm">
              {isConnected ? '已连接' : '未连接'}
            </span>
          </div>

          {/* 主题切换 */}
          <ThemeToggle />
        </div>
      </header>

      {/* Navigation Sidebar */}
      <SessionSidebar
        activeNav={activeNav}
        onNavigate={handleNavigate}
        sessionId={sessionId}
      />

      {/* Main Content */}
      <main className="content">
        {configError && (
          <div className="card mb-4">
            <div className="text-sm text-text-muted">
              {configError}。如果后端不在本机 `8000` 端口，可在
              <span className="mono"> packages/web/.env.local </span>
              设置 `VITE_API_BASE` 和 `VITE_WS_BASE`。
            </div>
          </div>
        )}

        {activeNav === 'chat' ? (
          <>
            <div className="flex-1 flex overflow-hidden gap-4">
              {/* Chat Panel */}
              <div className="flex-1 flex flex-col min-w-0">
                <ChatPanel
                  onSendMessage={sendMessage}
                  onInterrupt={interrupt}
                  isProcessing={isProcessing}
                  onNewSession={handleNewSession}
                />
              </div>

              {/* Tool Panel */}
              <ToolPanel />
            </div>

            {/* Status Bar */}
            <StatusBar
              onSwitchMode={handleSwitchMode}
              onPause={pause}
              onResume={resume}
            />
          </>
        ) : (
          <div className="flex-1 flex overflow-hidden gap-4">
            <SkillPanel />
          </div>
        )}
      </main>

      {/* 连接状态提示 */}
      {!isConnected && (
        <div className="fixed bottom-20 left-1/2 transform -translate-x-1/2 bg-danger text-white px-4 py-2 rounded-lg shadow-lg animate-rise z-50">
          {serverConfig ? '正在连接服务器...' : '加载配置中...'}
        </div>
      )}

      {/* 用户问题弹窗 */}
      <UserQuestionModal onSubmit={sendUserAnswer} />
    </div>
  );
}

function App() {
  return (
    <ErrorBoundary>
      <AppContent />
    </ErrorBoundary>
  );
}

export default App;
