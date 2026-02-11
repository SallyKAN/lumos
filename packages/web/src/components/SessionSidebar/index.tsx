/**
 * SessionSidebar 组件
 *
 * 会话侧边栏，显示会话列表
 * 采用 OpenClaw 风格
 */

import { OffloadFilesWidget } from './OffloadFilesWidget';

type MainNavKey = 'chat' | 'skills';

interface SessionSidebarProps {
  activeNav: MainNavKey;
  onNavigate: (nav: MainNavKey) => void;
  sessionId: string;
}

export function SessionSidebar({
  activeNav,
  onNavigate,
  sessionId,
}: SessionSidebarProps) {

  return (
    <aside className="nav flex flex-col">
      <div className="text-[11px] font-medium text-text-muted uppercase tracking-wider px-2.5 mb-2">
        对话
      </div>
      <div className="space-y-1 mb-4">
        <button
          onClick={() => onNavigate('chat')}
          className={`nav-item w-full ${activeNav === 'chat' ? 'active' : ''}`}
        >
          <svg className="w-4 h-4 nav-item__icon" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
          </svg>
          对话
        </button>
      </div>

      <div className="text-[11px] font-medium text-text-muted uppercase tracking-wider px-2.5 mb-2">
        Agent
      </div>
      <div className="space-y-1">
        <button
          onClick={() => onNavigate('skills')}
          className={`nav-item w-full ${activeNav === 'skills' ? 'active' : ''}`}
        >
          <svg className="w-4 h-4 nav-item__icon" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 11.25V6.75m0 4.5H9m6 0H9m6 0v4.5m-6-4.5v4.5m9 4.5H6.75A2.25 2.25 0 014.5 17.25V6.75A2.25 2.25 0 016.75 4.5h10.5A2.25 2.25 0 0119.5 6.75v10.5A2.25 2.25 0 0117.25 19.5z" />
          </svg>
          Skills
        </button>
      </div>

      <div className="flex-1" />

      {false && <OffloadFilesWidget sessionId={sessionId} />}

      <div className="pt-4 mt-4 border-t border-border text-xs text-text-muted">
        <div className="px-2.5">
          <span>版本 0.1.0</span>
        </div>
      </div>
    </aside>
  );
}
