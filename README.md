# 模拟夺标游戏位置服务

## 1. 项目说明
本项目实现一个“模拟夺标游戏位置服务”API，并提供 Python 客户端用于接口测试。

**详细设计说明**：见仓库根目录 [`DESIGN.md`](./DESIGN.md)。  
**简明使用说明（运行与打包）**：见 [`USAGE.md`](./USAGE.md)。

技术选型：
- 服务端：Node.js + Express
- 数据存储：内存存储
- 通知方式：SSE（Server-Sent Events）
- 测试客户端：Python + requests

## 2. 业务规则
- 使用平面直角坐标系
- 成员到达终点判定：成员位置到终点距离 `< 2.0`
- 团队到达终点判定：同一团队中有 `3` 位成员达到终点
- 夺标团队：同场竞赛中最先满足团队到达条件的团队
- 不实现认证、授权等安全能力

距离计算公式：

`d = sqrt((x2 - x1)^2 + (y2 - y1)^2)`

## 3. 数据模型
### Competition
- `id`：竞赛ID
- `target`：终点坐标
- `finished`：是否结束
- `winnerTeamId`：夺标团队ID
- `finishedAt`：结束时间
- `teams`：参赛团队集合
- `subscribers`：SSE订阅成员

### Team
- `teamId`：团队ID
- `members`：成员信息
- `arrivedMembers`：已到达终点成员集合

## 4. API 设计
### 4.1 新建竞赛
- 方法：`POST /competitions`
- 请求体（`x`/`y` 或 `endX`/`endY`，二选一写法均可）：
```json
{
  "x": 10,
  "y": 10
}
```
或 `{ "endX": 10, "endY": 10 }`。

### 4.2 创建团队
- 方法：`POST /competitions/:competitionId/teams`
- 请求体：
```json
{
  "teamId": "Alpha"
}
```

### 4.3 提交成员位置
- 方法：`POST /reports`
- 请求体：
```json
{
  "competitionId": "COMP_1",
  "teamId": "Alpha",
  "memberId": "M1",
  "x": 10.1,
  "y": 9.9
}
```

### 4.4 查询终点位置
- 方法：`GET /competitions/:competitionId/target`
- 竞赛未结束时返回终点坐标
- 竞赛已结束时返回“已结束”和夺标团队ID

### 4.5 查询竞赛是否结束
- 方法：`GET /competitions/:competitionId/status`
- 未结束返回 `未结束`
- 已结束返回 `已结束` 和夺标团队ID

### 4.6 订阅竞赛结束通知
- 方法：`GET /competitions/:competitionId/stream?teamId=Alpha&memberId=M1`
- 用途：竞赛结束时，通知当前在线参赛成员

## 5. 运行说明
### 5.1 安装 Node.js 依赖
在项目目录执行：

```powershell
npm install
```

### 5.2 启动服务端
```powershell
npm start
```

启动后访问：
- `http://127.0.0.1:3000/health`

### 5.3 安装 Python 测试依赖
```powershell
pip install -r requirements.txt
```

### 5.4 运行客户端测试
```powershell
python .\client_test.py
```

## 6. 测试流程说明
客户端脚本会自动执行以下流程：
- 创建一个竞赛
- 创建两个团队 `Alpha` 和 `Bravo`
- 为部分成员建立 SSE 通知监听
- 提交多次位置上报
- 让 `Alpha` 团队的三名成员先后到达终点
- 服务端判定 `Alpha` 为夺标团队
- 所有在线监听成员收到“竞赛结束”通知
- 最后查询竞赛终点和状态

## 7. 结果说明
当第三名成员到达终点后，服务端会：
- 标记竞赛结束
- 记录夺标团队ID
- 返回夺标成功结果
- 向所有已订阅通知的参赛成员推送结束消息

## 8. 局限性
- 当前采用内存存储，服务重启后数据会丢失
- SSE 只通知在线连接成员，离线成员不会收到历史推送
- 未实现用户认证、权限控制和数据库持久化
