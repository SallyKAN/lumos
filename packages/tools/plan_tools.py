"""
Plan 模式工具实现

提供 EnterPlanMode 和 ExitPlanMode 工具，支持结构化的规划工作流
"""

import os
import asyncio
import random
import json
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field, asdict
from ..core.tool import Tool, ToolInfo, Parameters, Param

from ..agents.mode_manager import AgentModeManager, AgentMode


# ==================== Plan 文件名生成词库 ====================

ADJECTIVES = [
    "luminous", "swift", "gentle", "bold", "quiet",
    "bright", "calm", "eager", "fair", "grand",
    "happy", "keen", "lively", "merry", "noble",
    "proud", "quick", "rare", "smart", "true",
    "vivid", "warm", "young", "zesty", "agile",
    "brave", "clear", "deft", "epic", "fresh"
]

NOUNS = [
    "lightning", "river", "mountain", "forest", "ocean",
    "thunder", "meadow", "canyon", "valley", "stream",
    "sunrise", "sunset", "rainbow", "crystal", "diamond",
    "phoenix", "dragon", "falcon", "tiger", "eagle",
    "comet", "nebula", "aurora", "glacier", "volcano",
    "breeze", "storm", "flame", "frost", "spark"
]


# ==================== 权限预授权管理器 ====================

class PermissionManager:
    """权限预授权管理器

    管理 Plan 模式审批后的命令预授权。
    当用户审批 Plan 时，可以预授权某些命令类型，
    这些命令在后续执行时无需再次确认。
    """

    # 预定义的命令模式映射
    # key: 语义描述, value: 匹配的命令模式列表
    PROMPT_PATTERNS = {
        "run tests": [
            "pytest", "python -m pytest", "python3 -m pytest",
            "npm test", "npm run test", "yarn test",
            "go test", "cargo test", "make test",
            "jest", "mocha", "vitest",
        ],
        "install dependencies": [
            "pip install", "pip3 install", "python -m pip install",
            "npm install", "npm i", "yarn install", "yarn add",
            "cargo build", "go mod download", "go get",
            "apt install", "apt-get install", "brew install",
        ],
        "build the project": [
            "npm run build", "yarn build", "make", "make build",
            "cargo build", "go build", "python setup.py build",
            "tsc", "webpack", "vite build", "next build",
        ],
        "run linter": [
            "flake8", "pylint", "mypy", "black --check",
            "eslint", "prettier --check", "tslint",
            "cargo clippy", "golint", "go vet",
        ],
        "format code": [
            "black", "autopep8", "yapf",
            "prettier", "eslint --fix",
            "cargo fmt", "gofmt", "go fmt",
        ],
        "start server": [
            "npm start", "npm run dev", "yarn start", "yarn dev",
            "python manage.py runserver", "flask run", "uvicorn",
            "go run", "cargo run",
        ],
        "run migrations": [
            "python manage.py migrate", "alembic upgrade",
            "prisma migrate", "knex migrate",
            "diesel migration run",
        ],
        "generate types": [
            "prisma generate", "graphql-codegen",
            "openapi-generator", "protoc",
        ],
    }

    def __init__(self):
        self._allowed_prompts: List[Dict[str, str]] = []
        self._custom_patterns: Dict[str, List[str]] = {}

    def add_allowed_prompts(self, prompts: List[Dict[str, str]]):
        """添加预授权的命令

        Args:
            prompts: 预授权列表，格式为 [{"tool": "Bash", "prompt": "run tests"}, ...]
        """
        self._allowed_prompts.extend(prompts)

    def clear_allowed_prompts(self):
        """清除所有预授权"""
        self._allowed_prompts.clear()

    def get_allowed_prompts(self) -> List[Dict[str, str]]:
        """获取当前预授权列表"""
        return self._allowed_prompts.copy()

    def is_command_preauthorized(self, command: str) -> bool:
        """检查命令是否已预授权

        Args:
            command: 要检查的命令

        Returns:
            如果命令匹配任何预授权的 prompt，返回 True
        """
        command_lower = command.lower().strip()

        for prompt_info in self._allowed_prompts:
            tool = prompt_info.get("tool", "").lower()
            prompt = prompt_info.get("prompt", "").lower()

            # 只处理 Bash 工具的预授权
            if tool != "bash":
                continue

            if self._match_prompt(command_lower, prompt):
                return True

        return False

    def _match_prompt(self, command: str, prompt: str) -> bool:
        """匹配命令和提示词

        Args:
            command: 命令（已转小写）
            prompt: 提示词（已转小写）

        Returns:
            如果命令匹配提示词描述的操作，返回 True
        """
        # 首先检查预定义模式
        patterns = self.PROMPT_PATTERNS.get(prompt, [])
        for pattern in patterns:
            if pattern.lower() in command:
                return True

        # 检查自定义模式
        custom_patterns = self._custom_patterns.get(prompt, [])
        for pattern in custom_patterns:
            if pattern.lower() in command:
                return True

        # 最后尝试直接匹配（prompt 本身作为命令前缀）
        # 例如 prompt="git status" 可以匹配 "git status" 命令
        if prompt in command:
            return True

        return False

    def add_custom_pattern(self, prompt: str, patterns: List[str]):
        """添加自定义命令模式

        Args:
            prompt: 提示词
            patterns: 匹配的命令模式列表
        """
        if prompt not in self._custom_patterns:
            self._custom_patterns[prompt] = []
        self._custom_patterns[prompt].extend(patterns)

    def get_matching_prompt(self, command: str) -> Optional[str]:
        """获取命令匹配的预授权提示词

        Args:
            command: 要检查的命令

        Returns:
            匹配的提示词，如果没有匹配返回 None
        """
        command_lower = command.lower().strip()

        for prompt_info in self._allowed_prompts:
            tool = prompt_info.get("tool", "").lower()
            prompt = prompt_info.get("prompt", "").lower()

            if tool != "bash":
                continue

            if self._match_prompt(command_lower, prompt):
                return prompt_info.get("prompt", "")

        return None


# 全局权限管理器实例（会话级别）
_permission_manager: Optional[PermissionManager] = None


def get_permission_manager() -> PermissionManager:
    """获取全局权限管理器"""
    global _permission_manager
    if _permission_manager is None:
        _permission_manager = PermissionManager()
    return _permission_manager


def reset_permission_manager():
    """重置全局权限管理器（用于测试或会话结束）"""
    global _permission_manager
    _permission_manager = None


# ==================== 数据模型 ====================

@dataclass
class PlanSession:
    """Plan 会话数据"""
    session_id: str
    plan_file_path: str
    created_at: str
    status: str = "planning"  # "planning" | "pending_approval" | "approved" | "rejected"
    allowed_prompts: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PlanSession':
        return cls(**data)


# ==================== Plan 文件管理器 ====================

class PlanFileManager:
    """Plan 文件管理器

    负责创建、读取、更新 plan 文件
    """

    PLAN_TEMPLATE = """# Implementation Plan

## Summary
[1-3 句话描述要实现的功能]

## Approach
[推荐的实现方案]

## Key Files
- `path/to/file1.py` - [修改说明]
- `path/to/file2.py` - [修改说明]

## Implementation Steps
1. [步骤 1]
2. [步骤 2]
3. [步骤 3]

## Verification
- [ ] [验证步骤 1]
- [ ] [验证步骤 2]
"""

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.plans_dir = Path.home() / ".lumos" / "plans"
        self.plans_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_file = self.plans_dir / "sessions.json"
        self._current_session: Optional[PlanSession] = None

    def _generate_plan_filename(self) -> str:
        """生成随机的 plan 文件名"""
        adj1 = random.choice(ADJECTIVES)
        adj2 = random.choice(ADJECTIVES)
        noun = random.choice(NOUNS)
        return f"{adj1}-{adj2}-{noun}.md"

    def _load_sessions(self) -> Dict[str, PlanSession]:
        """加载所有会话"""
        if not self.sessions_file.exists():
            return {}
        try:
            with open(self.sessions_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return {k: PlanSession.from_dict(v) for k, v in data.items()}
        except Exception:
            return {}

    def _save_sessions(self, sessions: Dict[str, PlanSession]):
        """保存所有会话"""
        data = {k: v.to_dict() for k, v in sessions.items()}
        with open(self.sessions_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def create_plan_file(self) -> Path:
        """创建新的 plan 文件

        Returns:
            plan 文件路径
        """
        filename = self._generate_plan_filename()
        file_path = self.plans_dir / filename

        # 确保文件名唯一
        while file_path.exists():
            filename = self._generate_plan_filename()
            file_path = self.plans_dir / filename

        # 写入模板
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(self.PLAN_TEMPLATE)

        # 创建会话记录
        self._current_session = PlanSession(
            session_id=self.session_id,
            plan_file_path=str(file_path),
            created_at=datetime.now().isoformat(),
            status="planning"
        )

        # 保存会话
        sessions = self._load_sessions()
        sessions[self.session_id] = self._current_session
        self._save_sessions(sessions)

        return file_path

    def get_current_plan_file(self) -> Optional[Path]:
        """获取当前会话的 plan 文件路径"""
        if self._current_session:
            return Path(self._current_session.plan_file_path)

        # 尝试从会话文件加载
        sessions = self._load_sessions()
        if self.session_id in sessions:
            self._current_session = sessions[self.session_id]
            return Path(self._current_session.plan_file_path)

        return None

    def read_plan_file(self, path: Optional[Path] = None) -> str:
        """读取 plan 文件内容

        Args:
            path: 文件路径，如果为 None 则使用当前会话的文件

        Returns:
            文件内容
        """
        if path is None:
            path = self.get_current_plan_file()

        if path is None or not path.exists():
            return ""

        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def update_plan_file(self, content: str, path: Optional[Path] = None) -> bool:
        """更新 plan 文件

        Args:
            content: 新内容
            path: 文件路径，如果为 None 则使用当前会话的文件

        Returns:
            是否成功
        """
        if path is None:
            path = self.get_current_plan_file()

        if path is None:
            return False

        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        except Exception:
            return False

    def update_session_status(self, status: str, allowed_prompts: Optional[List[Dict[str, str]]] = None):
        """更新会话状态

        Args:
            status: 新状态
            allowed_prompts: 预授权的命令列表
        """
        if self._current_session:
            self._current_session.status = status
            if allowed_prompts:
                self._current_session.allowed_prompts = allowed_prompts

            sessions = self._load_sessions()
            sessions[self.session_id] = self._current_session
            self._save_sessions(sessions)

    def get_session(self) -> Optional[PlanSession]:
        """获取当前会话"""
        if self._current_session:
            return self._current_session

        sessions = self._load_sessions()
        if self.session_id in sessions:
            self._current_session = sessions[self.session_id]
            return self._current_session

        return None

    def is_pending_approval(self) -> bool:
        """检查当前会话是否有待审批的 Plan

        Returns:
            如果有待审批的 Plan 返回 True
        """
        session = self.get_session()
        return session is not None and session.status == "pending_approval"

    def approve_plan(self) -> bool:
        """批准当前 Plan

        Returns:
            是否成功批准
        """
        session = self.get_session()
        if session is None or session.status != "pending_approval":
            return False

        # 更新状态为已批准
        self.update_session_status("approved", session.allowed_prompts)

        # 应用预授权权限
        if session.allowed_prompts:
            pm = get_permission_manager()
            pm.add_allowed_prompts(session.allowed_prompts)

        return True

    def reject_plan(self) -> bool:
        """拒绝当前 Plan

        Returns:
            是否成功拒绝
        """
        session = self.get_session()
        if session is None or session.status != "pending_approval":
            return False

        self.update_session_status("rejected")
        return True


# ==================== EnterPlanMode 工具 ====================

class EnterPlanModeTool(Tool):
    """进入 Plan 模式工具

    主动进入 plan 模式进行任务规划
    """

    def __init__(
        self,
        mode_manager: Optional[AgentModeManager] = None,
        session_id: Optional[str] = None,
        plan_file_manager: Optional[PlanFileManager] = None
    ):
        super().__init__()
        self.mode_manager = mode_manager
        self.session_id = session_id
        self.plan_file_manager = plan_file_manager or PlanFileManager(session_id)

        self.name = "enter_plan_mode"
        self.description = """主动进入 plan 模式进行任务规划。

使用场景:
- 新功能实现：需要设计架构和实现方案
- 多种实现方案可选：需要权衡不同方案
- 代码修改影响现有行为：需要评估影响范围
- 架构决策：需要做出技术选择
- 多文件变更：需要协调多个文件的修改
- 需求不明确：需要探索和澄清需求

进入 plan 模式后:
- 只能使用只读工具（read_file, grep, glob, ls 等）
- 会自动创建 plan 文件用于记录规划
- 完成规划后使用 exit_plan_mode 请求用户审批

注意: 此工具需要用户确认才能生效。
"""
        self.params = []  # 无参数

    def invoke(self, inputs: dict, **kwargs) -> str:
        """同步调用"""
        return asyncio.run(self.ainvoke(inputs, **kwargs))

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        """异步调用"""
        # 检查当前模式
        if self.mode_manager:
            current_mode = self.mode_manager.get_current_mode()
            if current_mode == AgentMode.PLAN:
                plan_file = self.plan_file_manager.get_current_plan_file()
                if plan_file:
                    return f"已经处于 PLAN 模式。\n\nPlan 文件: {plan_file}"
                else:
                    # 创建新的 plan 文件
                    plan_file = self.plan_file_manager.create_plan_file()
                    return f"已经处于 PLAN 模式，已创建 plan 文件。\n\nPlan 文件: {plan_file}"

        # 创建 plan 文件
        plan_file = self.plan_file_manager.create_plan_file()

        # 切换到 PLAN 模式
        if self.mode_manager:
            self.mode_manager.switch_mode(AgentMode.PLAN)

        return f"""已进入 PLAN 模式。

Plan 文件已创建: {plan_file}

在 PLAN 模式下:
- 可以使用只读工具探索代码库
- 请将规划内容写入 plan 文件
- 完成后使用 exit_plan_mode 请求用户审批

建议的工作流:
1. 理解需求和现有代码
2. 设计实现方案
3. 更新 plan 文件
4. 使用 exit_plan_mode 退出并请求审批
"""

    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={},
                required=[]
            )
        )


# ==================== ExitPlanMode 工具 ====================

class ExitPlanModeTool(Tool):
    """退出 Plan 模式工具

    完成规划后退出 plan 模式，请求用户审批
    """

    def __init__(
        self,
        mode_manager: Optional[AgentModeManager] = None,
        session_id: Optional[str] = None,
        plan_file_manager: Optional[PlanFileManager] = None
    ):
        super().__init__()
        self.mode_manager = mode_manager
        self.session_id = session_id
        self.plan_file_manager = plan_file_manager or PlanFileManager(session_id)

        self.name = "exit_plan_mode"
        self.description = """完成规划后退出 plan 模式，请求用户审批。

使用前提:
- 当前处于 PLAN 模式
- 已完成 plan 文件编写
- plan 文件包含完整的实现方案

调用后:
- 读取 plan 文件内容展示给用户
- 用户审批后切换到 BUILD 模式
- 预授权的命令（allowedPrompts）在后续执行时无需再次确认

allowedPrompts 示例:
[
  {"tool": "Bash", "prompt": "run tests"},
  {"tool": "Bash", "prompt": "install dependencies"},
  {"tool": "Bash", "prompt": "build the project"}
]
"""
        self.params = [
            Param(
                name="allowed_prompts",
                description="预申请的命令权限列表，格式为 JSON 数组",
                param_type="string",
                required=False
            )
        ]

    def invoke(self, inputs: dict, **kwargs) -> str:
        """同步调用"""
        return asyncio.run(self.ainvoke(inputs, **kwargs))

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        """异步调用"""
        # 检查当前模式
        if self.mode_manager:
            current_mode = self.mode_manager.get_current_mode()
            if current_mode != AgentMode.PLAN:
                return f"错误: 当前不在 PLAN 模式（当前模式: {current_mode.value}）。请先使用 enter_plan_mode 进入 PLAN 模式。"

        # 获取 plan 文件
        plan_file = self.plan_file_manager.get_current_plan_file()
        if not plan_file or not plan_file.exists():
            return "错误: 未找到 plan 文件。请先使用 enter_plan_mode 创建 plan 文件。"

        # 读取 plan 内容
        plan_content = self.plan_file_manager.read_plan_file(plan_file)

        # 检查 plan 是否为空或只有模板
        if not plan_content.strip() or plan_content.strip() == PlanFileManager.PLAN_TEMPLATE.strip():
            return f"错误: plan 文件内容为空或未修改。请先编写实现计划。\n\nPlan 文件: {plan_file}"

        # 解析 allowed_prompts
        allowed_prompts = []
        allowed_prompts_str = inputs.get("allowed_prompts", "")
        if allowed_prompts_str:
            try:
                allowed_prompts = json.loads(allowed_prompts_str)
                if not isinstance(allowed_prompts, list):
                    allowed_prompts = []
            except json.JSONDecodeError:
                pass

        # 更新会话状态
        self.plan_file_manager.update_session_status("pending_approval", allowed_prompts)

        # 构建审批请求
        result = f"""## Plan 审批请求

Plan 文件: {plan_file}

---

{plan_content}

---

"""

        if allowed_prompts:
            result += "### 预申请的命令权限:\n"
            for prompt in allowed_prompts:
                tool = prompt.get("tool", "Unknown")
                desc = prompt.get("prompt", "Unknown")
                result += f"- [{tool}] {desc}\n"
            result += "\n"

        result += """请审批此计划:
- 输入 'approve' 或 'yes' 批准计划并切换到 BUILD 模式
- 输入 'reject' 或 'no' 拒绝计划并继续规划
- 输入其他内容提供反馈

**重要**: 你必须停止执行并等待用户审批。在用户明确输入 'approve' 或 'yes' 之前，不要执行任何实现操作。

<AWAITING_USER_APPROVAL>
等待用户审批中...请勿继续执行任何操作，直到用户明确批准计划。
</AWAITING_USER_APPROVAL>"""

        return result

    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "allowed_prompts": {
                        "type": "string",
                        "description": "预申请的命令权限列表，格式为 JSON 数组"
                    }
                },
                required=[]
            )
        )


# ==================== 工具工厂 ====================

def create_plan_tools(
    mode_manager: Optional[AgentModeManager] = None,
    session_id: Optional[str] = None
) -> List[Tool]:
    """创建 plan 模式工具

    Args:
        mode_manager: 模式管理器
        session_id: 会话 ID

    Returns:
        plan 工具列表
    """
    # 共享同一个 PlanFileManager 实例
    plan_file_manager = PlanFileManager(session_id)

    return [
        EnterPlanModeTool(mode_manager, session_id, plan_file_manager),
        ExitPlanModeTool(mode_manager, session_id, plan_file_manager),
    ]
