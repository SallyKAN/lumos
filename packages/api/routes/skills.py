"""
Skills 管理 REST API 路由
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...skills import SkillManager, Skill, InstalledPlugin, MarketplaceInfo


router = APIRouter(prefix="/skills", tags=["skills"])

# 全局 SkillManager 实例
_skill_manager: Optional[SkillManager] = None


def get_skill_manager() -> SkillManager:
    """获取 SkillManager 单例"""
    global _skill_manager
    if _skill_manager is None:
        _skill_manager = SkillManager()
        _skill_manager.load_skills()
    return _skill_manager


# ============================================================================
# 请求/响应模型
# ============================================================================

class SkillItem(BaseModel):
    """Skill 项"""
    name: str
    description: str
    source: str  # local, project, marketplace
    version: str
    author: str
    tags: List[str]
    allowed_tools: List[str]


class SkillListResponse(BaseModel):
    """Skill 列表响应"""
    skills: List[SkillItem]
    total: int


class InstalledPluginItem(BaseModel):
    """已安装插件项"""
    plugin_name: str
    marketplace: str
    spec: str
    version: str
    installed_at: str
    git_commit: Optional[str] = None
    skills: List[str]


class InstalledPluginListResponse(BaseModel):
    """已安装插件列表响应"""
    plugins: List[InstalledPluginItem]
    total: int


class InstallPluginRequest(BaseModel):
    """安装插件请求"""
    spec: str  # 如 "example-skills@anthropics"
    force: bool = False


class UninstallPluginRequest(BaseModel):
    """卸载插件请求"""
    spec: str  # 如 "example-skills@anthropics"


class ImportLocalSkillRequest(BaseModel):
    """导入本地 skill 请求"""
    path: str
    force: bool = False


class PluginOperationResponse(BaseModel):
    """插件操作响应"""
    success: bool
    message: str
    plugin: Optional[InstalledPluginItem] = None


class ImportLocalSkillResponse(BaseModel):
    """导入本地 skill 响应"""
    success: bool
    message: str
    skill: Optional[SkillItem] = None


class MarketplaceItem(BaseModel):
    """Marketplace 项"""
    name: str
    url: str
    install_location: str
    last_updated: Optional[str] = None


class MarketplaceListResponse(BaseModel):
    """Marketplace 列表响应"""
    marketplaces: List[MarketplaceItem]
    total: int


class AddMarketplaceRequest(BaseModel):
    """添加 Marketplace 请求"""
    name: str
    url: str


class MarketplaceOperationResponse(BaseModel):
    """Marketplace 操作响应"""
    success: bool
    message: str
    marketplace: Optional[MarketplaceItem] = None


# ============================================================================
# 辅助函数
# ============================================================================

def skill_to_item(skill: Skill) -> SkillItem:
    """将 Skill 对象转换为 SkillItem"""
    return SkillItem(
        name=skill.name,
        description=skill.description,
        source=skill.source.value,
        version=skill.metadata.version,
        author=skill.metadata.author,
        tags=skill.metadata.tags,
        allowed_tools=list(skill.allowed_tools)
    )


def plugin_to_item(plugin: InstalledPlugin) -> InstalledPluginItem:
    """将 InstalledPlugin 对象转换为 InstalledPluginItem"""
    return InstalledPluginItem(
        plugin_name=plugin.plugin_name,
        marketplace=plugin.marketplace,
        spec=plugin.spec,
        version=plugin.version,
        installed_at=plugin.installed_at.isoformat(),
        git_commit=plugin.git_commit,
        skills=plugin.skills
    )


def marketplace_to_item(mp: MarketplaceInfo) -> MarketplaceItem:
    """将 MarketplaceInfo 对象转换为 MarketplaceItem"""
    return MarketplaceItem(
        name=mp.name,
        url=mp.url,
        install_location=str(mp.install_location),
        last_updated=mp.last_updated.isoformat() if mp.last_updated else None
    )


# ============================================================================
# 路由
# ============================================================================

@router.get("", response_model=SkillListResponse)
async def list_skills(reload: bool = False):
    """获取所有可用的 skills 列表

    Args:
        reload: 是否强制重新加载 skills
    """
    manager = get_skill_manager()
    if reload:
        manager.reload()

    skills = manager.list_skills()
    return SkillListResponse(
        skills=[skill_to_item(s) for s in skills],
        total=len(skills)
    )


@router.get("/installed", response_model=InstalledPluginListResponse)
async def list_installed_plugins():
    """获取已安装的插件列表"""
    manager = get_skill_manager()
    plugins = manager.list_installed_plugins()
    return InstalledPluginListResponse(
        plugins=[plugin_to_item(p) for p in plugins],
        total=len(plugins)
    )


@router.post("/install", response_model=PluginOperationResponse)
async def install_plugin(request: InstallPluginRequest):
    """安装插件

    Args:
        request: 安装请求，包含 spec 和 force 参数
    """
    manager = get_skill_manager()

    try:
        plugin = manager.install_plugin(request.spec, force=request.force)
        return PluginOperationResponse(
            success=True,
            message=f"插件 {request.spec} 安装成功",
            plugin=plugin_to_item(plugin)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/uninstall", response_model=PluginOperationResponse)
async def uninstall_plugin(request: UninstallPluginRequest):
    """卸载插件

    Args:
        request: 卸载请求，包含 spec 参数
    """
    manager = get_skill_manager()

    try:
        manager.uninstall_plugin(request.spec)
        return PluginOperationResponse(
            success=True,
            message=f"插件 {request.spec} 卸载成功"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/import_local", response_model=ImportLocalSkillResponse)
async def import_local_skill(request: ImportLocalSkillRequest):
    """导入本地 skill

    Args:
        request: 导入请求，包含 path 和 force 参数
    """
    manager = get_skill_manager()

    try:
        skill = manager.import_local_skill(request.path, force=request.force)
        return ImportLocalSkillResponse(
            success=True,
            message="导入成功",
            skill=skill_to_item(skill)
        )
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Marketplace 管理路由（必须在 /{skill_name} 之前定义）
# ============================================================================

@router.get("/marketplace/list", response_model=MarketplaceListResponse)
async def list_marketplaces():
    """获取所有已知的 marketplace 列表"""
    manager = get_skill_manager()
    marketplaces = manager.list_marketplaces()
    return MarketplaceListResponse(
        marketplaces=[marketplace_to_item(mp) for mp in marketplaces],
        total=len(marketplaces)
    )


@router.post("/marketplace/add", response_model=MarketplaceOperationResponse)
async def add_marketplace(request: AddMarketplaceRequest):
    """添加自定义 marketplace

    Args:
        request: 添加请求，包含 name 和 url 参数

    示例:
        添加 baoyu-skills marketplace:
        - name: "baoyu"
        - url: "https://github.com/JimLiu/baoyu-skills.git"

        然后可以使用 "baoyu-comic@baoyu" 格式安装其中的插件
    """
    manager = get_skill_manager()

    try:
        if not request.name or not request.name.strip():
            raise ValueError("marketplace 名称不能为空")
        if not request.url or not request.url.strip():
            raise ValueError("marketplace URL 不能为空")

        url = request.url.strip()
        if not url.endswith(".git"):
            url = url + ".git"

        marketplace = manager.add_marketplace(
            request.name.strip(),
            url
        )
        return MarketplaceOperationResponse(
            success=True,
            message=f"Marketplace '{request.name}' 添加成功",
            marketplace=marketplace_to_item(marketplace)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# 动态路由（必须放在最后）
# ============================================================================

@router.get("/{skill_name}")
async def get_skill(skill_name: str):
    """获取指定 skill 的详情

    Args:
        skill_name: Skill 名称
    """
    manager = get_skill_manager()
    skill = manager.get_skill(skill_name)

    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' 不存在")

    return {
        "name": skill.name,
        "description": skill.description,
        "source": skill.source.value,
        "version": skill.metadata.version,
        "author": skill.metadata.author,
        "tags": skill.metadata.tags,
        "allowed_tools": list(skill.allowed_tools),
        "content": skill.content,
        "file_path": str(skill.file_path)
    }
