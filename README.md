# 湖仓一体化治理平台

面向数据架构师的湖仓一体化治理平台。覆盖数据湖表格式管理、Iceberg/Hudi表优化、小文件合并、数据压缩策略、元数据服务、表快照管理、数据分支合并与数据回滚恢复的完整湖仓治理链路。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 湖表格式管理 | `tablefmt` | 表格式配置 | 配置编号、表名称、格式类型 |
| 小文件合并 | `compact` | 合并任务 | 任务编号、目标表名、文件范围 |
| 数据压缩策略 | `compress` | 压缩配置 | 配置编号、目标表名、压缩算法 |
| 元数据服务 | `metadata` | 元数据表 | 表编号、表名称、字段清单 |
| 表快照管理 | `snapshot` | 快照记录 | 快照编号、表名称、快照时间 |
| 数据分支合并 | `branch` | 分支记录 | 分支编号、表名称、分支类型 |
| 数据回滚恢复 | `rollback` | 回滚记录 | 记录编号、表名称、回滚版本 |
| 分区演进管理 | `partition` | 演进计划 | 计划编号、表名称、当前分区 |
| 表优化管理 | `iceberg` | 优化任务 | 任务编号、表名称、优化类型 |
| 数据目录同步 | `catalog` | 同步作业 | 作业编号、源路径、目标目录 |
| 数据过期清理 | `cleanup` | 清理策略 | 策略编号、目标表名、过期条件 |
| 湖存储配额 | `quota` | 配额配置 | 配置编号、存储空间、表数量上限 |
| 湖仓血缘追踪 | `lineage` | 血缘记录 | 记录编号、上游表名、下游表名 |
| 治理任务调度 | `schedule` | 治理任务 | 任务编号、任务类型、调度表达式 |
| 表统计信息 | `stats` | 统计报告 | 报告编号、表名称、行总数 |
| 数据迁移管理 | `migrate` | 迁移任务 | 任务编号、源表名、目标表名 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 回滚恢复预演

数据回滚恢复支持读取回滚记录并预演恢复，预演逻辑在
`backend/app/services/rehearsal.py`，把三类约束联动成同一份回滚影响范围：

- **快照可达性判定标准**：回滚版本必须在表快照中存在「可恢复/保留中」状态的快照，
  否则整单预演不成立、影响范围内表全部进入待处理；
- **迁移状态范围**：下游表存在「待执行/迁移中」的未提交迁移任务时，不能进入
  已完成恢复集合，只进入待处理并附原因（如 `MIGR-20261115-17` 待提交）；
- **恢复条件**：快照可达且无未提交迁移的下游表，采用迁移提交后的最新可恢复表版本
  进入预演；超出允许范围的表统一进入待处理说明。

预演与下游迁移提交在同一时间窗口冲突时，只发布一份对应完整边界的恢复结果：
未提交迁移的表列入待处理，已提交的表（如 `ads_finance_monthly`）采用迁移提交后的
表版本 `v20261118-post-migr` 进入预演。

| 接口 | 说明 |
| --- | --- |
| `POST /api/rollback/{id}/rehearsal` | 提交回滚预演，合成恢复计划并写回血缘影响清单 |
| `GET /api/rollback/{id}/rehearsal` | 读取同一预演批次（恢复快照、下游表、未提交迁移） |
| `GET /api/rollback/rehearsals` | 全部预演批次列表 |
| `GET /api/lineage/impacts` | 血缘影响清单，与回滚入口同源，保留下游表与迁移批次关系 |
| `GET /api/lineage/impacts/summary` | 按预演批次汇总影响范围与版本结论 |

前端在「数据回滚恢复」页面提交预演并打开影响详情逐项核对，在「湖仓血缘追踪」
页面核对同一份血缘影响清单，两个入口的回滚影响范围数据一致。示例场景：
`finance_ledger` 回滚到 `v20261110`，下游 `report_finance`、`dws_ledger_daily`、
`ads_finance_monthly` 全部进入影响范围，其中 `dws_ledger_daily` 因
`MIGR-20261115-17` 待提交而列入待处理。

领域：数据工程
子方向：数仓与数据湖
