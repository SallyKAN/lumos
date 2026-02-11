"""
双模型路由器

提供确定性的模型路由功能，仅用于子 Agent 模型选择。
主 Agent 始终使用主模型，只有特定类型的子 Agent 使用小模型。
"""

from enum import Enum
from typing import Dict, Any, Optional


class ModelTier(Enum):
    """模型层级"""
    MAIN = "main"    # 主模型
    SMALL = "small"  # 子Agent模型（默认与主模型相同）


class ModelRouter:
    """确定性模型路由器

    用于子 Agent 模型选择。
    默认情况下，子 Agent 与主 Agent 使用相同的模型，保持一致性。
    可通过配置 small_model 让子 Agent 使用不同的模型。
    """

    # 必须使用主模型的子 Agent 类型
    MAIN_MODEL_AGENTS = set()

    def __init__(
        self,
        main_config: Dict[str, Any],
        small_config: Optional[Dict[str, Any]] = None,
        routing_enabled: bool = True
    ):
        """初始化路由器

        Args:
            main_config: 主模型配置
            small_config: 小模型配置（可选，不配置则全部使用主模型）
            routing_enabled: 是否启用路由（False 则全部使用主模型）
        """
        self.main_config = main_config
        self.small_config = small_config or main_config
        self.routing_enabled = routing_enabled

    def get_model_for_agent(self, agent_type: str) -> Dict[str, Any]:
        """根据 Agent 类型返回模型配置

        Args:
            agent_type: 子 Agent 类型

        Returns:
            模型配置字典
        """
        if not self.routing_enabled:
            return self.main_config

        # 只有在 MAIN_MODEL_AGENTS 中的才用主模型，其他都用小模型（高并发）
        if agent_type in self.MAIN_MODEL_AGENTS:
            return self.main_config
        return self.small_config

    def get_main_model(self) -> Dict[str, Any]:
        """主 Agent 始终使用主模型"""
        return self.main_config

    def get_model_tier(self, agent_type: str) -> ModelTier:
        """获取 Agent 对应的模型层级"""
        if not self.routing_enabled:
            return ModelTier.MAIN
        # 只有在 MAIN_MODEL_AGENTS 中的才用主模型，其他都用小模型
        if agent_type in self.MAIN_MODEL_AGENTS:
            return ModelTier.MAIN
        return ModelTier.SMALL


def create_model_router(config: Dict[str, Any]) -> ModelRouter:
    """从配置创建 ModelRouter

    Args:
        config: 完整配置字典，包含主模型和可选的小模型配置

    Returns:
        ModelRouter 实例
    """
    # 主模型配置
    main_config = {
        "provider": config.get("provider", "zhipu"),
        "model": config.get("model", "glm-4.7"),
        "api_base_url": config.get("api_base_url", ""),
        "api_key": config.get("api_key", ""),
    }

    # 小模型配置（可选）
    # 默认使用主模型，确保子 Agent 与主 Agent 使用相同的模型
    small_model = config.get("small_model")
    if small_model:
        small_config = {
            "provider": small_model.get("provider", main_config["provider"]),
            "model": small_model.get("model", main_config["model"]),
            "api_base_url": small_model.get("api_base_url", main_config["api_base_url"]),
            "api_key": small_model.get("api_key", main_config["api_key"]),
        }
    else:
        # 未配置 small_model 时，使用主模型（保持一致性）
        small_config = main_config.copy()

    # 路由开关
    routing = config.get("routing", {})
    routing_enabled = routing.get("enabled", True) if routing else True

    return ModelRouter(main_config, small_config, routing_enabled)
