# Style Curator AI (真維斯服裝與配件選款/風格審核大模型)

[![GitHub Release](https://img.shields.io/github/v/release/monyhzc/style-curator-ai?color=blue&label=%E7%89%88%E6%9C%AC)](https://github.com/monyhzc/style-curator-ai/releases)
[![Python Version](https://img.shields.io/badge/Python-3.10%2B-green.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![CUDA](https://img.shields.io/badge/CUDA-11.8%20%7C%2012.1%2B-orange.svg)](https://developer.nvidia.com/cuda-toolkit)
[![INT4 NF4](https://img.shields.io/badge/Quantization-INT4%20NF4%20(8.5GB)-purple.svg)](https://github.com/TimDettmers/bitsandbytes)

基於 **Qwen3.5-9B 多模態基座 + Vision LoRA 視覺解凍微調 + 4096 標量分類頭** 的風格智慧審核與自動選款系統。  
全量支援 **8 大子品牌** 及 **7 大配件品類** 端到端直接打分，並深度內建旭日集團業務要求的**三檔判定雙套閾值體系**。

---

## ⚡【極速一鍵部署】(客戶 5 分鐘自動化上線指南)

為了讓您的團隊與客戶以最短時間完成部署，本專案提供**全自動一鍵化部署腳本 (`quick_deploy.sh`)**。  
您只需在伺服器上執行以下**兩行命令**，腳本將自動完成全部前置作業：

```bash
# 1. 克隆 GitHub 倉庫代碼
git clone https://github.com/monyhzc/style-curator-ai.git
cd style-curator-ai

# 2. 執行極速一鍵部署流水線 (全自動配置、下載、拼接與 INT4 推理)
bash quick_deploy.sh
```

### 🤖 一鍵部署腳本自動執行的 6 大工序：

```text
[步驟 1/6] 系統環境自檢 ──> 自動配置清華 PyPI 高速映象源，秒級安裝 PyTorch / Transformers / BitsAndBytes
[步驟 2/6] 基座模型獲取 ──> 透過阿里魔搭 (ModelScope) 國內高速 CDN 下載 Qwen3.5-9B (避開海外 HuggingFace 限制)
[步驟 3/6] 拉取 Release ──> 自動查詢 GitHub API，拉取最新發布的 patch.tar.gz (128MB 冠軍權重) 並解壓校驗
[步驟 4/6] 拼接物理模型 ──> 自動呼叫 merge.py 執行 merge_and_unload，將 LoRA 與基座物理疊加成 weights/merged
[步驟 5/6] 啟用 INT4 量化 ──> 自動寫入 .env 配置 USE_INT4=true，啟用 NF4 雙重量化 (顯存直降 54.4% 至 <= 8.59GB)
[步驟 6/6] 服務啟動與自檢 ──> 啟動後台守護進程 (端口 11451)，自動執行首張圖片 INT4 冒煙打分推理驗證
```

> 💡 **硬體門檻極低**：在啟用 **INT4 雙重量化** 模式後，單圖推理峰值顯存僅需 **約 8.59 GB**，無論是資料中心 GPU（L20, A10, A100, V100）還是消費級主流顯卡（**RTX 3060 12GB、RTX 4060Ti 16GB、RTX 3090/4090**），均可流暢高併發運行！

---

### 🛠️ 分步手動部署指引 (如需客製化分步執行)

若您的運維團隊偏好手動逐步掌控每個環節，可依序執行以下 4 個標準指令：

#### 步驟 1：配置環境依賴
```bash
# 配置國內清華映象源並安裝完整運行庫
bash 01_environment/setup_env.sh
```

#### 步驟 2：高速下載基座模型
```bash
# 透過魔搭社區高速 CDN 直連下載 (2~5 分鐘完成)
python3 01_environment/download_model.py --model Qwen/Qwen3.5-9B --local_dir ./weights/Qwen3.5-9B
```

#### 步驟 3：拉取最新 Release 附件並物理拼接模型
```bash
# 拉取最新 Release 權重補丁 (約 128MB)
bash update.sh --weights-only --no-restart

# 將基座與增量 LoRA 權重物理融合成獨立完整模型
python3 02_model/merge.py --base ./weights/Qwen3.5-9B --patch ./patch --out ./weights/merged
```

#### 步驟 4：啟用 INT4 量化並啟動服務
```bash
# 配置啟用 INT4 極簡顯存模式與融合權重路徑
cp .env.example .env
sed -i 's/^USE_INT4=.*/USE_INT4=true/' .env
sed -i 's|^BASE_MODEL=.*|BASE_MODEL=./weights/merged|' .env

# 啟動後台守護進程 (預設端口 11451)
./service.sh start

# 執行 INT4 顯存與推理自檢
python3 04_client_tests/test_int4.py
```

---

## 🎯 業務特性：旭日集團三檔審圖雙閾值機制

針對成衣與配件審圖標的，系統為每個品牌和品類設定 `[threshold_low, threshold_high]` 雙套閾值，提供自動化分流與人工協同機制：

| 判定檔位 | 判定條件 | 業務動作 | 核心目標 |
| :--- | :---: | :---: | :--- |
| **絕對符合 (`pass`)** | $\text{score} \ge \tau_{\text{high}}$ | **自動免審放行** | **極高 Precision**：放行純淨度達 98%~100%，杜絕劣質款式漏網 |
| **中度符合 (`review`)** | $\tau_{\text{low}} \le \text{score} < \tau_{\text{high}}$ | **提示人工介入審圖** | **灰度緩衝**：針對視覺語意偏離或爭議款式，由審圖員覆核兜底 |
| **絕對不符合 (`reject`)** | $\text{score} < \tau_{\text{low}}$ | **自動攔截駁回** | **極高 Specificity / Recall**：攔截線卡在極低分，絕不誤殺優質款式 |

### 1. 8 大子品牌雙閾值表
| 子品牌 (Brand) | `threshold_low` (攔截線) | `threshold_high` (放行線) | 風格調性定義 |
| :--- | :---: | :---: | :--- |
| **JEANS** | **0.15** | **0.60** | 街頭潮流、美式復古、重工水洗牛仔、寬鬆廓形、字母塗鴉與工裝解構 |
| **JKIDS** | **0.20** | **0.65** | 童趣時尚、舒適親膚、活潑明快色彩、精緻微縮印花圖案與兒童合體剪裁 |
| **JNR** | **0.30** | **0.75** | 青少年青春活力、輕運動街頭、多元拼色、適度寬鬆潮童版型 |
| **JSPORT** | **0.05** | **0.50** | 專業運動機能、吸濕速乾透氣面料、流線拼塊剪裁、反光條與科技運動質感 |
| **LIFE** | **0.25** | **0.65** | 都市商務通勤與質感生活、極簡克制、俐落剪裁、高階質感與優雅沉穩調性 |
| **MAIN** | **0.35** | **0.75** | 大眾經典休閒、百搭合身版型、簡約實用設計、品質耐穿與主流商業審美 |
| **OUTDOOR** | **0.30** | **0.80** | 山系硬核戶外、三防科技面料（防水/防風/抗撕裂）、多口袋工裝機能露營風 |
| **Z+** | **0.30** | **0.65** | 先鋒街頭潮流、暗黑解構剪裁、質感重工五金、極具辨識度的前衛設計語言 |

### 2. 7 大配件品類雙閾值表
| 配件品類 (Category) | `threshold_low` (攔截線) | `threshold_high` (放行線) | 業務處理邏輯 |
| :--- | :---: | :---: | :--- |
| **鞋子** | **0.010** | **0.500** | 視覺特徵辨識顯著，`≥0.50` 全自動免審放行，`<0.01` 自動攔截 |
| **襪子** | **0.020** | **0.500** | 正例特徵明顯，雙端純淨度高，`0.02~0.50` 提示人工覆核 |
| **家居服** | **0.005** | **0.500** | 寬鬆起居服飾，`≥0.50` 高精度放行 |
| **箱包** | **0.001** | **0.500** | 非服裝廓形語意偏移，低分段由人工介入緩衝 |
| **腰帶** | **0.001** | **0.400** | 線狀配飾特徵細小，放行線適度優化至 0.40 |
| **內褲** | **0.001** | **0.500** | 貼身輕薄件，中間段平滑接入人工覆查 |
| **內衣** | **0.0005** | **0.150** | **特殊少布料保護**：`≥0.15` 即自動通過，`0.0005~0.15` 提示人工 |

---

## 📁 階段分層工程架構

```text
style-curator-ai/
├── quick_deploy.sh         # ⚡【全自動一鍵部署】環境配置 + 下載 + 補丁 + 拼接 + INT4 推理自檢
├── update.sh               # 🔄 生產環境一鍵熱更新流水線 (Git 代碼拉取 + Release 最新權重熱替換 + 重啟)
├── service.sh              # 根目錄全域便捷維運控制腳本 (start / stop / restart / status)
├── requirements.txt        # 統一核心依賴清單
├── .env.example            # 環境變數設定範本 (支援 USE_INT4 雙重量化模式)
├── .gitignore              # 規避無用快取與大體積模型提交
│
├── 01_environment/         # 【階段一：環境搭建與基座獲取】
│   ├── setup_env.sh        # 國內清華映象源 / GPU 運行庫一鍵初始化
│   └── download_model.py   # 魔搭社區 (ModelScope) 國內高速 CDN 基座下載腳本
│
├── 02_model/               # 【階段二：核心模型與權重融合】
│   ├── core.py             # 核心模型、動態配件適配、INT4 NF4 雙重量化切換、三檔判別與推理引擎
│   ├── pack.sh             # 開發者一鍵提取打包 128MB patch.tar.gz 腳本
│   ├── merge.py            # 基座與增量 LoRA 權重物理融合工具 (merge_and_unload)
│   └── calibrate_thresholds.py # 在線標定演算法核心
│
├── 03_service/             # 【階段三：生產部署與 API 服務】
│   ├── app.py              # FastAPI 生產介面 (POST /api/analyze, /batch, GET /thresholds, /calibrate)
│   ├── service.sh          # 守護進程管理工具 (start / stop / restart / status)
│   └── data/               # 運行時動態配置資料
│       ├── thresholds.json # 8 品牌與 7 配件雙閾值設定檔 (支援秒級熱載入)
│       └── url_allowlist.conf # SSRF 白名單設定檔 (支援動態熱重載)
│
├── 04_client_tests/        # 【階段四：測試驗證與本地推理】
│   ├── smoke_test.py       # 生產服務全鏈路自動化 8 項冒煙自檢
│   ├── test_int4.py        # ⚡ INT4 雙重量化顯存與精度自檢 (驗證峰值顯存 <= 9GB)
│   ├── predict.py          # 命令行單圖 / 批量本地離線打分工具 (支援 --category)
│   └── calibrate_thresholds.py # 客戶端新品類 / 新品牌雙閾值自動標定工具
│
└── 05_training/            # 🎓【階段五：模型微調與增量後訓練】
    ├── train.py            # 核心微調腳本 (支援 LoRA 熱啟動與 QLoRA 4-bit 顯存優化)
    ├── dataset.py          # 多模態資料載入器 (支援成衣與配件專屬 Prompt 構造)
    ├── prepare_dataset.py  # 自動掃描資料夾建構 train/val (支援正負例分流)
    └── run_train.sh        # 一鍵微調訓練範本與參數範例
```

---

## ⚡ 顯存規格與 INT4 雙重量化模式對比

針對顯存有限的生產伺服器或消費級顯卡（如 RTX 3060 12GB、RTX 4060Ti 16GB、RTX 3090/4090 24GB），系統原生支援 **BitsAndBytes NF4 (Double Quantization)** 運行時動態自動量化，無需單獨重新下載數十 GB 的量化模型：

| 運行模式 | 靜態模型顯存 | 單圖推理峰值顯存 (Peak) | 決策一致率 | 最低硬體相容建議 |
| :--- | :---: | :---: | :---: | :--- |
| **標準 BF16 原生精度** | 18.50 GB | 18.82 GB | 100% (基準) | NVIDIA L20 / A100 / A800 / RTX 3090/4090 (24GB+) |
| **INT4 雙重量化模式** | **7.48 GB** | **8.59 GB (-54.4%)** | **96.67%** | **RTX 3060 (12GB) / 4060Ti (16GB) / 4070 (12GB) 等** |

### 啟用方法
在根目錄 `.env` 中設定：
```env
USE_INT4=true
```
服務啟動載入模型時，框架將在顯卡中動態以 NF4 格式存放權重，兼顧高精度與超低顯存消耗。

### INT4 顯存與精度獨立檢測
```bash
python3 04_client_tests/test_int4.py
```

---

## 🚀 常用維運控制與 API 介面規範

### 1. 服務控制命令 (預設監聽端口 11451)
```bash
./service.sh start    # 啟動後台服務
./service.sh status   # 檢查服務運行狀態與端口監聽
./service.sh restart  # 重啟服務
./service.sh stop     # 停止服務
tail -f 03_service/service.log  # 查看實時運維日誌
```

### 2. API 介面規格說明

#### (1) 單圖風格分析：`POST /api/analyze`
**請求入參 (JSON)**：
```json
{
  "image_url": "https://example.com/sample_shoe.jpg",
  "task": "MAIN",
  "category": "鞋子"
}
```
> `task`: 目標子品牌（預設 `LIFE`，支援 `LIFE`, `OUTDOOR`, `Z+`, `MAIN`, `JEANS`, `JNR`, `JKIDS`, `JSPORT`）  
> `category`: 可選配件品類（`鞋子`, `襪子`, `內褲`, `箱包`, `腰帶`, `家居服`, `內衣`），留空預設依成衣處理。

**響應返回 (JSON)**：
```json
{
  "url": "https://example.com/sample_shoe.jpg",
  "brand": "MAIN",
  "category": "鞋子",
  "probability": 0.8523,
  "decision": "pass",
  "level": "絕對符合",
  "level_code": 2,
  "manual_review_needed": false,
  "thresholds_used": {
    "low": 0.01,
    "high": 0.5
  }
}
```

#### (2) 批量任務提交：`POST /api/analyze/batch`
**請求入參 (JSON)**：
```json
{
  "urls": ["https://.../img1.jpg", "https://.../img2.jpg"],
  "task": "MAIN",
  "category": "箱包"
}
```

#### (3) 查詢當前三檔雙閾值配置表：`GET /api/thresholds`
返回 8 大子品牌與 7 大配件品類目前生效的雙閾值清單與決策規則。

---

### 3. 全鏈路自動化冒煙自檢
```bash
python3 04_client_tests/smoke_test.py
```
**期望輸出結果**：
```text
✅ [PASS] 1. 服務連通性檢測 (HTTP 200)
✅ [PASS] 2. 401 未授權防禦攔截
✅ [PASS] 3. 三檔雙閾值配置表介面 (支援 8 品牌 + 7 配件)
✅ [PASS] 4. 單圖成衣端到端三檔打分介面 (判定: 絕對符合 | low=0.3, high=0.65)
✅ [PASS] 5. 單圖配件專屬三檔打分介面 (品類: 鞋子 | 判定: 絕對符合 | low=0.01, high=0.5)
✅ [PASS] 6. 異步批量打分與輪詢 (批處理與三檔解析正常)
✅ [PASS] 7. 未標定新品類安全緩衝保護 (激活保守灰度策略 [0.01, 0.70])
✅ [PASS] 8. 在線新品類自動標定流程介面 (支援傳入樣張一鍵出閾值)
🎉 自動化冒煙測試執行完畢！
```

---

### 4. 命令行本地離線快速打分 (CLI)
```bash
# 1. 單張成衣圖片打分
python3 04_client_tests/predict.py --image sample_tshirt.jpg --brand Z+

# 2. 單張配件圖片打分 (指定品類)
python3 04_client_tests/predict.py --image sample_shoe.jpg --brand MAIN --category 鞋子

# 3. 本地資料夾批量評測
python3 04_client_tests/predict.py --dir ./my_shoes/ --brand MAIN --category 鞋子
```

**終端機打分輸出範例**：
```text
[Z+] [成衣] sample_tshirt.jpg -> 得分: 0.4230 | 判定: 中度符合 (REVIEW) [⚠️ 提示人工介入覆審] | 雙閾值: [low=0.3, high=0.65]
[MAIN] [鞋子] sample_shoe.jpg -> 得分: 0.8920 | 判定: 絕對符合 (PASS) | 雙閾值: [low=0.01, high=0.5]
```

---

## 🎯 新品類/新品牌三檔雙閾值自動標定流程 (Auto-Calibration)

當業務後續拓展**全新配件品類**（如：帽子、圍巾、手錶、手套、首飾）或**新子品牌**時，系統提供自動化標定工具，**無需重新微調訓練模型權重**：

### 命令行一鍵自動標定與持久化
準備少量該品類的正例與負例圖片（建議各 20~50 張）：
```bash
# 自動掃描目錄 (子目錄包含「符合/不符合」或「正例/反例」)
python3 04_client_tests/calibrate_thresholds.py \
  --category 帽子 \
  --dir /path/to/hats_data \
  --brand MAIN \
  --update_config
```
**自動化標定特點**：
1. 模型端到端批量打分並統計正負樣本的機率密度分布；
2. 根據目標目標（Recall $\ge 96\%$、Precision $\ge 96\%$）自動計算最優 `[low, high]`；
3. 自動持久化寫入 `03_service/data/thresholds.json`，線上 API 服務**秒級熱加載，無需重啟**！

#### 🛡️ 智慧安全緩衝機制 (Fallback)
若呼叫方傳入了尚未標定過的全新配件名稱（如未設定的「髮飾」），系統將**自動啟動保守灰度緩衝策略**：
- 自動套用保守雙閾值 `[low: 0.01, high: 0.70]`，主動擴大人工審核區間；
- 響應返回 `"calibrated": false` 及引導標定提示，確保在補全標定數據前**絕不誤殺好款式、絕不漏放劣質品**。

---

## 🔄 生產環境一鍵自動更新流水線 (update.sh)

本專案採用**程式碼與大體積模型權重解耦持續交付 (Code-Weight Decoupled CD)** 架構。當演算法團隊在 GitHub Release 發布新版模型時，運維人員只需執行一鍵更新腳本：

```bash
# 全自動更新：Git 代碼拉取 + 檢測 GitHub Release 最新權重 + 備份熱替換 + 優雅重啟服務
./update.sh
```

- **增量等冪檢測**：透過 `patch/.version` 比對版本，若已是最新版則跳過下載，2 秒內極速完成；
- **容災自動備份**：更新前自動備份現有權重至 `patch.bak/`，隨時支援一鍵回滾；
- **靈活參數支援**：
  * `./update.sh --code-only`：僅更新 Git 業務代碼與配置，不重複下載模型權重；
  * `./update.sh --weights-only`：僅更新模型權重，跳過 Git 代碼拉取；
  * `./update.sh --tag v1.0.0`：一鍵回滾或指定安裝特定 Release 版本的權重補丁；
  * `./update.sh --force`：強制重新下載並解壓覆蓋權重。

---

## 📦 客戶交付規格資訊 (GitHub Releases v1.1.0)

完整技術與交付細節請參閱 👉 [DEPLOY.md](DEPLOY.md)。
- **GitHub Release 官方頁面**：[Releases v1.1.0](https://github.com/monyhzc/style-curator-ai/releases/tag/v1.1.0)
- **核心交付附件**：[`patch.tar.gz`](https://github.com/monyhzc/style-curator-ai/releases/download/v1.1.0/patch.tar.gz)（約 128MB）
  * 內建 **Step 4004 最終冠軍模型權重**（MD5: `cb0b44251218ac80774288615564a20a`）；
  * 包含 `lora_weights/` 與 `classifier_head.pt`。
- **一鍵全自動部署**：直接運行 `bash quick_deploy.sh` 即可自動化完成全部部署流程。
