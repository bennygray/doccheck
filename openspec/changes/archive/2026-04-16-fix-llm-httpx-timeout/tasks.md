## 1. 核心修复

- [x] 1.1 [impl] `openai_compat.py`：给 `httpx.AsyncClient()` 传入 `timeout=self._timeout_s`
- [x] 1.2 [impl] `openai_compat.py`：httpx.HTTPError 捕获的 error message 改为 `f"{type(exc).__name__}: {exc}"` 避免空字符串

## 2. 验证

- [x] 2.1 [L1] 现有 LLM mock 测试不受影响（全量 L1 通过）
- [x] 2.2 [manual] 验证通过：LLM 返回真实结论"综合研判认为，本项目串标风险较低..."，suggested=3.5，非降级模板 手动验证 L-9 judge 真实 LLM 调用成功返回结论（非降级模板）

## 3. 全量测试

- [x] 3.1 跑 [L1][L2] 全部测试，全绿 (1037 passed in 108.67s)
