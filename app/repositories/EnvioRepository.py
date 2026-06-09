# app/repositories/envio_repository.py

from sqlalchemy.orm import Session, joinedload
from app.models.Envio import Envio
from app.models.EstadoEnvio import EstadoEnvio
from app.models.Usuario import Usuario
from typing import Optional


def _base_query(db: Session):
    return db.query(Envio).options(
        joinedload(Envio.cliente),
        joinedload(Envio.mensajero),
        joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega),
        joinedload(Envio.seguimientos)
    )


def find_all(db: Session) -> list[Envio]:
    return _base_query(db).all()


def find_by_id(db: Session, envio_id: int) -> Optional[Envio]:
    return _base_query(db).filter(Envio.envio_id == envio_id).first()


def find_by_cliente(db: Session, cliente: Usuario) -> list[Envio]:
    return _base_query(db).filter(Envio.usuario_cliente_id == cliente.id_usuario).all()


def find_by_mensajero(db: Session, mensajero: Usuario) -> list[Envio]:
    return _base_query(db).filter(Envio.usuario_mensajero_id == mensajero.id_usuario).all()


def find_by_numero_guia(db: Session, numero_guia: str) -> Optional[Envio]:
    guia_limpia = numero_guia.strip().upper()

    # 1. Búsqueda exacta
    resultado = _base_query(db).filter(Envio.numero_guia == guia_limpia).first()

    # 2. Sin guion
    if not resultado and "-" in guia_limpia:
        resultado = _base_query(db).filter(Envio.numero_guia == guia_limpia.replace("-", "")).first()

    # 3. Formato legacy ENV-XXXXX → E0000000
    if not resultado and guia_limpia.startswith("ENV"):
        solo_numeros = "".join(filter(str.isdigit, guia_limpia))
        if solo_numeros:
            nueva_guia_posible = f"E{solo_numeros.zfill(7)}"
            resultado = _base_query(db).filter(Envio.numero_guia == nueva_guia_posible).first()

    return resultado


def find_by_estado(db: Session, estado: EstadoEnvio) -> list[Envio]:
    return _base_query(db).filter(Envio.estado == estado).all()


def save(db: Session, envio: Envio) -> Envio:
    db.add(envio)
    db.commit()
    db.refresh(envio)
    return envio


def delete(db: Session, envio: Envio):
    db.delete(envio)
    db.commit()


def get_by_ids(db: Session, ids: list[int]) -> list[Envio]:
    return _base_query(db).filter(Envio.envio_id.in_(ids)).all()