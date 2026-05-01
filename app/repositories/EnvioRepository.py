# app/repositories/envio_repository.py

from sqlalchemy.orm import Session, joinedload  # <-- IMPORTANTE AGREGAR joinedload
from app.models.Envio import Envio
from app.models.EstadoEnvio import EstadoEnvio
from app.models.Usuario import Usuario
from typing import Optional

def find_all(db: Session) -> list[Envio]:
    # Usamos joinedload para traer las relaciones y que el HTML no de error
    return db.query(Envio).options(
        joinedload(Envio.cliente),
        joinedload(Envio.mensajero),
        joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega)
    ).all()

def find_by_id(db: Session, envio_id: int) -> Optional[Envio]:
    return db.query(Envio).options(
        joinedload(Envio.cliente),
        joinedload(Envio.mensajero),
        joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega)
    ).filter(Envio.envio_id == envio_id).first()

def find_by_cliente(db: Session, cliente: Usuario) -> list[Envio]:
    return db.query(Envio).options(
        joinedload(Envio.cliente),
        joinedload(Envio.mensajero),
        joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega)
    ).filter(Envio.usuario_cliente_id == cliente.id_usuario).all()

def find_by_mensajero(db: Session, mensajero: Usuario) -> list[Envio]:
    return db.query(Envio).options(
        joinedload(Envio.cliente),
        joinedload(Envio.mensajero),
        joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega)
    ).filter(Envio.usuario_mensajero_id == mensajero.id_usuario).all()

def find_by_numero_guia(db: Session, numero_guia: str) -> Optional[Envio]:
    guia_limpia = numero_guia.strip().upper()
    
    # 1. Intento de búsqueda exacta (Funciona para ENV-00007, ENV00007 o E0000007)
    resultado = db.query(Envio).options(
        joinedload(Envio.cliente),
        joinedload(Envio.mensajero),
        joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega)
    ).filter(Envio.numero_guia == guia_limpia).first()
    
    # 2. Si no encuentra y la búsqueda tiene guion, intenta sin guion
    if not resultado and "-" in guia_limpia:
        resultado = db.query(Envio).options(
            joinedload(Envio.cliente),
            joinedload(Envio.mensajero),
            joinedload(Envio.lugar_recogida),
            joinedload(Envio.lugar_entrega)
        ).filter(Envio.numero_guia == guia_limpia.replace("-", "")).first()

    # 3. Lógica de transición (Opcional pero recomendada): 
    # Si el usuario busca "ENV-00007" pero en la DB ya migraste a "E0000007"
    if not resultado and guia_limpia.startswith("ENV"):
        # Extraemos solo los números y buscamos con el nuevo formato 'E'
        solo_numeros = "".join(filter(str.isdigit, guia_limpia))
        if solo_numeros:
            nueva_guia_posible = f"E{solo_numeros.zfill(7)}"
            resultado = db.query(Envio).options(
                joinedload(Envio.cliente),
                joinedload(Envio.mensajero),
                joinedload(Envio.lugar_recogida),
                joinedload(Envio.lugar_entrega)
            ).filter(Envio.numero_guia == nueva_guia_posible).first()
    
    return resultado

def find_by_estado(db: Session, estado: EstadoEnvio) -> list[Envio]:
    return db.query(Envio).filter(Envio.estado == estado).all()

def save(db: Session, envio: Envio) -> Envio:
    db.add(envio)
    db.commit()
    db.refresh(envio)
    return envio

def delete(db: Session, envio: Envio):
    db.delete(envio)
    db.commit()
    
def get_by_ids(db: Session, ids: list[int]) -> list[Envio]:
    return db.query(Envio).options(
        joinedload(Envio.cliente),
        joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega)
    ).filter(Envio.envio_id.in_(ids)).all()