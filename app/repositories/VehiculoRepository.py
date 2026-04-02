# app/repositories/vehiculo_repository.py

from sqlalchemy.orm import Session
from app.models.Vehiculo import Vehiculo
from typing import Optional


def find_by_placa(db: Session, placa: str) -> Optional[Vehiculo]:
    return db.query(Vehiculo).filter(Vehiculo.placa == placa).first()


def find_all(db: Session) -> list[Vehiculo]:
    return db.query(Vehiculo).all()


def find_by_id(db: Session, vehiculo_id: int) -> Optional[Vehiculo]:
    return db.query(Vehiculo).filter(Vehiculo.vehiculo_id == vehiculo_id).first()


def save(db: Session, vehiculo: Vehiculo) -> Vehiculo:
    db.add(vehiculo)
    db.commit()
    db.refresh(vehiculo)
    return vehiculo


def delete(db: Session, vehiculo: Vehiculo):
    db.delete(vehiculo)
    db.commit()