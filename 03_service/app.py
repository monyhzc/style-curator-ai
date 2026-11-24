# -*- coding: utf-8 -*-
"""
app.py - 阶段三：选款 AI 生产级 HTTP API 服务
接口完全符合真维斯审图系统与外部调用规范 (POST /api/analyze, POST /api/analyze/batch)
内置：Bearer Token 鉴权、滑动窗口限流、SSRF 防护与图片安全校验
"""

import os
import sys
import time
import uuid
import socket
import ipaddress
import asyncio
import urllib.parse
from io import BytesIO
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PIL import Image
import requests

from fastapi import FastAPI, Header, HTTPException, Request, Depends, status
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# 自动关联 02_model 核心模型
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "02_model"))
sys.path.insert(0, str(ROOT_DIR / "04_client_tests"))
from core import StyleEngine, get_decision_level, DUAL_THRESHOLDS, ACCESSORY_CATEGORIES, reload_thresholds

# 优先加载根目录或当前目录的 .env
if (ROOT_DIR / ".env").exists():
    load_dotenv(dotenv_path=ROOT_DIR / ".env")
else:
    load_dotenv()

APP_AUTH_TOKEN = os.environ.get("APP_AUTH_TOKEN", "your_auth_token_here")
PORT = int(os.environ.get("PORT", "11451"))
HOST = os.environ.get("HOST", "0.0.0.0")
ALLOWLIST_PATH = os.environ.get("ALLOWLIST_PATH", str(Path(__file__).parent / "data/url_allowlist.conf"))

app = FastAPI(title="Style Curator AI API", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

from frontend_gate import FrontendGate
app.add_middleware(FrontendGate)

from review_routes import router as review_router
app.include_router(review_router)

executor = ThreadPoolExecutor(max_workers=4)
BATCH_TASKS: Dict[str, Dict[str, Any]] = {}
RATE_LIMIT_RECORDS: Dict[str, List[float]] = {}
SUPPORTED_BRANDS = ['LIFE', 'OUTDOOR', 'Z+', 'MAIN', 'JEANS', 'JNR', 'JKIDS', 'JSPORT']


# ===================== 动态组批请求缓冲池 (Dynamic Batching Pool) =====================
MAX_BATCH_SIZE = int(os.environ.get("MAX_BATCH_SIZE", "16"))
BATCH_WAIT_MS = int(os.environ.get("BATCH_WAIT_MS", "50")) / 1000.0  # 默认 50ms 凑批窗口
MAX_POOL_SIZE = int(os.environ.get("MAX_POOL_SIZE", "2000"))
POOL_TIMEOUT_SEC = float(os.environ.get("POOL_TIMEOUT_SEC", "60.0"))

@dataclass
class PoolItem:
    image: Image.Image
    brand: str
    category: Optional[str]
    future: asyncio.Future
    enqueued_at: float

REQUEST_POOL: Optional[asyncio.Queue] = None
BATCH_WORKER_TASK: Optional[asyncio.Task] = None
BATCH_STATS = {
    "total_requests": 0,
    "total_batches": 0,
    "max_pool_depth_seen": 0
}


async def dynamic_batch_worker():
    """后台持续运转的动态组批处理协程: 从 Pool 中收集请求凑成批次并提交 GPU 计算"""
    engine = StyleEngine.get_instance()
    print(f"[DynamicBatcher] 组批协程启动就绪，凑批窗口: {int(BATCH_WAIT_MS*1000)}ms，最大批次: {MAX_BATCH_SIZE}")

    while True:
        try:
            # 1. 阻塞等待至少一个请求到达 Pool
            first_item: PoolItem = await REQUEST_POOL.get()
            items: List[PoolItem] = [first_item]

            # 2. 在极小的时间窗口内 (BATCH_WAIT_MS) 尝试捞取更多排队请求，凑足 MAX_BATCH_SIZE
            start_wait = time.time()
            while len(items) < MAX_BATCH_SIZE:
                remaining_wait = BATCH_WAIT_MS - (time.time() - start_wait)
                if remaining_wait <= 0:
                    break
                try:
                    next_item = await asyncio.wait_for(REQUEST_POOL.get(), timeout=remaining_wait)
                    items.append(next_item)
                except asyncio.TimeoutError:
                    break

            # 3. 更新统计
            BATCH_STATS["total_batches"] += 1
            BATCH_STATS["total_requests"] += len(items)
            cur_depth = REQUEST_POOL.qsize()
            if cur_depth > BATCH_STATS["max_pool_depth_seen"]:
                BATCH_STATS["max_pool_depth_seen"] = cur_depth

            # 4. 组装批推理输入: [(img, brand, category), ...]
            batch_inputs = [(it.image, it.brand, it.category) for it in items]

            # 5. 在工作线程中安全执行 GPU 前向推理 (避免阻塞 asyncio 调度)
            try:
                scores = await asyncio.to_thread(engine.predict, batch_inputs)
                # 6. 为批次内的每个 Future 派发结果
                for it, score in zip(items, scores):
                    if not it.future.done():
                        it.future.set_result(score)
            except Exception as exc:
                for it in items:
                    if not it.future.done():
                        it.future.set_exception(exc)

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[DynamicBatcher] 组批处理异常: {e}")
            await asyncio.sleep(0.01)


# ===================== 安全与工具函数 =====================
def is_url_safe(url: str) -> bool:
    """校验 URL 并防御 SSRF"""
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme.lower() not in ("http", "https"):
            return False
        host = parsed.hostname
        if not host:
            return False

        # 白名单热检测
        if os.path.exists(ALLOWLIST_PATH):
            with open(ALLOWLIST_PATH, "r", encoding="utf-8") as f:
                allowed = [line.strip().lower() for line in f if line.strip() and not line.startswith("#")]
                if host.lower() in allowed:
                    return True

        # 解析 IP 防护私网与回环
        addr_info = socket.getaddrinfo(host, None)
        for item in addr_info:
            ip = ipaddress.ip_address(item[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return False
        return True
    except Exception:
        return False


def download_image(url: str, max_size: int = 10 * 1024 * 1024) -> Image.Image:
    """流式下载图片并校验体积与格式"""
    if not is_url_safe(url):
        raise ValueError("URL 安全检测未通过或命中了受限内网 IP")

    session = requests.Session()
    session.trust_env = False  # 隔离外部 socks/http 代理
    resp = session.get(url, stream=True, timeout=(3.0, 5.0), headers={"User-Agent": "StyleCuratorAI/2.0"})
    if resp.status_code != 200:
        raise IOError(f"下载失败 (HTTP {resp.status_code})")

    buf = bytearray()
    for chunk in resp.iter_content(chunk_size=65536):
        buf.extend(chunk)
        if len(buf) > max_size:
            raise ValueError("图片超出 10MB 大小限制")

    return Image.open(BytesIO(buf)).convert("RGB")


def check_auth(authorization: Optional[str] = Header(None)) -> str:
    """Bearer Token 认证"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"error": "Unauthorized"})
    token = authorization.split(" ", 1)[1]
    if token != APP_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail={"error": "Unauthorized"})
    return token


def check_rate(request: Request, max_reqs: int, window: int = 60):
    """滑动窗口限流"""
    ip = request.client.host if request.client else "127.0.0.1"
    now = time.time()
    records = [t for t in RATE_LIMIT_RECORDS.get(ip, []) if now - t < window]
    if len(records) >= max_reqs:
        raise HTTPException(status_code=429, detail={"error": "Rate limit exceeded"})
    records.append(now)
    RATE_LIMIT_RECORDS[ip] = records


# ===================== API 路由 =====================
class SingleReq(BaseModel):
    image_url: str = Field(..., description="图片公网/白名单 URL")
    task: Optional[str] = Field("LIFE", description="目标品牌 (LIFE, OUTDOOR, Z+, MAIN, JEANS, JNR, JKIDS, JSPORT)")
    category: Optional[str] = Field(None, description="配件品类 (鞋子, 袜子, 内裤, 箱包, 腰带, 家居服, 内衣)；为空则默认按成衣处理")


class BatchReq(BaseModel):
    urls: List[str] = Field(..., description="批量图片 URL", max_length=1000)
    task: Optional[str] = Field("LIFE", description="目标品牌")
    category: Optional[str] = Field(None, description="批量配件品类")


class CalibrateReq(BaseModel):
    category: str = Field(..., description="待标定的新品类或新子品牌名称")
    brand: Optional[str] = Field("MAIN", description="关联的主牌名称")
    is_brand: Optional[bool] = Field(False, description="是否为子品牌标定（否则默认为配件品类）")
    pos_urls: List[str] = Field(..., description="正例样本图片 URL 列表 (建议 10~50 张)")
    neg_urls: List[str] = Field(..., description="负例样本图片 URL 列表 (建议 10~50 张)")
    target_recall: Optional[float] = Field(0.96, description="拦截线目标召回率 (默认 0.96)")
    target_prec: Optional[float] = Field(0.96, description="放行线目标精确率 (默认 0.96)")
    auto_save: Optional[bool] = Field(True, description="是否自动写入 03_service/data/thresholds.json 并热生效")


@app.on_event("startup")
async def startup():
    global REQUEST_POOL, BATCH_WORKER_TASK
    StyleEngine.get_instance()
    REQUEST_POOL = asyncio.Queue(maxsize=MAX_POOL_SIZE)
    BATCH_WORKER_TASK = asyncio.create_task(dynamic_batch_worker())
    print(f"[Pool] 动态组批请求缓冲池启动就绪 (容量: {MAX_POOL_SIZE}, 最大批次: {MAX_BATCH_SIZE}, 凑批窗口: {int(BATCH_WAIT_MS*1000)}ms)")


@app.on_event("shutdown")
async def shutdown():
    global BATCH_WORKER_TASK
    if BATCH_WORKER_TASK:
        BATCH_WORKER_TASK.cancel()


@app.get("/")
def index():
    doc = Path(__file__).parent / "data/api_doc.html"
    if doc.exists():
        return FileResponse(doc)
    return {"message": "Style Curator AI API is running with Dynamic Batching Pool & 3-tier decision system"}


@app.get("/api/pool/status", summary="查询请求缓冲池队列深度与组批统计")
def get_pool_status(_: str = Depends(check_auth)):
    """返回当前请求缓冲池排队深度与组批吞吐性能指标"""
    qsize = REQUEST_POOL.qsize() if REQUEST_POOL else 0
    tot_reqs = BATCH_STATS["total_requests"]
    tot_batches = BATCH_STATS["total_batches"]
    avg_batch = round(tot_reqs / max(1, tot_batches), 2)
    return {
        "status": "online",
        "pool_depth": qsize,
        "max_pool_size": MAX_POOL_SIZE,
        "max_batch_size": MAX_BATCH_SIZE,
        "batch_wait_ms": int(BATCH_WAIT_MS * 1000),
        "total_requests_processed": tot_reqs,
        "total_batches_processed": tot_batches,
        "avg_batch_size": avg_batch,
        "max_pool_depth_seen": BATCH_STATS["max_pool_depth_seen"]
    }


@app.get("/api/thresholds", summary="获取 8 大品牌与 7 大配件三档双套阈值表")
def get_thresholds(_: str = Depends(check_auth)):
    """返回当前各子品牌与配件的 [low, high] 阈值及三档判定规则"""
    reload_thresholds()
    from core import DUAL_THRESHOLDS as CURRENT_THRS
    return {
        "status": "success",
        "thresholds": CURRENT_THRS,
        "rules": {
            "score >= high": "绝对符合 (pass, level_code=2, 自动免审放行)",
            "score < low": "绝对不符合 (reject, level_code=0, 自动拦截驳回)",
            "low <= score < high": "中度符合 (review, level_code=1, 提示人工介入复核)"
        }
    }


@app.post("/api/thresholds/calibrate", summary="在线自动标定新品类三档双阈值 (免重启即时生效)")
def api_calibrate(req: CalibrateReq, request: Request, _: str = Depends(check_auth)):
    """
    在线标定新品类三档双套阈值：
    业务方传入新品类的正例与负例图片 URL 列表，接口自动执行前向打分与极端分位搜索，
    产出 [low, high] 阈值并可自动写入 03_service/data/thresholds.json 实现热生效。
    """
    check_rate(request, max_reqs=10)
    cat_name = req.category.strip()
    b_name = (req.brand or "MAIN").upper()

    import numpy as np
    from calibrate_thresholds import calculate_optimal_dual_thresholds, update_thresholds_json

    pos_imgs, neg_imgs = [], []
    for u in req.pos_urls:
        try:
            pos_imgs.append(download_image(u))
        except Exception:
            pass

    for u in req.neg_urls:
        try:
            neg_imgs.append(download_image(u))
        except Exception:
            pass

    if not pos_imgs or not neg_imgs:
        raise HTTPException(status_code=400, detail={
            "error": f"有效图片不足: 成功下载正例 {len(pos_imgs)} 张，负例 {len(neg_imgs)} 张，请检查图片 URL 可访问性"
        })

    engine = StyleEngine.get_instance()
    pos_items = [(im, b_name, cat_name) for im in pos_imgs]
    neg_items = [(im, b_name, cat_name) for im in neg_imgs]

    pos_scores = np.array(engine.predict(pos_items))
    neg_scores = np.array(engine.predict(neg_items))

    res = calculate_optimal_dual_thresholds(
        pos_scores,
        neg_scores,
        target_recall=req.target_recall,
        target_prec=req.target_prec
    )

    if req.auto_save and res.get("valid"):
        m = res.get("metrics", {})
        desc = (
            f"在线自动标定: 放行纯度={m['auto_pass']['precision']*100:.1f}%, "
            f"拦截纯度={m['auto_reject']['specificity']*100:.1f}%, 人工介入率={m['manual_review']['review_rate']*100:.1f}%"
        )
        update_thresholds_json(cat_name, res["low"], res["high"], description=desc, is_brand=req.is_brand)
        reload_thresholds()

    return {
        "status": "success",
        "category": cat_name,
        "brand": b_name,
        "is_brand": req.is_brand,
        "low": res["low"],
        "high": res["high"],
        "metrics": res.get("metrics"),
        "auto_saved": req.auto_save
    }


@app.post("/api/analyze", summary="单图风格分析 (池化动态组批三档判定: 绝对符合/中度符合/绝对不符合)")
async def analyze(req: SingleReq, request: Request, _: str = Depends(check_auth)):
    brand = req.task.upper() if req.task else "LIFE"
    if brand not in SUPPORTED_BRANDS:
        raise HTTPException(status_code=400, detail={"error": f"不支持的品牌: {brand}"})

    cat = req.category.strip() if req.category else None

    # 1. 检查缓冲池容量上限 (达到 MAX_POOL_SIZE 时才返回 503，避免硬限流 429 频繁阻断)
    if REQUEST_POOL is None or REQUEST_POOL.qsize() >= MAX_POOL_SIZE:
        raise HTTPException(status_code=503, detail={
            "error": "请求缓冲池已达容量上限，系统正在高速并发组批消化中，请稍后重试",
            "pool_depth": REQUEST_POOL.qsize() if REQUEST_POOL else 0,
            "max_pool_size": MAX_POOL_SIZE
        })

    # 2. 异步下载图片 (在工作线程池执行，不阻塞主事件循环)
    try:
        img = await asyncio.to_thread(download_image, req.image_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail={"error": f"图片获取失败: {str(e)}"})

    # 3. 压入请求缓冲池并创建等待 Future
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    item = PoolItem(
        image=img,
        brand=brand,
        category=cat,
        future=fut,
        enqueued_at=time.time()
    )

    await REQUEST_POOL.put(item)

    # 4. 等待动态批处理器执行完毕并唤醒
    try:
        score = await asyncio.wait_for(fut, timeout=POOL_TIMEOUT_SEC)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail={
            "error": "排队处理超时，请稍后重试",
            "timeout_sec": POOL_TIMEOUT_SEC
        })

    # 5. 三档判定
    decision_info = get_decision_level(score, brand, cat)

    return {
        "url": req.image_url,
        "brand": brand,
        "category": cat or "服装",
        "probability": score,
        "decision": decision_info["decision"],
        "level": decision_info["level"],
        "level_code": decision_info["level_code"],
        "manual_review_needed": decision_info["manual_review_needed"],
        "thresholds_used": decision_info["thresholds_used"]
    }


@app.post("/api/analyze/batch", summary="提交批量分析任务 (分片动态组批三档判定)")
def analyze_batch(req: BatchReq, request: Request, _: str = Depends(check_auth)):
    brand = req.task.upper() if req.task else "LIFE"
    if brand not in SUPPORTED_BRANDS:
        raise HTTPException(status_code=400, detail={"error": f"不支持的品牌: {brand}"})

    cat = req.category.strip() if req.category else None
    batch_id = f"batch_{uuid.uuid4().hex[:12]}"
    BATCH_TASKS[batch_id] = {
        "batch_id": batch_id,
        "total": len(req.urls),
        "status": "processing",
        "brand": brand,
        "category": cat or "服装",
        "results": []
    }

    def _worker(bid: str, urls: List[str], b_name: str, c_name: Optional[str]):
        engine = StyleEngine.get_instance()
        imgs, results = [], []
        for u in urls:
            try:
                im = download_image(u)
                imgs.append((u, im, None))
            except Exception as e:
                imgs.append((u, None, str(e)))

        valid = [(im, b_name, c_name) for _, im, err in imgs if im is not None]

        # 分片按 MAX_BATCH_SIZE (16) 组批推理，防止超大列表导致 OOM
        scores = []
        chunk_size = MAX_BATCH_SIZE
        for i in range(0, len(valid), chunk_size):
            chunk = valid[i:i + chunk_size]
            chunk_scores = engine.predict(chunk)
            scores.extend(chunk_scores)

        idx = 0
        for u, im, err in imgs:
            if im is not None:
                sc = scores[idx]
                d_info = get_decision_level(sc, b_name, c_name)
                results.append({
                    "url": u,
                    "probability": sc,
                    "decision": d_info["decision"],
                    "level": d_info["level"],
                    "level_code": d_info["level_code"],
                    "manual_review_needed": d_info["manual_review_needed"],
                    "thresholds_used": d_info["thresholds_used"],
                    "error": None
                })
                idx += 1
            else:
                results.append({
                    "url": u,
                    "probability": None,
                    "decision": None,
                    "level": None,
                    "level_code": None,
                    "manual_review_needed": None,
                    "thresholds_used": None,
                    "error": err
                })

        BATCH_TASKS[bid].update({
            "status": "completed",
            "completed": len(results),
            "results": results
        })

    executor.submit(_worker, batch_id, req.urls, brand, cat)
    return {
        "batch_id": batch_id,
        "total": len(req.urls),
        "brand": brand,
        "category": cat or "服装",
        "status": "processing"
    }


@app.get("/api/analyze/batch/{batch_id}", summary="查询批量任务状态与结果")
def get_batch(batch_id: str, request: Request, _: str = Depends(check_auth)):
    check_rate(request, max_reqs=60)
    if batch_id not in BATCH_TASKS:
        raise HTTPException(status_code=404, detail={"error": "Batch task not found"})
    return BATCH_TASKS[batch_id]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host=HOST, port=PORT)
