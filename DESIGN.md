# 模拟夺标游戏位置服务 — 详细设计说明

## 1. 文档目的与范围

本文档描述「模拟夺标游戏位置服务」的服务端架构、领域模型、接口契约、核心算法、并发与时间假设、通知机制及已知局限，作为课程设计的技术说明与实现依据。

**范围**：多竞赛并行、内存存储、HTTP API + SSE 推送；不包含认证、授权与持久化。

**实现载体**：Node.js 20+（建议）+ Express 4.x；测试客户端为 Python 3 + `requests`。

---

## 2. 需求映射

| 序号 | 需求摘要 | 设计落点 |
|------|-----------|----------|
| 1 | 指定终点坐标新建竞赛，返回竞赛 ID | `POST /competitions`，内存分配唯一 `competitionId` |
| 2 | 在指定竞赛下创建团队，ID 冲突报错 | `POST /competitions/:id/teams`，`Map` 判重 |
| 3 | 上报竞赛/团队/成员/坐标，记录时间，判定终点；缺参报错；已结束返回结束与夺标队 | `POST /reports`，统一校验与状态机 |
| 4 | 查询终点；已结束则返回已结束与夺标团队 ID | `GET /competitions/:id/target` |
| 5 | 查询是否结束 | `GET /competitions/:id/status` |
| 6 | 竞赛结束时通知正在参赛的成员 | `GET /competitions/:id/stream`（SSE），向已登记连接广播 |

---

## 3. 业务规则（形式化）

### 3.1 坐标与距离

- 平面直角坐标系，欧氏距离  
  \(d(p, t) = \sqrt{(x - x_t)^2 + (y - y_t)^2}\)

### 3.2 成员到达终点

- 条件：`d < 2.0`（严格小于，与题面一致）。
- 同一成员仅首次满足条件时记入「已到达集合」；重复上报不增加计数。

### 3.3 团队到达终点

- 条件：该团队「已到达集合」大小 ≥ 3（三名**不同**成员）。

### 3.4 夺标团队与竞赛结束

- **夺标团队**：本场竞赛中**最先**达到「团队到达终点」条件的团队。
- **最先**以服务器在处理该次位置上报时记录的 **`reportTime`（ISO 8601 时间戳）** 为准：在本次上报的处理过程中，若某团队由「未达标」变为「达标」，则将该时刻记为该队**首次达标时刻**；全场第一个产生达标事件且使竞赛尚未结束的团队即夺标。
- 竞赛**一旦夺标即刻结束**；结束后状态只读（不再产生新的夺标结果）。
- **平局**：若两个团队在同一毫秒（`Date` 精度内）同时首次达标，实现上后以**先完成 Express 请求处理**的团队为准；可在说明中归类为「时钟精度内的极小概率事件」。如需严格全序，可改为引入单调递增序号器作为第二排序键（当前实现未引入，保持简单）。

---

## 4. 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                      HTTP 客户端 / 脚本                    │
│                 (Python client_test.py 等)               │
└───────────────┬──────────────────────┬──────────────────┘
                │ REST JSON              │ SSE (text/event-stream)
                ▼                        ▼
┌───────────────────────────────────────────────────────────┐
│                     Express 应用 (server.js)                 │
│  ├─ 路由：竞赛 / 团队 / 上报 / 查询 / 订阅                     │
│  ├─ 领域状态：competitions Map（内存）                       │
│  └─ 通知：notifyCompetitionFinished → 向 subscribers 写 SSE    │
└───────────────────────────────────────────────────────────┘
```

- **单进程、单线程事件循环**：请求串行进入，避免锁；状态变更集中在「上报」路径，便于推理。
- **无数据库**：进程重启则数据清空。

---

## 5. 数据模型

### 5.1 Competition（竞赛）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 形如 `COMP_1` 的唯一 ID |
| `target` | `{ x: number, y: number }` | 终点坐标 |
| `finished` | boolean | 是否已结束 |
| `winnerTeamId` | string \| null | 夺标团队 ID |
| `finishedAt` | string \| null | ISO 时间，夺标/结束时刻 |
| `teams` | Map\<teamId, Team\> | 已注册团队 |
| `subscribers` | Map\<subscriberKey, Set\<Response\>\> | SSE 订阅者（每个 key 下可能多个连接） |

### 5.2 Team（团队）

| 字段 | 类型 | 说明 |
|------|------|------|
| `teamId` | string | 用户自定义 ID |
| `members` | Map\<memberId, Member\> | 成员上报痕迹（最近位置、是否曾到达等） |
| `arrivedMembers` | Set\<memberId\> | 曾满足 `d < 2.0` 的成员集合 |

### 5.3 Member（成员，可选持久细节）

| 字段 | 说明 |
|------|------|
| `lastPosition`, `lastReportAt` | 最近上报 |
| `arrived`, `arrivedAt` | 是否曾达标及首次达标时间 |

### 5.4 subscriberKey

- 格式：`${teamId}:${memberId}`，用于区分订阅身份并支持同身份多连接（如重复打开页面）。

---

## 6. API 设计

### 6.1 通用约定

- `Content-Type: application/json`（GET SSE 除外）。
- 错误时返回 JSON，含 `error` 字段。

### 6.2 `POST /competitions`

**请求体**（二选一字段名兼容实现）：

```json
{ "x": 10, "y": 20 }
```

或 `endX` / `endY`（与题面表述一致时可选用）。

**成功 201**：

```json
{ "message": "竞赛创建成功", "competitionId": "COMP_1", "target": { "x": 10, "y": 20 } }
```

### 6.3 `POST /competitions/:competitionId/teams`

**请求体**：`{ "teamId": "Alpha" }`

- 竞赛不存在 → `404`
- 竞赛已结束 → `400`，禁止新团队
- 团队 ID 已存在 → `400`，明确错误提示
- 成功 → `201`，`团队创建成功`

### 6.4 `POST /reports`

**请求体**：

```json
{
  "competitionId": "COMP_1",
  "teamId": "Alpha",
  "memberId": "M1",
  "x": 10.1,
  "y": 9.9
}
```

**处理顺序（重要）**：

1. 校验 `competitionId、teamId、memberId、x、y` 齐全且数值合法 → 否则 `400`
2. 竞赛不存在 → `404`
3. **若竞赛已结束** → `200` + `message/status/winnerTeamId/...`（不要求团队仍存在，满足题面「已结束」提示）
4. 团队未注册 → `404`
5. 计算距离、更新成员与 `arrivedMembers`，判断是否触发夺标；若触发则 `notifyCompetitionFinished`

**成功未结束 200**示例字段：`message`, `competitionId`, `status: 未结束`, `reportTime`, `distance`, `memberArrived`, `memberArrivedNow`, `teamArrivedCount`

**夺标当次 200**：`status: 已结束`, `winnerTeamId`, `finishedAt`, 等

### 6.5 `GET /competitions/:competitionId/target`

- 未结束：`competitionId`, `status: 未结束`, `target`
- 已结束：与 `buildFinishedPayload` 一致（含 `winnerTeamId`）

### 6.6 `GET /competitions/:competitionId/status`

- 未结束：`status: 未结束`
- 已结束：含夺标团队 ID 与结束信息

### 6.7 `GET /competitions/:competitionId/stream?teamId=&memberId=`

- `Content-Type: text/event-stream`
- 首次 `event: connected`
- 若已结束，紧接着 `event: competition-finished` 后结束响应
- 未结束：周期性 `: keepalive` 注释行保活；竞赛结束时服务端向该场所有已登记连接写入 `competition-finished`
- `close` 时从 `subscribers` 摘除，防止内存泄漏

---

## 7. 核心流程（位置上报）

```
开始
  → 校验参数
  → 加载 Competition
  → 若 finished → 返回结束摘要
  → 加载 Team（未注册 → 404）
  → reportTime = now()
  → d = hypot(x - tx, y - ty)
  → 若 d < 2 且成员未记到达 → arrivedMembers += memberId
  → 若 |arrivedMembers| >= 3 且 !finished
        → finished=true, winnerTeamId=当前队, finishedAt=reportTime
        → SSE 广播
        → 返回夺标响应
  → 否则返回普通成功响应
结束
```

---

## 8. 通知语义

- **推送对象**：已通过 SSE 建立连接且 `teamId/memberId` 合法的成员端。
- **尽力推送**：网络断开期间的事件不补发；客户端可通过 `GET .../status` 补偿。
- **与 HTTP 一致性**：广播 payload 与 `buildFinishedPayload` 同源字段，避免歧义。

---

## 9. 测试策略（客户端）

- 创建两场竞赛，验证 ID 独立。
- 团队重复创建：期望 400。
- 上报缺参：期望 400。
- 三成员陆续进入终点半径：夺标队正确。
- 竞赛结束后继续上报：返回结束信息与 `winnerTeamId`，非 404。
- 多 SSE 订阅者：均在夺标后收到 `competition-finished`。

---

## 10. 已知局限与非功能说明

| 项目 | 说明 |
|------|------|
| 持久化 | 无，重启丢失 |
| 安全 | 无认证鉴权，仅供教学演示 |
| 水平扩展 | 内存状态无法多实例共享 |
| 时钟 | 使用系统本地 `Date`，未做 NTP 约束 |
| SSE | 非 WebSocket；浏览器与 `requests` 均可消费 |

---

## 11. 文件与模块对应

| 文件 | 职责 |
|------|------|
| `server.js` | Express 应用、领域逻辑、SSE |
| `client_test.py` | 自动化接口与通知验证 |
| `README.md` | 项目简介与快速运行 |
| `USAGE.md` | 简明使用说明（交付用） |

---

## 12. 版本与依赖

- `express`: ^4.21.x
- Python: 3.10+，`requests` >= 2.32

（具体版本以 `package.json` / `requirements.txt` 为准。）
