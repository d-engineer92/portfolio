"""Image optimization service using pngquant + jpegoptim.

Uses industry-standard tools for high-quality compression:
- PNG: pngquant (same engine as TinyPNG) — lossy but visually indistinguishable
- JPEG: jpegoptim — progressive encoding + quality optimization
- WebP: Pillow — high quality lossy conversion
- Metadata stripping preserves ICC color profiles
"""

from __future__ import annotations

import io
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageFile, ImageCms

# Allow loading truncated images gracefully
ImageFile.LOAD_TRUNCATED_IMAGES = True

# Maximum dimension to accept (prevent abuse)
MAX_DIMENSION = 16384
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


@dataclass
class OptimizeResult:
    """Result of an image optimization operation."""

    data: bytes
    original_size: int
    optimized_size: int
    original_format: str
    output_format: str
    width: int
    height: int

    @property
    def savings_bytes(self) -> int:
        return self.original_size - self.optimized_size

    @property
    def savings_pct(self) -> float:
        if self.original_size == 0:
            return 0.0
        return (self.savings_bytes / self.original_size) * 100

    def to_dict(self) -> dict:
        return {
            "original_size": self.original_size,
            "optimized_size": self.optimized_size,
            "savings_bytes": self.savings_bytes,
            "savings_pct": round(self.savings_pct, 1),
            "original_format": self.original_format,
            "output_format": self.output_format,
            "width": self.width,
            "height": self.height,
        }


def _detect_format(img: Image.Image, original_filename: str) -> str:
    """Detect the image format from the PIL Image or filename."""
    if img.format:
        return img.format.upper()
    ext = Path(original_filename).suffix.lower()
    mapping = {
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".png": "PNG",
        ".webp": "WEBP",
        ".gif": "GIF",
        ".bmp": "BMP",
        ".tiff": "TIFF",
        ".tif": "TIFF",
    }
    return mapping.get(ext, "PNG")


def _strip_metadata_preserve_icc(img: Image.Image) -> Image.Image:
    """Strip EXIF metadata but preserve ICC color profile.

    This prevents the color shift that occurs when ICC profiles are removed.
    """
    # Extract ICC profile before stripping
    icc_profile = img.info.get("icc_profile")

    # Create clean image (drops all metadata including EXIF)
    clean = Image.new(img.mode, img.size)
    clean.putdata(list(img.getdata()))

    # Restore ICC profile
    if icc_profile:
        clean.info["icc_profile"] = icc_profile

    # Preserve palette for P mode images
    if img.mode == "P":
        clean.putpalette(img.getpalette())
        if "transparency" in img.info:
            clean.info["transparency"] = img.info["transparency"]

    return clean


def _optimize_png_pngquant(data: bytes, quality: int = 80) -> bytes:
    """Optimize PNG using pngquant (same engine as TinyPNG).

    pngquant uses advanced color quantization with Floyd-Steinberg dithering
    to produce high quality results that are visually indistinguishable.
    """
    # Map quality 1-100 to pngquant's min-max quality range
    # Lower quality = more compression
    q_min = max(0, quality - 30)
    q_max = quality

    with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as tmp_in:
        tmp_in.write(data)
        tmp_in.flush()

        out_path = tmp_in.name.replace(".png", "-fs8.png")

        try:
            result = subprocess.run(
                [
                    "pngquant",
                    "--quality", f"{q_min}-{q_max}",
                    "--speed", "1",  # Slowest = best quality
                    "--strip",       # Strip metadata
                    "--force",
                    "--output", out_path,
                    tmp_in.name,
                ],
                capture_output=True,
                timeout=30,
            )

            if result.returncode == 0 and Path(out_path).exists():
                optimized = Path(out_path).read_bytes()
                Path(out_path).unlink(missing_ok=True)
                return optimized

            # pngquant exit code 99 = quality too low, skip quantization
            # Fall back to standard optimization
            Path(out_path).unlink(missing_ok=True)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            Path(out_path).unlink(missing_ok=True) if Path(out_path).exists() else None

    # Fallback: standard PNG optimization with Pillow
    img = Image.open(io.BytesIO(data))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True, compress_level=9)
    return buf.getvalue()


def _optimize_jpeg(data: bytes, img: Image.Image, quality: int = 80,
                   strip_metadata: bool = True) -> bytes:
    """Optimize JPEG using jpegoptim or Pillow.

    Preserves ICC color profile to maintain accurate colors.
    """
    # Try jpegoptim first (better quality preservation)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=True) as tmp:
        tmp.write(data)
        tmp.flush()

        try:
            cmd = [
                "jpegoptim",
                f"--max={quality}",
                "--all-progressive",
            ]
            if strip_metadata:
                cmd.append("--strip-all")
                # But keep ICC profile for color accuracy
                cmd.append("--strip-none")
                # Actually jpegoptim --strip-all removes everything
                # Let's use --strip-exif --strip-iptc --strip-xmp instead
                cmd = [
                    "jpegoptim",
                    f"--max={quality}",
                    "--all-progressive",
                    "--strip-exif",
                    "--strip-iptc",
                    "--strip-xmp",
                    tmp.name,
                ]
            else:
                cmd.append(tmp.name)

            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=30,
            )

            if result.returncode == 0:
                return Path(tmp.name).read_bytes()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # Fallback: Pillow
    icc_profile = img.info.get("icc_profile")
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    buf = io.BytesIO()
    save_kwargs = {
        "format": "JPEG",
        "optimize": True,
        "quality": quality,
        "progressive": True,
    }
    if icc_profile:
        save_kwargs["icc_profile"] = icc_profile

    img.save(buf, **save_kwargs)
    return buf.getvalue()


def _optimize_webp(img: Image.Image, quality: int = 80) -> bytes:
    """Convert to WebP with high quality lossy encoding."""
    buf = io.BytesIO()
    if img.mode == "P":
        has_alpha = "transparency" in img.info
        img = img.convert("RGBA" if has_alpha else "RGB")

    save_kwargs = {
        "format": "WEBP",
        "lossless": False,
        "quality": quality,
        "method": 6,  # Best compression (slowest)
    }

    icc_profile = img.info.get("icc_profile")
    if icc_profile:
        save_kwargs["icc_profile"] = icc_profile

    img.save(buf, **save_kwargs)
    return buf.getvalue()


def _optimize_generic(img: Image.Image, fmt: str) -> bytes:
    """Fallback: re-save in original format without metadata."""
    buf = io.BytesIO()
    save_kwargs: dict = {}
    if fmt == "GIF":
        save_kwargs["optimize"] = True
    icc_profile = img.info.get("icc_profile")
    if icc_profile:
        save_kwargs["icc_profile"] = icc_profile
    img.save(buf, format=fmt, **save_kwargs)
    return buf.getvalue()


def optimize_image(
    data: bytes,
    filename: str,
    *,
    strip_metadata: bool = True,
    convert_webp: bool = False,
    quality: int = 80,
) -> OptimizeResult:
    """Optimize a single image.

    Uses pngquant for PNG (same as TinyPNG) and jpegoptim for JPEG.
    Preserves ICC color profiles to prevent color shifts.

    Args:
        data: Raw image bytes
        filename: Original filename (used for format detection)
        strip_metadata: Remove EXIF metadata (preserves ICC profile)
        convert_webp: Convert to WebP format
        quality: Compression quality 1-100 (default 80)

    Returns:
        OptimizeResult with optimized data and statistics
    """
    original_size = len(data)

    img = Image.open(io.BytesIO(data))
    original_format = _detect_format(img, filename)

    # Security: reject overly large images
    if img.width > MAX_DIMENSION or img.height > MAX_DIMENSION:
        raise ValueError(
            f"画像が大きすぎます (最大 {MAX_DIMENSION}x{MAX_DIMENSION}px)"
        )

    width, height = img.width, img.height

    # Choose optimization strategy
    if convert_webp:
        if strip_metadata:
            img = _strip_metadata_preserve_icc(img)
        optimized_data = _optimize_webp(img, quality)
        output_format = "WEBP"
    elif original_format == "PNG":
        # For PNG, pass raw data to pngquant (it handles stripping itself)
        if strip_metadata:
            # First strip metadata while preserving ICC, then pass to pngquant
            img_clean = _strip_metadata_preserve_icc(img)
            buf = io.BytesIO()
            icc = img_clean.info.get("icc_profile")
            save_kwargs = {"format": "PNG", "optimize": True, "compress_level": 9}
            if icc:
                save_kwargs["icc_profile"] = icc
            img_clean.save(buf, **save_kwargs)
            clean_data = buf.getvalue()
        else:
            clean_data = data
        optimized_data = _optimize_png_pngquant(clean_data, quality)
        output_format = "PNG"
    elif original_format == "JPEG":
        optimized_data = _optimize_jpeg(data, img, quality, strip_metadata)
        output_format = "JPEG"
    else:
        if strip_metadata:
            img = _strip_metadata_preserve_icc(img)
        optimized_data = _optimize_generic(img, original_format)
        output_format = original_format

    # If optimization made the file larger, return original
    # (unless format conversion was requested)
    if not convert_webp and len(optimized_data) >= original_size:
        optimized_data = data
        output_format = original_format

    return OptimizeResult(
        data=optimized_data,
        original_size=original_size,
        optimized_size=len(optimized_data),
        original_format=original_format,
        output_format=output_format,
        width=width,
        height=height,
    )


def get_output_filename(original: str, output_format: str) -> str:
    """Generate output filename with correct extension."""
    stem = Path(original).stem
    ext_map = {
        "JPEG": ".jpg",
        "PNG": ".png",
        "WEBP": ".webp",
        "GIF": ".gif",
        "BMP": ".bmp",
        "TIFF": ".tiff",
    }
    ext = ext_map.get(output_format, ".bin")
    return f"{stem}_optimized{ext}"
