# app/repositories/seguimiento_repository.py

from sqlalchemy.orm import Session
from app.models.Seguimiento import Seguimiento
from app.models.Envio import Envio
from typing import Optional


def find_by_envio_order_by_fecha_desc(db: Session, envio: Envio) -> list[Seguimiento]:
    return (
        db.query(Seguimiento)
        .filter(Seguimiento.envio_id == envio.envio_id)
        .order_by(Seguimiento.fecha.desc())
        .all()
    )


def find_all(db: Session) -> list[Seguimiento]:
    return db.query(Seguimiento).all()


def find_by_id(db: Session, seguimiento_id: int) -> Optional[Seguimiento]:
    return db.query(Seguimiento).filter(Seguimiento.seguimiento_id == seguimiento_id).first()


def save(db: Session, seguimiento: Seguimiento) -> Seguimiento:
    db.add(seguimiento)
    db.commit()
    db.refresh(seguimiento)
    return seguimiento


def delete(db: Session, seguimiento: Seguimiento):
    db.delete(seguimiento)
    db.commit()