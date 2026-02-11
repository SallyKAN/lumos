/**
 * WebSocket 消息类型
 */

export enum MessageType {
  // 客户端 -> 服务端
  CHAT_MESSAGE = 'chat_message',
  INTERRUPT = 'interrupt',
  SWITCH_MODE = 'switch_mode',
  TODO_ACTION = 'todo_action',
  SESSION_ACTION = 'session_action',
  USER_ANSWER = 'user_answer',

  // 服务端 -> 客户端
  THINKING = 'thinking',
  CONTENT_CHUNK = 'content_chunk',
  CONTENT = 'content',
  MEDIA_CONTENT = 'media_content',
  TOOL_CALL = 'tool_call',
  TOOL_RESULT = 'tool_result',
  ERROR = 'error',
  MODE_CHANGE = 'mode_change',
  INTERRUPT_RESULT = 'interrupt_result',
  SUBTASK_UPDATE = 'subtask_update',
  ASK_USER_QUESTION = 'ask_user_question',

  // 双向
  TODO_UPDATE = 'todo_update',
  SESSION_UPDATE = 'session_update',
  CONNECTION_ACK = 'connection_ack',
  HEARTBEAT = 'heartbeat',
  PROCESSING_STATUS = 'processing_status',
}

export interface WebSocketMessage {
  type: MessageType | string;
  payload: Record<string, unknown>;
  session_id?: string;
  message_id?: string;
  timestamp: string;
}

export interface ConnectionAckPayload {
  session_id: string;
  mode: string;
  tools: string[];
}

export interface ProcessingStatusPayload {
  is_processing: boolean;
  current_task?: string;
}

export interface ErrorPayload {
  error: string;
  code?: string;
  recoverable: boolean;
}

/**
 * 中断意图类型
 */
export type InterruptIntent = 'switch' | 'pause' | 'cancel' | 'supplement' | 'resume';

/**
 * 中断结果 Payload
 */
export interface InterruptResultPayload {
  intent: InterruptIntent;
  success: boolean;
  message: string;
  new_input?: string;
  merged_input?: string;
  paused_task?: string;
}

/**
 * 子任务状态类型
 */
export type SubtaskStatus = 'starting' | 'tool_call' | 'tool_result' | 'completed' | 'error';

/**
 * 子任务更新 Payload
 */
export interface SubtaskUpdatePayload {
  task_id: string;
  description: string;
  status: SubtaskStatus;
  index: number;
  total: number;
  tool_name?: string;
  tool_count?: number;
  message?: string;
  is_parallel?: boolean;
}

/**
 * 问题选项
 */
export interface QuestionOption {
  label: string;
  description?: string;
}

/**
 * 问题定义
 */
export interface Question {
  question: string;
  header: string;
  options: QuestionOption[];
  multi_select?: boolean;
}

/**
 * 用户问题请求 Payload（服务端 -> 客户端）
 */
export interface AskUserQuestionPayload {
  request_id: string;
  questions: Question[];
}

/**
 * 用户回答
 */
export interface UserAnswer {
  selected_options: string[];
  custom_input?: string;
}

/**
 * 用户回答 Payload（客户端 -> 服务端）
 */
export interface UserAnswerPayload {
  request_id: string;
  answers: UserAnswer[];
}
