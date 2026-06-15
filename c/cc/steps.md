
A 股操作流程：

第 1 步（闸门）：运行 `python tool/index.py` 检查 framed.md §1 第一层环境
（上证 / 创业板 / 沪深300 对比 5/10 日均线 + 从缓存的 scan_zt CSV 读取的情绪）。
它会打印 GREEN / AMBER / RED 并保存 share_data/index_<date>.txt；RED = 空仓，不开新仓。

第 2 步（扫到 3 只）：运行 `python tool/scan_cn.py --final 3` 把今天的涨停池收敛到 3 只候选股
（每个最热板块出一个龙头）。它会保存 share_data/candidates_<date>.txt，
并复用 share_data/scan_zt_<date>.csv 作为 §1B 的情绪来源。

第 3 步（部署 3 槽）：3 只候选股各占一槽，市值 30-500 亿 + 结构干净 + 尚未 5+ 连板。
分散到不同板块。扫描器的 #1 可能市值超标或连板过高（如 600726），
此时跳过取下一板块的龙头替补。

第 4 步（验证历史）：运行 `python tool/cn_stock.py <code> --history` 拉取/刷新
share_data/price_<code>.txt，并核实存在 framed.md §3 的入场触发条件
（放量突破平台、量 >= 均量 1.5 倍，或缩量回踩 5/10 日均线站稳 + 再次放量收阳）。
无触发 = 不进场。

第 5 步（仓位 + 止损）：按 framed.md §5A 三槽集中模式。
每槽 ≈ 25,000 元（账户 ¥75K 的 33%；若 ¥100K 则每槽 ~33K），股数 = 仓位 / 入场价（取整到 100 股）。
实际风险由 ATR 止损宽度决定（framed.md §4A），而非固定百分比上限。
同时检查流动性：持仓金额不得超过该股 10 日平均成交额的 1%（§5A 流动性闸门）。
止损 = framed.md §4A 的 ATR 止损（max(5%, 1.0× 10日 ATR)，封顶 10%，所有板块统一）
或结构位下方 1-2% —— 取更接近入场价的那个。

第 6 步（直接入场）：GREEN 日 T+1 开盘直接买入目标股数（framed §3）。
不追高，不抄底。若 T+1 一字板无法成交则跳过该票。

第 7 步（记录 + 写次日计划）：用 "<code> <qty> <cost>" 更新 c/chold.md，并在次日开盘"前"
按 framed §6 写好管理计划 —— 止损触发（"收盘 < X => 次日开盘卖出"）、+8% 出一半、+15% 清仓
（固定目标，无移动止损）。

第 8 步（机械管理）：每个收盘检查计划并在次日开盘动作 —— 收盘触及 ATR 止损 = 全部卖出；
价格 >= +8%（约 入场价 × 1.08）= 减一半；价格 >= +15% = 减掉剩余；
第 5 天收盘浮盈 < +2% = 次日开盘出场（时间止损）；炸板后回封失败 = 次日开盘出场。
绝不补仓摊低成本；最多 10 个交易日后清仓。

第 9 步（复盘 + 重复）：收盘后重跑第 1 步并更新 c/watchlistd.md（最多 6 只）。
按 framed §6，规则违反"和"绿灯/暖市中错过的有效入场都要记录 —— 两者都算。

===
闸门 —— index.py → GREEN/AMBER/RED（RED = 空仓）。
扫到 3 只 —— scan_cn.py --final 3。
部署 3 槽 —— 市值 30-500 亿，分散到不同板块。
验证历史 —— cn_stock.py <code> --history + framed §3 触发检查。
仓位 + 止损 —— 三槽集中（每槽 ~25K / ¥75K），ATR 止损 1.0×（§4A），流动性检查（≤1% 日均成交额）。
直接入场 —— GREEN 日 T+1 开盘买。
记录 + 写计划 —— c/chold.md + 次日指令。
机械管理 —— ATR 止损 / 8/15 固定止盈 / 第 5 天时间止损 / 绝不补仓。
复盘 + 重复 —— 重跑闸门，更新 c/watchlistd.md，记录违规和错过的入场。

===============
 股票工具  (tool/cn_stock.py  +  tool/us_stock.py)
===============

初始化（每台机器一次）：
    python -m venv .venv
    source .venv/bin/activate          # Windows: .venv\Scripts\activate
    pip install -r tool/requirements.txt   # akshare 锁定在 1.18.63

用法（两个脚本接口相同）：
    python tool/cn_stock.py 601991 600726        # 最新行情（A 股）
    python tool/us_stock.py NVDA AMD             # 最新行情（美股）
    python tool/cn_stock.py 601991 --history     # 下载/刷新 price_<CODE>.txt
    python tool/us_stock.py NVDA  --history      # 增量：只抓取缺失的日期
    python tool/cn_stock.py 601991 --export      # 导出 JSON 供分析
    python tool/cn_stock.py 601991 --history --commit   # + git 增删改提交推送（手机 -> GitHub）

    可选：--start YYYY-MM-DD  --end YYYY-MM-DD  （默认回看约 2 年至今）
    输出文件落在 tool/share_data/price_<CODE>.txt

内置稳定性：
  - 每个脚本两个数据源，自动回退。
  - 增量缓存：抓取失败绝不清空文件；重跑只追加新行。
  - 每只标的之间间隔 2 秒，避免触发限流。

操作注意：
  - 不要爆发式请求。一次批量几个代码；若被拦，等约 1 分钟（新浪能兜底）。
  - akshare 已锁定版本，使 Windows 和 Ubuntu 行为一致。
  - 手机：--history --commit 一条命令完成 抓取 + 推送（需先一次性配好 venv +
    git 授权）。或在真机上运行，让手机拉取。
  - 美股 Turnover（换手）列为空（新浪美股只给成交量；振幅是计算得出）。
  - CN 文件在回退时可能混有 东方财富/新浪 的行；单位已对齐，表头反映最后写入的数据源。

===============
 候选股扫描器  (tool/scan_cn.py)
===============

用途：产出一份排好序的热门 A 股板块 + 其龙头的短名单，
这样你就不用凭空从 6 只自选里挑。它是"找"的一步；
cn_stock.py --history 是"验证"的一步。

流程：
    scan_cn.py            -> 排序后的候选股（热门板块 + 龙头）
      挑 6 只（注意旗标）
    cn_stock.py <code> --history -> 下载历史，验证买点 + 止损
    c/watchlistd.md       -> 选定的 6 只票
    c/framed.md           -> 闸门 / 入场 / 管理 / 再入场规则

用法：
    python tool/scan_cn.py                  # 今天 / 最近一个交易日
    python tool/scan_cn.py --date 20260526  # 指定某个交易日
    python tool/scan_cn.py --sleep 8        # 更温和的节奏
    python tool/scan_cn.py --no-cache       # 强制重新联网抓取
    python tool/scan_cn.py --out candidates # 同时保存 share_data/candidates_<date>.txt

读懂输出旗标（自动套用 framed.md）：
    市值✓  = 流通市值 30-500亿，framed.md §2 友好区间
    市值✗  = 太小（易控盘）或太大（拉不动）
    ⚠高位  = 连板 >= 5，高位接力风险，不追
    龙头排序：连板高 -> 首封早 -> 炸板少 -> 封板资金大。

防封设计（让这台电脑永不被东方财富封禁）：
  - 默认只发 1 次网络请求（涨停池 stock_zt_pool_em，
    它已携带 板块 + 连板 + 首封 + 封板资金）。
  - 熔断：被拦时等一次、重试一次，然后"停止"。
    它绝不进入锤击式重试循环（那才是触发封禁的原因）。
  - 按日期的磁盘缓存（share_data/scan_zt_<date>.csv）-> 重跑免费。
  - 收盘后运行，画面最真实。
  - 出现退避后的 "抓取被拒...已停止" 消息是正确行为，不是 bug ——
    等一会儿再重跑；它会抓取一次并缓存。

source /home/wujun/git/gprun/.venv/bin/activate


