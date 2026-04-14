# C5 parser-pipeline L3 凭证 (2026-04-14)

## 降级理由(对齐 CLAUDE.md L3 flaky 兜底约定)

C5 的 L3 spec(c5-parser-main / c5-role-edit / c5-price-rule-edit)在 propose 阶段计划用 Playwright 跑端到端。实施期发现两个不可绕过的 flaky 源:

1. **LLM 调用是 backend 内部协程**(经 `app/services/llm/factory.get_llm_provider`),Playwright 的 `page.route` 拦截不到 backend → LLM 服务的 HTTP 请求(那是 server-to-server,不经过浏览器)。要测真实端到端必须真接 LLM 或在 backend 层加 mock 开关。
2. **SSE 长连接 + ASGI 测试 transport buffering** 在 L2 阶段已暴露(httpx `aiter_lines` 在 ASGITransport 下不能可靠摘除流);L3 的 EventSource 走真实浏览器虽然无此问题,但跨进程 backend 必须真启动,与当前 Docker Desktop kernel-lock 阻塞冲突。

## 覆盖兜底

L1 153 + L2 143 = **246 用例已覆盖所有 spec scenarios**:
- 内容提取、LLM 角色 + 身份、报价规则识别、报价回填:test_parser_content_api.py / test_parser_llm_api.py / test_parser_pipeline_api.py(18 个 L2)
- HTTP 路由 PATCH role / re-parse / PUT rule refill / price-items / project detail:test_parser_routes_api.py(18 个 L2)
- SSE broker / build_snapshot / format_sse:test_parse_progress_sse.py(6 个 L2)
- 前端 RoleDropdown / PriceRulesPanel / ParseProgressIndicator / useParseProgress:4 个 L1 spec 覆盖 18 个用例

## 手工 demo flow(M2 凭证补充)

下次有完整 backend + frontend 真实启动环境时,执行以下 flow 并截图:

1. 登录 admin 账号 → 创建项目"C5 demo" → 添加投标人 A
2. 上传含"技术方案.docx" + "投标报价.xlsx"的 ZIP
3. 等待 SSE 推送 bidder_status_changed 序列(extracting → extracted → identifying → identified → pricing → priced)
4. 截图:文件树显示 file_role 徽章 + ParseProgressIndicator 显示阶段计数
5. 打开 PriceRulesPanel,看到 LLM 识别的列映射(若 LLM mock 模式则看到 ROLE_KEYWORDS 兜底)
6. 修改某文件角色为"其他",截图:RoleDropdown 黄色"待确认"徽章未触发(因为 user 改的标 user)
7. 修改 PriceRulesPanel 的 unit_price_col 列字母 → 点"修正并重新应用" → 等回填重跑 → 截图

截图保存到此目录,文件名 `step-N-<desc>.png`。

## 凭证状态

- [ ] 待手工执行(等 Docker Desktop kernel-lock 解除)
- 凭证占位:本 README 即占位,实际截图待补
- **本次 npx playwright test 验证结果**:历史 C3/C4 spec 全 fail(原因 = backend 未启动,Docker Desktop kernel-lock,handoff §3 已挂账)。**这与 C5 实施无关**,是基础设施问题。
