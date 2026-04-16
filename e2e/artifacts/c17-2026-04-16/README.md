# C17 admin-users L3 手工凭证

Docker kernel-lock 未解（C3~C17 延续），L3 降级为手工验证。

## 待验证项
- [ ] admin 登录后看到"管理"导航入口
- [ ] /admin/users 页面：用户列表、创建用户表单、启用/禁用开关
- [ ] /admin/rules 页面：10 维度配置表单、全局配置、保存、恢复默认
- [ ] reviewer 登录后看不到"管理"入口
- [ ] reviewer 直接访问 /admin/users → 重定向到 /projects
