/**
 * ToolGroupDisplay 组件
 *
 * 将连续的工具调用/结果消息整合到一个可滚动区域中，
 * 支持自动滚动到最新工具、手动回滚查看历史，
 * 并在顶部显示工具执行计数。
 */

import {
  useState,
  useEffect,
  useRef,
  useCallback,
  useMemo,
} from 'react';
import { Message, ToolCall, ToolResult } from '../../types';
import {
  formatToolArguments,
  formatToolResult,
} from '../../utils';
import clsx from 'clsx';

interface ToolGroupDisplayProps {
  messages: Message[];
}

/**
 * 配对后的工具调用单元：call + 可选 result
 */
interface ToolPair {
  callMsg: Message;
  call: ToolCall;
  result?: ToolResult;
  resultMsg?: Message;
}

/**
 * 将连续的 tool 消息配对为 call+result 组合。
 *
 * 配对策略（按优先级）：
 *  1. ID 匹配：result.toolCallId === call.id
 *  2. 顺序匹配：result 自动配对到最近一个还没有
 *     result 的 call 上
 *  3. 兜底：独立 result 作为一个完整 pair
 */
function buildToolPairs(messages: Message[]): ToolPair[] {
  const pairs: ToolPair[] = [];
  // id -> pair，用于 ID 匹配
  const idMap = new Map<string, ToolPair>();

  for (const msg of messages) {
    if (msg.toolCall) {
      const pair: ToolPair = {
        callMsg: msg,
        call: msg.toolCall,
      };
      pairs.push(pair);
      idMap.set(msg.toolCall.id, pair);
    } else if (msg.toolResult) {
      // 1) 尝试 ID 精确匹配
      const matchId = msg.toolResult.toolCallId;
      let matched = matchId
        ? idMap.get(matchId)
        : undefined;

      // 2) 退化为顺序匹配：最近一个没 result 的 pair
      if (!matched) {
        for (let i = pairs.length - 1; i >= 0; i--) {
          if (!pairs[i].result) {
            matched = pairs[i];
            break;
          }
        }
      }

      if (matched) {
        matched.result = msg.toolResult;
        matched.resultMsg = msg;
      } else {
        // 3) 兜底：独立 result
        pairs.push({
          callMsg: msg,
          call: {
            id: msg.id,
            name: msg.toolResult.toolName,
            arguments: {},
          },
          result: msg.toolResult,
          resultMsg: msg,
        });
      }
    }
  }
  return pairs;
}

/**
 * 单条工具调用+结果的紧凑展示
 */
function ToolPairItem({ pair }: { pair: ToolPair }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const { call, result } = pair;

  const subtitle = call.formatted_args || '';
  const hasResult = !!result;
  const isSuccess = result?.success ?? true;

  // 结果摘要：优先用 summary，再拼工具名+状态
  const resultSummary = result
    ? (result.summary
      || `${result.success ? '完成' : '失败'}`)
    : '';

  return (
    <div className="tool-pair-item">
      <div
        className="tool-pair-header"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        {/* 状态图标 */}
        <span className={clsx(
          'tool-pair-icon',
          hasResult
            ? (isSuccess ? 'success' : 'error')
            : 'pending'
        )}>
          {hasResult ? (
            isSuccess ? (
              <svg
                className="w-3 h-3"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M5 13l4 4L19 7"
                />
              </svg>
            ) : (
              <svg
                className="w-3 h-3"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M6 18L18 6M6 6l12 12"
                />
              </svg>
            )
          ) : (
            <svg
              className="w-3 h-3 animate-spin"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
              />
            </svg>
          )}
        </span>

        {/* 工具名称 */}
        <span className="tool-pair-name">
          {call.name}
        </span>

        {/* 参数摘要（始终显示） */}
        {subtitle && (
          <span className="tool-pair-summary">
            {subtitle}
          </span>
        )}

        {/* 结果摘要 */}
        {hasResult && (
          <span className={clsx(
            'tool-pair-result-badge',
            isSuccess ? 'success' : 'error'
          )}>
            {resultSummary}
          </span>
        )}

        {/* 展开/折叠 */}
        <span className="tool-pair-toggle">
          {isExpanded ? '▼' : '▶'}
        </span>
      </div>

      {/* 展开后的详细内容 */}
      {isExpanded && (
        <div className="tool-pair-detail">
          {/* 参数 */}
          {Object.keys(call.arguments).length > 0 && (
            <div className="tool-pair-section">
              <div className="tool-pair-section-label">
                参数
              </div>
              <pre className="tool-pair-pre">
                {formatToolArguments(call.arguments)}
              </pre>
            </div>
          )}
          {/* 结果 */}
          {result && (
            <div className="tool-pair-section">
              <div className="tool-pair-section-label">
                结果
              </div>
              <pre className={clsx(
                'tool-pair-pre',
                !result.success && 'error'
              )}>
                {formatToolResult(result.result, 1000)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function ToolGroupDisplay(
  { messages }: ToolGroupDisplayProps
) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [userScrolled, setUserScrolled] = useState(false);

  const pairs = useMemo(
    () => buildToolPairs(messages),
    [messages]
  );

  // 统计：以配对数为准
  const totalPairs = pairs.length;
  const pendingCount = pairs.filter(
    (p) => !p.result
  ).length;

  // 检测用户是否手动向上滚动
  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = (
      el.scrollHeight - el.scrollTop - el.clientHeight < 40
    );
    setUserScrolled(!atBottom);
  }, []);

  // 滚动内部容器到底部（不影响外层滚动）
  const scrollInner = useCallback((smooth = true) => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({
      top: el.scrollHeight,
      behavior: smooth ? 'smooth' : 'instant',
    });
  }, []);

  // 自动滚动到底部
  useEffect(() => {
    if (!userScrolled) {
      scrollInner(true);
    }
  }, [messages.length, userScrolled, scrollInner]);

  // 手动"回到底部"
  const scrollToBottom = useCallback(() => {
    setUserScrolled(false);
    scrollInner(true);
  }, [scrollInner]);

  return (
    <div className="tool-group-container animate-rise">
      {/* 顶部计数器 */}
      <div className="tool-group-header">
        <div className="tool-group-header-left">
          <svg
            className="w-4 h-4"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            strokeWidth={1.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M11.42 15.17L17.25 21A2.652 2.652 0 0021 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 11-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 004.486-6.336l-3.276 3.277a3.004 3.004 0 01-2.25-2.25l3.276-3.276a4.5 4.5 0 00-6.336 4.486c.091 1.076-.071 2.264-.904 2.95l-.102.085m-1.745 1.437L5.909 7.5H4.5L2.25 3.75l1.5-1.5L7.5 4.5v1.409l4.26 4.26m-1.745 1.437l1.745-1.437m6.615 8.206L15.75 15.75M4.867 19.125h.008v.008h-.008v-.008z"
            />
          </svg>
          <span>
            已执行 {totalPairs} 次工具调用
            {pendingCount > 0 && (
              <span className="tool-group-pending">
                {' '}({pendingCount} 个执行中)
              </span>
            )}
          </span>
        </div>
      </div>

      {/* 可滚动的工具列表 */}
      <div
        ref={scrollRef}
        className="tool-group-scroll"
        onScroll={handleScroll}
      >
        {pairs.map((pair) => (
          <ToolPairItem
            key={pair.callMsg.id}
            pair={pair}
          />
        ))}
      </div>

      {/* 用户向上滚动时，显示"回到底部"按钮 */}
      {userScrolled && (
        <button
          className="tool-group-scroll-btn"
          onClick={scrollToBottom}
        >
          ↓ 最新
        </button>
      )}
    </div>
  );
}
