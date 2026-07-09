"""知识库相关入口：查询已沉淀的知识。"""

from __future__ import annotations

from typing import Any

from plugin.sdk.plugin import plugin_entry, Ok, Err, SdkError
from plugin.sdk.shared.core.router import PluginRouter


class KnowledgeRouter(PluginRouter):
    """已学习知识的检索。"""

    def __init__(self):
        super().__init__(name="knowledge")

    @plugin_entry(
        id="get_knowledge",
        name="查询知识库",
        description="查询已学习的知识库内容，可传入关键词过滤。",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "关键词（留空返回全部）"},
                "limit": {"type": "integer", "default": 10, "description": "返回条数上限"},
            },
        },
        kind="action",
    )
    async def get_knowledge(self, query: str = "", limit: int = 10, **_) -> Any:
        plugin = self.main_plugin
        kb: list[Any] = []
        if plugin.store.enabled:
            res = await plugin.store.get("knowledge_base", [])
            kb = res.value if hasattr(res, "value") else []
        kb = kb if isinstance(kb, list) else []

        if query:
            q = query.lower()
            kb = [k for k in kb if q in str(k).lower()]

        return Ok({
            "success": True,
            "message": f"找到 {len(kb)} 条知识",
            "data": kb[:limit],
            "store_enabled": plugin.store.enabled,
        })
