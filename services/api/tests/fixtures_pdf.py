"""M1-02 测试 fixture：手工构造最小合法 PDF（不依赖 reportlab）。

文本通过 ToUnicode CMap 映射回 Unicode，pypdf `extract_text` 可正确还原
ASCII 与中文（已在锁定 pypdf 6.19.0 上实测）。空字符串页 = 无文字层页，
用于模拟扫描件。加密页门禁 user 口令非空。
"""

from __future__ import annotations

import io


def make_pdf(page_texts: list[str]) -> bytes:
    seen: dict[str, int] = {}
    for text in page_texts:
        for ch in text:
            if ch not in seen:
                if len(seen) >= 255:
                    raise ValueError("fixture PDF 仅支持每文档 ≤255 个不同字符")
                seen[ch] = len(seen) + 1

    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    bfchar = "".join(f"<{code:02X}> <{ord(ch):04X}>\n" for ch, code in seen.items())
    tounicode = (
        "/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
        "/CMapName /ZhijueTestCMap def /CMapType 2 def\n"
        "begincodespacingrange\n<01> <FF>\nendcodespacingrange\n"
        f"beginbfchar\n{bfchar}endbfchar\n"
        "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend"
    ).encode("ascii")
    tu_obj = add(
        b"<< /Length "
        + str(len(tounicode)).encode()
        + b" >>\nstream\n"
        + tounicode
        + b"\nendstream"
    )
    font_obj = add(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding "
        b"/ToUnicode " + str(tu_obj).encode() + b" 0 R >>"
    )

    page_pairs: list[tuple[int, int]] = []
    for text in page_texts:
        if text:
            codes = "".join(f"{seen[ch]:02X}" for ch in text)
            stream = f"BT /F1 11 Tf 50 700 Td <{codes}> Tj ET".encode("ascii")
        else:
            stream = b""
        content_obj = add(
            b"<< /Length "
            + str(len(stream)).encode()
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )
        page_obj = add(
            b"<< /Type /Page /Parent PAGES /Contents CONTENTS 0 R /Resources << /Font << /F1 "
            + str(font_obj).encode()
            + b" 0 R >> >> >>"
        )
        page_pairs.append((page_obj, content_obj))

    kids = " ".join(f"{page} 0 R" for page, _ in page_pairs)
    pages_obj = add(
        f"<< /Type /Pages /Kids [{kids}] /Count {len(page_texts)} >>".encode("ascii")
    )
    for page_obj, content_obj in page_pairs:
        raw = objects[page_obj - 1]
        objects[page_obj - 1] = raw.replace(
            b"PAGES", f"{pages_obj} 0 R".encode()
        ).replace(b"CONTENTS", str(content_obj).encode())
    catalog_obj = add(f"<< /Type /Catalog /Pages {pages_obj} 0 R >>".encode("ascii"))

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode("ascii"))
        out.write(body)
        out.write(b"\nendobj\n")
    xref_pos = out.tell()
    total = len(objects) + 1
    out.write(f"xref\n0 {total}\n".encode("ascii"))
    out.write(b"0000000000 65535 f \n")
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    out.write(
        (
            f"trailer\n<< /Size {total} /Root {catalog_obj} 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n"
        ).encode("ascii")
    )
    return out.getvalue()


def encrypt_pdf(data: bytes, password: str = "demo-user-pw") -> bytes:
    """加密且 user 口令非空：不口令不可读，匹配 api.md §4 的加密拒绝路径。"""
    from pypdf import PdfWriter

    writer = PdfWriter(clone_from=io.BytesIO(data))
    writer.encrypt(user_password=password, owner_password=password, algorithm="AES-256")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
