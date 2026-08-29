from fastapi import APIRouter, HTTPException
from src.database.database import check_connection

router = APIRouter()


@router.get("/health")
def health():
    try:
        check_connection()
        return {"status": "Database is healthy"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
