# Style Curator AI (服装选款与风格审核大模型)

基于 **Qwen3.5-9B 多模态基座 + Vision LoRA 视觉解冻微调 + 4096 标量分类头** 的服装风格智能审核与自动选款系统。全量支持 8 大品牌端到端直接打分。

---

## 📁 阶段分层工程架构

项目按照系统交付生命周期划分为 4 个清晰阶段，结构整洁，职责明确：

```text
style-curator-ai/
├── README.md               # 项目主入口与架构导航
├── DEPLOY.md               # 生产部署与国内交付实操指南
├── requirements.txt        # 统一运行依赖
├── .env.example            # 环境变量配置模板
├── .gitignore              # 规避无用与大文件提交
├── service.sh              # 根目录全局便捷运维控制脚本 (可选)
│
├── 01_environment/         # 【阶段一：环境搭建与基座获取】
│   ├── setup_env.sh        # 国内清华源/GPU环境一键初始化
│   └── download_model.py   # 魔搭 ModelScope 国内高速 CDN 基座下载
│
├── 02_model/               # 【阶段二：核心模型与权重融合】
│   ├── core.py             # 8 品牌 Prompt 定义、网络结构与推理引擎
│   ├── pack.sh             # 开发者一键提取打包 138MB patch.tar.gz 脚本
│   └── merge.py            # 客户基座与增量物理融合工具 (merge_and_unload)
│
├── 03_service/             # 【阶段三：生产部署与 API 服务】
│   ├── app.py              # FastAPI 生产接口 (POST /api/analyze, /batch)
│   ├── service.sh          # 守护进程管理 (start / stop / restart / status)
│   └── data/               # 运行时配置数据
│       └── url_allowlist.conf # SSRF 白名单配置 (热重载)
│
└── 04_client_tests/        # 【阶段四：测试验证与本地推理】
    ├── smoke_test.py       # 生产服务全链路自动化冒烟自检
    └── predict.py          # 命令行单图/多图本地离线打分工具
```

---

## 🚀 极简运维与使用

### 1. 一键启动 HTTP API 服务 (默认端口 11451)
```bash
./service.sh start
# 查看状态: ./service.sh status
# 查看日志: tail -f 03_service/service.log
```
- **单图打分**：`POST /api/analyze`  
  入参：`{"image_url": "https://...", "task": "Z+"}`  
  返回：`{"url": "...", "probability": 0.985}`
- **批量打分**：`POST /api/analyze/batch`  
  入参：`{"urls": ["..."], "task": "LIFE"}`  
  返回：`{"batch_id": "...", "total": 10, "status": "processing"}`

### 2. 自动化冒烟健康自检
```bash
python 04_client_tests/smoke_test.py
```

### 3. 命令行本地离线快速打分
```bash
# 单图评测
python 04_client_tests/predict.py --image sample.jpg --brand Z+

# 目录批量评测
python 04_client_tests/predict.py --dir ./images/ --brand LIFE
```

---

## 📦 客户极简交付流程 (仅需交付 138MB)

详见完整部署指南 👉 [DEPLOY.md](DEPLOY.md)。
- **开发者**：运行 `./02_model/pack.sh <权重路径>` 生成 `patch.tar.gz`（约 138MB）交付给客户。
- **客户方**：
  1. 下载官方原版：`python 01_environment/download_model.py`
  2. 解压补丁并物理融合：`python 02_model/merge.py --base ./weights/Qwen3.5-9B --patch ./patch --out ./weights/merged`
  3. 启动服务：`./service.sh start`
