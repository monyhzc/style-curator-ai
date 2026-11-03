# Style Curator AI - 生产部署与国内交付全流程指南

本文档面向需要在**国内网络环境（无法顺畅访问海外 HuggingFace）**中部署上线 **Style Curator AI** 风格审核服务的运维与工程人员。

---

## 📋 架构与前置要求

- **操作系统**：Linux (Ubuntu 20.04/22.04、Debian 11+、CentOS 7/8、Alibaba Cloud Linux)
- **Python 环境**：Python 3.10+ (推荐 Miniconda / Anaconda)
- **硬件配置**：
  - 推理 GPU：NVIDIA 显卡（显存 $\ge 16\text{GB}$，如 RTX 4090、A10、L20、V100、A800 等）
  - 磁盘空间：空余空间 $\ge 30\text{GB}$

---

## 🚀 四阶段部署全流程

### 【阶段一】环境搭建与基座下载

1. **一键初始化国内运行环境**：
   ```bash
   bash 01_environment/setup_env.sh
   ```
   > 自动绑定清华大学 PyPI 镜像源，安装 PyTorch、Transformers、PEFT、FastAPI 及魔搭 ModelScope。

2. **通过魔搭社区 (ModelScope) 高速下载基座模型**：
   ```bash
   python 01_environment/download_model.py --model Qwen/Qwen3.5-9B --local_dir ./weights/Qwen3.5-9B
   ```
   > 直连阿里国内 CDN 高速节点，通常 2~5 分钟内下载完毕。

---

### 【阶段二】补丁解压与权重融合

将开发者提供的 `patch.tar.gz`（约 138MB）解压，并执行一键物理融合：

```bash
mkdir -p ./patch && tar -xzf patch.tar.gz -C ./patch
python 02_model/merge.py --base ./weights/Qwen3.5-9B --patch ./patch --out ./weights/merged
```
> 融合完成后将生成 `weights/merged` 目录，权重数学叠加完毕，不再依赖 PEFT 动态加载。

---

### 【阶段三】生产服务启动与守护

```bash
# 启动后台服务 (默认端口 11451)
./service.sh start

# 查看服务状态与监听端口
./service.sh status

# 查看实时运行日志
tail -f 03_service/service.log
```

若需停止或重启：
```bash
./service.sh stop
./service.sh restart
```

---

### 【阶段四】自动化冒烟自检与测试

服务启动完毕后，运行阶段四自检工具一键验证：
```bash
python 04_client_tests/smoke_test.py
```
**期望输出**：
```text
✅ [PASS] 1. 服务连通性检测 (HTTP 200)
✅ [PASS] 2. 401 未授权防御拦截
✅ [PASS] 3. 单图端到端打分接口 (品牌: Z+ | 置信度: 0.999 | 耗时: 45ms)
✅ [PASS] 4. 异步批量打分与轮询 (状态: completed | 已完成: 2/2)
🎉 自动化冒烟测试执行完毕！
```

---

## ⚙️ 运维配置与通用化说明

### 1. 修改端口与鉴权 Token
复制根目录下 `.env.example` 为 `.env`：
```env
PORT=11451                            # 业务监听端口
APP_AUTH_TOKEN=your_secure_token_2026 # 客户端 Bearer 认证 Token
ALLOWLIST_PATH=03_service/data/url_allowlist.conf # SSRF 白名单配置路径
```

### 2. 内网图片服务器 SSRF 白名单
若调用方的图片服务器位于内网（如 `192.168.x.x` 或 `internal-images.local`），请编辑 `03_service/data/url_allowlist.conf`：
```text
192.168.1.100
10.0.0.0/8
images.company.internal
```
**保存即生效，无需重启服务。**
