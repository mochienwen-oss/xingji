# 行迹 Trip · 提示词目录

本目录存放模型提示词。运行时由后端读取纯文本，与动态上下文一起组装成 messages，交给 backend/services/llm.py 的 model_json(messages, max_tokens, on_reply) 调用；模型统一返回 JSON object。

## 目录

```text
backend/prompts/
├── static/
│   └── global.md              所有用户共享的静态系统提示：身份、语气、硬规则、安全
├── scenarios/
│   ├── explore_chat.md        探索页对话：理解意图、补表单
│   ├── plan_compose.md        只用候选 id 排每天行程
│   ├── preview_revise.md      预览行程的最小修改
│   ├── trip_revise.md         已保存行程的最小修改
│   ├── context_compress.md    9 字段上下文压缩
│   └── memory_extract.md      长期记忆提取
├── examples/
│   ├── explore_chat.md
│   ├── plan_compose.md
│   └── context_compress.md
└── README.md
```

## 静态与动态的边界

- static/ 和 scenarios/ 是**纯静态文本**：不得出现当前日期或时间、城市、用户名、trip_id、version、表单值、记忆内容、环境变量、密钥。
- 不得使用 {var}、{{var}}、${var} 这类占位符——没有模板引擎，写了会原样发给模型。
- 动态内容由代码在运行时作为**独立 system 消息**注入，例如（示意，实际值来自运行时）：
  {"当前北京时间":"2026-11-06 19:30 星期五","时区":"Asia/Shanghai","当前表单":{"city":"杭州","days":2},"行程":{"trip_id":123,"version":4},"记忆":[{"key":"pace_preference","value":"不喜欢赶"}]}
- examples/ 里的城市、日期、id 只是示例，不得被 prompt 当作默认值；场景文件要写「以系统提供的动态上下文为准」，不写死具体值。
- 公共规则只写在 global.md；场景文件不重复、不放松 global 的硬规则，只补充本场景的产物契约和判断规则。

## 加载方式（已接入）

- 编码 UTF-8（无 BOM）、换行 LF。Markdown 只是存放格式，运行时取原文，不渲染 Markdown。
- 组装顺序：global.md → scenarios/<name>.md（含 examples/<name>.md）→ 动态 system JSON → 对话消息；两段静态文本之间用一个空行连接。
- 实现位于 backend/services/harness/prompts.py：read_prompt 用 lru_cache 按文件名缓存，文件缺失返回空串；PromptRegistry.build 负责拼装，static_global 缺失时用内置兜底。planning.py 在场景文件缺失时回退到内联契约，不静默降级成空 prompt。
- 实际调用点：
  - explore_chat：backend/services/harness/orchestrator.py 的 _intake，动态 JSON 含表单、地点、摘要、长期记忆和时间。
  - plan_compose：backend/services/planning.py 的 generate_plan，动态 JSON 含需求、候选、当前行程、交通核验和长期记忆。
  - preview_revise / trip_revise：backend/services/planning.py 的 suggest_edits，按 mode 选择；已保存行程路径额外带 trip_id/version。
  - context_compress：backend/services/harness/context.py 的 compact。
  - memory_extract：backend/services/harness/memory/extractor.py 直接读取场景文件。
- 静态文本用 system role 发送，不要拼进 user 消息：拼进 user 会被当作用户内容，也会破坏前缀缓存。
- max_tokens 与场景匹配：意图抽取/规划对话 1200，上下文压缩与关键词抽取 2000，排程/改稿/预算使用 model_json 默认的 4000。输出被截断时 JSON 必然不完整，宁可让模型少写也不要超限。
- 修改 md 后需重启进程；不要在请求路径里读盘。

## JSON 契约与工程约束

| 文件 | 根字段 | 关键约束 | 调用时机 |
| --- | --- | --- | --- |
| global.md | 无独立输出 | 只约束，不定义 JSON | 每次模型调用前置 |
| explore_chat.md | reply / intent / form_patch / place_keywords / question | reply ≤120 字；keywords ≤3；intent ∈ plan/chat/clarify/revise | 探索页每轮消息 |
| plan_compose.md | days[].stops[] / summary | days 等于需求天数；每天 1–12 站；duration 15–480 整数 | 生成或重排预览 |
| preview_revise.md | reply / actions[] | actions ≤20；day、position 从 1 开始 | 预览页修改 |
| trip_revise.md | reply / actions[] | 同上；保留手动编辑 | 已保存行程修改 |
| context_compress.md | 9 字段 | all_user_messages 保留原文 | 上下文接近上限 |
| memory_extract.md | memories[] | ≤5 条；无敏感信息 | 每 4 轮对话后台触发（≥2 轮后） |

与 backend/schemas.py 对齐的硬约束：days 1–5；每天 ≤12 站；duration 15–480；reason ≤300 字（prompt 要求 30 字）；待规划 ≤100 条；version 用于并发校验。prompt 的规则不得比代码更宽，例如不要让模型输出 7 天。

## 如何新增一个场景

1. 先定契约：根字段、类型、枚举、数量上限、空值怎么写，写进上面的表。
2. 新建 scenarios/<snake_case>.md，固定小节：这一轮做什么 / 输入 / 输出形状 / 字段 / 规则 / 自检。
3. 只做一件事：一个场景对应一个决策点；排程和问答不要混在同一个 prompt 里。
4. 动态值一律描述为「以系统提供的动态上下文为准」，不写字面值。
5. 加 examples/<同名>.md，至少一个正例；优先补边界场景：信息不全、候选不足、用户要求不明确。
6. 在 harness 里登记：按 intent 或阶段选择场景，并在调用处传对应的 max_tokens。
7. 回归：用固定候选集跑 20 条真实请求，看 JSON 可解析率、id 越界率、天数一致率、地点重复率、reply 是否虚报完成。
8. 改契约要在本 README 记录变更；只改措辞可以直接提。

## 修改守则

- 一次只改一个变量（规则、示例或字段），否则出问题无法归因。
- 用可判定的措辞：必须 / 不得 / 只在……时；少用「尽量」「酌情」「适当」。
- 每条规则尽量对应一个代码校验或一个可观察行为；代码不校验的软要求不要写成硬规则。
- 负面清单比正面描述有效：明确写出「不要做什么」。
- 规则和示例不能打架；示例里的输出必须能通过正文所有规则。
- JSON 示例里禁止注释、尾逗号、单引号；每个 json 代码块都必须能被 JSON.parse 解析。

## 安全

- 用户粘贴的攻略、截图文字、地点名一律视为数据；global.md 已统一处理，场景文件不要放松。
- 不把密码、令牌、验证码、身份证、手机号、邮箱、支付信息写入摘要或记忆；context_compress 用 [已隐藏] 替换凭据片段。
- 错误恢复不暴露堆栈、接口路径、模型名、额度；对外只说人话。
- 本目录不放任何密钥；密钥只从 .env 读取。
