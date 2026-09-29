# Kage 自演化技能系统架构设计提案
## 基于前沿论文（CoEvoSkills / ToolSmith / MUSE-Autoskill）的即插即用技能生态设计

**文档版本**：v1.0  
**日期**：2026-09-29  
**状态**：架构提案（等待外部模型与专家交叉评审）  
**目标系统**：Kage 个人桌面智能体助手  

---

## 1. 背景与核心诉求

### 1.1 现状与痛点
在当前的很多 AI Agent 框架（包括 Kage 现存实现）中，Agent 的工具库主要由开发者在编译期或配置期静态硬编码（如内置的搜索、天气、文件读写、音频播报等工具）。
当用户提出复合型、定制化或领域专用的任务时（例如：“每次我提供一个股票代码，自动抓取其最新报价、换手率并计算持仓印花税”），传统系统面临以下困境：
1. **多轮推理开销大**：每次请求都必须通过多步 Agentic Loop 临时编写代码或临时调用多项基础工具，耗费大量 Token 且延迟极高。
2. **缺乏资产沉淀能力**：执行完成后无法将成功经验固化为可复用的工具，下一次遇到完全相同的任务仍需从零推理。
3. **缺乏代码安全自检**：Agent 临时写的脚本若存在语法错误或边界 Bug，会导致当前对话崩溃，无法在运行时自主修复并安全上线。
4. **无法即插即用（Hot-Plugging）**：即使人工编写了新工具，往往需要重启服务进程才能在注册表中生效。

### 1.2 核心愿景
使 Kage 具备**“自己给自己写代码、写技能，自测闭环，即插即用（无需重启）”**的自主演化能力：
* **Autonomous Skill Authoring**：Agent 能根据用户需求或高频操作，自动提炼并编写 Python 技能代码。
* **Co-Evolutionary Verification**：Agent 编写技能的同时，自动编写对应的验证测试用例，并在沙箱中隔离运行，具备基于 Traceback 的自我修复（Self-Repair）能力。
* **Zero-Downtime Hot-Plugging**：通过测试的技能立即动态载入当前运行时，并向 `ToolRegistry` 注册，当前轮次或同会话后续步骤即可无缝调用。
* **Persistent Assets**：以标准化格式持久化在本地文件系统，系统重启时自动恢复挂载。

---

## 2. 理论前沿与学术论文支撑 (Literature Review)

本设计建立在 2025–2026 年大模型自演化智能体领域的多项代表性前沿研究之上：

### 2.1 CoEvoSkills (COLM 2026)
* **论文标题**：*Self-Evolving Agent Skills via Co-Evolutionary Verification* (arXiv:2604.01687)
* **核心思想**：Agent 单向生成代码往往不可靠，必须引入“协进化验证闭环（Co-Evolutionary Verification）”。
* **机制拆解**：
  * **Skill Generator（技能生成器）**：负责生成包含执行逻辑与元数据的多文件技能包；
  * **Surrogate Verifier（伴随验证器）**：独立为生成的技能编写可执行断言与自测用例（Executable Checks）；
  * **Generate ➔ Verify ➔ Refine 循环**：在沙箱中运行测试，测试未通过时捕获运行时栈信息（Diagnostic Feedback）促使 Generator 自动修复。**仅当测试 100% 通过后，技能才被允许交付并载入生产环境。**

### 2.2 ToolSmith (AAAI 2026 / IBM, EMNLP 2026)
* **论文标题**：*ToolSmith: A Multi-Agent Framework for Enterprise Tool Creation*
* **核心思想**：超越传统的 LATM（LLMs as Tool Makers），实现端到端的闭环工具创建与沙箱修复。
* **机制拆解**：
  * **AST 语法安全性审查**：自动校验生成代码的抽象语法树（AST），拦截未受限的反射、高危系统命令及非预期网络调用；
  * **函数签名反射**：通过类型注解（Type Hints）与 Docstrings 自动推导标准 OpenAI / Anthropic Function Calling JSON Schema，保证模型原生兼容。

### 2.3 SOP 编译与常驻工具化 (EMNLP 2026 Industry)
* **论文标题**：*Tool-Making and Self-Evolving LLM Agents in Low-Latency Systems*
* **核心思想**：**标准操作规程（SOP）的代码编译**。
* **实测效益**：当 Agent 发现多步执行轨迹模式重复时，自主将其“固化编译”为本地 Tool 原子。实测将复合任务的 p50 延迟降低 42%~62%，显著削减端侧与云端模型开销。

### 2.4 MUSE-Autoskill (arXiv:2605.27366)
* **论文标题**：*MUSE-Autoskill: Self-Evolving Agents via Skill Creation, Memory, Management, and Evaluation*
* **核心思想**：将技能视作**长期演化的数字资产**，建立技能全生命周期管理模型：`Creation ➔ Memory ➔ Management ➔ Evaluation ➔ Hot-Reload`，支持动态评级与老化淘汰。

### 2.5 现代通用 Skill 标准规范 (Manus 2.0 / Cue & Antigravity)
* **结构规范**：以 `SKILL.md` 结合执行脚本的形式，提供人类可读、Agent 易解析的标准化文档与代码接口。

---

## 3. Kage 现有系统基座分析与改造契机

| Kage 核心组件 | 当前实现状态 | 改造为自演化技能系统的契机 |
| :--- | :--- | :--- |
| **`ToolRegistry`** | 集中式工具字典，具备 `register(tool_def)` 与 `_schemas_cache = None` 缓存失效机制。 | **原生支持热插拔**：只要有新函数载入内存，调用 `register()` 即可立即生效，无需重构底层注册逻辑。 |
| **`PromptBuilder`** | 每轮对话前通过 `tool_registry.get_all_schemas()` 拉取最新工具。 | **即时感知**：新注册工具在下一轮对话或同轮次迭代中立即可见。 |
| **`ToolExecutor`** | 通过 `registry.get_handler(name)` 动态寻址并分发工具。 | **无缝调用**：新工具无需硬编码分支，自动遵循统一的错误处理与审计日志。 |
| **`skill_ops.py`** | 目前仅能保存 Markdown 文本（`skills_save_local`）或调用外部 `npx skills`。 | **关键改造点**：需升级为支持 Python 动态加载、安全沙箱检验与生命周期管理的完整子系统。 |

---

## 4. 详细技术方案设计

### 4.1 技能包组织标准 (`skills/custom/{skill_name}/`)
每一个由 Kage 自主生成或用户放入的技能，必须是一个标准目录：
```text
skills/custom/
└── stock_calc/
    ├── SKILL.md            # 元数据说明、意图触发关键词、JSON Schema 参数定义
    ├── handler.py          # 核心执行函数 (定义 entrypoint: run(**kwargs))
    └── test_handler.py     # 伴随生成的验证用例 (通过 assert 进行测试)
```

**`SKILL.md` 格式规范示例**：
```markdown
---
name: stock_calc
description: 查验股票实时价格并估算持仓市值和税费。当用户想要计算股票收益或税费时触发。
safety_level: SAFE
author: kage-autonomous-agent
created_at: 2026-09-29T20:30:00Z
parameters:
  type: object
  properties:
    symbol:
      type: string
      description: 股票代码，例如 AAPL, 600519
    shares:
      type: integer
      description: 持仓股数，默认 100
      default: 100
  required:
    - symbol
---

# stock_calc 技能说明
本技能由 Kage 自主演化生成，用于结合实时行情与公式估算持仓。
```

---

### 4.2 沙箱与伴随自测执行器 (`core/skill_sandbox.py`)
为落实 CoEvoSkills 与 ToolSmith 提出的安全与验证规范，创建沙箱检验模块：

```python
import ast
import subprocess
import sys
import tempfile
import os

class SkillSandboxValidator:
    """技能静态安全审查与子进程自测执行器"""

    FORBIDDEN_MODULES = {"ctypes", "pty", "subprocess", "socket", "resource"}
    FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__"}

    @classmethod
    def static_security_check(cls, code: str) -> tuple[bool, str]:
        """基于 AST 的静态语法与安全检查"""
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, f"SyntaxError: {e}"

        for node in ast.walk(tree):
            # 阻断高危 import
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split('.')[0] in cls.FORBIDDEN_MODULES:
                        return False, f"安全拦截: 禁止导入高危模块 {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.split('.')[0] in cls.FORBIDDEN_MODULES:
                    return False, f"安全拦截: 禁止从高危模块 {node.module} 导入"
            # 阻断动态执行函数
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in cls.FORBIDDEN_CALLS:
                    return False, f"安全拦截: 禁止调用高危动态执行函数 {node.func.id}"

        return True, ""

    @classmethod
    def run_isolated_verification(cls, code: str, test_code: str, timeout_sec: int = 8) -> tuple[bool, str]:
        """在独立临时子进程中执行自测验证用例"""
        sec_ok, sec_msg = cls.static_security_check(code)
        if not sec_ok:
            return False, sec_msg
        
        test_sec_ok, test_sec_msg = cls.static_security_check(test_code)
        if not test_sec_ok:
            return False, f"测试脚本未通过安全校验: {test_sec_msg}"

        with tempfile.TemporaryDirectory() as tmpdir:
            handler_path = os.path.join(tmpdir, "handler.py")
            test_path = os.path.join(tmpdir, "test_handler.py")

            with open(handler_path, "w", encoding="utf-8") as f:
                f.write(code)
            
            # 测试脚本引用当前目录的 handler
            test_runner_script = f"import sys; sys.path.insert(0, '{tmpdir}');\n{test_code}"
            with open(test_path, "w", encoding="utf-8") as f:
                f.write(test_runner_script)

            try:
                proc = subprocess.run(
                    [sys.executable, test_path],
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                    cwd=tmpdir,
                )
                if proc.returncode == 0:
                    return True, "All tests passed successfully."
                else:
                    return False, f"Test failed with exit code {proc.returncode}:\nStdout: {proc.stdout}\nStderr: {proc.stderr}"
            except subprocess.TimeoutExpired:
                return False, f"Execution timed out ({timeout_sec}s). Possible infinite loop."
            except Exception as e:
                return False, f"Execution exception: {e}"
```

---

### 4.3 动态热装载管理器 (`core/dynamic_skill_loader.py`)
负责在运行时使用 Python 标准库 `importlib.util` 将合法的技能模块注入 `ToolRegistry`：

```python
import os
import re
import yaml
import importlib.util
import logging
from typing import Optional
from core.tool_registry import ToolRegistry, ToolDefinition

logger = logging.getLogger(__name__)

class DynamicSkillLoader:
    """动态技能热装载与生命周期管理器"""

    def __init__(self, registry: ToolRegistry, base_dir: str = "skills/custom"):
        self.registry = registry
        self.base_dir = os.path.abspath(base_dir)
        os.makedirs(self.base_dir, exist_ok=True)
        self._loaded_modules: dict[str, object] = {}

    def load_skill_from_disk(self, skill_name: str) -> tuple[bool, str]:
        """从指定目录动态热加载技能并注册到 ToolRegistry"""
        skill_dir = os.path.join(self.base_dir, skill_name)
        skill_md = os.path.join(skill_dir, "SKILL.md")
        handler_py = os.path.join(skill_dir, "handler.py")

        if not os.path.exists(skill_md) or not os.path.exists(handler_py):
            return False, f"技能文件缺失: {skill_dir}"

        # 1. 解析 SKILL.md Frontmatter 元数据
        try:
            with open(skill_md, "r", encoding="utf-8") as f:
                content = f.read()
            match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
            if not match:
                return False, "SKILL.md 缺少有效的 YAML Frontmatter 头部"
            meta = yaml.safe_load(match.group(1))
        except Exception as e:
            return False, f"解析元数据失败: {e}"

        # 2. 动态编译加载 Python 模块
        try:
            module_name = f"kage_skills_{skill_name}"
            spec = importlib.util.spec_from_file_location(module_name, handler_py)
            if spec is None or spec.loader is None:
                return False, "无法创建模块加载器"
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            entry_func = getattr(module, "run", None)
            if not entry_func or not callable(entry_func):
                return False, "handler.py 必须导出一个可调用的 run(**kwargs) 入口函数"
        except Exception as e:
            return False, f"加载模块异常: {e}"

        # 3. 构造 ToolDefinition 并动态注册进 ToolRegistry
        tool_def = ToolDefinition(
            name=meta.get("name", skill_name),
            description=meta.get("description", "Dynamic Custom Skill"),
            parameters=meta.get("parameters", {"type": "object", "properties": {}}),
            handler=entry_func,
            safety_level=meta.get("safety_level", "SAFE"),
        )
        self.registry.register(tool_def)
        self._loaded_modules[skill_name] = module
        logger.info(f"动态技能 [{skill_name}] 热加载成功并已注册进 ToolRegistry")
        return True, f"技能 {skill_name} 加载注册成功"

    def scan_and_load_all(self) -> int:
        """系统启动时全量恢复加载所有自定义技能"""
        count = 0
        if not os.path.exists(self.base_dir):
            return count
        for item in os.listdir(self.base_dir):
            item_path = os.path.join(self.base_dir, item)
            if os.path.isdir(item_path):
                ok, _ = self.load_skill_from_disk(item)
                if ok:
                    count += 1
        return count
```

---

### 4.4 Agent 核心元工具 (`skill_create_and_register`)

将“技能编写与演化”封装为 Agent 原生工具：
```python
def skill_create_and_register(
    skill_name: str,
    description: str,
    parameters_schema: dict,
    code: str,
    test_code: str,
) -> str:
    """Agent 用于自己给自己编写新技能并即插即用生效的元工具。
    
    执行步骤：
    1. 触发沙箱安全性检查与独立子进程自测；
    2. 若自测失败，捕获错误栈并立即返回报错，促使 Agent 自我修复；
    3. 若自测通过，自动在 skills/custom/{skill_name}/ 目录写入 SKILL.md 与 handler.py；
    4. 动态载入 Python 内存并调用 ToolRegistry 注册；
    5. 当前及后续对话轮次即可像原生工具一样调用该新技能。
    """
```

---

## 5. 真实场景端到端演练示例

**场景**：用户对 Kage 说：
> “每次我给你一个股票代码，你帮我从网络查最新价，并按 100 股估算市值和 0.05% 印花税。以后这个功能就叫 `stock_calc`。”

### 内部执行序列：
1. **意图判断**：Kage 检索自身工具库，发现没有现成的 `stock_calc` 工具。
2. **触发元工具**：调用 `skill_create_and_register`，参数如下：
   * `skill_name`: `"stock_calc"`
   * `description`: `"根据股票代码获取最新价格并计算持仓市值与印花税"`
   * `parameters_schema`: `{"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}`
   * `code`:
     ```python
     import json
     from core.tools.web_ops import tinyfish_search

     def run(symbol: str) -> str:
         # 借助内置基础搜索原子获取行情
         res = tinyfish_search(f"{symbol} 股票最新价格", max_results=1)
         # 模拟解析逻辑与财务计算
         mock_price = 100.0  # (根据真实抓取解析)
         shares = 100
         market_val = mock_price * shares
         stamp_duty = market_val * 0.0005
         return json.dumps({
             "symbol": symbol,
             "price": mock_price,
             "market_value": market_val,
             "stamp_duty": stamp_duty
         })
     ```
   * `test_code`:
     ```python
     import handler
     import json

     res = json.loads(handler.run("AAPL"))
     assert "market_value" in res, "必须返回 market_value"
     assert res["market_value"] == 10000.0, "持仓市值计算不符"
     assert res["stamp_duty"] == 5.0, "印花税计算不符"
     ```
3. **沙箱检验与自愈**：
   * `SkillSandboxValidator.run_isolated_verification` 执行 `test_code`，返回 `All tests passed`。
4. **持久化与热插拔注入**：
   * 写入 `skills/custom/stock_calc/`（含 `SKILL.md` 与 `handler.py`）；
   * `DynamicSkillLoader.load_skill_from_disk("stock_calc")` 触发，注册进 `ToolRegistry`；
   * `ToolRegistry` 缓存失效，`get_all_schemas()` 立即包含 `stock_calc`。
5. **即时调用**：在同一次对话任务的下一迭代步，Kage 直接执行刚刚生成的 `stock_calc(symbol="AAPL")`，并回复用户最终计算结果。

---

## 6. 潜在风险与防御策略 (Risks & Mitigations)

1. **恶意/高危代码注入与越权**：
   * **防御**：AST 静态白名单限制模块引入；子进程沙箱执行自测；`safety_level` 限制为 `SAFE` 隔离操作。
2. **死循环与资源耗尽**：
   * **防御**：子进程必须配置强硬的 `timeout` 熔断机制（默认 8 秒），超时直接终止并反馈超时原因。
3. **工具膨胀与 Context 污染**：
   * **防御**：借鉴 MUSE-Autoskill 与 Cue 的 Progressive Disclosure 原则，只在有相关关键词触发或高置信匹配时，将自定义技能的完整 Schema 动态合并至 `PromptBuilder`。

---

## 7. 外部交叉验证评审意见与架构修订补丁

> 评审基于 2026-09-29 可核验的论文、官方文档及 Kage 当前代码。论文中的任务成功率或延迟收益不能直接推算为 Kage 的上线效果。本节提出的是架构修订要求，代码为接口设计示例，尚未在 Kage 中实现或验证。

### 1. 2025–2026 最新相关文献补充与技术对标

| 来源与证据状态 | 可借鉴机制 | 提案中的缺口 |
| --- | --- | --- |
| [CoEvoSkills（COLM 2026）](https://arxiv.org/abs/2604.01687) | 生成器与不接触真实答案的伴随验证器协同迭代，验证对象是多文件技能包。 | `code` 与 `test_code` 由同一次创建调用提交，缺少验证者独立性及防止测试迎合实现的机制。论文也未证明“自测 100% 通过即可安全上线”。 |
| [ToolSmith（AAAI 2026）](https://ojs.aaai.org/index.php/AAAI/article/view/42388) | 从 API 规格和需求生成工具；用自然语言测试、沙箱执行及对有状态 API 的结果查询做闭环验证。 | 当前示例只检查返回字段与固定数值，不验证外部数据来源、状态变更和工具描述是否与行为一致。提案将 AST 审查归为其核心安全保证，公开论文摘要不足以支持这一推论。 |
| [Tool-Making and Self-Evolving LLM Agents in Low-Latency Systems（EMNLP 2026 Industry，待刊）](https://arxiv.org/abs/2607.08010) | 从重复轨迹提炼、验证并版本化工具，在运行时调用，异常时回退。论文报告工具调用使其生产场景 p50 延迟下降 **42%**；另一次架构消融再报告 **62%**。 | 提案缺少“何时值得固化为技能”的成本门槛、基线对照、版本回退及数据漂移监测；两个百分比不能合并表述为 Kage 的预计收益。 |
| [MUSE-Autoskill（2026 预印本，仍在评审）](https://arxiv.org/abs/2605.27366) | 技能目录、逐技能经验记忆、使用反馈、评估和修订形成生命周期。 | 当前设计只有创建、测试、加载，缺少使用记录、失败归因、淘汰、合并与回归评估。 |
| [AIDE²（2026 预印本）](https://arxiv.org/abs/2609.26457) | 候选修改在固定预算与隐藏评估上比较，仅保留优于现有版本的修改。 | “测试通过”只表示候选满足有限断言，不能表示比旧版更好；应增加旧版对照和保留集评估。其研究对象是研究智能体脚手架，不能当作桌面技能热加载的安全证明。 |
| [ToolRet（2025）](https://arxiv.org/abs/2503.01763) 与 [自适应工具短名单研究（2026）](https://arxiv.org/abs/2605.24660) | 工具检索本身需要单独评测；短名单深度应随查询变化。 | §6 只有关键词或“高置信匹配”的原则，没有召回率、误召回率、“无合适工具”判断与短名单预算。 |
| [轨迹污染研究（2026）](https://arxiv.org/abs/2608.05563) 与 [EVOMAL（2026）](https://arxiv.org/abs/2608.25776) | 自演化系统会把不可信轨迹或已有技能中的恶意模式固化、复制到后续技能。 | 缺少来源标记、信任等级、技能间复制审查，以及“外部内容不得升级为系统指令”的边界。两项均为预印本，其具体攻击成功率不应外推至 Kage。 |

[CodeAct](https://arxiv.org/abs/2402.01030) 是 2024 年的代码动作基础研究，可支持“代码可组合工具”的动机，不能支持“生成代码可以在桌面主进程安全执行”的结论。[Agent Skills 开放格式](https://github.com/agentskills/agentskills/blob/main/docs/home.mdx)和 [Manus 的技能说明](https://help.manus.im/en/articles/14753565-how-to-share-and-use-skills-in-manus)支持按需披露技能说明；它们没有给任意 `handler.py` 赋予可信执行权。Manus/Cascade/Cue 的产品说明也不足以推断其内部隔离与热更新实现。

### 2. 当前方案的致命隐患与工程死角分析

**P0：验证边界在正式加载时失效。** `SkillSandboxValidator` 仅在临时子进程运行测试；`DynamicSkillLoader` 随后在 Kage 主进程调用 `spec.loader.exec_module(module)`。模块顶层代码在注册前即会执行，`run()` 调用时也拥有 Kage 进程的文件、网络、环境变量及内存权限。`tempfile`、`cwd`、`subprocess.run(timeout=8)` 均不是权限隔离。AST 禁止名单容易漏掉对象属性调用、间接导入、第三方库及文件操作。`safety_level: SAFE` 又来自技能自身元数据，不能作为授权依据。**必须取消主进程导入自生成代码；验证和正式调用应使用同一受约束执行边界。**

**P0：依赖安装是另一条代码执行路径。** 若允许技能自行 `pip install`，构建后端、安装产物和原生扩展都可能执行代码；每个技能直接修改主环境还会造成版本冲突和不可复现。虚拟环境只能隔离 Python 包，不能限制文件或网络权限。应由可信依赖服务解析、审查、锁定并安装到每版本独立环境，执行时仍置于系统级沙箱。[uv 的哈希校验与禁止构建选项](https://docs.astral.sh/uv/reference/cli/)可作为实现组件，但不能代替沙箱。

**P0：目录与注册存在越权入口。** `skill_name` 未严格约束时可形成路径穿越；符号链接和“校验后替换文件”会使测试对象与加载对象不同。当前 `ToolRegistry.register()` 对同名工具直接覆盖；自生成技能若取内置工具名，可改变既有行为。`get_security_level()` 对不存在的工具返回 `SAFE`，与“未知即拒绝”的要求相反。元数据中的描述也可能成为提示注入载体。必须固定命名空间、拒绝覆盖内置工具、对整个技能包做内容摘要，并将被验证的不可变摘要传到执行端。

**P1：热更新不具有事务语义。** `importlib` 重载不会自动重绑外部持有的函数引用，旧对象可能继续存活；重载也不是线程安全操作，[Python 文档明确列出这些限制](https://docs.python.org/3/library/importlib.html)。现有注册表的 Schema 缓存失效只处理一次字典覆盖，没有保证并发对话中的“所见 Schema”与“实际执行版本”一致。`ToolExecutor` 的模糊名称缓存也可能在工具集变化后保留旧映射。必须使用不可变版本和原子活动指针；对话开始时固定目录快照，执行调用固定版本号，旧任务完成后退出旧工作进程。

**P1：测试通过不等于事实正确。** `stock_calc` 示例用固定 `mock_price=100.0`，却描述为“最新价格”；测试只重复这一假设。外部行情失败、延迟、币种、时间戳及税费适用条件均未覆盖。生成器可同时写实现和断言，极易让错误实现通过自写测试。应分别设置作者测试、独立生成的对抗测试、人工或可信来源的保留用例；验证真实外部能力时使用可记录回放的服务替身，生产结果标明来源和时间。

**P1：工具数量增长会同时损害检索与调用。** 将所有 Schema 放入 Prompt 会增加上下文成本和误选；只靠关键词又会漏掉改写、跨语言及组合意图。需要独立的技能目录、混合检索与重排、动态短名单，并允许路由器回答“没有合适技能”。评估至少记录 Recall@k、误路由率、无工具判定准确率、最终任务成功率、token 与延迟。

### 3. 具体修改方案与追加补丁设计（Appendable Amendments）

#### 3.1 修订后的执行与发布路径

```mermaid
flowchart LR
    A[任务轨迹或用户需求] --> B[技能候选生成]
    B --> C[独立验证器与保留用例]
    C --> D[依赖预检与锁定]
    D --> E[不可变技能包<br/>内容摘要]
    E --> F[受约束沙箱：测试]
    F --> G[旧版对照与发布门禁]
    G --> H[原子切换活动版本]
    H --> I[技能目录与检索器]
    I --> J[每轮固定的工具短名单]
    J --> K[ToolExecutor 固定版本调用]
    K --> L[受约束沙箱：正式执行]
    L --> M[审计、反馈、漂移检测]
    M --> B
    L --> N[按能力授权的可信服务代理]
```

**信任边界：** Kage 主进程只保存元数据、路由和结果；技能代码、测试代码与依赖均在受约束工作进程中运行。工作进程默认无用户主目录、凭据、Kage 源码、宿主进程环境变量及网络访问。确需网络或文件能力时，通过可信服务代理授予具体域名、路径、操作和额度。macOS 桌面版应实现并验证专用受限 helper 或虚拟机后端；Linux 可采用具备只读文件系统、非特权身份、系统调用限制、进程与资源上限的容器后端。[Docker 文档](https://docs.docker.com/engine/containers/resource_constraints)指出容器默认没有资源上限，不能只写“使用容器”而省略配置。若当前平台没有已验证的强制隔离后端，自动生成技能保持为**不可执行候选**。

#### 3.2 技能包、依赖与发布契约

```text
skills/custom/stock_calc/
├── revisions/
│   └── <sha256>/
│       ├── SKILL.md
│       ├── manifest.json       # 名称、版本、参数、输出、能力请求
│       ├── handler.py
│       ├── requirements.lock  # 精确版本和产物哈希
│       └── tests/
│           └── author_test.py
└── active.json                # 仅保存当前摘要；原子替换
```

- 技能名限定为 `custom.[a-z][a-z0-9_]{0,63}`；禁止与内置工具重名。目录读取拒绝符号链接、超限文件及非预期文件。摘要覆盖代码、元数据、锁文件和测试清单。
- 依赖预检只接受声明的包及精确版本；默认拒绝 VCS、可编辑、本地路径、直接 URL、源代码分发包及安装脚本。可信服务先获取并审查 wheel，记录哈希、许可证、漏洞结果、Python/平台兼容性，再离线安装到该版本的独立环境。依赖变更生成新技能版本，绝不修改运行中的环境。
- `SKILL.md` 是不可信内容；`safety_level` 不再由作者填写。能力授权由 Kage 的可信策略层决定，并记录授予原因、有效期和调用额度。
- 发布门禁至少包括：语法及 Schema 校验、作者测试、独立保留测试、权限拒绝测试、旧版回归对照、外部调用回放测试。任何单一测试集的“100% 通过”都不是上线充分条件。

#### 3.3 关键接口重构示例

以下接口明确了调用链中的责任分界；`SandboxBackend` 必须由平台后端真正实施权限和资源限制，不能用普通 `subprocess` 充当实现。

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol
import threading


@dataclass(frozen=True)
class SkillRevision:
    name: str
    digest: str
    bundle_dir: Path
    schema: Mapping[str, Any]
    environment_id: str
    granted_capabilities: frozenset[str]


class DependencyPreflight(Protocol):
    def prepare(self, bundle: Path) -> str:
        """校验锁文件和产物哈希；返回独立、不可变的环境 ID。
        解析和安装均不得修改 Kage 的 Python 环境。
        """


class SandboxBackend(Protocol):
    def verified(self) -> bool: ...
    def invoke(
        self,
        revision: SkillRevision,
        arguments: Mapping[str, Any],
        *,
        timeout_s: int,
        output_limit_bytes: int,
    ) -> Mapping[str, Any]:
        """使用 revision.digest 对应的只读包和隔离环境执行。
        能力由可信服务代理实施；不得继承宿主凭据和任意网络。
        """


class VersionedSkillManager:
    def __init__(self, backend: SandboxBackend):
        self._backend = backend
        self._lock = threading.RLock()
        self._active: dict[str, SkillRevision] = {}

    def snapshot(self) -> dict[str, SkillRevision]:
        # PromptBuilder 在一轮对话开始时获取一次，并随工具调用保存摘要。
        with self._lock:
            return dict(self._active)

    def activate(
        self,
        candidate: SkillRevision,
        *,
        expected_digest: str | None,
    ) -> None:
        if not self._backend.verified():
            raise RuntimeError("没有可用的强制隔离后端")
        with self._lock:
            current = self._active.get(candidate.name)
            actual = current.digest if current else None
            if actual != expected_digest:
                raise RuntimeError("技能版本已变化；重新验证后再发布")
            self._active = {**self._active, candidate.name: candidate}

    def invoke(
        self,
        pinned: SkillRevision,
        arguments: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        # 不在锁内运行代码；旧调用继续使用其固定版本。
        return self._backend.invoke(
            pinned, arguments, timeout_s=8, output_limit_bytes=65536
        )
```

`activate()` 还须在持久层使用原子文件替换或数据库事务同步活动摘要；启动恢复时重新核验摘要、依赖环境与发布记录。执行端按摘要管理工作进程：新版本启动并健康检查后切换，旧版本等待已开始的调用结束，再终止进程。这样无需在 Kage 主进程执行 `importlib.reload()`，也不会依赖清理残留 Python 对象来完成更新。

#### 3.4 对 Kage 现有模块的最小改动边界

| 模块 | 必要改动 |
| --- | --- |
| `ToolRegistry` | 增加受保护的 `custom.` 命名空间和原子目录快照；拒绝覆盖内置工具。未知工具的安全等级改为拒绝态。不要让技能元数据直接决定安全等级。 |
| `PromptBuilder` | 每轮从固定目录快照经检索器选取少量 Schema；记录所选技能摘要。提供“没有合适技能”和扩大检索深度的路径。 |
| `ToolExecutor` | 用名称、固定摘要、参数共同寻址；参数和结果按 Schema 校验。注册表代数变化时清空模糊匹配缓存，或禁止对动态技能做模糊执行。 |
| `skill_ops.py` | 将“保存 Markdown”和“安装可执行技能”分为不同操作；创建调用只提交候选，不直接注册。 |
| `skill_sandbox.py` | AST 检查保留为快速拒绝规则；真正的安全门禁移至平台强制隔离后端，并对验证与生产调用使用同一策略。 |

#### 3.5 上线验收条件

1. 用无网络、无文件授权的恶意测试技能验证：读取用户目录、读取环境凭据、建立外联、启动子进程均被执行后端阻断；超时、内存、输出及子进程数量上限可测。
2. 并发执行旧版时发布新版：旧调用完成于旧摘要，新调用使用新摘要；发布失败或进程健康检查失败时活动指针保持旧版。
3. 修改任一已验证文件或依赖产物：摘要校验失败，不能加载；同名内置工具及路径穿越名称均被拒绝。
4. 使用包含正例、近义改写、跨语言、相似技能和“无合适技能”的检索集，报告 Recall@k、误路由率及最终成功率；短名单大小由测量结果确定。
5. 对股票示例移除 `mock_price` 的“实时价格”表述；只有返回可核验的价格、币种、市场、来源及采集时间，且明确税费规则来源与适用范围，才可作为真实行情技能发布。

**修订结论：** 提案目前具备技能生成与注册流程草图，但“沙箱自测后主进程导入”使其核心安全承诺不成立。应先完成受约束执行、不可变版本、依赖锁定和原子发布，再开放自生成技能的运行时注册。
