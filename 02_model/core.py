# -*- coding: utf-8 -*-
"""
model.py - 选款 AI 核心模型与推理引擎
基于 Qwen3.5-9B + Vision LoRA + 4096 标量分类头，支持全量 8 品牌统一端到端风格契合度打分。
"""

import os
import torch
import torch.nn as nn
from PIL import Image
from pathlib import Path
from typing import List, Tuple, Optional
from transformers import AutoProcessor, AutoModelForImageTextToText
from peft import PeftModel

# 8 大品牌专属风格调性定义
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


class FashionClassifier(nn.Module):
    """端到端视觉语言分类器架构"""
    def __init__(self, base_model_id: str):
        super().__init__()
        self.backbone = AutoModelForImageTextToText.from_pretrained(
            base_model_id,
            torch_dtype=torch.bfloat16,
            device_map="auto"
        )
        try:
            hidden_size = self.backbone.config.hidden_size
        except AttributeError:
            hidden_size = self.backbone.config.text_config.hidden_size
        if hidden_size is None:
            hidden_size = 4096

        self.dropout = nn.Dropout(0.1)
        self.classifier = nn.Linear(hidden_size, 1, dtype=torch.bfloat16).to(self.backbone.device)

    def forward(self, input_ids, attention_mask=None, pixel_values=None, image_grid_thw=None, **kwargs):
        out = self.backbone(
            input_ids=input_ids,
            attention_mask=attention_mask,
            pixel_values=pixel_values,
            image_grid_thw=image_grid_thw,
            output_hidden_states=True,
            return_dict=True,
            **kwargs
        )
        last_hidden_state = out.hidden_states[-1]
        if attention_mask is not None:
            seq_lens = attention_mask.sum(dim=1) - 1
            pooled = last_hidden_state[torch.arange(last_hidden_state.shape[0]), seq_lens]
        else:
            pooled = last_hidden_state[:, -1, :]

        pooled = self.dropout(pooled)
        logits = self.classifier(pooled).squeeze(-1)
        return torch.sigmoid(logits.float())


class StyleEngine:
    """推理单例引擎"""
    _instance = None

    @classmethod
    def get_instance(cls, base_model: str = "Qwen/Qwen3.5-9B", patch_dir: Optional[str] = None):
        if cls._instance is None:
            cls._instance = cls(base_model, patch_dir)
        return cls._instance

    def __init__(self, base_model: str = "Qwen/Qwen3.5-9B", patch_dir: Optional[str] = None):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        if patch_dir is None:
            patch_dir = os.environ.get("PATCH_DIR", "./patch")
        self.patch_dir = Path(patch_dir)

        print(f"[Model] 正在加载 Qwen3.5-9B 处理器...")
        self.processor = AutoProcessor.from_pretrained(
            base_model, min_pixels=256 * 28 * 28, max_pixels=768 * 768
        )
        print(f"[Model] 正在初始化基座结构...")
        self.model = FashionClassifier(base_model)

        lora_path = self.patch_dir / "lora_weights"
        head_path = self.patch_dir / "classifier_head.pt"

        if lora_path.exists():
            print(f"[Model] 挂载 LoRA 权重: {lora_path}")
            self.model.backbone = PeftModel.from_pretrained(self.model.backbone, str(lora_path))
        if head_path.exists():
            print(f"[Model] 加载标量分类头: {head_path}")
            self.model.classifier.load_state_dict(torch.load(head_path, map_location=self.device))

        self.model.eval()
        torch.cuda.empty_cache()
        print(f"[Model] 选款引擎就绪 (设备: {self.device})")

    def predict(self, items: List[Tuple[Image.Image, str]]) -> List[float]:
        """批量预测 [(PIL.Image, brand), ...] -> [0.985, ...]"""
        if not items:
            return []

        batch_texts, batch_images = [], []
        for img, brand in items:
            b_name = brand.upper()
            desc = BRAND_PROMPTS.get(b_name, "大众休闲流行风格与质感")
            prompt = (
                f"这是一件服饰。请仔细审视其版型廓形、剪裁细节、面料肌理质感与设计印花，"
                f"结合【{b_name}】（{desc}）的核心设计语言，严格审核判断它是否契合该品牌的风格调性要求。"
            )
            messages = [{"role": "user", "content": [{"type": "image", "image": img}, {"type": "text", "text": prompt}]}]
            text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
            batch_texts.append(text)
            batch_images.append(img)

        inputs = self.processor(text=batch_texts, images=batch_images, padding=True, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            scores = self.model(**inputs)
            if scores.ndim == 0:
                scores = scores.unsqueeze(0)
            return [round(float(s), 4) for s in scores.cpu().numpy()]

    def predict_one(self, image: Image.Image, brand: str) -> float:
        res = self.predict([(image, brand)])
        return res[0] if res else 0.5
