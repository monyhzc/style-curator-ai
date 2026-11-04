# -*- coding: utf-8 -*-
"""
dataset.py - 阶段五：训练数据集与多模态数据加载器
支持指定外部数据集路径（JSONL 文件或外部图片根目录），完全与 Git 代码库解耦。
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from PIL import Image

import torch
from torch.utils.data import Dataset
from torchvision import transforms

# 统一 8 品牌风格指导 Prompt
BRAND_PROMPTS = {
    "JEANS": "街头潮流、美式复古、重工水洗牛仔、宽松廓形、字母涂鸦与工装解构风格",
    "JKIDS": "童趣时尚、舒适亲肤、活泼明快色彩、精致微缩印花图案与儿童合体剪裁",
    "JNR": "青少年青春活力、轻运动街头、多元拼色、适度宽松潮童版型与流行元素",
    "JSPORT": "专业运动机能、吸湿速干透气面料、流线拼块剪裁、反光条与科技运动质感",
    "LIFE": "都市商务通勤与质感生活风格、注重极简克制、利落剪裁、高阶质感与优雅沉稳调性",
    "MAIN": "大众经典休闲、百搭合身版型、简约实用设计、品质耐穿与主流商业审美",
    "OUTDOOR": "山系硬核户外、三防科技面料（防水/防风/抗撕裂）、多口袋工装与机能露营风",
    "Z+": "先锋街头潮流、暗黑解构剪裁、质感重工五金、极具辨识度的前卫设计语言"
}


class ClothingStyleDataset(Dataset):
    """
    通用服装风格数据集
    支持从外部任意路径的 JSONL 文件读取，每条记录格式支持：
    {"path": "相对路径或绝对路径", "brand": "Z+", "category": "T恤", "label": 1}
    """
    def __init__(
        self,
        jsonl_path: str,
        processor,
        image_root: Optional[str] = None,
        is_train: bool = True
    ):
        self.jsonl_path = Path(jsonl_path)
        self.processor = processor
        self.image_root = Path(image_root) if image_root else None
        self.is_train = is_train
        self.items: List[Dict[str, Any]] = []

        if not self.jsonl_path.exists():
            raise FileNotFoundError(f"未找到数据集标注文件: {self.jsonl_path}")

        with open(self.jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    self.items.append(json.loads(line))
                except Exception:
                    pass

        # 训练期轻微色彩与翻转数据增强
        self.train_transform = transforms.Compose([
            transforms.RandomHorizontalFlip(p=0.5),
            transforms.ColorJitter(brightness=0.08, contrast=0.08, saturation=0.08),
        ])

    def __len__(self):
        return len(self.items)

    def _resolve_image_path(self, item: Dict[str, Any]) -> Path:
        """动态解析图片真实绝对路径"""
        p_str = item.get("abs_path") or item.get("path") or item.get("image_path")
        p = Path(p_str)
        if p.is_absolute() and p.exists():
            return p
        if self.image_root:
            candidate = self.image_root / p
            if candidate.exists():
                return candidate
        # 兜底直接返回
        return p

    def __getitem__(self, idx: int):
        item = self.items[idx]
        img_path = self._resolve_image_path(item)
        brand = str(item.get("brand", "LIFE")).upper()
        category = item.get("category", "服饰")
        label = float(item.get("label", 1.0))

        # 容错加载
        try:
            image = Image.open(img_path).convert("RGB")
            if self.is_train:
                image = self.train_transform(image)
        except Exception:
            # 异常图片自动回退白底，保证训练不崩
            image = Image.new("RGB", (768, 768), color=(255, 255, 255))

        brand_desc = BRAND_PROMPTS.get(brand, "大众休闲流行风格与质感要求")
        prompt_text = (
            f"这是一件【{category}】服饰。请仔细审视其版型廓形、剪裁细节、面料肌理质感与设计印花，"
            f"结合【{brand}】（{brand_desc}）的核心设计语言，严格审核判断它是否契合该品牌的风格调性要求。"
        )

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt_text}
                ]
            }
        ]

        text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
        return {
            "image": image,
            "text": text,
            "label": label,
            "brand": brand,
            "category": category,
            "path": str(img_path)
        }


class BatchCollateFn:
    """批处理拼接器"""
    def __init__(self, processor):
        self.processor = processor

    def __call__(self, batch: List[Dict[str, Any]]):
        images = [item["image"] for item in batch]
        texts = [item["text"] for item in batch]
        labels = torch.tensor([item["label"] for item in batch], dtype=torch.float32)

        inputs = self.processor(
            text=texts,
            images=images,
            padding=True,
            return_tensors="pt"
        )
        inputs["labels"] = labels
        inputs["brands"] = [item["brand"] for item in batch]
        inputs["categories"] = [item["category"] for item in batch]
        inputs["paths"] = [item["path"] for item in batch]
        return inputs
