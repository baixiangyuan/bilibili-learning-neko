"""B 站 AI 学习机器人 —— 模块化入口 (PluginRouter)。

把入口按职责拆分到不同 router：
- ``LearningRouter``  学习生命周期：启动 / 停止 / 状态 / Web 面板 / 兴趣管理
- ``ContentRouter``   内容交互：分析视频 / 生成网页 / 评论 / 私信
- ``KnowledgeRouter`` 知识库：查询已沉淀的知识

每个 router 在插件 ``__init__`` 中通过 ``include_router`` 挂载，
入口 ID 在插件命名空间下自动可见。
"""

from __future__ import annotations

from .learning import LearningRouter
from .content import ContentRouter
from .knowledge import KnowledgeRouter

__all__ = [
    "LearningRouter",
    "ContentRouter",
    "KnowledgeRouter",
]
