from __future__ import annotations


 

import re

from pathlib import Path

from typing import Any


 

from PIL import Image, ImageEnhance, ImageFilter, ImageOps


 

# from backend.app.integrations import extract_fields_from_text

from backend.app.schemas import InvoiceFields, LineItem

from backend.app.settings import DOCUMENT_EXTENSIONS



 

def _prepare_ocr_image(image: Image.Image) -> Image.Image:

    image = ImageOps.exif_transpose(image).convert("L")

    image = ImageOps.autocontrast(image)

    scale = min(3.0, max(1.0, 1800 / image.height))

    if scale > 1:

        image = image.resize(

            (round(image.width * scale), round(image.height * scale)),

            Image.Resampling.LANCZOS,

        )

    image = ImageEnhance.Sharpness(image).enhance(1.5)

    return image.filter(ImageFilter.MedianFilter(size=3))



 

def _ocr_image(image: Image.Image) -> str:

    import pytesseract


 

    processed = _prepare_ocr_image(image)

    text = pytesseract.image_to_string(processed, config="--oem 3 --psm 6").strip()

    if len(re.sub(r"[^A-Za-z0-9]", "", text)) < 20:

        alternate = pytesseract.image_to_string(processed, config="--oem 3 --psm 11").strip()

        if len(re.sub(r"[^A-Za-z0-9]", "", alternate)) > len(re.sub(r"[^A-Za-z0-9]", "", text)):

            return alternate

    return text



 

# JSON invoices are no longer supported: *.meta.json files are sidecar metadata only.



 

def _docx_pages(path: Path) -> list[dict[str, Any]]:

    """Read a Word document as plain text, keeping table rows aligned for line-item parsing."""

    from docx import Document


 

    document = Document(str(path))

    blocks: list[str] = []

    for paragraph in document.paragraphs:

        text = paragraph.text.strip()

        if text:

            blocks.append(text)

    for table in document.tables:

        for row in table.rows:

            cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]

            deduped: list[str] = []

            for cell in cells:

                if not deduped or deduped[-1] != cell:

                    deduped.append(cell)

            line = "  ".join(cell for cell in deduped if cell)

            if line:

                blocks.append(line)

    for section in document.sections:

        for part in (section.header, section.footer):

            for paragraph in part.paragraphs:

                text = paragraph.text.strip()

                if text and text not in blocks:

                    blocks.append(text)

    return [{"page": 1, "text": "\n".join(blocks).strip()}]



 

def extract_document(path: Path, extension: str) -> tuple[str, InvoiceFields, list[dict[str, Any]]]:

    # JSON files in the monitored folder are sidecar metadata, never invoices, so an
    # invoice is only ever extracted from a PDF, a DOCX or an image.

    if extension not in DOCUMENT_EXTENSIONS:

        raise ValueError(

            f"'{extension}' is not an invoice document. "

            f"Supported types are: {', '.join(sorted(DOCUMENT_EXTENSIONS))}."

        )


 

    pages: list[dict[str, Any]] = []

    if extension == ".pdf":

        import fitz

        with fitz.open(path) as document:

            for number, page in enumerate(document, start=1):

                text = page.get_text("text").strip()

                if not text:

                    from io import BytesIO

                    pixmap = page.get_pixmap(dpi=200, alpha=False)

                    with Image.open(BytesIO(pixmap.tobytes("png"))) as image:

                        text = _ocr_image(image)

                pages.append({"page": number, "text": text})

    elif extension == ".docx":

        pages = _docx_pages(path)

    else:

        with Image.open(path) as image:

            pages.append({"page": 1, "text": _ocr_image(image)})


 

    raw_text = "\n\n".join(page["text"] for page in pages).strip()

    # fields = extract_fields_from_text(raw_text)
    

    # line_items = []

    # for match in re.finditer(

    #     r"\b(SKU-[A-Z0-9-]+)\b[^\r\n]*?(\d+(?:\.\d+)?)\s*(?:x|@)\s*[$€£₹]?\s*(\d+(?:\.\d{1,2})?)",

    #     raw_text,

    #     flags=re.IGNORECASE,

    # ):

    #     qty, unit_price = float(match.group(2)), float(match.group(3))

    #     line_items.append(LineItem(

    #         item_code=match.group(1).upper(),

    #         description=match.group(0).split(match.group(1), 1)[-1].strip(),

    #         qty=qty,

    #         unit_price=unit_price,

    #         total=round(qty * unit_price, 2),

    #     ))

    # if not line_items:

    #     for line in raw_text.splitlines():

    #         match = re.match(

    #             r"^\s*(?P<description>.+?)\s+(?P<qty>\d+(?:\.\d+)?)\s+"

    #             r"[$€£₹]?(?P<unit_price>[\d,]+(?:\.\d+)?)\s+"

    #             r"[$€£₹]?(?P<total>[\d,]+(?:\.\d+)?)\s*$",

    #             line,

    #         )

    #         if not match or match.group("description").strip().lower() in {

    #             "item", "subtotal", "tax", "total", "grand total",

    #         }:

    #             continue

    #         line_items.append(LineItem(

    #             description=match.group("description").strip(),

    #             qty=float(match.group("qty").replace(",", "")),

    #             unit_price=float(match.group("unit_price").replace(",", "")),

    #             total=float(match.group("total").replace(",", "")),

    #         ))

    # if line_items:

    #     fields.line_items = line_items

    return raw_text, pages


 