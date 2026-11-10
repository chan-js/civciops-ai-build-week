# 数据与开源来源核查

核查日期：2026-11-10。以下列出**官方原始资料或项目维护者来源**。网页展示不等于稳定、获授权、可批量复用的接口。本轮没有抓取个人、灾民登记或家庭查询资料。

| 来源 | 可支持什么 | 本版接入情况 | 原始链接 |
|---|---|---|---|
| MET Malaysia / data.gov.my | 预报、天气与地震预警 | 已验证网页手动读取；Python 样本连接器已编写；未输入规划 | [官方 Weather API](https://developer.data.gov.my/realtime-api/weather) |
| JPS | 河流水位与雨量监测 | 官方门户已核对；稳定接口与复用条款未确认 | [Public Infobanjir](https://publicinfobanjir.water.gov.my/) |
| JKM | PPS 与灾民汇总 | 官方入口已核对；逐 PPS 实时名额接口未确认 | [InfoBencana](https://infobencanajkmv2.jkm.gov.my/landing/index.php) |
| NADMA | 多灾种态势与技术机构入口 | 用作权威核对来源；没有复制实时统计 | [Portal Bencana](https://portalbencana.nadma.gov.my/ms/) |
| DOSM | 行政区人口及年龄结构 | 已提供 20 条样本获取与单位转换函数；未作撤离人数 | [人口目录](https://data.gov.my/data-catalogue/population_district) |
| WorldPop | 空间人口栅格 | 未来暴露层候选，按产品核对年份与许可 | [WorldPop](https://www.worldpop.org/) |
| HOT / OSM | 人道制图、道路与设施 | OSM 导入脚本已编写，未联网执行 | [HOT 灾害响应](https://www.hotosm.org/en/impact-areas/disaster-response/) |
| Copernicus CEMS 全球洪灾入口 | 洪灾监测与预测研究 | 后续水文层候选；没有下载产品或宣称具体分辨率 | [CEMS Global Flood](https://global-flood.emergency.copernicus.eu/) |

## 接口细节与陷阱

当前官方天气文档列出 `/weather/forecast`、`/weather/warning`、`/weather/warning/earthquake`，天气资料许可为 CC BY 4.0。预报每天更新，预警按需要更新。[原始文档](https://developer.data.gov.my/realtime-api/weather)

官方开放 API 文档当前列出每类接口每分钟 4 次请求的限制；本连接器不循环重试，网页有最小请求间隔。[限流说明](https://developer.data.gov.my/rate-limit)

旧 changelog 曾提及 `/flood-warning`；本轮未能在当前文档核实该接口，因此没有将它写成已可用连接器。浏览器已于 2026-11-10 21:27 MYT 成功读取气象 API 返回；这不代表 Python 连接器或所有端点已完成在线验证。Python 请求失败会保留 `records: null`，不会表示“无灾情”。

DOSM 的 `population` 单位是**千人**。总计、性别、族群和年龄分组彼此有重叠，不能直接相加。地区年度估计不能代表事件当天暴露人口；应与独立的栅格人口、灾害足迹和实际现场报告校核。[变量与许可说明](https://data.gov.my/data-catalogue/population_district)

PPS 的存在、灾民总数、登记容量、剩余名额、无障碍设施、所在建筑安全与实时开放状态是不同字段；需要逐项确认。OSM 的道路存在也不等于灾中可通行。

## GitHub 开源项目

通过 GitHub 连接器实际检索并核对 OSMnx、OR-Tools、OSRM 和 Sahana Eden 的项目资料及许可；同时查阅 InaSAFE 与 CLIMADA 的维护者资料。

| 项目 | 许可（查阅时） | 用途与取舍 | 本版状态 |
|---|---|---|---|
| [gboeing/osmnx](https://github.com/gboeing/osmnx) | MIT | Python GIS 路网获取与转换 | 已编写可选导入脚本；未安装 / 联网运行 |
| [google/or-tools](https://github.com/google/or-tools) | Apache-2.0 | 车辆容量、时窗、多任务调度 | 下一阶段候选；当前算法为原创实现 |
| [Project-OSRM/osrm-backend](https://github.com/Project-OSRM/osrm-backend) | BSD-2-Clause | 自托管路由及时间矩阵 | 未部署；不使用公共 demo 服务作救援路径 |
| [sahana/eden](https://github.com/sahana/eden) | MIT | 人道信息管理与应用架构 | 参考；未部署或复制代码 |
| [inasafe/inasafe](https://github.com/inasafe/inasafe) | GPL-3.0 | 灾害影响与 GIS | 研究候选；兼容性待查；未集成 |
| [CLIMADA-project/climada_python](https://github.com/CLIMADA-project/climada_python) | GPL-3.0 | 精算与气候风险、暴露、脆弱性 | 研究候选；不等同分钟级调度；未集成 |

Sahana 基金会说明 2025 年 5 月 Eden ASP 成为主线，旧 Eden 代码归档；因此避免直接把旧仓库教程当作当前部署说明。[基金会原文](https://new.sahanafoundation.org/eden/)

原型没有复制以上项目代码，也没有安装未核查的未知救灾仓库。可选依赖与数据许可需要在真正引入时再次核对；OSM 数据许可和 OSMnx 代码许可并非同一种许可。
