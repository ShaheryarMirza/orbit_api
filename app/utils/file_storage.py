import os
import shutil
import uuid
import urllib.request
import urllib.error

from fastapi import UploadFile

SUPABASE_URL = (
    os.getenv("SUPABASE_URL")
    or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    or "https://iqwpwawpmndewyxmvpju.supabase.co"
)
SUPABASE_KEY = (
    os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    or os.getenv("SUPABASE_ANON_KEY")
    or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
    or ""
)
SUPABASE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET") or "products"




def save_upload_file(upload_file: UploadFile, folder_name: str) -> str:
    """
    Saves an uploaded file to Supabase Cloud Storage returning a permanent Public URL,
    with local disk fallback for development environments.
    """
    filename = upload_file.filename or "file.png"
    _, ext = os.path.splitext(filename)
    if not ext:
        ext = ".png"

    unique_filename = f"{uuid.uuid4()}{ext.lower()}"
    file_bytes = upload_file.file.read()
    upload_file.file.seek(0)

    content_type = upload_file.content_type or "image/png"

    # Attempt direct upload to Supabase Storage bucket (permanent Public URL)
    bucket = SUPABASE_BUCKET
    supabase_url_clean = SUPABASE_URL.rstrip("/")
    object_path = f"{folder_name}/{unique_filename}"
    upload_endpoint = f"{supabase_url_clean}/storage/v1/object/{bucket}/{object_path}"

    if SUPABASE_KEY and not SUPABASE_KEY.endswith("placeholder"):
        try:
            req = urllib.request.Request(
                upload_endpoint,
                data=file_bytes,
                headers={
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "apiKey": SUPABASE_KEY,
                    "Content-Type": content_type,
                    "x-upsert": "true",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status in (200, 201):
                    # Return permanent Public URL (no expiration timestamp)
                    public_url = f"{supabase_url_clean}/storage/v1/object/public/{bucket}/{object_path}"
                    return public_url
        except Exception as exc:
            print(f"[Storage Notice] Supabase cloud upload skipped or offline ({exc}), using local storage.")

    # Local disk fallback
    folder_path = os.path.join("uploads", folder_name)
    os.makedirs(folder_path, exist_ok=True)
    file_path = os.path.join(folder_path, unique_filename)

    with open(file_path, "wb") as buffer:
        buffer.write(file_bytes)

    try:
        frontend_folder = os.path.join("..", "frontend", "public", "uploads", folder_name)
        if os.path.exists(os.path.dirname(os.path.dirname(frontend_folder))):
            os.makedirs(frontend_folder, exist_ok=True)
            shutil.copy2(file_path, os.path.join(frontend_folder, unique_filename))
    except Exception:
        pass

    return f"/uploads/{folder_name}/{unique_filename}"
