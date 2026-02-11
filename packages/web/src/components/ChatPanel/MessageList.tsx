/**
 * MessageList 组件
 *
 * 消息列表显示，连续的工具消息会被自动合并为
 * 一个可滚动的 ToolGroupDisplay 块。
 */

import { useMemo } from 'react';
import { Message } from '../../types';
import { MessageItem } from './MessageItem';
import { ToolGroupDisplay } from './ToolGroupDisplay';

interface MessageListProps {
  messages: Message[];
}

type MessageGroup =
  | { type: 'message'; message: Message }
  | { type: 'toolGroup'; messages: Message[] };

/**
 * 将消息列表中连续的 role='tool' 消息合并为分组，
 * 非 tool 消息保持原样。
 */
function groupMessages(messages: Message[]): MessageGroup[] {
  const groups: MessageGroup[] = [];
  let toolBuf: Message[] = [];

  const flushTools = () => {
    if (toolBuf.length > 0) {
      groups.push({ type: 'toolGroup', messages: toolBuf });
      toolBuf = [];
    }
  };

  for (const msg of messages) {
    if (msg.role === 'tool') {
      toolBuf.push(msg);
    } else {
      flushTools();
      groups.push({ type: 'message', message: msg });
    }
  }
  flushTools();

  return groups;
}

export function MessageList({ messages }: MessageListProps) {
  const groups = useMemo(
    () => groupMessages(messages),
    [messages]
  );

  if (messages.length === 0) {
    return null;
  }

  return (
    <div className="space-y-1">
      {groups.map((group) => {
        if (group.type === 'toolGroup') {
          // 用第一条消息的 id 作 key
          const key = group.messages[0].id;
          return (
            <ToolGroupDisplay
              key={key}
              messages={group.messages}
            />
          );
        }
        return (
          <MessageItem
            key={group.message.id}
            message={group.message}
          />
        );
      })}
    </div>
  );
}
