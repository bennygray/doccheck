# admin-llm-config Design

## 5 产品级决策(propose 期)

| Q | 决策 | 说明 |
|---|---|---|
| Q1 | **B:dashscope + openai + custom** | 白名单 3 种;custom = OpenAI 兼容端点(填 base_url) |
| Q2 | **B:脱敏保留末 4 位** | `sk-****abc1`,便于确认是哪把 key;短于 8 位全脱敏 |
| Q3 | **B:提供测试连接按钮** | 发一个 `ping` + max_tokens=1,最省 token |
| Q4 | **B:三层优先级** | DB > env > 代码默认;保持旧部署兼容 |
| Q5 | **B:指纹哈希 cache + PUT 失效** | 配置指纹作 key,PUT 触发清空;兼顾性能和一致性 |

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend: AdminLLMPage                                     │
│   ├─ GET /api/admin/llm  ← 回显脱敏配置                     │
│   ├─ PUT /api/admin/llm  ← 写 + 失效 cache + 审计           │
│   └─ POST /api/admin/llm/test  ← 验证 provider/key 可用     │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  Backend: routes/admin.py (3 new endpoints)                 │
│                              ↓                              │
│  Service: llm_reader.read / write  +  tester.test_connection│
│                              ↓                              │
│  Model: SystemConfig.config.llm (JSON 子段)                 │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  factory.get_llm_provider() 每次调用:                       │
│    1. 读 DB 最新配置                                        │
│    2. 计算指纹 = hash(provider, api_key, model, base, to)  │
│    3. dict 命中 → 返旧 Provider                            │
│    4. 未命中 → 新建 Provider 存入 dict + 返                 │
│                                                             │
│  PUT 触发 invalidate_provider_cache() 清空 dict              │
└─────────────────────────────────────────────────────────────┘
```

## 3 层回退优先级(Q4)

```python
def read_llm_config(db) -> LLMConfig:
    # 1. DB 优先
    sc = db.get(SystemConfig, 1)
    if sc and isinstance(sc.config, dict) and sc.config.get("llm"):
        llm = sc.config["llm"]
        return LLMConfig(
            provider = llm.get("provider") or settings.llm_provider,
            api_key = llm.get("api_key") or settings.llm_api_key,
            ...
        )

    # 2. env 回退
    return LLMConfig(
        provider=settings.llm_provider,
        api_key=settings.llm_api_key,
        ...
    )
```

## Cache 失效策略(Q5)

- **Key = tuple(provider, api_key, model, base_url, timeout_s)** 作指纹
- `_providers: dict[tuple, LLMProvider]` 全局 dict
- **读时**:同指纹命中直接返,否则新建并存
- **写时**(PUT):`_providers.clear()` 直接清空(简单,且 admin 改配置的频率极低)
- `_providers` 容量上限 3,防病态输入把 dict 撑爆(超时则 FIFO 淘汰)

## 脱敏实现(Q2)

```python
def mask_api_key(raw: str | None) -> str:
    if not raw or len(raw) < 8:
        return "sk-****"  # 固定占位,不暴露长度
    return f"{raw[:3]}****{raw[-4:]}"  # eg. "sk-****abc1"
```

## 测试连接实现(Q3)

```python
async def test_connection(cfg: LLMConfig) -> tuple[bool, int, str | None]:
    t0 = time.time()
    try:
        provider = OpenAICompatProvider(
            name=cfg.provider,
            api_key=cfg.api_key,
            model=cfg.model,
            base_url=cfg.base_url or PROVIDER_DEFAULT_BASE_URL[cfg.provider],
            timeout_s=min(cfg.timeout_s, 10),  # 测试超时最多 10s,不卡界面
        )
        await provider.chat([{"role": "user", "content": "ping"}], max_tokens=1)
        return (True, int((time.time() - t0) * 1000), None)
    except Exception as e:
        return (False, int((time.time() - t0) * 1000), str(e)[:200])
```

## API 契约

### GET /api/admin/llm

Response (200):
```json
{
  "provider": "dashscope",
  "api_key_masked": "sk-****abc1",
  "model": "qwen-plus",
  "base_url": null,
  "timeout_s": 30,
  "source": "db"   // "db" / "env" / "default",告诉 UI 配置从哪来
}
```

### PUT /api/admin/llm

Request:
```json
{
  "provider": "openai",
  "api_key": "sk-new...",   // optional;空时保持旧值不变
  "model": "gpt-4o-mini",
  "base_url": null,
  "timeout_s": 30
}
```

Response (200): 同 GET(返最新脱敏值)

### POST /api/admin/llm/test

Request (可空,默认用 DB 当前配置):
```json
{
  "provider": "dashscope",
  "api_key": "sk-xxx",
  "model": "qwen-plus",
  "base_url": null,
  "timeout_s": 10
}
```

Response (200):
```json
{
  "ok": true,
  "latency_ms": 324,
  "error": null
}
```

失败态:
```json
{
  "ok": false,
  "latency_ms": 3012,
  "error": "timeout after 3s"
}
```

## 前端页面结构

```
Breadcrumb: 首页 / 管理 / LLM 配置
标题:LLM 配置
副标题:配置检测所用的大模型 provider、API Key 和模型参数

┌─ Card:基本配置 ───────────────────────────────────────────┐
│ Provider [Select: dashscope / openai / custom]            │
│ API Key  [Input.Password,占位 = 当前脱敏值,空白输入=保持]│
│ Model    [Input: qwen-plus]                               │
│ Base URL [Input,仅 custom provider 时启用]               │
│ Timeout  [InputNumber: 30]                                │
└──────────────────────────────────────────────────────────┘

┌─ Card:测试连接 ───────────────────────────────────────────┐
│ [测试连接]  ← 用当前表单值发 ping                         │
│ (结果 Alert)                                              │
└──────────────────────────────────────────────────────────┘

┌─ Card:底部操作条 ─────────────────────────────────────────┐
│                              [恢复默认]  [保存]           │
└──────────────────────────────────────────────────────────┘
```

## apply 现场决策(预计)

*(这一节 apply 阶段会追加实际踩到的坑和就地决策)*

## 安全 / 部署

- **api_key 明文存 DB**:SystemConfig 是 JSONB 明文。运维需保证 DB 访问受控(只有业务 admin + 运维可读)
- **审计日志**:PUT 动作写 audit_log,包含 actor_id / before(脱敏)/after(脱敏)/ ip / ua,合规需要时可追溯
- **并发**:两个 admin 同时 PUT 是"最后写赢";不做乐观锁,admin 少量场景可接受
- **部署提示**:归档时补 `backend/README.md`"LLM 配置优先级从 env 改为 DB"一段
