# -*- coding: utf-8 -*-
"""
train.py - 阶段五：Qwen3.5-9B 服装风格微调与增量后训练脚本
支持两种训练模式：
  1. 从头全量微调 (从官方原版 Qwen3.5-9B 基座出发)
  2. 加新数据增量后训练 (基于已有 checkpoint-best 热启动，只学新增/纠错样本)
完全支持指定外部数据集目录，绝不污染 Git 仓库。
"""

import os
import sys
import time
import json
import argparse
from pathlib import Path
from typing import Optional

import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from transformers import AutoProcessor, AutoModelForImageTextToText, get_cosine_schedule_with_warmup
from peft import LoraConfig, get_peft_model, TaskType, PeftModel
import safetensors.torch
from sklearn.metrics import accuracy_score, average_precision_score

# 关联当前阶段数据集
CURRENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CURRENT_DIR))
from dataset import ClothingStyleDataset, BatchCollateFn


class FashionClassifier(nn.Module):
    """端到端视觉语言分类器架构 (Qwen3.5-9B + LoRA + 4096 标量分类头)"""
    def __init__(self, base_model_id: str, lora_r: int = 16, lora_alpha: int = 32):
        super().__init__()
        print(f"[Model] 加载多模态基座: {base_model_id}")
        self.backbone = AutoModelForImageTextToText.from_pretrained(
            base_model_id,
            torch_dtype=torch.bfloat16,
            device_map="auto"
        )
        self.backbone.gradient_checkpointing_enable()

        # 视觉塔 (ViT) 与语言大模型 (LLM) 双重关键投影层
        target_modules = [
            "q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj",
            "qkv", "linear_fc1", "linear_fc2"
        ]
        lora_config = LoraConfig(
            r=lora_r,
            lora_alpha=lora_alpha,
            target_modules=target_modules,
            lora_dropout=0.05,
            bias="none",
            task_type=TaskType.FEATURE_EXTRACTION,
        )
        self.backbone = get_peft_model(self.backbone, lora_config)

        try:
            hidden_size = self.backbone.config.hidden_size
        except AttributeError:
            hidden_size = self.backbone.config.text_config.hidden_size
        if hidden_size is None:
            hidden_size = 4096

        self.dropout = nn.Dropout(0.1)
        self.classifier = nn.Linear(hidden_size, 1, dtype=torch.bfloat16).to(self.backbone.device)

    def forward(self, input_ids, attention_mask=None, pixel_values=None, image_grid_thw=None, labels=None, **kwargs):
        outputs = self.backbone(
            input_ids=input_ids,
            attention_mask=attention_mask,
            pixel_values=pixel_values,
            image_grid_thw=image_grid_thw,
            output_hidden_states=True,
            return_dict=True,
            **kwargs,
        )
        last_hidden = outputs.hidden_states[-1]
        if attention_mask is not None:
            seq_lens = attention_mask.sum(dim=1) - 1
            pooled = last_hidden[torch.arange(last_hidden.shape[0]), seq_lens]
        else:
            pooled = last_hidden[:, -1, :]

        pooled = self.dropout(pooled)
        logits = self.classifier(pooled).squeeze(-1)

        loss = None
        if labels is not None:
            loss_fn = nn.BCEWithLogitsLoss()
            loss = loss_fn(logits.float(), labels.float())

        return {"loss": loss, "logits": logits, "score": torch.sigmoid(logits.float())}


def evaluate(model, loader, device):
    """验证集评估"""
    model.eval()
    torch.cuda.empty_cache()
    all_labels, all_preds = [], []
    total_loss = 0.0

    with torch.no_grad():
        for batch in loader:
            labels = batch.pop("labels").to(device)
            _ = batch.pop("categories", None)
            _ = batch.pop("brands", None)
            _ = batch.pop("paths", None)
            batch = {k: v.to(device) if isinstance(v, torch.Tensor) else v for k, v in batch.items()}
            out = model(**batch, labels=labels)
            total_loss += float(out["loss"].item())
            all_labels.extend(labels.cpu().numpy().tolist())
            all_preds.extend(out["score"].cpu().numpy().tolist())

    acc = accuracy_score(all_labels, [1 if p >= 0.5 else 0 for p in all_preds])
    try:
        ap = average_precision_score(all_labels, all_preds)
    except Exception:
        ap = 0.0
    avg_loss = total_loss / max(len(loader), 1)
    return {"val_loss": round(avg_loss, 4), "acc": round(acc, 4), "ap": round(ap, 4)}


def main():
    parser = argparse.ArgumentParser(description="选款 AI 多模态微调与增量后训练主脚本")
    # 数据集路径解耦 (必选/关键)
    parser.add_argument("--train_data", type=str, required=True, help="外部训练集 JSONL 标注文件路径")
    parser.add_argument("--val_data", type=str, default=None, help="外部验证集 JSONL 标注文件路径")
    parser.add_argument("--image_root", type=str, default=None, help="外部图片根目录 (若 JSONL 中为相对路径)")
    
    # 模型基座与热启动 (后训练增量支持)
    parser.add_argument("--base_model", type=str, default="Qwen/Qwen3.5-9B", help="官方基座模型名称或本地路径")
    parser.add_argument("--resume_from", type=str, default=None, help="热启动目录 (加载已有 checkpoint 继续训练)")
    
    # 超参数与输出配置
    parser.add_argument("--output_dir", type=str, default="./training_output", help="产物输出目录")
    parser.add_argument("--epochs", type=int, default=3, help="训练轮数")
    parser.add_argument("--batch_size", type=int, default=8, help="单步批大小 (推荐 8~16)")
    parser.add_argument("--grad_accum", type=int, default=2, help="梯度累加步数")
    parser.add_argument("--lr", type=float, default=2e-5, help="学习率 (后训练微调推荐 1e-5 ~ 2e-5)")
    parser.add_argument("--save_steps", type=int, default=100, help="每隔多少步保存并评估一次")
    parser.add_argument("--max_steps", type=int, default=None, help="最大步数 (调试或冒烟测试用)")
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("==================================================")
    print("🔥 Style Curator AI - 启动模型微调 / 后训练")
    print(f"• 训练数据:   {args.train_data}")
    print(f"• 验证数据:   {args.val_data or '无 (跳过评估)'}")
    print(f"• 产物目录:   {out_dir}")
    print(f"• 基座模型:   {args.base_model}")
    print(f"• 热启动模式: {'已启用 (从 ' + args.resume_from + ' 继续)' if args.resume_from else '否 (从头微调)'}")
    print(f"• 有效 Batch: {args.batch_size * args.grad_accum} | 学习率: {args.lr}")
    print("==================================================\n")

    # 1. 处理器与数据加载
    print("⏳ [1/4] 加载多模态处理器与外部数据集...")
    processor = AutoProcessor.from_pretrained(
        args.base_model, min_pixels=256 * 28 * 28, max_pixels=768 * 768
    )

    train_ds = ClothingStyleDataset(args.train_data, processor, image_root=args.image_root, is_train=True)
    val_ds = ClothingStyleDataset(args.val_data, processor, image_root=args.image_root, is_train=False) if args.val_data else None

    collate_fn = BatchCollateFn(processor)
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, collate_fn=collate_fn, num_workers=2)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False, collate_fn=collate_fn, num_workers=2) if val_ds else None

    print(f"✅ 成功加载: 训练集 {len(train_ds)} 样本 | 验证集 {len(val_ds) if val_ds else 0} 样本")

    # 2. 模型初始化与热启动权重注入
    print("⏳ [2/4] 初始化网络结构与权重...")
    model = FashionClassifier(args.base_model)

    if args.resume_from and Path(args.resume_from).exists():
        r_dir = Path(args.resume_from)
        lora_p = r_dir / "lora_weights"
        head_p = r_dir / "classifier_head.pt"
        if (lora_p / "adapter_model.safetensors").exists():
            print(f"• 注入已有 LoRA 增量权重: {lora_p}")
            w = safetensors.torch.load_file(str(lora_p / "adapter_model.safetensors"))
            from peft import set_peft_model_state_dict
            set_peft_model_state_dict(model.backbone, w)
        if head_p.exists():
            print(f"• 注入已有打分头权重: {head_p}")
            model.classifier.load_state_dict(torch.load(head_p, map_location=device))

    # 3. 优化器与调度器
    total_steps = len(train_loader) * args.epochs // args.grad_accum
    if args.max_steps:
        total_steps = min(total_steps, args.max_steps)

    optimizer = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad],
        lr=args.lr,
        weight_decay=0.01
    )
    scheduler = get_cosine_schedule_with_warmup(
        optimizer, num_warmup_steps=max(int(total_steps * 0.05), 1), num_training_steps=max(total_steps, 1)
    )

    # 4. 训练迭代循环
    print("⏳ [3/4] 开始迭代训练...")
    global_step = 0
    best_ap = 0.0
    optimizer.zero_grad()

    model.train()
    start_time = time.time()

    for epoch in range(args.epochs):
        for step, batch in enumerate(train_loader):
            labels = batch.pop("labels").to(device)
            _ = batch.pop("categories", None)
            _ = batch.pop("brands", None)
            _ = batch.pop("paths", None)
            batch = {k: v.to(device) if isinstance(v, torch.Tensor) else v for k, v in batch.items()}

            out = model(**batch, labels=labels)
            loss = out["loss"] / args.grad_accum
            loss.backward()

            if (step + 1) % args.grad_accum == 0 or (step + 1) == len(train_loader):
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad()
                global_step += 1

                if global_step % 10 == 0 or global_step == 1:
                    lr_curr = optimizer.param_groups[0]["lr"]
                    print(f"Epoch [{epoch+1}/{args.epochs}] Step {global_step}/{total_steps} | Loss: {loss.item()*args.grad_accum:.4f} | LR: {lr_curr:.2e}")

                # 定期评估与 Checkpoint 保存
                if val_loader and (global_step % args.save_steps == 0 or global_step == total_steps):
                    metrics = evaluate(model, val_loader, device)
                    print(f"\n📊 [评估 Step {global_step}] Loss: {metrics['val_loss']} | Acc: {metrics['acc']} | AP: {metrics['ap']}")

                    # 保存最新检查点
                    ckpt_p = out_dir / f"checkpoint-step-{global_step}"
                    save_checkpoint(model, ckpt_p, metrics)

                    if metrics["ap"] >= best_ap:
                        best_ap = metrics["ap"]
                        save_checkpoint(model, out_dir / "checkpoint-best", metrics)
                        print(f"🌟 刷新最佳指标！已同步保存至: {out_dir / 'checkpoint-best'}\n")

                    model.train()

                if args.max_steps and global_step >= args.max_steps:
                    break
        if args.max_steps and global_step >= args.max_steps:
            break

    # 训练收官最终保存
    save_checkpoint(model, out_dir / "checkpoint-final", {"status": "finished"})
    elapsed = round(time.time() - start_time, 1)
    print(f"\n🎉 训练全部完成！耗时: {elapsed} 秒，产物已归档至: {out_dir}")
    print(f"👉 您可直接使用 ./02_model/pack.sh {out_dir / 'checkpoint-best'} 一键生成客户交付包。")


def save_checkpoint(model, target_dir: Path, metrics: dict):
    """保存标准格式的 LoRA 权重与打分头 (直接适配 02_model/pack.sh)"""
    target_dir.mkdir(parents=True, exist_ok=True)
    lora_dir = target_dir / "lora_weights"
    lora_dir.mkdir(parents=True, exist_ok=True)

    # 保存 LoRA safetensors 与配置
    model.backbone.save_pretrained(str(lora_dir), safe_serialization=True)
    # 保存标量分类头
    torch.save(model.classifier.state_dict(), str(target_dir / "classifier_head.pt"))
    # 保存指标日志
    with open(target_dir / "eval_report.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
