## Context

N3(LLM 大文档精度退化)根因未知。`harden-async-infra` 已为 role_classifier / 5 个 agent LLM 调用点加了精细化 `kind` 日志 + 60s 全局 timeout cap,覆盖**路径 1**(provider 层 error)。但 `role_classifier.py` 对 LLM 返回的处理有 **3 条分支**:

```
llm.complete(prompt)
  │
  ├── 1. result.error != None              ──▶  已有 warning "kind=X"   (可见)
  ├── 2. result.error==None, parse==None   ──▶  已有 warning "invalid JSON"  (可见但无 raw head)
  └── 3. result.error==None, parse ok,
         但 item["confidence"]=="low"      ──▶  (无日志)             (隐身)
```

路径 2 的日志没带 raw 文本,无法判断截断模式;路径 3 完全隐身 —— LLM 自己返 "low"(snippet 差 / 推理退化 / prompt 质量问题)在 DB 里看到的现象和路径 1(fallback 强制 low)**完全一样**(所有 doc 的 `role_confidence='low'`)。

在不补这两条路径的可观测性之前,任何面向 N3 的 hardening propose 都是盲选。

## Goals / Non-Goals

**Goals:**
1. 让 role_classifier 的 3 条决策路径**都有可观测信号**,真 LLM 采样一次即可归因 N3 到 H1/H2/H3
2. 提供可复现的双采样脚本(B 方案:A+B × 2 轮),横向看 A vs B 差异 + 纵向看稳定性
3. 采样结果以凭证形式 commit 进 e2e/artifacts/,后续 hardening propose 可直接引用
4. 零产品行为变化,零 schema 变更,零 breaking

**Non-Goals:**
- 不做 snippet 策略重写 / max_tokens 调参 / timeout 变更(留给 N3 hardening 第二个 propose)
- 不做统一 LLM 调用点观测性框架(只改 role_classifier 一个站点;其他 5 个 LLM 调用点的 kind 日志足够本次诊断)
- 不抽通用 observability helper(3 条 log 站点手写 3-5 行,复用/抽象收益为负)
- 不改 provider 层或 LLMResult 契约(日志是调用方行为,不是 provider 契约)
- 不跑 LLM mock 也能验证的 L2 端到端(L1 caplog 断言够,真采样凭证就是 end-to-end)

## Decisions

### D1 日志 level = `logger.info`,不是 `warning`

**选定**:3 条新增日志用 `logger.info`。

**理由**:
- 这 3 条是诊断用信息(input shape / output mix / raw text head),不是异常
- prod 默认 warning 级,info 不输出,零噪声;诊断时主动调低到 info
- 和既有 `warning`(error fallback / invalid JSON)形成清晰 level 分层:warning=需关注,info=诊断

**备选**(已否):全 warning → 误报干扰 prod 运维;

### D2 站点只改 role_classifier.py,不改其他 5 个 LLM 调用点

**选定**:本 change 只动 `backend/app/services/parser/llm/role_classifier.py`。

**理由**:
- N3 目前只观察到 role_classifier 的精度退化;其他 5 调用点无对应病例
- 其他 5 调用点都有 kind 日志,若未来 N3 探到更广根因再补;单点先做证据链,别扩 scope
- agent LLM 调用点的失败语义是 skipped(engine 有 AgentTask.summary 凭证),不需要 role_classifier 这种"成功但质量差"的信号

### D3 input shape 字段选择

**选定**:`files=N snippet_empty=M total_prompt_chars=K file_name_has_mojibake=bool`。

**字段理由**:
| 字段 | 用途 |
|---|---|
| `files=N` | basic:prompt doc 总数 |
| `snippet_empty=M` | H2 子假设:无正文文档比例 |
| `total_prompt_chars=K` | H3 鉴别:判断是否接近 token 上限 |
| `file_name_has_mojibake=bool` | H2 新子假设:文件名乱码是否影响 LLM 推理 |

**不选**(备选已否):
- `total_tokens=K`:需加 tokenizer 依赖,info 级不值得
- 完整文件名列表:日志体积大,凭证脚本会转存 JSON 更合适
- snippet 文本采样:隐私/合规;文件名在本 change 已够用

### D4 mojibake 粗判 heuristic

**选定**:纯启发式,不新加依赖:
```python
def _looks_mojibake(name: str) -> bool:
    # 典型 cp850-decoded-GBK 特征:连续 2+ 个 0x80-0xFF 范围且含常见 mojibake 片段
    if not name:
        return False
    # 常见 GBK→cp850 mojibake 片段(µ Φ Θ ╕ 等组合)
    MARKERS = ("µ▒", "µ£", "µ¥", "Φï", "Φ¿", "Θö", "Θ£", "σ┐", "σ║", "Σ╗", "Σ╕")
    return any(m in name for m in MARKERS)
```

**理由**:
- 不准就不准 —— 日志是诊断用,heuristic 足够分辨"大比例乱码" vs "纯中文"两个集群
- 零依赖,10 行内可测
- 若未来证明需要更精准,再替换

**备选**(已否):引入 `chardet`/`charamel`:增加运行时依赖,info 日志不值得

### D5 raw_text head 截 200 字符

**选定**:扩展现有 `"returned invalid JSON; fallback to keywords"` warning,追加 `raw_text_head=<200 字符>`。

**理由**:
- 200 字符可容 JSON 开头 `{"roles":[{"document_id":...` + 部分内容,足以判断是否明显截断
- 截断到 200 防止日志爆炸 + 敏感内容泄露控制
- 中文 JSON 1 汉字 3 字节,200 字符大约 70 汉字,够看开头两三个 item

**备选**(已否):log 完整 raw text → 体积不可控 / 日志系统过滤敏感内容的成本

### D6 output confidence mix 字段

**选定**:`llm_confidence_high=X low=Y missing=Z`(总数可从 input shape 的 files=N 对齐)。

**理由**:
- `missing` = LLM 漏返的 doc 数;这批要走关键词兜底(现有逻辑),区分"LLM 返 low" vs "LLM 没返"
- 3 个 count 够覆盖所有 LLM 成功路径的可观察状态
- 诊断时 `high=0 low=8 missing=0` 可直接读出 H2a(LLM 自己判 low),`high=3 low=0 missing=5` 可读出 H3 候选(LLM 漏返 = 疑似截断)

### D7 采样脚本设计

**选定**:`e2e/artifacts/supplier-ab-n3-observability/run_sampling.py`:
1. 清库 → 新建 project(或复用已有 project 226 → 清 bidders)
2. 上传 A+B zip(复用 `run_detection.py` 的 login/upload 函数)
3. 等解析完成(poll `GET /bidders/:id/documents`,直到 parse_status 稳定)
4. 从 backend log 里 grep `role_classifier` 相关日志(按 bidder_id 分组);或直接调 API 拿 bid_documents 的 role/confidence + bidder identity_info
5. 输出 round{1,2}.json,两轮跑完写 README.md 的 4 行对比表

**理由**:
- 复用 run_detection.py 骨架,减少新代码
- 输出结构化 JSON,便于后续 hardening propose 直接引用
- 日志抓取降级:若 server 日志流不易 grep,退回调 API 观察 DB 状态(role_confidence 分布)—— 日志是诊断主线,API 是 fallback

**运行前置**:Server 端调低 `role_classifier` logger 级到 INFO(脚本启动时 POST admin 配置 or 用户手动)。采样脚本 README 写清楚前置步骤。

### D8 L1 测试策略

**选定**:`backend/tests/unit/test_role_classifier_observability.py`,纯 caplog + mock LLM,3-5 case:
1. input shape 日志字段完整(files/snippet_empty/total_prompt_chars/file_name_has_mojibake)
2. LLM 成功 + 混合 confidence → output mix 日志 `high=X low=Y missing=Z` 计数正确
3. LLM 失败 → 只有 kind 日志,**不**记 output mix
4. JSON 解析失败 → warning 带 `raw_text_head=` 字段,且截到 200 字符
5. mojibake helper 正反 case(纯中文 / 纯 ASCII / cp850-decoded-GBK 典型片段)

**不加 L2**:manual 采样脚本作为 end-to-end 凭证;observability 单改日志,L2 收益<成本。

## Risks / Trade-offs

- **[R1]** `file_name_has_mojibake` heuristic 误判率不可证 → **Mitigation**:heuristic 只作为诊断信号,不触发任何行为;误判不造成业务损失;命中少就查误判,命中多就查真乱码 —— 两种情况都有价值
- **[R2]** info 日志在 prod 默认不输出,采样时必须手动调 level → **Mitigation**:采样脚本 README 明确"调低 logger 级"前置;且凭证优先走 API 状态(bid_documents 的 role/confidence 分布 = LLM 成功路径的 output mix 的 DB 投影,可部分替代日志)
- **[R3]** raw_text_head 200 字符可能恰好切断 Unicode 字符 → **Mitigation**:Python 字符串切片按 code point,不是字节;不会切断 Unicode 字符(`s[:200]` 安全)
- **[R4]** 采样跑 2 轮 ~¥0.2 成本,且 dashscope 可能限流 → **Mitigation**:成本已与用户对齐(B 选项);限流时 2 轮间插 30s 间隔 + 脚本支持断点续跑

## Migration Plan

零迁移:
- 无 DB schema 变更
- 无 API 契约变更
- 日志为新增,prod 默认级别不输出,既有部署零改动
- Rollback:回滚 commit,无残留状态

## Open Questions

(无。产品决策 Q1=A 已对齐;D1-D8 均自决;采样前置"手动调 INFO 级"写进脚本 README。)
