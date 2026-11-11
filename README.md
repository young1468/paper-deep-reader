# Paper Deep Reader · 论文精读阅读器

将论文或长文章整理成简洁的中文精读 HTML，把**完整原文、中文翻译和详细解读**放在同一页，支持逐自然段连续阅读。

这是一个供 Codex 等支持 `SKILL.md` 的助手使用的 skill。翻译与语义解读由当前模型完成，Python 脚本负责提取、分批处理、校验和排版；它不是运行一个 Python 命令就能独立完成翻译的应用，也不需要另外配置模型 API Key。

## 功能

- **自然段双语对照**：按章节 / Part 组织，跨页续句合并，页码仅用于回查原文。
- **详细通俗解读**：章节导读、逐段直觉说明、机制、例子、前提、误解和结论边界。
- **文章专属术语**：中文名、英文名、直观含义及上下文作用，支持认可别名和排除译法。
- **公式与图表精读**：保留原式和图像，独立解释符号、机制、比较设置和证据边界。
- **科研阅读卡片**：研究问题、贡献、假设、证据、局限、成本与研究衔接。
- **第二轮对照审校**：分别记录语义、否定、条件、数字单位、术语和主张强度，展示真实修订和待核对问题。
- **原文溯源**：关键解释附可定位引文，检查原文版本、来源覆盖及审校是否过期。
- **离线阅读**：HTML 内嵌样式、脚本和图片，支持章节目录、搜索、中文 / 双语切换、解读开关、窄屏布局和打印。

支持文本 PDF、HTML、Markdown、TXT。文章链接需要助手先取得并保存正文；扫描 PDF 需要先 OCR，脚本不内置 OCR 服务。

## 安装与使用

将仓库安装到客户端的 skills 目录。Codex 的常见用户级路径是 `$CODEX_HOME/skills/paper-deep-reader`，未设置 `CODEX_HOME` 时通常为 `~/.codex/skills/paper-deep-reader`。

例如，使用默认路径的 PowerShell 用户可以运行：

```powershell
git clone https://github.com/young1468/paper-deep-reader.git "$env:USERPROFILE\.codex\skills\paper-deep-reader"
```

macOS / Linux 的默认路径示例：

```bash
git clone https://github.com/young1468/paper-deep-reader.git ~/.codex/skills/paper-deep-reader
```

如目标目录已有同名 skill，先保留已有修改，再决定如何更新；无需覆盖正在使用的阅读包。

让客户端识别该 skill 后，在对话中提供论文文件或可获取正文的文章链接，并输入：

> 使用 $paper-deep-reader，为这篇论文生成详细中文精读 HTML，包含全文原文对照、逐段解读、术语解释、关键图表公式、科研阅读卡片和第二轮审校。

也可以补充研究方向、阅读范围或希望重点解释的知识。默认处理正文及附录中的叙述段落。

## Python 环境

Python 3.10+。PDF 提取需要 `pdfplumber`，HTML 提取需要 `lxml`；渲染、分批工具及审校使用标准库。

```bash
python -m pip install -r requirements.txt
```

已有运行环境时直接复用；只处理 Markdown / TXT 时，不需要安装 PDF / HTML 提取依赖。

## 工作流程

以下命令在仓库根目录执行。内容字段的完整格式见 [内容格式](references/content-format.md)，语义加工标准见 [审校与解读](references/review-and-explain.md)。

```bash
# 1. 提取原文并创建待完成的阅读包；输出目录须为新目录
python scripts/prepare.py article.pdf --out output/article

# 2. 查看进度，导出待加工的小批完整自然段
python scripts/workflow.py status output/article/reading.json
python scripts/workflow.py export output/article/reading.json --stage draft --out output/article/current-batch.json

# 3. 模型完成该批翻译和解读，按约定生成增量补丁后写回
python scripts/workflow.py apply output/article/reading.json output/article/current-patch.json

# 4. 首轮全文完成后，另做第二轮逐段对照审校
python scripts/workflow.py export output/article/reading.json --stage review --out output/article/current-review.json
python scripts/workflow.py apply output/article/reading.json output/article/review-patch.json

# 5. 所有批次、图表及阅读卡片完成后严格校验并渲染
python scripts/render.py output/article/reading.json
```

`prepare.py` 只生成草稿，不生成完整翻译。上述第 2–4 步需要逐批继续，直到约定范围完成。也保留完整工作单和只检查入口：

```bash
python scripts/audit.py output/article/reading.json
python scripts/render.py output/article/reading.json --check-only
```

## 降低重复上下文

默认每批最多 12 段、约 24000 字符，按复杂度缩小；单段超预算仍保留完整段落。只读取本批及相关术语、必要邻段，写回时不重复输出整篇原文和 JSON。

已完成且仍有效的审校可复用；修改后的段落重新核对，术语表变化仍会触发原有审校失效规则。脚本不会自动编造审校结论，也不会因为规则没有提示就认定翻译正确。

分批不会清除聊天历史，也不保证固定的 token 节省比例。具体补丁格式、恢复流程和边界见 [高效分批流程](references/efficient-workflow.md)。

## 阅读包与质量边界

生成的目录包含原文副本、`source.json`、`reading.json`、`论文精读.html`、检查报告及审校报告；公式和图表可附相对路径图片。`source.json` 保留初次提取基线，不能为了通过覆盖检查而改写。

结构、引文定位、数字和术语规则只能辅助发现问题，不能自动证明语义或科学解释正确。第二轮是当前模型分开的对照审校，不声称由独立模型或人工完成；无法判定的问题以 `needs_check` 明确保留。关键数据、公式和研究结论应回查同版本原文。

仓库只包含 skill 源码与使用说明，不包含论文全文、个人阅读包、会话日志或凭据。使用者应确认自己有权处理所提供的文章。

## 目录

```text
SKILL.md                 助手执行入口
agents/openai.yaml       skill 显示名称与默认提示
assets/                  离线阅读器 CSS / JavaScript
references/              内容格式、审校及高效分批说明
scripts/prepare.py       原文提取
scripts/workflow.py      进度、批次导出和增量写回
scripts/audit.py         规则提示与二轮审校检查
scripts/render.py        严格校验与 HTML 渲染
```
