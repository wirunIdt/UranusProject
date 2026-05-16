"""
File Reader Skill
- Read text files (.txt, .md, .py, .js, .csv, etc.)
- Read PDF (via pdfplumber or pypdf2)
- Read images (base64 encode for vision models)
- Returns content + media_type for Ollama API
"""
import os
import base64
import mimetypes

TEXT_EXTS = {
    ".txt", ".md", ".py", ".js", ".ts", ".jsx", ".tsx",
    ".html", ".css", ".json", ".yaml", ".yml", ".toml",
    ".csv", ".xml", ".sh", ".bat", ".sql", ".r", ".go",
    ".java", ".c", ".cpp", ".h", ".rs", ".swift", ".kt",
}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
PDF_EXTS   = {".pdf"}
MAX_TEXT_CHARS = 60_000   # ~15k tokens


def read_file(path: str) -> dict:
    """
    Returns:
        {
          "ok": bool,
          "type": "text" | "image" | "pdf" | "unsupported",
          "content": str,          # for text/pdf
          "base64": str,            # for image
          "mime_type": str,
          "filename": str,
          "size_kb": float,
          "error": str             # if ok=False
        }
    """
    if not os.path.exists(path):
        return {"ok": False, "error": f"File not found: {path}"}

    ext = os.path.splitext(path)[1].lower()
    filename = os.path.basename(path)
    size_kb = os.path.getsize(path) / 1024
    mime_type = mimetypes.guess_type(path)[0] or "application/octet-stream"

    # ── Text ──────────────────────────────────────────────────────────────────
    if ext in TEXT_EXTS:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(MAX_TEXT_CHARS)
            truncated = len(content) >= MAX_TEXT_CHARS
            note = "\n\n[... ไฟล์ถูกตัดเนื่องจากยาวเกินไป ...]" if truncated else ""
            return {
                "ok": True, "type": "text",
                "content": content + note,
                "mime_type": mime_type or "text/plain",
                "filename": filename, "size_kb": round(size_kb, 1),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── Image ─────────────────────────────────────────────────────────────────
    if ext in IMAGE_EXTS:
        try:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            mt_map = {".png":"image/png",".jpg":"image/jpeg",
                      ".jpeg":"image/jpeg",".gif":"image/gif",
                      ".webp":"image/webp",".bmp":"image/bmp"}
            return {
                "ok": True, "type": "image",
                "base64": b64,
                "mime_type": mt_map.get(ext, "image/png"),
                "filename": filename, "size_kb": round(size_kb, 1),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── PDF ───────────────────────────────────────────────────────────────────
    if ext in PDF_EXTS:
        # Try pdfplumber first, then pypdf2
        text = _read_pdf(path)
        if text:
            if len(text) > MAX_TEXT_CHARS:
                text = text[:MAX_TEXT_CHARS] + "\n\n[... ตัดเนื่องจากยาวเกินไป ...]"
            return {
                "ok": True, "type": "pdf",
                "content": text,
                "mime_type": "application/pdf",
                "filename": filename, "size_kb": round(size_kb, 1),
            }
        return {"ok": False, "error": "ไม่สามารถอ่าน PDF ได้ ลอง: pip install pdfplumber"}

    return {
        "ok": False, "type": "unsupported",
        "error": f"ไม่รองรับไฟล์ประเภท {ext}",
        "filename": filename,
    }


def _read_pdf(path: str) -> str | None:
    # pdfplumber (better)
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            pages = []
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text:
                    pages.append(f"--- Page {i+1} ---\n{text}")
        return "\n\n".join(pages) if pages else None
    except ImportError:
        pass
    # pypdf (fallback)
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        pages = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                pages.append(f"--- Page {i+1} ---\n{text}")
        return "\n\n".join(pages) if pages else None
    except ImportError:
        pass
    return None


def build_message_with_file(user_text: str, file_result: dict) -> list:
    """
    Build Ollama message content list with file attached.
    Works with vision models (llava, bakllava, llama3.2-vision).
    """
    if not file_result.get("ok"):
        return [{"type": "text",
                 "text": f"{user_text}\n\n⚠️ ไม่สามารถอ่านไฟล์ได้: {file_result.get('error')}"}]

    ftype = file_result.get("type")
    fname = file_result.get("filename", "file")
    size  = file_result.get("size_kb", 0)

    if ftype == "image":
        return [
            {"type": "text",
             "text": f"{user_text}\n\n[แนบรูปภาพ: {fname} ({size:.0f}KB)]"},
            {"type": "image_url",
             "image_url": {
                 "url": f"data:{file_result['mime_type']};base64,{file_result['base64']}"
             }}
        ]
    elif ftype in ("text", "pdf"):
        header = f"[ไฟล์: {fname} | {size:.0f}KB | {ftype.upper()}]\n\n"
        content = file_result.get("content", "")
        return [{"type": "text",
                 "text": f"{user_text}\n\n{header}```\n{content}\n```"}]
    else:
        return [{"type": "text", "text": user_text}]


SUPPORTED_EXTENSIONS = sorted(TEXT_EXTS | IMAGE_EXTS | PDF_EXTS)
