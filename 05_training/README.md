# 阶段五：模型微调与增量后训练 (Training & Continual Learning)

本模块专为 **Qwen3.5-9B 服装风格审核大模型** 的初次微调与**后续追加新数据时的增量后训练（Post-training / Continual Learning）**而设计。

---

## 🔒 核心设计原则：数据与仓库绝对解耦

- **严禁将庞大的数据集（图片、大体积 JSONL）直接提交进 Git 仓库**；
- 所有脚本均支持命令行参数 `--train_data`、`--val_data`、`--image_root` 动态指定**外部任意存储路径**；
- 产物目录（Checkpoints）默认被 `.gitignore` 过滤，保持代码库极致轻量纯净。

---

## 📁 模块文件清单

```text
05_training/
├── train.py             # 【核心训练引擎】支持从头全量微调与已有权重热启动后训练
├── dataset.py           # 【多模态加载器】读取外部标注文件，动态注入 8 品牌 Prompt 指令
├── prepare_dataset.py   # 【数据构建工具】自动扫描外部图片文件夹，生成 train/val JSONL
├── run_train.sh         # 【一键训练模板】提供多种训练场景的快速启动命令
└── README.md            # 本使用说明
```

---

## 🚀 业务实战流程

### 场景一：后续搜集了新款式/纠错样本，如何快速生成数据集？

假设您在外部磁盘存放了一批新样本：
```text
/data/new_season_samples/
├── Z+/
│   ├── T恤/*.jpg           (正例: 符合风格)
│   └── 反例/T恤/*.jpg      (负例: 商家投诉/偏离风格的错单)
└── LIFE/
    ├── 外套/*.jpg          (正例)
    └── 反例/外套/*.jpg     (负例)
```

运行数据自动构建工具：
```bash
python 05_training/prepare_dataset.py \
  --source_dir /data/new_season_samples \
  --out_dir /data/processed_jsonl \
  --val_ratio 0.15
```
> 自动扫描生成 `/data/processed_jsonl/train.jsonl` 与 `val.jsonl`。

---

### 场景二：新数据加入后，如何执行增量后训练 (热启动)？

当您有了新增数据，**无需从零重新训练几万步**，只需传入 `--resume_from` 加载上一次训练的最佳检查点，在此基础上进行微调：

```bash
python 05_training/train.py \
  --train_data /data/processed_jsonl/train.jsonl \
  --val_data /data/processed_jsonl/val.jsonl \
  --resume_from /path/to/checkpoint-best \
  --output_dir ./incremental_output \
  --epochs 2 \
  --batch_size 8 \
  --lr 1e-5
```

---

### 场景三：初次从官方原版基座进行完整微调

```bash
python 05_training/train.py \
  --train_data /data/full_dataset/train.jsonl \
  --val_data /data/full_dataset/val.jsonl \
  --output_dir ./training_output \
  --epochs 3 \
  --batch_size 8 \
  --lr 2e-5
```

---

## 📦 训练产物直接一键交付

训练脚本输出的检查点目录（如 `incremental_output/checkpoint-best/`）内部结构为：
```text
checkpoint-best/
├── lora_weights/
│   ├── adapter_model.safetensors  (LoRA 增量)
│   └── adapter_config.json
├── classifier_head.pt             (标量分类头)
└── eval_report.json               (验证集指标)
```

该结构与阶段二的打包工具 **100% 原生兼容**。训练完毕后，直接执行：
```bash
./02_model/pack.sh ./incremental_output/checkpoint-best
```
即可直接生成 138MB 的 `patch.tar.gz` 交付物！
