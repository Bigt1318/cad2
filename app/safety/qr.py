"""
FORD-CAD Safety — QR Code Generation Utilities
"""
import io
import zipfile
from typing import List, Dict

QR_PREFIX = "FORDCAD:SAFETY:"


def generate_qr_png(data: str, size: int = 300) -> bytes:
    """Generate a QR code as PNG bytes."""
    try:
        import qrcode
        from qrcode.image.pil import PilImage
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
        qr.add_data(f"{QR_PREFIX}{data}")
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        # Resize
        img = img.resize((size, size))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except ImportError:
        return _generate_qr_svg_fallback_png(data, size)


def _generate_qr_svg_fallback_png(data: str, size: int) -> bytes:
    """Fallback: return a simple placeholder PNG if qrcode not installed."""
    # Minimal 1x1 white PNG
    import struct
    import zlib
    def _make_png(w, h):
        raw = b""
        for _ in range(h):
            raw += b"\x00" + b"\xff\xff\xff" * w
        compressed = zlib.compress(raw)
        def chunk(ctype, cdata):
            c = ctype + cdata
            return struct.pack(">I", len(cdata)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)
        return (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", compressed)
                + chunk(b"IEND", b""))
    return _make_png(1, 1)


def generate_qr_svg(data: str, size: int = 300) -> str:
    """Generate a QR code as SVG string."""
    try:
        import qrcode
        import qrcode.image.svg
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
        qr.add_data(f"{QR_PREFIX}{data}")
        qr.make(fit=True)
        factory = qrcode.image.svg.SvgPathImage
        img = qr.make_image(image_factory=factory)
        buf = io.BytesIO()
        img.save(buf)
        return buf.getvalue().decode("utf-8")
    except ImportError:
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}"><text x="10" y="30" font-size="12">QR: {data[:20]}</text></svg>'


def generate_batch_zip(assets: List[Dict]) -> bytes:
    """Generate a ZIP containing QR PNG images for multiple assets."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for asset in assets:
            qr_data = asset.get("qr_code", "")
            tag = asset.get("asset_tag", f"asset-{asset.get('id', 'unknown')}")
            png = generate_qr_png(qr_data)
            zf.writestr(f"{tag}.png", png)
    return buf.getvalue()


def generate_print_sheet(assets: List[Dict]) -> str:
    """Generate an HTML print sheet with QR labels in a grid."""
    import base64
    rows_html = ""
    for i, asset in enumerate(assets):
        qr_data = asset.get("qr_code", "")
        tag = asset.get("asset_tag", "?")
        type_name = asset.get("type_name", "")
        location = asset.get("location_name", "")

        png_bytes = generate_qr_png(qr_data, size=200)
        b64 = base64.b64encode(png_bytes).decode("ascii")

        rows_html += f"""
        <div style="display:inline-block;width:240px;margin:8px;padding:12px;border:1px solid #333;
                    text-align:center;page-break-inside:avoid;background:#fff;">
            <img src="data:image/png;base64,{b64}" width="180" height="180" style="display:block;margin:0 auto 8px;" />
            <div style="font-weight:bold;font-size:14px;color:#000;">{tag}</div>
            <div style="font-size:11px;color:#555;">{type_name}</div>
            <div style="font-size:10px;color:#888;">{location}</div>
        </div>
        """
        if (i + 1) % 3 == 0:
            rows_html += '<div style="clear:both;"></div>'

    return f"""<!DOCTYPE html>
<html><head>
<title>Safety Equipment QR Labels</title>
<style>
    @media print {{
        body {{ margin: 0; }}
        @page {{ margin: 0.5in; }}
    }}
    body {{ font-family: Arial, sans-serif; background: #fff; padding: 16px; }}
</style>
</head><body>
<h2 style="color:#000;margin-bottom:16px;">Safety Equipment QR Labels</h2>
{rows_html}
</body></html>"""
