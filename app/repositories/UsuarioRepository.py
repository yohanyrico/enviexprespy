# app/repositories/usuario_repository.py

from sqlalchemy.orm import Session
from app.models.Usuario import Usuario
from typing import Optional


def find_by_user_name(db: Session, user_name: str) -> Optional[Usuario]:
    return db.query(Usuario).filter(Usuario.user_name == user_name).first()


def find_by_rol(db: Session, rol: str) -> list[Usuario]:
    return db.query(Usuario).filter(Usuario.rol == rol).all()


def find_all(db: Session) -> list[Usuario]:
    return db.query(Usuario).all()


def find_by_id(db: Session, id_usuario: int) -> Optional[Usuario]:
    return db.query(Usuario).filter(Usuario.id_usuario == id_usuario).first()


def save(db: Session, usuario: Usuario) -> Usuario:
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


def delete(db: Session, usuario: Usuario):
    db.delete(usuario)
    db.commit()