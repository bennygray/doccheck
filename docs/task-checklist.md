# 围标检测系统 — 第一期层级需求清单

> **版本**: v1.0  
> **日期**: 2026-04-13  
> **用途**: 项目验收级参考文档，覆盖第一期全部功能点  
> **关联文档**: requirements.md (v0.8) / user-stories.md (v0.1)

## 工作量定义

| 等级 | 含义 | 参考人日 |
|------|------|---------|
| **小 (S)** | 单一职责，逻辑简单，不涉及复杂联动 | 1-2 人日 |
| **中 (M)** | 涉及多个组件/表/接口联动，有一定业务逻辑 | 3-5 人日 |
| **大 (L)** | 复杂业务逻辑、LLM 集成、多维度联动 | 5-10 人日 |

## 统计概览

| 指标 | 数量 |
|------|------|
| 模块数 | 9 |
| 功能项数 | 29 |
| 实现任务数 | 105 |
| API 端点数 | 36 |
| 数据库表 | 14 |
| 前端页面 | 11 |
| 检测维度 | 10 |
| LLM 调用场景 | 8 |

---

## 模块 1: 认证与授权 (AUTH)

### AUTH-01 用户登录 `US-1.1`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| AUTH-01-BE1 | 实现 POST /api/auth/login 接口（凭证校验、JWT 生成、失败计数、账户锁定） | BE | 中 | POST /api/auth/login | User | 5 |
| AUTH-01-BE2 | 实现 GET /api/auth/me 接口（解析 JWT、返回用户信息含 must_change_password） | BE | 小 | GET /api/auth/me | User | 2 |
| AUTH-01-BE3 | JWT 中间件依赖注入（get_current_user），所有受保护路由集成 | BE | 中 | 全部受保护端点 | User | 2 |
| AUTH-01-FE1 | 登录页面（/login）：表单、错误提示、loading 状态 | FE | 小 | POST /api/auth/login | - | 3 |
| AUTH-01-FE2 | Token 管理：localStorage 存取 + axios 拦截器自动附带 Authorization header | FE | 小 | - | - | 2 |
| AUTH-01-FE3 | 401 拦截器：token 过期提示"登录已过期" + 表单防丢失（缓存未提交数据到 localStorage） | FE | 中 | - | - | 2 |

### AUTH-02 用户登出 `US-1.2`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| AUTH-02-FE1 | 登出按钮（顶部栏）：清除 localStorage token + 跳转 /login | FE | 小 | - | - | 3 |

### AUTH-03 路由守卫与权限控制 `US-1.3`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| AUTH-03-FE1 | ProtectedRoute 组件：未登录→/login，审查员访问 /admin→/projects | FE | 中 | GET /api/auth/me | - | 4 |
| AUTH-03-BE1 | 后端每个 API 端点权限装饰器（角色校验：reviewer/admin） | BE | 中 | 全部端点 | User | 3 |
| AUTH-03-BE2 | 管理员对他人项目只读访问逻辑（查看详情/报告/导出可用，写操作拒绝） | BE | 小 | 项目相关端点 | Project | 2 |

### AUTH-04 初始用户与修改密码 `US-1.4`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| AUTH-04-BE1 | 数据库初始化脚本创建默认管理员（admin/admin123, must_change_password=true） | BE | 小 | - | User | 2 |
| AUTH-04-BE2 | POST /api/auth/change-password 接口（旧密码校验、新密码规则≥8位含字母数字） | BE | 小 | POST /api/auth/change-password | User | 4 |
| AUTH-04-FE1 | 修改密码页面（/change-password）+ ForceChangePassword 拦截组件 | FE | 小 | POST /api/auth/change-password | - | 3 |

---

## 模块 2: 项目管理 (PROJ)

### PROJ-01 创建项目 `US-2.1` `F-PM-01`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| PROJ-01-BE1 | POST /api/projects 接口（字段校验、owner 关联、status=draft） | BE | 小 | POST /api/projects | Project | 5 |
| PROJ-01-FE1 | 创建项目页面（/projects/new）：居中表单、字段校验、限价提示文案 | FE | 小 | POST /api/projects | - | 3 |

### PROJ-02 项目列表 `US-2.2` `F-PM-02`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| PROJ-02-BE1 | GET /api/projects 接口（分页、状态筛选、风险等级筛选、关键词搜索、权限过滤） | BE | 中 | GET /api/projects | Project | 5 |
| PROJ-02-FE1 | 项目列表页面（/projects）：卡片网格、筛选栏、搜索框、空状态引导 | FE | 中 | GET /api/projects | - | 5 |

### PROJ-03 项目详情 `US-2.3` `F-PM-03`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| PROJ-03-BE1 | GET /api/projects/{id} 接口（含 bidders[] + reports[] + current_analysis?） | BE | 中 | GET /api/projects/{id} | Project, Bidder, AnalysisReport, AgentTask | 6 |
| PROJ-03-FE1 | 项目详情页面（/projects/:id）：项目信息栏 + 投标人管理区 + 检测记录区 | FE | 大 | GET /api/projects/{id} | - | 6 |
| PROJ-03-FE2 | 状态流转展示（draft→parsing→ready→analyzing→completed）+ 按钮启禁逻辑 | FE | 小 | - | - | 3 |
| PROJ-03-FE3 | 检测进度条（SSE 驱动）：进度比例 + 一行最新动态摘要 `US-5.3` | FE | 中 | GET /api/projects/{pid}/events | - | 4 |

### PROJ-04 删除项目 `US-2.4` `F-PM-04`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| PROJ-04-BE1 | DELETE /api/projects/{id} 接口（级联删除全部关联数据 + 磁盘文件清理） | BE | 中 | DELETE /api/projects/{id} | Project 及全部级联表 | 4 |
| PROJ-04-FE1 | 删除确认弹窗 + analyzing 状态禁止删除 | FE | 小 | DELETE /api/projects/{id} | - | 2 |

---

## 模块 3: 投标人与文件管理 (FILE)

### FILE-01 添加投标人并上传 `US-3.1` `F-FM-01`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| FILE-01-BE1 | POST /api/projects/{pid}/bidders 接口（multipart: name+file?，名称唯一校验，触发异步解析） | BE | 中 | POST /api/projects/{pid}/bidders | Bidder, BidDocument | 7 |
| FILE-01-FE1 | "添加投标人"弹窗（名称输入 + 拖拽/选择压缩包上传区域） | FE | 中 | POST /api/projects/{pid}/bidders | - | 4 |
| FILE-01-FE2 | 前端文件校验（格式 ZIP/RAR/7Z + 大小≤500MB） | FE | 小 | - | - | 2 |

### FILE-02 追加上传 `US-3.2`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| FILE-02-BE1 | POST /api/projects/{pid}/bidders/{bid}/upload 接口（追加模式、MD5 去重、魔数校验） | BE | 中 | POST /api/projects/{pid}/bidders/{bid}/upload | BidDocument | 8 |
| FILE-02-FE1 | 追加上传交互（拖拽上传 + 进度条 + 去重提示） | FE | 小 | POST /api/projects/{pid}/bidders/{bid}/upload | - | 3 |

### FILE-03 文件列表与状态 `US-3.3` `F-FM-05`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| FILE-03-BE1 | GET /api/projects/{pid}/bidders/{bid}/documents 接口（文件列表含解析状态、角色、置信度） | BE | 小 | GET /api/projects/{pid}/bidders/{bid}/documents | BidDocument | 3 |
| FILE-03-BE2 | GET /api/documents/{id}/download 接口（文件流下载，过期返回 410 Gone） | BE | 小 | GET /api/documents/{id}/download | BidDocument | 3 |
| FILE-03-FE1 | 文件列表展开子表格（树形结构、角色标签、状态图标、下载按钮） | FE | 中 | 上述两个 API | - | 7 |

### FILE-04 修正文档角色 `US-4.3`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| FILE-04-BE1 | PATCH /api/documents/{id}/role 接口（角色枚举校验） | BE | 小 | PATCH /api/documents/{id}/role | BidDocument | 2 |
| FILE-04-FE1 | 角色标签点击弹出下拉修改 + "待确认"黄色高亮 + completed 项目提示 banner | FE | 小 | PATCH /api/documents/{id}/role | - | 3 |

### FILE-05 删除投标人 `US-3.4`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| FILE-05-BE1 | DELETE /api/projects/{pid}/bidders/{bid} 接口（级联删除 + 项目状态回退 ready/draft） | BE | 中 | DELETE /api/projects/{pid}/bidders/{bid} | Bidder 及级联表 | 4 |
| FILE-05-FE1 | 删除确认弹窗 + analyzing 状态禁止删除 | FE | 小 | DELETE /api/projects/{pid}/bidders/{bid} | - | 2 |

### FILE-06 加密压缩包解密 `US-4.1`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| FILE-06-BE1 | POST /api/documents/{id}/decrypt 接口（密码解压重试） | BE | 小 | POST /api/documents/{id}/decrypt | BidDocument | 2 |
| FILE-06-FE1 | "需密码"状态展示 + 密码输入弹窗 | FE | 小 | POST /api/documents/{id}/decrypt | - | 1 |

### FILE-07 报价解析规则 `US-4.4`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| FILE-07-BE1 | GET /api/projects/{pid}/price-rules 接口 | BE | 小 | GET /api/projects/{pid}/price-rules | PriceParsingRule | 1 |
| FILE-07-BE2 | PUT /api/projects/{pid}/price-rules/{id} 接口（修正列映射 + 触发批量重新提取） | BE | 中 | PUT /api/projects/{pid}/price-rules/{id} | PriceParsingRule, PriceItem | 3 |
| FILE-07-FE1 | 报价规则确认/修正界面（列映射下拉、sheet 选择、表头行配置） | FE | 中 | 上述两个 API | - | 4 |

---

## 模块 4: 文档解析 (PARSE)

### PARSE-01 压缩包解压与安全校验 `US-4.1` `F-FM-02` `F-PA-05步骤1`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| PARSE-01-BE1 | 递归解压引擎（ZIP/RAR/7Z，最大嵌套3层） | BE | 大 | - | BidDocument | 4 |
| PARSE-01-BE2 | 安全校验：zip bomb 防护（大小≤2GB、文件数≤1000）+ Zip Slip 路径穿越防护（realpath 验证） | BE | 中 | - | - | 3 |
| PARSE-01-BE3 | 文件名编码处理（UTF-8/GBK/GB2312 自动检测） | BE | 小 | - | - | 1 |
| PARSE-01-BE4 | 文件类型识别（魔数校验）+ 分类登记（docx/xlsx/image/unsupported/other） | BE | 小 | - | BidDocument | 2 |

### PARSE-02 文档内容提取 `US-4.2` `F-PA-01~04` `F-PA-05步骤2`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| PARSE-02-BE1 | DOCX 文本提取（段落 + 文本框 + 表格按行合并） | BE | 中 | - | DocumentText | 3 |
| PARSE-02-BE2 | DOCX 页眉页脚单独提取（存入 header_footer JSON 字段） | BE | 小 | - | DocumentText | 1 |
| PARSE-02-BE3 | DOCX/XLSX 元数据提取（author/last_saved_by/company/creator/时间/raw_metadata） | BE | 中 | - | DocumentMetadata | 2 |
| PARSE-02-BE4 | DOCX 图片提取 + MD5 + pHash 计算 | BE | 中 | - | DocumentImage | 2 |
| PARSE-02-BE5 | XLSX 单元格数据提取 + 隐藏 sheet/列扫描（硬件信息关键词） | BE | 中 | - | DocumentMetadata | 2 |

### PARSE-03 LLM 角色分类与标识提取 `US-4.3` `F-FM-04` `F-PA-05步骤3` `L-1`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| PARSE-03-BE1 | 规则预分类（文件名关键词匹配 9 种角色） | BE | 小 | - | BidDocument | 1 |
| PARSE-03-BE2 | LLM 批量分类 + 标识提取（L-1 prompt 实现，每投标人1次调用） | BE | 大 | - | BidDocument, Bidder | 4 |
| PARSE-03-BE3 | 兜底逻辑：LLM 失败→关键词匹配角色 + 标识信息留空 | BE | 小 | - | BidDocument, Bidder | 2 |

### PARSE-04 报价表结构识别与提取 `US-4.4` `F-PA-03` `F-PA-05步骤4` `L-2`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| PARSE-04-BE1 | LLM 报价结构识别（L-2 prompt，每项目1次） | BE | 大 | - | PriceParsingRule | 3 |
| PARSE-04-BE2 | 规则批量应用引擎（提取报价数据到 PriceItem） | BE | 中 | - | PriceItem | 2 |
| PARSE-04-BE3 | 并发控制（asyncio.Lock，同项目仅首个投标人触发 LLM）+ 自动回填 | BE | 中 | - | PriceParsingRule, PriceItem | 2 |
| PARSE-04-BE4 | 兜底：识别失败→标记待手动配置 + 批量应用失败→单独 LLM 重试 | BE | 小 | - | PriceParsingRule | 2 |

### PARSE-05 解析流水线编排 `F-PA-05`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| PARSE-05-BE1 | 异步流水线编排（5步骤串行/并行：解压→提取→分类→报价→收尾） | BE | 大 | - | 全部解析相关表 | 5 |
| PARSE-05-BE2 | 状态级联更新（BidDocument→Bidder→Project 状态转换） | BE | 中 | - | Project, Bidder, BidDocument | 3 |
| PARSE-05-BE3 | SSE 推送 parse_progress 事件（各步骤进度） | BE | 小 | GET /api/projects/{pid}/events | - | 2 |

---

## 模块 5: 检测执行 (DETECT)

### DETECT-01 启动检测 `US-5.1`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| DETECT-01-BE1 | POST /api/projects/{pid}/analysis/start 接口（前置校验、版本分配、AgentTask 创建、后台任务启动） | BE | 中 | POST /api/projects/{pid}/analysis/start | AgentTask | 6 |
| DETECT-01-FE1 | "启动检测"按钮逻辑（启禁条件、防重复提交、进度面板展开） | FE | 小 | POST /api/projects/{pid}/analysis/start | - | 3 |

### DETECT-02 Agent 并行执行框架 `US-5.2`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| DETECT-02-BE1 | Agent 调度框架（asyncio.gather 并行、各 Agent 自检前置条件、跳过/执行分支） | BE | 大 | - | AgentTask | 4 |
| DETECT-02-BE2 | SSE 推送 agent_status 事件 + report_ready 事件 | BE | 小 | GET /api/projects/{pid}/events | - | 2 |

### DETECT-03 硬件特征码 Agent `F-DA-01` `L-3`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| DETECT-03-BE1 | 三层提取（DOCX 属性→XLSX 隐藏 sheet/关键词→LLM 兜底）+ 精确匹配 | BE | 大 | - | PairComparison, DocumentMetadata | 4 |

### DETECT-04 错误一致性 Agent `F-DA-02` `L-5`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| DETECT-04-BE1 | 关键词交叉初筛（含防碰撞：短词过滤≤2字、高频降权>50段、候选上限100段） | BE | 中 | - | DocumentText, Bidder | 3 |
| DETECT-04-BE2 | LLM 深度判断（L-5 prompt，双向检查 + 页眉页脚） | BE | 大 | - | PairComparison | 3 |
| DETECT-04-BE3 | 降级模式（identity_info 为空→用投标人名称搜索，不跳过，不做铁证判定） | BE | 小 | - | PairComparison | 2 |

### DETECT-05 文本相似度 Agent `F-DA-03` `L-4`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| DETECT-05-BE1 | 段落级 TF-IDF + 余弦相似度计算（同角色文档对齐，过滤<50字短段落） | BE | 大 | - | PairComparison, DocumentText | 3 |
| DETECT-05-BE2 | LLM 同源性鉴别（L-4 prompt，区分模板/通用表述/真正抄袭） | BE | 中 | - | PairComparison | 2 |

### DETECT-06 价格构成 Agent `F-DA-04` `L-6`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| DETECT-06-BE1 | 清单对齐（编码精确→前缀局部→名称相似度→LLM 辅助→兜底跳过） | BE | 大 | - | PriceItem | 3 |
| DETECT-06-BE2 | 逐项相似度 + 分布模式比对（余弦相似度 + 趋势分析） | BE | 中 | - | PairComparison | 2 |
| DETECT-06-BE3 | LLM 合理性判断（L-6 prompt，区分定额标准 vs 串通） | BE | 中 | - | PairComparison | 2 |

### DETECT-07 图片复用 Agent `F-DA-05` `L-7`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| DETECT-07-BE1 | MD5 精确匹配 + pHash 模糊匹配（汉明距离<5） | BE | 中 | - | PairComparison, DocumentImage | 2 |
| DETECT-07-BE2 | LLM 通用性判断（L-7 prompt，通用素材 vs 应独立制作）+ 铁证升级 | BE | 中 | - | PairComparison | 2 |

### DETECT-08 语言风格 Agent `F-DA-06` `L-8`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| DETECT-08-BE1 | TF-IDF 预过滤通用段落 + 抽样 5-10 段 | BE | 中 | - | DocumentText | 1 |
| DETECT-08-BE2 | LLM 两阶段分析（L-8：每投标人风格特征提取→全局比较，>20人自动分组） | BE | 大 | - | PairComparison | 3 |

### DETECT-09 软件特征 Agent `F-DA-07`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| DETECT-09-BE1 | 元数据字段精确匹配 + 白名单过滤（纯程序，无 LLM） | BE | 小 | - | PairComparison, DocumentMetadata | 2 |

### DETECT-10 操作时间 Agent `F-DA-08`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| DETECT-10-BE1 | 滑动窗口聚集检测（默认30分钟窗口，≥3投标人）+ 非工作时间占比 | BE | 中 | - | OverallAnalysis, DocumentMetadata | 2 |

### DETECT-11 报价规律性 Agent `F-DA-09`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| DETECT-11-BE1 | 等差/等比/百分比数列检验（R²>0.95 触发） | BE | 中 | - | OverallAnalysis, PriceItem | 2 |

### DETECT-12 接近限价 Agent `F-DA-10`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| DETECT-12-BE1 | 偏离度方差统计（98%-100%区间，方差趋近零触发） | BE | 小 | - | OverallAnalysis, PriceItem | 2 |

### DETECT-13 综合评分与研判 `F-RP-01` `4.4.1`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| DETECT-13-BE1 | Pair 评分（加权公式）+ 铁证直判 + Project 评分（max pair + overall bonus） | BE | 中 | - | PairComparison, OverallAnalysis | 3 |
| DETECT-13-BE2 | LLM 综合研判（输入预聚合摘要→输出风险结论 2-3 段）+ 兜底 | BE | 大 | - | AnalysisReport | 3 |
| DETECT-13-BE3 | AnalysisReport 创建 + Project 状态→completed | BE | 小 | - | AnalysisReport, Project | 2 |

### DETECT-14 超时与兜底 `US-5.4`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| DETECT-14-BE1 | Agent 超时控制（5分钟/Agent，30分钟/全局）+ Process.kill() 强制回收 | BE | 中 | - | AgentTask | 3 |
| DETECT-14-BE2 | LLM 调用重试（超时30秒，重试2次）+ 失败降级策略 | BE | 中 | - | - | 3 |

---

## 模块 6: 报告与结果 (REPORT)

### REPORT-01 报告总览 `US-6.1` `F-RP-02`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| REPORT-01-BE1 | GET /api/projects/{pid}/reports 接口（报告列表含版本/风险等级/状态） | BE | 小 | GET /api/projects/{pid}/reports | AnalysisReport | 1 |
| REPORT-01-BE2 | GET /api/projects/{pid}/reports/{ver} 接口（完整报告数据 + 维度得分汇总） | BE | 中 | GET /api/projects/{pid}/reports/{ver} | AnalysisReport, PairComparison, OverallAnalysis | 3 |
| REPORT-01-BE3 | GET /api/projects/{pid}/reports/{ver}/matrix 接口（投标人×投标人风险矩阵） | BE | 小 | GET /api/projects/{pid}/reports/{ver}/matrix | PairComparison | 2 |
| REPORT-01-FE1 | 报告页面（/projects/:id/report/:version）Tab 1 概要：风险徽章 + LLM 结论 + 雷达图 + 热力图 + 汇总表 | FE | 大 | 上述3个 API | - | 8 |

### REPORT-02 维度明细 `US-6.2`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| REPORT-02-BE1 | GET /api/projects/{pid}/reports/{ver}/dimensions/{dim} 接口（区分 pair/overall 响应格式） | BE | 中 | GET /api/projects/{pid}/reports/{ver}/dimensions/{dim} | PairComparison, OverallAnalysis | 3 |
| REPORT-02-FE1 | Tab 2 维度明细：Master-Detail 布局（左侧维度列表 + 右侧详情面板） | FE | 中 | 上述 API | - | 7 |

### REPORT-03 投标人对比详情 `US-6.3`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| REPORT-03-BE1 | GET /api/projects/{pid}/reports/{ver}/pairs 接口（?bidder_a=&bidder_b=） | BE | 小 | GET /api/projects/{pid}/reports/{ver}/pairs | PairComparison | 2 |
| REPORT-03-FE1 | Tab 3 投标人对：下拉选择 + 维度得分表 + 对比/查看操作链接 | FE | 中 | 上述 API | - | 5 |

### REPORT-04 检测日志 `US-6.4`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| REPORT-04-BE1 | GET /api/projects/{pid}/reports/{ver}/logs 接口 | BE | 小 | GET /api/projects/{pid}/reports/{ver}/logs | AgentTask | 1 |
| REPORT-04-FE1 | Tab 4 检测日志：时间线表格 + 状态筛选 + 展开详情 | FE | 中 | 上述 API | - | 5 |

### REPORT-05 人工复核 `US-6.5` `F-RP-05`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| REPORT-05-BE1 | POST /api/projects/{pid}/reports/{ver}/review 接口（风险等级调整 + 复核意见） | BE | 小 | POST /api/projects/{pid}/reports/{ver}/review | AnalysisReport | 4 |
| REPORT-05-FE1 | 复核弹窗（风险等级下拉 + 意见文本域）+ 复核状态展示 | FE | 小 | 上述 API | - | 3 |

### REPORT-06 Word 导出 `US-6.6` `F-RP-04`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| REPORT-06-BE1 | GET /api/projects/{pid}/reports/{ver}/export 接口（python-docx 生成 DOCX：封面+概要+维度详情+复核记录） | BE | 大 | GET /api/projects/{pid}/reports/{ver}/export | AnalysisReport, PairComparison, OverallAnalysis | 5 |
| REPORT-06-FE1 | "导出 Word"按钮 + 浏览器下载触发 | FE | 小 | 上述 API | - | 2 |

---

## 模块 7: 对比视图 (COMPARE)

### COMPARE-01 文本对比 `US-7.1` `F-CV-01`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| COMPARE-01-BE1 | GET /api/projects/{pid}/compare/text 接口（段落 + 相似度匹配数据，支持 version 参数） | BE | 中 | GET /api/projects/{pid}/compare/text | DocumentText, PairComparison | 2 |
| COMPARE-01-FE1 | 文本对比页面（/projects/:id/compare/text）：左右分栏、同步滚动、相似段落高亮、角色切换 | FE | 大 | 上述 API | - | 6 |

### COMPARE-02 报价对比 `US-7.2` `F-CV-02`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| COMPARE-02-BE1 | GET /api/projects/{pid}/compare/price 接口（对齐后报价项 + 偏差计算，支持 version 参数） | BE | 中 | GET /api/projects/{pid}/compare/price | PriceItem, PairComparison | 2 |
| COMPARE-02-FE1 | 报价对比页面（/projects/:id/compare/price）：逐项对比表格、偏差色标、排序 | FE | 中 | 上述 API | - | 5 |

### COMPARE-03 元数据对比 `US-7.3` `F-CV-03`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| COMPARE-03-BE1 | GET /api/projects/{pid}/compare/metadata 接口（全投标人元数据矩阵 + 白名单标记，支持 version 参数） | BE | 小 | GET /api/projects/{pid}/compare/metadata | DocumentMetadata | 2 |
| COMPARE-03-FE1 | 元数据对比页面（/projects/:id/compare/metadata）：矩阵表格、匹配高亮、白名单标灰 | FE | 中 | 上述 API | - | 5 |

---

## 模块 8: 管理后台 (ADMIN)

### ADMIN-01 用户列表 `US-8.1`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| ADMIN-01-BE1 | GET /api/admin/users 接口（用户列表，不含密码） | BE | 小 | GET /api/admin/users | User | 2 |
| ADMIN-01-FE1 | 用户管理页面（/admin/users）：表格 + 搜索 | FE | 小 | GET /api/admin/users | - | 2 |

### ADMIN-02 创建用户 `US-8.2`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| ADMIN-02-BE1 | POST /api/admin/users 接口（用户名唯一、密码规则校验） | BE | 小 | POST /api/admin/users | User | 4 |
| ADMIN-02-FE1 | 创建用户表单弹窗 | FE | 小 | POST /api/admin/users | - | 2 |

### ADMIN-03 禁用/启用用户 `US-8.3`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| ADMIN-03-BE1 | PATCH /api/admin/users/{id} 接口（is_active/role 修改，不可禁用自己） | BE | 小 | PATCH /api/admin/users/{id} | User | 3 |
| ADMIN-03-FE1 | 用户行操作按钮（禁用/启用切换、角色修改） | FE | 小 | PATCH /api/admin/users/{id} | - | 1 |

### ADMIN-04 规则配置 `US-9.1` `F-AM-02`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| ADMIN-04-BE1 | GET/PUT /api/admin/rules 接口（JSON 配置读写 + 校验：权重非负、区间连续等） | BE | 中 | GET /api/admin/rules, PUT /api/admin/rules | SystemConfig | 5 |
| ADMIN-04-BE2 | 系统启动时加载默认配置（初始化写入 SystemConfig 表） | BE | 小 | - | SystemConfig | 1 |
| ADMIN-04-FE1 | 规则配置页面（/admin/rules）：JSON 配置表单 + 恢复默认按钮 | FE | 中 | GET/PUT /api/admin/rules | - | 3 |

---

## 模块 9: 技术基础设施 (INFRA)

### INFRA-01 数据库模型与迁移 `TS-4`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| INFRA-01-BE1 | SQLAlchemy 模型定义（14 张表：User, Project, Bidder, BidDocument, DocumentText, DocumentMetadata, PriceItem, DocumentImage, PairComparison, OverallAnalysis, AnalysisReport, AgentTask, PriceParsingRule, SystemConfig） | BE | 大 | - | 全部14张表 | 5 |
| INFRA-01-BE2 | Alembic 初始迁移脚本（upgrade/downgrade） | BE | 小 | - | - | 3 |

### INFRA-02 异步任务基础设施 `TS-1`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| INFRA-02-BE1 | asyncio + ProcessPoolExecutor 封装（create_task / run_in_executor） | BE | 中 | - | - | 2 |
| INFRA-02-BE2 | 超时机制（asyncio.wait_for + Process.kill() 强制回收僵尸进程） | BE | 中 | - | - | 2 |
| INFRA-02-BE3 | 进程重启恢复逻辑（扫描并修复 parsing/analyzing 异常状态） | BE | 中 | - | Project, Bidder, BidDocument, AgentTask | 4 |

### INFRA-03 SSE 推送基础设施 `TS-2`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| INFRA-03-BE1 | GET /api/projects/{pid}/events SSE 端点（EventSourceResponse，parse_progress/agent_status/report_ready） | BE | 中 | GET /api/projects/{pid}/events | - | 4 |
| INFRA-03-BE2 | GET /api/projects/{pid}/analysis/status 快照接口（SSE 重连恢复用） | BE | 小 | GET /api/projects/{pid}/analysis/status | AgentTask | 2 |
| INFRA-03-FE1 | EventSource 客户端封装（连接/断线重连/事件分发/状态恢复） | FE | 中 | 上述2个 API | - | 3 |

### INFRA-04 LLM 统一适配层 `TS-3`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| INFRA-04-BE1 | 模型无关调用接口（llm.chat → LLMResponse，支持 OpenAI 兼容 API） | BE | 中 | - | - | 2 |
| INFRA-04-BE2 | 重试机制（超时30秒，重试2次）+ JSON 容错解析 | BE | 中 | - | - | 3 |
| INFRA-04-BE3 | API Key 环境变量加载 + Prompt 模板管理（Python 模块/YAML） | BE | 小 | - | - | 2 |

### INFRA-05 前端基础设施 `TS-5`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| INFRA-05-FE1 | 路由配置（react-router-dom，11个页面路由表） | FE | 小 | - | - | 1 |
| INFRA-05-FE2 | UI 框架集成（Ant Design 主题配置 + 全局 Layout：左侧导航可收起+内容区） | FE | 中 | - | - | 3 |
| INFRA-05-FE3 | 状态管理（zustand）+ API 客户端封装（axios baseURL/拦截器/错误处理） | FE | 中 | - | - | 3 |
| INFRA-05-FE4 | 图表库集成（ECharts：雷达图 + 热力图） | FE | 小 | - | - | 1 |

### INFRA-06 数据生命周期管理 `TS-6`

| 编号 | 任务 | 归属 | 工作量 | 关联 API | 关联表 | AC数 |
|------|------|------|--------|---------|--------|------|
| INFRA-06-BE1 | 定时清理任务（每日执行，清理超过 N 天的原始文件，保留数据库记录） | BE | 中 | - | BidDocument | 4 |
| INFRA-06-BE2 | 清理日志记录 + 文件过期后下载返回"已清理"提示 | BE | 小 | - | - | 2 |

---

## 汇总统计

### 按模块汇总

| 模块 | 功能项 | 任务数 | BE任务 | FE任务 | 小 | 中 | 大 |
|------|--------|--------|--------|--------|---|---|---|
| AUTH 认证与授权 | 4 | 12 | 6 | 6 | 7 | 4 | 1 |
| PROJ 项目管理 | 4 | 10 | 4 | 6 | 4 | 4 | 2 |
| FILE 投标人与文件 | 7 | 16 | 9 | 7 | 8 | 6 | 2 |
| PARSE 文档解析 | 5 | 17 | 17 | 0 | 6 | 7 | 4 |
| DETECT 检测执行 | 14 | 25 | 25 | 0 | 4 | 12 | 9 |
| REPORT 报告与结果 | 6 | 14 | 7 | 7 | 5 | 4 | 5 |
| COMPARE 对比视图 | 3 | 6 | 3 | 3 | 1 | 4 | 1 |
| ADMIN 管理后台 | 4 | 9 | 5 | 4 | 6 | 2 | 1 |
| INFRA 技术基础设施 | 6 | 16 | 12 | 4 | 5 | 9 | 2 |
| **合计** | **53** | **125** | **88** | **37** | **46** | **52** | **27** |

### 工作量估算

| 工作量等级 | 任务数 | 参考人日范围 | 估算总人日 |
|-----------|--------|-------------|-----------|
| 小 (S) | 46 | 1-2 | 46-92 |
| 中 (M) | 52 | 3-5 | 156-260 |
| 大 (L) | 27 | 5-10 | 135-270 |
| **合计** | **125** | - | **337-622** |

> 注：以上为纯开发工作量估算，不含项目管理、联调、部署、文档编写等非开发工作。实际项目周期需在此基础上乘以 1.3-1.5 的管理系数。
