"""全局记忆子模块：候选抽取（extractor）+ 存取（store）。

这里不做包级 import，保证单独 import extractor 时不会顺带拉起数据库层。
用法：
    from backend.services.harness.memory.store import MemoryStore
    from backend.services.harness.memory.extractor import extract_memories
"""
