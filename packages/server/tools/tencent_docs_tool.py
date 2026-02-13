"""
腾讯文档专用工具

直接使用 Playwright 执行已知操作流程，
比 browser-use 快 10-50 倍。

适用场景：
- 创建文档/表格
- 填写表单数据
- 导出文档

不适用：
- 探索性任务（不知道具体步骤）
"""

import os
import json
import asyncio
from typing import Optional, List, Dict, Any
from pathlib import Path


from ..core.tool import Tool, ToolInfo, Parameters, Param

from ..agents.mode_manager import AgentModeManager, AgentMode


# 默认 cookies 路径
DEFAULT_COOKIES_PATH = os.path.expanduser("~/.lumos/browser_cookies.json")


class TencentDocsCreateSheetTool(Tool):
    """腾讯文档：创建智能表格

    直接执行 Playwright 脚本，不使用 AI 驱动。
    速度比 browser-use 快 10-50 倍。
    """

    def __init__(
        self,
        mode_manager: Optional[AgentModeManager] = None,
        headless: bool = False
    ):
        super().__init__()
        self.mode_manager = mode_manager
        self.headless = headless

        self.name = "tencent_docs_create_sheet"
        self.description = """在腾讯文档中创建智能表格。

使用说明:
- 快速创建腾讯文档智能表格
- 自动使用已保存的登录状态（无需登录）
- 比 browser_use_task 快 10-50 倍

参数:
- sheet_name: 表格名称（必需）
- columns: 列名列表（可选，如 ["姓名", "金额", "日期"]）

示例:
- sheet_name: "报销表格"
- columns: ["发票号", "金额", "日期", "备注"]
"""
        self.params = [
            Param(
                name="sheet_name",
                description="表格名称",
                param_type="string",
                required=True
            ),
            Param(
                name="columns",
                description="列名列表（JSON 数组格式）",
                param_type="string",
                required=False
            ),
        ]

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        """异步执行"""
        # 模式检查
        if (self.mode_manager and
                self.mode_manager.get_current_mode() != AgentMode.BUILD):
            mode = self.mode_manager.get_current_mode().value
            return f"错误: 此工具在 {mode} 模式下不可用。请切换到 BUILD 模式。"

        sheet_name = inputs.get("sheet_name", "新建表格")
        columns_str = inputs.get("columns", "")

        # 解析列名
        columns = []
        if columns_str:
            try:
                columns = json.loads(columns_str)
            except json.JSONDecodeError:
                columns = [c.strip() for c in columns_str.split(",")]

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return "错误: playwright 未安装。请运行: pip install playwright"

        # 检查 cookies 是否存在
        if not os.path.exists(DEFAULT_COOKIES_PATH):
            return (
                "错误: 未找到登录状态。"
                "请先运行 python scripts/save_browser_cookies_auto.py "
                "登录腾讯文档。"
            )

        try:
            async with async_playwright() as p:
                # 启动浏览器并加载 cookies
                browser = await p.chromium.launch(headless=self.headless)
                context = await browser.new_context(
                    storage_state=DEFAULT_COOKIES_PATH,
                    viewport={'width': 1280, 'height': 800}
                )
                page = await context.new_page()
                page.set_default_timeout(60000)

                # 1. 打开腾讯文档首页
                print("[腾讯文档] 正在打开 docs.qq.com...")
                await page.goto(
                    'https://docs.qq.com',
                    wait_until='domcontentloaded'
                )
                await page.wait_for_timeout(3000)

                # 2. 点击 New 按钮
                print("[腾讯文档] 点击 New 按钮...")
                new_btn = page.locator('text=New').first
                if not await new_btn.is_visible(timeout=5000):
                    new_btn = page.locator('text=新建').first
                await new_btn.click()
                await page.wait_for_timeout(2000)

                # 3. 点击 Smart Sheet
                print("[腾讯文档] 选择 Smart Sheet...")
                sheet_btn = page.locator('text=Smart Sheet').first
                if not await sheet_btn.is_visible(timeout=3000):
                    sheet_btn = page.locator('text=智能表格').first
                await sheet_btn.click()
                await page.wait_for_timeout(3000)

                # 4. 在 iframe 中点击空白智能表格，等待新页面
                print("[腾讯文档] 创建空白智能表格...")
                async with context.expect_page() as new_page_info:
                    iframe = page.frame_locator('iframe').first
                    await iframe.locator('text=空白智能表格').click()

                new_page = await new_page_info.value
                await new_page.wait_for_timeout(5000)

                # 获取新表格 URL
                current_url = new_page.url
                # 清理 URL 参数
                if '?' in current_url:
                    current_url = current_url.split('?')[0]
                print(f"[腾讯文档] 表格链接: {current_url}")

                # 5. 修改表格名称（在新页面中）
                print(f"[腾讯文档] 修改表格名称为: {sheet_name}")
                try:
                    # 尝试点击标题区域并输入新名称
                    title_area = new_page.locator(
                        '[class*="title"], [class*="name"]'
                    ).first
                    if await title_area.is_visible(timeout=3000):
                        await title_area.click()
                        await new_page.wait_for_timeout(500)
                        await new_page.keyboard.press('Control+A')
                        await new_page.keyboard.type(sheet_name)
                        await new_page.keyboard.press('Enter')
                        await new_page.wait_for_timeout(1000)
                except Exception as e:
                    print(f"[腾讯文档] 重命名失败: {e}")

                # 截图保存
                screenshot_path = f"/tmp/tencent_sheet.png"
                await new_page.screenshot(path=screenshot_path)

                await browser.close()

                result = f"""✅ 智能表格创建成功！

📋 表格名称: {sheet_name}
🔗 链接: {current_url}
📸 截图: {screenshot_path}
"""
                if columns:
                    result += f"📊 列: {', '.join(columns)}\n"

                return result

        except Exception as e:
            return f"错误: 创建表格失败 - {str(e)}"

    def invoke(self, inputs: dict, **kwargs) -> str:
        """同步调用"""
        return asyncio.run(self.ainvoke(inputs, **kwargs))

    def get_tool_info(self) -> ToolInfo:
        """获取工具信息"""
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "sheet_name": {
                        "type": "string",
                        "description": "表格名称"
                    },
                    "columns": {
                        "type": "string",
                        "description": "列名列表（JSON 数组或逗号分隔）"
                    }
                },
                required=["sheet_name"]
            )
        )


class TencentDocsImportExcelTool(Tool):
    """腾讯文档：导入 Excel 文件

    直接上传 Excel 文件到腾讯文档，比手动填写更快更可靠。
    """

    def __init__(
        self,
        mode_manager: Optional[AgentModeManager] = None,
        headless: bool = False
    ):
        super().__init__()
        self.mode_manager = mode_manager
        self.headless = headless

        self.name = "tencent_docs_import_excel"
        self.description = """将本地 Excel 文件导入到腾讯文档。

使用说明:
- 自动上传 Excel 文件到腾讯文档
- 返回在线表格的链接
- 比手动填写更快更可靠

参数:
- file_path: Excel 文件的绝对路径（必需）

示例:
- file_path: "/home/user/Documents/发票汇总.xlsx"
"""
        self.params = [
            Param(
                name="file_path",
                description="Excel 文件的绝对路径",
                param_type="string",
                required=True
            ),
        ]

    async def ainvoke(self, inputs: dict, **kwargs) -> str:
        """异步执行"""
        file_path = inputs.get("file_path", "")

        if not file_path:
            return "错误: 未指定文件路径"

        # 展开路径
        file_path = os.path.expanduser(file_path)

        if not os.path.exists(file_path):
            return f"错误: 文件不存在 - {file_path}"

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return "错误: playwright 未安装"

        if not os.path.exists(DEFAULT_COOKIES_PATH):
            return "错误: 未找到登录状态"

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=self.headless)
                context = await browser.new_context(
                    storage_state=DEFAULT_COOKIES_PATH,
                    viewport={'width': 1600, 'height': 900}
                )
                page = await context.new_page()
                page.set_default_timeout(60000)

                # 1. 打开腾讯文档
                print("[腾讯文档] 打开 docs.qq.com...")
                await page.goto(
                    'https://docs.qq.com',
                    wait_until='domcontentloaded'
                )
                await page.wait_for_timeout(3000)

                # 2. 点击 Upload 按钮（中英文都尝试）
                print("[腾讯文档] 点击 Upload...")
                upload_btn = page.locator('text=Upload').first
                if not await upload_btn.is_visible(timeout=3000):
                    upload_btn = page.locator('text=上传').first
                await upload_btn.click()
                await page.wait_for_timeout(2000)

                # 3. 上传文件
                print(f"[腾讯文档] 上传文件: {file_path}")
                file_input = page.locator('input[type="file"]').first
                await file_input.set_input_files(file_path)

                # 4. 等待上传完成（检测进度条消失或成功提示）
                print("[腾讯文档] 等待上传完成...")
                # 先等待基本时间
                await page.wait_for_timeout(5000)

                # 尝试等待上传完成的标志（进度100%或View按钮出现）
                for i in range(10):  # 最多等待20秒
                    # 检查 View 按钮是否出现
                    view_visible = await page.locator(
                        'text=View'
                    ).first.is_visible(timeout=1000)
                    view_cn_visible = await page.locator(
                        'text=查看'
                    ).first.is_visible(timeout=500)
                    if view_visible or view_cn_visible:
                        print(f"[腾讯文档] 上传完成！(第{i+1}次检查)")
                        break
                    print(f"[腾讯文档] 等待中... ({i+1}/10)")
                    await page.wait_for_timeout(2000)

                # 5. 获取上传文档的链接
                print("[腾讯文档] 获取文档链接...")
                sheet_url = None
                file_name_base = os.path.splitext(
                    os.path.basename(file_path)
                )[0]

                # 辅助函数：点击文档并获取链接
                async def click_doc_and_get_url(doc_locator):
                    nonlocal sheet_url
                    try:
                        # 尝试捕获新页面
                        async with context.expect_page(timeout=8000) as np:
                            await doc_locator.click()
                        new_page = await np.value
                        await new_page.wait_for_timeout(2000)
                        sheet_url = new_page.url.split('?')[0]
                        print(f"[腾讯文档] 从新页面获取链接: {sheet_url}")
                        # 打开文档后停留3秒
                        print("[腾讯文档] 文档已打开，停留3秒...")
                        await new_page.wait_for_timeout(3000)
                        return True
                    except Exception:
                        # 检查当前页面URL是否变化
                        await page.wait_for_timeout(2000)
                        current_url = page.url
                        if '/sheet/' in current_url or '/document/' in current_url:
                            sheet_url = current_url.split('?')[0]
                            print(f"[腾讯文档] 从当前页面获取链接: {sheet_url}")
                            # 打开文档后停留3秒
                            print("[腾讯文档] 文档已打开，停留3秒...")
                            await page.wait_for_timeout(3000)
                            return True
                    return False

                # 辅助函数：使用搜索框搜索文件
                async def search_and_open_doc(search_term):
                    nonlocal sheet_url
                    # 查找搜索框
                    search_input = page.locator(
                        'input[placeholder*="Search"]'
                    ).first
                    if not await search_input.is_visible(timeout=3000):
                        search_input = page.locator(
                            'input[placeholder*="搜索"]'
                        ).first
                    if not await search_input.is_visible(timeout=2000):
                        print("[腾讯文档] 未找到搜索框")
                        return False

                    # 输入搜索词
                    print(f"[腾讯文档] 在搜索框输入: {search_term}")
                    await search_input.click()
                    await search_input.fill(search_term)
                    await page.keyboard.press('Enter')
                    await page.wait_for_timeout(3000)

                    # 点击搜索结果中的文档
                    doc_link = page.locator(f'text="{search_term}"').first
                    if await doc_link.is_visible(timeout=5000):
                        print(f"[腾讯文档] 找到搜索结果，点击打开...")
                        return await click_doc_and_get_url(doc_link)
                    return False

                # 先跳转到主页使用搜索功能
                print("[腾讯文档] 跳转到主页搜索文档...")
                await page.goto(
                    'https://docs.qq.com/desktop',
                    wait_until='domcontentloaded'
                )
                await page.wait_for_timeout(3000)

                # 使用搜索框搜索刚上传的文件
                await search_and_open_doc(file_name_base)

                # 最后兜底
                if not sheet_url or sheet_url == 'https://docs.qq.com':
                    sheet_url = "上传成功但未能获取链接，请手动在腾讯文档中查看"

                await browser.close()

                file_name = os.path.basename(file_path)
                return f"""✅ Excel 文件已导入腾讯文档！

📄 文件名: {file_name}
🔗 链接: {sheet_url}
"""

        except Exception as e:
            import traceback
            traceback.print_exc()
            return f"错误: 导入文件失败 - {str(e)}"

    def invoke(self, inputs: dict, **kwargs) -> str:
        return asyncio.run(self.ainvoke(inputs, **kwargs))

    def get_tool_info(self) -> ToolInfo:
        return ToolInfo(
            type="function",
            name=self.name,
            description=self.description,
            parameters=Parameters(
                type="object",
                properties={
                    "file_path": {
                        "type": "string",
                        "description": "Excel 文件的绝对路径"
                    }
                },
                required=["file_path"]
            )
        )


def create_tencent_docs_tools(
    mode_manager: Optional[AgentModeManager] = None,
    headless: bool = False
) -> List[Tool]:
    """创建腾讯文档工具列表"""
    return [
        TencentDocsCreateSheetTool(mode_manager, headless),
        TencentDocsImportExcelTool(mode_manager, headless),
    ]
