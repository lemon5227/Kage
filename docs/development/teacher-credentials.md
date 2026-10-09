# 教师模型私有配置

DeepSeek教师配置的规范位置为 **`~/.config/kage/teachers/deepseek.json`**；本机完整路径`/Users/wenbo/.config/kage/teachers/deepseek.json`。配置包含`model.cloud_api`，由已有客户端读取；不把key复制到仓库的公开`config/settings.json`、报告、冻结文件或聊天。

2026-10-09已从主checkout的`artifacts/private/deepseek-settings.json`迁移，内容保持。规范文件权限0600，teachers目录0700。旧绝对路径`/Users/wenbo/Kage/artifacts/private/deepseek-settings.json`现为指向规范文件的兼容符号链接，旧实验脚本仍可读取。活动worktree不必复制凭据；使用同一个用户级完整路径。

G1配置文件的`teacher_settings`填写规范路径；实际运行仍须明确的费用/请求预算，凭据存在不代表无限调用授权。当前G1已由用户授权最多6次教师请求、按配置计费上限0.03美元，不能扩大或重新索要相同授权。

后续模型先检查此位置。只输出存在、是否配置、模型名称和权限等元数据，不打印配置全文/key。缺失时再请求配置位置，不默认要求用户重新发送key。其他机器需要自行准备私有配置，不通过Git传播。
