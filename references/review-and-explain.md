# 第二轮审校、详细解读与原文溯源

## 详细程度与解读归属

`explanation` 是直觉摘要，`analysis` 承担详细讲解。方法段一般用 3—5 个有实质内容的层次，可按“这段解决什么 → 一步步机制 → 具体例子 → 为什么这样设计 → 与前后文的联系及局限”展开；普通段通常 2—3 个层次。核心段可写约 200—500 个汉字或更多，取决于复杂度，不能把字数当作质量保证。过渡句不制造不存在的方法，确需简短时用 `detail_note` 说明。

```json
"analysis": [{
  "label": "机制如何工作", "basis": "author",
  "text": "结合该段实际内容解释输入、操作、输出和逻辑关系。",
  "evidence": [{"paragraph_id": "p00001", "quote": "a continuous verbatim English excerpt"}]
}, {
  "label": "直观例子", "basis": "analogy",
  "text": "明确是辅助类比，不冒充作者做过的实验或已有证据。"
}]
```

`basis` 取 `author`（论文内容）、`analogy`（辅助类比）、`inference`（延伸推论）、`reader_note`（阅读提示）。每段至少一个 `author` 解读并附真实原文引句；`author` 条目必须有 `evidence`。其他类型可附动机来源，一旦填写也会检查引文存在。每个引句必须是指定段落的连续原文片段，不接受凭记忆改写或拼接引文。数学 token 可保留，或使用保护项的原文文本；优先引用完整文字句。

引文存在只能证明可定位，不能自动证明其支持整个解读。第二轮要检查是否省略限制或把相关性说成因果。类比中的具体数字如非原文，应显式注明“假设示例”。

## 规则提示与第二轮语义审校

默认用 `workflow.py export reading.json --stage review --out 当前审校批.json` 读取本批原文、当前译文、解读及规则提示，按 [高效分批流程](efficient-workflow.md) 写回。`audit.py reading.json` 的全量工作单仍可用，但不必每批读取整篇。先重新对照原文和译文，再审查解释；不要沿用首轮结论直接填表。修订后由 apply 计算最终 digest；直接编辑 JSON 时则从重新导出的工作单取得最新 digest。digest 只是版本绑定，不是模型已审校的证明。有效审校可复用，内容改变后的旧记录不能直接重签。

逐段填写：

```json
"review": {
  "method": "model_second_pass", "status": "reviewed",
  "digest": "copy the current digest after actual review",
  "checklist": {
    "meaning": "本段具体主语、操作和结论是否完整，记录核对发现。",
    "negation": "具体哪处否定已保留；没有否定也说明。",
    "conditions": "具体条件、适用范围及例外是否保留。",
    "numbers": "核对本段实际数字、单位、分母、对照对象及增幅。",
    "terms": "列出本段关键术语及使用的认可译法。",
    "claims": "核对可能性、因果强度及分析条目的证据边界。"
  },
  "decisions": [{"id": "f...", "resolution": "accepted", "reason": "此提示是合法表达差异的具体原因。"}],
  "changes": [{
    "before": "修订前的有问题译文片段", "after": "当前译文中的修订后片段",
    "reason": "错误类型及改动理由", "source_quote": "exact original excerpt"
  }]
}
```

六项结论须针对该段，不能全填“已检查”“通过”。数字规则比较阿拉伯数值集合和常见单位，可能因图号、省写、中文数词或等价单位产生差异；不能据此自动裁决翻译正确性。术语规则使用当前文章词表，不采用固定领域译法。

当前规则提示逐条处理：修正实际错误后重跑工作单；误报记录 `accepted` 和理由；确实未能判断记录 `open`，且段落 `status` 为 `needs_check`。已解决的错误用 `changes` 保留前后对照。没有发现错误时允许空 `changes`，不能为展示功能编造修改记录。任何待核对问题都须在交付中披露。

## 图表与公式精读

对支撑主要结论的图表与关键公式先查看原图/原式。长原式不送去翻译。只是一两个变量的记号通常在段落里解释，不为每个变量建立一张卡片；`protected` 数学项可设 `detail_required` 明确是否需要独立精读。独立公式、结构复杂的关键表达通常需要。不能用 `false` 绕过关键公式解读。

```json
"visuals": [{
  "id": "v001", "kind": "formula", "title": "式（1）：目标函数",
  "paragraph_ids": ["p00003"], "protected_key": "M1", "pages": [3],
  "summary": "先用一句话说明它计算什么以及为何需要。",
  "details": [
    {"role": "purpose", "label": "解决什么问题", "text": "在方法中的位置及用途。"},
    {"role": "symbols", "label": "每个量的含义", "text": "输入、优化变量、常量、取值范围及单位；未报告则说明。"},
    {"role": "mechanism", "label": "一步步怎么理解", "text": "项与项如何作用、参数改变会怎样；不要补造推导。"},
    {"role": "boundary", "label": "成立条件与误解", "text": "所需假设、与相似公式区别以及不能得出的结论。"}
  ],
  "evidence": [{"paragraph_id": "p00003", "quote": "exact original excerpt"}]
}]
```

图解 `kind: figure` 的四类必需 `role` 为 `axes`、`setup`、`observations`、`boundary`；表格 `kind: table` 为 `headers`、`setup`、`observations`、`boundary`。分别说明坐标/图例/表头、比较设置与预算、实际趋势/数字、结果能支持和不能支持什么。示意图没有坐标轴时说明结构含义，不编造轴。图表可用 `image` 指向阅读包内 PNG/JPEG/WebP/GIF，渲染时内嵌；无法取得图像时提供来源页码，不声称已看图。

`paragraph_ids` 可关联正文或 reference 项；`protected_key` 仅用于正文中被保护的公式。提取器标有 `visual_kind` 的独立图表/公式需有对应卡片。源文件保留、解释和证据锚点必须指向同一版本。

## 科研视角卡片

`research_card` 必须含以下七个列表，每项为 `{"text": "具体说明", "basis": "author 或 inference 等", "evidence": [...]}`：

- `problem`：实际研究问题、现有方法的具体缺口。
- `contributions`：新增了什么，对比对象是谁；增量改进与核心贡献分开。
- `assumptions`：算法、数据、环境、标注和部署的前提；是否使用特权状态。
- `evidence`：关键实验/论据、基线、消融、公平性、样本数及统计支持；非实验文章按论证方式分析。
- `limitations`：作者承认的限制与读者推断分开，说明失败条件和未验证的泛化。
- `costs`：人工示范、标注、环境交互、计算和复现资源分别讨论；未给出的数字标明未报告。
- `connections`：结合 `research_focus` 或对话中的研究方向，提出可检验想法，写明改变什么、控制什么、评价指标及预期失败条件，标为推论，不冒充论文结论。

所有卡片项带可定位原文动机。“原文未报告”是阅读提示，不假造引句证明全文不存在；引用最相关段落并说明检查范围。没有实验时不虚构实验、基线或 GPU 成本。v2 的每项 `overview` 同样增加 `basis` 和 `evidence`，详细串联问题、方法、证据与局限，不仅重复摘要。交付前连同图表和科研卡片一起重新对照来源，不能只检查翻译。
