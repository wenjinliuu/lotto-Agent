# lotto-agent

lotto-agent 是面向通用消息宿主的彩票 Agent Skill，可运行在 OpenClaw、自定义宿主或纯命令行调试环境中。它支持 8 个彩种的 Crypto 级随机选号、开奖数据读取、SQLite 持久化、规则兑奖、定时任务和报表。

## 支持彩种

- 双色球
- 大乐透
- 七星彩
- 福彩3D
- 排列三
- 排列五
- 七乐彩
- 快乐8

## 部署

当前上线范围只包含 Skill 本体。根目录的 `requirements.txt` 是 Skill 运行依赖。

推荐目录：

```bash
/root/.openclaw/workspace/skills/lotto-agent
```

安装依赖：

```bash
pip install -r requirements.txt
```

默认公共开奖数据源已经指向你的 GitHub 开奖仓库：

```bash
https://raw.githubusercontent.com/wenjinliuu/lottery-data-repo/main/public_data
```

如果其他人部署到自己的仓库，可以用环境变量覆盖：

```bash
export LOTTERY_PUBLIC_DATA_BASE_URL="https://raw.githubusercontent.com/<owner>/<repo>/main/public_data"
```

默认安装不需要配置开奖 API。Skill 会直接读取上面的 GitHub 公共开奖数据源。

初始化数据库：

```bash
python scripts/main.py status
```

运行数据默认保存在 OpenClaw workspace 下的 skill 专属目录，避免 OpenClaw/ClawHub 更新 skill 时覆盖历史记录，也方便用户直接找到、备份或删除：

```text
~/.openclaw/workspace/lotto-agent-data/lottery.db
```

Windows 下 `~` 表示当前运行用户目录，例如：

```text
C:\Users\<用户名>\.openclaw\workspace\lotto-agent-data\lottery.db
```

也可以用环境变量覆盖到其他明确位置：

```bash
export LOTTO_AGENT_DATA_DIR="$HOME/.openclaw/workspace/lotto-agent-data"
```

Skill 第一次执行 `status`、选号、查开奖、兑奖或报表命令时，会在上述目录自动创建数据库并初始化所需表结构。如果部署者覆盖了 `LOTTO_AGENT_DATA_DIR`，cron 环境也要使用同一个变量，确保手动调用和自动化任务读写同一份数据库。

### 数据库位置与权限

运行以下命令可以查看当前实际数据库位置：

```bash
python scripts/main.py status
```

返回里的 `data_dir` 和 `db_path` 就是实际读写位置。所有业务入口都会使用同一份 SQLite 数据库，包括选号、手动记录、自动任务、开奖抓取、兑奖、报表和调度日志。

默认 OpenClaw workspace 目录通常不需要额外授权。如果目录不能自动创建，先确认 OpenClaw/cron 是由哪个系统用户运行，再给这个用户授权：

```bash
mkdir -p "$HOME/.openclaw/workspace/lotto-agent-data"
chmod 700 "$HOME/.openclaw/workspace/lotto-agent-data"
python scripts/main.py status
```

如果 OpenClaw 或 cron 由某个专用用户运行，请以该用户身份创建目录，或由管理员授权给对应用户，例如：

```bash
sudo mkdir -p /home/openclaw/.openclaw/workspace/lotto-agent-data
sudo chown -R openclaw:openclaw /home/openclaw/.openclaw/workspace/lotto-agent-data
sudo chmod 700 /home/openclaw/.openclaw/workspace/lotto-agent-data
```

如果显式设置了 `LOTTO_AGENT_DATA_DIR`，cron 也要带上同一个环境变量：

```bash
*/30 * * * * cd /root/.openclaw/workspace/skills/lotto-agent && LOTTO_AGENT_DATA_DIR=$HOME/.openclaw/workspace/lotto-agent-data python3 scripts/main.py schedule --push # lotto-agent automation
```

如果目录不可写，`status` 会返回可执行的授权引导。

上线后建议先跑一次健康检查和基础命令：

```bash
python scripts/main.py status
python scripts/main.py generate --lottery-type dlt --count 1 --message-text
python scripts/main.py fetch_draw --lottery-type dlt --message-text
```

## 示例

```bash
python scripts/main.py generate --lottery-type dlt --count 10 --message-text
python scripts/main.py generate --lottery-type dlt --count 5 --additional --multiple 2 --message-text
python scripts/main.py confirm_purchase --limit 5 --message-text
python scripts/main.py cancel_tickets --limit 5 --notes "只是看看" --message-text
python scripts/main.py record_ticket --lottery-type dlt --issue 25001 --text "01 05 12 18 30 + 02 09" --multiple 2 --additional --message-text
python scripts/main.py recent_tickets --limit 10 --message-text
python scripts/main.py parse_command --text "大乐透5注2倍追加"
python scripts/main.py generate --lottery-type kl8 --play-type 10 --count 5 --message-text
python scripts/main.py fetch_draw --lottery-type all
python scripts/main.py fetch_draw --lottery-type dlt --issue 25001
python scripts/main.py query_draw_detail --lottery-type dlt --prize-level 一等奖 --message-text
python scripts/main.py check_prize --message-text
python scripts/main.py report --report-type weekly --message-text
python scripts/main.py create_automation --task-action generate --lottery-type dlt --count 5 --multiple 2 --time-start 09:00 --delivery-channel <channel> --delivery-chat-id <chat_id> --delivery-account-id <account_id> --message-text
python scripts/main.py create_automation --task-action generate --payload '{"lottery_type":"dlt","count":5,"multiple":2}' --time-start 09:00 --message-text
python scripts/main.py install_cron --confirm --message-text
python scripts/main.py notification_status
python scripts/main.py configure_notification --provider openclaw_cli --channel <channel> --chat-id <chat_id> --account-id <account_id>
python scripts/main.py bind_notification_target --provider openclaw_cli --recipient self --channel <channel> --chat-id <chat_id> --account-id <account_id> --confirm
python scripts/main.py list_notification_targets --message-text
python scripts/main.py enable_notification --confirm
python scripts/main.py schedule --push
```

## 基础偏好

默认大乐透不追加。大乐透普通一注 2 元，追加一注 3 元；所有彩种支持倍数，成本按 `单注价格 * 注数 * 倍数` 计算。用户可通过 `update_config` 随时修改默认彩种、默认注数、默认预算、默认玩法、是否追加、倍数、推送时间和推送内容。

生成号码会尽量绑定 API 返回的下一期期号、下一期开奖时间和停止购买时间。用户说“今天、明天、后天、5月1日”时，系统会先按开奖日历/API 校正到真实开奖日；如果当天不是该彩种开奖日，会把号码绑定到下一次开奖日，并在结构化结果里返回 `notice_text` 供 message host 单独提醒。兑奖时只按明确期号匹配；如果票据没有期号，则按记录的开奖日期匹配，避免一张票被拿去兑多个历史开奖。

## 开奖日历

开奖日期判断优先级：

1. 数据库中最新开奖/API/公共 GitHub 数据里的 `next_issue`、`nextopentime`、`nextbuyendtime`
2. 本地 `config/draw_calendar.json` 的节假日/特殊日历预留
3. 固定开奖周历兜底

固定周历只做兜底：双色球周二/四/日，七乐彩周一/三/五，大乐透周一/三/六，七星彩周二/五/日；福彩3D、排列三、排列五、快乐8按每日开奖处理。遇到节假日休市或官方调整时，以 API/开奖日历为准，不靠固定周历硬判。

## 票据状态

生成号码默认是 `purchased`，会计入成本并参与后续兑奖。用户明确说“先看看、参考一下、只是看看、先别记录、不算成本”时，才会以 `generated` 状态保存，不计入成本。取消后为 `cancelled`，重新生成替换上一组后旧票据为 `replaced`，都不会计入成本。

常用口径：

- 默认生成：计入投入和兑奖
- 先看看/参考：不算成本
- 已取消/已替换：不算成本
- 手动记录号码：默认就是已购买

手动记录支持常见复制格式：

```text
01 05 12 18 30 + 02 09
01,05,12,18,30 / 02,09
前区 01 05 12 18 30 后区 02 09
红球 01 06 12 18 25 31 蓝球 09
```

兑奖后票据状态会自动更新为 `won` 或 `lost`。生成但未购买、已取消、已替换的票据不会参与兑奖。

用户也可以查询开奖奖项明细，例如“上一期大乐透一等奖中了几个人，单注多少钱”。这类问题会先读取 SQLite 的 `draws` 和 `draw_prize_details`，返回中奖注数、单注奖金、追加注数和追加奖金；如果本地 SQLite 没有对应期开奖数据，会自动从 GitHub 公共开奖源补拉，写入本地数据库后再查询。GitHub 也没有时，才提示需要稍后再试或手动录入。

配置更新会做基础校验，避免写入非法注数、倍数、推送时间。定时任务执行结果会写入 `scheduler_logs`，方便后续排查自动任务。

## 自动化

自动化分两层：

- 业务自动任务：用户通过消息自然语言创建，保存到 SQLite 的 `scheduled_tasks`。
- 服务器唤醒器：cron 每 30 分钟调用一次 `python scripts/main.py schedule --push`，让 Skill 检查到期任务。

用户可以直接说：

```text
以后每天早上9点给我大乐透5注
明天上午10点给我一组快乐8选十
每天晚上10点帮我兑奖
每周二四六晚上8点给我双色球3注
以后大乐透开奖那天早上给我5注
双色球开奖前一天晚上给我3注
每期开奖后自动兑奖并告诉我
查看自动任务
确认开启自动化
```

开奖日类任务是受控触发器，不靠模型猜：`trigger_type=draw_day`，`draw_day_offset=0` 表示开奖当天，`-1` 表示开奖前一天。开奖日优先按 GitHub/API 日历判断，缺数据时才用本地固定周历兜底。

自动化时间只保留三个自然窗口：早上/上午统一为 `07:00-12:00`，下午为 `12:00-18:00`，晚上为 `18:00-23:30`。用户说“上午、下午、晚上”这类窗口时，任务会在窗口内用 Crypto 随机生成一个当天执行时间；用户明确说“9点、晚上10点”时，按固定时间执行。

如果用户说“有空的时候、看情况、你觉得合适的时候”等模糊时间，Skill 不会创建任务，会反问用户选择上午、下午、晚上或给出固定时间，避免自动化规则被污染。

默认配置会开启“开奖检测+自动兑奖窗口”：每天 21:35-23:55 反复检查 GitHub 公共开奖源，抓到新开奖后写入 SQLite，然后立刻按本地已购买号码兑奖并推送结果。没有可兑奖号码时默认不推送空结果。

用户也可以随时手动触发一次：

```text
为什么今天还没开奖呀
帮我查一下开奖状态
我今天中了没有
```

这会立即执行一次“抓 GitHub 开奖数据 -> 写库 -> 兑奖”的链路，不必等窗口里的下一次轮询。

创建业务任务时，如果检测到 cron 唤醒器未开启，Skill 会提示用户回复“确认开启自动化”。确认后会尝试在服务器 crontab 中写入一条统一唤醒任务。其他部署者也可以手动添加：

```bash
*/30 * * * * cd /root/.openclaw/workspace/skills/lotto-agent && python3 scripts/main.py schedule --push # lotto-agent automation
```

创建自动任务时，如果本次调用带有当前会话路由，任务 payload 会保存 `delivery.channel`、`delivery.chat_id`、`delivery.account_id` 快照。后续 cron 唤醒后，`schedule --push` 会优先按任务自己的 delivery 推送，实现“谁创建，跟谁走”。如果老任务没有 delivery，才 fallback 到 `notification_recipient` 绑定目标。

自动化任务的业务参数必须完整写入 `payload_json`。生成类任务会保存 `lottery_type`、`count`、`budget`、`play_type`、`multiple`、`is_additional` 等字段；`create_automation` 同时兼容两种调用方式：

```bash
python scripts/main.py create_automation --task-action generate --payload '{"lottery_type":"ssq","count":5,"multiple":2}'
python scripts/main.py create_automation --task-action generate --lottery-type ssq --count 5 --multiple 2
```

如果同一字段同时出现在 `payload` 和顶层参数里，以 `payload` 为准，顶层参数只作为兜底补全。这样可以避免“用户说 5 注 2 倍，但自动任务只保存 1 注”的问题。

## 消息推送

主动消息推送是通用通知层，不默认绑定任何聊天平台。默认 `config/notifications.json` 使用 `dry_run` 且 `enabled=false`，因此 `schedule --push` 会返回待发送 payload 和配置引导，但不会伪装成已发送。

支持的 provider：

- `host_payload`：只把 payload 返回给宿主，由宿主负责投递。
- `openclaw_cli`：调用 `openclaw message send --channel <channel> --target <chat_id> --message <content>`；多账号时会追加 `--account <account_id>`。固定使用 PATH 中解析到的 `openclaw` 可执行文件，不接受任何来自配置或参数的自定义命令。
- `dry_run`：仅调试，不发送。

### 安全边界

- lotto-agent **不支持任意 webhook 外发**，已移除 `webhook` provider 与对应配置/参数。
- lotto-agent **不允许配置自定义消息发送命令**：`openclaw_cli` 永远只调用进程启动时通过 `shutil.which("openclaw")` 解析到的可执行文件。`notifications.json` 中已不再有 `command` 字段，CLI 也不再接受 `--command` / `--webhook-url`。
- 通用 `update_config` **不能修改 `config/notifications.json`**。通知配置只能通过 `configure_notification`、`bind_notification_target`、`enable_notification` 修改，并保留 “确认绑定 / 确认开启 / 确认开启自动化” 的二次确认流程。
- 主动推送的全部出口只剩两个：`openclaw message send`（本地 CLI）或 `host_payload`（payload 交给宿主）。

OpenClaw 示例：

```bash
python scripts/main.py configure_notification --provider openclaw_cli --channel openclaw-weixin --chat-id '<chat_id>' --account-id '<account_id>'
python scripts/main.py bind_notification_target --provider openclaw_cli --recipient self --channel openclaw-weixin --chat-id '<chat_id>' --account-id '<account_id>' --confirm
python scripts/main.py enable_notification --confirm
```

OpenClaw 入站消息通常会带当前会话路由信息：

```json
{
  "channel": "<当前channel>",
  "chat_id": "<当前chat_id>",
  "account_id": "<当前account_id>"
}
```

如果宿主能提供当前会话的 `channel`、`chat_id`、`account_id`，创建自动任务时应直接传入并写入任务快照：

```bash
python scripts/main.py create_automation --task-action draw_check_prize --delivery-channel '<当前channel>' --delivery-chat-id '<当前chat_id>' --delivery-account-id '<当前account_id>'
```

同时也可以引导用户绑定默认通知目标，作为老任务或手动推送的 fallback：

```bash
python scripts/main.py bind_notification_target --provider openclaw_cli --recipient self --channel '<当前channel>' --chat-id '<当前chat_id>' --account-id '<当前account_id>'
python scripts/main.py bind_notification_target --provider openclaw_cli --recipient self --confirm
```

`recipient` 是 lotto-agent 内部的通用收件人别名，不等同于某个聊天平台账号。一个部署可以保留默认 `self`，也可以给不同窗口或不同用户配置 `work`、`family`、`operator` 等别名。查看当前绑定：

```bash
python scripts/main.py list_notification_targets --message-text
```

如果配置缺少 channel、chat_id，或 openclaw_cli 的 recipient 尚未确认绑定，`push_message` 会返回 `requires_configuration=true` 或 `requires_binding=true`，不会再把未发送的消息标记成成功推送。如果运行环境的 PATH 中找不到 `openclaw` 可执行文件，`openclaw_cli` 也会直接返回 `requires_configuration=true`。

## 第二条提示

核心结果仍放在 `message_text`，第二条轻提示使用半开放机制：

- `followup_contexts`：给消息宿主/大模型的结构化事实、语气和边界
- `followup_messages`：规则兜底句，模型不生成时直接发送

模型可以根据 `followup_contexts` 自由写得自然一点，但不能改动号码、期号、开奖日期、金额、购买状态，也不能承诺中奖或暗示提高中奖率。

## 消息号码文本

号码文本保持干净，只放号码相关信息。默认不显示每注序号，不在号码消息里附加免责声明或解释。大乐透不追加时不显示追加字段，只有追加时显示 `追加`。

同一彩种多玩法会合并成一条消息，例如：

```text
福彩3D
开奖：2026-05-01
投入：32元

单选｜5注｜2倍
3  6  8
0  1  9

组三｜2注
3  3  8

组六｜2注｜2倍
3  6  8
```

## 公共开奖数据

默认情况下，Skill 不直接调用开奖 API，而是读取 GitHub 公共开奖 JSON。开奖仓库维护逻辑统一放在 `lottery-data-repo/`，Skill 根目录不再保留仓库更新脚本或 GitHub Actions。

维护者更新流程在独立的 `lottery-data-repo` 仓库中完成：

```bash
cd lottery-data-repo
python scripts/update_public_data.py
python scripts/validate_public_data.py
git add public_data
git commit -m "Update lottery public data"
git push
```

GitHub Actions 定时任务在 `lottery-data-repo/.github/workflows/update-lottery-data.yml`。开奖 API 凭据只属于公共开奖仓库维护侧配置，普通 Skill 安装者不需要配置。

## 设计原则

- 大模型只做意图理解、调用 Skill 和组织回复。
- 选号、抓取、解析、兑奖、存储全部由 Python 规则代码完成。
- 自动任务和消息手动调用共用同一套模块。
- 随机源使用 `secrets.SystemRandom()`、`secrets.randbelow()`、`secrets.choice()`。
- 不跨注去重，不做冷热号干预，不做概率优化。
- 开奖原始响应完整保存在 `draws.raw_json`。
- 规则、接口、输出格式、偏好和定时任务均配置化。
