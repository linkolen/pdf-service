"""
MinIO read/write for the PDF service (spec Section 4.1/4.3). Stateless: reads
uploaded page images by key from the `uploads` bucket, writes composed PDFs
by key to the `outputs` bucket. Bucket creation here is a dev convenience for
running against a bare local MinIO container; Section 8 revisits ownership
of bucket creation once Docker Compose wires up all services.
"""

from __future__ import annotations

import os
from io import BytesIO
from typing import Optional

from minio import Minio

UPLOADS_BUCKET = os.environ.get("MINIO_BUCKET_UPLOADS", "uploads")
OUTPUTS_BUCKET = os.environ.get("MINIO_BUCKET_OUTPUTS", "outputs")


def _client_from_env() -> Minio:
    return Minio(
        os.environ.get("MINIO_ENDPOINT", "localhost:9000"),
        access_key=os.environ.get("MINIO_ACCESS_KEY", "minioadmin"),
        secret_key=os.environ.get("MINIO_SECRET_KEY", "minioadmin"),
        secure=os.environ.get("MINIO_SECURE", "false").lower() == "true",
    )


class Storage:
    def __init__(self, client: Optional[Minio] = None):
        self.client = client or _client_from_env()
        self._ensure_bucket(UPLOADS_BUCKET)
        self._ensure_bucket(OUTPUTS_BUCKET)

    def _ensure_bucket(self, bucket: str) -> None:
        if not self.client.bucket_exists(bucket):
            self.client.make_bucket(bucket)

    def put_image_bytes(self, key: str, data: bytes, content_type: str = "image/png") -> str:
        """Upload helper for seeding/testing. In the real system, Spring Boot
        owns writes to `uploads`; the PDF service only reads from it."""
        self.client.put_object(
            UPLOADS_BUCKET,
            key,
            BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        return key

    def get_image_bytes(self, key: str) -> bytes:
        response = self.client.get_object(UPLOADS_BUCKET, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def put_pdf_bytes(self, key: str, data: bytes) -> str:
        self.client.put_object(
            OUTPUTS_BUCKET,
            key,
            BytesIO(data),
            length=len(data),
            content_type="application/pdf",
        )
        return key
