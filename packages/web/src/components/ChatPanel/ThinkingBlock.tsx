/**
 * ThinkingBlock 组件
 *
 * 可折叠的思考内容显示组件
 * 用于展示模型的推理过程
 */

import { useState } from 'react';
import clsx from 'clsx';

interface ThinkingBlockProps {
  content: string;
  isStreaming?: boolean;
}

export function ThinkingBlock({ content, isStreaming = false }: ThinkingBlockProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  if (!content) {
    return null;
  }

  // 生成摘要（显示前 50 个字符）
  const summary = content.length > 50 
    ? content.slice(0, 50) + '...' 
    : content;

  return (
    <div className="chat-thinking-block animate-rise mb-2">
      <div
        className="cursor-pointer p-2 rounded-lg bg-secondary/50 border border-border/50 hover:bg-secondary transition-colors"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-2">
          {/* 思考图标 */}
          <span className="w-5 h-5 rounded bg-accent/10 text-accent flex items-center justify-center text-xs">
            <svg 
              className={clsx("w-3 h-3", isStreaming && "animate-pulse")} 
              fill="none" 
              stroke="currentColor" 
              viewBox="0 0 24 24" 
              strokeWidth={2}
            >
              <path 
                strokeLinecap="round" 
                strokeLinejoin="round" 
                d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" 
              />
            </svg>
          </span>
          
          <span className="text-sm text-text-muted">
            {isExpanded ? '思考过程' : '查看思考过程'}
          </span>
          
          {/* 展开/收起指示器 */}
          <span className="text-text-muted text-xs ml-auto">
            {isExpanded ? '▲' : '▼'}
          </span>
        </div>
        
        {/* 收起状态下显示摘要 */}
        {!isExpanded && (
          <div className="mt-1 text-xs text-text-muted/70 truncate pl-7">
            {summary}
          </div>
        )}
      </div>
      
      {/* 展开后的完整内容 */}
      {isExpanded && (
        <div className="mt-1 p-3 rounded-lg bg-secondary/30 border border-border/30">
          <pre className={clsx(
            "text-xs text-text-muted whitespace-pre-wrap font-sans leading-relaxed",
            isStreaming && "animate-pulse"
          )}>
            {content}
          </pre>
        </div>
      )}
    </div>
  );
}
