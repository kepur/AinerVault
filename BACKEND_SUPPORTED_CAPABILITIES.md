# BACKEND_SUPPORTED_CAPABILITIES.md
# AinerN2D 当前后端能力（由 Skill 01~22 + 14~20 + 21~22 定义）

## 你已经“设计上支持”的后端模块
- 内容入口与规划：01~03
- 实体抽取与一致性：04 + 21 + 07
- 音频：05~06（含TTS时长回填与多轨道timeline_final）
- 素材与提示词：08~10 + 20
- RAG/Persona/进化：11~13 + 14 + 22
- 工业增强：15~19 + 16 + 17 + 18
- Studio 产品层：23~30（本次新增）

## 与两台服务器落地的建议
- CPU服务器：Gateway/Orchestrator/API、PostgreSQL/pgvector、Redis、RabbitMQ、MinIO、监控
- GPU服务器：ComfyUI/I2V/视频模型 Workers、TTS/音频模型 Workers
- 25 配置中心管理各后端端点、健康检查与路由策略；28 在 Run 启动时冻结配置快照以便追溯。
