# hub.P1.D1 r2 设计修订
补全实际音频原字节身份、sample_rate、anchor_tick、offset_samples、alignment状态和aligned产物身份；增加十错误码的路径化错误记录schema；统一binding与owner字段命名，明确阶段/唯一控制者/有限值/绑定/口型等为D2语义层责任。r1两文件保存在本目录，未覆盖原报告。
配套schema元校验和15项结构检查通过，日志structure-checks.json；身份见identities.json。无语义实现、真实音频、表演、渲染、模型或E2E；所有D5控制器仍pending/unsupported。待非作者独立复审，不自验收。
