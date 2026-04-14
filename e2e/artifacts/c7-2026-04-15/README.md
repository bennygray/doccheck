# C7 detect-agent-text-similarity L3 手工凭证占位

延续 C5 / C6 降级策略:Docker Desktop kernel-lock 未解除,`docker compose up` 真实部署不可用,L3 Playwright 跑不起来。kernel-lock 解除后按以下步骤手工补 3 张截图。

## 前置(kernel-lock 解除后)

```bash
# 1. 启服务 + 跑 L2 e2e 种子(或手工建 2 bidder、上传抄袭样本)
cd backend && uv sync && uvicorn app.main:app --reload &
cd frontend && npm run dev &

# 2. 登录 → 创建项目 → 上传 2 bidder(预埋抄袭样本)→ 等解析完成
# 3. 点"启动检测"
```

## 3 张截图(保存为 01/02/03.png)

- **01-start-detect.png**:项目详情页,点"启动检测"按钮前状态 + SSE 进度条开始显示
- **02-report-text-sim-row.png**:报告页 text_similarity 行:score ≥ 60,红色铁证徽章显示,summary 非"dummy"字样
- **03-evidence-drawer.png**(可选,若 C14 未做证据抽屉则跳过):展开段落对表,能看到 10 条 samples

## 通过判据

- score 非 dummy 随机分特征(dummy 是 round(random.uniform(0,100), 2),真实应落在 70~95 典型区间)
- evidence_json.algorithm == "tfidf_cosine_v1"(可通过 DevTools Network 抓 `/api/projects/{pid}/reports/{v}` JSON 验证)
- is_ironclad=true 时报告总分 ≥ 85(铁证强制)

kernel-lock 解除前,L1 (232) + L2 (178) 共 410 通过已覆盖所有 spec scenario,L3 凭证仅作 M3 demo 价值补齐。
