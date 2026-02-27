# 25_CONFIG_CENTER_API_MODEL_ROUTER.md
# Config Center（API配置+模型路由 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 定义 Studio 的配置中心：
- LLM API 配置（OpenAI/Anthropic/DeepSeek/自建兼容API等）
- Embedding API 配置（自建或第三方）
- TTS/BGM/SFX 模型配置
- 图像/视频后端配置（ComfyUI/Wan/Hunyuan等）
- 模型路由策略（按 stage 选择不同模型）
- 配置校验与健康检查

---

## 1. Workflow Goal（目标）
1) 用户可在前端配置多套 Provider
2) 为每个 stage（01~22 的关键阶段）指定默认模型或路由规则
3) 支持 fallback（主模型失败切换备用）
4) 支持 secrets 管理（仅 admin 可见）
5) 提供健康检查（连通性/额度/速率限制提示）

---

## 2. Inputs（输入）
- Provider 配置（base_url/api_key/model list）
- Stage routing rules（router policy）
- Secret vault settings（可选）
- Health check triggers

---

## 3. Outputs（输出）
- provider_registry.json
- model_router_policy.json
- health_status.json

---

## 4. Stage Routing（建议）
- 01/02：router（便宜快）
- 03/10：planner/prompt（更强）
- 12：embedding（专用）
- 16：critic（稳定）
- 20：compiler（模板化）

---

## 5. Integration Points（接入点）
- 01~22 所有 LLM/Embedding/TTS/I2V 调用都从这里取配置
- 28 Task Runner 在启动 Run 时冻结 config snapshot（可追溯）
- 18 Failure Policy 用 fallback 列表进行切换

---

## 6. Definition of Done
- [ ] 支持多 Provider 配置与加密存储
- [ ] 支持按 stage 路由与 fallback
- [ ] 支持健康检查与状态展示
- [ ] Run 可记录 config snapshot id
