"""Cloudflare R2 client — private object storage for Secret Images.

R2 is S3-compatible, so this is a thin `boto3` wrapper rather than a bespoke client.
The bucket is expected to be created with no public access and no custom domain, so
every read goes through `presigned_url`, never a plain object URL.

Kept as free functions (not a class) so tests can monkeypatch them individually, the
same way `telegram_bridge.resolve_contact`/`send_text` are swapped for a fake transport.
"""

import os

import boto3


def _account_id() -> str:
    return os.getenv("R2_ACCOUNT_ID", "").strip()


def _access_key_id() -> str:
    return os.getenv("R2_ACCESS_KEY_ID", "").strip()


def _secret_access_key() -> str:
    return os.getenv("R2_SECRET_ACCESS_KEY", "").strip()


def bucket_name() -> str:
    return os.getenv("R2_BUCKET_NAME", "").strip()


def configured() -> bool:
    return bool(_account_id() and _access_key_id() and _secret_access_key() and bucket_name())


def _client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{_account_id()}.r2.cloudflarestorage.com",
        aws_access_key_id=_access_key_id(),
        aws_secret_access_key=_secret_access_key(),
        region_name="auto",
    )


def upload_object(key: str, data: bytes, content_type: str) -> None:
    _client().put_object(Bucket=bucket_name(), Key=key, Body=data, ContentType=content_type)


def delete_object(key: str) -> None:
    _client().delete_object(Bucket=bucket_name(), Key=key)


def presigned_url(key: str, expires_in: int = 900) -> str:
    return _client().generate_presigned_url(
        "get_object", Params={"Bucket": bucket_name(), "Key": key}, ExpiresIn=expires_in
    )
