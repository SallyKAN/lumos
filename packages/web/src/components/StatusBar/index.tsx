/**
 * StatusBar 组件
 *
 * 状态栏，显示当前模式、处理状态、暂停/恢复按钮
 * 采用 OpenClaw 风格
 */

import { useSessionStore, useChatStore } from '../../stores';
import clsx from 'clsx';

interface StatusBarProps {
  onSwitchMode: (mode: string) => void;
  onPause?: () => void;
  onResume?: () => void;
}

export function StatusBar({ onSwitchMode, onPause, onResume }: StatusBarProps) {
  const { mode } = useSessionStore();
  const { isProcessing, isPaused, pausedTask, interruptResult } = useChatStore();

  const modes = [
    { value: 'BUILD', label: '构建', icon: (
      <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M11.42 15.17L17.25 21A2.652 2.652 0 0021 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 11-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 004.486-6.336l-3.276 3.277a3.004 3.004 0 01-2.25-2.25l3.276-3.276a4.5 4.5 0 00-6.336 4.486c.091 1.076-.071 2.264-.904 2.95l-.102.085m-1.745 1.437L5.909 7.5H4.5L2.25 3.75l1.5-1.5L7.5 4.5v1.409l4.26 4.26m-1.745 1.437l1.745-1.437m6.615 8.206L15.75 15.75M4.867 19.125h.008v.008h-.008v-.008z" />
      </svg>
    )},
    { value: 'PLAN', label: '规划', icon: (
      <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25zM6.75 12h.008v.008H6.75V12zm0 3h.008v.008H6.75V15zm0 3h.008v.008H6.75V18z" />
      </svg>
    )},
    { value: 'REVIEW', label: '审查', icon: (
      <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    )},
  ];

  return (
    <div className="flex items-center justify-between px-4 py-2 mt-auto border-t border-border bg-panel text-sm">
      {/* 左侧：模式切换 */}
      <div className="flex items-center gap-1 bg-secondary rounded-full p-1">
        {modes.map((m) => (
          <button
            key={m.value}
            onClick={() => {
              if (mode !== m.value) {
                onSwitchMode(m.value);
              }
            }}
            disabled={mode === m.value}
            className={clsx(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-all duration-fast',
              mode === m.value
                ? 'bg-accent text-white shadow-sm'
                : 'text-text-muted hover:text-text hover:bg-bg-hover'
            )}
          >
            {m.icon}
            {m.label}
          </button>
        ))}
      </div>

      {/* 中间：处理状态和暂停/恢复按钮 */}
      <div className="flex items-center gap-3">
        {/* 暂停状态 */}
        {isPaused && (
          <div className="flex items-center gap-2">
            <div className="pill text-warn border-warn-subtle bg-warn-subtle">
              <span className="w-1.5 h-1.5 rounded-full bg-warn" />
              <span className="text-xs">
                已暂停{pausedTask ? `: ${pausedTask.slice(0, 20)}...` : ''}
              </span>
            </div>
            {onResume && (
              <button
                onClick={onResume}
                className="btn primary text-xs px-3 py-1"
              >
                恢复
              </button>
            )}
          </div>
        )}

        {/* 处理中状态 */}
        {isProcessing && !isPaused && (
          <div className="flex items-center gap-2">
            <div className="pill">
              <span className="statusDot" style={{ width: '6px', height: '6px' }} />
              <span className="text-xs text-warn">处理中...</span>
            </div>
            {onPause && (
              <button
                onClick={onPause}
                className="btn text-xs px-3 py-1 text-warn border-warn-subtle hover:bg-warn-subtle"
              >
                暂停
              </button>
            )}
          </div>
        )}

        {/* 中断结果提示 (Toast) */}
        {interruptResult && interruptResult.message && (
          <div
            className={clsx(
              'pill animate-fade-in',
              interruptResult.success
                ? 'bg-info text-white border-info'
                : 'bg-danger text-white border-danger'
            )}
          >
            <span className="text-xs">{interruptResult.message}</span>
          </div>
        )}
      </div>

      {/* 右侧：留空或放其他控件 */}
      <div className="w-[200px]" />
    </div>
  );
}
