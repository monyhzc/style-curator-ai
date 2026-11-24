# -*- coding: utf-8 -*-
"""
review_routes.py - 选款与审图工作台前端业务接口
完全对接 index.html 与前端对接说明规范 (GET /api/results, POST /api/upload, POST /action/{id}, 等)
"""

import os
import time
import uuid
import sqlite3
from pathlib import Path
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Form, File, UploadFile, HTTPException, Request, Depends, status
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from PIL import Image

# 关联核心模型与决策模块
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(__file__).resolve().parent / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
THUMBNAILS_DIR = DATA_DIR / "thumbnails"
DB_PATH = DATA_DIR / "reviews.db"

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL,
        safe_name TEXT NOT NULL,
        thumb_name TEXT NOT NULL,
        folder TEXT NOT NULL DEFAULT 'uploads',
        status TEXT NOT NULL DEFAULT 'done',
        task TEXT NOT NULL,
        probability REAL,
        level TEXT,
        is_marked_error INTEGER NOT NULL DEFAULT 0,
        pre_delete_status TEXT,
        error_msg TEXT,
        created_at REAL NOT NULL
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS action_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action_type TEXT NOT NULL,
        item_id INTEGER NOT NULL,
        old_status TEXT NOT NULL,
        new_status TEXT NOT NULL,
        created_at REAL NOT NULL
    );
    """)
    conn.commit()
    conn.close()


init_db()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


router = APIRouter()


def map_level(level_raw: str) -> str:
    if not level_raw:
        return "中度符合"
    if "绝对符合" in level_raw or "非常符合" in level_raw:
        return "非常符合"
    if "绝对不符合" in level_raw or level_raw == "不符合":
        return "不符合"
    return "中度符合"


# ===================== 请求/响应模型 =====================
class BatchActionReq(BaseModel):
    ids: List[int]
    action: str


class MarkErrorReq(BaseModel):
    id: int


# ===================== 业务 API 路由 =====================

@router.get("/api/results", summary="查询审核结果列表")
def get_results(
    tab: str = "pending",
    filter: str = "all",
    sort: str = "id",
    order: str = "desc",
    brands: Optional[str] = None,
    page: int = 0,
    limit: int = 25
):
    conn = get_db()
    cur = conn.cursor()

    conditions = []
    params = []

    # 1. Tab 状态筛选
    if tab == "pending":
        conditions.append("status IN ('pending', 'done')")
    elif tab == "processed":
        conditions.append("status IN ('approved', 'rejected')")
    elif tab == "trash":
        conditions.append("status = 'deleted'")

    # 2. 品牌筛选
    if brands:
        brand_list = [b.strip() for b in brands.split(",") if b.strip()]
        if brand_list:
            placeholders = ",".join(["?"] * len(brand_list))
            conditions.append(f"task IN ({placeholders})")
            params.extend(brand_list)

    # 3. 契合度等级筛选 (filter: all / high / mid / low)
    if filter == "high":
        conditions.append("level = '非常符合'")
    elif filter == "mid":
        conditions.append("level = '中度符合'")
    elif filter == "low":
        conditions.append("level = '不符合'")
    elif tab == "trash" and filter == "processed":
        conditions.append("pre_delete_status IN ('approved', 'rejected')")
    elif tab == "trash" and filter == "unprocessed":
        conditions.append("pre_delete_status NOT IN ('approved', 'rejected')")

    where_sql = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # 统计总数
    cur.execute(f"SELECT COUNT(*) FROM reviews {where_sql}", params)
    total = cur.fetchone()[0]

    # 排序与分页
    sort_col = "probability" if sort in ("prob", "probability", "confidence") else "id"
    sort_dir = "ASC" if order.lower() == "asc" else "DESC"
    offset = max(0, page) * max(1, limit)

    query_sql = f"""
    SELECT * FROM reviews
    {where_sql}
    ORDER BY {sort_col} {sort_dir}
    LIMIT ? OFFSET ?
    """
    cur.execute(query_sql, params + [limit, offset])
    rows = cur.fetchall()

    results = []
    for r in rows:
        ai_res = None
        if r["level"] or r["probability"] is not None:
            ai_res = {
                "level": r["level"],
                "probability": r["probability"] if r["probability"] is not None else 0.0
            }
        results.append({
            "id": r["id"],
            "filename": r["filename"],
            "safe_name": r["safe_name"],
            "thumb_name": r["thumb_name"],
            "folder": r["folder"],
            "status": r["status"],
            "task": r["task"],
            "ai_result": ai_res,
            "is_marked_error": bool(r["is_marked_error"]),
            "pre_delete_status": r["pre_delete_status"],
            "error_msg": r["error_msg"]
        })

    conn.close()
    return {"results": results, "total": total}


@router.post("/api/upload", summary="上传图片并自动审图打分")
async def upload_files(
    files: List[UploadFile] = File(...),
    task: str = Form("LIFE")
):
    from core import StyleEngine, get_decision_level

    task = task.strip().upper() if task else "LIFE"
    engine = StyleEngine.get_instance()
    conn = get_db()
    cur = conn.cursor()

    saved_items = []
    for f in files:
        raw_name = f.filename or "image.jpg"
        ext = Path(raw_name).suffix.lower() or ".jpg"
        unique_prefix = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
        safe_name = f"{unique_prefix}{ext}"
        thumb_name = f"thumb_{unique_prefix}.jpg"

        file_path = UPLOADS_DIR / safe_name
        thumb_path = THUMBNAILS_DIR / thumb_name

        content = await f.read()
        with open(file_path, "wb") as out_f:
            out_f.write(content)

        # 生成缩略图与获取 PIL 图像用于推理
        try:
            with Image.open(file_path) as img:
                rgb_img = img.convert("RGB")
                # 缩略图
                thumb_copy = rgb_img.copy()
                thumb_copy.thumbnail((360, 360))
                thumb_copy.save(thumb_path, "JPEG", quality=85)

                # 推理
                prob = engine.predict_one(rgb_img, task)
                dec = get_decision_level(prob, task)
                level = map_level(dec.get("level", "中度符合"))
                status_val = "done"
                err_msg = None
        except Exception as e:
            prob = None
            level = None
            status_val = "error"
            err_msg = str(e)

        cur.execute("""
        INSERT INTO reviews (filename, safe_name, thumb_name, folder, status, task, probability, level, created_at, error_msg)
        VALUES (?, ?, ?, 'uploads', ?, ?, ?, ?, ?, ?)
        """, (raw_name, safe_name, thumb_name, status_val, task, prob, level, time.time(), err_msg))

    conn.commit()
    conn.close()
    return {"status": "ok"}


@router.post("/action/{item_id}", summary="单项审核操作")
async def perform_action(item_id: int, request: Request):
    form_data = await request.form()
    action = form_data.get("action", "")
    if not action:
        try:
            body = await request.json()
            action = body.get("action", "")
        except Exception:
            pass

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM reviews WHERE id = ?", (item_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Item not found")

    old_status = row["status"]
    pre_del = row["pre_delete_status"]

    new_status = old_status
    new_pre_del = pre_del

    if action == "approve":
        new_status = "approved"
    elif action == "reject":
        new_status = "rejected"
    elif action == "delete":
        new_pre_del = old_status
        new_status = "deleted"
    elif action == "restore":
        new_status = pre_del if pre_del in ("approved", "rejected") else "done"
    elif action in ("withdraw", "undo"):
        new_status = "done"
    elif action == "permanent_delete":
        cur.execute("DELETE FROM reviews WHERE id = ?", (item_id,))
        # 清理文件
        try:
            (UPLOADS_DIR / row["safe_name"]).unlink(missing_ok=True)
            (THUMBNAILS_DIR / row["thumb_name"]).unlink(missing_ok=True)
        except Exception:
            pass
        conn.commit()
        conn.close()
        return {"status": "ok"}
    else:
        conn.close()
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    cur.execute("""
    UPDATE reviews SET status = ?, pre_delete_status = ? WHERE id = ?
    """, (new_status, new_pre_del, item_id))

    cur.execute("""
    INSERT INTO action_history (action_type, item_id, old_status, new_status, created_at)
    VALUES (?, ?, ?, ?, ?)
    """, (action, item_id, old_status, new_status, time.time()))

    conn.commit()
    conn.close()
    return {"status": "ok"}


@router.post("/api/batch_action", summary="批量审核操作")
def batch_action(req: BatchActionReq):
    conn = get_db()
    cur = conn.cursor()

    action = req.action
    for item_id in req.ids:
        cur.execute("SELECT * FROM reviews WHERE id = ?", (item_id,))
        row = cur.fetchone()
        if not row:
            continue
        old_status = row["status"]
        pre_del = row["pre_delete_status"]
        new_status = old_status
        new_pre_del = pre_del

        if action == "approve":
            new_status = "approved"
        elif action == "reject":
            new_status = "rejected"
        elif action == "delete":
            new_pre_del = old_status
            new_status = "deleted"
        elif action == "restore":
            new_status = pre_del if pre_del in ("approved", "rejected") else "done"
        elif action in ("withdraw", "undo"):
            new_status = "done"
        elif action == "permanent_delete":
            cur.execute("DELETE FROM reviews WHERE id = ?", (item_id,))
            continue

        cur.execute("""
        UPDATE reviews SET status = ?, pre_delete_status = ? WHERE id = ?
        """, (new_status, new_pre_del, item_id))

        cur.execute("""
        INSERT INTO action_history (action_type, item_id, old_status, new_status, created_at)
        VALUES (?, ?, ?, ?, ?)
        """, (action, item_id, old_status, new_status, time.time()))

    conn.commit()
    conn.close()
    return {"status": "ok"}


@router.post("/api/update_task", summary="修改款式所属品牌并重算契合度")
async def update_task(id: int = Form(...), new_task: str = Form(...)):
    from core import StyleEngine, get_decision_level

    new_task = new_task.strip().upper()
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM reviews WHERE id = ?", (id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Item not found")

    img_path = UPLOADS_DIR / row["safe_name"]
    try:
        engine = StyleEngine.get_instance()
        with Image.open(img_path) as img:
            rgb_img = img.convert("RGB")
            prob = engine.predict_one(rgb_img, new_task)
            dec = get_decision_level(prob, new_task)
            level = map_level(dec.get("level", "中度符合"))
    except Exception as e:
        prob = row["probability"]
        level = row["level"]

    cur.execute("""
    UPDATE reviews SET task = ?, probability = ?, level = ? WHERE id = ?
    """, (new_task, prob, level, id))

    conn.commit()
    conn.close()
    return {"status": "ok"}


@router.post("/api/mark_error", summary="标记模型误判")
def mark_error(req: MarkErrorReq):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT is_marked_error FROM reviews WHERE id = ?", (req.id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Item not found")

    new_val = 0 if row["is_marked_error"] else 1
    cur.execute("UPDATE reviews SET is_marked_error = ? WHERE id = ?", (new_val, req.id))
    conn.commit()
    conn.close()
    return {"status": "ok"}


@router.post("/undo_global", summary="全局撤回最近一次审核操作")
def undo_global():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM action_history ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    if not row:
        conn.close()
        return {"status": "empty"}

    item_id = row["item_id"]
    old_status = row["old_status"]

    cur.execute("UPDATE reviews SET status = ? WHERE id = ?", (old_status, item_id))
    cur.execute("DELETE FROM action_history WHERE id = ?", (row["id"],))

    conn.commit()
    conn.close()
    return {"status": "ok"}


@router.get("/image/thumbnails/{thumb_name}", summary="访问缩略图")
def get_thumbnail(thumb_name: str):
    file_path = THUMBNAILS_DIR / thumb_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(file_path, media_type="image/jpeg")


@router.get("/image/{folder}/{safe_name}", summary="访问原图")
def get_original_image(folder: str, safe_name: str):
    file_path = DATA_DIR / folder / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(file_path)
