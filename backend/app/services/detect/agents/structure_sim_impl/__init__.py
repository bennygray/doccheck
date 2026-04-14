"""structure_similarity Agent 实现细节子包 (C9)

三维度结构相似度(纯程序化,不调 LLM):

- config        : 5 env(MIN_CHAPTERS / MIN_SHEET_ROWS / WEIGHTS /
                  FIELD_JACCARD_SUB_WEIGHTS / MAX_ROWS_PER_SHEET)
- models        : DirResult / FieldSimResult / FillSimResult /
                  SheetFieldResult / SheetFillResult
- title_lcs     : 目录结构维度(docx 章节标题序列 LCS);复用 C8 chapter_parser
- field_sig     : 字段结构维度(xlsx 列头 hash + 非空 bitmask + 合并单元格 Jaccard)
- fill_pattern  : 表单填充模式维度(xlsx cell type pattern Jaccard)
- scorer        : 三维度聚合 + evidence_json 构造

C9 仅替换 structure_similarity Agent 的 run(),C7/C8 子包只读复用。
"""
