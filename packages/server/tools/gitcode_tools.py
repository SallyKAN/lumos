"""
GitCode 工具集

封装 GitCode API，提供 PR、Issue 等操作工具
API 文档: https://docs.gitcode.com/docs/apis/

使用前需要配置环境变量:
- GITCODE_ACCESS_TOKEN: GitCode 个人访问令牌
"""

import os
import asyncio
import json
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from ..core.tool import Tool, ToolInfo, Parameters, Param

from ..agents.mode_manager import AgentModeManager


# ==================== GitCode API 客户端 ====================

class GitCodeAPIError(Exception):
    """GitCode API 错误"""
    def __init__(self, status_code: int, message: str, response: Optional[Dict] = None):
        self.status_code = status_code
        self.message = message
        self.response = response
        super().__init__(f"GitCode API Error ({status_code}): {message}")


class GitCodeClient:
    """GitCode API 客户端

    封装 GitCode REST API 调用
    """

    BASE_URL = "https://api.gitcode.com/api/v5"

    def __init__(self, access_token: Optional[str] = None):
        """初始化客户端

        Args:
            access_token: GitCode 访问令牌，如果不提供则从环境变量读取
        """
        self.access_token = access_token or os.environ.get("GITCODE_ACCESS_TOKEN")
        if not self.access_token:
            raise ValueError("未配置 GITCODE_ACCESS_TOKEN 环境变量")

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """发送 API 请求

        Args:
            method: HTTP 方法 (GET, POST, PUT, PATCH, DELETE)
            endpoint: API 端点 (不含 base URL)
            params: URL 查询参数
            data: 请求体数据

        Returns:
            API 响应 JSON
        """
        import aiohttp

        url = f"{self.BASE_URL}{endpoint}"

        # 添加 access_token 到参数
        if params is None:
            params = {}
        params["access_token"] = self.access_token

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        timeout = aiohttp.ClientTimeout(total=30)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request(
                method,
                url,
                params=params,
                json=data if data else None,
                headers=headers
            ) as response:
                response_text = await response.text()

                try:
                    response_json = json.loads(response_text) if response_text else {}
                except json.JSONDecodeError:
                    response_json = {"raw": response_text}

                if response.status >= 400:
                    error_msg = response_json.get("message", response_text)
                    raise GitCodeAPIError(response.status, error_msg, response_json)

                return response_json

    # ==================== Pull Request API ====================

    async def create_pull_request(
        self,
        owner: str,
        repo: str,
        title: str,
        head: str,
        base: str,
        body: Optional[str] = None,
        milestone_number: Optional[int] = None,
        labels: Optional[List[str]] = None,
        assignees: Optional[List[str]] = None,
        testers: Optional[List[str]] = None,
        draft: bool = False,
        prune_source_branch: bool = False
    ) -> Dict[str, Any]:
        """创建 Pull Request

        Args:
            owner: 仓库所属空间地址 (企业、组织或个人的地址 path)
            repo: 仓库路径 (path)
            title: PR 标题
            head: 源分支 (格式: branch 或 username:branch)
            base: 目标分支
            body: PR 描述
            milestone_number: 里程碑序号
            labels: 标签列表
            assignees: 审查人员列表
            testers: 测试人员列表
            draft: 是否为草稿
            prune_source_branch: 合并后是否删除源分支

        Returns:
            创建的 PR 信息
        """
        data = {
            "title": title,
            "head": head,
            "base": base
        }

        if body:
            data["body"] = body
        if milestone_number:
            data["milestone_number"] = milestone_number
        if labels:
            data["labels"] = ",".join(labels)
        if assignees:
            data["assignees"] = ",".join(assignees)
        if testers:
            data["testers"] = ",".join(testers)
        if draft:
            data["draft"] = draft
        if prune_source_branch:
            data["prune_source_branch"] = prune_source_branch

        return await self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls",
            data=data
        )

    async def list_pull_requests(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        head: Optional[str] = None,
        base: Optional[str] = None,
        sort: str = "created",
        direction: str = "desc",
        page: int = 1,
        per_page: int = 20
    ) -> List[Dict[str, Any]]:
        """获取 PR 列表

        Args:
            owner: 仓库所属空间地址
            repo: 仓库路径
            state: PR 状态 (open, closed, merged, all)
            head: 源分支筛选
            base: 目标分支筛选
            sort: 排序字段 (created, updated, popularity, long-running)
            direction: 排序方向 (asc, desc)
            page: 页码
            per_page: 每页数量

        Returns:
            PR 列表
        """
        params = {
            "state": state,
            "sort": sort,
            "direction": direction,
            "page": page,
            "per_page": per_page
        }

        if head:
            params["head"] = head
        if base:
            params["base"] = base

        return await self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls",
            params=params
        )

    async def get_pull_request(
        self,
        owner: str,
        repo: str,
        number: int
    ) -> Dict[str, Any]:
        """获取单个 PR 详情

        Args:
            owner: 仓库所属空间地址
            repo: 仓库路径
            number: PR 编号

        Returns:
            PR 详情
        """
        return await self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{number}"
        )

    async def merge_pull_request(
        self,
        owner: str,
        repo: str,
        number: int,
        merge_method: str = "merge",
        prune_source_branch: bool = False,
        title: Optional[str] = None,
        description: Optional[str] = None
    ) -> Dict[str, Any]:
        """合并 PR

        Args:
            owner: 仓库所属空间地址
            repo: 仓库路径
            number: PR 编号
            merge_method: 合并方式 (merge, squash, rebase)
            prune_source_branch: 合并后是否删除源分支
            title: 合并标题
            description: 合并描述

        Returns:
            合并结果
        """
        data = {
            "merge_method": merge_method,
            "prune_source_branch": prune_source_branch
        }

        if title:
            data["title"] = title
        if description:
            data["description"] = description

        return await self._request(
            "PUT",
            f"/repos/{owner}/{repo}/pulls/{number}/merge",
            data=data
        )

    async def get_pull_request_comments(
        self,
        owner: str,
        repo: str,
        number: int,
        page: int = 1,
        per_page: int = 20
    ) -> List[Dict[str, Any]]:
        """获取 PR 评论

        Args:
            owner: 仓库所属空间地址
            repo: 仓库路径
            number: PR 编号
            page: 页码
            per_page: 每页数量

        Returns:
            评论列表
        """
        params = {
            "page": page,
            "per_page": per_page
        }

        return await self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{number}/comments",
            params=params
        )

    # ==================== Issue API ====================

    async def create_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: Optional[str] = None,
        assignee: Optional[str] = None,
        milestone: Optional[int] = None,
        labels: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """创建 Issue

        Args:
            owner: 仓库所属空间地址
            repo: 仓库路径
            title: Issue 标题
            body: Issue 内容
            assignee: 负责人
            milestone: 里程碑编号
            labels: 标签列表

        Returns:
            创建的 Issue 信息
        """
        data = {
            "title": title,
            "repo": repo
        }

        if body:
            data["body"] = body
        if assignee:
            data["assignee"] = assignee
        if milestone:
            data["milestone"] = milestone
        if labels:
            data["labels"] = ",".join(labels)

        return await self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues",
            data=data
        )

    async def list_issues(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        labels: Optional[str] = None,
        sort: str = "created",
        direction: str = "desc",
        page: int = 1,
        per_page: int = 20
    ) -> List[Dict[str, Any]]:
        """获取 Issue 列表

        Args:
            owner: 仓库所属空间地址
            repo: 仓库路径
            state: Issue 状态 (open, progressing, closed, rejected, all)
            labels: 标签筛选 (逗号分隔)
            sort: 排序字段 (created, updated)
            direction: 排序方向 (asc, desc)
            page: 页码
            per_page: 每页数量

        Returns:
            Issue 列表
        """
        params = {
            "state": state,
            "sort": sort,
            "direction": direction,
            "page": page,
            "per_page": per_page
        }

        if labels:
            params["labels"] = labels

        return await self._request(
            "GET",
            f"/repos/{owner}/{repo}/issues",
            params=params
        )

    async def get_issue(
        self,
        owner: str,
        repo: str,
        number: str
    ) -> Dict[str, Any]:
        """获取单个 Issue 详情

        Args:
            owner: 仓库所属空间地址
            repo: 仓库路径
            number: Issue 编号

        Returns:
            Issue 详情
        """
        return await self._request(
            "GET",
            f"/repos/{owner}/{repo}/issues/{number}"
        )

    # ==================== Repository API ====================

    async def get_repo(self, owner: str, repo: str) -> Dict[str, Any]:
        """获取仓库信息

        Args:
            owner: 仓库所属空间地址
            repo: 仓库路径

        Returns:
            仓库信息
        """
        return await self._request(
            "GET",
            f"/repos/{owner}/{repo}"
        )

    async def list_branches(
        self,
        owner: str,
        repo: str,
        page: int = 1,
        per_page: int = 20
    ) -> List[Dict[str, Any]]:
        """获取分支列表

        Args:
            owner: 仓库所属空间地址
            repo: 仓库路径
            page: 页码
            per_page: 每页数量

        Returns:
            分支列表
        """
        params = {
            "page": page,
            "per_page": per_page
        }

        return await self._request(
            "GET",
            f"/repos/{owner}/{repo}/branches",
            params=params
        )


# 全局客户端实例（延迟初始化）
_gitcode_client: Optional[GitCodeClient] = None


def get_gitcode_client() -> GitCodeClient:
    """获取 GitCode 客户端实例"""
    global _gitcode_client
    if _gitcode_client is None:
        _gitcode_client = GitCodeClient()
    return _gitcode_client


# ==================== GitCode 工具类 ====================

class GitCodeCreatePRTool(Tool):
    """创建 GitCode Pull Request 工具"""

    def __init__(self, mode_manager: Optional[AgentModeManager] = None):
        super().__init__()
        self.mode_manager = mode_manager
        self.name = "gitcode_create_pr"
        self.description = """创建 GitCode Pull Request。

使用说明:
- 在 GitCode 仓库中创建新的 Pull Request
- 需要配置 GITCODE_ACCESS_TOKEN 环境变量
- owner 和 repo 可以从仓库 URL 中获取，如 https://gitcode.com/owner/repo
- 支持从 fork 仓库创建 PR 到上游仓库

参数:
- owner: 目标仓库所属空间地址（必需），即 PR 要合并到的仓库
- repo: 目标仓库路径（必需）
- title: PR 标题（必需）
- head: 源分支（必需），格式为 "branch" 或 "fork_owner:branch"
- base: 目标分支（必需）
- head_owner: 源分支所在仓库的 owner（可选），用于从 fork 创建 PR
  - 如果不指定，会自动获取当前用户作为 head_owner
  - 如果 head_owner 与 owner 相同，则不添加前缀
- body: PR 描述（可选）
- labels: 标签列表，逗号分隔（可选）
- assignees: 审查人员列表，逗号分隔（可选）
- draft: 是否为草稿 PR（可选，默认 false）

示例:
1. 同仓库 PR（不需要 head_owner）:
   owner: "Lumos", repo: "agent-core", head: "feature-branch", base: "develop"

2. 从 fork 创建 PR（推荐使用 head_owner）:
   owner: "Lumos", repo: "agent-core", head: "fix-bug", base: "develop", head_owner: "SnapeK"
   -> 自动转换为 head: "SnapeK:fix-bug"

3. 手动指定完整 head 格式:
   owner: "Lumos", repo: "agent-core", head: "SnapeK:fix-bug", base: "develop"
"""
        self.params = [
            Param(name="owner", description="目标仓库所属空间地址", param_type="string", required=True),
            Param(name="repo", description="目标仓库路径", param_type="string", required=True),
            Param(name="title", description="PR 标题", param_type="string", required=True),
            Param(name="head", description="源分支，格式为 'branch' 或 'fork_owner:branch'", param_type="string", required=True),
            Param(name="base", description="目标分支", param_type="string", required=True),
            Param(name="head_owner", description="源分支所在仓库的 owner（用于从 fork 创建 PR）", param_type="string", required=False),
            Param(name="body", description="PR 描述", param_type="string", required=False),
            Param(name="labels", description="标签列表，逗号分隔", param_type="string", required=False),
            Param(name="assignees", description="审查人员列表，逗号分隔", param_type="string", required=False),
            Param(name="draft", description="是否为草稿 PR", param_type="boolean", required=False),
        ]

    def invoke(self, inputs: dict, **kwargs) -> str:
        return asyncio.run(self.ainvoke(inputs, **kwargs))

    async def _get_current_user(self, client: GitCodeClient) -> Optional[str]:
        """获取当前认证用户的 login 名"""
        try:
            user_info = await client._request("GET", "/user")
            return user_info.get("login")
        except Exception:
            return None

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        owner = inputs.get("owner", "").strip()
        repo = inputs.get("repo", "").strip()
        title = inputs.get("title", "").strip()
        head = inputs.get("head", "").strip()
        base = inputs.get("base", "").strip()
        head_owner = inputs.get("head_owner", "").strip() if inputs.get("head_owner") else None
        body = inputs.get("body", "").strip() if inputs.get("body") else None
        labels_str = inputs.get("labels", "")
        assignees_str = inputs.get("assignees", "")
        draft = inputs.get("draft", False)

        # 参数验证
        if not owner:
            return "错误: 未指定 owner (目标仓库)"
        if not repo:
            return "错误: 未指定 repo"
        if not title:
            return "错误: 未指定 title"
        if not head:
            return "错误: 未指定 head (源分支)"
        if not base:
            return "错误: 未指定 base (目标分支)"

        # 解析列表参数
        labels = [l.strip() for l in labels_str.split(",") if l.strip()] if labels_str else None
        assignees = [a.strip() for a in assignees_str.split(",") if a.strip()] if assignees_str else None

        try:
            client = get_gitcode_client()

            # 处理 head 参数，支持从 fork 创建 PR
            # 如果 head 中没有 ":"，且指定了 head_owner 或需要自动获取
            if ":" not in head:
                if head_owner:
                    # 使用指定的 head_owner
                    if head_owner != owner:
                        head = f"{head_owner}:{head}"
                else:
                    # 自动获取当前用户
                    current_user = await self._get_current_user(client)
                    if current_user and current_user != owner:
                        head = f"{current_user}:{head}"
                        head_owner = current_user  # 用于输出显示

            result = await client.create_pull_request(
                owner=owner,
                repo=repo,
                title=title,
                head=head,
                base=base,
                body=body,
                labels=labels,
                assignees=assignees,
                draft=draft
            )

            # 格式化输出
            pr_number = result.get("number") or result.get("iid", "N/A")
            pr_url = result.get("html_url") or result.get("web_url", f"https://gitcode.com/{owner}/{repo}/merge_requests/{pr_number}")
            pr_state = result.get("state", "unknown")

            # 显示源仓库信息
            source_info = f"{head_owner}/{repo}" if head_owner and head_owner != owner else f"{owner}/{repo}"

            return f"""PR 创建成功!

编号: #{pr_number}
标题: {title}
状态: {pr_state}
源: {source_info} ({head.split(':')[-1]})
目标: {owner}/{repo} ({base})
URL: {pr_url}
"""

        except ValueError as e:
            return f"配置错误: {str(e)}"
        except GitCodeAPIError as e:
            error_detail = e.message
            # 提供更友好的错误提示
            if "Can not find the branch" in str(e.message):
                error_detail += f"\n\n提示: 请确保分支已推送到你的 fork 仓库。如果从 fork 创建 PR，请指定 head_owner 参数或使用 'fork_owner:branch' 格式的 head。"
            return f"GitCode API 错误 ({e.status_code}): {error_detail}"
        except Exception as e:
            return f"创建 PR 失败: {str(e)}"

    def get_tool_info(self) -> ToolInfo:
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "owner": {"type": "string", "description": "目标仓库所属空间地址（PR 要合并到的仓库）"},
                    "repo": {"type": "string", "description": "目标仓库路径"},
                    "title": {"type": "string", "description": "PR 标题"},
                    "head": {"type": "string", "description": "源分支，格式为 'branch' 或 'fork_owner:branch'"},
                    "base": {"type": "string", "description": "目标分支"},
                    "head_owner": {"type": "string", "description": "源分支所在仓库的 owner（用于从 fork 创建 PR，不指定则自动获取当前用户）"},
                    "body": {"type": "string", "description": "PR 描述"},
                    "labels": {"type": "string", "description": "标签列表，逗号分隔"},
                    "assignees": {"type": "string", "description": "审查人员列表，逗号分隔"},
                    "draft": {"type": "boolean", "description": "是否为草稿 PR"}
                },
                required=["owner", "repo", "title", "head", "base"]
            )
        )


class GitCodeListPRsTool(Tool):
    """获取 GitCode PR 列表工具"""

    def __init__(self, mode_manager: Optional[AgentModeManager] = None):
        super().__init__()
        self.mode_manager = mode_manager
        self.name = "gitcode_list_prs"
        self.description = """获取 GitCode 仓库的 Pull Request 列表。

使用说明:
- 列出指定仓库的 PR
- 可按状态、分支筛选
- 支持分页

参数:
- owner: 仓库所属空间地址（必需）
- repo: 仓库路径（必需）
- state: PR 状态 (open/closed/merged/all)，默认 open
- base: 目标分支筛选（可选）
- page: 页码，默认 1
- per_page: 每页数量，默认 20
"""
        self.params = [
            Param(name="owner", description="仓库所属空间地址", param_type="string", required=True),
            Param(name="repo", description="仓库路径", param_type="string", required=True),
            Param(name="state", description="PR 状态", param_type="string", required=False),
            Param(name="base", description="目标分支筛选", param_type="string", required=False),
            Param(name="page", description="页码", param_type="integer", required=False),
            Param(name="per_page", description="每页数量", param_type="integer", required=False),
        ]

    def invoke(self, inputs: dict, **kwargs) -> str:
        return asyncio.run(self.ainvoke(inputs, **kwargs))

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        owner = inputs.get("owner", "").strip()
        repo = inputs.get("repo", "").strip()
        state = inputs.get("state", "open")
        base = inputs.get("base")
        page = inputs.get("page", 1)
        per_page = inputs.get("per_page", 20)

        if not owner:
            return "错误: 未指定 owner"
        if not repo:
            return "错误: 未指定 repo"

        try:
            client = get_gitcode_client()
            prs = await client.list_pull_requests(
                owner=owner,
                repo=repo,
                state=state,
                base=base,
                page=page,
                per_page=per_page
            )

            if not prs:
                return f"没有找到 {state} 状态的 PR"

            # 格式化输出
            lines = [f"找到 {len(prs)} 个 PR (状态: {state}):\n"]
            for pr in prs:
                pr_num = pr.get("number", "?")
                pr_title = pr.get("title", "无标题")
                pr_state = pr.get("state", "unknown")
                pr_user = pr.get("user", {}).get("login", "unknown")
                pr_head = pr.get("head", {}).get("ref", "?")
                pr_base = pr.get("base", {}).get("ref", "?")
                lines.append(f"  #{pr_num} [{pr_state}] {pr_title}")
                lines.append(f"      作者: {pr_user} | {pr_head} -> {pr_base}")

            return "\n".join(lines)

        except ValueError as e:
            return f"配置错误: {str(e)}"
        except GitCodeAPIError as e:
            return f"GitCode API 错误 ({e.status_code}): {e.message}"
        except Exception as e:
            return f"获取 PR 列表失败: {str(e)}"

    def get_tool_info(self) -> ToolInfo:
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "owner": {"type": "string", "description": "仓库所属空间地址"},
                    "repo": {"type": "string", "description": "仓库路径"},
                    "state": {"type": "string", "description": "PR 状态", "enum": ["open", "closed", "merged", "all"]},
                    "base": {"type": "string", "description": "目标分支筛选"},
                    "page": {"type": "integer", "description": "页码"},
                    "per_page": {"type": "integer", "description": "每页数量"}
                },
                required=["owner", "repo"]
            )
        )


class GitCodeGetPRTool(Tool):
    """获取 GitCode PR 详情工具"""

    def __init__(self, mode_manager: Optional[AgentModeManager] = None):
        super().__init__()
        self.mode_manager = mode_manager
        self.name = "gitcode_get_pr"
        self.description = """获取 GitCode Pull Request 详情。

使用说明:
- 获取指定 PR 的详细信息
- 包括标题、描述、状态、分支、评论等

参数:
- owner: 仓库所属空间地址（必需）
- repo: 仓库路径（必需）
- number: PR 编号（必需）
"""
        self.params = [
            Param(name="owner", description="仓库所属空间地址", param_type="string", required=True),
            Param(name="repo", description="仓库路径", param_type="string", required=True),
            Param(name="number", description="PR 编号", param_type="integer", required=True),
        ]

    def invoke(self, inputs: dict, **kwargs) -> str:
        return asyncio.run(self.ainvoke(inputs, **kwargs))

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        owner = inputs.get("owner", "").strip()
        repo = inputs.get("repo", "").strip()
        number = inputs.get("number")

        if not owner:
            return "错误: 未指定 owner"
        if not repo:
            return "错误: 未指定 repo"
        if not number:
            return "错误: 未指定 PR 编号"

        try:
            client = get_gitcode_client()
            pr = await client.get_pull_request(owner=owner, repo=repo, number=int(number))

            # 格式化输出
            lines = [
                f"PR #{pr.get('number', '?')}: {pr.get('title', '无标题')}",
                f"状态: {pr.get('state', 'unknown')}",
                f"作者: {pr.get('user', {}).get('login', 'unknown')}",
                f"分支: {pr.get('head', {}).get('ref', '?')} -> {pr.get('base', {}).get('ref', '?')}",
                f"创建时间: {pr.get('created_at', 'unknown')}",
                f"更新时间: {pr.get('updated_at', 'unknown')}",
                f"URL: {pr.get('html_url', 'N/A')}",
                "",
                "描述:",
                pr.get("body", "无描述") or "无描述"
            ]

            return "\n".join(lines)

        except ValueError as e:
            return f"配置错误: {str(e)}"
        except GitCodeAPIError as e:
            return f"GitCode API 错误 ({e.status_code}): {e.message}"
        except Exception as e:
            return f"获取 PR 详情失败: {str(e)}"

    def get_tool_info(self) -> ToolInfo:
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "owner": {"type": "string", "description": "仓库所属空间地址"},
                    "repo": {"type": "string", "description": "仓库路径"},
                    "number": {"type": "integer", "description": "PR 编号"}
                },
                required=["owner", "repo", "number"]
            )
        )


class GitCodeMergePRTool(Tool):
    """合并 GitCode PR 工具"""

    def __init__(self, mode_manager: Optional[AgentModeManager] = None):
        super().__init__()
        self.mode_manager = mode_manager
        self.name = "gitcode_merge_pr"
        self.description = """合并 GitCode Pull Request。

使用说明:
- 合并指定的 PR
- 支持多种合并方式

参数:
- owner: 仓库所属空间地址（必需）
- repo: 仓库路径（必需）
- number: PR 编号（必需）
- merge_method: 合并方式 (merge/squash/rebase)，默认 merge
- prune_source_branch: 合并后是否删除源分支，默认 false
"""
        self.params = [
            Param(name="owner", description="仓库所属空间地址", param_type="string", required=True),
            Param(name="repo", description="仓库路径", param_type="string", required=True),
            Param(name="number", description="PR 编号", param_type="integer", required=True),
            Param(name="merge_method", description="合并方式", param_type="string", required=False),
            Param(name="prune_source_branch", description="合并后是否删除源分支", param_type="boolean", required=False),
        ]

    def invoke(self, inputs: dict, **kwargs) -> str:
        return asyncio.run(self.ainvoke(inputs, **kwargs))

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        owner = inputs.get("owner", "").strip()
        repo = inputs.get("repo", "").strip()
        number = inputs.get("number")
        merge_method = inputs.get("merge_method", "merge")
        prune_source_branch = inputs.get("prune_source_branch", False)

        if not owner:
            return "错误: 未指定 owner"
        if not repo:
            return "错误: 未指定 repo"
        if not number:
            return "错误: 未指定 PR 编号"

        try:
            client = get_gitcode_client()
            result = await client.merge_pull_request(
                owner=owner,
                repo=repo,
                number=int(number),
                merge_method=merge_method,
                prune_source_branch=prune_source_branch
            )

            return f"PR #{number} 合并成功! (方式: {merge_method})"

        except ValueError as e:
            return f"配置错误: {str(e)}"
        except GitCodeAPIError as e:
            return f"GitCode API 错误 ({e.status_code}): {e.message}"
        except Exception as e:
            return f"合并 PR 失败: {str(e)}"

    def get_tool_info(self) -> ToolInfo:
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "owner": {"type": "string", "description": "仓库所属空间地址"},
                    "repo": {"type": "string", "description": "仓库路径"},
                    "number": {"type": "integer", "description": "PR 编号"},
                    "merge_method": {"type": "string", "description": "合并方式", "enum": ["merge", "squash", "rebase"]},
                    "prune_source_branch": {"type": "boolean", "description": "合并后是否删除源分支"}
                },
                required=["owner", "repo", "number"]
            )
        )


class GitCodeCreateIssueTool(Tool):
    """创建 GitCode Issue 工具"""

    def __init__(self, mode_manager: Optional[AgentModeManager] = None):
        super().__init__()
        self.mode_manager = mode_manager
        self.name = "gitcode_create_issue"
        self.description = """创建 GitCode Issue。

使用说明:
- 在 GitCode 仓库中创建新的 Issue
- 需要配置 GITCODE_ACCESS_TOKEN 环境变量

参数:
- owner: 仓库所属空间地址（必需）
- repo: 仓库路径（必需）
- title: Issue 标题（必需）
- body: Issue 内容（可选）
- labels: 标签列表，逗号分隔（可选）
- assignee: 负责人（可选）
"""
        self.params = [
            Param(name="owner", description="仓库所属空间地址", param_type="string", required=True),
            Param(name="repo", description="仓库路径", param_type="string", required=True),
            Param(name="title", description="Issue 标题", param_type="string", required=True),
            Param(name="body", description="Issue 内容", param_type="string", required=False),
            Param(name="labels", description="标签列表，逗号分隔", param_type="string", required=False),
            Param(name="assignee", description="负责人", param_type="string", required=False),
        ]

    def invoke(self, inputs: dict, **kwargs) -> str:
        return asyncio.run(self.ainvoke(inputs, **kwargs))

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        owner = inputs.get("owner", "").strip()
        repo = inputs.get("repo", "").strip()
        title = inputs.get("title", "").strip()
        body = inputs.get("body", "").strip() if inputs.get("body") else None
        labels_str = inputs.get("labels", "")
        assignee = inputs.get("assignee", "").strip() if inputs.get("assignee") else None

        if not owner:
            return "错误: 未指定 owner"
        if not repo:
            return "错误: 未指定 repo"
        if not title:
            return "错误: 未指定 title"

        labels = [l.strip() for l in labels_str.split(",") if l.strip()] if labels_str else None

        try:
            client = get_gitcode_client()
            result = await client.create_issue(
                owner=owner,
                repo=repo,
                title=title,
                body=body,
                labels=labels,
                assignee=assignee
            )

            issue_number = result.get("number", "N/A")
            issue_url = result.get("html_url", f"https://gitcode.com/{owner}/{repo}/issues/{issue_number}")

            return f"""Issue 创建成功!

编号: #{issue_number}
标题: {title}
URL: {issue_url}
"""

        except ValueError as e:
            return f"配置错误: {str(e)}"
        except GitCodeAPIError as e:
            return f"GitCode API 错误 ({e.status_code}): {e.message}"
        except Exception as e:
            return f"创建 Issue 失败: {str(e)}"

    def get_tool_info(self) -> ToolInfo:
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "owner": {"type": "string", "description": "仓库所属空间地址"},
                    "repo": {"type": "string", "description": "仓库路径"},
                    "title": {"type": "string", "description": "Issue 标题"},
                    "body": {"type": "string", "description": "Issue 内容"},
                    "labels": {"type": "string", "description": "标签列表，逗号分隔"},
                    "assignee": {"type": "string", "description": "负责人"}
                },
                required=["owner", "repo", "title"]
            )
        )


class GitCodeGetIssueTool(Tool):
    """获取 GitCode Issue 详情工具"""

    def __init__(self, mode_manager: Optional[AgentModeManager] = None):
        super().__init__()
        self.mode_manager = mode_manager
        self.name = "gitcode_get_issue"
        self.description = """获取 GitCode Issue 详情。

使用说明:
- 获取指定 Issue 的详细信息
- 包括标题、描述、状态、标签、负责人等

参数:
- owner: 仓库所属空间地址（必需）
- repo: 仓库路径（必需）
- number: Issue 编号（必需）

示例:
- owner: "lumos", repo: "agent-core", number: "I123ABC"
"""
        self.params = [
            Param(name="owner", description="仓库所属空间地址", param_type="string", required=True),
            Param(name="repo", description="仓库路径", param_type="string", required=True),
            Param(name="number", description="Issue 编号", param_type="string", required=True),
        ]

    def invoke(self, inputs: dict, **kwargs) -> str:
        return asyncio.run(self.ainvoke(inputs, **kwargs))

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        owner = inputs.get("owner", "").strip()
        repo = inputs.get("repo", "").strip()
        number = inputs.get("number", "").strip() if inputs.get("number") else ""

        if not owner:
            return "错误: 未指定 owner"
        if not repo:
            return "错误: 未指定 repo"
        if not number:
            return "错误: 未指定 Issue 编号"

        try:
            client = get_gitcode_client()
            issue = await client.get_issue(owner=owner, repo=repo, number=number)

            # 格式化输出
            labels = issue.get("labels", [])
            label_names = [l.get("name", "") for l in labels] if labels else []

            lines = [
                f"Issue #{issue.get('number', '?')}: {issue.get('title', '无标题')}",
                f"状态: {issue.get('state', 'unknown')}",
                f"作者: {issue.get('user', {}).get('login', 'unknown')}",
                f"负责人: {issue.get('assignee', {}).get('login', '未分配') if issue.get('assignee') else '未分配'}",
                f"标签: {', '.join(label_names) if label_names else '无'}",
                f"创建时间: {issue.get('created_at', 'unknown')}",
                f"更新时间: {issue.get('updated_at', 'unknown')}",
                f"URL: {issue.get('html_url', 'N/A')}",
                "",
                "描述:",
                issue.get("body", "无描述") or "无描述"
            ]

            return "\n".join(lines)

        except ValueError as e:
            return f"配置错误: {str(e)}"
        except GitCodeAPIError as e:
            return f"GitCode API 错误 ({e.status_code}): {e.message}"
        except Exception as e:
            return f"获取 Issue 详情失败: {str(e)}"

    def get_tool_info(self) -> ToolInfo:
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "owner": {"type": "string", "description": "仓库所属空间地址"},
                    "repo": {"type": "string", "description": "仓库路径"},
                    "number": {"type": "string", "description": "Issue 编号"}
                },
                required=["owner", "repo", "number"]
            )
        )


class GitCodeListIssuesTool(Tool):
    """获取 GitCode Issue 列表工具"""

    def __init__(self, mode_manager: Optional[AgentModeManager] = None):
        super().__init__()
        self.mode_manager = mode_manager
        self.name = "gitcode_list_issues"
        self.description = """获取 GitCode 仓库的 Issue 列表。

使用说明:
- 列出指定仓库的 Issue
- 可按状态、标签筛选
- 支持分页

参数:
- owner: 仓库所属空间地址（必需）
- repo: 仓库路径（必需）
- state: Issue 状态 (open/progressing/closed/rejected/all)，默认 open
- labels: 标签筛选，逗号分隔（可选）
- page: 页码，默认 1
- per_page: 每页数量，默认 20
"""
        self.params = [
            Param(name="owner", description="仓库所属空间地址", param_type="string", required=True),
            Param(name="repo", description="仓库路径", param_type="string", required=True),
            Param(name="state", description="Issue 状态", param_type="string", required=False),
            Param(name="labels", description="标签筛选，逗号分隔", param_type="string", required=False),
            Param(name="page", description="页码", param_type="integer", required=False),
            Param(name="per_page", description="每页数量", param_type="integer", required=False),
        ]

    def invoke(self, inputs: dict, **kwargs) -> str:
        return asyncio.run(self.ainvoke(inputs, **kwargs))

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        owner = inputs.get("owner", "").strip()
        repo = inputs.get("repo", "").strip()
        state = inputs.get("state", "open")
        labels = inputs.get("labels")
        page = inputs.get("page", 1)
        per_page = inputs.get("per_page", 20)

        if not owner:
            return "错误: 未指定 owner"
        if not repo:
            return "错误: 未指定 repo"

        try:
            client = get_gitcode_client()
            issues = await client.list_issues(
                owner=owner,
                repo=repo,
                state=state,
                labels=labels,
                page=page,
                per_page=per_page
            )

            if not issues:
                return f"没有找到 {state} 状态的 Issue"

            lines = [f"找到 {len(issues)} 个 Issue (状态: {state}):\n"]
            for issue in issues:
                issue_num = issue.get("number", "?")
                issue_title = issue.get("title", "无标题")
                issue_state = issue.get("state", "unknown")
                issue_user = issue.get("user", {}).get("login", "unknown")
                lines.append(f"  #{issue_num} [{issue_state}] {issue_title}")
                lines.append(f"      作者: {issue_user}")

            return "\n".join(lines)

        except ValueError as e:
            return f"配置错误: {str(e)}"
        except GitCodeAPIError as e:
            return f"GitCode API 错误 ({e.status_code}): {e.message}"
        except Exception as e:
            return f"获取 Issue 列表失败: {str(e)}"

    def get_tool_info(self) -> ToolInfo:
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "owner": {"type": "string", "description": "仓库所属空间地址"},
                    "repo": {"type": "string", "description": "仓库路径"},
                    "state": {"type": "string", "description": "Issue 状态", "enum": ["open", "progressing", "closed", "rejected", "all"]},
                    "labels": {"type": "string", "description": "标签筛选，逗号分隔"},
                    "page": {"type": "integer", "description": "页码"},
                    "per_page": {"type": "integer", "description": "每页数量"}
                },
                required=["owner", "repo"]
            )
        )


# ==================== 工具工厂 ====================

def create_gitcode_tools(
    mode_manager: Optional[AgentModeManager] = None
) -> List[Tool]:
    """创建所有 GitCode 工具实例

    Args:
        mode_manager: 模式管理器

    Returns:
        GitCode 工具列表
    """
    return [
        GitCodeCreatePRTool(mode_manager),
        GitCodeListPRsTool(mode_manager),
        GitCodeGetPRTool(mode_manager),
        GitCodeMergePRTool(mode_manager),
        GitCodeCreateIssueTool(mode_manager),
        GitCodeGetIssueTool(mode_manager),
        GitCodeListIssuesTool(mode_manager),
    ]
