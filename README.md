# B2B Sage 50 Ordering Portal - Backend

FastAPI-powered REST API backend that handles user authentication, shop registrations, catalog categories, inventory updates, and order generation (with automatic Zynk XML formatting for Sage 50 integration).

## Tech Stack
*   **Framework**: FastAPI (Python 3)
*   **Database ORM**: SQLAlchemy with PostgreSQL / SQLite support
*   **Migration Engine**: Alembic
*   **Authentication**: JWT (JSON Web Tokens) with Bcrypt password hashing

## Setup Instructions

### 1. Initialize Virtual Environment
Create and activate a virtual environment in the backend root directory:
```bash
# Windows PowerShell
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Linux / macOS Terminal
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Dependencies
Ensure you have the latest packages installed:
```bash
pip install -r requirements.txt
```

### 3. Environment Settings
Create a `.env` file in the backend root with the following variables:
```env
DATABASE_URL=postgresql://user:password@localhost:5432/db_name
JWT_SECRET_KEY=generate_a_secure_random_key_here
ACCESS_TOKEN_EXPIRE_MINUTES=1440
```

### 4. Database Migrations
Run Alembic upgrades to set up your tables:
```bash
alembic upgrade head
```

### 5. Running the Application
Start the development server with Uvicorn:
```bash
uvicorn app.main:app --reload
```
The server will run on `http://127.0.0.1:8000`. You can access interactive OpenAPI documentation at `http://127.0.0.1:8000/docs`.
