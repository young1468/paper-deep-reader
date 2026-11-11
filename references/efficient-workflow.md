# 高效分批：保留全部内容与检查

目标是减少每次请求携带的历史原文、报告和重写内容，而非减少最终解读。工具不调用翻译服务或模型 API，不添加并行代理。

## 先确定结构，再做内容

1. 提取一次。按 Part 检查结构、自然段、跨页拼接及公式标记，保留不可改的 `source.json`。先处理会改变段落 ID 的结构问题，不到最后才重排。
2. 浏览标题、摘要、方法和结论，建立本篇术语及别名；尚不清楚的含义记录为疑点。术语表不是不可改，只是应尽量在第二轮之前稳定。当前 digest 绑定完整词表，后改词表必须真实重审受绑定影响的记录，不能自动重签旧审校。
3. 图表按所需页码一次渲染、逐张观察并保存，后续复用同一版本裁图。不要重复输出截图或 base64。正文批处理不重新查看无关图表。

## 小批读取、只写变化

脚本相对于 skill，`book` 为阅读包目录。命令输出只含进度或路径；读取导出的批次文件即可。

```text
python scripts/workflow.py status book/reading.json
python scripts/workflow.py export book/reading.json --stage draft --part s003 --out book/current-batch.json
python scripts/workflow.py apply book/reading.json book/current-patch.json
```

`status` 列出章节和未完成/审校过期 ID，不携带整篇内容。默认导出尚未完成的叙述段，最多 12 段，整个工作包预算约 24000 字符（不是 token）；可用 `--limit`、`--max-chars` 调整。预算计入本批有关术语、章节导读和边界相邻段。单段超预算时完整导出并标记 `oversize_single_paragraph`，绝不截断一句话。空批次表示此阶段没有符合条件的段落；用 status 确认下一阶段。

每个批次带原文版本、完整词表的摘要哈希，以及每段的 `base_digest`。模型只提供以下增量补丁，摘要值从本批原样复制，或用本地代码拼装，不能凭空重算：

```json
{
  "stage": "draft",
  "document_digest": "从批次复制",
  "glossary_digest": "从批次复制",
  "updates": [{
    "id": "p00001",
    "base_digest": "从该段复制",
    "set": {
      "translation": "该段完整译文",
      "explanation": "具体直觉摘要",
      "analysis": ["依审校与解读格式填写的对象列表"],
      "terms": ["t1"]
    }
  }]
}
```

这是字段示意，`analysis` 需实际对象，不是示意字符串。不重复输出 `original`、`protected`、`source_ids`、其他段落或既有图片。`apply` 只允许改译文、解读、术语引用、简短段说明；结构修订另做有针对性的本地编辑。原文版本、词表或该段在导出后改变会拒绝写回；整批失败则不改文件。可只提交批次中实际处理的部分段落。

章节导读、全局术语、overview、visuals、research_card 在本地对相应字段定点写回，不重新生成整份 JSON；全局组件仍须完成并对照原文审阅。不要在工具输出中打印整份字典。JSON 序列化、段落查找、哈希、图片嵌入都交给脚本。

## 第二轮仍覆盖每段

首轮全文完成后另行审校，不在生成同一段的同时认定其已审过：

```text
python scripts/workflow.py export book/reading.json --stage review --out book/current-review.json
python scripts/workflow.py apply book/reading.json book/review-patch.json
```

只读本批。重新对照原文、译文和解读，填写六类具体判断；逐条处理 flags，必要时查看实际 PDF 页或用 ID 定点补取上下文。补丁仍用 `updates[].set`，stage 改为 `review`，其中必须有真实的 `review`；可同时包含本次修正的内容字段。无需手写 `review.digest`，apply 用修正后的内容计算；其余 method/status/checklist/decisions/changes 全由实际审校提供。六项标准、证据检查及原有严格校验保持不变。修改译文必须记录本次真实的 before/after、原因与原文依据。

已有效审校的段落（包括明确保留的 `needs_check`）默认不再发送。确需回看用 `--ids p00001,p00002`；这会显式重开指定段落。过期或不完整审校仍会列为待办；自动哈希计算不构成审校。完整 `audit.py` 命令和旧 v1/v2 渲染入口均保持可用。

六类判断简明而具体，不机械复述整段译文；修订记录引用实际有问题的最小完整片段。修订完成一批就保存，再取下一批。可在同一次工具调用中顺序执行“应用已完成补丁 → 导出下一批 → 读取下一批”；写回失败就停止，不能继续使用旧状态。不要为每个 JSON 查找或哈希单独发起模型往返。无新变化时不重复读旧批次或全量审校报告。跨段疑点只补读相关段落；多篇逐篇闭环，避免三个全文同时常驻上下文。恢复时先 status；保留的阅读包、当前批次和已记录疑点就是检查点，无需把全过程复制到新提示中。

如果当前聊天已有大量旧任务历史，分批工具不能清除模型上下文；新论文适合由用户在新聊天调用 skill。不要擅自新建聊天或派代理来改变运行方式。

## 最终验收与统计

全文覆盖、引文定位、公式/图表、七项科研卡片、二轮审校及离线阅读控件仍按原流程检查。先修确实阻塞的问题，重新检查相关项；不能把叙述段改成 reference 来减少任务。不要在已有检查通过且内容不变时反复生成/检查所有文件。

字符/字节减少只衡量工具数据量，不能当作端到端 token 节省比例。若需要实际用量，使用本次任务的 usage 记录，区分缓存输入、非缓存输入和输出；推理子项不重复相加。无新论文完整运行的测量，就不声称已验证耗时或总 token 降幅。
