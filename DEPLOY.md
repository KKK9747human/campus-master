# DEPLOY.md —— 部署手册：本地一键起 + 切华为云

> 配套读：`HANDOVER.md`（链路权威）、`LOCAL_SETUP.md`（本机裸机跑法）。
> 本文档回答一件事：**「切云只改 .env」具体怎么落**。

---

## 一、本地 ↔ 云上服务对齐

| 华为云服务 | 本项目用法 | 本地等价物 | 切云动作 |
|---|---|---|---|
| RDS for MySQL 8.4 | 10 张业务表 | 本机 mysqld / compose 的 mysql:8.4 | .env 改 MYSQL_* 五项 |
| DCS Redis | 6 类热点缓存键 | 本机 Windows Redis / compose 的 redis:7 | .env 改 REDIS_* 三项 |
| MaaS 大模型 | OpenAI 兼容 /v1/chat/completions | 无 Key 时本地规则降级 | .env 改 MAAS_* 三项 |
| ECS | uvicorn 单实例 + 静态托管 /web | 本机裸跑 uvicorn / compose 的 app | 装 Docker 跑容器 |

代码零改动，所有差异都收在 `.env`。

---

## 二、本地 Docker 一键跑（不想配本机 MySQL/Redis 时用）

```bash
cd campus-master
docker compose up -d --build        # 首次自动建表（init_tables.sql 挂进 mysql 初始化目录）
curl http://127.0.0.1:8100/health   # {"status":"ok","mysql":"connected","redis":"connected"}
```

- compose 内部把 `MYSQL_HOST/REDIS_HOST` 覆盖成服务名 `mysql`/`redis`，**.env 里这两项保持本机值即可**，互不打架。
- 本地全栈版 Redis 不设密码：`.env` 里 `REDIS_PASSWORD` 留空（本机裸跑也是这么配的）。
- 数据落 `mysql-data`/`redis-data` 卷，配图落 `./uploads`；想清库重来：`docker compose down -v`。
- 要验证定时抓取间隔：`FETCH_INTERVAL_MINUTES`（分钟，默认 30，0=关）加进 `.env` 即可，日志前缀 `[fetch-cron]`。

---

## 三、华为云部署（ECS + RDS + DCS + MaaS）

### 第 0 步 .env 核对（11 个键，值不外泄不入 git）

```
MYSQL_HOST / MYSQL_PORT / MYSQL_USER / MYSQL_PASSWORD / MYSQL_DATABASE
REDIS_HOST / REDIS_PORT / REDIS_PASSWORD
MAAS_API_KEY / MAAS_MODEL / MAAS_BASE_URL
FETCH_INTERVAL_MINUTES        # 可选，默认 30
```

### 第 1 步 RDS for MySQL
1. 购买 MySQL 8.4 实例（与 ECS 同 VPC），设 root 密码。
2. 库字符集必须是 **utf8mb4**（赛题数据含中文与 emoji 场景）。
3. 导入表结构：`mysql -h <RDS地址> -u root -p campus_master < sql/init_tables.sql`
4. 安全组：放行 ECS 内网 IP 的 3306。

### 第 2 步 DCS Redis
1. 购买 Redis 实例（与 ECS 同 VPC），设访问密码（Redis 6+ 默认 RESP3 也没问题，客户端已强制兼容）。
2. 白名单放行 ECS。

### 第 3 步 MaaS 大模型
1. 华为云 MaaS 开通服务，建 OpenAI 兼容接入点，拿 API Key。
2. `.env` 填 `MAAS_API_KEY` + `MAAS_BASE_URL`（形如 https://api.xxx/v1）+ `MAAS_MODEL`。
3. 填好重启后端，页面引擎标签从「本地规则」变「大模型」，**代码不用改**。

### 第 4 步 ECS 起容器
```bash
# 装 Docker（华为云镜像源）后，把项目目录传上去（scp/git 均可，.env 手工单独放）
cd campus-master
docker build -t campus-master .
docker run -d --name campus-app \
  --env-file .env \
  -p 8100:8100 \
  -v /data/campus-uploads:/app/uploads \
  --restart unless-stopped \
  campus-master
```

- `.env` 只放服务器上，**不进 git、不进镜像**（.dockerignore 已挡）。
- 配图目录挂卷持久化，容器重建不丢。
- 安全组：对公网放行 8100（或挂 SLB/域名 + HTTPS 后只放 80/443）。

### 第 5 步 验证清单
1. `curl http://<ECS公网IP>:8100/health` → mysql/redis 全 connected。
2. 打开 `http://<ECS公网IP>:8100/` 落地页，状态灯全绿。
3. 情报官点「拉取最新」能抓到学校通知（ECS 出网需可达目标高校站点）。
4. `docker logs campus-app | grep fetch-cron` → 定时抓取在跑。
5. 评委动线五步走一遍（落地页有现成脚本）。

---

## 四、注意事项

- **单实例单 worker**：uvicorn 不要开 `--workers N`——官方源定时抓取线程随进程启动，多 worker 会每份各跑一轮（抓取本身幂等去重，不会重复入库，但徒增对学校网站的压力）。
- **CORS**：`app/main.py` 现为 `allow_origins=["*"]`（本地开发方便）；公网部署后建议收敛成自己的域名。
- **数据库连接是现连现关**（非连接池），单实例演示并发完全够；上量再换连接池（`get_mysql_conn` 已注释标明）。
- **镜像更新**：改完代码 `docker build` 后 `docker stop campus-app && docker rm $_ && docker run ...`（run 命令同上，配图卷不动数据就在）。
