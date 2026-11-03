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
import urllib.parse
from io import BytesIO
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
from core import StyleEngine

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

executor = ThreadPoolExecutor(max_workers=4)
BATCH_TASKS: Dict[str, Dict[str, Any]] = {}
RATE_LIMIT_RECORDS: Dict[str, List[float]] = {}
SUPPORTED_BRANDS = ['LIFE', 'OUTDOOR', 'Z+', 'MAIN', 'JEANS', 'JNR', 'JKIDS', 'JSPORT']


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
    task: Optional[str] = Field("LIFE", description="目标品牌")


class BatchReq(BaseModel):
    urls: List[str] = Field(..., description="批量图片 URL", max_length=1000)
    task: Optional[str] = Field("LIFE", description="目标品牌")


@app.on_event("startup")
def startup():
    StyleEngine.get_instance()


@app.get("/")
def index():
    doc = Path(__file__).parent / "data/api_doc.html"
    if doc.exists():
        return FileResponse(doc)
    return {"message": "Style Curator AI API is running"}


@app.post("/api/analyze", summary="单图风格分析 (同步)")
def analyze(req: SingleReq, request: Request, _: str = Depends(check_auth)):
    check_rate(request, max_reqs=120)
    brand = req.task.upper() if req.task else "LIFE"
    if brand not in SUPPORTED_BRANDS:
        raise HTTPException(status_code=400, detail={"error": f"不支持的品牌: {brand}"})

    try:
        img = download_image(req.image_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail={"error": f"图片获取失败: {str(e)}"})

    score = StyleEngine.get_instance().predict_one(img, brand)
    return {"url": req.image_url, "probability": score}


@app.post("/api/analyze/batch", summary="提交批量分析任务 (异步)")
def analyze_batch(req: BatchReq, request: Request, _: str = Depends(check_auth)):
    check_rate(request, max_reqs=30)
    brand = req.task.upper() if req.task else "LIFE"
    if brand not in SUPPORTED_BRANDS:
        raise HTTPException(status_code=400, detail={"error": f"不支持的品牌: {brand}"})

    batch_id = f"batch_{uuid.uuid4().hex[:12]}"
    BATCH_TASKS[batch_id] = {"batch_id": batch_id, "total": len(req.urls), "status": "processing", "results": []}

    def _worker(bid: str, urls: List[str], b_name: str):
        engine = StyleEngine.get_instance()
        imgs, results = [], []
        for u in urls:
            try:
                im = download_image(u)
                imgs.append((u, im, None))
            except Exception as e:
                imgs.append((u, None, str(e)))

        valid = [(im, b_name) for _, im, err in imgs if im is not None]
        scores = engine.predict(valid) if valid else []
        idx = 0
        for u, im, err in imgs:
            if im is not None:
                results.append({"url": u, "probability": scores[idx], "error": None})
                idx += 1
            else:
                results.append({"url": u, "probability": None, "error": err})

        BATCH_TASKS[bid].update({"status": "completed", "completed": len(results), "results": results})

    executor.submit(_worker, batch_id, req.urls, brand)
    return {"batch_id": batch_id, "total": len(req.urls), "status": "processing"}


@app.get("/api/analyze/batch/{batch_id}", summary="查询批量任务状态与结果")
def get_batch(batch_id: str, request: Request, _: str = Depends(check_auth)):
    check_rate(request, max_reqs=60)
    if batch_id not in BATCH_TASKS:
        raise HTTPException(status_code=404, detail={"error": "Batch task not found"})
    return BATCH_TASKS[batch_id]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host=HOST, port=PORT)
