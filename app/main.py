from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.auth import router as auth_router, api_router as api_auth_router
from app.api.categories import router as categories_router
from app.api.orders import admin_router as admin_orders_router
from app.api.orders import router as orders_router
from app.api.products import router as products_router
from app.api.shops import router as shops_router
from app.api.test_routes import router as test_router
from app.api.sage_sync import router as sage_sync_router
from app.api.users import router as users_router
from app.api.import_shops import router as import_shops_router
from app.api.password_requests import router as password_requests_router
from app.db.database import get_db, SessionLocal, Base, engine
from app.models.user import User
from app.utils.security import hash_password

app = FastAPI(title="B2B Sage Ordering App API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://orbitfood.net",
        "https://www.orbitfood.net",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure base uploads directory exists
os.makedirs("uploads", exist_ok=True)

# Mount static files directory
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

app.include_router(auth_router)
app.include_router(api_auth_router)
app.include_router(admin_orders_router)
app.include_router(categories_router)
app.include_router(orders_router)
app.include_router(products_router)
app.include_router(shops_router)
app.include_router(test_router)
app.include_router(sage_sync_router)
app.include_router(users_router)
app.include_router(import_shops_router)
app.include_router(password_requests_router)


@app.on_event("startup")
def seed_root_admin():
    # Automatically build database tables if they do not exist
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        admin_user = db.query(User).filter(User.email == "admin@admin.com").first()
        if not admin_user:
            root_admin = User(
                name="Root Admin",
                email="admin@admin.com",
                password_hash=hash_password("admin123"),
                role="admin",
                is_active=True
            )
            db.add(root_admin)
            db.commit()
        else:
            # Force role to admin and active status to ensure the admin has permissions
            if admin_user.role != "admin" or not admin_user.is_active:
                admin_user.role = "admin"
                admin_user.is_active = True
                db.commit()
    finally:
        db.close()


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/db-test")
def database_test(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
        return {"database": "connected"}
    except Exception as exc:
        return {"database": "failed", "error": str(exc)}


@app.get("/users-test")
def users_test(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    users = db.query(User).all()
    return [
        {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "is_active": user.is_active,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
        }
        for user in users
    ]
