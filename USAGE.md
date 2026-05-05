# 简明使用说明

## 环境要求

- **Node.js**：建议 18 或 20 及以上（用于运行服务端）
- **Python**：3.10 及以上（用于运行测试脚本）

## 获取与进入项目目录

将源码解压或克隆后，在终端进入项目根目录（含 `server.js`、`package.json` 的目录）。

## 安装依赖

**Node.js（服务端）**

```powershell
npm install
```

**Python（客户端测试）**

```powershell
pip install -r requirements.txt
```

## 启动服务

```powershell
npm start
```

默认监听：`http://127.0.0.1:3000`  
健康检查：`GET http://127.0.0.1:3000/health`

## 运行 API 测试客户端

确保服务端已启动，在**另一终端**执行：

```powershell
python .\client_test.py
```

脚本将依次验证：创建竞赛（含 `endX/endY` 兼容）、团队创建、重复团队报错、缺参上报、夺标流程、结束后上报、SSE 通知、查询终点与状态等。

## 打包提交「运行程序包」建议

1. 包含完整源码目录（可排除 `node_modules` 以减小体积）。
2. 在使用说明中写明：接收方需执行 `npm install` 与 `pip install -r requirements.txt` 后再 `npm start` 与 `python client_test.py`。
3. 若需「开箱即运行」且无法在目标环境联网安装依赖，可将本地已安装的 `node_modules` 一并打包，并注明 Node 主版本需与打包环境一致。

## 接口速查

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/competitions` | 新建竞赛，body: `x,y` 或 `endX,endY` |
| POST | `/competitions/:id/teams` | 创建团队，body: `teamId` |
| POST | `/reports` | 位置上报 |
| GET | `/competitions/:id/target` | 查询终点或已结束信息 |
| GET | `/competitions/:id/status` | 查询是否结束 |
| GET | `/competitions/:id/stream` | SSE 订阅结束通知（query: `teamId`, `memberId`） |

详细字段与状态机见 `DESIGN.md`。
