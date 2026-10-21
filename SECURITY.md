# 安全策略

## 报告安全问题

**请不要用公开 issue 报告漏洞。** 请通过 GitHub 的
[私密漏洞报告](https://github.com/nKwYi/Blender-Agent/security/advisories/new)
提交（仓库 → Security → Report a vulnerability）。

我们会在 7 天内给出初步回应。

## 关于 API Key

- Key **不会**被写进场景文件（`.blend`）
- 在设置框里填写的 Key 以**明文**存进 Blender 偏好设置文件（`userpref.blend`，仅本机）
- **推荐**：设置框留空，改用环境变量 `DEEPSEEK_API_KEY` / `MINIMAX_API_KEY`，
  这样 Key 完全不落盘
- 日志、错误详情、导出转录中的 Key 会被自动脱敏为 `sk-***`
- 仓库的 `.gitignore` 已排除 `.env` / `*.key` / `*.pem` / `userpref.blend`

如果你**不小心把 Key 提交进了仓库**，请立刻：

1. 到服务商后台**吊销（revoke）这个 Key**并重新生成一个 —— 删掉提交是不够的，
   Git 历史里还能翻出来
2. 用 `git filter-repo` 或 BFG 清理历史后 force-push
3. 告知维护者，方便核查是否已被拉取

## 本插件的权限边界

`execute_blender_code` 可以在 Blender 的 Python 作用域里执行任意代码。
插件的设计前提是**用户逐次审批**：

- 每次执行前弹审批框，可以展开看完整代码
- 批准 / 拒绝是逐次的，不是「一次批准后面全放行」
- 超时自动停止

请不要在不了解代码的情况下批量点「批准执行」。
