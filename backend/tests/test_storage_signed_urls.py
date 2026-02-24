"""
Tests for storage backend signed URL generation and validation.

These tests verify that signed URLs are properly generated and validated
for the LocalStorageBackend.
"""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from botocore.stub import ANY, Stubber

from app.infra.storage.backends import (
    CloudflareImagesStorageBackend,
    InMemoryStorageBackend,
    LocalStorageBackend,
    S3StorageBackend,
)


class TestLocalStorageBackendSignedUrls:
    """Tests for LocalStorageBackend signed URL functionality."""

    def test_generate_and_validate_signed_url(self, tmp_path):
        """
        Test that a generated signed URL can be validated successfully.
        """
        backend = LocalStorageBackend(
            root=tmp_path,
            signing_secret="test-secret-key-for-hmac-signing"
        )

        key = "test-file.txt"
        resource_url = "https://api.example.test/download"
        expires_in = 3600  # 1 hour

        # Generate signed URL
        signed_url = asyncio.run(
            backend.generate_signed_get_url(
                key=key,
                expires_in=expires_in,
                resource_url=resource_url
            )
        )

        # Verify URL was generated
        assert signed_url.startswith(resource_url)
        assert "exp=" in signed_url
        assert "sig=" in signed_url

        # Validate the signed URL
        is_valid = backend.validate_signed_get_url(key=key, url=signed_url)
        assert is_valid is True

    def test_signed_url_validation_fails_with_wrong_key(self, tmp_path):
        """
        Test that validation fails when key doesn't match.
        """
        backend = LocalStorageBackend(
            root=tmp_path,
            signing_secret="test-secret-key-for-hmac-signing"
        )

        key = "test-file.txt"
        wrong_key = "different-file.txt"
        resource_url = "https://api.example.test/download"
        expires_in = 3600

        # Generate signed URL for one key
        signed_url = asyncio.run(
            backend.generate_signed_get_url(
                key=key,
                expires_in=expires_in,
                resource_url=resource_url
            )
        )

        # Try to validate with different key
        is_valid = backend.validate_signed_get_url(key=wrong_key, url=signed_url)
        assert is_valid is False

    def test_signed_url_validation_fails_when_expired(self, tmp_path):
        """
        Test that validation fails for expired URLs.
        """
        backend = LocalStorageBackend(
            root=tmp_path,
            signing_secret="test-secret-key-for-hmac-signing"
        )

        key = "test-file.txt"
        resource_url = "https://api.example.test/download"
        expires_in = 1  # 1 second

        # Generate signed URL
        signed_url = asyncio.run(
            backend.generate_signed_get_url(
                key=key,
                expires_in=expires_in,
                resource_url=resource_url
            )
        )

        # Wait for expiration
        time.sleep(2)

        # Try to validate expired URL
        is_valid = backend.validate_signed_get_url(key=key, url=signed_url)
        assert is_valid is False

    def test_signed_url_validation_uses_constant_time_comparison(self, tmp_path):
        """
        Test that signature validation uses constant-time comparison.

        This is a security best practice to prevent timing attacks.
        """
        from app.infra.storage import backends
        import inspect

        # Get source code of validate_signature method (used by validate_signed_get_url)
        source = inspect.getsource(backends.LocalStorageBackend.validate_signature)

        # Verify constant-time comparison is used
        assert "hmac.compare_digest" in source or "compare_digest" in source, \
            "Signed URL validation should use constant-time comparison (hmac.compare_digest)"

    def test_local_backend_full_workflow(self, tmp_path):
        """
        Test full workflow: PUT file -> generate signed URL -> validate URL -> read file.
        """
        backend = LocalStorageBackend(
            root=tmp_path,
            signing_secret="test-secret-key-for-hmac-signing"
        )

        key = "uploads/photo.jpg"
        content = b"fake-image-data"

        async def workflow():
            # Put file
            async def content_iterator():
                yield content

            stored = await backend.put(
                key=key,
                body=content_iterator(),
                content_type="image/jpeg"
            )
            assert stored.key == key
            assert stored.size == len(content)

            # Generate signed URL
            signed_url = await backend.generate_signed_get_url(
                key=key,
                expires_in=3600,
                resource_url="https://api.example.test/download"
            )
            assert signed_url is not None

            # Validate signed URL
            is_valid = backend.validate_signed_get_url(key=key, url=signed_url)
            assert is_valid is True

            # Read file back
            read_content = await backend.read(key=key)
            assert read_content == content

        asyncio.run(workflow())


class TestInMemoryStorageBackendSignedUrls:
    """Tests for InMemoryStorageBackend signed URL functionality."""

    def test_generate_signed_url_with_resource_url(self):
        """
        Test that InMemoryStorageBackend generates URLs with provided resource_url.
        """
        backend = InMemoryStorageBackend()

        key = "test-file.txt"
        resource_url = "https://api.example.test/download"
        expires_in = 3600

        signed_url = asyncio.run(
            backend.generate_signed_get_url(
                key=key,
                expires_in=expires_in,
                resource_url=resource_url
            )
        )

        assert signed_url.startswith("https://example.invalid/test-file.txt")
        assert "exp=" in signed_url

    def test_in_memory_backend_full_workflow(self):
        """
        Test full workflow for in-memory backend.
        """
        backend = InMemoryStorageBackend()

        key = "uploads/photo.jpg"
        content = b"fake-image-data"

        async def workflow():
            # Put file
            async def content_iterator():
                yield content

            stored = await backend.put(
                key=key,
                body=content_iterator(),
                content_type="image/jpeg"
            )
            assert stored.key == key
            assert stored.size == len(content)

            signed_url = await backend.generate_signed_get_url(
                key=key,
                expires_in=3600,
                resource_url="https://api.example.test/download"
            )
            assert signed_url.startswith("https://example.invalid/uploads/photo.jpg")

            # Read file back
            read_content = await backend.read(key=key)
            assert read_content == content

        asyncio.run(workflow())


class _NoUnboundedReadStream:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


def test_s3_put_streams_body_without_full_buffering():
    class FakeS3Client:
        def __init__(self) -> None:
            self.payload = bytearray()
            self.read_sizes: list[int] = []

        def put_object(self, Bucket: str, Key: str, Body, ContentType: str):
            assert not isinstance(Body, (bytes, bytearray))
            while True:
                chunk = Body.read(5)
                self.read_sizes.append(5)
                if not chunk:
                    break
                self.payload.extend(chunk)

    backend = S3StorageBackend(
        bucket="uploads",
        access_key="ak",
        secret_key="sk",
        client=FakeS3Client(),
        enable_circuit_breaker=False,
    )

    async def _body():
        source = _NoUnboundedReadStream([b"abc", b"def", b"ghi"])
        async for chunk in source:
            yield chunk

    stored = asyncio.run(backend.put(key="orders/1/photo.jpg", body=_body(), content_type="image/jpeg"))

    assert bytes(backend.client.payload) == b"abcdefghi"
    assert stored.size == 9


def test_s3_put_rejects_payload_over_limit_without_buffering():
    class FakeS3Client:
        def put_object(self, Bucket: str, Key: str, Body, ContentType: str):
            while True:
                chunk = Body.read(4)
                if not chunk:
                    break

    backend = S3StorageBackend(
        bucket="uploads",
        access_key="ak",
        secret_key="sk",
        max_payload_bytes=8,
        client=FakeS3Client(),
        enable_circuit_breaker=False,
    )

    async def _body():
        source = _NoUnboundedReadStream([b"abcd", b"efgh", b"ij"])
        async for chunk in source:
            yield chunk

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(backend.put(key="orders/1/photo.jpg", body=_body(), content_type="image/jpeg"))

    assert exc_info.value.status_code == 413


def test_s3_put_supports_unbounded_read_to_eof():
    class FakeS3Client:
        def __init__(self) -> None:
            self.payload = b""

        def put_object(self, Bucket: str, Key: str, Body, ContentType: str):
            self.payload = Body.read(-1)

    backend = S3StorageBackend(
        bucket="uploads",
        access_key="ak",
        secret_key="sk",
        client=FakeS3Client(),
        enable_circuit_breaker=False,
    )

    async def _body():
        source = _NoUnboundedReadStream([b"abc", b"def", b"ghi"])
        async for chunk in source:
            yield chunk

    stored = asyncio.run(backend.put(key="orders/1/photo.jpg", body=_body(), content_type="image/jpeg"))

    assert backend.client.payload == b"abcdefghi"
    assert stored.size == 9


def test_s3_put_does_not_hang_on_abort_during_upload():
    class UploadAbortedError(RuntimeError):
        pass

    class FakeS3Client:
        def put_object(self, Bucket: str, Key: str, Body, ContentType: str):
            _ = Body.read(1)
            raise UploadAbortedError("client aborted upload")

    backend = S3StorageBackend(
        bucket="uploads",
        access_key="ak",
        secret_key="sk",
        client=FakeS3Client(),
        enable_circuit_breaker=False,
    )

    async def _body():
        for _ in range(512):
            yield b"x" * 1024

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            asyncio.run,
            backend.put(key="orders/1/photo.jpg", body=_body(), content_type="image/jpeg"),
        )
        try:
            with pytest.raises(UploadAbortedError):
                future.result(timeout=1)
        except FuturesTimeoutError as exc:  # pragma: no cover - regression guard
            pytest.fail(f"backend.put hung after abort: {exc}")


def test_s3_put_does_not_hang_when_upload_aborts_before_first_read():
    class UploadAbortedError(RuntimeError):
        pass

    class FakeS3Client:
        def put_object(self, Bucket: str, Key: str, Body, ContentType: str):  # noqa: N802, ANN001, ANN201
            raise UploadAbortedError("client aborted upload before read")

    backend = S3StorageBackend(
        bucket="uploads",
        access_key="ak",
        secret_key="sk",
        client=FakeS3Client(),
        enable_circuit_breaker=False,
    )

    async def _body():
        while True:
            yield b"x" * 1024

    before_threads = len([thread for thread in threading.enumerate() if thread.is_alive()])
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            asyncio.run,
            backend.put(key="orders/1/photo.jpg", body=_body(), content_type="image/jpeg"),
        )
        try:
            with pytest.raises(UploadAbortedError):
                future.result(timeout=1)
        except FuturesTimeoutError as exc:  # pragma: no cover - regression guard
            pytest.fail(f"backend.put hung after early abort: {exc}")
    after_threads = len([thread for thread in threading.enumerate() if thread.is_alive()])
    assert after_threads <= before_threads + 1



def test_s3_put_abort_before_read_does_not_leave_reader_blocked():
    class UploadAbortedError(RuntimeError):
        pass

    class FakeS3Client:
        def __init__(self) -> None:
            self.body = None

        def put_object(self, Bucket: str, Key: str, Body, ContentType: str):  # noqa: N802, ANN001, ANN201
            self.body = Body
            raise UploadAbortedError("client aborted upload before read")

    client = FakeS3Client()
    backend = S3StorageBackend(
        bucket="uploads",
        access_key="ak",
        secret_key="sk",
        client=client,
        enable_circuit_breaker=False,
    )

    async def _body():
        while True:
            yield b"x" * 1024

    with pytest.raises(UploadAbortedError):
        asyncio.run(backend.put(key="orders/1/photo.jpg", body=_body(), content_type="image/jpeg"))

    assert client.body is not None
    assert client.body.read() == b""

def test_s3_put_streams_with_real_botocore_stubber_non_seekable_body():
    backend = S3StorageBackend(
        bucket="uploads",
        access_key="ak",
        secret_key="sk",
        region="us-east-1",
        endpoint="https://s3.test.invalid",
        enable_circuit_breaker=False,
    )

    assert backend.client.meta.config.s3.get("payload_signing_enabled") is False

    with Stubber(backend.client) as stubber:
        stubber.add_response(
            "put_object",
            {"ETag": '"abc123"'},
            {
                "Bucket": "uploads",
                "Key": "orders/1/photo.jpg",
                "Body": ANY,
                "ContentType": "image/jpeg",
            },
        )

        async def _body():
            source = _NoUnboundedReadStream([b"abc", b"def", b"ghi"])
            async for chunk in source:
                yield chunk

        stored = asyncio.run(
            backend.put(key="orders/1/photo.jpg", body=_body(), content_type="image/jpeg")
        )

    assert stored.size == 9


def test_cloudflare_images_put_streams_multipart_request_body():
    collected = bytearray()

    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["content-type"].startswith("multipart/form-data; boundary=")
        for part in request.stream:
            collected.extend(part)
        return httpx.Response(200, json={"success": True, "result": {"id": "img-stream"}})

    backend = CloudflareImagesStorageBackend(
        account_id="acct",
        api_token="token",
        account_hash="hash",
        default_variant="public",
        max_payload_bytes=1024,
        client=httpx.AsyncClient(transport=httpx.MockTransport(_handler), base_url="https://api.cloudflare.com"),
    )

    async def _body():
        source = _NoUnboundedReadStream([b"chunk-1", b"chunk-2"])
        async for chunk in source:
            yield chunk

    stored = asyncio.run(backend.put(key="folder/photo.jpg", body=_body(), content_type="image/jpeg"))
    asyncio.run(backend.client.aclose())

    payload = bytes(collected)
    assert b"name=\"requireSignedURLs\"" in payload
    assert b"chunk-1chunk-2" in payload
    assert stored.key == "img-stream"
    assert stored.size == len(b"chunk-1chunk-2")
