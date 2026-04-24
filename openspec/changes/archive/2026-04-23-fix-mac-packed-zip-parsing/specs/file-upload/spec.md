## MODIFIED Requirements

### Requirement: 压缩包安全解压

系统 SHALL 在上传成功后异步解压压缩包,过程 MUST 防护 zip-bomb(总解压大小 ≤2GB / 文件总数 ≤1000 / 嵌套深度 ≤3)与 zip-slip(拒绝含 `..` / 绝对路径 / 解压后实际位置超出解压根目录的 entry)。压缩包内中文文件名 MUST 正确还原,覆盖 Windows 端常见 GBK 编码以及 macOS Archive Utility 端常见的"UTF-8 字节但未置 ZIP bit 11(UTF-8 flag)"场景。解压过程 MUST 识别并静默丢弃打包元数据垃圾文件(不产生 `bid_documents` 行),垃圾清单定义在 `app/services/extract/junk_filter.py`。损坏/空压缩包 MUST 标 `parse_status=failed` + 可读 `parse_error`。

#### Scenario: 正常 ZIP 解压成功

- **WHEN** 解压一个正常 ZIP,含 docx / xlsx / jpg 混合文件
- **THEN** bidder `parse_status` 变为 `extracted`;`bid_documents` 表生成对应条数记录(不含任何打包垃圾占位行);`extracted/{pid}/{bid}/<archive>/` 下文件结构与 ZIP 内一致

#### Scenario: zip-slip 恶意 entry 被跳过

- **WHEN** ZIP 含一个 entry 路径为 `../../etc/passwd`
- **THEN** 该 entry 不解压到 `extracted/` 外;`bid_documents` 记录包含一条 `parse_status=skipped` + `parse_error="路径不安全,已跳过"` 的条目;其他正常 entry 照常解压

#### Scenario: 解压总大小超 2GB 中断

- **WHEN** 压缩包声明或实际解压过程中总字节数超过 2GB
- **THEN** 中断解压;bidder `parse_status=failed`;`parse_error` 含"解压文件过大,超过 2GB 限制"

#### Scenario: 文件数超 1000 中断

- **WHEN** 压缩包含 >1000 个文件
- **THEN** 中断;`parse_status=failed`;`parse_error` 含"文件数超过 1000"

#### Scenario: 嵌套压缩包超 3 层

- **WHEN** ZIP 内包含嵌套 ZIP,递归深度达到第 4 层
- **THEN** 第 4 层不解压;`bid_documents` 记录一条 `parse_status=skipped` + `parse_error="嵌套层数超过 3"`;前 3 层正常解压

#### Scenario: GBK 中文文件名还原

- **WHEN** ZIP 中文件名使用 GBK 编码(而非 UTF-8 flag)
- **THEN** 解压后 `bid_documents.file_name` 字段为正确的中文字符串,非乱码

#### Scenario: macOS 打包 UTF-8 无 flag 文件名还原

- **WHEN** ZIP 文件名实为 UTF-8 字节但未置 ZIP bit 11(典型 macOS Archive Utility 输出),entry 名形如 `供应商A/江苏锂源一期...docx` 的 UTF-8 字节
- **THEN** 解压后 `bid_documents.file_name` 字段为正确的中文字符串,非 `Σ╛¢σ║öσòåA/...` 形式的乱码

#### Scenario: 损坏的 ZIP

- **WHEN** 上传损坏的 ZIP 文件(CRC 校验失败)
- **THEN** `parse_status=failed`;`parse_error="文件已损坏,无法解压"`

#### Scenario: 空压缩包

- **WHEN** 上传空 ZIP(无 entry)
- **THEN** `parse_status=failed`;`parse_error="压缩包内无有效文件"`

#### Scenario: 不支持的文件类型被标 skipped

- **WHEN** ZIP 内含 `.doc` / `.xls` / `.pdf` 文件
- **THEN** `bid_documents` 对应记录 `parse_status="skipped"` + `parse_error="暂不支持 X 格式"`;不报错,不中断其他文件

#### Scenario: macOS 打包垃圾被静默丢弃

- **WHEN** ZIP 含 `__MACOSX/` 目录下的任意 entry、以 `._` 开头的 AppleDouble 文件、或 `.DS_Store` 文件
- **THEN** 这些 entry 不写盘也不产生 `bid_documents` 行(静默丢弃),同 ZIP 内的真实业务文件正常解压

#### Scenario: Office 临时/锁文件被静默丢弃

- **WHEN** ZIP 含以 `~$` 开头(Word/Excel 打开锁文件)或 `.~` 开头(Office/WPS 崩溃残留)的 `.docx`/`.xlsx` 文件
- **THEN** 这些 entry 不写盘也不产生 `bid_documents` 行,同 ZIP 内的真实业务文件正常解压

#### Scenario: Windows 系统与编辑器元数据被静默丢弃

- **WHEN** ZIP 含 `Thumbs.db`(任意大小写)、`desktop.ini`、`.directory`,或 `.git/`、`.svn/`、`.hg/`、`__pycache__/`、`node_modules/`、`.idea/`、`.vscode/`、`$RECYCLE.BIN/`、`System Volume Information/` 中任一目录下的 entry
- **THEN** 这些 entry 不写盘也不产生 `bid_documents` 行

#### Scenario: 过滤统计留痕于归档行

- **WHEN** 一个 ZIP 内有 N 个 entry 被识别为打包垃圾静默丢弃(N>0)
- **THEN** 归档行(file_type 为压缩包后缀的 `bid_documents`)的 `parse_error` 或 summary 字段含"已过滤 N 个打包垃圾文件"文本,便于运维审计

#### Scenario: 7z/rar 路径也应用过滤

- **WHEN** 解压 7z 或 rar 压缩包,产物目录里出现打包垃圾文件(如嵌套的 macOS 打包 zip 经递归解压后落盘 `__MACOSX/` 产物)
- **THEN** `_walk_extracted_dir` 阶段识别并从磁盘删除这些垃圾文件,且不为它们产生 `bid_documents` 行

#### Scenario: 用户正常命名的文件不被误过滤

- **WHEN** ZIP 含 `my~dollar.docx`(`~` 在中间)、`my._file.docx`(`._` 在中间)、`.gitignore`(前缀不完全匹配 `.git/` 目录)、`README.md` 等
- **THEN** 这些文件按现有规则正常写 `bid_documents`,不被识别为垃圾
