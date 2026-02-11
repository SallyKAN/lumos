/**
 * WebSocket Hook
 *
 * 管理 WebSocket 连接和消息处理
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import {
  MessageType,
  WebSocketMessage,
  ConnectionAckPayload,
  InterruptResultPayload,
  SubtaskUpdatePayload,
  AskUserQuestionPayload,
  UserAnswer,
  MediaItem,
} from '../types';
import { useChatStore, useTodoStore, useSessionStore } from '../stores';
import {
  fetchTtsAudio,
  playAudioBase64,
  sanitizeTtsText,
  stopAllTts,
} from '../utils';

interface UseWebSocketOptions {
  sessionId: string;
  provider?: string;
  apiKey?: string;
  apiBase?: string;
  model?: string;
  projectPath?: string;
  onConnect?: (payload: ConnectionAckPayload) => void;
  onDisconnect?: () => void;
  onError?: (error: string) => void;
}

interface UseWebSocketReturn {
  isConnected: boolean;
  send: (type: MessageType, payload: Record<string, unknown>) => void;
  sendMessage: (content: string) => void;
  interrupt: (newInput?: string) => void;
  pause: () => void;
  resume: () => void;
  switchMode: (mode: string) => void;
  disconnect: () => void;
  sendUserAnswer: (requestId: string, answers: UserAnswer[]) => void;
}

export function useWebSocket(options: UseWebSocketOptions): UseWebSocketReturn {
  const {
    sessionId,
    provider = 'openai',
    apiKey,
    apiBase,
    model,
    projectPath,
    onConnect,
    onDisconnect,
    onError,
  } = options;

  const wsRef = useRef<WebSocket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const maxReconnectAttempts = 5;
  const userInputVersionRef = useRef(0);

  // Stores
  const {
    addMessage,
    appendStreamContent,
    startStreaming,
    stopStreaming,
    updateMessage,
    setProcessing,
    setThinking,
    setPaused,
    setInterruptResult,
    addToolCall,
    addToolResult,
    updateSubtask,
    clearSubtasks,
    clearMessages,
    setPendingQuestion,
  } = useChatStore();
  const { setTodos, clearTodos } = useTodoStore();
  const { setMode, setConnected, setAvailableTools } = useSessionStore();

  // 构建 WebSocket URL
  const buildWsUrl = useCallback(() => {
    // 使用相对路径，通过 Vite proxy 转发
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const params = new URLSearchParams();

    params.set('provider', provider);
    if (apiKey) params.set('api_key', apiKey);
    if (apiBase) params.set('api_base', apiBase);
    if (model) params.set('model', model);
    if (projectPath) params.set('project_path', projectPath);

    return `${protocol}//${host}/ws/${sessionId}?${params.toString()}`;
  }, [sessionId, provider, apiKey, apiBase, model, projectPath]);

  const handleTtsPlayback = useCallback(
    (messageId: string, content: string) => {
      const sanitized = sanitizeTtsText(content);
      if (!sanitized || sanitized.startsWith('[任务已中断]')) {
        return;
      }

      const { messages } = useChatStore.getState();
      const existing = messages.find((msg) => msg.id === messageId);
      if (existing?.audioBase64) {
        return;
      }

      void (async () => {
        const versionAtStart = userInputVersionRef.current;
        const response = await fetchTtsAudio(sanitized);
        if (!response?.success || !response.audio_base64) {
          return;
        }

        updateMessage(messageId, {
          audioBase64: response.audio_base64,
          audioMime: response.audio_mime,
        });

        if (versionAtStart !== userInputVersionRef.current) {
          return;
        }

        await playAudioBase64(
          response.audio_base64,
          response.audio_mime || 'audio/mpeg'
        );
      })();
    },
    [updateMessage]
  );

  // 处理消息
  const handleMessage = useCallback(
    (event: MessageEvent) => {
      try {
        const message: WebSocketMessage = JSON.parse(event.data);
        const { type, payload, session_id: msgSessionId } = message;

        // 校验 session_id - 忽略不匹配当前会话的消息
        // 允许 CONNECTION_ACK 消息（用于更新 session_id）
        // 允许 session_id 为空的消息（兼容性）
        if (
          msgSessionId &&
          expectedSessionIdRef.current !== 'new' &&
          msgSessionId !== expectedSessionIdRef.current &&
          type !== MessageType.CONNECTION_ACK
        ) {
          console.log(
            `Ignoring message for old session: ${msgSessionId}, ` +
            `expected: ${expectedSessionIdRef.current}`
          );
          return;
        }

        switch (type) {
          case MessageType.CONNECTION_ACK: {
            const ackPayload = payload as unknown as ConnectionAckPayload;
            // 更新期望的 session_id
            expectedSessionIdRef.current = ackPayload.session_id;
            setConnected(true);
            setAvailableTools(ackPayload.tools || []);
            setMode(ackPayload.mode as 'BUILD' | 'PLAN' | 'REVIEW');
            onConnect?.(ackPayload);
            break;
          }

          case MessageType.CONTENT_CHUNK: {
            const content = (payload as { content?: string }).content || '';
            const { currentStreamId } = useChatStore.getState();
            
            // 收到内容后关闭思考状态
            setThinking(false);
            
            // 如果还没有助手消息，先创建一个
            if (!currentStreamId && content) {
              const assistantMsgId = `assistant-${Date.now()}`;
              addMessage({
                id: assistantMsgId,
                role: 'assistant',
                content: content,
                timestamp: new Date().toISOString(),
                isStreaming: true,
              });
              startStreaming(assistantMsgId);
            } else {
              appendStreamContent(content);
            }
            break;
          }

          case MessageType.CONTENT: {
            const content = (payload as { content?: string }).content || '';
            const { currentStreamId } = useChatStore.getState();

            if (currentStreamId) {
              updateMessage(currentStreamId, {
                content,
                isStreaming: false,
              });
              stopStreaming();
              if (content && !content.includes('MEDIA:')) {
                handleTtsPlayback(currentStreamId, content);
              }
              break;
            }

            // 非流式的完整内容，添加新消息
            if (content) {
              const messageId = `msg-${Date.now()}`;
              addMessage({
                id: messageId,
                role: 'assistant',
                content,
                timestamp: new Date().toISOString(),
              });
              if (!content.includes('MEDIA:')) {
                handleTtsPlayback(messageId, content);
              }
            }
            break;
          }
          
          case MessageType.MEDIA_CONTENT: {
            const mediaPayload = payload as {
              content?: string;
              media_items?: MediaItem[];
            };
            const { currentStreamId, messages } = useChatStore.getState();
            const targetId =
              currentStreamId ??
              [...messages].reverse().find((msg) => msg.role === 'assistant')
                ?.id;

            if (targetId) {
              const updates: {
                content?: string;
                mediaItems?: MediaItem[];
              } = {};
              if (mediaPayload.content !== undefined) {
                updates.content = mediaPayload.content;
              }
              if (mediaPayload.media_items?.length) {
                updates.mediaItems = mediaPayload.media_items;
              }
              if (Object.keys(updates).length > 0) {
                updateMessage(targetId, updates);
              }
              if (mediaPayload.content) {
                handleTtsPlayback(targetId, mediaPayload.content);
              }
            }
            break;
          }

          case MessageType.TOOL_CALL: {
            // 收到工具调用后关闭思考状态
            setThinking(false);

            // 如果当前有流式内容，先触发 TTS 播放
            const { currentStreamId, currentStreamContent } =
              useChatStore.getState();
            if (currentStreamId && currentStreamContent) {
              updateMessage(currentStreamId, { isStreaming: false });
              stopStreaming();
              handleTtsPlayback(currentStreamId, currentStreamContent);
            }

            const toolPayload = payload as {
              id?: string;
              name?: string;
              arguments?: Record<string, unknown>;
              description?: string;
              formatted_args?: string;
            };
            addToolCall({
              id: toolPayload.id || `tool-${Date.now()}`,
              name: toolPayload.name || 'unknown',
              arguments: toolPayload.arguments || {},
              description: toolPayload.description,
              formatted_args: toolPayload.formatted_args,
            });
            break;
          }

          case MessageType.TOOL_RESULT: {
            const resultPayload = payload as {
              tool_name?: string;
              tool_call_id?: string;
              result?: string;
              data?: unknown;
              error?: string;
              status?: string;
              success?: boolean;
              summary?: string;
            };
            const result =
              resultPayload.result ??
              (resultPayload.data != null
                ? String(resultPayload.data)
                : resultPayload.error || '');
            const success =
              resultPayload.success ??
              (resultPayload.status ? resultPayload.status !== 'error' : true);
            addToolResult({
              toolName: resultPayload.tool_name || 'unknown',
              toolCallId: resultPayload.tool_call_id,
              result,
              success,
              summary: resultPayload.summary,
            });
            break;
          }

          case MessageType.TODO_UPDATE: {
            const todos = (payload as { todos?: unknown[] }).todos || [];
            setTodos(todos as Parameters<typeof setTodos>[0]);
            break;
          }

          case MessageType.MODE_CHANGE: {
            const mode = (payload as { mode?: string }).mode || 'BUILD';
            setMode(mode as 'BUILD' | 'PLAN' | 'REVIEW');
            break;
          }

          case MessageType.PROCESSING_STATUS: {
            const statusPayload = payload as { is_processing?: boolean };
            const isProcessingNow = statusPayload.is_processing ?? false;
            setProcessing(isProcessingNow);
            // 处理结束时确保关闭思考状态和清除子任务
            if (!isProcessingNow) {
              setThinking(false);
              clearSubtasks();  // 清除所有子任务状态
            }
            break;
          }

          case MessageType.ERROR: {
            // 错误时关闭思考状态
            setThinking(false);
            const errorPayload = payload as { error?: string };
            const errorMsg = errorPayload.error || 'Unknown error';
            onError?.(errorMsg);
            addMessage({
              id: `error-${Date.now()}`,
              role: 'system',
              content: `错误: ${errorMsg}`,
              timestamp: new Date().toISOString(),
            });
            break;
          }

          case MessageType.THINKING: {
            // 可以显示思考状态
            break;
          }

          case MessageType.HEARTBEAT: {
            // 心跳响应，不需要处理
            break;
          }

          case MessageType.INTERRUPT_RESULT: {
            // 处理中断结果
            const resultPayload = payload as unknown as InterruptResultPayload;
            setInterruptResult(resultPayload);

            // 根据意图更新状态
            if (resultPayload.intent === 'pause') {
              setPaused(true, resultPayload.paused_task);
              setProcessing(false);
              setThinking(false);
            } else if (resultPayload.intent === 'resume') {
              setPaused(false);
            } else if (resultPayload.intent === 'cancel') {
              setProcessing(false);
              setThinking(false);
            } else if (resultPayload.intent === 'switch') {
              // switch 会自动开始新任务，保持 processing 状态
              setThinking(true);
            }
            // supplement 不需要特殊处理，继续当前任务
            break;
          }

          case MessageType.SUBTASK_UPDATE: {
            // 处理子任务更新
            const subtaskPayload = payload as unknown as SubtaskUpdatePayload;
            updateSubtask(subtaskPayload);
            break;
          }

          case MessageType.ASK_USER_QUESTION: {
            // 处理用户问题请求
            const questionPayload = payload as unknown as AskUserQuestionPayload;
            setPendingQuestion(questionPayload);
            break;
          }

          default:
            console.log('Unknown message type:', type);
        }
      } catch (error) {
        console.error('Failed to parse WebSocket message:', error);
      }
    },
    [
      addMessage,
      appendStreamContent,
      startStreaming,
      stopStreaming,
      updateMessage,
      setProcessing,
      setThinking,
      setPaused,
      setInterruptResult,
      addToolCall,
      addToolResult,
      updateSubtask,
      setTodos,
      setMode,
      setConnected,
      setAvailableTools,
      handleTtsPlayback,
      setPendingQuestion,
      onConnect,
      onError,
    ]
  );

  // 连接 WebSocket
  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    const url = buildWsUrl();
    const ws = new WebSocket(url);

    ws.onopen = () => {
      console.log('WebSocket connected');
      setIsConnected(true);
      reconnectAttemptsRef.current = 0;
    };

    ws.onmessage = handleMessage;

    ws.onclose = (event) => {
      console.log('WebSocket closed:', event.code, event.reason);
      setIsConnected(false);
      setConnected(false);
      onDisconnect?.();

      // 自动重连
      if (
        reconnectAttemptsRef.current < maxReconnectAttempts &&
        event.code !== 1000 // 正常关闭不重连
      ) {
        const delay = Math.min(1000 * Math.pow(2, reconnectAttemptsRef.current), 30000);
        reconnectTimeoutRef.current = window.setTimeout(() => {
          reconnectAttemptsRef.current++;
          connect();
        }, delay);
      }
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
      onError?.('WebSocket connection error');
    };

    wsRef.current = ws;
  }, [buildWsUrl, handleMessage, setConnected, onDisconnect, onError]);

  // 断开连接
  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    reconnectAttemptsRef.current = maxReconnectAttempts; // 阻止重连
    wsRef.current?.close(1000, 'User disconnect');
    wsRef.current = null;
    setIsConnected(false);
    setConnected(false);
  }, [setConnected]);

  // 发送消息
  const send = useCallback(
    (type: MessageType, payload: Record<string, unknown>) => {
      if (wsRef.current?.readyState !== WebSocket.OPEN) {
        console.warn('WebSocket is not connected');
        return;
      }

      const message: WebSocketMessage = {
        type,
        payload,
        session_id: sessionId,
        timestamp: new Date().toISOString(),
      };

      wsRef.current.send(JSON.stringify(message));
    },
    [sessionId]
  );

  // 发送聊天消息
  const sendMessage = useCallback(
    (content: string) => {
      if (!content.trim()) return;

      userInputVersionRef.current += 1;
      stopAllTts();

      // 添加用户消息
      addMessage({
        id: `user-${Date.now()}`,
        role: 'user',
        content,
        timestamp: new Date().toISOString(),
      });

      // 不再预先创建助手消息，而是在收到第一个 content_chunk 时创建
      // 这样工具调用会先显示，然后才是助手的回复

      // 发送到服务器
      send(MessageType.CHAT_MESSAGE, { content });
      setProcessing(true);
      setThinking(true);  // 开始思考状态，显示闪烁动画
    },
    [addMessage, send, setProcessing, setThinking]
  );

  // 中断 - 发送新输入，由后端识别意图
  const interrupt = useCallback(
    (newInput?: string) => {
      // 如果有新输入，先添加用户消息到列表
      if (newInput) {
        userInputVersionRef.current += 1;
        stopAllTts();
        addMessage({
          id: `user-${Date.now()}`,
          role: 'user',
          content: newInput,
          timestamp: new Date().toISOString(),
        });
      }
      send(MessageType.INTERRUPT, { new_input: newInput });
    },
    [send, addMessage]
  );

  // 暂停 - 显式暂停当前任务
  const pause = useCallback(() => {
    send(MessageType.INTERRUPT, { intent: 'pause' });
  }, [send]);

  // 恢复 - 恢复暂停的任务
  const resume = useCallback(() => {
    send(MessageType.SESSION_ACTION, { action: 'resume' });
    setPaused(false);
  }, [send, setPaused]);

  // 切换模式
  const switchMode = useCallback(
    (mode: string) => {
      send(MessageType.SWITCH_MODE, { mode });
    },
    [send]
  );

  // 发送用户回答
  const sendUserAnswer = useCallback(
    (requestId: string, answers: UserAnswer[]) => {
      send(MessageType.USER_ANSWER, {
        request_id: requestId,
        answers,
      });
      // 清除待处理的问题
      setPendingQuestion(null);
    },
    [send, setPendingQuestion]
  );

  // 使用 ref 来存储最新的 connect 函数，避免依赖变化导致无限循环
  const connectRef = useRef(connect);
  const disconnectRef = useRef(disconnect);
  
  // 追踪当前期望的 session_id，用于过滤过期消息
  const expectedSessionIdRef = useRef(sessionId);

  // 更新 ref
  useEffect(() => {
    connectRef.current = connect;
    disconnectRef.current = disconnect;
    expectedSessionIdRef.current = sessionId;
  });

  // 连接和清理 - 在 sessionId 或 provider 变化时重新连接
  useEffect(() => {
    // 1. 先强制断开老的连接，确保不再接收老会话的数据
    if (wsRef.current) {
      wsRef.current.onmessage = null;  // 立即停止处理消息
      wsRef.current.close(1000, 'Session changed');
      wsRef.current = null;
    }
    
    // 2. 清除状态
    clearMessages();
    clearTodos();
    clearSubtasks();
    setIsConnected(false);
    setConnected(false);
    
    // 3. 重置重连计数
    reconnectAttemptsRef.current = 0;
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    
    // 4. 建立新连接
    connectRef.current();
    
    return () => {
      // cleanup 时也断开连接
      if (wsRef.current) {
        wsRef.current.onmessage = null;
        wsRef.current.close(1000, 'Cleanup');
        wsRef.current = null;
      }
    };
  }, [sessionId, provider, clearMessages, clearTodos, clearSubtasks, setConnected]);

  return {
    isConnected,
    send,
    sendMessage,
    interrupt,
    pause,
    resume,
    switchMode,
    disconnect,
    sendUserAnswer,
  };
}
