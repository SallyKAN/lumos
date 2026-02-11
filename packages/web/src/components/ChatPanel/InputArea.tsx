/**
 * InputArea 组件
 *
 * 消息输入区域，支持多行输入、快捷键和语音输入
 * 采用 OpenClaw 风格
 */

import { useState, useRef, useCallback, KeyboardEvent, useEffect } from 'react';
import { useSpeechRecognition } from '../../hooks';
import { stopAllTts } from '../../utils';

interface InputAreaProps {
  onSubmit: (content: string) => void;
  onInterrupt: (newInput?: string) => void;
  isProcessing: boolean;
  onNewSession: () => void;
}

export function InputArea({ onSubmit, onInterrupt, isProcessing, onNewSession }: InputAreaProps) {
  const [value, setValue] = useState('');
  const [pendingVoiceText, setPendingVoiceText] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const autoSendTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 语音识别 - 使用 cmn-Hans-CN（普通话-简体中文）获得更准确的简体结果
  const {
    isListening,
    interimTranscript,
    startListening,
    stopListening,
    isSupported: speechSupported,
  } = useSpeechRecognition({
    language: 'cmn-Hans-CN', // 普通话简体中文
    continuous: true, // 持续识别，允许中间停顿
    interimResults: true,
    silenceTimeoutMs: 8000, // 停顿 8 秒后才结束识别
    onResult: (text, isFinal) => {
      if (isFinal) {
        setPendingVoiceText((prev) => prev + text);
      }
    },
    onEnd: () => {
      // 语音结束时，触发自动发送（稍作延迟以确保最后的文本已处理）
      autoSendTimeoutRef.current = setTimeout(() => {
        // 在 timeout 回调中会通过 effect 处理发送
      }, 100);
    },
    onError: (error) => {
      console.error('语音识别错误:', error);
    },
  });

  // 语音结束后自动发送
  useEffect(() => {
    if (!isListening && pendingVoiceText) {
      const finalText = (value + pendingVoiceText).trim();
      if (finalText) {
        // 更新输入框
        setValue(finalText);
        setPendingVoiceText('');
        
        // 自动发送
        setTimeout(() => {
          if (isProcessing) {
            onInterrupt(finalText);
          } else {
            onSubmit(finalText);
          }
          setValue('');
          // 重置高度
          if (textareaRef.current) {
            textareaRef.current.style.height = 'auto';
          }
        }, 150);
      }
    }
  }, [isListening, pendingVoiceText, value, isProcessing, onSubmit, onInterrupt]);

  // 清理 timeout
  useEffect(() => {
    return () => {
      if (autoSendTimeoutRef.current) {
        clearTimeout(autoSendTimeoutRef.current);
      }
    };
  }, []);

  const handleSubmit = useCallback(() => {
    const trimmed = (value + pendingVoiceText).trim();
    if (!trimmed) return;

    // 如果正在录音，先停止
    if (isListening) {
      stopListening();
    }

    if (isProcessing) {
      // 处理中输入 = 发送中断，由后端识别意图
      onInterrupt(trimmed);
    } else {
      onSubmit(trimmed);
    }
    setValue('');
    setPendingVoiceText('');

    // 重置高度
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  }, [value, pendingVoiceText, isProcessing, isListening, onSubmit, onInterrupt, stopListening]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      // Enter 发送（Shift+Enter 换行）
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit]
  );

  const handleInput = useCallback(() => {
    // 自动调整高度
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
    }
  }, []);

  const handleVoiceStart = useCallback(() => {
    if (isListening) {
      return;
    }
    stopAllTts();
    startListening();
  }, [isListening, startListening]);

  const handleVoiceEnd = useCallback(() => {
    if (!isListening) {
      return;
    }
    stopListening();
  }, [isListening, stopListening]);

  const handleNewSession = useCallback(() => {
    if (isListening || isProcessing) {
      return;
    }
    setValue('');
    setPendingVoiceText('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
    onNewSession();
  }, [isListening, isProcessing, onNewSession]);

  // 显示的文本（包括临时识别结果和待发送的语音文本）
  const displayValue = isListening
    ? value + pendingVoiceText + interimTranscript
    : value + pendingVoiceText;

  return (
    <div className="relative">
      {/* 录音状态指示 */}
      {isListening && (
        <div className="absolute left-4 -top-8 flex items-center gap-2 text-xs">
          <span className="w-2 h-2 rounded-full bg-danger animate-pulse" />
          <span className="text-danger">正在录音...（松开按钮自动发送）</span>
        </div>
      )}

      <textarea
        ref={textareaRef}
        value={displayValue}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        onInput={handleInput}
        placeholder={
          isListening
            ? '正在听取语音...'
            : isProcessing
            ? '处理中，输入新指令可中断...'
            : '输入消息，或按住麦克风语音输入...'
        }
        className={clsx(
          'w-full min-h-[72px] max-h-[200px] pr-24 resize-none',
          isListening && 'border-danger'
        )}
        rows={2}
      />

      {/* 按钮组 */}
      <div className="absolute right-3 bottom-3 flex items-center gap-2">
        <button
          onClick={handleNewSession}
          disabled={isListening || isProcessing}
          className={clsx(
            'p-2 rounded-lg transition-all duration-fast',
            isListening || isProcessing
              ? 'bg-secondary text-text-muted cursor-not-allowed opacity-60'
              : 'bg-secondary text-text-muted hover:bg-accent hover:text-white'
          )}
          title={isListening || isProcessing ? '处理中或录音中不可新建' : '新建会话'}
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
        </button>
        {/* 语音输入按钮 */}
        {speechSupported && (
          <button
            onMouseDown={(e) => {
              e.preventDefault();
              handleVoiceStart();
            }}
            onMouseUp={(e) => {
              e.preventDefault();
              handleVoiceEnd();
            }}
            onMouseLeave={(e) => {
              e.preventDefault();
              handleVoiceEnd();
            }}
            onTouchStart={(e) => {
              e.preventDefault();
              handleVoiceStart();
            }}
            onTouchEnd={(e) => {
              e.preventDefault();
              handleVoiceEnd();
            }}
            className={clsx(
              'p-2 rounded-lg transition-all duration-fast',
              isListening
                ? 'bg-danger text-white animate-pulse'
                : 'bg-secondary text-text-muted hover:bg-accent hover:text-white'
            )}
            title="按住说话"
          >
            {isListening ? (
              // 停止图标
              <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
                <rect x="6" y="6" width="12" height="12" rx="2" />
              </svg>
            ) : (
              // 麦克风图标
              <svg
                className="w-5 h-5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                strokeWidth={1.5}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M12 18.75a6 6 0 006-6v-1.5m-6 7.5a6 6 0 01-6-6v-1.5m6 7.5v3.75m-3.75 0h7.5M12 15.75a3 3 0 01-3-3V4.5a3 3 0 116 0v8.25a3 3 0 01-3 3z"
                />
              </svg>
            )}
          </button>
        )}

        {/* 发送按钮 */}
        <button
          onClick={handleSubmit}
          disabled={!value.trim() && !isListening}
          className={clsx(
            'p-2 rounded-lg transition-all duration-fast',
            value.trim()
              ? 'bg-accent text-white hover:bg-accent-hover shadow-sm hover:shadow-md'
              : 'bg-secondary text-text-muted cursor-not-allowed'
          )}
          title="发送 (Enter)"
        >
          <svg
            className="w-5 h-5"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            strokeWidth={1.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5"
            />
          </svg>
        </button>
      </div>

      {/* 快捷键提示 */}
      <div className="absolute left-4 bottom-3 flex items-center gap-3 text-xs text-text-muted">
        <span>
          <kbd className="kbd">Enter</kbd> 发送
        </span>
        <span>
          <kbd className="kbd">Shift</kbd>+<kbd className="kbd">Enter</kbd> 换行
        </span>
      </div>
    </div>
  );
}

// 辅助函数
function clsx(...classes: (string | boolean | undefined)[]) {
  return classes.filter(Boolean).join(' ');
}
