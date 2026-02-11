/**
 * ToolPanel 组件
 *
 * 工具面板，显示可用工具和 Todo 列表
 * 采用 OpenClaw 风格
 */

import { useSessionStore } from '../../stores';
import { TodoList } from '../TodoList';

export function ToolPanel() {
  const { availableTools } = useSessionStore();

  return (
    <div className="w-72 bg-panel border-l border-border flex flex-col h-full overflow-hidden">
      {/* Todo 列表 */}
      <div className="flex-1 overflow-y-auto border-b border-border">
        <TodoList />
      </div>

      {/* 可用工具 */}
      <div className="p-4 overflow-y-auto max-h-48">
        <h3 className="text-[11px] font-medium text-text-muted uppercase tracking-wider mb-3">
          可用工具 ({availableTools.length})
        </h3>
        <div className="flex flex-wrap gap-1.5">
          {availableTools.map((tool) => (
            <span
              key={tool}
              className="px-2 py-1 bg-secondary text-text-muted text-xs rounded-md border border-border hover:border-border-strong transition-colors cursor-default"
            >
              {tool}
            </span>
          ))}
          {availableTools.length === 0 && (
            <span className="text-text-muted text-xs">无可用工具</span>
          )}
        </div>
      </div>
    </div>
  );
}
