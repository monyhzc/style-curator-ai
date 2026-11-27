# -*- coding: utf-8 -*-
"""
check_deps.py - 逐項依賴獨立單元自檢工具
對每個核心依賴單獨執行真實導入與關鍵能力校驗，輸出清晰報告並支援返回缺失套件清單供自動安裝。
"""

import argparse
import importlib
import sys


def _check_torch():
    import torch
    ver = getattr(torch, "__version__", "unknown")
    cuda_ver = getattr(torch.version, "cuda", None)
    return True, f"{ver} (cuda={cuda_ver}, available={torch.cuda.is_available()})"


def _check_torchvision():
    import torchvision
    return True, getattr(torchvision, "__version__", "unknown")


def _check_transformers():
    import transformers
    from transformers import AutoProcessor
    try:
        from transformers import AutoModelForImageTextToText  # noqa: F401
    except ImportError:
        from transformers import AutoModelForVision2Seq  # noqa: F401
    ver = getattr(transformers, "__version__", "0.0.0")
    parts = [int(x) for x in ver.split(".")[:2] if x.isdigit()]
    if len(parts) >= 2 and (parts[0], parts[1]) < (4, 45):
        return False, f"版本過低 ({ver} < 4.45.0)"
    return True, ver


def _check_peft():
    import peft
    from peft import PeftModel  # noqa: F401
    return True, getattr(peft, "__version__", "unknown")


def _check_accelerate():
    import accelerate
    return True, getattr(accelerate, "__version__", "unknown")


def _check_bitsandbytes():
    import bitsandbytes
    return True, getattr(bitsandbytes, "__version__", "unknown")


def _check_modelscope():
    import modelscope
    return True, getattr(modelscope, "__version__", "unknown")


def _check_fastapi():
    import fastapi
    from fastapi import FastAPI  # noqa: F401
    return True, getattr(fastapi, "__version__", "unknown")


def _check_uvicorn():
    import uvicorn
    return True, getattr(uvicorn, "__version__", "unknown")


def _check_multipart():
    # 直接使用 FastAPI 官方檢測函式，確保 Form / UploadFile 100% 可用
    try:
        from fastapi.dependencies.utils import ensure_multipart_is_installed
        ensure_multipart_is_installed()
    except ImportError:
        import python_multipart  # noqa: F401
    mod = None
    for name in ("python_multipart", "multipart"):
        try:
            mod = importlib.import_module(name)
            break
        except ImportError:
            continue
    ver = getattr(mod, "__version__", "installed") if mod else "installed"
    return True, ver


def _check_pydantic():
    import pydantic
    from pydantic import BaseModel  # noqa: F401
    ver = getattr(pydantic, "__version__", "0.0.0")
    major = int(ver.split(".")[0]) if ver.split(".")[0].isdigit() else 0
    if major < 2:
        return False, f"版本過低 ({ver} < 2.0.0)"
    return True, ver


def _check_pillow():
    import PIL
    from PIL import Image  # noqa: F401
    return True, getattr(PIL, "__version__", "unknown")


def _check_requests():
    import requests
    return True, getattr(requests, "__version__", "unknown")


def _check_dotenv():
    from dotenv import load_dotenv  # noqa: F401
    return True, "ok"


# (顯示名稱, pip 安裝規格, 測試函式)
CHECKS = [
    ("torch", "torch>=2.0.0", _check_torch),
    ("torchvision", "torchvision", _check_torchvision),
    ("transformers", "transformers>=4.45.0", _check_transformers),
    ("peft", "peft>=0.10.0", _check_peft),
    ("accelerate", "accelerate", _check_accelerate),
    ("bitsandbytes", "bitsandbytes", _check_bitsandbytes),
    ("modelscope", "modelscope", _check_modelscope),
    ("fastapi", "fastapi>=0.110.0", _check_fastapi),
    ("uvicorn", "uvicorn>=0.28.0", _check_uvicorn),
    ("python-multipart", "python-multipart>=0.0.9", _check_multipart),
    ("pydantic", "pydantic>=2.0.0", _check_pydantic),
    ("pillow", "pillow>=10.0.0", _check_pillow),
    ("requests", "requests>=2.31.0", _check_requests),
    ("python-dotenv", "python-dotenv>=1.0.0", _check_dotenv),
]


def main():
    parser = argparse.ArgumentParser(description="逐項依賴獨立單元自檢")
    parser.add_argument("--list-missing", action="store_true", help="僅輸出缺失/異常的 pip 套件名稱 (空白分隔)")
    args = parser.parse_args()

    failed_specs = []
    if not args.list_missing:
        print("==================================================")
        print("🔍 正在逐項進行依賴庫獨立單元自檢...")
        print("==================================================")

    for name, pip_spec, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"

        if not ok:
            failed_specs.append(pip_spec)
        if not args.list_missing:
            mark = "✅ [PASS]" if ok else "❌ [FAIL]"
            print(f"  {mark} {name:<18} | {detail}")

    if args.list_missing:
        print(" ".join(failed_specs))
    else:
        print("==================================================")
        if failed_specs:
            print(f"⚠️ 共發現 {len(failed_specs)} 項異常/缺失依賴: {' '.join(failed_specs)}")
        else:
            print("🎉 全部 14 項核心依賴單元測試通過！")

    sys.exit(1 if failed_specs else 0)


if __name__ == "__main__":
    main()
