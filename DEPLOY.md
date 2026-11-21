# Style Curator AI - 生产部署与国内交付全流程指南

本文档面向需要在**国内网络环境（无法顺畅访问海外 HuggingFace）**中部署上线 **Style Curator AI** 风格审核服务的运维与工程人员。

---

## 📋 架构与前置要求

- **操作系统**：Linux (Ubuntu 20.04/22.04、Debian 11+、CentOS 7/8、Alibaba Cloud Linux)
- **Python 环境**：Python 3.10+ (强烈推荐使用独立的 Conda 隔离环境，如 `style_curator`，避免污染或影响服务器上的其他应用)
- **硬件配置**：
  - 推理 GPU：NVIDIA 显卡（显存 $\ge 16\text{GB}$，如 NVIDIA H20、H100、RTX 4090、A10、L20、V100、A800 等；建议 CUDA 12.1+ / 12.4+）
  - 磁盘空间：空余空间 $\ge 30\text{GB}$

---

## 🚀 四阶段部署全流程

### 【阶段一】环境搭建与基座下载

1. **一键创建独立隔离环境与依赖 (Conda)**：
   若服务器存在其他应用，推荐先执行独立环境构建脚本：
   ```bash
   bash 01_environment/create_conda_env.sh
   ```
   或者直接运行一键部署脚本（已内置 Conda 环境自动隔离与识别）：
   ```bash
   bash quick_deploy.sh
   ```
   > 自动隔离创建 `style_curator` Conda 环境，安装 PyTorch (CUDA 12.4 现代 GPU 架构构建版)、Transformers、PEFT、FastAPI 及魔搭 ModelScope。

2. **通过魔搭社区 (ModelScope) 高速下载基座模型**：
   ```bash
   python 01_environment/download_model.py --model Qwen/Qwen3.5-9B --local_dir ./weights/Qwen3.5-9B
   ```
   > 直连阿里国内 CDN 高速节点，通常 2~5 分钟内下载完毕。

---

### 【阶段二】获取增量补丁并执行融合

从项目的 [Releases v1.1.0](https://github.com/monyhzc/style-curator-ai/releases/tag/v1.1.0) 下载交付的最新 `patch.tar.gz`（约 128MB，已内置 Step 4004 最终冠军权重），解压并执行一键物理融合：

```bash
# 1. 解压交付的 patch.tar.gz 到 patch 目录
mkdir -p ./patch && tar -xzf patch.tar.gz -C ./patch

# 2. 物理融合成完整独立模型
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
✅ [PASS] 3. 三档双阈值配置表接口 (支持 8 品牌 + 7 配件)
✅ [PASS] 4. 单图成衣端到端三档打分接口 (判定: 绝对符合 | low=0.3, high=0.65)
✅ [PASS] 5. 单图配件专属三档打分接口 (品类: 鞋子 | 判定: 绝对符合 | low=0.01, high=0.5)
✅ [PASS] 6. 异步批量打分与轮询 (批处理与三档解析正常)
✅ [PASS] 7. 未标定新品类安全缓冲保护 (激活保守灰度策略 [0.01, 0.70])
✅ [PASS] 8. 在线新品类自动标定流程接口 (支持传入样张一键出阈值)
🎉 自动化冒烟测试执行完毕！
```

---

## ⚙️ 运维配置与通用化说明

### 1. 修改端口、鉴权 Token 与阈值路径
复制根目录下 `.env.example` 为 `.env`：
```env
PORT=11451                            # 业务监听端口
APP_AUTH_TOKEN=your_secure_token_2026 # 客户端 Bearer 认证 Token
ALLOWLIST_PATH=03_service/data/url_allowlist.conf # SSRF 白名单配置路径
THRESHOLDS_PATH=03_service/data/thresholds.json   # 8 品牌与 7 配件三档双阈值配置路径
USE_INT4=false                        # 设为 true 即可在 8G/12G/16G 显卡上以 INT4 模式运行 (峰值显存仅 8.6GB)
```

### 2. INT4 极简显存推理自检 (可选)
如果服务器显存有限（如只有 12GB 或 16GB 显存显卡），可运行 INT4 量化自检工具：
```bash
python 04_client_tests/test_int4.py
```
> 实测可将推理峰值显存从 18.8GB 降至 8.59GB，打分判定吻合率达 96.7%。

### 3. 内网图片服务器 SSRF 白名单
若调用方的图片服务器位于内网（如 `192.168.x.x` 或 `internal-images.local`），请编辑 `03_service/data/url_allowlist.conf`：
```text
192.168.1.100
10.0.0.0/8
images.company.internal
```
**保存即生效，无需重启服务。**

---

## 🔄 生产环境一键自动更新流水线

当月度增量模型重新训练并发布新 Release 时，运维人员无需手动下载或替换文件，只需在根目录执行一键更新脚本：

```bash
# 全自动更新：拉取 Git 最新代码 + 检查 GitHub Release 最新权重 + 备份替换 + 重启服务
./update.sh
```

**高级选项支持**：
* `./update.sh --code-only`：仅更新 Git 业务代码，跳过权重下载；
* `./update.sh --weights-only`：仅检测更新模型权重，跳过 Git 拉取；
* `./update.sh --tag v1.0.0`：一键回滚或指定安装特定 Release 版本的权重；
* `./update.sh --force`：强制重新下载并解压权重。
