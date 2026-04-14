# C8 detect-agent-section-similarity L3 手工凭证占位

延续 C5/C6/C7 降级策略:Docker Desktop kernel-lock 未解除。kernel-lock 解除后按下面步骤手工补 3 张截图。

## 前置

- 同 C7;预埋 2 bidder × 技术方案.docx(明显 "第一章/第二章/第三章" 章节标题;其中一个章节双方文本 80% 相同)

## 3 张截图(保存为 01/02/03.png)

- **01-start-detect.png**:启动检测后,进度条显示 section_similarity 维度开始运行
- **02-report-chapter-row.png**:报告页 section_similarity 行:score ≥ 60,chapter_pairs 展开显示各对齐章节分数
- **03-fallback-case.png**:准备另一组无章节标题的文档(纯正文),跑完后 section_similarity 行 evidence.degraded_to_doc_level=true + algorithm=tfidf_cosine_fallback_to_doc 的降级提示

## 通过判据

- evidence_json.algorithm == "tfidf_cosine_chapter_v1"(正常)/ "tfidf_cosine_fallback_to_doc"(降级)
- chapter_pairs 至少 1 条 `aligned_by='title'`
- C7 text_similarity 维度不受 C8 影响,两行 PairComparison 独立计入总分

L1 266 + L2 182 = 448 通过已覆盖所有 C8 spec scenario,L3 凭证仅作 M3 demo 价值补齐。
