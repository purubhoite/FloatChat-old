from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from urllib.parse import quote_plus

# --- CONFIGURATION ---
DB_USER = "postgres"
DB_PASS = "Nov@2608"
DB_HOST = "localhost"
DB_PORT = "5432"
DB_NAME = "argo_final"

safe_password = quote_plus(DB_PASS)

DATABASE_URL = f"postgresql://{DB_USER}:{safe_password}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

def test_connection():
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1;"))
            print(f"✅ DB test result: {list(result)}")
            print("Connection Successful!")
    except Exception as e:
        print(f"❌ Connection Failed: {e}")

if __name__ == "__main__":
    test_connection()