# 兑奖规则

兑奖逻辑在 `config/lottery_rules.json` 和 `scripts/check_prize.py` 中实现。浮动奖金记为中奖但金额为 0，后续可结合 `draw_prize_details` 补充实际金额。

核心规则不允许通过 `update_config.py` 自动修改；只允许修改偏好、定时和输出格式等非核心配置。
