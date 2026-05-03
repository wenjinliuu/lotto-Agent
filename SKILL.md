# lotto-agent 彩票 Agent Skill

当用户提到：彩票、双色球、大乐透、七星彩、七乐彩、福彩3D、排列三、排列五、快乐8、选号、开奖、兑奖、中奖、期号、奖池、奖金、报告、盈亏、推荐号码，必须优先使用此 Skill。

本 Skill 是私人自用彩票 Agent，不承诺提高中奖概率，不做预测，不使用“预测必中”等说法。大模型只负责理解用户意图、调用脚本和组织输出；选号、开奖抓取、兑奖判断、数据存储必须由 Python 规则代码完成。

## 入口

统一入口：

```bash
python scripts/main.py <action> [options]
```

支持 action：

- `generate`：生成号码并写入 `tickets`
- `fetch_draw`：抓取开奖并写入 `draws`、`draw_prize_details`
- `check_prize`：按规则自动兑奖并写入 `prize_results`
- `report`：生成日报、周报、月报
- `update_config`：修改非核心配置，修改前自动备份
- `status`：健康检查
- `manual_draw_input`：手动录入开奖结果
- `schedule`：供 cron 调用定时任务
- `create_automation`：创建一次性/长期自动任务并写入 SQLite
- `list_automation`：查看自动任务
- `disable_automation`：停用自动任务
- `install_cron` / `uninstall_cron` / `cron_status`：安装、停止、查看服务器唤醒器
- `notification_status` / `configure_notification` / `bind_notification_target` / `list_notification_targets` / `enable_notification`：查看、配置、绑定目标并确认开启通用消息推送

## 消息输出要求

输出要简洁、适合消息阅读、数字格式整齐。号码文本只放号码相关内容，不在号码消息里附加免责声明、解释或废话。每注号码前不显示序号。大乐透不追加时不显示追加字段，追加时才显示 `追加`。不要夸大中奖概率，不承诺提高中奖率，不使用预测、必中、稳赚等表达。

## 常用调用

```bash
python scripts/main.py generate --lottery-type dlt --count 10 --message-text
python scripts/main.py generate --lottery-type kl8 --play-type 10 --count 5 --message-text
python scripts/main.py fetch_draw --lottery-type ssq --message-text
python scripts/main.py fetch_draw --lottery-type dlt --issue 25001 --message-text
python scripts/main.py check_prize --message-text
python scripts/main.py report --report-type monthly --message-text
python scripts/main.py create_automation --task-action generate --lottery-type ssq --count 5 --multiple 2 --time-start 09:00 --message-text
python scripts/main.py schedule --job-name fetch_draws --push
python scripts/main.py notification_status
```

## 自然语言意图映射

- “生成今天大乐透10注” -> `generate --lottery-type dlt --count 10`
- “给我50元方案” -> `generate --lottery-type <默认彩种> --budget 50`
- “生成快乐8选十5注” -> `generate --lottery-type kl8 --play-type 10 --count 5`
- “大乐透5注2倍追加” -> `generate --lottery-type dlt --count 5 --multiple 2 --additional`
- “福彩3D组三来5注” -> `generate --lottery-type fc3d --play-type group3 --count 5`
- “排列三组六10注” -> `generate --lottery-type pl3 --play-type group6 --count 10`
- “福彩3D单选5注2倍，组三2注，组六2注双倍” -> `generate_plan --lottery-type fc3d`
- “快乐8选十5注，选三2注” -> `generate_plan --lottery-type kl8`
- “查一下最新双色球开奖” -> `fetch_draw --lottery-type ssq`
- “查一下大乐透第25001期” -> `fetch_draw --lottery-type dlt --issue 25001`
- “上一期大乐透一等奖中了几个人，单注多少钱” -> `query_draw_detail --lottery-type dlt --prize-level 一等奖`
- “双色球第25001期二等奖奖金是多少” -> `query_draw_detail --lottery-type ssq --issue 25001 --prize-level 二等奖`
- “帮我兑奖今天的号码 / 最近一期” -> `check_prize`
- “看看本月盈亏” -> `report --report-type monthly`
- “以后大乐透默认10注” -> `update_config --config-name preferences --updates '{"default_lottery":"dlt","default_count":10}'`
- “大乐透以后不追加” -> `update_config --config-name preferences --updates '{"default_additional":{"dlt":false}}'`
- “大乐透以后追加” -> `update_config --config-name preferences --updates '{"default_additional":{"dlt":true}}'`
- “大乐透买2倍” -> `generate --lottery-type dlt --multiple 2`
- “把每天推送时间改成早上9点” -> `update_config --config-name preferences --updates '{"subscriptions":{"daily_push_time":"09:00"}}'`
- “刚才生成的号码我买了” -> `confirm_purchase`
- “今天生成的都算已买” -> `confirm_purchase`
- “刚才那几注不要算成本” -> `cancel_tickets`
- “这几注只是看看” -> `cancel_tickets`
- “先看看大乐透5注” -> `generate --lottery-type dlt --count 5 --preview`
- “不喜欢这个，重新给我生成一组” -> `replace_last_batch`
- “换一组大乐透5注2倍追加” -> `replace_last_batch --lottery-type dlt --count 5 --multiple 2 --additional`
- “再来一组” -> `generate`，保留上一组并新增一组
- “最近选号记录” -> `recent_tickets`
- “以后每天早上9点给我大乐透5注” -> `create_automation --task-action generate`
- “明天上午10点给我一组快乐8选十” -> `create_automation --schedule-type once`
- “每天晚上10点帮我兑奖” -> `create_automation --task-action check_prize`
- “以后大乐透开奖那天早上给我5注” -> `create_automation --task-action generate --trigger-type draw_day --draw-day-offset 0`
- “双色球开奖前一天晚上给我3注” -> `create_automation --task-action generate --trigger-type draw_day --draw-day-offset -1`
- “每期开奖后自动兑奖并告诉我” -> `create_automation --task-action draw_check_prize`
- “查看自动任务” -> `list_automation`
- “确认开启自动化” -> `install_cron --confirm`
- “通知状态 / 消息推送状态” -> `notification_status`
- “查看通知目标 / 通知目标列表” -> `list_notification_targets`
- “绑定当前窗口 / 以后发到这里” -> `bind_notification_target`
- “确认绑定当前通知目标” -> `bind_notification_target --confirm`
- “确认开启消息推送” -> `enable_notification --confirm`
- “停止自动化” -> `uninstall_cron`
- “我买了大乐透第25001期 01 05 12 18 30 + 02 09，2倍追加” -> `record_ticket --lottery-type dlt --issue 25001 --multiple 2 --additional`
- “我买了双色球 01 06 12 18 25 31 + 09，帮我记录” -> `record_ticket --lottery-type ssq`
- “前区 01 05 12 18 30 后区 02 09，帮我记录大乐透” -> `record_ticket --lottery-type dlt`
- “红球 01 06 12 18 25 31 蓝球 09，帮我记录双色球” -> `record_ticket --lottery-type ssq`
- “本周花了多少钱” -> `report --report-type weekly`
- “今年大乐透投入多少” -> 后续后台统计；当前可用月报/周报/日报

如果需要让 Skill 先解析自然语言而不是直接执行，可以调用：

```bash
python scripts/main.py parse_command --text "大乐透5注2倍追加"
```

## 成本和追踪

大乐透普通投注每注 2 元，追加投注每注 3 元。所有彩种都支持倍数，成本公式为：

```text
单注价格 * 注数 * 倍数
```

生成号码时如果用户没有明确指定期号，会优先使用最近开奖数据里的 `next_issue`、`next_open_time`、`next_buy_end_time`。当前时间没有超过停止购买时间时，系统自动绑定下一期期号和开奖日期；如果已经超过停止购买时间，则退回下一次可开奖日期，避免错兑。用户通常只需要看到开奖日期，期号作为内部追踪字段保存。兑奖时只会匹配同一期号，或在没有期号时匹配同开奖日期。

用户说“今天、明天、后天、5月1日”时，先把自然语言日期解析成目标开奖日期，再按开奖日历校正。校正优先级是：API/公共开奖数据里的下一期开奖信息 -> `config/draw_calendar.json` 的本地日历/节假日预留 -> 固定开奖周历兜底。固定周历只作为兜底：双色球周二/四/日，七乐彩周一/三/五，大乐透周一/三/六，七星彩周二/五/日，福彩3D/排列三/排列五/快乐8每日。若用户指定日期不是该彩种开奖日，号码正文仍只显示最终开奖日，另在 `notice_text` 返回一句单独提醒，例如“你说的是 2026-05-01，但该彩种这天不开奖，已按下一次开奖 2026-05-03 生成。”

大乐透三至七等奖根据开奖 API 保存的奖池金额分档计算：奖池 8 亿以下使用 5000/300/150/15/5，奖池 8 亿及以上使用 6666/380/200/18/7。一、二等奖优先使用 API 奖项明细中的单注奖金和追加奖金。

用户查询“上一期一等奖中了几个人、单注奖金多少、奖项明细”时，使用 `query_draw_detail` 读取 SQLite 的 `draws` 和 `draw_prize_details`，不要让大模型自由回答金额或人数。数据库没有该期数据时，自动调用 `fetch_draw` 从 GitHub 公共开奖源补拉，写入本地 SQLite 后再查询；公共源也没有时，再提示稍后再试或手动录入。

## 自动化规则

用户说“每天、每周、明天、后天、定时、自动、每期开奖后”并包含选号、生成、兑奖、开奖、报告等意图时，优先创建自动任务，而不是只更新普通偏好。业务任务写入 SQLite 的 `scheduled_tasks`，服务器只需要安装一次统一 cron 唤醒器：每 30 分钟调用 `python3 scripts/main.py schedule --push`。如果用户创建了自动任务但 cron 未开启，回复中必须引导用户“确认开启自动化”。

开奖日类表达必须走受控触发器：`trigger_type=draw_day`，`draw_day_offset=0` 表示开奖当天，`-1` 表示开奖前一天。支持“开奖那天、开奖当天、开奖日、开奖前一天、开奖日前一天”。不要让模型自由脑补其它时间规则。

自动化时间窗口只分三类：早上/上午统一为 `07:00-12:00`，下午为 `12:00-18:00`，晚上为 `18:00-23:30`。用户说窗口词或“8点到10点之间”时，写入 `run_time_mode=random_once_in_window`，由调度器在窗口内用 Crypto 随机安排一次执行；用户明确说固定时间时，写入 `run_time_mode=fixed`。模糊表达如“有空的时候、看情况、你觉得合适的时候、差不多的时候”必须反问，只让用户选择上午、下午、晚上或固定时间，不能创建任务。

`schedule` 执行时要先判断任务是否到期，并通过 `last_run_key` 避免重复执行。一次性任务执行后自动停用；长期任务保持启用。窗口类任务同一天只执行一次，计划时间记录在 `planned_run_key` 和 `planned_run_time`。

创建自动任务时，如果当前调用能拿到 OpenClaw 入站路由，payload 必须保存任务级 `delivery` 快照：`delivery.channel`、`delivery.chat_id`、`delivery.account_id`。定时任务推送时优先使用 `payload.delivery`，实现“谁创建，跟谁走”；只有老任务或缺少 delivery 的任务，才 fallback 到 `notification_recipient` 并解析 `config/notifications.json` 的绑定目标。

自动化业务参数必须完整持久化到 `payload_json`。生成类任务至少要保留 `lottery_type`、`count`、`budget`、`play_type`、`multiple`、`is_additional` 等已经识别出的参数。`create_automation` 允许调用方把这些字段放在顶层参数或 `payload` 内；如果两边都有同名字段，以 `payload` 为准，顶层参数只作为兜底补全。不要只保存动作和时间，避免后续 cron 执行时退回默认 `count=1`、`multiple=1`。

默认 `schedule.json` 开启 `draw_check_prize_window`：21:35-23:55 由 cron 唤醒，按 30 分钟粒度允许重试抓 GitHub 公共开奖源。抓到开奖后写入 SQLite，再立即调用 `check_prize`。如果 `checked_count` 为 0，默认不主动推送空结果，除非配置 `subscriptions.push_content.empty_prize_result = true`。

用户说“为什么今天还没开奖呀 / 帮我查一下开奖状态 / 我今天中了没有”时，直接调用 `draw_check_prize`，立即执行一次“抓 GitHub 开奖数据 -> 写库 -> 兑奖”，并返回当前状态。

## 通用消息推送

主动推送必须通过 `config/notifications.json` 的通用通知层完成，不要在代码或提示里写死某个聊天平台。默认 provider 是 `dry_run` 且 `enabled=false`，表示只返回待发送 payload，不实际投递。`schedule --push` 如果发现通知未启用或配置不完整，必须返回 `requires_configuration=true` 和简短配置引导。

支持 provider：

- `host_payload`：返回 payload 给宿主接管投递。
- `openclaw_cli`：调用 OpenClaw CLI 的 message send 能力，必须配置 channel 和 chat_id；多账号时应保存 account_id。
- `dry_run`：调试用，不视为真实主动推送。

lotto-agent 不支持任意 webhook 外发。lotto-agent 不允许配置自定义消息发送命令；`openclaw_cli` 永远只调用 PATH 中的 `openclaw` 可执行文件。主动推送仅通过 `openclaw message send` 或 `host_payload` 交给宿主处理。通用 `update_config` 不能修改 `config/notifications.json`，通知配置只能通过 `configure_notification` / `bind_notification_target` / `enable_notification` 修改。

`openclaw_cli` 必须先绑定 recipient 的 channel/chat_id/account_id，再启用推送。推荐流程：

```bash
python scripts/main.py configure_notification --provider openclaw_cli --channel <channel> --chat-id <chat_id> --account-id <account_id>
python scripts/main.py bind_notification_target --provider openclaw_cli --recipient self --channel <channel> --chat-id <chat_id> --account-id <account_id> --confirm
python scripts/main.py enable_notification --confirm
```

OpenClaw 入站消息路由字段按 `channel`、`chat_id`、`account_id` 处理。`chat_id` 对应 CLI 出站时的 `--target`，`account_id` 对应多账号投递时的 `--account`。`recipient` 是 lotto-agent 内部通用别名，不代表固定平台；多窗口或多用户部署时，为每个需要接收自动化消息的目标配置明确别名，并通过 `list_notification_targets` 查看。用户换窗口后，如果宿主传入的 `chat_id` 不同，应再次引导绑定，不要把消息静默发给旧窗口。

用户明确确认前，不要启用主动消息推送。配置后引导用户回复“确认开启消息推送”；确认后才调用 `enable_notification --confirm`。

## 第二条提示

Skill 返回结果时，`message_text` 是第一条核心消息。若存在 `followup_contexts`，优先让大模型基于其中的事实和边界生成第二条自然提示；若模型没有生成，则发送 `followup_messages` 里的兜底句。第二条提示可以有一点个性和变化，但必须遵守：

- 不改动号码、期号、开奖日期、金额、购买状态
- 不承诺中奖，不暗示提高中奖率
- 不新增推荐号码
- 不长篇解释算法
- 对日期顺延、取消统计、仅生成预览、自动化未开启、无可兑奖号码等关键事实，必须保留原意

## 公共开奖数据源

默认开奖数据源是 GitHub 公共 JSON，不要求普通使用者配置 API key。当前 `config/api_sources.json` 已默认指向：

```text
https://raw.githubusercontent.com/wenjinliuu/lottery-data-repo/main/public_data
```

其他部署者可以用服务器环境变量覆盖：

```bash
export LOTTERY_PUBLIC_DATA_BASE_URL="https://raw.githubusercontent.com/<owner>/<repo>/main/public_data"
```

开奖仓库维护逻辑统一放在独立的 `lottery-data-repo` 仓库。普通 Skill 使用者不需要配置开奖 API；维护者只在开奖仓库侧运行：

```bash
cd lottery-data-repo
python scripts/update_public_data.py
python scripts/validate_public_data.py
```

这会根据 `caipiao/query` 和 `caipiao/class` 生成开奖仓库 `public_data/` 下的公开开奖数据。Skill 根目录不保留开奖仓库更新脚本或 GitHub Actions。

## 运行前配置

腾讯云服务器上建议放置在：

```text
/root/.openclaw/workspace/skills/lotto-agent
```

默认运行不需要配置开奖 API。Skill 会读取 GitHub 公共开奖数据源；只有公共开奖仓库维护侧才需要配置外部开奖接口凭据。

数据库默认位置在 OpenClaw workspace 下的 skill 专属目录，避免更新 skill 时覆盖历史数据，并符合 OpenClaw 社区常见的 workspace 数据存放习惯：

```text
~/.openclaw/workspace/lotto-agent-data/lottery.db
```

Windows 下 `~` 是当前运行用户目录，例如 `C:\Users\<用户名>\.openclaw\workspace\lotto-agent-data\lottery.db`。部署者仍然可以用 `LOTTO_AGENT_DATA_DIR` 覆盖默认目录。cron 和手动命令必须使用同一个数据目录，确保读写同一份数据库。

用户询问数据库位置或权限时，先让用户运行：

```bash
python scripts/main.py status
```

返回中的 `data_dir` 和 `db_path` 是实际路径。如果默认目录不能自动创建，推荐先以运行 OpenClaw/cron 的用户创建 workspace 数据目录：

```bash
mkdir -p "$HOME/.openclaw/workspace/lotto-agent-data"
chmod 700 "$HOME/.openclaw/workspace/lotto-agent-data"
python scripts/main.py status
```

如果 OpenClaw/cron 使用专用系统用户运行，应把目录授权给该用户，例如 `openclaw:openclaw`。只有在显式覆盖默认路径时，cron 命令才需要包含同一个 `LOTTO_AGENT_DATA_DIR`。
