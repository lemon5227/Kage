# E3.0-B 不可变恢复模块与云生成接口

日期：2026-10-01。本包完成源码生成/加载接口，真实云pilot由下一包记录。

问题：只有恢复hook不足以证明下一代执行了新代码。实现：manifest v1新增modules.recovery，固定recover(error, history, checkpoints)入口并校验源码SHA256；加载和每次执行都校验。已有沙箱运行器通过固定adapter执行源码，在临时scratch目录返回决策；实际任务文件动作仍经AgenticLoop/ToolExecutor。记录原模块绝对路径、源码/adapter/实际合并源码hash、Docker镜像ID、输入、返回值、恢复actor与错误；cache identity包含模块和运行器设置。

云生成复用E1 Mutator的预算预留/结算、最多3次提案/格式修复、持久attempt、重启缓存与不可变bundle。抽取消息/发布/父包校验三个扩展点，RecoveryMutator只替换恢复源码及manifest指针，保留全部技能；没有创建另一套评分或晋级器。候选仅允许stop/switch_tool，本包尚未提供replan/rollback等动作。

测试先因缺模块失败，再验证真实源代码返回write_file产生14、实际读回、hash/actor贯穿链；篡改拒绝；scratch写文件不写到任务目录；错误签名被修复且两个请求均计费；重读提案不重复付费；父包/非空技能源码与digest不变；隐藏expected不进入生成输入。ProcessSkillRunner只用于可信测试，真实生成实验指定Docker。

验证：相关29 passed；空闲全量`python -m pytest -q`，834 passed、1 skipped、1 xfailed（64.10秒），`git diff --check`通过。实际云生成与独立父子/新变体结果尚未产生，不将本包测试成绩称为真实自修改收益。
