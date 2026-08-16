# GitHub 版本管理指南

## 分支管理策略

### 主分支
- main: 稳定版本，随时可部署
- develop: 开发集成分支

### 功能分支
从 develop 分支创建：
`ash
git checkout -b feature/your-feature-name develop
`

### 发布分支
从 develop 分支创建，用于准备发布：
`ash
git checkout -b release/v1.0.0 develop
`

### 热修复分支
从 main 分支创建，用于紧急修复：
`ash
git checkout -b hotfix/urgent-fix main
`

## 提交信息规范

使用约定式提交格式：

`
&lt;type&gt;(&lt;scope&gt;): &lt;subject&gt;

&lt;body&gt; (可选)

&lt;footer&gt; (可选)
`

### Type 类型
- eat: 新功能
- ix: 修复 bug
- docs: 文档更新
- style: 代码格式调整
- efactor: 重构（既不是新增功能，也不是修复 bug）
- 	est: 测试相关
- chore: 构建/工具相关

### 示例
`ash
git commit -m "feat(p1): 添加新的数据获取源"
git commit -m "fix(backtest): 修复回测计算错误"
git commit -m "docs: 更新 README 文档"
`

## 发布流程

### 1. 创建发布分支
`ash
git checkout develop
git pull origin develop
git checkout -b release/v1.0.0
`

### 2. 更新版本号和测试
- 更新版本信息
- 运行完整测试
- 修复发现的问题

### 3. 完成发布
`ash
# 合并到 main
git checkout main
git merge --no-ff release/v1.0.0
git tag -a v1.0.0 -m "Release v1.0.0"

# 合并回 develop
git checkout develop
git merge --no-ff release/v1.0.0

# 删除发布分支
git branch -d release/v1.0.0

# 推送到 GitHub
git push origin main develop --tags
`

## 日常开发流程

`ash
# 1. 更新本地 develop
git checkout develop
git pull origin develop

# 2. 创建功能分支
git checkout -b feature/my-feature

# 3. 开发和提交
git add .
git commit -m "feat: 描述你的更改"

# 4. 定期同步
git checkout develop
git pull origin develop
git checkout feature/my-feature
git rebase develop

# 5. 推送并创建 PR
git push origin feature/my-feature
`

## 标签管理

### 创建版本标签
`ash
git tag -a v1.0.0 -m "Version 1.0.0 - 初始发布"
git push origin v1.0.0
`

### 查看标签
`ash
git tag -l
git show v1.0.0
`

## 保护分支

在 GitHub 仓库设置中启用：
- 分支保护规则（Require pull request reviews before merging）
- 状态检查（Require status checks to pass）
- 签署提交（Require signed commits）
