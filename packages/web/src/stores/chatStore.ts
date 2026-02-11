/**
 * 聊天状态管理
 */

import { create } from 'zustand';
import {
  Message,
  ToolCall,
  ToolResult,
  InterruptResultPayload,
  SubtaskUpdatePayload,
  AskUserQuestionPayload,
  UserAnswer,
} from '../types';
import { useTodoStore } from './todoStore';

/**
 * 子任务状态
 */
export interface SubtaskState {
  task_id: string;
  description: string;
  status: string;
  index: number;
  total: number;
  tool_name?: string;
  tool_count: number;
  message?: string;
  is_parallel: boolean;
}

interface ChatState {
  messages: Message[];
  isProcessing: boolean;
  isThinking: boolean;  // 思考中状态（显示闪烁动画）
  isPaused: boolean;    // 任务是否暂停
  pausedTask: string | null;  // 暂停的任务描述
  interruptResult: InterruptResultPayload | null;  // 最近的中断结果
  currentStreamContent: string;
  currentStreamId: string | null;
  activeSubtasks: Map<string, SubtaskState>;  // 活跃的子任务
  // 用户问题相关
  pendingQuestion: AskUserQuestionPayload | null;  // 待回答的问题

  // Actions
  addMessage: (message: Message) => void;
  updateMessage: (id: string, updates: Partial<Message>) => void;
  appendStreamContent: (content: string) => void;
  startStreaming: (messageId: string) => void;
  stopStreaming: () => void;
  setProcessing: (status: boolean) => void;
  setThinking: (status: boolean) => void;
  setPaused: (paused: boolean, task?: string | null) => void;
  setInterruptResult: (result: InterruptResultPayload | null) => void;
  addToolCall: (toolCall: ToolCall) => void;
  addToolResult: (toolResult: ToolResult) => void;
  updateSubtask: (payload: SubtaskUpdatePayload) => void;
  clearSubtasks: () => void;
  clearMessages: () => void;
  // 用户问题相关
  setPendingQuestion: (question: AskUserQuestionPayload | null) => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  isProcessing: false,
  isThinking: false,
  isPaused: false,
  pausedTask: null,
  interruptResult: null,
  currentStreamContent: '',
  currentStreamId: null,
  activeSubtasks: new Map(),
  pendingQuestion: null,

  addMessage: (message) => {
    set((state) => ({
      messages: [...state.messages, message],
    }));
  },

  updateMessage: (id, updates) => {
    set((state) => ({
      messages: state.messages.map((msg) =>
        msg.id === id ? { ...msg, ...updates } : msg
      ),
    }));
  },

  appendStreamContent: (content) => {
    const { currentStreamId, messages } = get();
    if (!currentStreamId) return;

    set((state) => ({
      currentStreamContent: state.currentStreamContent + content,
      messages: state.messages.map((msg) =>
        msg.id === currentStreamId
          ? { ...msg, content: state.currentStreamContent + content }
          : msg
      ),
    }));
  },

  startStreaming: (messageId) => {
    set({
      currentStreamId: messageId,
      currentStreamContent: '',
    });
  },

  stopStreaming: () => {
    const { currentStreamId } = get();
    if (currentStreamId) {
      set((state) => ({
        messages: state.messages.map((msg) =>
          msg.id === currentStreamId ? { ...msg, isStreaming: false } : msg
        ),
        currentStreamId: null,
        currentStreamContent: '',
      }));
    }
  },

  setProcessing: (status) => {
    set({ isProcessing: status });
  },

  setThinking: (status) => {
    set({ isThinking: status });
  },

  setPaused: (paused, task = null) => {
    set({ isPaused: paused, pausedTask: task ?? null });
  },

  setInterruptResult: (result) => {
    set({ interruptResult: result });
    // 3 秒后自动清除中断结果提示
    if (result) {
      setTimeout(() => {
        set((state) => {
          // 只有当前结果没有变化时才清除
          if (state.interruptResult === result) {
            return { interruptResult: null };
          }
          return {};
        });
      }, 3000);
    }
  },

  addToolCall: (toolCall) => {
    const id = `tool-call-${Date.now()}`;
    const message: Message = {
      id,
      role: 'tool',
      content: `调用工具: ${toolCall.name}`,
      timestamp: new Date().toISOString(),
      toolCall,
    };
    set((state) => ({
      messages: [...state.messages, message],
    }));
  },

  addToolResult: (toolResult) => {
    set((state) => {
      let toolName = toolResult.toolName;
      if (
        (!toolName || toolName === 'unknown') &&
        toolResult.toolCallId
      ) {
        const matched_call = state.messages.find(
          (msg) => msg.toolCall?.id === toolResult.toolCallId
        );
        if (matched_call?.toolCall?.name) {
          toolName = matched_call.toolCall.name;
        }
      }

      const id = `tool-result-${Date.now()}`;
      const message: Message = {
        id,
        role: 'tool',
        content: toolResult.result,
        timestamp: new Date().toISOString(),
        toolResult: {
          ...toolResult,
          toolName: toolName || 'unknown',
        },
      };
      return { messages: [...state.messages, message] };
    });
  },

  updateSubtask: (payload: SubtaskUpdatePayload) => {
    set((state) => {
      const newSubtasks = new Map(state.activeSubtasks);
      
      if (payload.status === 'completed' || payload.status === 'error') {
        // 任务完成或出错，从活跃列表中移除
        newSubtasks.delete(payload.task_id);
      } else {
        // 更新或添加子任务状态
        newSubtasks.set(payload.task_id, {
          task_id: payload.task_id,
          description: payload.description,
          status: payload.status,
          index: payload.index,
          total: payload.total,
          tool_name: payload.tool_name,
          tool_count: payload.tool_count || 0,
          message: payload.message,
          is_parallel: payload.is_parallel || false,
        });
      }
      
      return { activeSubtasks: newSubtasks };
    });

    // 同时更新 todoStore 中对应任务的 activeForm（如果能匹配）
    const todoState = useTodoStore.getState();
    const { todos, setTodos } = todoState;
    
    // 尝试匹配子任务描述和 todo 内容
    const matchingTodo = todos.find(
      (todo) =>
        todo.status === 'in_progress' &&
        (todo.content.includes(payload.description) ||
         payload.description.includes(todo.content.slice(0, 20)))
    );
    
    if (matchingTodo) {
      let activeForm = '';
      if (payload.status === 'starting') {
        activeForm = `正在${payload.description}...`;
      } else if (payload.status === 'tool_call') {
        activeForm = `正在调用 ${payload.tool_name}...`;
      } else if (payload.status === 'completed') {
        activeForm = '';  // 清除
      }
      
      if (activeForm || payload.status === 'completed') {
        const updatedTodos = todos.map((todo) =>
          todo.id === matchingTodo.id
            ? { ...todo, activeForm }
            : todo
        );
        setTodos(updatedTodos);
      }
    }
  },

  clearSubtasks: () => {
    set({ activeSubtasks: new Map() });
  },

  clearMessages: () => {
    set({
      messages: [],
      currentStreamContent: '',
      currentStreamId: null,
      isPaused: false,
      pausedTask: null,
      interruptResult: null,
      activeSubtasks: new Map(),
      pendingQuestion: null,
    });
  },

  setPendingQuestion: (question) => {
    set({ pendingQuestion: question });
  },
}));
