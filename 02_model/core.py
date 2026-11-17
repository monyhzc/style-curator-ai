# -*- coding: utf-8 -*-
"""
model.py - 选款 AI 核心模型与推理引擎
基于 Qwen3.5-9B + Vision LoRA + 4096 标量分类头，支持全量 8 品牌统一端到端风格契合度打分。
"""

import os
import json
import torch
import torch.nn as nn
from PIL import Image
from pathlib import Path
from typing import List, Tuple, Optional, Any, Dict
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

# 旭日集团三档审图决策双套阈值表 (8大品牌 + 7大配件品类)
# low:  自动拦截阈值 (score < low 直接判定【绝对不符合】，拉高整体 Recall，保证零误杀优质款式)
# high: 自动放行阈值 (score >= high 直接判定【绝对符合】，拉高整体 Precision，保证放行纯度无劣质款式)
# [low, high): 判定为【中度符合】，提示人工介入审图复核
DUAL_THRESHOLDS = {
    "brands": {
        "JEANS": {"low": 0.15, "high": 0.60},
        "JKIDS": {"low": 0.20, "high": 0.65},
        "JNR": {"low": 0.30, "high": 0.75},
        "JSPORT": {"low": 0.05, "high": 0.50},
        "LIFE": {"low": 0.25, "high": 0.65},
        "MAIN": {"low": 0.35, "high": 0.75},
        "OUTDOOR": {"low": 0.30, "high": 0.80},
        "Z+": {"low": 0.30, "high": 0.65}
    },
    "accessories": {
        "鞋子": {"low": 0.010, "high": 0.500},
        "袜子": {"low": 0.020, "high": 0.500},
        "家居服": {"low": 0.005, "high": 0.500},
        "箱包": {"low": 0.001, "high": 0.500},
        "腰带": {"low": 0.001, "high": 0.400},
        "内裤": {"low": 0.001, "high": 0.500},
        "内衣": {"low": 0.0005, "high": 0.150}
    }
}

# 动态热加载 03_service/data/thresholds.json 外部配置文件 (若存在)
_CFG_CANDIDATES = [
    Path(__file__).resolve().parent.parent / "03_service/data/thresholds.json",
    Path(os.environ.get("THRESHOLDS_PATH", ""))
]
for _cp in _CFG_CANDIDATES:
    if _cp and _cp.exists() and _cp.is_file():
        try:
            with open(_cp, "r", encoding="utf-8") as _f:
                _cfg_data = json.load(_f)
                if "brands" in _cfg_data and "accessories" in _cfg_data:
                    DUAL_THRESHOLDS = _cfg_data
                    break
        except Exception:
            pass

def reload_thresholds() -> bool:
    """动态热重载 03_service/data/thresholds.json 外部配置文件"""
    global DUAL_THRESHOLDS, ACCESSORY_CATEGORIES
    _CFG_CANDIDATES = [
        Path(__file__).resolve().parent.parent / "03_service/data/thresholds.json",
        Path(os.environ.get("THRESHOLDS_PATH", ""))
    ]
    for _cp in _CFG_CANDIDATES:
        if _cp and _cp.exists() and _cp.is_file():
            try:
                with open(_cp, "r", encoding="utf-8") as _f:
                    _cfg_data = json.load(_f)
                    if "brands" in _cfg_data and "accessories" in _cfg_data:
                        DUAL_THRESHOLDS = _cfg_data
                        ACCESSORY_CATEGORIES = set(DUAL_THRESHOLDS["accessories"].keys())
                        return True
            except Exception:
                pass
    return False

reload_thresholds()
ACCESSORY_CATEGORIES = set(DUAL_THRESHOLDS["accessories"].keys())


def get_decision_level(score: float, brand: str = "MAIN", category: Optional[str] = None) -> dict:
    """
    根据模型概率分数与目标品类/子品牌，执行旭日集团三档业务判定
    支持新品类自动适配：若遇到未标定新品类，自动启用安全保守缓冲阈值 [0.01, 0.70]，扩大人工复审比例
    返回:
      decision: "pass" | "review" | "reject"
      level: "绝对符合" | "中度符合" | "绝对不符合"
      level_code: 2 | 1 | 0
      manual_review_needed: False | True | False
      thresholds_used: {"low": float, "high": float, "calibrated": bool}
    """
    b_name = (brand or "MAIN").upper()
    cat_name = category.strip() if category else None
    calibrated = True

    # 1. 优先匹配配件专属阈值
    if cat_name and cat_name in DUAL_THRESHOLDS.get("accessories", {}):
        thrs = DUAL_THRESHOLDS["accessories"][cat_name]
    # 2. 匹配已标定子品牌 (成衣)
    elif b_name in DUAL_THRESHOLDS.get("brands", {}):
        thrs = DUAL_THRESHOLDS["brands"][b_name]
        # 若用户传入了未在配件表中的全新配件名 (例如: 帽子、围巾等)
        if cat_name and cat_name not in ("服装", "成衣"):
            calibrated = False
            # 启用安全保守灰度双阈值 [0.01, 0.70]，扩大人工审核区间，防止误判
            thrs = {"low": 0.01, "high": 0.70}
    else:
        thrs = {"low": 0.30, "high": 0.70}
        calibrated = False

    low = thrs["low"]
    high = thrs["high"]

    if score >= high:
        decision = "pass"
        level = "绝对符合"
        level_code = 2
        manual_review = False
    elif score < low:
        decision = "reject"
        level = "绝对不符合"
        level_code = 0
        manual_review = False
    else:
        decision = "review"
        level = "中度符合"
        level_code = 1
        manual_review = True

    res = {
        "decision": decision,
        "level": level,
        "level_code": level_code,
        "manual_review_needed": manual_review,
        "thresholds_used": {
            "low": low,
            "high": high,
            "calibrated": calibrated
        }
    }
    if not calibrated and cat_name:
        res["thresholds_used"]["notice"] = f"新品类【{cat_name}】尚未独立标定双阈值，已启用安全保守缓冲策略，建议运行 calibrate_thresholds.py 自动标定"

    return res


class FashionClassifier(nn.Module):
    """端到端视觉语言分类器架构 (支持 BF16 原生与 INT4 NF4 双重量化)"""
    def __init__(self, base_model_id: str, load_in_4bit: bool = False):
        super().__init__()
        self.load_in_4bit = load_in_4bit
        quant_config = None
        if load_in_4bit:
            try:
                from transformers import BitsAndBytesConfig
                quant_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_compute_dtype=torch.bfloat16,
                    bnb_4bit_use_double_quant=True
                )
                print(f"[Model] 启用了 INT4 (NF4) 极简显存量化模式 (推理峰值显存 <= 9GB)")
            except Exception as e:
                print(f"[Model] 警告: BitsAndBytes 导入失败，自动回退至 BF16 精度: {e}")
                self.load_in_4bit = False

        self.backbone = AutoModelForImageTextToText.from_pretrained(
            base_model_id,
            torch_dtype=torch.bfloat16,
            quantization_config=quant_config,
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
    def get_instance(cls, base_model: Optional[str] = None, patch_dir: Optional[str] = None, load_in_4bit: Optional[bool] = None):
        if cls._instance is None:
            if base_model is None:
                env_base = os.environ.get("BASE_MODEL")
                if env_base:
                    base_model = env_base
                elif Path("./weights/merged").exists():
                    base_model = "./weights/merged"
                elif Path("./weights/Qwen3.5-9B").exists():
                    base_model = "./weights/Qwen3.5-9B"
                else:
                    base_model = "Qwen/Qwen3.5-9B"
            if load_in_4bit is None:
                load_in_4bit = os.environ.get("USE_INT4", "false").lower() in ("1", "true", "yes")
            cls._instance = cls(base_model, patch_dir, load_in_4bit=load_in_4bit)
        return cls._instance

    def __init__(self, base_model: str = "Qwen/Qwen3.5-9B", patch_dir: Optional[str] = None, load_in_4bit: bool = False):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.load_in_4bit = load_in_4bit
        if patch_dir is None:
            patch_dir = os.environ.get("PATCH_DIR", "./patch")
        self.patch_dir = Path(patch_dir)

        print(f"[Model] 正在加载 Qwen3.5-9B 处理器...")
        self.processor = AutoProcessor.from_pretrained(
            base_model, min_pixels=256 * 28 * 28, max_pixels=768 * 768
        )
        print(f"[Model] 正在初始化基座结构 (INT4模式: {self.load_in_4bit})...")
        self.model = FashionClassifier(base_model, load_in_4bit=self.load_in_4bit)

        lora_path = self.patch_dir / "lora_weights"
        head_path = self.patch_dir / "classifier_head.pt"
        if not head_path.exists() and (Path(base_model) / "classifier_head.pt").exists():
            head_path = Path(base_model) / "classifier_head.pt"

        if lora_path.exists():
            print(f"[Model] 挂载 LoRA 权重: {lora_path}")
            self.model.backbone = PeftModel.from_pretrained(self.model.backbone, str(lora_path))
        if head_path.exists():
            print(f"[Model] 加载标量分类头: {head_path}")
            self.model.classifier.load_state_dict(torch.load(head_path, map_location=self.device))

        self.model.eval()
        torch.cuda.empty_cache()
        print(f"[Model] 选款引擎就绪 (设备: {self.device}, INT4: {self.load_in_4bit})")

    def predict(self, items: List[Any]) -> List[float]:
        """
        批量预测:
          items 支持两种入参格式:
          - [(PIL.Image, brand), ...]
          - [(PIL.Image, brand, category), ...]
        返回: [0.985, ...]
        """
        if not items:
            return []

        batch_texts, batch_images = [], []
        for item in items:
            img = item[0]
            brand = item[1]
            cat = item[2] if len(item) > 2 else None

            b_name = (brand or "MAIN").upper()
            desc = BRAND_PROMPTS.get(b_name, "大众经典休闲、百搭合身版型、简约实用设计")

            if cat and cat in ACCESSORY_CATEGORIES:
                prompt = (
                    f"这是一件{cat}配件。请仔细审视其外观设计、材质细节、做工质感与视觉风格，"
                    f"结合【真维斯（{b_name}）】（{desc}）的核心品牌设计语言，严格审核判断它是否契合该品牌的风格调性要求。"
                )
            else:
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

    def predict_one(self, image: Image.Image, brand: str, category: Optional[str] = None) -> float:
        res = self.predict([(image, brand, category)])
        return res[0] if res else 0.5

    def predict_one_with_decision(self, image: Image.Image, brand: str, category: Optional[str] = None) -> dict:
        score = self.predict_one(image, brand, category)
        decision = get_decision_level(score, brand, category)
        return {"probability": score, **decision}
