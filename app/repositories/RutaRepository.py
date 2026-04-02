# app/repositories/ruta_repository.py

from sqlalchemy.orm import Session
from app.models.Ruta import Ruta
from typing import Optional


def find_all(db: Session) -> list[Ruta]:
    return db.query(Ruta).all()


def find_by_id(db: Session, ruta_id: int) -> Optional[Ruta]:
    return db.query(Ruta).filter(Ruta.ruta_id == ruta_id).first()


def save(db: Session, ruta: Ruta) -> Ruta:
    db.add(ruta)
    db.commit()
    db.refresh(ruta)
    return ruta


def delete(db: Session, ruta: Ruta):
    db.delete(ruta)
    db.commit()