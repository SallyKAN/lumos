/**
 * ChatPanel 组件
 *
 * 聊天面板，包含消息列表和输入区域
 * 采用 OpenClaw 风格
 */

import { useRef, useEffect } from 'react';
import { useChatStore } from '../../stores';
import { MessageList } from './MessageList';
import { InputArea } from './InputArea';
import { SubtaskProgress } from './SubtaskProgress';

interface ChatPanelProps {
  onSendMessage: (content: string) => void;
  onInterrupt: (newInput?: string) => void;
  isProcessing: boolean;
  onNewSession: () => void;
}

/**
 * 思考中指示器组件
 * 显示 OpenClaw 风格的动画点
 */
function ThinkingIndicator() {
  return (
    <div className="flex justify-start animate-rise">
      <div className="chat-bubble assistant chat-reading-indicator">
        <div className="chat-reading-indicator__dots">
          <span />
          <span />
          <span />
        </div>
      </div>
    </div>
  );
}

export function ChatPanel({ onSendMessage, onInterrupt, isProcessing, onNewSession }: ChatPanelProps) {
  const { messages, isThinking } = useChatStore();
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isThinking]);

  return (
    <div className="flex flex-col h-full">
      {/* 消息列表 */}
      <div className="flex-1 overflow-y-auto px-3 py-4">
        {messages.length === 0 ? (
          <div className="h-full flex items-center justify-center">
            <div className="text-center max-w-md animate-rise">
              <div className="w-16 h-16 mx-auto mb-6 rounded-xl bg-gradient-to-br from-accent to-accent-2 flex items-center justify-center">
                <svg className="w-8 h-8 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456z" />
                </svg>
              </div>
              <h2 className="text-xl font-semibold text-text-strong mb-2">
                开始新对话
              </h2>
              <p className="text-text-muted text-sm leading-relaxed">
                输入你的问题或需求，我会尽力帮助你完成编程任务。
                <br />
                支持代码编写、调试、解释等功能。
              </p>
            </div>
          </div>
        ) : (
          <>
            <MessageList messages={messages} />
            {/* 子任务进度 */}
            <SubtaskProgress />
            {/* 思考中指示器 */}
            {isThinking && <ThinkingIndicator />}
          </>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* 输入区域 */}
      <div className="chat-compose px-3 pb-4">
        <InputArea
          onSubmit={onSendMessage}
          onInterrupt={onInterrupt}
          isProcessing={isProcessing}
          onNewSession={onNewSession}
        />
      </div>
    </div>
  );
}
