import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    GEMINI_API_KEY: str = "placeholder"
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/lecturer_db"
    OPENALEX_EMAIL: str = "dev@telkomuniversity.ac.id"
    
    DATA_DIR: str = "data"
    # Use a directory inside the repository for CI stability.
    # Allows overriding via env var BASE_OUTPUT_DIR if needed.
    BASE_OUTPUT_DIR: str = os.path.abspath(os.getenv("BASE_OUTPUT_DIR", os.path.join(os.path.dirname(__file__), "..", "output")))
    INPUT_DIR: str = os.path.join(DATA_DIR, "input")
    RAW_DIR: str = os.path.join(BASE_OUTPUT_DIR, "raw")
    CLEANED_DIR: str = os.path.join(BASE_OUTPUT_DIR, "cleaned")
    JSON_DIR: str = os.path.join(BASE_OUTPUT_DIR, "json")
    
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIM: int = 384
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
