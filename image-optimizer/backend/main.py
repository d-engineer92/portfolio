"""FastAPI backend for Image Optimizer."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from optimizer import MAX_FILE_SIZE, optimize_image, get_output_filename

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

ALLOWED_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/bmp",
    "image/tiff",
}

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Image Optimizer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/api/optimize")
async def optimize(
    files: list[UploadFile] = File(...),
    strip_metadata: bool = Form(True),
    convert_webp: bool = Form(False),
    quality: int = Form(80),
):
    """Optimize one or more uploaded images.

    Single image  → returns the optimized image directly.
    Multiple images → returns a ZIP archive.
    """
    if not files:
        raise HTTPException(status_code=400, detail="ファイルが選択されていません。")

    if len(files) > 20:
        raise HTTPException(status_code=400, detail="一度に最大20ファイルまでです。")

    results: list[dict] = []
    optimized_files: list[tuple[str, bytes, str]] = []  # (filename, data, media_type)

    for upload in files:
        # Validate content type
        ct = upload.content_type or ""
        if ct not in ALLOWED_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"非対応の形式です: {upload.filename} ({ct})",
            )

        data = await upload.read()
        if len(data) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"ファイルが大きすぎます: {upload.filename} (最大50MB)",
            )

        try:
            result = optimize_image(
                data,
                upload.filename or "image.jpg",
                strip_metadata=strip_metadata,
                convert_webp=convert_webp,
                quality=max(1, min(100, quality)),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"最適化エラー ({upload.filename}): {exc}",
            )

        out_filename = get_output_filename(
            upload.filename or "image", result.output_format
        )

        media_map = {
            "JPEG": "image/jpeg",
            "PNG": "image/png",
            "WEBP": "image/webp",
            "GIF": "image/gif",
            "BMP": "image/bmp",
            "TIFF": "image/tiff",
        }
        media_type = media_map.get(result.output_format, "application/octet-stream")

        optimized_files.append((out_filename, result.data, media_type))
        results.append(
            {
                "filename": upload.filename,
                "output_filename": out_filename,
                **result.to_dict(),
            }
        )

    # Single file → return image directly with stats in headers
    if len(optimized_files) == 1:
        fname, fdata, fmedia = optimized_files[0]
        stats = results[0]
        # RFC 5987 encoding for non-ASCII filenames
        encoded_fname = quote(fname)
        return Response(
            content=fdata,
            media_type=fmedia,
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_fname}",
                "X-Original-Size": str(stats["original_size"]),
                "X-Optimized-Size": str(stats["optimized_size"]),
                "X-Savings-Pct": str(stats["savings_pct"]),
                "X-Output-Format": stats["output_format"],
                "X-Width": str(stats["width"]),
                "X-Height": str(stats["height"]),
                "Access-Control-Expose-Headers": "X-Original-Size, X-Optimized-Size, X-Savings-Pct, X-Output-Format, X-Width, X-Height",
            },
        )

    # Multiple files → ZIP
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, fdata, _ in optimized_files:
            zf.writestr(fname, fdata)

    zip_buf.seek(0)

    import json
    results_json = quote(json.dumps(results, ensure_ascii=False))

    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="optimized_images.zip"',
            "X-Results": results_json,
            "Access-Control-Expose-Headers": "X-Results",
        },
    )


@app.post("/api/optimize/info")
async def optimize_info(
    files: list[UploadFile] = File(...),
    strip_metadata: bool = Form(True),
    convert_webp: bool = Form(False),
    quality: int = Form(80),
):
    """Optimize images and return only stats (no file data).

    Useful for preview before downloading.
    """
    if not files:
        raise HTTPException(status_code=400, detail="ファイルが選択されていません。")

    if len(files) > 20:
        raise HTTPException(status_code=400, detail="一度に最大20ファイルまでです。")

    results: list[dict] = []

    for upload in files:
        ct = upload.content_type or ""
        if ct not in ALLOWED_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"非対応の形式です: {upload.filename} ({ct})",
            )

        data = await upload.read()
        if len(data) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"ファイルが大きすぎます: {upload.filename} (最大50MB)",
            )

        try:
            result = optimize_image(
                data,
                upload.filename or "image.jpg",
                strip_metadata=strip_metadata,
                convert_webp=convert_webp,
                quality=max(1, min(100, quality)),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"最適化エラー ({upload.filename}): {exc}",
            )

        out_filename = get_output_filename(
            upload.filename or "image", result.output_format
        )
        results.append(
            {
                "filename": upload.filename,
                "output_filename": out_filename,
                **result.to_dict(),
            }
        )

    return {"results": results, "count": len(results)}


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Static files (frontend) — must be AFTER API routes
# ---------------------------------------------------------------------------

if FRONTEND_DIR.exists():
    app.mount(
        "/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend"
    )
