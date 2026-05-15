# 外骨骼资讯自动推送

每天自动搜索外骨骼相关资讯，推送到企业微信群。

## 推送时间
- 09:00（第1期）
- 15:00（第2期）
- 21:00（第3期）

## 内容类型
- 🎬 视频推荐（B站、抖音等）
- 🔬 科研进展（学术论文、研究突破）
- 📰 行业资讯（新闻、政策）
- 💰 公司动态（产品发布、融资消息）

## 配置说明

### 1. 设置 GitHub Secret
在仓库 Settings → Secrets and variables → Actions 中添加：
- `WECHAT_WEBHOOK_KEY`: 你的企业微信群机器人Webhook Key

### 2. 手动触发
进入 Actions 页面，选择 "外骨骼资讯定时推送"，点击 "Run workflow"。

## 技术栈
- Python 3.11
- DuckDuckGo 搜索
- 企业微信 Webhook API
- GitHub Actions 定时任务
