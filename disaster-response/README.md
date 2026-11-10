# CivicOps Resilience · Malaysia

马来西亚灾难决策支持**研究原型 v0.1**。把暴露人口、道路可达性、PPS 容量和第一波资源建议放进可复现的框架。第一版是 Klang–Shah Alam 背景的**完全虚构洪灾演练**。

**所有社区、路网、人口、资源和避难所都是合成资料。它不是实时救援系统，不提供真实撤离导航。**

网页使用与 Python 结果对齐的 JavaScript 引擎；Python CLI 和可选 FastAPI 可在自己的电脑运行。发布的静态网页没有远程运行 Python、R 或 Power BI。

## 已实现的内容

| 能力 | 本版实现 | 验证边界 |
|---|---|---|
| APROM / Python | 验证、算法、CLI、结构化导出 | 已运行 |
| Predictive Analytics | Logistic 合成基线、滞后特征、时间留出、Brier | 教学数据；不参与路线决策 |
| Stochastic Processes | 三状态 Markov、共同道路冲击、随机需求、Monte Carlo | 概率与分布全部是假设 |
| OR / 撤离 | 整数最小费用最大流，双向道路共享通量，PPS 剩余容量 | 静态分配；不是完成撤离时间模型 |
| 前线资源 | 能力匹配、每项资源一个第一波任务、可达性与时间筛选 | 与人口流分开求解；未联立车辆座位 |
| GIS / SQL | WGS84 GeoJSON、SQLite、SQL 查询 | 已验证；OSM 联网导入尚未执行 |
| Power BI | CSV、Power Query M、DAX、报表配置说明 | 未在 Power BI Desktop 中执行 |
| RStudio | `.Rproj`、Base R Markov 与守恒检查 | 当前环境未安装 R，尚未执行 |
| GitHub / Codex | 独立分支、项目 AGENTS.md、测试与接手任务 | Codex Cloud 环境仍需在账户里选仓库 |

网页可以更改灾情压力、通量窗口、PPS 容量、行程时间、无障碍筛选，关闭单条道路或 PPS，再重新分配。支持方案 JSON 和路线 CSV 导出。已整理 12 个官方 / 开源来源，区分“已实现”“连接器待在线验证”和“未来候选”。

## 在电脑上运行

需要 Python 3.11+；测试网页引擎还需要 Node.js 20+。从 GitHub 独立分支检出后，进入 `disaster-response` 目录：

```sh
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -e .
python -m disaster_response.cli plan --out outputs
python -m disaster_response.cli stress --runs 100 --out outputs
python -m disaster_response.cli train-demo --out outputs
python -m unittest discover -s tests -v
node tests/parity.mjs
```

打开网页：

```sh
python -m http.server 8000 --directory dist
```

浏览器访问 `http://localhost:8000`。不能直接双击 HTML，因为浏览器需要通过 HTTP 读取演练 JSON。

可选 Python API：

```sh
python -m pip install -e '.[api]'
uvicorn disaster_response.api:app --host 127.0.0.1 --port 8001
```

`GET /health`；`POST /plan` 的请求示例：`{"options":{"pressure":1.8}}`。这只是本机演练 API。线上静态 Site 与它没有自动建立连接。

## 数据与可复现性

- `data/demo/scenario.json` 是 Python 的演练输入；`dist/scenario.json` 是网页对应副本。
- 演练时钟固定为 **2026-11-10 09:00 Asia/Kuala_Lumpur**；不是用户打开网页时的实时时钟。
- 演练内默认排除 R02（关闭）和 R10（观测过期）。无障碍筛选默认排除 PPS D。
- 基准人口 1,460；静态分配 1,260；未分配 200；第一波资源建议 12 / 22 个需求单位。需要协助群体共 400 人。
- `dist/exports/` 是可复现的基准输出；所有输出均带合成数据标识。
- Python 与浏览器的**确定性规划**经过一致性验证；Monte Carlo 使用不同随机数生成器，结果不逐样本相同。

## 进一步阅读

- [数学模型、假设与限制](docs/MODEL.md)
- [数据接入与开源项目核查](docs/SOURCES.md)
- [Power BI、QGIS、SQL、RStudio 与 Codex 接手](docs/INTEGRATIONS.md)
- [从原型到前线试点的研究路线](docs/ROADMAP.md)
- [验证记录](docs/VALIDATION.md)

本项目在原 CivicOps AI 的独立分支下开发，未合并到主分支。
