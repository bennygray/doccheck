## Context

### 现状(C10 归档后)

- **`price_consistency` Agent 骨架已就绪**(C6):已注册到 `AGENT_REGISTRY`,`agent_type="pair"`,preflight 使用既有 `bidder_has_priced(session, bidder_id)`(`_preflight_helpers.py` 已支持);run 目前走 `dummy_pair_run`。
- **`PriceItem` 数据层已就绪**(C5):表 `price_items`,字段 `bidder_id / price_parsing_rule_id / sheet_name / row_index / item_code / item_name / unit / quantity / unit_price / total_price`(均已就绪)。**注意**:`currency` 与 `tax_included` 字段在 `price_parsing_rules` 表(规则级),**不在 PriceItem 行级**(handoff.md 此前记录偏差,本 change 以代码事实为准)。
- **`price_parsing_rules` 表**:规则级 `currency` / `tax_included` 字段存在,但 **C11 明确不读取**(Q2 决策)。
- **其他 3 个 Agent 仍 dummy**:`error_consistency` / `style` / `image_reuse`,C11 不触。
- **`DocumentSheet` 表**(C9 建):xlsx cell 矩阵;C11 **明确不消费**(Q4 决策),结构信号归 C9 专管。

### 约束

- **C6 contract 锁定**:`name + agent_type + preflight` 三元组不变;`price_consistency.py` 文件保留,只改 `run()`。
- **C7/C8/C9/C10 子包零改动**:C11 不 import 任何 `*_sim_impl/` / `metadata_impl/` 模块。
- **`AgentRunResult` 契约不变**:`score: float, summary: str, evidence_json: dict = {}`;Agent 级 skip 用 `score=0.0` 哨兵(C9/C10 已验证对齐)。
- **零新增第三方依赖**:`unicodedata`(stdlib)NFKC 归一化 + `statistics`(stdlib)方差/变异系数 + `decimal` / `collections` 原生类型。
- **零 LLM 引入**:4 子检测纯程序化(字符串归一化 + 数值聚合 + 集合匹配 + 方差计算);`ctx.llm_provider` 不消费。
- **execution-plan §3 C11 原文兜底**:
  - 异常样本(非数值/缺失)→ 跳过不假阳
  - 归一化失败 → 标"口径不一致,无法比对"(Q2 决策下已简化为:不做口径归一化,直接比原始值)
- **score ∈ [0, 100]**:DB `Numeric(6, 2)`,C6 PairComparison 已定。
- **score 规则**:Agent 级 score = 参与子检测 `hit_strength`(0~1)按子权重加权归一化 × 100。

### 干系方

- **审查员**:报告页可见"尾数碰撞:3 家报价尾 3 位都是 '880' 且整数位长同为 6(金额约 百万级)"/"等比关系:B 家总价 = A 家 × 0.95(5 行对齐)"这类明证。
- **C12 实施者**:C11 验证的"共享 extractor + 4 子检测 + Agent 级 skip 哨兵"模式,C12 价格异常类似可复用;**垂直关系(单家 vs 群体)归 C12**,水平关系(bidder 之间)归 C11,语义分层清晰。
- **C14 综合研判**:含税/币种混用导致同价不同数值的场景,由 C14 LLM 综合研判识别(C11 故意不做)。
- **C17 前端**:C11 evidence_json 结构复用 "participating_subdims / hits" 风格,前端按 C6 既有渲染。

## Goals / Non-Goals

### Goals

1. **4 子检测真实算法落地**:tail / amount_pattern / item_list / series_relation 各自独立执行并汇总写 PairComparison。
2. **`price_impl/` 共享子包 11 文件**:config / models / normalizer / extractor / 4 个 detector / scorer / `__init__.py`。
3. **5 Scenario 全绿**(execution-plan §3 C11 原 4 Scenario + 本 change 新增 series 1 Scenario)。
4. **子检测 flag 单独开关**:env 级配置不重启生效(L1 monkeypatch 可验证)。
5. **Agent 级 skip 与子检测级 skip 语义对齐 C9/C10**:Agent 级用 `score=0.0` 哨兵 + `evidence.participating_subdims=[]`;子检测级用 `evidence.subdims.<name>.reason` 标注。
6. **第一性原理审纳入子检测**:series_relation 子检测覆盖"等差/等比/精确比例"真信号(execution-plan §3 C11 原文未列,本 change scope 扩展)。

### Non-Goals

- **币种归一化**:Q2 决策,C11 完全不读 `price_parsing_rule.currency`;真多币种场景留 C14 LLM 综合研判或 C17 管理后台。
- **含税/不含税换算**:Q2 决策,C11 完全不读 `price_parsing_rule.tax_included`;不做 `× 1.09` 类固定税率换算。
- **LLM 语义对齐 item_name**:"钢筋Φ12" vs "Φ12 螺纹钢"变体不做语义合并;留 C14。
- **Levenshtein / 模糊匹配 item_name**:Q3 决策,两阶段对齐只做位置对齐 + NFKC 精确归一,不引入部分匹配。
- **DocumentSheet 消费**:Q4 决策,C11 不 touch;结构维度归 C9 专管。
- **异常低价 / 垂直关系检测**:单家相对均值/标底的异常,归 C12 `price_anomaly`。
- **前端合并 tab**:C17 做;本 change 保 judge 层能够 `SELECT dimension = 'price_consistency'` 捞行即可。
- **PriceItem 数据修复**:C5 归一化失败写 NULL 是既定契约,C11 遇 NULL 行级 skip 不假阳,不反向修 C5。

## Decisions

### D1 — `price_impl/` 子包结构

**决策**:`backend/app/services/detect/agents/price_impl/`,11 文件:

```
price_impl/
├── __init__.py                      # 共享 helper(write_pair_comparison_row 照搬 C10)
├── config.py                        # env 读取 + 4 flag + 阈值默认值
├── models.py                        # PriceRow / SubDimResult / evidence schema (TypedDict)
├── normalizer.py                    # item_name NFKC + Decimal 拆解(尾 N 位 / 整数位长)
├── extractor.py                     # extract_bidder_prices(session, bidder_id) -> {sheet_name: [PriceRow]}
├── tail_detector.py                 # 子 1:尾数组合 key 跨投标人碰撞
├── amount_pattern_detector.py       # 子 2:(item_name_norm, unit_price) 对精确匹配率
├── item_list_detector.py            # 子 3:两阶段对齐 + 整体相似度
├── series_relation_detector.py      # 子 4(新增):等差/等比/比例关系
└── scorer.py                        # 4 子检测合成 Agent 级 score
```

**理由**:
- 与 C10 `metadata_impl/`(9 文件) 风格一致,规模相当(C11 多 1 个子检测 = 多 1 文件 + 多 1 scorer 分支)。
- 4 detector 分文件:4 子算法签名完全不同(tail 哈希桶 / amount_pattern 集合匹配 / item_list 两阶段对齐 / series 方差计算),抽 `BaseDetector` 反耦合。
- `normalizer.py` 独立:item_name NFKC + Decimal 拆解多处调用,避免内联重复。
- `models.py` 用 `TypedDict`(不引 pydantic):仅内部类型契约,不做序列化。

**替代方案**:
- 4 detector 合并到 1 个 `detectors.py` → 单文件 500+ 行易糊;拒。
- 抽 `BaseDetector` 抽象类 → 过度抽象(4 detector 签名/返回不一致);拒(对齐 C10 D4 同理由)。

### D2 — Normalizer(item_name NFKC + Decimal 拆解)

**决策**:`normalizer.py` 提供 3 个纯函数:

```python
# normalizer.py
def normalize_item_name(name: str | None) -> str | None:
    """NFKC + casefold + strip;空串/None → None(当缺失)"""
    if name is None:
        return None
    s = unicodedata.normalize("NFKC", name).casefold().strip()
    return s or None


def split_price_tail(
    total_price: Decimal | None, tail_n: int
) -> tuple[str, int] | None:
    """
    返回 (尾 N 位字符串, 整数部分位长);异常样本 → None。
    Decimal -> int: truncate 取整(1000.99 → 1000);NaN/None/<0 → None。
    """
    if total_price is None:
        return None
    try:
        int_val = int(total_price)       # Decimal 的 int() 是 truncate
    except (InvalidOperation, ValueError, TypeError):
        return None
    if int_val < 0:
        return None
    int_str = str(int_val)
    tail = int_str[-tail_n:] if len(int_str) >= tail_n else int_str.zfill(tail_n)
    return (tail, len(int_str))


def decimal_to_float_safe(d: Decimal | None) -> float | None:
    """series 子检测需要 float(方差/比值);异常样本 → None。"""
    if d is None:
        return None
    try:
        return float(d)
    except (InvalidOperation, ValueError, TypeError):
        return None
```

**理由**:
- `int()` truncate 而非 `round`:围标方通常写整数价(如 ¥1,234,567);小数部分多为 0 或 .00,truncate 简单稳定;真遇 .99 要进位的场景极少,实战若必要可改 round。
- `zfill(tail_n)`:整数位 < tail_n 的小金额(如 ¥100,tail_n=3 → "100" 正好 3 位,无需 pad;但 ¥99 则 "99" → "099",避免 index 越界)。
- `normalize_item_name` 复用 C10 `normalizer.py` 的 NFKC+casefold+strip 模式。

**替代方案**:
- Decimal quantize 保留 2 位小数再拼 str → 围标信号以"整元尾数"为主,小数位干扰多,拒。
- 用 `round(float(d))` 代 `int(d)` → 精度损失且围标场景不必要,拒。

### D3 — `PriceRow` & `extractor`

**决策**:extractor 批量 query 指定 bidder 的所有 PriceItem,返 `dict[sheet_name, list[PriceRow]]`(按 sheet 分组)。

```python
# models.py
class PriceRow(TypedDict):
    price_item_id: int
    bidder_id: int
    sheet_name: str
    row_index: int
    item_name_raw: str | None
    item_name_norm: str | None
    unit_price_raw: Decimal | None
    total_price_raw: Decimal | None
    # 预计算字段
    total_price_float: float | None   # series/variance 消费
    tail_key: tuple[str, int] | None  # (tail_3, int_len);tail 子消费

# extractor.py
async def extract_bidder_prices(
    session: AsyncSession, bidder_id: int, cfg: PriceConfig
) -> dict[str, list[PriceRow]]:
    stmt = (
        select(PriceItem)
        .where(PriceItem.bidder_id == bidder_id)
        .order_by(PriceItem.sheet_name, PriceItem.row_index)
        .limit(cfg.max_rows_per_bidder)
    )
    items = (await session.execute(stmt)).scalars().all()
    grouped: dict[str, list[PriceRow]] = defaultdict(list)
    for it in items:
        tail_key = split_price_tail(it.total_price, cfg.tail_n)
        grouped[it.sheet_name].append({
            "price_item_id": it.id,
            "bidder_id": bidder_id,
            "sheet_name": it.sheet_name,
            "row_index": it.row_index,
            "item_name_raw": it.item_name,
            "item_name_norm": normalize_item_name(it.item_name),
            "unit_price_raw": it.unit_price,
            "total_price_raw": it.total_price,
            "total_price_float": decimal_to_float_safe(it.total_price),
            "tail_key": tail_key,
        })
    return dict(grouped)
```

**理由**:
- 一次性预计算 `total_price_float` / `tail_key` / `item_name_norm`:4 detector 反复用,避免重复解析。
- `max_rows_per_bidder` 保护阈值(默认 5000):极端文档有万行报价明细时不拉爆内存。
- 按 `sheet_name` 分组:item_list_detector 的位置对齐阶段需要按同名 sheet 配对;tail/amount_pattern 则 flatten 使用。

**替代方案**:
- 不预计算,detector 内临时算 → 4 detector 反复算 Decimal → int,CPU 浪费;拒。
- 不分组直接返 `list[PriceRow]` → item_list_detector 内需重分组,重复劳动;拒。

### D4 — `tail_detector` 算法(子检测 1)

**决策**:基于 Q1 决策 `(尾 N 位字符串, 整数位长)` 组合 key,在 bidder_a/bidder_b 两侧 flatten 全部 PriceRow 后做跨投标人碰撞。

```python
# tail_detector.py
def detect_tail_collisions(
    rows_a: list[PriceRow], rows_b: list[PriceRow], cfg: TailConfig
) -> SubDimResult:
    # flatten 两侧 tail_key,过滤 None(异常样本行级 skip)
    keys_a = [r["tail_key"] for r in rows_a if r["tail_key"] is not None]
    keys_b = [r["tail_key"] for r in rows_b if r["tail_key"] is not None]
    if not keys_a or not keys_b:
        return {"score": None, "reason": "至少一侧无可比对报价行", "hits": []}
    set_a = set(keys_a)
    set_b = set(keys_b)
    intersect = set_a & set_b
    if not intersect:
        return {"score": 0.0, "reason": None, "hits": []}
    # hit_strength = |∩| / min(|A|, |B|)(对齐 C10 author_detector 语义)
    strength = len(intersect) / min(len(set_a), len(set_b))
    hits = []
    for key in intersect:
        docs_a = [r for r in rows_a if r["tail_key"] == key]
        docs_b = [r for r in rows_b if r["tail_key"] == key]
        hits.append({
            "tail": key[0],
            "int_len": key[1],
            "rows_a": [(r["sheet_name"], r["row_index"], str(r["total_price_raw"])) for r in docs_a],
            "rows_b": [(r["sheet_name"], r["row_index"], str(r["total_price_raw"])) for r in docs_b],
        })
    return {"score": strength, "reason": None, "hits": hits[:cfg.max_hits]}
```

**理由**:
- `(tail, int_len)` 组合 key 区分 ¥100 / ¥1100 / ¥8100(尾 3 位都是 100,整数位长 3/4/4)→ 避免不同量级跨行误撞(第一性原理审指出的精度漏洞)。
- `|∩| / min(|A|, |B|)` 公式与 C10 author_detector D6 一致(既有惯例推导 + 贴"围标信号"语义)。
- 异常样本行级 skip(`tail_key is None` 行直接过滤),不假阳(对齐 execution-plan §3 C11 兜底)。
- `max_hits` 限流(默认 20),避免 evidence_json 巨大。

**替代方案**:
- 纯尾数 key 不带 int_len → 不同量级误撞(Q1 选项 A 已否);拒。
- tail_n=2 → 围标 5 家两两 10 对,2 位 00-99 100 桶撞率极高(~10%),误报率飙升;拒。
- tail_n=4 → 漏报率上升(Q1 选项 C 讨论过);可 env 覆盖但默认 3。

### D5 — `amount_pattern_detector` 算法(子检测 2)

**决策**:跨投标人构建 `(item_name_norm, unit_price)` 对集合,计算**有效对**的交集占比。

```python
# amount_pattern_detector.py
def detect_amount_pattern(
    rows_a: list[PriceRow], rows_b: list[PriceRow], cfg: AmountPatternConfig
) -> SubDimResult:
    def _to_key(r: PriceRow) -> tuple[str, Decimal] | None:
        if r["item_name_norm"] is None or r["unit_price_raw"] is None:
            return None
        return (r["item_name_norm"], r["unit_price_raw"])

    pairs_a = {k for r in rows_a if (k := _to_key(r)) is not None}
    pairs_b = {k for r in rows_b if (k := _to_key(r)) is not None}
    if not pairs_a or not pairs_b:
        return {"score": None, "reason": "至少一侧无 (item_name, unit_price) 有效对", "hits": []}
    intersect = pairs_a & pairs_b
    if not intersect:
        return {"score": 0.0, "reason": None, "hits": []}
    strength = len(intersect) / min(len(pairs_a), len(pairs_b))
    hits = [
        {"item_name": name, "unit_price": str(price)}
        for (name, price) in list(intersect)[:cfg.max_hits]
    ]
    score = strength if strength >= cfg.threshold else 0.0
    return {"score": score, "reason": None, "hits": hits}
```

**理由**:
- 直接抓"共享报价计算的结构"真信号:同项同单价跨 bidder = 强证据(价格计算共享)。
- 阈值 `threshold=0.5`(默认):低于阈值视为弱信号不记分;避免 2 家报价表各有一两项单价相同的正常巧合被算高分。
- 异常样本行级 skip(item_name_norm 或 unit_price_raw 为 None)。
- `max_hits` 限流。

**替代方案**:
- 直接用 `total_price` 而非 `unit_price` → total_price 受 quantity 放大,同 item 不同量无法比对;拒。
- 三元组 `(item_name, unit_price, quantity)` → quantity 通常反映投标量差异,加进 key 会过严,实战漏报多;拒。

### D6 — `item_list_detector` 算法(子检测 3,Q3 两阶段对齐)

**决策**:两阶段对齐 + 整体相似度 ≥ 阈值命中。

```python
# item_list_detector.py
def detect_item_list_similarity(
    grouped_a: dict[str, list[PriceRow]],
    grouped_b: dict[str, list[PriceRow]],
    cfg: ItemListConfig,
) -> SubDimResult:
    # 阶段 1:判定"是否用同模板"
    same_sheets = set(grouped_a.keys()) == set(grouped_b.keys())
    same_sizes = all(
        len(grouped_a.get(s, [])) == len(grouped_b.get(s, []))
        for s in grouped_a.keys()
    ) if same_sheets else False

    if same_sheets and same_sizes:
        # 阶段 1a:按 (sheet_name, row_index) 位置对齐
        return _detect_by_position(grouped_a, grouped_b, cfg)
    else:
        # 阶段 1b:按 item_name_norm 精确归一匹配(flatten)
        return _detect_by_item_name(grouped_a, grouped_b, cfg)


def _detect_by_position(
    grouped_a: dict[str, list[PriceRow]],
    grouped_b: dict[str, list[PriceRow]],
    cfg: ItemListConfig,
) -> SubDimResult:
    total_pairs = 0
    matched_pairs = 0
    hits = []
    for sheet in sorted(grouped_a.keys()):
        rows_a_sorted = sorted(grouped_a[sheet], key=lambda r: r["row_index"])
        rows_b_sorted = sorted(grouped_b[sheet], key=lambda r: r["row_index"])
        for r_a, r_b in zip(rows_a_sorted, rows_b_sorted):
            # 对齐行:item_name_norm 相同 + unit_price 相同 → 视为"同项同价"配对成功
            total_pairs += 1
            if (
                r_a["item_name_norm"] is not None
                and r_a["item_name_norm"] == r_b["item_name_norm"]
                and r_a["unit_price_raw"] is not None
                and r_a["unit_price_raw"] == r_b["unit_price_raw"]
            ):
                matched_pairs += 1
                if len(hits) < cfg.max_hits:
                    hits.append({
                        "mode": "position",
                        "sheet": sheet,
                        "row_a": r_a["row_index"],
                        "row_b": r_b["row_index"],
                        "item_name": r_a["item_name_raw"],
                    })
    if total_pairs == 0:
        return {"score": None, "reason": "阶段 1a 对齐后无有效行", "hits": []}
    strength = matched_pairs / total_pairs
    score = strength if strength >= cfg.threshold else 0.0
    return {"score": score, "reason": None, "hits": hits}


def _detect_by_item_name(
    grouped_a: dict[str, list[PriceRow]],
    grouped_b: dict[str, list[PriceRow]],
    cfg: ItemListConfig,
) -> SubDimResult:
    rows_a = [r for rs in grouped_a.values() for r in rs]
    rows_b = [r for rs in grouped_b.values() for r in rs]
    names_a = {r["item_name_norm"] for r in rows_a if r["item_name_norm"]}
    names_b = {r["item_name_norm"] for r in rows_b if r["item_name_norm"]}
    if not names_a or not names_b:
        return {"score": None, "reason": "阶段 1b 至少一侧无 item_name", "hits": []}
    intersect = names_a & names_b
    strength = len(intersect) / min(len(names_a), len(names_b))
    score = strength if strength >= cfg.threshold else 0.0
    hits = [{"mode": "item_name", "item_name": n} for n in list(intersect)[:cfg.max_hits]]
    return {"score": score, "reason": None, "hits": hits}
```

**理由**:
- 两阶段对齐的必要性详见 Q3 讨论:同模板场景 row_index 天然对齐是最强信号;非同模板场景 item_name 精确归一是兜底。
- 阈值 0.95(默认,对齐 execution-plan §3 C11 Scenario 2 "95%+ 相似"原文):高阈值减少误报。
- 阶段 1a 的"同项同价"双条件:仅 item_name 相同不够(模板共享的本质是"同结构 + 同价"),需 unit_price 也相同。

**替代方案**:
- 只做位置对齐 → 非同模板场景全 skip,漏报多;拒(Q3 选项 B 已否)。
- 只做 item_name 归一 → 同模板信号弱化,漏掉"共享模板"这个最强围标套路;拒(Q3 选项 A 已否)。
- LLM 语义对齐 → Q3 选项 D,留 C14;拒。

### D7 — `series_relation_detector` 算法(子检测 4,Q5 新增)

**决策**:基于第一性原理审暴露的"水平关系"真信号缺口新增。对齐行序列检测等比/等差关系。

```python
# series_relation_detector.py
def detect_series_relation(
    grouped_a: dict[str, list[PriceRow]],
    grouped_b: dict[str, list[PriceRow]],
    cfg: SeriesConfig,
) -> SubDimResult:
    # 仅在阶段 1a(同模板)条件满足时跑 series 检测;否则 row_index 对齐不可靠
    same_sheets = set(grouped_a.keys()) == set(grouped_b.keys())
    same_sizes = all(
        len(grouped_a.get(s, [])) == len(grouped_b.get(s, []))
        for s in grouped_a.keys()
    ) if same_sheets else False
    if not (same_sheets and same_sizes):
        return {"score": None, "reason": "非同模板,series 子检测不适用", "hits": []}

    ratios: list[float] = []
    diffs: list[float] = []
    pair_count = 0
    for sheet in sorted(grouped_a.keys()):
        rows_a_sorted = sorted(grouped_a[sheet], key=lambda r: r["row_index"])
        rows_b_sorted = sorted(grouped_b[sheet], key=lambda r: r["row_index"])
        for r_a, r_b in zip(rows_a_sorted, rows_b_sorted):
            a = r_a["total_price_float"]
            b = r_b["total_price_float"]
            if a is None or b is None or a == 0:
                continue
            ratios.append(b / a)
            diffs.append(b - a)
            pair_count += 1

    if pair_count < cfg.min_pairs:
        return {
            "score": None,
            "reason": f"对齐样本不足(需 ≥ {cfg.min_pairs},实得 {pair_count})",
            "hits": [],
        }

    import statistics
    ratio_var = statistics.pvariance(ratios) if len(ratios) >= 2 else 0.0
    mean_diff = statistics.mean(diffs)
    diff_cv = (
        statistics.pstdev(diffs) / abs(mean_diff)
        if len(diffs) >= 2 and mean_diff != 0
        else float("inf")
    )

    hits = []
    is_ratio_hit = ratio_var < cfg.ratio_variance_max
    is_diff_hit = diff_cv < cfg.diff_cv_max
    score = 0.0

    if is_ratio_hit:
        k = statistics.mean(ratios)
        hits.append({
            "mode": "ratio",
            "k": round(k, 6),
            "variance": round(ratio_var, 9),
            "pairs": pair_count,
        })
        score = max(score, 1.0)
    if is_diff_hit:
        hits.append({
            "mode": "diff",
            "diff": round(mean_diff, 2),
            "cv": round(diff_cv, 6),
            "pairs": pair_count,
        })
        score = max(score, 1.0)

    return {"score": score, "reason": None, "hits": hits}
```

**理由**:
- **只在同模板时跑**:row_index 对齐不可靠时方差计算无意义(对齐错位会让 ratios 全乱)。
- **ratio_variance_max=0.001**:等比关系要求 k 在样本间波动极小(5 行 k=0.95 ± 0.03 方差 ≈ 0.001,更紧的围标信号方差 < 0.0001);env 可调。
- **diff_cv_max=0.01**:变异系数对数值尺度鲁棒(相同结构下 CV 比绝对方差更稳);百万量级差额 1% 波动即命中。
- **min_pairs=3**:方差 2 样本不稳(几乎必然很小),最低 3 行对齐;env 可调。
- **等差 k=1 与等比 k=1 的区分**:当 b = a 时比值 k=1 方差 0(命中 ratio),差值 = 0 CV 未定义(mean_diff=0 → inf,不命中 diff);此时 amount_pattern 本就会命中(单价相同),不重复记分,且 ratio hit 仍触发 series 子检测 1.0 强信号,体现"精确比例 1:1"语义。

**替代方案**:
- 滑窗切片一部分行做 series → 实战围标常整表等比,全对齐更稳;拒。
- 只做等比不做等差 → 等差套路"A/B/C 线性抬高"漏报;拒。
- 对任意 `|ratio - median_ratio| / median_ratio < ε` 做 robust 中位数法 → 初版先用方差 + CV 标准统计量,实战有异常值干扰再升级;留 follow-up。

### D8 — scorer 合成规则

**决策**:4 子检测按 env `PRICE_CONSISTENCY_SUBDIM_WEIGHTS`(默认 `0.25,0.25,0.3,0.2`)加权合成 Agent 级 score,disabled / score=None 子检测不参与归一化(对齐 C10 D10)。

```python
# scorer.py
def combine_subdims(
    results: dict[str, SubDimResult],  # {"tail": ..., "amount_pattern": ..., ...}
    cfg: ScorerConfig,
) -> tuple[float, dict]:
    participating = []
    total_weight = 0.0
    weighted = 0.0
    for name in cfg.order:  # ["tail", "amount_pattern", "item_list", "series"]
        if not cfg.enabled[name]:
            continue  # flag disabled
        r = results[name]
        if r["score"] is None:
            continue  # 子检测自我 skip(样本不足等)
        participating.append(name)
        w = cfg.weights[name]
        total_weight += w
        weighted += r["score"] * w
    if not participating:
        # 全部 skip:Agent 级 skip 哨兵
        return 0.0, {
            "enabled": False,
            "reason": "所有子检测均 skip 或 disabled",
            "participating_subdims": [],
            "subdims": {n: _shape_subdim(results.get(n), cfg.enabled[n]) for n in cfg.order},
        }
    # 归一化
    score_normalized = (weighted / total_weight) * 100.0  # → 0~100
    return score_normalized, {
        "enabled": True,
        "participating_subdims": participating,
        "subdims": {n: _shape_subdim(results.get(n), cfg.enabled[n]) for n in cfg.order},
    }
```

**子权重默认 `0.25/0.25/0.3/0.2`(tail/amount_pattern/item_list/series)理由**:
- item_list 权重最高(0.3):直接抓"共享模板"这个最强围标套路。
- tail + amount_pattern 并列次之(各 0.25):都是"共享报价计算"证据,但各自有假阳可能(tail 随机撞 / amount_pattern 行业单价巧合)。
- series 权重略低(0.2):新增信号,初期保守;实战反馈后可调高。

**替代方案**:
- 均权 `0.25 × 4` → 无法反映 item_list 的最强信号地位;拒。
- 任一子检测命中即 score=100 → 丢失强度信息 + 不同子检测信号强弱差异大;拒。

### D9 — 兜底语义(行级 / 子检测级 / Agent 级)

**决策**:三层 skip,语义清晰分离。

| 层级 | 触发条件 | 行为 | evidence 标记 |
|---|---|---|---|
| **行级** | `total_price` NULL / 非数值 / < 0;`item_name` NULL | 该行过滤不参与任何子检测 | 不单独标记;`participating_rows_count` 可选输出 |
| **子检测级(数据不足)** | extractor 后任一侧 0 有效行;series `min_pairs` 不足 | `score=None + reason` | `evidence.subdims.<name>.score=null, reason="..."` |
| **子检测级(flag disabled)** | `PRICE_CONSISTENCY_<SUB>_ENABLED=false` | 不执行 detector | `evidence.subdims.<name>.enabled=false` |
| **子检测级(hit 为 0)** | detector 返 `score=0.0` | 正常参与合成 | `evidence.subdims.<name>.score=0.0` |
| **Agent 级(preflight skip)** | 两 bidder 都无 PriceItem / 单侧无 | preflight 返 `skip` | 不写 PairComparison(C6 既有行为) |
| **Agent 级(4 子全 skip)** | 4 子检测全 `score=None` 或全 disabled | `score=0.0` + `participating_subdims=[]` 哨兵 | `evidence.enabled=false` |

**execution-plan §3 C11 原文对齐**:
- "异常样本(非数值/缺失)→ 跳过不假阳" ↔ 行级 skip + 子检测级 score=None
- "归一化失败 → 标'口径不一致,无法比对'" ↔ Q2 决策简化:C11 不做口径归一化,不产生该路径;design §Non-Goals 注明

### D10 — env 配置

**决策**:统一 `PRICE_CONSISTENCY_` 前缀,9 个 env。

| env | 默认值 | 说明 |
|---|---|---|
| `PRICE_CONSISTENCY_TAIL_ENABLED` | `true` | 子检测 1 开关 |
| `PRICE_CONSISTENCY_AMOUNT_PATTERN_ENABLED` | `true` | 子检测 2 开关 |
| `PRICE_CONSISTENCY_ITEM_LIST_ENABLED` | `true` | 子检测 3 开关 |
| `PRICE_CONSISTENCY_SERIES_ENABLED` | `true` | 子检测 4 开关(第一性原理审新增) |
| `PRICE_CONSISTENCY_TAIL_N` | `3` | 尾数位数 |
| `PRICE_CONSISTENCY_AMOUNT_PATTERN_THRESHOLD` | `0.5` | 子 2 命中阈值 |
| `PRICE_CONSISTENCY_ITEM_LIST_THRESHOLD` | `0.95` | 子 3 命中阈值 |
| `PRICE_CONSISTENCY_SERIES_RATIO_VARIANCE_MAX` | `0.001` | 等比方差上限 |
| `PRICE_CONSISTENCY_SERIES_DIFF_CV_MAX` | `0.01` | 等差变异系数上限 |
| `PRICE_CONSISTENCY_SERIES_MIN_PAIRS` | `3` | 系列检测最低对齐样本 |
| `PRICE_CONSISTENCY_SUBDIM_WEIGHTS` | `0.25,0.25,0.3,0.2` | 4 子权重(逗号分隔,顺序 tail/amount_pattern/item_list/series) |
| `PRICE_CONSISTENCY_MAX_ROWS_PER_BIDDER` | `5000` | 单 bidder PriceItem 最大加载量(保护阈值) |
| `PRICE_CONSISTENCY_MAX_HITS_PER_SUBDIM` | `20` | 单子检测 evidence hits 限流 |

**理由**:统计实际 13 条(含阈值细项),但关键"可调优阀值"9 个;命名对齐 C10 `METADATA_*` 风格。

### D11 — Q2 决策落地:不读 price_parsing_rule 字段

**决策**:C11 **完全不 import** `price_parsing_rules` 相关 schema;不 query `currency` / `tax_included` 字段;所有 `total_price` / `unit_price` 按 PriceItem 表原始值比较。

**Scenario 3 改写(execution-plan §3 C11 原"币种/含税口径不一致 → 先归一化再比较")**:
- 原语义:口径不一致 → 归一化比对
- Q2 决策语义:**口径字段不读**,直接比原始数值;"真同价不同数值"场景留 C14

**兜底链**:
- Plan A(C4 业主侧报价规则配置):业主统一规定"都含税"或"都不含税",前置消化口径分歧
- Plan B(C14 LLM 综合研判):真有口径混用场景 LLM 识别"同价不同表述"
- Plan C(C17 admin):规则版本化,可审计

**理由**:详见 Q2 讨论三条(§3 原文兜底就是此决策 / 项目一贯"宁漏勿误"风格 / 多币种场景国内目标市场极罕见,不造汇率基础设施)。

### D12 — Q4 决策落地:只走 PriceItem,不消费 DocumentSheet

**决策**:C11 4 子检测全部从 `PriceItem` 查数据;`DocumentSheet` 表 C11 代码中不 import、不 query。

**理由**:
- Q3 已定的 `(sheet_name, row_index)` 对齐 PriceItem 自带字段,不需要 DocumentSheet 提供
- 结构信号(合并单元格/空白填充)已在 C9 `structure_similarity` 覆盖,C11 再做是职责重叠
- 分层清晰:C5 = 报价抽取层、C9 = 结构层、C11 = 报价数值检测层

**Follow-up**:如 PriceItem 抽取本身漏行(C5 规则瑕疵),由 C5 修,C11 不绕路补。

## Risks / Trade-offs

### R1 — series 方差阈值实战调参不确定

**风险**:`ratio_variance_max=0.001` / `diff_cv_max=0.01` 是经验值,真实样本数据分布未知;阈值过松 → 假阳;过严 → 漏报。

**缓解**:
- env 可动态覆盖,无需改代码
- L2 Scenario 5 用人工构造的"等比 k=0.95(方差 0)"和"正常独立报价(方差 > 0.05)"验证边界
- handoff follow-up 项:实战数据反馈后首 PR 调参

### R2 — Decimal → float 精度损失(仅 series 子检测)

**风险**:`Numeric(18, 2)` 最大约 9×10^15 < float64 尾数位 2^53 ≈ 9×10^15,临界值附近精度边缘;围标场景实际金额通常在 10^7~10^9 量级,远低于临界。

**缓解**:
- `decimal_to_float_safe` 兜底 try/except
- series 对数值尺度用 CV 归一,绝对精度损失对结果不敏感

### R3 — item_name NULL 行漏报

**风险**:C5 归一化失败写 NULL;C11 对 NULL item_name 行:tail 子检测仍参与(只看 total_price);amount_pattern 子检测跳过该行;item_list 阶段 1a 仍参与(看 unit_price_raw 等价),阶段 1b 跳过;series 仍参与(看 total_price)。

**缓解**:4 子检测有 3 个对 NULL item_name 有覆盖,不会让 NULL 行 evidence 完全丢失;design 在 D9 表格明示分层 skip 语义。

### R4 — 同模板误判为不同模板

**风险**:两 bidder 清单条目数因各自删除某行而 count mismatch(如 A 把"优惠"一行删了 B 没删),D6 阶段 1 判定就失败掉到阶段 1b;series 也整体 skip。

**缓解**:
- 阶段 1b 按 item_name 归一仍能抓"95%+ 重合"的 item_list 强信号
- series 漏报此场景是 design 妥协(行对齐歧义下方差无意义);留 follow-up:极端场景可加"模糊 count 差 < 5%"放行
- L1 测试覆盖"A 18 行 / B 17 行"这种差 1 行的边界

### R5 — series vs amount_pattern 双命中重复记分

**风险**:当 b = a(ratio=1)时,series 与 amount_pattern 可能同时命中;双 1.0 按权重合成后 score 不会超过 100(归一化保证),但 evidence 上可能让审查员误以为"双维度独立命中"。

**缓解**:scorer 合成时是数学归一化,score 总体在 [0, 100];evidence.subdims 各自保留原值给前端判断语义;handoff 写清楚此约束。

### R6 — preflight 未收紧到 4 子检测全 disabled

**风险**:所有 4 个 flag 都 false 时 preflight 仍可能返 ok(因 `bidder_has_priced` 不看 flag),run 进来 4 子全 skip 写哨兵 row。

**缓解**:
- scorer 的 Agent 级 skip 哨兵就是为这种情况兜底
- handoff 写入:生产若全关 C11 请通过 AGENT_ENABLED 机制整体关闭,不要 4 flag 单独全关

### R7 — 第一性原理审的遗漏

**风险**:审一次不代表穷尽;围标可能还有"分段位跳变"(报价在某几段线性、某几段跳变)这种复杂模式本 change 未捕获。

**缓解**:memory 已新增 feedback_first_principles_review.md,后续 change 常驻审计;本 change follow-up 可追加"分段 series 检测"。
