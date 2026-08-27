#!/usr/bin/env python3
"""
Recover Arabic text from composed EPUBs in MinIO outputs bucket.
Run inside the pdf-service container (has minio + all deps).
Usage: docker exec arabic-book-creator-pdf-1 python /app/recover_text.py
"""
import json
import sys
import zipfile
import io
import os
import re
from minio import Minio

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
OUTPUTS_BUCKET = "outputs"

def get_output_bytes(client, key):
    response = client.get_object(OUTPUTS_BUCKET, key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()

def extract_text_from_epub(epub_bytes):
    pages = []
    with zipfile.ZipFile(io.BytesIO(epub_bytes)) as zf:
        xhtml_files = sorted([
            n for n in zf.namelist()
            if n.endswith('.xhtml') or n.endswith('.html')
        ])
        for fname in xhtml_files:
            content = zf.read(fname).decode('utf-8')
            rtl_paragraphs = re.findall(r'<p[^>]*dir="rtl"[^>]*>(.*?)</p>', content, re.DOTALL)
            if rtl_paragraphs:
                text_parts = []
                for p in rtl_paragraphs:
                    clean = re.sub(r'<[^>]+>', '', p).strip()
                    if clean:
                        text_parts.append(clean)
                if text_parts:
                    pages.append({
                        'file': fname,
                        'text': '\n'.join(text_parts)
                    })
    return pages

def main():
    client = Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS, secret_key=MINIO_SECRET, secure=False)

    book_ids = ['1', '5', '9', '11', '14', '16', '17', '20', '22', '23', '24', '25', '26', '27', '28']
    results = {}

    for book_id in book_ids:
        epub_key = f"{book_id}/interior.epub"
        try:
            epub_bytes = get_output_bytes(client, epub_key)
            pages = extract_text_from_epub(epub_bytes)
            if pages:
                results[book_id] = pages
                print(f"Book {book_id}: recovered text from {len(pages)} pages", file=sys.stderr)
            else:
                print(f"Book {book_id}: no text found in EPUB", file=sys.stderr)
        except Exception as e:
            print(f"Book {book_id}: error - {e}", file=sys.stderr)

    print(json.dumps(results, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
