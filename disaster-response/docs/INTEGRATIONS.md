# Python、Power BI、SQL、GIS、RStudio 与 Codex

## 导出后看哪些文件

运行 `python -m disaster_response.cli plan --out outputs` 后得到 `plan.json`、`community_plan.csv`、`shelter_plan.csv`、`route_plan.csv`、`road_usage.csv`、`resource_dispatch.csv`、`scenario_metadata.csv`、`exercise.geojson` 和 `planning.sqlite`。

每次导出代表一个情景，SQLite 会替换同名结果表。若做历史追踪，应加入 `run_id`、版本和数据哈希，不能直接混合追加。

## Power BI Desktop

当前提供导入脚本与度量值，没有创建或运行 `.pbix`。

1. 在 Power BI Desktop 使用 **Get data / Text/CSV** 选择 `community_plan.csv`，查询命名为 `CommunityPlan`。
2. 或创建文本参数 `ExportFolder`，值为本机 `outputs` 文件夹绝对路径；在空白查询的 Advanced Editor 粘贴 `powerbi/CommunityPlan.pq`。
3. 在 `CommunityPlan` 上按条创建 `powerbi/Measures.dax` 的度量值，覆盖率格式设为百分比。
4. 同样导入 `shelter_plan`、`road_usage`、`resource_dispatch`、`route_plan` 与 `scenario_metadata`。当前 CSV 都是同一演练情景；不要仅凭同名 `id` 在社区和 PPS 表之间建立错误关系。
5. 第一页用需求、分配、缺口和覆盖率卡片；第二页按社区列出未分配与需协助缺口；第三页显示 PPS 名额和道路通量。顶部始终显示 `SYNTHETIC EXERCISE` 与演练时钟。

Power Query 入口会随版本改变，请参考 [Microsoft 官方数据连接说明](https://learn.microsoft.com/en-us/power-bi/connect-data/desktop-data-sources)。CSV 接入可用；未假设 Power BI 内置 SQLite 连接器。

## SQL

使用 SQLite 客户端打开 `outputs/planning.sqlite`，执行 `sql/analysis.sql`。其中包含社区缺口、PPS 占用、道路超容量和资源重复分配检查。

`sql/postgis_staging.sql` 是 PostgreSQL/PostGIS 后续结构蓝图，尚未执行。危险区空间相交仅标记待审 / 禁入，不把不相交路段自动认定为安全。

## QGIS / OSMnx

直接在 QGIS 打开 `outputs/exercise.geojson`，选择 EPSG:4326；它包含抽象道路、社区和 PPS，所有点均有合成标识。几何顺序为 `[longitude, latitude]`。真实距离与面积分析应使用合适投影，不能将经纬度差当作米。

需要真实路网时，安装 `pip install -e '.[gis]'`，再运行 `python scripts/import_osm.py --place 'Klang, Selangor, Malaysia'`。此脚本将路段默认标为 `unverified`，不输出可直接用于救援的通行图。本轮只核对了 [OSMnx 公开 API 文档](https://osmnx.readthedocs.io/en/stable/user-reference.html)，没有联网运行该导入。

## RStudio

打开 `r/CivicOpsResilience.Rproj`，运行 `source('validate_markov.R')`。脚本用 Base R 检查转移矩阵，计算三小时状态分布，做固定 seed 的模拟，并在存在 Python CSV 时检查人口守恒。

R 的 seed 与 Python / 浏览器 seed 不会产生相同样本。当前构建环境没有 R，未把该脚本标为已执行。

## Codex / GitHub

GitHub 已通过当前连接器确认账号与仓库访问；代码在 `codex/malaysia-disaster-model-v1` 分支的 `disaster-response/`。原有 app 与主分支不变。

已放置项目 `AGENTS.md`，包含运行命令、数据模式、模型约束与后续任务。官方文档说明 AGENTS.md 可作为 Codex 的持久项目指引：[OpenAI 官方说明](https://learn.chatgpt.com/docs/agent-configuration/agents-md)。

**当前连接器没有创建 Codex Cloud 环境的操作；额外浏览器检查显示 Codex 登录入口，没有可用的登录会话，因此云端环境尚未连接。** 如需后续云端任务，在 ChatGPT/Codex 的 Cloud Environments 中创建环境，选择 `chan-js/civciops-ai-build-week`；任务使用上述开发分支，工作目录为 `disaster-response`。安装 `python -m pip install -e .`，执行 README 中的测试和命令。配置流程以 [OpenAI 官方 Cloud Environments 文档](https://learn.chatgpt.com/docs/environments/cloud-environments) 为准。

可直接给 Codex 的下一条任务：

> 读取 disaster-response/AGENTS.md。限定在该目录开发，为 Selangor 的一个试点区设计真实道路与 PPS 观测适配器，增加来源、时效和空间相交验证；保留 synthetic_exercise 默认模式。运行 Python 测试和浏览器一致性检查，不将未核实资料变成可通行道路。
