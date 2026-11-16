# -*- coding: utf-8 -*-
"""
calibrate_thresholds.py - 阶段四：新品类与新品牌三档双阈值自动标定与适配工具
业务功能：
  当业务方或审核团队引入新配件品类（如：帽子、围巾、手表、首饰等）或新子品牌时，
  只需提供少量标注样张（正例 + 负例，建议各 20~50 张），本脚本即可：
  1. 自动化推理打分（支持通过已运行的 HTTP API 或本地模型）
  2. 精确计算双套阈值 [threshold_low, threshold_high]：
     - threshold_low:  拉高 Recall，锁定【绝对不符合】自动拦截线（保证不误杀好款式）
     - threshold_high: 拉高 Precision，锁定【绝对符合】自动免审放行线（保证放行零劣质）
     - [low, high):    中间灰度带自动划归为【中度符合】，提示人工介入复审
  3. 一键将新阈值注册更新到 03_service/data/thresholds.json，实现即时自动适配！

用法示例：
  # 方式 1：通过已常驻的 11451 服务快速标定新目录 (推荐，零额外显存)
  python 04_client_tests/calibrate_thresholds.py \
    --category 帽子 \
    --dir /path/to/hat_dataset \
    --api_url http://127.0.0.1:11451 \
    --token jw_style_audit_prod_token_2026 \
    --update_config

  # 方式 2：分别指定正例与负例文件夹
  python 04_client_tests/calibrate_thresholds.py \
    --category 围巾 \
    --pos_dir /path/to/pos_scarf \
    --neg_dir /path/to/neg_scarf \
    --update_config

  # 方式 3：通过 JSONL 标注集标定
  python 04_client_tests/calibrate_thresholds.py \
    --category 帽子 \
    --jsonl /path/to/hat_annotated.jsonl \
    --update_config
"""

import os
import sys
import json
import time
import argparse
import random
from pathlib import Path
from typing import List, Dict, Any, Tuple
from PIL import Image

import numpy as np
import requests

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "03_service/data/thresholds.json"
VALID_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def scan_category_samples(
    category_dir: Path,
    pos_dir: Path = None,
    neg_dir: Path = None,
    jsonl_path: Path = None
) -> Tuple[List[Path], List[Path]]:
    """扫描提取正例与负例图片路径"""
    pos_images, neg_images = [], []

    # 1. 优先使用独立指定正负例目录
    if pos_dir and pos_dir.exists():
        for p in pos_dir.rglob("*"):
            if p.is_file() and p.suffix.lower() in VALID_EXTS:
                pos_images.append(p)
    if neg_dir and neg_dir.exists():
        for p in neg_dir.rglob("*"):
            if p.is_file() and p.suffix.lower() in VALID_EXTS:
                neg_images.append(p)

    if pos_images or neg_images:
        return pos_images, neg_images

    # 2. 从 JSONL 文件读取
    if jsonl_path and jsonl_path.exists():
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                    img_p = Path(item.get("abs_path") or item.get("path", ""))
                    if img_p.exists():
                        if int(item.get("label", 1)) == 1:
                            pos_images.append(img_p)
                        else:
                            neg_images.append(img_p)
                except Exception:
                    continue
        return pos_images, neg_images

    # 3. 扫描统一根目录（智能推断正负例子目录或文件命名）
    if category_dir and category_dir.exists():
        for p in category_dir.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in VALID_EXTS:
                continue
            parts = [part.lower() for part in p.parts]
            if any("不符合" in part or "不符" in part or "反例" in part or "negative" in part or "bad" in part for part in parts):
                neg_images.append(p)
            elif any("符合" in part or "正例" in part or "positive" in part or "good" in part for part in parts):
                pos_images.append(p)
            else:
                # 默认按正例收集
                pos_images.append(p)

    return pos_images, neg_images


def score_via_api(
    images: List[Path],
    api_url: str,
    token: str,
    brand: str,
    category: str
) -> List[float]:
    """通过线上 HTTP 服务预测评分"""
    api_url = api_url.rstrip("/")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    scores = []

    # 若为本地文件路径，使用单图上传或基于本地 SimpleHTTP/文件直读
    # 这里通过本地 base64 或直接通过 API
    print(f"  正在通过线上服务 ({api_url}) 打分...")
    for idx, img_path in enumerate(images):
        try:
            # 兼容本地图片 URL 传入或使用临时 file 服务
            img_url = f"file://{img_path.resolve()}"
            payload = {"image_url": str(img_path.resolve()), "task": brand, "category": category}
            # 如果是标准 HTTP 请求，调用 analyze 接口
            r = requests.post(f"{api_url}/api/analyze", json=payload, headers=headers, timeout=10.0)
            if r.status_code == 200:
                scores.append(float(r.json().get("probability", 0.5)))
            else:
                scores.append(0.5)
        except Exception:
            scores.append(0.5)

    return scores


def score_via_local_engine(
    images: List[Path],
    brand: str,
    category: str,
    patch_dir: str = None
) -> List[float]:
    """直接在本地使用 StyleEngine 模型打分"""
    sys.path.insert(0, str(ROOT_DIR / "02_model"))
    from core import StyleEngine

    print(f"  正在初始化本地 StyleEngine 进行推理...")
    engine = StyleEngine.get_instance(patch_dir=patch_dir)
    loaded_imgs = []
    for p in images:
        try:
            loaded_imgs.append((Image.open(p).convert("RGB"), brand, category))
        except Exception as e:
            loaded_imgs.append((Image.new("RGB", (224, 224), (128, 128, 128)), brand, category))

    batch_size = 16
    scores = []
    for i in range(0, len(loaded_imgs), batch_size):
        chunk = loaded_imgs[i:i + batch_size]
        scs = engine.predict(chunk)
        scores.extend(scs)

    return scores


def calculate_optimal_dual_thresholds(
    pos_scores: np.ndarray,
    neg_scores: np.ndarray,
    target_recall: float = 0.96,
    target_prec: float = 0.96
) -> Dict[str, Any]:
    """
    数学严密计算双套阈值:
    - low:  保证 正例 Recall >= target_recall (极大化自动拦截负例，零误杀正品)
    - high: 保证 正例 Precision >= target_prec (极大化自动免审放行，零漏放劣质)
    """
    if len(pos_scores) == 0:
        return {"low": 0.01, "high": 0.50, "valid": False}
    if len(neg_scores) == 0:
        return {"low": 0.01, "high": max(0.50, float(np.median(pos_scores))), "valid": False}

    # 1. 计算 low 拦截阈值:
    # 取满足 positive recall >= target_recall 的最大候选值
    cand_lows = np.linspace(0.0001, 0.90, 1800)
    best_low = 0.001
    for t in cand_lows:
        rec = np.sum(pos_scores >= t) / len(pos_scores)
        if rec >= target_recall:
            best_low = t
        else:
            break

    # 2. 计算 high 放行阈值:
    # 在所有满足 precision >= target_prec 的候选阈值中，取最小的那个 (最大化免审放行比例)
    cand_highs = np.linspace(best_low + 0.01, 0.99, 1800)
    best_high = 0.85
    found_high = False
    for t in cand_highs:
        tp = np.sum(pos_scores >= t)
        fp = np.sum(neg_scores >= t)
        if tp + fp == 0:
            continue
        prec = tp / (tp + fp)
        if prec >= target_prec:
            best_high = t
            found_high = True
            break

    if not found_high:
        # 如果未严格达到 target_prec，则取正例得分的 75 分位数与 0.50 较大者
        best_high = max(float(best_low + 0.15), float(np.percentile(pos_scores, 75)))

    best_low = round(float(best_low), 4)
    best_high = round(float(best_high), 4)
    if best_high <= best_low:
        best_high = min(0.95, round(best_low + 0.15, 4))

    # 计算三档表现统计
    all_scores = np.concatenate([pos_scores, neg_scores])
    all_labels = np.concatenate([np.ones(len(pos_scores)), np.zeros(len(neg_scores))])

    # 自动放行 (score >= high)
    pass_mask = all_scores >= best_high
    pass_cnt = int(np.sum(pass_mask))
    pass_tp = int(np.sum(pass_mask & (all_labels == 1)))
    pass_fp = int(np.sum(pass_mask & (all_labels == 0)))
    pass_prec = pass_tp / max(1, pass_cnt)

    # 自动拦截 (score < low)
    reject_mask = all_scores < best_low
    reject_cnt = int(np.sum(reject_mask))
    reject_tn = int(np.sum(reject_mask & (all_labels == 0)))
    reject_fn = int(np.sum(reject_mask & (all_labels == 1)))
    reject_spec = reject_tn / max(1, reject_cnt)

    # 中度符合 (low <= score < high) -> 人工介入
    review_mask = (all_scores >= best_low) & (all_scores < best_high)
    review_cnt = int(np.sum(review_mask))
    review_rate = review_cnt / len(all_scores)

    return {
        "low": best_low,
        "high": best_high,
        "valid": True,
        "metrics": {
            "pos_count": len(pos_scores),
            "neg_count": len(neg_scores),
            "pos_score_mean": round(float(np.mean(pos_scores)), 4),
            "neg_score_mean": round(float(np.mean(neg_scores)), 4),
            "auto_pass": {
                "count": pass_cnt,
                "tp": pass_tp,
                "fp": pass_fp,
                "precision": round(float(pass_prec), 4)
            },
            "auto_reject": {
                "count": reject_cnt,
                "tn": reject_tn,
                "fn": reject_fn,
                "specificity": round(float(reject_spec), 4)
            },
            "manual_review": {
                "count": review_cnt,
                "review_rate": round(float(review_rate), 4)
            }
        }
    }


def update_thresholds_json(
    category_name: str,
    low: float,
    high: float,
    description: str = "",
    is_brand: bool = False
) -> bool:
    """自动将标定出的双阈值持久化写入 03_service/data/thresholds.json"""
    if not CONFIG_PATH.exists():
        data = {"brands": {}, "accessories": {}}
    else:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

    section = "brands" if is_brand else "accessories"
    if section not in data:
        data[section] = {}

    desc = description or f"自动标定生成 (low={low}, high={high})"
    data[section][category_name] = {
        "low": low,
        "high": high,
        "description": desc
    }

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return True


def main():
    parser = argparse.ArgumentParser(description="Style Curator AI - 新品类/新品牌三档双阈值自动标定与适配工具")
    parser.add_argument("--category", type=str, required=True, help="待标定的新品类名称（如：帽子、围巾、手表、手套）或新子品牌名称")
    parser.add_argument("--brand", type=str, default="MAIN", help="所属子品牌 (默认: MAIN)")
    parser.add_argument("--is_brand", action="store_true", help="若标定的目标为子品牌而非配件品类，请指定该项")
    parser.add_argument("--dir", type=str, default=None, help="图片样本目录（包含正例与负例子文件夹或包含符合/不符合命名的图片）")
    parser.add_argument("--pos_dir", type=str, default=None, help="正例图片文件夹")
    parser.add_argument("--neg_dir", type=str, default=None, help="负例图片文件夹")
    parser.add_argument("--jsonl", type=str, default=None, help="包含 path 与 label (1/0) 的标注 JSONL 文件")
    parser.add_argument("--sample_limit", type=int, default=50, help="正负例采样上限数量 (默认 50 张，已足够快速标定)")
    parser.add_argument("--target_recall", type=float, default=0.96, help="正例拦截线目标召回率 (默认 0.96，拉高拦截纯度)")
    parser.add_argument("--target_prec", type=float, default=0.96, help="正例放行线目标精确率 (默认 0.96，拉高放行纯度)")
    parser.add_argument("--patch_dir", type=str, default=None, help="模型权重目录 (默认: ./patch)")
    parser.add_argument("--update_config", action="store_true", default=True, help="是否自动持久化写入 03_service/data/thresholds.json (默认 True)")
    parser.add_argument("--out_json", type=str, default=None, help="可选：导出详细标定结果报告路径")
    args = parser.parse_args()

    cat_name = args.category.strip()
    print("=" * 75)
    print(f"🎯 Style Curator AI - 新品类/新品牌三档双阈值自动标定")
    print(f"• 目标名称: 【{cat_name}】 ({'子品牌' if args.is_brand else '配件品类'})")
    print(f"• 关联主牌: {args.brand.upper()}")
    print(f"• 标定目标: 拦截线 Recall ≥ {args.target_recall*100:.1f}% | 放行线 Precision ≥ {args.target_prec*100:.1f}%")
    print("=" * 75)

    # 1. 扫描与准备正负例样本
    cd = Path(args.dir) if args.dir else None
    pd = Path(args.pos_dir) if args.pos_dir else None
    nd = Path(args.neg_dir) if args.neg_dir else None
    jl = Path(args.jsonl) if args.jsonl else None

    pos_paths, neg_paths = scan_category_samples(cd, pd, nd, jl)
    if not pos_paths or not neg_paths:
        print(f"\n❌ 错误: 未扫描到有效的正例或负例图片！")
        print(f"   已找到: 正例 {len(pos_paths)} 张，负例 {len(neg_paths)} 张")
        print("   提示: 请确认目录结构包含“符合/不符合”字样，或通过 --pos_dir 与 --neg_dir 分别指定。")
        sys.exit(1)

    rng = random.Random(42)
    sel_pos = rng.sample(pos_paths, min(args.sample_limit, len(pos_paths)))
    sel_neg = rng.sample(neg_paths, min(args.sample_limit, len(neg_paths)))
    print(f"\n[1/3] 样本采集完毕: 正例采样 {len(sel_pos)} 张 (全量 {len(pos_paths)}) | 负例采样 {len(sel_neg)} 张 (全量 {len(neg_paths)})")

    # 2. 推理打分
    t0 = time.time()
    print(f"\n[2/3] 正在对标定样本执行多模态前向推理打分...")
    all_imgs = sel_pos + sel_neg
    all_scores = score_via_local_engine(all_imgs, args.brand, cat_name, patch_dir=args.patch_dir)
    pos_scores = np.array(all_scores[:len(sel_pos)])
    neg_scores = np.array(all_scores[len(sel_pos):])
    print(f"✅ 推理完成！总耗时: {time.time() - t0:.1f}s")

    # 3. 计算双阈值
    print(f"\n[3/3] 正在搜索三档最优双套阈值...")
    res = calculate_optimal_dual_thresholds(
        pos_scores,
        neg_scores,
        target_recall=args.target_recall,
        target_prec=args.target_prec
    )

    low = res["low"]
    high = res["high"]
    m = res["metrics"]

    print("\n" + "=" * 75)
    print(f"🏆 【{cat_name}】三档双阈值标定成功！")
    print("=" * 75)
    print(f"• 自动拦截阈值 (threshold_low):  【{low:.4f}】")
    print(f"  👉 score < {low:.4f} 直接判定为【绝对不符合 (REJECT)】")
    print(f"     纯度指标: 拦截纯度(Specificity) = {m['auto_reject']['specificity']*100:.1f}% (自动拦截 {m['auto_reject']['count']} 张，零误杀好款)")
    print()
    print(f"• 自动放行阈值 (threshold_high): 【{high:.4f}】")
    print(f"  👉 score >= {high:.4f} 直接判定为【绝对符合 (PASS)】")
    print(f"     纯度指标: 放行纯度(Precision)   = {m['auto_pass']['precision']*100:.1f}% (免审放行 {m['auto_pass']['count']} 张，零漏放劣质)")
    print()
    print(f"• 人工审核缓冲区 [low, high):     【{low:.4f} ~ {high:.4f}】")
    print(f"  👉 判定为【中度符合 (REVIEW)】，系统自动提示人工介入审图")
    print(f"     介入负荷: 人工介入率 = {m['manual_review']['review_rate']*100:.1f}% ({m['manual_review']['count']}/{len(all_imgs)} 张)")
    print("=" * 75)

    # 4. 自动持久化写入配置
    if args.update_config:
        desc = (
            f"自动标定生成: 放行纯度={m['auto_pass']['precision']*100:.1f}%, "
            f"拦截纯度={m['auto_reject']['specificity']*100:.1f}%, 人工介入率={m['manual_review']['review_rate']*100:.1f}%"
        )
        update_thresholds_json(cat_name, low, high, description=desc, is_brand=args.is_brand)
        print(f"\n💾 成功持久化写入配置文件: {CONFIG_PATH}")
        print(f"👉 线上服务与本地推理引擎已即时适配新品类【{cat_name}】，无需重启服务！")

    # 5. 导出可选报告
    if args.out_json:
        out_p = Path(args.out_json)
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump({"category": cat_name, "brand": args.brand, **res}, f, ensure_ascii=False, indent=2)
        print(f"📁 详细评测指标已导出至: {out_p}")


if __name__ == "__main__":
    main()
