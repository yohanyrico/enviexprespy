from sqlalchemy.orm import Session
from app.models.Lugar import Lugar
from typing import Optional

def find_all(db: Session) -> list[Lugar]:
    return db.query(Lugar).all()

def find_by_id(db: Session, lugar_id: int) -> Optional[Lugar]:
    return db.query(Lugar).filter(Lugar.lugar_id == lugar_id).first()

def save(db: Session, lugar: Lugar) -> Lugar:
    db.add(lugar)
    db.commit()
    db.refresh(lugar)
    return lugar

def delete(db: Session, lugar: Lugar):
    db.delete(lugar)
    db.commit()