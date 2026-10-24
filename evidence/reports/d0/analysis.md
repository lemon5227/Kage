# D0：命令行优先 + 文档定位（Kage 应用端到端，2026-10-24）

**设置**：Kage 后端纯文字模式（`KAGE_TEXT_ONLY=1`）+ 本地 Agents-A1-4B（llama-server，16k），通过 WebSocket 像前端一样发消息；TextEdit 里打开 4 个测试文档（`~/.kage/desktop/demo/`，测试内容，非真实数据）。同一会话连续 10 条请求（改错字 / 追加行 / 读内容 / 改一句 / 删一行）。记录：`d0-dialog.txt`、`d0-tools.txt`、`final-documents.txt`。

| 版本 | 结果 | 失败方式 |
|---|---|---|
| 第 1 版（`desktop_task` 支持 TextEdit） | 改错字失败 | 模型没给文档名；`exec` 4 次 `open -a TextEdit /Users/yourname/Documents/...`（编造路径） |
| 第 2 版（+`open_documents`、`doc_read/replace/append_lines`，界面工具去掉 TextEdit） | 10 条里 ≈ 2 条做成，一次声称“已添加”但文件未变 | 看到“打开的”就调 `exec open -a …`，路径照样编；二十多个工具里挑不准 |
| **第 3 版（服务端先查出已打开文档的真实路径附在请求后；文档类请求只给文档工具）** | **9/10 完全正确**（第 6 条署名“Best regards,”少了逗号），**0 次编造路径、0 次虚报** | — |

**结论**：与 C4（显式写出复选框状态）和 G0（按行编辑）是同一个规律——**把小模型需要的信息直接放到它面前、把工具面收窄到这件事**，比在说明里提醒它“不要猜路径”有效得多。命令行优先的分工：辅助功能接口只负责“定位”（读窗口的 `AXDocument`），读写走可撤销的文件工具。
