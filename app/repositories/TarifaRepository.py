# app/repositories/tarifa_repository.py

from sqlalchemy.orm import Session
from app.models.Tarifa import Tarifa
from typing import Optional


def find_all(db: Session) -> list[Tarifa]:
    return db.query(Tarifa).all()


def find_by_id(db: Session, tarifa_id: int) -> Optional[Tarifa]:
    return db.query(Tarifa).filter(Tarifa.id == tarifa_id).first()


def save(db: Session, tarifa: Tarifa) -> Tarifa:
    """
    Guarda o actualiza una tarifa en la base de datos.
    Se usa db.merge() para que funcione tanto en 'Nueva Tarifa' como en 'Editar'.
    """
    if tarifa.id:
        # Si ya tiene ID, fusionamos los cambios con el registro existente
        tarifa = db.merge(tarifa)
    else:
        # Si no tiene ID, es un registro nuevo
        db.add(tarifa)
    
    db.commit()
    db.refresh(tarifa)
    return tarifa


def delete(db: Session, tarifa: Tarifa):
    """
    Elimina una tarifa de la base de datos.
    """
    db.delete(tarifa)
    db.commit()