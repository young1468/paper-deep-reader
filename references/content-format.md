# 输入、依赖与内容格式

`prepare.py` 支持本地 `.pdf`、`.html/.htm`、`.md/.markdown`、`.txt`。链接由调用者用可用工具获取并保存，再通过 `--source-url` 记录来源。不会执行网页脚本。扫描件先 OCR；提取器不内置 OCR 服务。

Python 3.10+；PDF 提取使用 `pdfplumber`，HTML 使用 `lxml`；其余操作和渲染仅依赖标准库。优先使用已有环境，缺依赖时只安装实际输入所需包。

```text
python scripts/prepare.py article.pdf --out output/article
python scripts/audit.py output/article/reading.json
python scripts/render.py output/article/reading.json
python scripts/render.py output/article/reading.json --check-only
```

默认用 `workflow.py status/export/apply` 分批加工及审校，见 [高效分批流程](efficient-workflow.md)。以上全量 audit/render 命令保持兼容。分批工具只组织工作和写回当前字段，不替代任何内容质量校验。

## reading.json

提取器生成结构完整、内容待补全的草稿。直接编辑它即可。

```json
{
  "schema_version": 2,
  "title": "Article title",
  "source": {"file": "原文.pdf", "sha256": "...", "url": "", "version": ""},
  "notes": ["阅读范围与公式处理说明"],
  "warnings": [],
  "overview": [{"title": "核心问题", "text": "具体、可核查的整体解读"}],
  "research_focus": "可根据当前用户研究方向填写",
  "visuals": [],
  "research_card": {},
  "glossary": [{
    "id": "t1", "term": "sample efficiency", "translation": "样本效率",
    "explanation": "达到指定表现所需的样本量；此文具体统计的是……"
  }],
  "parts": [{
    "id": "s001", "title": "1 Introduction", "title_zh": "1 引言",
    "level": 2, "guide": "本节的问题、主线和阅读要点。",
    "paragraphs": [{
      "id": "p0001", "source_ids": ["p0001"], "kind": "paragraph",
      "original": "The policy uses [[M1]] ... [[C1]]",
      "translation": "策略使用 [[M1]]……",
      "explanation": "该段的直观含义、机制与上下文联系。",
      "analysis": [], "review": {},
      "terms": ["t1"], "pages": [2, 3],
      "protected": {
        "M1": {"kind": "math", "text": "a_t"},
        "C1": {"kind": "citation", "text": "(Smith et al., 2025)"}
      }
    }]
  }]
}
```

上例是待补全草稿的结构示意。v2 的 `analysis`、`review`、`visuals` 和 `research_card` 依照 [review-and-explain.md](review-and-explain.md) 补齐后才能生成成品；不应把空对象当作完成内容。

- `original` 是完整原文，不是摘要；`translation` 为完整译文；`explanation` 是辅助解读。三者不能互相替代。中文原文可将 `translation` 填为忠实的中文整理，并在说明中注明。
- `parts` 可整理成合理章节，主章节 `level: 2`，小节 `3`。文档 ID 唯一，`terms` 只能引用文章 `glossary` 中的 ID。
- `source_ids` 表示本段覆盖哪些初次提取的段落。`source.json` 保存基线，不改动它；每个来源 ID 必须且只能覆盖一次。合并跨页段落时合并 ID，重命名冲突的数学 token。OCR、断词和元信息修正记入 `notes`。
- `kind: "reference"` 用于作者元信息、独立公式、表格、代码、参考文献等，保留 `original`、`source_ids` 和页码，不强制译文/解读。不要为了通过检查把未翻译叙述段标为 reference。
- `protected` 的 key 不带方括号；正文用 `[[M1]]` 等 token。数学项可增加 `mathml` 字符串或同目录图片相对路径 `image`；渲染器清理 MathML 并将图片内嵌 HTML。`text` 是无结构化表示时的原式。无法可靠抽取就链接 PDF 页，不能猜公式。
- 人名和引文可用 `kind: "name"`、`kind: "citation"` 保护。中文可省略引文 token，使用则按原拼写还原。术语词义写入 `glossary`。
- 术语可增加 `aliases_en`、`aliases_zh`（认可别名列表）及 `avoid_zh`（明确排除译法列表），数字和有单位的量尽量用阿拉伯数字保持易核对。规则差异可能是合法表达，须在审校中解释，不能为了消除提示篡改原文含义。
- 图表数值、伪代码默认在原文核对。可在解读中描述已核实的趋势和条件，不把图注碎片混入正文。

## 段落修复与检查

页面不是段落边界：上一页末尾的未完成句子应与下一页/栏续句合并；两段中间隔着公式也不等于同一段。`pages` 保留所有涉及页码。

双栏、标题、数学字体识别只做辅助。先抽查第一页、随机一页和正文末页，在模型整理时处理异常换行、图表和脚注。低文字密度触发警告，扫描件不会得到虚假的完整译稿。

渲染前检查内容、来源覆盖、原文哈希、保护标记、资源、引文片段及第二轮审校是否绑定当前内容；缺项返回非零，不写成品。数字/单位/术语规则只提示疑点，六类语义判断由模型另行完成，检查记录不等于保证科学解释正确。旧 `schema_version: 1` 保持兼容，但页面标明未进行二轮审校。
