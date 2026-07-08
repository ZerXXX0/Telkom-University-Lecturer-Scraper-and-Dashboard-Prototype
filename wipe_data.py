import os
import shutil
from database.postgres import engine, init_db
from database.models import Base
from config import settings
from utils.logger import get_logger

logger = get_logger("wipe_data")

def wipe_database():
    logger.info("Dropping all tables from database...")
    try:
        # Reflect and drop all tables
        Base.metadata.drop_all(bind=engine)
        logger.info("Database tables dropped successfully.")
        
        logger.info("Re-initializing database schema...")
        init_db()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to reset database: {e}")

def clear_directory(path):
    if os.path.exists(path):
        logger.info(f"Clearing directory: {path}")
        for filename in os.listdir(path):
            file_path = os.path.join(path, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                logger.error(f"Failed to delete {file_path}. Reason: {e}")

def wipe_files():
    # 1. Clear BASE_OUTPUT_DIR paths
    clear_directory(settings.RAW_DIR)
    clear_directory(settings.CLEANED_DIR)
    clear_directory(settings.JSON_DIR)
    
    # 2. Clear local data/ subdirectory paths just in case they exist
    clear_directory(os.path.join(settings.DATA_DIR, "raw"))
    clear_directory(os.path.join(settings.DATA_DIR, "cleaned"))
    clear_directory(os.path.join(settings.DATA_DIR, "json"))

def main():
    print("WARNING: This will delete all scraped files, JSON cache, and clear all database tables!")
    confirm = input("Are you sure you want to proceed? (y/N): ").strip().lower()
    if confirm == 'y':
        wipe_database()
        wipe_files()
        print("\nAll data has been wiped successfully. Ready to start from scratch!")
    else:
        print("Operation cancelled.")

if __name__ == "__main__":
    main()
