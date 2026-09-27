# 每天 08:10（北京时间）自动推送到你的邮箱 —— 部署步骤（约 5 分钟，零密钥）

流程：GitHub Actions 定时 → 拉 Coinbase 日线 → 跑 V2 规则 → 按收盘价把建议交易记入账本 → 提交回仓库 → **机器人开一个 Issue，GitHub 自动把它发到你账号绑定的邮箱**。
不需要 SMTP、不需要任何 key。邮件标题 = Issue 标题 = 当天操作，例如：
`[你的用户名/仓库名] 买入 $7,000（0%→70%）｜BTC $84,417｜信号日 2026-09-27 (#12)`

## 第 1 步：建仓库并上传（注意 `.github` 是隐藏文件夹）

GitHub 新建仓库，**选 Private**。然后三选一：

**方式 A：网页上传 + 手工补 1 个文件（无需装任何软件，只做一次）**
1. *Add file → Upload files*，把文件夹里的东西全部拖进去（`.github` 会被系统当隐藏文件夹悄悄丢掉，正常现象）
2. *Add file → Create new file*，文件名框里输入 `.github/workflows/btc.yml`（输入 `/` 会自动建文件夹）
3. 打开刚上传的 `workflow_btc.yml` → *Raw* → 全选复制 → 粘贴进去 → Commit
   现在整个工程**只有这一个工作流文件**，以后更新代码只需替换 `.py`，不用再碰 `.github`。

**方式 B：GitHub Desktop（图形界面，隐藏文件夹会一起传）**
安装 GitHub Desktop → *File → Add local repository* 选中 `btc_quant` 文件夹 → *Publish repository*（勾 Private）。

**方式 C：命令行（一条命令，需要装 `gh`）**
```bash
cd btc_quant && git init && git add . && git commit -m init
gh repo create btc-signal --private --source=. --push
```

## 第 2 步：允许机器人写账本和开 Issue
Settings → Actions → General → **Workflow permissions → 选 "Read and write permissions"** → Save。
（没有这一步，账本无法保存、Issue 也开不了。）

## 第 3 步：确认 GitHub 会给你发邮件（通常默认就是开的）
- 仓库右上角 **Watch** 显示为 *All Activity*（自己新建的仓库默认如此）
- 头像 → Settings → Notifications → *Participating / Watching* 勾选 **Email**
- 机器人在 Issue 里会 @你，所以哪怕只勾了 "Participating and @mentions" 也会收到

## 第 4 步：手动测试一次
Actions 页 → 左侧 **BTC daily signal** → *Run workflow*。1–2 分钟后邮箱应收到 GitHub 的通知邮件，正文就是完整信号。
每天的 Issue 会自动关掉前一天的，仓库里始终只有一个 open 的信号。

> 注意：测试运行也会真的记账（按当天收盘价记一笔买入）。如果只是测试、不打算今天下单，测完后到 Actions → *BTC daily signal* → *Run workflow*，`mode` 选 `reinit`、`amount` 填 `10000` 重置即可。

## （可选）额外走 SMTP 直发邮件
不想经过 GitHub 通知、或想发到另一个邮箱时才需要。Settings → Secrets → 填 `MAIL_SERVER` / `MAIL_PORT`=465 / `MAIL_USERNAME` / `MAIL_PASSWORD`（授权码）/ `MAIL_TO`，工作流会自动多发一封；不填则自动跳过。
QQ 邮箱 `smtp.qq.com`（授权码）、163 `smtp.163.com`（授权码）、Gmail `smtp.gmail.com`（应用专用密码）。

## 从明天起自动运行
定时 `10 0 * * *`（UTC）= **每天 08:10 北京时间**。设成 08:10 而不是 08:00 的原因：
- 日 K 在 08:00 整才收盘，交易所需要一点时间生成完整 K 线（脚本会最多等 8 分钟直到拿到昨日完整 K 线）
- GitHub 定时任务本身常有 5–30 分钟排队延迟，这是平台特性，无法消除

## 每天你要做的
1. 看邮件标题：`买入 $X` / `卖出 $X` / `持有不动`
2. 去交易所按金额执行（限价贴近盘口，费率 ≤0.2% 的平台）
3. 邮件正文里有 **"执行后账本应为：现金 $… BTC …"**，每周和交易所余额对一次；偏差大就到 Actions → *Run workflow*，`mode` 选 `set`，填实际 `cash` 和 `btc` 同步

## 账本逻辑（重要）
- 默认 **自动模式**：邮件发出的同时，建议交易已按昨日收盘价记入账本（和回测口径一致）。你不执行 ≠ 账本不变，所以务必执行或校正。
- 熔断状态、权益高点都保存在 `portfolio.json`，由机器人每天提交到仓库。**不要手改这个文件**，用 Run workflow 的 `set` / `record` 模式。
- 想改成"我确认后才记账"的手动模式：把 `.github/workflows/btc.yml` 里的 `--auto-execute` 删掉，然后每次成交后用 Run workflow 的 `record` 模式填 `trade_usd` + `price`。

## 已知限制
- GitHub 可能在仓库 60 天无活动后暂停定时任务；机器人每天提交账本一般能保持活跃，若收到 GitHub 的"workflow 将被禁用"邮件，进仓库点一下 *Enable* 即可。
- 如果某天没收到邮件：Actions 页看运行日志（失败时也会发一封"⚠ 生成失败"邮件，除非邮件本身发不出去）。
- 回测按收盘价成交；你实际在 08:10–08:30 下单，价格会略有偏差，属正常。
