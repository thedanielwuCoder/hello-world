# config.py
import os
from typing import Optional
from dotenv import load_dotenv

# Load .env once on import
load_dotenv()

# ---- Public settings (available if you want them elsewhere) ----
class Settings:
    FLASK_SECRET_KEY: str = os.getenv("FLASK_SECRET_KEY", "dev-secret")

    DB_HOST: str = os.getenv("DB_HOST", "127.0.0.1")
    DB_PORT: int = int(os.getenv("DB_PORT", "3306"))
    DB_NAME: str = os.getenv("DB_NAME", "user_management")
    DB_USER: str = os.getenv("DB_USER", "root")
    DB_PASS: str = os.getenv("DB_PASS", "DanielWu@2003**")
    # DB_AUTH: str = os.getenv("DB_AUTH", "mysql_native_password")

    DB_POOL_NAME: Optional[str] = os.getenv("DB_POOL_NAME", "cic_pool") or None
    DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "0"))  # 0 disables pooling

    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY")

settings = Settings()

# ---- DB connector (mysql-connector) ----
import mysql.connector

def get_db():
    """
    Returns a new MySQL connection. Uses a pool if DB_POOL_SIZE > 0.
    Caller is responsible for closing the connection after use.
    """
    common = dict(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        database=settings.DB_NAME,
        user=settings.DB_USER,
        password=settings.DB_PASS,
        # auth_plugin=settings.DB_AUTH,
    )

    if settings.DB_POOL_SIZE and settings.DB_POOL_SIZE > 0:
        return mysql.connector.connect(
            **common,
            pool_name=settings.DB_POOL_NAME or "cic_pool",
            pool_size=settings.DB_POOL_SIZE,
            pool_reset_session=True,
        )
    else:
        return mysql.connector.connect(**common)
