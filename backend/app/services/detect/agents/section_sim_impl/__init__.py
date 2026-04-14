"""section_similarity Agent 实现细节子包 (C8 detect-agent-section-similarity)

职责分工:
- config          : 3 env(MIN_CHAPTERS / MIN_CHAPTER_CHARS / TITLE_ALIGN_THRESHOLD)
- models          : ChapterBlock / ChapterPair / ChapterScoreResult dataclass
- chapter_parser  : 纯正则 5 种 PATTERN 切章
- aligner         : title TF-IDF 贪心对齐 + 序号回退
- scorer          : 章节对评分(复用 C7 text_sim_impl.tfidf/llm_judge/aggregator)
- fallback        : 章节切分失败时降级到整文档粒度(A1 独立降级)

C8 仅替换 section_similarity Agent 的 run(),C7 text_sim_impl/ 只读复用。
"""
