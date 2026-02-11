# OpenJiuwen Web 前端

基于 React + TypeScript + Tailwind CSS 构建的 AI 编程助手 Web 界面，设计风格参考 OpenClaw。

## 功能特性

### 已实现功能

#### 💬 聊天交互
- **实时对话**：WebSocket 双向通信，支持流式输出
- **Markdown 渲染**：支持代码高亮、列表、链接等格式
- **思考动画**：AI 思考时显示动态指示器
- **消息历史**：显示用户和助手的对话记录

#### 🛠 工具调用
- **工具执行可视化**：显示 AI 调用的工具名称和参数
- **执行结果展示**：显示工具执行成功/失败状态和返回结果
- **可用工具列表**：右侧面板显示当前可用的工具

#### 📋 任务管理
- **Todo 列表**：显示 AI 创建的任务列表
- **状态分组**：按进行中、待处理、已完成分组显示
- **实时更新**：任务状态变化实时同步

#### 📂 会话管理
- **会话列表**：侧边栏显示历史会话
- **会话切换**：点击切换不同会话
- **会话删除**：悬停显示删除按钮，支持删除会话
- **会话持久化**：刷新页面自动恢复上次会话

#### ⚙️ 模式切换
- **BUILD 模式**：默认编码模式
- **PLAN 模式**：规划模式
- **REVIEW 模式**：审查模式

#### 🎨 主题支持
- **浅色主题**：默认，蓝色基调
- **深色主题**：深色背景，优化蓝色可见度
- **系统跟随**：可选跟随系统主题

#### ⏯ 流程控制
- **暂停/继续**：暂停和恢复 AI 处理
- **中断**：中断当前任务，可附加新指令

#### 🎤 语音交互
- **语音输入**：点击麦克风按钮进行语音输入（STT）
- **语音朗读**：鼠标悬停在 AI 回复上显示朗读按钮（TTS）
- **打断演示**：语音输入时可随时打断 AI 处理

## 技术栈

- **框架**：React 18 + TypeScript
- **样式**：Tailwind CSS + CSS Variables
- **状态管理**：Zustand
- **构建工具**：Vite
- **通信**：WebSocket + REST API

## 快速开始

### 环境要求

- Node.js 18+
- npm 或 pnpm

### 安装依赖

```bash
cd packages/web
npm install
```

### 配置后端地址

编辑 `vite.config.ts` 中的 proxy 配置：

```typescript
proxy: {
  '/api': {
    target: 'http://127.0.0.1:19000',  // 修改为你的后端地址
    changeOrigin: true,
  },
  '/ws': {
    target: 'http://127.0.0.1:19000',  // 修改为你的后端地址
    ws: true,
    changeOrigin: true,
  },
}
```

### 启动开发服务器

```bash
npm run dev
```

访问 http://localhost:5173

### 启动后端

```bash
cd packages/server
PORT=19000 python -m packages.server.api.app
```

## 后端 API 要求

前端依赖以下后端接口：

### REST API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/config` | GET | 获取服务配置（provider, model 等） |
| `/api/sessions` | GET | 获取会话列表 |
| `/api/sessions/:id` | DELETE | 删除会话 |

### WebSocket

连接地址：`/ws/{session_id}?provider=openai`

#### 客户端 → 服务端消息

| 类型 | 说明 |
|------|------|
| `chat_message` | 发送聊天消息 |
| `interrupt` | 中断当前任务 |
| `switch_mode` | 切换模式 |
| `todo_action` | Todo 操作 |

#### 服务端 → 客户端消息

| 类型 | 说明 |
|------|------|
| `connection_ack` | 连接确认 |
| `thinking` | AI 正在思考 |
| `content_chunk` | 流式内容片段 |
| `content` | 完整内容 |
| `tool_call` | 工具调用 |
| `tool_result` | 工具执行结果 |
| `todo_update` | Todo 更新 |
| `error` | 错误信息 |

## 项目结构

```
packages/web/
├── public/
│   └── logo.png           # 应用 Logo
├── src/
│   ├── components/
│   │   ├── ChatPanel/     # 聊天面板
│   │   ├── SessionSidebar/# 会话侧边栏
│   │   ├── StatusBar/     # 状态栏
│   │   ├── TodoList/      # 任务列表
│   │   └── ToolPanel/     # 工具面板
│   ├── hooks/
│   │   └── useWebSocket.ts# WebSocket Hook
│   ├── stores/
│   │   ├── chatStore.ts   # 聊天状态
│   │   ├── sessionStore.ts# 会话状态
│   │   └── todoStore.ts   # Todo 状态
│   ├── types/             # TypeScript 类型定义
│   ├── utils/             # 工具函数
│   ├── App.tsx            # 主应用组件
│   ├── index.css          # 全局样式 + CSS 变量
│   └── main.tsx           # 入口文件
├── index.html
├── tailwind.config.js
├── vite.config.ts
└── package.json
```

## 与 OpenClaw 的功能差异

### ✅ 已对齐的功能

| 功能 | 状态 |
|------|------|
| 聊天界面 | ✅ |
| 流式输出 | ✅ |
| 工具调用显示 | ✅ |
| Todo 任务列表 | ✅ |
| 会话管理 | ✅ |
| 主题切换 | ✅ |
| 模式切换 | ✅ |
| 暂停/继续/中断 | ✅ |

### ❌ 尚未实现的功能

| 功能 | 说明 | 优先级 |
|------|------|--------|
| **Overview 仪表盘** | 系统状态概览、统计数据 | 中 |
| **Channels 渠道管理** | WhatsApp/Telegram/Discord 等消息渠道配置 | 低 |
| **Agents 管理** | 多 Agent 列表、Agent 文件浏览 | 中 |
| **Config 配置编辑器** | 可视化配置编辑界面 | 高 |
| **Logs 日志查看** | 系统日志查看、级别筛选、导出 | 高 |
| **Cron 定时任务** | 定时任务创建和管理 | 低 |
| **Skills 技能管理** | 技能插件安装/卸载/配置 | 中 |
| **Nodes 节点管理** | 分布式节点状态和管理 | 低 |
| **Exec Approval** | 危险命令执行审批弹窗 | 高 |
| **侧边栏详情面板** | 点击工具调用查看完整输入输出 | 高 |
| **聊天附件** | 上传文件/图片作为消息附件 | 高 |
| **消息队列显示** | 显示排队中的消息 | 中 |
| **Session 详情页** | 单会话详情、完整历史记录 | 中 |
| **密码保护** | 访问密码验证 | 低 |
| **Onboarding 引导** | 新用户引导流程 | 低 |
| **Gateway URL 配置** | 网关地址配置界面 | 中 |

### 建议优先实现

1. **侧边栏详情面板** - 查看工具调用的完整输出
2. **聊天附件** - 支持上传文件
3. **Config 配置** - 可视化配置编辑
4. **Logs 日志** - 调试和问题排查必备
5. **Exec Approval** - 安全相关，防止危险命令执行

## 自定义配置

### 修改品牌

1. 替换 `public/logo.png`
2. 修改 `index.html` 中的 `<title>`
3. 修改 `src/App.tsx` 中的品牌文字

### 修改主题颜色

编辑 `src/index.css` 中的 CSS 变量：

```css
:root {
  --accent: #60a5fa;        /* 深色模式主色 */
  --accent-hover: #93c5fd;  /* 悬停色 */
}

:root[data-theme="light"] {
  --accent: #2563eb;        /* 浅色模式主色 */
  --accent-hover: #3b82f6;  /* 悬停色 */
}
```

## License

MIT
