# ainer-core

> AinerN2D v2 主线服务。设计基线见 `docs/v2/`。

**它不生成像素、不生成声波、不合成视频。** 它把小说编译成结构与指令，
通过 Capability API 交给能力中间层执行，再把结果收回来做一致性管理。

## 当前进度

| 阶段 | 内容 | 状态 |
|------|------|------|
| P0.1 | 骨架 + 30 张表 + alembic 基线迁移 | ✅ |
| P0.2 | Capability 客户端（submit / poll / callback / 重试 / 幂等 / 成本闸门） | ✅ |
| P0.3 | Mock Gateway（契约参考实现） | ✅ |
| P0.4 | 书架：小说 / 章节 CRUD + 导入分章 | ⬜ |
| P0.5 | 剧本生成 pipeline | ⬜ |
| P0.6 | 翻译 + 术语一致性 | ⬜ |
| P0.5* | 世界观转译（L1–L4 + 防漂移三道闸） | ⬜ |

## 本地起服务

```bash
# 1. Mock Gateway（延迟设 0 便于开发）
MOCK_LATENCY_FACTOR=0 uvicorn mock_gateway.main:app --port 8199

# 2. Core
alembic upgrade head
uvicorn app.main:app --port 8100 --reload
```

Docker：`docker compose up -d ainer-core mock-gateway`（v1 服务已标 legacy profile，默认不启动）。

## 首次配置

```bash
# 注册中间层端点
curl -X POST http://localhost:8100/api/v2/settings/endpoints \
  -H 'Content-Type: application/json' \
  -d '{"name":"mock","base_url":"http://localhost:8199/cap/v1","auth":{"mode":"none"}}'

# 探活（真实请求 /health，不是模拟）
curl -X POST "http://localhost:8100/api/v2/settings/endpoints/{id}:test"

# 拉能力目录（后台参数表单的数据源）
curl -X POST "http://localhost:8100/api/v2/settings/endpoints/{id}:refresh-caps"
```

## 测试

```bash
MOCK_LATENCY_FACTOR=0 uvicorn mock_gateway.main:app --port 8199 &
pytest tests/ -q
```

`tests/test_capability_contract.py` 的断言就是契约本身 —— 任何中间层实现都应该能通过这一套。

## 结构

```
app/
├── config.py        运行配置（env 前缀 CORE_）
├── db.py            会话；search_path 固定到 core schema
├── ids.py           ULID
├── models/          30 张表
│   ├── content.py   novels / chapters
│   ├── script.py    script_docs / scenes / script_blocks
│   ├── translation.py
│   ├── world.py     ★ 世界观转译：profiles / transforms / lexicon / names / visual / violations
│   ├── entity.py    world_entities / entity_chapter_states
│   ├── shot.py      shot_plans / shots / frame_specs / audio_specs
│   ├── gen.py       gen_tasks / assets
│   └── settings.py  capability_endpoints / capability_routes
├── capability/      ★ 与中间层的唯一出口，厂商名不得出现在此目录之外
│   ├── schemas.py   契约类型
│   ├── errors.py    错误码 + 可重试性
│   ├── client.py    HTTP 客户端 + 幂等键 + HMAC
│   ├── router.py    capability × purpose → 端点
│   └── service.py   GenTask 生命周期 + 资产登记
├── api/v2/
└── pipelines/       固定管线 = 普通函数，无注册表无编排层
mock_gateway/        契约参考实现
```

## 数据库隔离

v2 全部建在 Postgres 的 `core` schema，v1 的 96 张表原样留在 `public`。
迁移数据时 `INSERT INTO core.novels SELECT ... FROM public.novels`。
`migrations/env.py` 的 `include_name` 严格过滤 schema，autogenerate 不会碰到 v1 的表。
