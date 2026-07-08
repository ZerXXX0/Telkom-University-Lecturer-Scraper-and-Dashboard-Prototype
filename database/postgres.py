from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from database.models import Base
from config import settings
from utils.logger import get_logger

logger = get_logger("database")

engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
        Base.metadata.create_all(bind=engine)
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
