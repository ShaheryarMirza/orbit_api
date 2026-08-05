import os
import shutil
import uuid

from fastapi import UploadFile


def save_upload_file(upload_file: UploadFile, folder_name: str) -> str:
    """Saves an uploaded file to local disk and returns the relative URL path."""
    # Define the directory path
    folder_path = os.path.join("uploads", folder_name)
    os.makedirs(folder_path, exist_ok=True)

    # Extract the file extension
    filename = upload_file.filename or ""
    _, ext = os.path.splitext(filename)

    # Generate a unique filename using UUID
    unique_filename = f"{uuid.uuid4()}{ext}"
    file_path = os.path.join(folder_path, unique_filename)

    # Save the file contents to backend uploads folder
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)

    # Also copy to frontend/public/uploads folder if available on host
    try:
        frontend_folder = os.path.join("..", "frontend", "public", "uploads", folder_name)
        if os.path.exists(os.path.dirname(os.path.dirname(frontend_folder))):
            os.makedirs(frontend_folder, exist_ok=True)
            shutil.copy2(file_path, os.path.join(frontend_folder, unique_filename))
    except Exception:
        pass

    # Return the relative URL path as a string using forward slashes
    return f"/uploads/{folder_name}/{unique_filename}"
