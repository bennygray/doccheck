## 1. 修改常量

- [x] 1.1 [impl] `text_sim_impl/aggregator.py`：`_SAMPLES_LIMIT` 从 10 改为 30
- [x] 1.2 [impl] `section_sim_impl/scorer.py`：`_CHAPTER_SAMPLES_LIMIT` 从 5 改为 15

## 2. 验证

- [x] 2.1 [L1] 现有测试全量通过（更新了 test_aggregator 的截断断言从 10→30）

## 3. 全量测试

- [x] 3.1 跑 [L1][L2] 全部测试，全绿 (1037 passed in 110.38s)
