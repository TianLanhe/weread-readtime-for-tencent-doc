---
name: weread-readtime-for-tencent-doc
version: 1.0.0
description: "Read WeRead/微信读书 daily reading duration and either print it as a 日期/秒/分/时 table or sync it into a Tencent Docs SmartSheet/腾讯文档智能表格. Trigger only when the request is specifically about 微信读书阅读时长读取，或把微信读书阅读时长同步到腾讯文档智能表格；不要用于其他平台的多维表格、腾讯普通表格/Excel、腾讯文档正文、知识库、云文档或其他文档产品，也不要用于非微信读书数据同步。"
metadata:
  requires:
    bins: ["python3", "mcporter"]
    env: ["WEREAD_API_KEY", "TENCENT_DOCS_TOKEN"]
---

# 微信读书阅读时长 → 腾讯文档智能表格 / 表格输出

这个 skill 负责两件事：

1. **只读打印**：读取微信读书某段时间内的每日阅读时长，并按下列四列表格输出。
2. **写入腾讯智能表格**：把同一份数据按日期 upsert 到腾讯文档智能表格的 `阅读时长` 工作表。

固定表头如下：

- `日期`
- `当日阅读时长（秒）`
- `当日阅读时长（分）`
- `当日阅读时长（时）`

## 依赖与配置

执行这个 skill 时，优先按下面的依赖关系工作：

### 依赖 skill

- `weread-skill`
  - 用来理解 WeRead 的接口能力与已有口径，尤其是 `/readdata/detail` 的 `monthly` 模式。
- `tencent-docs`
  - 用来读写腾讯文档智能表格、校验字段、复制模板智能表格。

如果遇到腾讯文档认证或权限报错，先按 `tencent-docs` 的 `references/auth.md` 流程处理，不要盲目重试写入。

### 必要环境

- 环境变量：`WEREAD_API_KEY`
- 腾讯文档鉴权：`TENCENT_DOCS_TOKEN`
- 可执行命令：`python3`、`mcporter`

如果 `WEREAD_API_KEY` 缺失，直接告诉用户先配置，不要继续执行。
如果腾讯文档授权缺失或过期，按 `tencent-docs` skill 的授权流程重新配置。

### 依赖安装

这个 skill 依赖三个外部组件：

1. `python3`
2. `weread-skill`
3. 腾讯文档 MCP / `mcporter`

推荐的人工安装方式：

#### 安装 Python 3

当执行 skill 前发现 `python3` 命令不存在时，允许先在终端自动安装，再继续执行；**这属于环境准备，不要把安装逻辑写进 `scripts/sync_weread_readtime_to_tencent_doc.py`。**

优先按当前机器环境选择：

**macOS（推荐，已安装 Homebrew）**

```bash
brew install python@3.12
python3 --version
```

**macOS（未安装 Homebrew 时先安装 Homebrew，再安装 Python 3）**

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install python@3.12
python3 --version
```

**Debian / Ubuntu**

```bash
sudo apt-get update
sudo apt-get install -y python3
python3 --version
```

如果用户环境里缺少 `python3`，应先执行上述环境安装流程，再继续使用本 skill；不要因为缺少 `python3` 直接放弃。

#### 安装微信读书 skill

1. 从 "https://cdn.weread.qq.com/skills/weread-skills.zip” 下载并安装 skill，重命名 skill 为 weread-skill
2. 提示用户下载最新版本移动端“微信读书App”。在“我->设置->微信读书Skill->获取API Key”中获取API Key并配置 WEREAD_API_KEY 环境变量

#### 安装 / 配置腾讯文档 MCP

1. 从 "https://cdn.addon.tencentsuite.com/static/tencent-docs.zip" 下载 zip 包并 unzip 解压，安装这个 skills
2. 提示用户 “https://docs.qq.com/scenario/open-claw.html?nlc=1” 从这个网址获取并配置 TENCENT_DOCS_TOKEN 环境变量

```bash
mcporter list tencent-docs
```

重要限制：

- `scripts/sync_weread_readtime_to_tencent_doc.py` 只允许包含两类逻辑：
  1. 微信读书阅读时长获取
  2. 腾讯文档智能表格写入 / 从固定模板复制新智能表格与其直接相关的最小逻辑
- 不要把 skill 安装、MCP 安装、依赖检测、环境探测、升级向导等非核心流程写进这个 Python 脚本。
- 后续如果要更新安装方式、依赖说明、触发条件、操作约束，优先修改 `SKILL.md`、`references/`、`assets/`，**不要因为这些非阅读时长获取 / 腾讯智能表格写入需求去改 Python 代码。**

## 何时触发

下列请求都应该触发这个 skill：

- “读取我的微信读书每日阅读时长”
- “按 日期 / 秒 / 分 / 时 给我整理 X 月 X 日到今天的阅读时长”
- “把微信读书阅读时长写入腾讯文档智能表格”
- “同步 weread readtime 到腾讯智能表格，避免重复写入”
- “我只想看阅读时长，不需要导入腾讯文档”

下列请求**不要**触发这个 skill：

- 把微信读书数据同步到其他平台的多维表格
- 把微信读书数据同步到腾讯普通表格（sheet / Excel）、腾讯文档正文、知识库等非智能表格产品
- 把其他来源的数据同步到腾讯文档智能表格
- 与微信读书阅读时长无关的文档整理、报表搬运、表格写入需求

## 模式判定

收到请求后，先判断用户要的是哪一种模式：

### A. print-only / 只读模式

如果用户明确表达以下意思，就走**只读打印**，不要写腾讯智能表格：

- “只需要读取”
- “不用导入腾讯文档”
- “先打印出来”
- “只看表格结果”

此时直接运行脚本的 `--print-only` 模式，然后把结果以 Markdown 表格返回给用户。

### B. 写入已有腾讯智能表格

如果用户给了下面任一信息，就按已有腾讯智能表格写入：

- 完整腾讯文档智能表格链接（最好能识别 `file_id`，并带 `sheet_id` / `sheet` / `tab` 参数）
- `file_id + sheet_id`

写入前先校验目标工作表结构；若缺字段或字段类型不匹配，先告诉用户修正表结构，不要盲写。

如果用户给的 `sheet_id` **格式不合法或缺失**，不要直接失败：

1. 先检索整个腾讯智能表格文件的所有工作表；
2. 找出字段满足 `日期 / 当日阅读时长（秒） / 当日阅读时长（分） / 当日阅读时长（时）` 的工作表；
3. 优先使用名为 `阅读时长` 的工作表；否则使用第一个符合要求的工作表；
4. 回复用户时明确说明发生了自动回退与最终命中的 `sheet_id`。

### C. 未给腾讯智能表格，询问是否新建

如果用户要写入腾讯文档智能表格，但**没有提供智能表格链接 / file_id + sheet_id**，必须先追问：

> 你要不要我直接新建一个保存微信读书阅读时长的腾讯文档智能表格？

确认后，再复制固定模板创建腾讯智能表格副本。**不要在用户未确认时直接复制模板。**

## 复制腾讯智能表格模板规则

当用户确认要新建腾讯智能表格时，不要从空白表格创建字段，也不要在代码里初始化工作表结构；直接从下面的腾讯文档智能表格模板复制副本：

- 模板链接：`https://docs.qq.com/smartsheet/DYXpmanNXaURNWVB4?nlc=1&no_promotion=1&is_blank_or_template=template&tab=sc_tNPtzz`
- 模板 `file_id`：`DYXpmanNXaURNWVB4`

说明：

- 主脚本在 `--init-smartsheet` 路径下调用 `tencent-docs` 的 `manage.copy_file` 复制该模板。
- 复制完成后，自动在副本中查找满足字段要求的工作表，优先使用名为 `阅读时长` 的工作表。
- 模板本身负责提供字段、视图、格式和其他初始化内容；脚本只做复制、定位目标工作表、校验字段和写入数据。
- 如果要修改新建智能表格的结构、视图或样式，应该修改模板文档本身，而不是修改脚本里的字段初始化逻辑。

## 数据来源与口径

每日阅读时长来自：

```text
POST https://i.weread.qq.com/api/agent/gateway
api_name = /readdata/detail
mode = monthly
```

关键口径：

- `readTimes` 的 value 单位是 **秒**。
- `monthly` 模式下，返回的是按天分桶的时间戳 -> 秒数映射。
- 跨月区间需要**按自然月分段查询**后再拼接。
- 缺失日期按 `0` 秒补齐。
- 输出口径固定为：
  - 分钟 = `秒 / 60`，保留 1 位小数
  - 小时 = `秒 / 3600`，保留 2 位小数

## 目标表结构要求

写入的目标工作表必须包含以下字段：

- `日期`：`dateTime`
- `当日阅读时长（秒）`：`number`
- `当日阅读时长（分）`：`number`
- `当日阅读时长（时）`：`number`

在写入已有工作表前，先执行字段校验；字段不对就停止。

## 推荐执行命令

### 1) print-only：只读取并打印

```bash
python3 ${HOME}/.trae/skills/weread-readtime-for-tencent-doc/scripts/sync_weread_readtime_to_tencent_doc.py \
  --start-date 2026-05-01 \
  --end-date 2026-05-18 \
  --print-only
```

### 2) 写入已有腾讯智能表格（完整链接）

```bash
python3 ${HOME}/.trae/skills/weread-readtime-for-tencent-doc/scripts/sync_weread_readtime_to_tencent_doc.py \
  --table-url "https://docs.qq.com/smartsheet/DRXxxxxxx?sheet_id=sheet_abc123" \
  --start-date 2026-05-01 \
  --end-date 2026-05-18
```

### 3) 写入已有腾讯智能表格（file_id + sheet_id）

```bash
python3 ${HOME}/.trae/skills/weread-readtime-for-tencent-doc/scripts/sync_weread_readtime_to_tencent_doc.py \
  --file-id DRXxxxxxx \
  --sheet-id sheet_abc123 \
  --start-date 2026-05-01 \
  --end-date 2026-05-18
```

### 4) 用户确认后，从模板复制腾讯智能表格并写入

```bash
python3 ${HOME}/.trae/skills/weread-readtime-for-tencent-doc/scripts/sync_weread_readtime_to_tencent_doc.py \
  --init-smartsheet \
  --file-name "微信读书书架" \
  --start-date 2026-05-01 \
  --end-date 2026-05-18
```

## 常用参数

```bash
--print-only                  # 只读取打印，不做任何腾讯智能表格操作
--table-url <url>             # 腾讯文档智能表格链接，建议带 sheet_id/sheet/tab 参数
--file-id <id>                # 腾讯文档智能表格 file_id
--sheet-id <id>               # 工作表 sheet_id
--init-smartsheet             # 从固定模板复制腾讯智能表格副本，并把数据写入其“阅读时长”工作表
--file-name <name>            # 复制后的腾讯智能表格名字，默认“微信读书书架”
--folder-id <id>              # 可选，把副本放到指定文件夹
--start-date YYYY-MM-DD       # 默认最近 5 年的同一天
--end-date YYYY-MM-DD         # 默认今天
--dry-run                     # 只计算 upsert 结果，不实际写入已有腾讯智能表格
```

## 执行流程

### 1. 判断模式

- 只读 -> `--print-only`
- 已给腾讯智能表格 -> 直接校验并写入
- 要写入但没给腾讯智能表格 -> 先问是否从固定模板复制腾讯智能表格

### 2. 读取阅读时长

- 按月调用 `/readdata/detail`
- 过滤到目标日期区间
- 缺失日期补 0
- 用户没给范围时，默认查询最近 5 年到今天

### 3. 如需写入，解析并校验目标工作表

- 若用户给的是 URL，从中提取 `file_id` 和可选 `sheet_id`
- 若 `sheet_id` 缺失或格式不合法，则遍历整个腾讯智能表格自动寻找符合表头要求的工作表
- 读取字段结构
- 确认四个字段都存在且类型正确

### 4. upsert 写入

对每个目标日期：

- 当日阅读时长 = 0 -> 不创建
- 不存在且当日阅读时长 > 0 -> 创建
- 已存在但值变了 -> 更新
- 已存在且值相同 -> 跳过

### 5. 返回结果

返回时至少说明：

- `起止日期`
- `总天数`
- print-only 还是 sync
- 若写入：`新增 / 更新 / 跳过` 数量
- 若发生了 sheet_id 自动回退：返回原始 `sheet_id` 与最终命中的 `sheet_id`
- 若复制了模板腾讯智能表格：返回 `file_id`、`sheet_id`、文件名称、可访问链接（若 MCP 返回）、模板来源链接

## 返回格式要求

### print-only 模式

优先返回脚本输出里的 `markdown_table`，直接展示成 Markdown 表格，不需要再写一遍 JSON。

### 写入模式

先给简要摘要，再按需附上表格：

- 起止日期
- 总天数
- 新增记录数
- 更新记录数
- 跳过记录数
- 非 0 阅读天数（可写入天数）
- 目标腾讯智能表格 / 工作表
- 如果发生了 `sheet_id` 自动回退，明确说明是因为用户提供的 `sheet_id` 格式不合法或缺失
- 如果是 `dry-run`，明确说明未实际写入

## 注意事项

- 这是一个**可能包含写操作**的 skill；复制模板创建腾讯智能表格、写入腾讯智能表格前都要先得到用户确认。
- 用户只说“读取 / 打印 / 看一下”时，不要顺手写入腾讯文档。
- `readTimes` 单位始终是秒，不要误当分钟。
- 跨月区间一定按自然月拆分查询。
- 当用户误把其他 token 当成 `sheet_id` 传入，或链接里没有 `sheet_id` 时，要自动扫描整个腾讯智能表格找到真正可写的 `阅读时长` 工作表，而不是直接报错结束。
