# 23_STUDIO_AUTH_USER_ORG.md
# Studio Auth / Users / Org（登录登出与权限 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 为 AinerN2D Studio 的基础账户与权限层，提供：
- 登录/登出
- 用户与角色（owner/admin/editor/viewer）
- 项目级权限（Project ACL）
- API Key/密钥可见性控制（与 25 配置中心联动）
- 审计日志（谁在何时做了什么）

> 本模块是 Studio 产品层，不替代生成流水线（01~22），用于保障多用户与安全运营。

---

## 1. Workflow Goal（目标）
输出并维持以下能力：
- 用户身份认证与会话
- 组织/团队（可选）
- 项目授权（谁能看/改/发起生成/发布版本）
- 操作审计日志

---

## 2. Inputs（输入）
- 注册/登录信息（邮箱/用户名/密码或OAuth）
- 会话 token / refresh token
- 组织邀请/加入（可选）
- 项目权限变更请求

---

## 3. Outputs（输出）
- auth session（access_token）
- user profile
- org membership（可选）
- project ACL
- audit log events

---

## 4. Roles（建议）
- owner：全权限（含发布版本、删除项目）
- admin：配置与运营管理（含模型配置、KB发布）
- editor：编辑小说/篇章、发起生成、编辑时间线
- viewer：只读

---

## 5. Integration Points（接入点）
- 所有 Studio API 必须携带 user/session
- 25 配置中心：密钥只允许 owner/admin
- 11/12/22/14：发布与实验权限需要 admin+
- 30 时间线编辑：editor+

---

## 6. Definition of Done
- [ ] 支持登录/登出与会话续期
- [ ] 支持项目 ACL
- [ ] 支持审计日志

---

## 7. 对话补充需求索引（接力必读）
- 23~30 对话收敛需求见：`SKILL_23_30_PRODUCT_REQUIREMENTS_MASTER.md`
- 本 Skill 重点补充：后台统一登录守卫、RBAC 强化、错误对象结构化一致性。
