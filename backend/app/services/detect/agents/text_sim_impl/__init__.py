"""text_similarity Agent 实现细节子包 (C7 detect-agent-text-similarity)

职责分工:
- config     : 3 个 env(MIN_DOC_CHARS / PAIR_SCORE_THRESHOLD / MAX_PAIRS_TO_LLM)动态读取
- stopwords  : 中文停用词集合
- models     : ParaPair dataclass(可 pickle 进子进程)
- segmenter  : DocumentText → 段落列表 + 短段合并 + 角色选择
- tfidf      : jieba 分词 + TfidfVectorizer + cosine_similarity,超阈值段落对提取
- llm_judge  : 组 L-4 prompt + 调 LLM + JSON 解析 + 重试 + 降级
- aggregator : pair 级 score 汇总 + is_ironclad 判定 + evidence_json 构造

C7 仅替换 text_similarity Agent 的 run(),其他 9 Agent 不触碰。
"""
