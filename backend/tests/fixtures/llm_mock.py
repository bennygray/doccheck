"""LLM mock 统一入口 - C1 infra-base

CLAUDE.md 测试标准约定:所有需要 mock LLM 的测试(后续 L-1/L-2 + 7 个文本相似类 Agent,
共 8 个调用点)**必须**从此模块取 fixture,不允许各自 mock,避免行为漂移。

使用方式:
    @pytest.fixture
    def mock_llm_provider(): ...      # 默认 mock 返回 text="mocked"
    @pytest.fixture
    def mock_llm_provider_timeout(): ...  # 模拟超时错
    @pytest.fixture
    def mock_llm_provider_rate_limit(): ...  # 模拟限流错
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.services.llm.base import ErrorKind, LLMError, LLMResult, Message


@dataclass
class MockLLMProvider:
    """可编程 mock provider:按需构造成功/失败响应。

    - 默认成功:返回 LLMResult(text="mocked")
    - 失败:设置 error_kind,返回对应 LLMError
    - calls:记录调用历史,测试里可断言
    """

    name: str = "mock"
    response_text: str = "mocked"
    error_kind: ErrorKind | None = None
    error_message: str = "mocked error"
    calls: list[list[Message]] = field(default_factory=list)

    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResult:
        self.calls.append(list(messages))
        if self.error_kind is not None:
            return LLMResult(
                text="",
                error=LLMError(kind=self.error_kind, message=self.error_message),
            )
        return LLMResult(text=self.response_text)


@pytest.fixture
def mock_llm_provider() -> MockLLMProvider:
    """默认成功 mock。测试里可 .error_kind = 'timeout' 等切换成失败分支。"""
    return MockLLMProvider()


@pytest.fixture
def mock_llm_provider_timeout() -> MockLLMProvider:
    return MockLLMProvider(error_kind="timeout", error_message="mocked timeout")


@pytest.fixture
def mock_llm_provider_rate_limit() -> MockLLMProvider:
    return MockLLMProvider(error_kind="rate_limit", error_message="mocked 429")


# C5 新增:parser-pipeline 专用 mock 工厂 -----------------------------------


def make_role_classify_response(
    doc_roles: list[tuple[int, str]],
    identity_info: dict | None = None,
    confidence: str = "high",
) -> str:
    """构造 role_classifier LLM 成功响应 JSON 文本。"""
    import json

    return json.dumps(
        {
            "roles": [
                {"document_id": did, "role": r, "confidence": confidence}
                for did, r in doc_roles
            ],
            "identity_info": identity_info or {},
        }
    )


def make_price_rule_response(
    sheet_name: str = "报价清单",
    header_row: int = 2,
    mapping: dict | None = None,
) -> str:
    """构造 price_rule_detector LLM 成功响应 JSON 文本。"""
    import json

    default_mapping = {
        "code_col": "A",
        "name_col": "B",
        "unit_col": "C",
        "qty_col": "D",
        "unit_price_col": "E",
        "total_price_col": "F",
        "skip_cols": [],
    }
    return json.dumps(
        {
            "sheet_name": sheet_name,
            "header_row": header_row,
            "column_mapping": mapping or default_mapping,
        }
    )


# C7 新增:text_similarity 专用 mock 工厂 -----------------------------------


def make_text_similarity_response(
    judgments: list[tuple[int, str]],
    overall: str = "mock overall",
    confidence: str = "high",
) -> str:
    """构造 text_similarity LLM 成功响应 JSON 文本(按 L-4 规格)。"""
    import json

    return json.dumps(
        {
            "pairs": [
                {"idx": idx, "judgment": j, "note": "mock"}
                for idx, j in judgments
            ],
            "overall": overall,
            "confidence": confidence,
        },
        ensure_ascii=False,
    )


@pytest.fixture
def mock_llm_text_sim_success() -> ScriptedLLMProvider:
    """默认返全部 plagiarism(用于抄袭命中 scenario)。"""
    # 构造 "idx 0..N"(最多 30)都标 plagiarism 的通用响应;
    # scripted 的 loop_last=True 让无论调几次都一致返这个
    payload = make_text_similarity_response(
        [(i, "plagiarism") for i in range(30)],
        overall="技术方案段落高度疑似同源",
        confidence="high",
    )
    return ScriptedLLMProvider([payload], loop_last=True)


@pytest.fixture
def mock_llm_text_sim_bad_json() -> ScriptedLLMProvider:
    """始终返回非 JSON(触发 2 次解析失败 → 降级)。"""
    return ScriptedLLMProvider(["this is not json"], loop_last=True)


@pytest.fixture
def mock_llm_text_sim_timeout() -> ScriptedLLMProvider:
    """始终返 timeout error(触发降级)。"""
    return ScriptedLLMProvider(
        [LLMError(kind="timeout", message="mocked text_sim timeout")],
        loop_last=True,
    )


# C8 新增:section_similarity LLM mock --------------------------------------


def make_section_similarity_response(
    judgments: list[tuple[int, str]],
    overall: str = "mock section overall",
    confidence: str = "high",
) -> str:
    """构造 section_similarity LLM 响应 JSON(与 C7 response schema 一致)。

    C8 评分器把跨章节段落对合并为一次 LLM 调用,返 schema 完全复用 C7。
    单独命名工厂便于测试语义区分。
    """
    return make_text_similarity_response(judgments, overall, confidence)


@pytest.fixture
def mock_llm_section_sim_success() -> ScriptedLLMProvider:
    """返全 plagiarism(用于章节雷同 scenario)。"""
    payload = make_section_similarity_response(
        [(i, "plagiarism") for i in range(30)],
        overall="章节级高度疑似同源",
        confidence="high",
    )
    return ScriptedLLMProvider([payload], loop_last=True)


@pytest.fixture
def mock_llm_section_sim_degraded() -> ScriptedLLMProvider:
    """返 timeout → 降级(evidence.degraded=true)。"""
    return ScriptedLLMProvider(
        [LLMError(kind="timeout", message="mocked section_sim timeout")],
        loop_last=True,
    )


# C13 新增:error_consistency L-5 + style L-8 两阶段 mock 工厂 -----------------


def make_l5_response(
    *,
    is_cross_contamination: bool = True,
    direct_evidence: bool = True,
    confidence: float = 0.85,
    evidence_items: list[dict] | None = None,
) -> str:
    """构造 error_consistency L-5 LLM 响应 JSON。"""
    import json

    return json.dumps(
        {
            "is_cross_contamination": is_cross_contamination,
            "direct_evidence": direct_evidence,
            "confidence": confidence,
            "evidence": evidence_items or [
                {
                    "type": "公司名混入",
                    "snippet": "mock snippet",
                    "position": "body",
                }
            ],
        },
        ensure_ascii=False,
    )


@pytest.fixture
def mock_llm_l5_iron() -> ScriptedLLMProvider:
    """L-5 返铁证(direct_evidence=true)。"""
    return ScriptedLLMProvider(
        [make_l5_response(direct_evidence=True)], loop_last=True
    )


@pytest.fixture
def mock_llm_l5_non_iron() -> ScriptedLLMProvider:
    """L-5 返污染但非铁证。"""
    return ScriptedLLMProvider(
        [
            make_l5_response(
                is_cross_contamination=True,
                direct_evidence=False,
                confidence=0.6,
            )
        ],
        loop_last=True,
    )


@pytest.fixture
def mock_llm_l5_no_contamination() -> ScriptedLLMProvider:
    """L-5 返无污染。"""
    return ScriptedLLMProvider(
        [
            make_l5_response(
                is_cross_contamination=False,
                direct_evidence=False,
                confidence=0.1,
            )
        ],
        loop_last=True,
    )


@pytest.fixture
def mock_llm_l5_failed() -> ScriptedLLMProvider:
    """L-5 全部 timeout(触发兜底:仅程序 evidence)。"""
    return ScriptedLLMProvider(
        [LLMError(kind="timeout", message="mocked L-5 timeout")],
        loop_last=True,
    )


@pytest.fixture
def mock_llm_l5_bad_json() -> ScriptedLLMProvider:
    """L-5 返非 JSON,触发解析失败兜底。"""
    return ScriptedLLMProvider(["not json at all"], loop_last=True)


def make_l8_stage1_response(
    *,
    word_pref: str = "口语化、多用'我们'",
    sentence_style: str = "短句为主",
    punctuation: str = "顿号偏好",
    paragraph: str = "总分总结构",
) -> str:
    """构造 style L-8 Stage1 响应 JSON。"""
    import json

    return json.dumps(
        {
            "用词偏好": word_pref,
            "句式特点": sentence_style,
            "标点习惯": punctuation,
            "段落组织": paragraph,
        },
        ensure_ascii=False,
    )


def make_l8_stage2_response(
    consistent_groups: list[dict] | None = None,
) -> str:
    """构造 style L-8 Stage2 响应 JSON。

    consistent_groups: [{"bidder_ids": [int], "consistency_score": float, "typical_features": str}]
    """
    import json

    return json.dumps(
        {
            "consistent_groups": consistent_groups
            or [
                {
                    "bidder_ids": [1, 2],
                    "consistency_score": 0.85,
                    "typical_features": "mock typical features",
                }
            ]
        },
        ensure_ascii=False,
    )


@pytest.fixture
def mock_llm_l8_full_success() -> ScriptedLLMProvider:
    """L-8 两阶段全成功(Stage1 多次返同一 brief + Stage2 返一致组)。

    用 loop_last=True 让 Stage1 多次调用都返同一 brief;Stage2 单次。
    实际多次调用时 Stage1 brief 会重复(测试场景默认 N 家用相同 mock brief),
    Stage2 触发后用 stage2_response 覆盖。
    """
    # 注意:此 fixture 用顺序脚本 — 测试时 Stage1 调 N 次,Stage2 调 1 次
    # ScriptedLLMProvider loop_last=True 让 Stage2 之后的调用都返 stage2 响应
    return ScriptedLLMProvider(
        [
            make_l8_stage1_response(),  # 默认 Stage1 第一次
            make_l8_stage1_response(),  # Stage1 第二次
            make_l8_stage1_response(),  # Stage1 第三次
            make_l8_stage2_response(),  # Stage2(loop_last 兜底)
        ],
        loop_last=True,
    )


@pytest.fixture
def mock_llm_l8_stage1_failed() -> ScriptedLLMProvider:
    """L-8 Stage1 全部失败 → Agent skip。"""
    return ScriptedLLMProvider(
        [LLMError(kind="timeout", message="mocked L-8 Stage1 timeout")],
        loop_last=True,
    )


@pytest.fixture
def mock_llm_l8_stage2_failed() -> ScriptedLLMProvider:
    """L-8 Stage1 成功,Stage2 失败。

    脚本顺序:Stage1 N 次成功 + 1 次 Stage2 失败(需要 loop_last 让后续 Stage2
    重试也返同一 LLMError)。
    Stage1 默认全成功(loop_last 之前 brief 多份);Stage2 失败由 ScriptedLLM 单
    error 控制。本 fixture 无法精确控制"先 N 次成功后失败" — 调用方需自行
    用 monkeypatch 拦截 call_l8_stage2 单独 mock 失败。
    """
    return ScriptedLLMProvider(
        [
            make_l8_stage1_response(),
            make_l8_stage1_response(),
            make_l8_stage1_response(),
            LLMError(kind="timeout", message="mocked L-8 Stage2 timeout"),
        ],
        loop_last=True,
    )


@pytest.fixture
def mock_llm_l8_bad_json_stage1() -> ScriptedLLMProvider:
    """L-8 Stage1 返非 JSON。"""
    return ScriptedLLMProvider(["not json"], loop_last=True)


# C14 新增:judge L-9 综合研判 mock(直接 patch judge_llm.call_llm_judge,不走 provider)


def make_l9_response(
    *,
    suggested_total: float = 78.0,
    conclusion: str = "基于 11 维度证据综合研判,本项目存在中等围标嫌疑,建议重点关注文本相似度和报价一致性维度。",
    reasoning: str = "mock reasoning",
) -> str:
    """构造 L-9 合法 JSON 响应字符串(仅 ScriptedLLMProvider 需要;大多数测试直接用下方 fixture)"""
    import json

    return json.dumps(
        {
            "suggested_total": suggested_total,
            "conclusion": conclusion,
            "reasoning": reasoning,
        },
        ensure_ascii=False,
    )


@pytest.fixture
def mock_llm_l9_ok(monkeypatch):
    """L-9 成功:直接 patch call_llm_judge 返 (conclusion, suggested)。

    用法:
        def test_foo(mock_llm_l9_ok):
            mock_llm_l9_ok(conclusion="...", suggested_total=78.0)
            # 之后任何调 judge_llm.call_llm_judge 的路径都返 mock 值
    """
    from app.services.detect import judge_llm

    def _apply(
        conclusion: str = "综合研判:中等围标嫌疑。",
        suggested_total: float = 78.0,
    ):
        async def _fake(summary, formula_total, *, provider=None, cfg=None):
            return conclusion, float(suggested_total)

        monkeypatch.setattr(judge_llm, "call_llm_judge", _fake)

    return _apply


@pytest.fixture
def mock_llm_l9_upgrade(monkeypatch):
    """L-9 升分跨档:mock 返回一个比 formula 高的 suggested_total。

    默认 suggested=75(配合 formula=65 跨档到 high)。
    """
    from app.services.detect import judge_llm

    def _apply(suggested_total: float = 75.0):
        async def _fake(summary, formula_total, *, provider=None, cfg=None):
            return "综合研判:跨维度共振升分。", float(suggested_total)

        monkeypatch.setattr(judge_llm, "call_llm_judge", _fake)

    return _apply


@pytest.fixture
def mock_llm_l9_clamped(monkeypatch):
    """L-9 试图降分被守护:mock 返回低于 formula 或低于铁证下限的 suggested_total。

    默认 suggested=60(配合 formula=88+铁证,clamp 守护后 final=88)。
    """
    from app.services.detect import judge_llm

    def _apply(suggested_total: float = 60.0):
        async def _fake(summary, formula_total, *, provider=None, cfg=None):
            return "综合研判(LLM 误判降分测试)。", float(suggested_total)

        monkeypatch.setattr(judge_llm, "call_llm_judge", _fake)

    return _apply


@pytest.fixture
def mock_llm_l9_failed(monkeypatch):
    """L-9 失败:patch call_llm_judge 返 (None, None) → 上层走降级。"""
    from app.services.detect import judge_llm

    async def _fake(summary, formula_total, *, provider=None, cfg=None):
        return None, None

    monkeypatch.setattr(judge_llm, "call_llm_judge", _fake)
    return None


@pytest.fixture
def mock_llm_l9_bad_json():
    """L-9 返 bad JSON:返 ScriptedLLMProvider,测试时显式注入到 call_llm_judge 的 provider。

    此 fixture 用于 **单元测试** call_llm_judge 自身的 retry+parse 逻辑,不用于
    集成测试(集成测试用 mock_llm_l9_failed 或 mock_llm_l9_ok)。
    """
    return ScriptedLLMProvider(["this is not json at all"], loop_last=True)


@pytest.fixture
def mock_llm_l9_disabled(monkeypatch):
    """L-9 env disabled:LLM_JUDGE_ENABLED=false → judge_and_create_report 跳过 LLM 走降级"""
    monkeypatch.setenv("LLM_JUDGE_ENABLED", "false")
    return None


class ScriptedLLMProvider:
    """按调用顺序依次返不同响应/错 的 provider。

    用于 rule_coordinator 等多次调用场景。
    """

    def __init__(self, scripts: list, *, loop_last: bool = True):
        self.name = "scripted"
        self._scripts = list(scripts)
        self._loop_last = loop_last
        self._cursor = 0
        self.calls: list[list[Message]] = []

    async def complete(
        self, messages: list[Message], **kwargs
    ) -> LLMResult:
        self.calls.append(list(messages))
        if self._cursor >= len(self._scripts):
            if not self._loop_last:
                return LLMResult(
                    text="",
                    error=LLMError(kind="other", message="exhausted"),
                )
            item = self._scripts[-1]
        else:
            item = self._scripts[self._cursor]
            self._cursor += 1
        if isinstance(item, str):
            return LLMResult(text=item)
        if isinstance(item, LLMError):
            return LLMResult(text="", error=item)
        return LLMResult(text="", error=LLMError(kind=item, message="mock"))
