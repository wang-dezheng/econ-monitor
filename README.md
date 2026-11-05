# 每日经济观察 · China Macro Pulse

一个跑在本地（或服务器上）的「经济温度计」。每天自动抓取宏观数据、政策发布和财经新闻，打出一个 0–100 的经济温度，告诉你：

- 经济现在偏冷还是偏热；
- 过去 3 个月在改善还是走弱；
- 增长、物价、货币信用、地产、外部环境五个维度分别是什么状态；
- 新闻面偏乐观还是偏悲观，政策信号偏宽松还是偏收紧；
- 今天有哪些值得看的具体新闻，以及它为什么被判定为利好/利空。

输出是一份**自包含的 HTML 看板**（双击即可打开，不依赖网络和 CDN）和一份 **Markdown 日报**（方便存档、搜索、发给别人）。

> 这是“当前状态的温度计”，不是预测模型，也不构成投资建议。

---

## 1. 快速开始

环境：Windows / macOS / Linux，Python 3.10+（建议 3.12）。

```powershell
cd D:\经济
python -m pip install -r requirements.txt
python run.py --check      # 先检查数据源，约 1 分钟
python run.py --open       # 生成今日报告并打开浏览器
```

生成的文件：

| 文件 | 说明 |
|---|---|
| `reports/2026-11-05.html` | 今日可视化看板（自包含，可离线打开） |
| `reports/2026-11-05.md` | 今日 Markdown 日报 |
| `reports/index.html` | 历史报告归档页 |
| `data/latest.json` | 最新一期的结构化快照，方便二次开发 |
| `data/econ.db` | SQLite 历史库，保存每天的分数与新闻 |
| `logs/econ-YYYYMMDD.log` | 运行日志 |

Windows 下也可以直接双击 **`每日经济观察.bat`**。

---

## 2. 看板怎么读

### 经济温度（0–100）

| 区间 | 含义 |
|---|---|
| < 40 | 偏冷，收缩压力明显 |
| 40–47.5 | 偏弱 |
| 47.5–52.5 | 中性 |
| 52.5–60 | 偏暖 |
| > 60 | 偏热 |

50 是中性线。分数不是“GDP 增速”，而是**多个指标相对自身近 5 年正常水平的综合位置**。所以它回答的是“现在比过去几年更热还是更冷”，不是“经济好不好”的道德判断。

### 五个维度

| 维度 | 默认权重 | 看什么 |
|---|---:|---|
| 增长动能 | 34% | PMI、GDP、工业增加值、社零、固投、出口、消费者信心 |
| 物价水平 | 14% | CPI、PPI |
| 货币信用 | 20% | M2、M1、M1-M2 剪刀差、新增贷款、LPR 变化 |
| 地产链 | 14% | 70 城房价扩散指数、房价同比、一线二手房环比 |
| 外部环境 | 18% | 美债曲线、美债利率变化、美国 CPI、人民币汇率、铜、原油 |

权重可以在 `config.yaml` 的 `pillars` 里改，程序会自动归一化。

### 新闻面与政策信号

这两个分数**不混入硬数据温度**，单独展示：

- **新闻面**：用“宏观相关词过滤 + 情绪短语词典 + 否定词/程度副词 + 数字幅度”打分。不是让大模型凭感觉判断，每条新闻都会显示命中了哪些词，方便复核。
- **政策信号**：降准/降息/财政加码/收储等偏宽松，加息/收紧/严监管等偏收紧。 routine 的逆回购不再计入政策信号，避免把日常流动性操作误判成“大宽松”。

最终判断会组合“数据现实”和“新闻预期”，例如：

- 数据偏弱 + 新闻偏乐观 → “弱现实、强预期，政策发力期关注落地效果”；
- 数据偏弱 + 新闻偏悲观 → “数据与情绪共振向下，短期以防御为主”；
- 数据偏强 + 新闻偏悲观 → “数据尚可但预期转弱，警惕后续动能衰减”。

### 数据健康度

看板底部会列出：

- 权重覆盖率；
- 缺失/滞后/过期的指标；
- 各新闻源是否可用、抓了多少条。

月度数据超过 75 天视为“滞后”（权重 ×0.6），超过 120 天视为“过期”（不计入总分）；季度数据阈值是 150 / 240 天。这样不会拿半年前的社融数据假装“今天的经济”。

---

## 3. 每天自动跑

### Windows 计划任务

```powershell
# 默认每天 08:30，生成报告但不自动弹浏览器
powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1

# 每天 08:30 和 18:30 各跑一次，并自动打开报告
powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1 -Time "08:30","18:30" -OpenReport
```

卸载：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall_task.ps1
```

任务默认以当前用户身份、仅在登录时运行。日志在 `logs\`。如果想在未登录时也跑，需要用“不管用户是否登录都要运行”并保存凭据，或在服务器上用 cron。

### macOS / Linux cron

```bash
cd /opt/econ
crontab -e
# 每天 08:30
30 8 * * * cd /opt/econ && /usr/bin/python3 run.py >> logs/cron.log 2>&1
```

---

## 4. 境外新闻、VPN 与境外部署

### 4.1 境外新闻源

配置在 `config.yaml` 的 `news.overseas`，包括 FT中文网、BBC中文、纽约时报中文网、德国之声、联合早报、日经中文网、CNBC、MarketWatch、美联储、IMF Blog、Google News 等。

默认 `enabled: auto`：**能连上就用，连不上就自动跳过**，不会拖慢整份报告。当前网络下 CNBC、MarketWatch 等可以直连；FT、BBC、Google News 等通常需要代理。

### 4.2 开 VPN 时怎么配

在 `config.yaml` 里填本地代理（Clash 常见 `7890`，v2ray 常见 `10809`）：

```yaml
network:
  proxy: "http://127.0.0.1:7890"
  proxy_for: "overseas"   # 只让境外新闻走代理，国内数据直连
```

也可以临时覆盖：

```powershell
python run.py --proxy http://127.0.0.1:7890
python run.py --check --proxy http://127.0.0.1:7890
```

`proxy_for` 可选：

- `overseas`：只代理境外新闻（推荐；国内数据不绕路）；
- `all`：所有请求都走代理；
- `none`：从不使用代理。

### 4.3 直接部署在境外可以吗？

可以，而且这是更省心的长期方案。建议：

| 部署位置 | 国内数据（akshare/东财/官方站） | 境外新闻 | 建议 |
|---|---|---|---|
| 中国境内 + VPN | 快 | 需代理 | 适合个人电脑 |
| **香港 / 新加坡 VPS** | 通常可直连 | 通常可直连 | **最推荐**，两边都通 |
| 美国 / 欧洲 VPS | 多数可访问，但东财/部分接口可能慢或被限 | 原生可用 | 先跑 `--check`，失败源会自动跳过 |

部署步骤（Docker）：

```bash
git clone <你的仓库> /opt/econ && cd /opt/econ
# 按需编辑 config.yaml：代理、权重、LLM
docker compose -f deploy/docker-compose.yml build
docker compose -f deploy/docker-compose.yml run --rm econ
```

`deploy/` 里已经放了 `Dockerfile`、`docker-compose.yml` 和 `crontab.example`。镜像内置 Noto CJK 字体，中文图表不会乱码。

境外部署的注意点：

1. **时区**：容器已设 `TZ=Asia/Shanghai`；cron 也按北京时间。
2. **国内源失败**：先 `python run.py --check` 看具体哪个源不通；程序会自动用本地缓存，不会因此不生成报告。
3. **静态报告**：`reports/` 是纯静态 HTML，可以用 nginx 直接托管，手机也能看。
4. **如果国内源在境外不稳定**：优先选香港/新加坡，而不是美国西海岸。
5. **容器里的代理地址**：`127.0.0.1` 指的是容器自己；如果要走宿主机的 VPN，Windows/macOS 填 `http://host.docker.internal:7890`，Linux 用宿主机内网 IP。

### 4.4 免费托管：GitHub Actions + GitHub Pages（推荐给没有服务器的人）

这是最省事的免费方案：GitHub 提供临时的 x86_64 Linux 机器（每次 7GB 内存），每天定时跑一次，跑完把 `reports/` 发布成静态网站。你不需要买服务器，也不需要 NAS。

仓库里已经放好两个工作流：

- `.github/workflows/check.yml`：手动检查数据源连通性
- `.github/workflows/daily.yml`：每天北京时间 08:30 自动生成报告并发布

**设置步骤：**

1. **注册 GitHub**：用你的 Google 邮箱注册即可；打开 VPN。
2. **新建仓库**：New repository → 名称例如 `econ-monitor` → 选 **Public**（免费额度最充足）→ Create。
3. **上传项目**：推荐用 [GitHub Desktop](https://desktop.github.com/)：
   - Clone 刚建的仓库到本地；
   - 把 `D:\经济` 里的文件复制进去（至少包括 `run.py`、`config.yaml`、`requirements.txt`、`econ/`、`.github/`、`deploy/`）；
   - Commit → Push。
   - 注意 `.github` 是隐藏文件夹；GitHub Desktop 会自动识别。
4. **开启写权限**：仓库 Settings → Actions → General → Workflow permissions → 选 **Read and write permissions** → Save。
5. **开启 Pages**：Settings → Pages → Build and deployment → Source 选 **GitHub Actions**。
6. **先测数据源**：Actions → **Check Data Sources** → Run workflow。看日志里境内/境外源是否 OK。如果东财、统计局等大量 FAIL，说明 GitHub 美国 runner 访问国内源不稳，改用 Oracle 日本/新加坡（见 4.3）。
7. **跑第一次日报**：Actions → **Daily Econ Report** → Run workflow。约 2–3 分钟。
8. **打开网站**：`https://你的用户名.github.io/econ-monitor/`。以后每天 08:30 自动更新。

**注意：**

- GitHub 的 cron 用 UTC，北京时间 08:30 对应 `30 0 * * *`；GitHub 可能延迟几分钟到半小时。
- 公共仓库的 Actions 免费；私有仓库每月 2000 分钟，这个任务每天约 2 分钟，一个月约 60 分钟，也够用。私有仓库的 Pages 需要付费，公共仓库免费。
- 报告和历史都会 commit 回仓库，公开仓库意味着这些宏观数据公开；不要往仓库里放 API key。LLM key 放在 Settings → Secrets and variables → Actions → New repository secret，名称 `ECON_LLM_API_KEY`。
- 如果某天数据源临时失败，程序会用缓存/跳过，不会让整个任务失败；但第一次运行没有缓存，建议先跑 `Check Data Sources`。

### 4.5 当前网络没有 VPN 会怎样？

不会报错。境外源会显示为失败 chip，报告照常生成；国内数据和新闻不受影响。等 VPN 开了，下一次运行会自动启用。

---

## 5. 可选：大模型解读

不填 key 也能用，文字由规则引擎生成。想让它写得更像分析师，可以接一个 OpenAI 兼容接口（默认 DeepSeek）：

```powershell
setx ECON_LLM_API_KEY "sk-你的key"
# 重新打开终端后生效
python run.py
```

或在 `config.yaml`：

```yaml
llm:
  enabled: auto          # auto = 有 key 就用
  base_url: "https://api.deepseek.com"
  model: "deepseek-chat"
  api_key: ""            # 不建议把 key 写进公开仓库
```

大模型只负责写“判断/综述/风险/关注”，**不允许编造数字**；所有数字仍来自本地数据。调用失败会自动回退到规则版，不影响报告生成。

---

## 6. 数据口径与已知边界

### 数据来源

- 国家统计局：PMI、CPI、PPI、GDP、工业增加值、社零、固投、消费者信心
- 中国人民银行：M2/M1、新增人民币贷款、LPR
- 海关总署：出口同比
- 东方财富：70 城房价（全量 70 城）、指数/汇率行情
- 上海期货交易所 / 上海国际能源交易中心：沪铜、原油、沪金
- 美国财政部 / 美国劳工部（经 akshare）：美债收益率、美国 CPI
- 新闻：新浪财经、东方财富快讯、华尔街见闻、国家统计局、央行、财政部、发改委；境外 RSS 可选

### 重要边界

1. **不是预测模型**。它给的是当前状态和 3 个月方向，不预测下个季度 GDP 或点位。
2. **数据会修订**。所有指标都按“最新可得值”计算，历史序列会被修订影响。
3. **70 城房价来自东方财富的转引**，不是直接抓统计局 HTML；口径为 70 城新建商品住宅价格指数。
4. **新闻情绪是词典法**，对反讽、复杂因果、长文语境的把握有限；它的价值是“可解释、稳定、零成本”，不是“比人更懂新闻”。重要判断仍建议点开原文。
5. **美国 CPI / 失业率等海外数据经第三方转引**，极端情况下可能滞后；程序会标注“滞后/过期”，不会强行打分。
6. **政策信号**只识别常见表述，不能替代对政策文件的完整阅读。
7. **权重和锚点是主观的**。它们代表一种“常识区间”，不是物理定律；你可以按自己的研究框架改 `config.yaml` 和 `econ/registry.py`。

---

## 7. 目录结构

```
D:\经济\
├─ run.py                     # 入口
├─ config.yaml                # 配置：代理、新闻源、权重、LLM
├─ requirements.txt
├─ 每日经济观察.bat            # Windows 双击运行
├─ econ\
│  ├─ registry.py             # 指标定义、权重、打分锚点
│  ├─ collect\macro.py        # 宏观/地产数据
│  ├─ collect\market.py       # 指数、汇率、商品
│  ├─ collect\news.py         # 新闻抓取与解析
│  ├─ analyze\scoring.py      # z 分数、五维合成、历史序列
│  ├─ analyze\sentiment.py    # 新闻情绪与政策信号
│  ├─ analyze\narrative.py    # 规则版 / LLM 版解读
│  ├─ report\charts.py        # SVG 图表
│  ├─ report\html.py          # HTML 看板
│  ├─ report\markdown.py      # Markdown 日报
│  ├─ store.py                # SQLite
│  └─ pipeline.py             # 主流程
├─ scripts\
│  ├─ install_task.ps1        # 注册 Windows 计划任务
│  └─ uninstall_task.ps1
├─ deploy\
│  ├─ Dockerfile
│  ├─ docker-compose.yml
│  └─ crontab.example
├─ data\                      # 缓存、SQLite、latest.json
├─ reports\                   # HTML / Markdown 报告
└─ logs\
```

---

## 8. 常见问题

**Q：运行很慢？**
首次运行要抓十几个数据源，约 30–60 秒；之后有缓存会快一些。`--offline` 可以完全用缓存，秒出报告。

**Q：某个指标显示“缺失/滞后”？**
先看 `logs\` 里的错误，再跑 `python run.py --check`。单个源失败不会影响整份报告；程序会尽量用上一次缓存。

**Q：新闻太少或太多？**
调 `config.yaml` 的 `news.window_hours`（媒体回看窗口）和 `news.max_report_items`。相关性过滤在 `econ/analyze/sentiment.py` 的 `CHINA_WORDS` / `STRONG_MACRO` / `CORPORATE` 里。

**Q：想改权重？**
改 `config.yaml` 的 `pillars` 即可；想改单个指标的权重或锚点，改 `econ/registry.py` 里对应 `Indicator`。

**Q：想加一个新闻源？**
在 `config.yaml` 的 `news.domestic` 或 `news.overseas` 加一项，`type` 选 `rss`、`official`、`sina_roll`、`eastmoney_flash`、`wscn_live` 之一。RSS 源最省事。

**Q：报告里的中文在记事本里乱码？**
HTML 和 Markdown 都是 UTF-8；用 VS Code、Typora、浏览器打开即可。Windows 控制台如果乱码，双击 `每日经济观察.bat`（已设 UTF-8）。

**Q：能不能推到微信/邮件？**
当前版本输出 HTML/Markdown，没有内置推送。最简单的方式：用 nginx 托管 `reports/`，或加一个 cron 把 `reports/YYYY-MM-DD.md` 发邮件；需要的话可以在这套结构上扩展。

---

## 9. 免责声明

本项目只做公开数据的整理与可视化，所有判断由规则/模型自动生成，可能存在错误、滞后或偏差。它不构成任何投资、交易、政策或法律建议。使用前请自行核对原始数据。
