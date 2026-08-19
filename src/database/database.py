import os
from sqlalchemy import create_engine,text
from dotenv import load_dotenv

load_dotenv()
engine = create_engine(os.environ['AZURE_DB_URL'],pool_pre_ping=True)

def check_connection():
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
