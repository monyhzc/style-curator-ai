# Style Curator AI (真维斯服装与配件选款/风格审核大模型)

基于 **Qwen3.5-9B 多模态基座 + Vision LoRA 视觉解冻微调 + 4096 标量分类头** 的风格智能审核与自动选款系统。
全量支持 **8 大子品牌** 及 **7 大配件品类** 端到端直接打分，并深度内置旭日集团业务要求的**三档判定双套阈值体系**。

---

## 🎯 业务特性：旭日集团三档审图双阈值机制

针对成衣与配件审图标的，系统为每个品牌和品类设定 `[threshold_low, threshold_high]` 双套阈值，提供自动化分流与人工协同机制：

| 判定档位 | 判定条件 | 业务动作 | 核心目标 |
| :--- | :---: | :---: | :--- |
| **绝对符合 (`pass`)** | $\text{score} \ge \tau_{\text{high}}$ | **自动免审放行** | **极高 Precision**：放行纯净度达 98%~100%，杜绝劣质款式漏网 |
| **中度符合 (`review`)** | $\tau_{\text{low}} \le \text{score} < \tau_{\text{high}}$ | **提示人工介入审图** | **灰度缓冲**：针对视觉语义偏离或争议款式，由业务员复核兜底 |
| **绝对不符合 (`reject`)** | $\text{score} < \tau_{\text{low}}$ | **自动拦截驳回** | **极高 Specificity / Recall**：拦截线卡在极低分，绝不误杀优质款式 |

### 1. 8 大子品牌双阈值表
| 子品牌 (Brand) | `threshold_low` (拦截线) | `threshold_high` (放行线) | 风格调性 |
| :--- | :---: | :---: | :--- |
| **JEANS** | **0.15** | **0.60** | 街头潮流、美式复古、重工水洗牛仔、宽松廓形、字母涂鸦与工装解构 |
| **JKIDS** | **0.20** | **0.65** | 童趣时尚、舒适亲肤、活泼明快色彩、精致微缩印花与儿童合体剪裁 |
| **JNR** | **0.30** | **0.75** | 青少年青春活力、轻运动街头、多元拼色、适度宽松潮童版型 |
| **JSPORT** | **0.05** | **0.50** | 专业运动机能、吸湿速干透气面料、流线拼块剪裁、反光条与科技运动质感 |
| **LIFE** | **0.25** | **0.65** | 都市商务通勤与质感生活、极简克制、利落剪裁、高阶质感与优雅沉稳 |
| **MAIN** | **0.35** | **0.75** | 大众经典休闲、百搭合身版型、简约实用设计、品质耐穿与主流商业审美 |
| **OUTDOOR** | **0.30** | **0.80** | 山系硬核户外、三防科技面料（防水/防风/抗撕裂）、多口袋工装露营风 |
| **Z+** | **0.30** | **0.65** | 先锋街头潮流、暗黑解构剪裁、质感重工五金、极具辨识度的前卫设计语言 |

### 2. 7 大配件品类双阈值表
| 配件品类 (Category) | `threshold_low` (拦截线) | `threshold_high` (放行线) | 业务处理逻辑 |
| :--- | :---: | :---: | :--- |
| **鞋子** | **0.010** | **0.500** | 视觉辨识显著，`≥0.50` 全自动放行，`<0.01` 自动拦截 |
| **袜子** | **0.020** | **0.500** | 正例特征明显，双端纯净，`0.02~0.50` 提示人工复核 |
| **家居服** | **0.005** | **0.500** | 宽松起居服饰，`≥0.50` 高精度免审放行 |
| **箱包** | **0.001** | **0.500** | 非服装廓形语义偏移，低分段由人工介入缓冲 |
| **腰带** | **0.001** | **0.400** | 线状配饰，放行线适度优化至 0.40 |
| **内裤** | **0.001** | **0.500** | 贴身轻薄件，中间段平滑接入人工复查 |
| **内衣** | **0.0005** | **0.150** | **特殊少布料保护**：`≥0.15` 即自动通过，`0.0005~0.15` 提示人工 |

---

## 📁 阶段分层工程架构

```text
style-curator-ai/
├── README.md               # 项目主入口与架构导航
├── DEPLOY.md               # 生产部署与国内交付实操指南
├── requirements.txt        # 统一运行依赖
├── .env.example            # 环境变量配置模板
├── .gitignore              # 规避无用与大文件提交
├── service.sh              # 根目录全局便捷运维控制脚本
│
├── 01_environment/         # 【阶段一：环境搭建与基座获取】
│   ├── setup_env.sh        # 国内清华源/GPU环境一键初始化
│   └── download_model.py   # 魔搭 ModelScope 国内高速 CDN 基座下载
│
├── 02_model/               # 【阶段二：核心模型与权重融合】
│   ├── core.py             # 风格 Prompt、动态配件适配、三档判别与推理引擎
│   ├── pack.sh             # 开发者一键提取打包 138MB patch.tar.gz 脚本
│   └── merge.py            # 客户基座与增量物理融合工具 (merge_and_unload)
│
├── 03_service/             # 【阶段三：生产部署与 API 服务】
│   ├── app.py              # FastAPI 生产接口 (POST /api/analyze, /batch, GET /thresholds)
│   ├── service.sh          # 守护进程管理 (start / stop / restart / status)
│   └── data/               # 运行时配置数据
│       ├── thresholds.json # 8 品牌与 7 配件双阈值配置文件 (热更新)
│       └── url_allowlist.conf # SSRF 白名单配置 (热重载)
│
├── 04_client_tests/        # 【阶段四：测试验证与本地推理】
│   ├── smoke_test.py       # 生产服务全链路自动化 6 项冒烟自检
│   └── predict.py          # 命令行单图/多图离线打分工具 (支持 --category)
│
└── 05_training/            # 🎓【阶段五：模型微调与增量后训练】
    ├── train.py            # 核心微调脚本 (支持 LoRA 热启动与显存优化)
    ├── dataset.py          # 多模态数据加载器 (支持成衣与配件专属 Prompt)
    ├── prepare_dataset.py  # 自动扫描文件夹构建 train/val (支持配件与正反例)
    └── run_train.sh        # 一键训练模板与参数示例
```

---

## 🚀 极简运维与 API 规范

### 1. 一键启动 HTTP API 服务 (默认端口 11451)
```bash
./service.sh start
# 查看状态: ./service.sh status
# 查看日志: tail -f 03_service/service.log
```

### 2. API 接口说明

#### (1) 单图风格分析：`POST /api/analyze`
**入参 (JSON)**：
```json
{
  "image_url": "https://example.com/shoe.jpg",
  "task": "MAIN",
  "category": "鞋子"
}
```
> `task`: 目标品牌（默认 `LIFE`，支持 `LIFE`, `OUTDOOR`, `Z+`, `MAIN`, `JEANS`, `JNR`, `JKIDS`, `JSPORT`）  
> `category`: 可选配件品类（`鞋子`, `袜子`, `内裤`, `箱包`, `腰带`, `家居服`, `内衣`），留空默认按成衣处理。

**返回 (JSON)**：
```json
{
  "url": "https://example.com/shoe.jpg",
  "brand": "MAIN",
  "category": "鞋子",
  "probability": 0.8523,
  "decision": "pass",
  "level": "绝对符合",
  "level_code": 2,
  "manual_review_needed": false,
  "thresholds_used": {
    "low": 0.01,
    "high": 0.5
  }
}
```

#### (2) 批量任务提交：`POST /api/analyze/batch`
**入参 (JSON)**：
```json
{
  "urls": ["https://.../img1.jpg", "https://.../img2.jpg"],
  "task": "MAIN",
  "category": "箱包"
}
```

#### (3) 获取当前三档双阈值配置表：`GET /api/thresholds`
返回 8 大子品牌与 7 大配件品类的当前有效双阈值清单及规则定义。

---

### 3. 自动化冒烟健康自检
```bash
python 04_client_tests/smoke_test.py
```
**自检输出**：
```text
✅ [PASS] 1. 服务连通性检测 (HTTP 200)
✅ [PASS] 2. 401 未授权防御拦截
✅ [PASS] 3. 三档双阈值配置表接口 (支持 8 品牌 + 7 配件)
✅ [PASS] 4. 单图成衣端到端三档打分接口 (判定: 绝对符合 | low=0.3, high=0.65)
✅ [PASS] 5. 单图配件专属三档打分接口 (品类: 鞋子 | 判定: 绝对符合 | low=0.01, high=0.5)
✅ [PASS] 6. 异步批量打分与轮询 (批处理与三档解析正常)
```

---

### 4. 命令行本地离线快速打分
```bash
# 单图成衣打分
python 04_client_tests/predict.py --image sample_tshirt.jpg --brand Z+

# 单图配件打分 (指定品类)
python 04_client_tests/predict.py --image sample_shoe.jpg --brand MAIN --category 鞋子

# 文件夹批量评测
python 04_client_tests/predict.py --dir ./my_shoes/ --brand MAIN --category 鞋子
```

**控制台输出示例**：
```text
[Z+] [成衣] sample_tshirt.jpg -> 得分: 0.4230 | 判定: 中度符合 (REVIEW) [⚠️ 提示人工介入复审] | 双阈值: [low=0.3, high=0.65]
[MAIN] [鞋子] sample_shoe.jpg -> 得分: 0.8920 | 判定: 绝对符合 (PASS) | 双阈值: [low=0.01, high=0.5]
```

---

### 5. 新品类/新品牌三档双阈值自动标定流程 (Auto-Calibration)

当业务方后续拓展**全新配件品类**（如：帽子、围巾、手表、手套、首饰）或**新子品牌**时，系统提供两种自动化标定适配路径，无需重新训练模型权重：

#### 方式 A：命令行一键自动标定与持久化 (推荐)
只需准备少量该品类的正例与负例图片（建议各 20~50 张），直接运行标定工具：
```bash
# 自动扫描目录 (子目录包含“符合/不符合”或“正例/反例”)
python 04_client_tests/calibrate_thresholds.py \
  --category 帽子 \
  --dir /path/to/hats_data \
  --brand MAIN \
  --update_config

# 或者分别指定正负例文件夹
python 04_client_tests/calibrate_thresholds.py \
  --category 围巾 \
  --pos_dir /path/to/pos_scarf \
  --neg_dir /path/to/neg_scarf \
  --brand MAIN \
  --update_config
```
**标定过程自动执行**：
1. 模型端到端打分并分析正负样本概率分布；
2. 按照目标指标（Recall $\ge 96\%$、Precision $\ge 96\%$）搜索最优 `[low, high]`；
3. 打印放行纯度、拦截纯度与人工介入率指标；
4. 自动持久化写入 `03_service/data/thresholds.json`，线上服务与 CLI 工具**秒级自动适配新品类，无需重启服务**！

#### 方式 B：通过 HTTP API 在线自动标定
审图管理后台可直接调用在线标定接口：
```bash
curl -X POST http://127.0.0.1:11451/api/thresholds/calibrate \
  -H "Authorization: Bearer jw_style_audit_prod_token_2026" \
  -H "Content-Type: application/json" \
  -d '{
    "category": "帽子",
    "brand": "MAIN",
    "pos_urls": ["https://.../hat_pos1.jpg", "https://.../hat_pos2.jpg"],
    "neg_urls": ["https://.../hat_neg1.jpg", "https://.../hat_neg2.jpg"],
    "auto_save": true
  }'
```

#### 🛡️ 智能安全缓冲机制 (Fallback)
若调用方提交了尚未标定过的全新配件名（如未配置的“发饰”），系统将**自动激活保守灰度缓冲策略**：
- 采用保守双阈值 `[low: 0.01, high: 0.70]`，自动放大人工审核区间；
- 接口返回 `"calibrated": false` 及引导标定通知，确保在补全标定数据前**绝不误杀好款式、绝不漏放劣质品**。

---

## 📦 客户极简交付流程 (仅需交付 138MB)

详见完整部署指南 👉 [DEPLOY.md](DEPLOY.md)。
- **开发者**：运行 `./02_model/pack.sh <权重路径>` 生成 `patch.tar.gz`（约 138MB）交付给客户。
- **客户方**：
  1. 下载官方原版基座：`python 01_environment/download_model.py`
  2. 解压补丁并物理融合：`python 02_model/merge.py --base ./weights/Qwen3.5-9B --patch ./patch --out ./weights/merged`
  3. 启动服务：`./service.sh start`
