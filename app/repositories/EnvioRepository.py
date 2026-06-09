# app/repositories/envio_repository.py

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text
from app.models.Envio import Envio
from app.models.EstadoEnvio import EstadoEnvio
from app.models.Usuario import Usuario
from typing import Optional


def _base_query(db: Session):
    """
    Base query que unifica la carga de relaciones (Eager Loading).
    Nota: Se fuerza que la relación de 'seguimientos' cargue los registros 
    asociados para evitar problemas de Lazy Loading fuera de la sesión.
    """
    return db.query(Envio).options(
        joinedload(Envio.cliente),
        joinedload(Envio.mensajero),
        joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega),
        joinedload(Envio.seguimientos)
    )


def find_all(db: Session) -> list[Envio]:
    return _base_query(db).order_by(Envio.fecha_creacion.desc()).all()


def find_by_id(db: Session, envio_id: int) -> Optional[Envio]:
    return _base_query(db).filter(Envio.envio_id == envio_id).first()


def find_by_cliente(db: Session, cliente: Usuario) -> list[Envio]:
    return _base_query(db).filter(Envio.usuario_cliente_id == cliente.id_usuario).order_by(Envio.fecha_creacion.desc()).all()


def find_by_mensajero(db: Session, mensajero: Usuario) -> list[Envio]:
    return _base_query(db).filter(Envio.usuario_mensajero_id == mensajero.id_usuario).order_by(Envio.fecha_creacion.desc()).all()


def find_by_numero_guia(db: Session, numero_guia: str) -> Optional[Envio]:
    guia_limpia = numero_guia.strip().upper()

    # 1. Búsqueda exacta con todas las relaciones cargadas
    resultado = _base_query(db).filter(Envio.numero_guia == guia_limpia).first()

    # 2. Reintento eliminando guiones si no se encontró en primera instancia
    if not resultado and "-" in guia_limpia:
        resultado = _base_query(db).filter(Envio.numero_guia == guia_limpia.replace("-", "")).first()

    # 3. Formato legacy / fallback adaptativo (ENV-XXXXX → E0000000)
    if not resultado and guia_limpia.startswith("ENV"):
        solo_numeros = "".join(filter(str.isdigit, guia_limpia))
        if solo_numeros:
            nueva_guia_posible = f"E{solo_numeros.zfill(7)}"
            resultado = _base_query(db).filter(Envio.numero_guia == nueva_guia_posible).first()

    # --- CONTROL DE ROBUSTEZ ---
    # Si se encontró el envío, aseguramos que sus seguimientos estén ordenados por ID o Fecha 
    # de forma ascendente para que la línea de tiempo se dibuje correctamente en el frontend.
    if resultado and resultado.seguimientos:
        # Intenta ordenar por el atributo disponible de fecha, si falla usa el ID del seguimiento
        try:
            resultado.seguimientos.sort(key=lambda x: x.fecha_creacion if hasattr(x, 'fecha_creacion') else (x.fecha_cambio if hasattr(x, 'fecha_cambio') else x.seguimiento_id))
        except Exception as e:
            print(f"Aviso en ordenamiento de historial: {e}")
            resultado.seguimientos.sort(key=lambda x: x.seguimiento_id)

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