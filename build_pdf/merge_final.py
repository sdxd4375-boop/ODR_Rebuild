# -*- coding: utf-8 -*-
"""Merge cover + body into the final deliverable PDF."""

import os

from pypdf import PdfReader, PdfWriter, Transformation

HERE = os.path.dirname(os.path.abspath(__file__))
COVER = os.path.join(HERE, "cover.pdf")
BODY = os.path.join(HERE, "body.pdf")
OUT = os.path.join(os.path.dirname(HERE), "docs", "深度调研系统对标分析报告.pdf")

A4_W, A4_H = 595.28, 841.89


def normalize_page_to_a4(page):
    box = page.mediabox
    w, h = float(box.width), float(box.height)
    if abs(w - A4_W) > 2 or abs(h - A4_H) > 2:
        sx, sy = A4_W / w, A4_H / h
        page.add_transformation(Transformation().scale(sx=sx, sy=sy))
        page.mediabox.lower_left = (0, 0)
        page.mediabox.upper_right = (A4_W, A4_H)
    return page


writer = PdfWriter()
writer.add_page(normalize_page_to_a4(PdfReader(COVER).pages[0]))
for page in PdfReader(BODY).pages:
    writer.add_page(normalize_page_to_a4(page))
writer.add_metadata({
    "/Title": "深度调研系统对标分析报告",
    "/Author": "Z.ai",
    "/Creator": "Z.ai",
    "/Subject": "open_deep_research 与 GitHub 同类深度调研系统对比、架构调整与改进路线",
})
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "wb") as f:
    writer.write(f)
print("final:", OUT)
