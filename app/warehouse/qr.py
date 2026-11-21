"""QR code generation."""
from __future__ import annotations

import io
import qrcode
from PIL import Image


def generate_qr_png(url: str, box_size: int = 10, border: int = 2) -> bytes:
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=box_size, border=border)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    output = io.BytesIO()
    img.save(output, format="PNG")
    return output.getvalue()
