"""pytest 全局配置 - C1 infra-base

- 加载共享 fixtures(LLM mock 等)
- 配置 asyncio 自动模式(pyproject.toml 已配 asyncio_mode=auto,此处留空即可)
"""

pytest_plugins = [
    "tests.fixtures.llm_mock",
]
