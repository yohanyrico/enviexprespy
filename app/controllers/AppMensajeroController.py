# app/controllers/AppMensajeroController.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
from app.config.database import get_db
from app.models.Envio import Envio
from app.models.Ruta import Ruta
from app.models.Usuario import Usuario
from app.security.SecurityConfig import get_current_user

router = APIRouter(prefix="/api/mensajero", tags=["App Mensajero"])

# --- MODELOS ---
class ActualizarEstadoRequest(BaseModel):
    estado: str

class GestionEntregaRequest(BaseModel):
    estado: str
    tipo_receptor: str
    nombre_receptor: Optional[str] = None
    observacion: Optional[str] = None

class UbicacionRequest(BaseModel):
    latitud: float
    longitud: float

class IniciarRutaRequest(BaseModel):
    ruta_id: int


# ─────────────────────────────────────────────────────────────
# HELPER — verifica si todos los envíos de una ruta están
# gestionados (Entregado o Rechazado) y finaliza la ruta sola.
# Se llama después de cada cambio de estado de un envío.
# ─────────────────────────────────────────────────────────────
def _verificar_y_auto_finalizar(ruta_id: int, db: Session) -> bool:
    """
    Retorna True si la ruta fue finalizada automáticamente.
    """
    if not ruta_id:
        return False

    ruta = db.query(Ruta).filter(Ruta.ruta_id == ruta_id).first()
    if not ruta or ruta.estado != "En curso":
        return False

    # Contar envíos que aún NO están gestionados
    estados_terminales = {"Entregado", "Rechazado"}
    pendientes = db.query(Envio).filter(
        Envio.ruta_id == ruta_id,
        Envio.estado.notin_(estados_terminales)
    ).count()

    if pendientes == 0:
        ruta.estado = "Finalizada"
        db.commit()
        return True

    return False


# --- OBTENER PEDIDOS PENDIENTES ---
@router.get("/pedidos-pendientes")
def obtener_pedidos_app(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    try:
        pedidos = db.query(Envio).filter(
            Envio.usuario_mensajero_id == current_user.id_usuario,
            Envio.estado != "Entregado"
        ).all()
        return [
            {
                "id": p.envio_id,
                "guia": p.numero_guia,
                "cliente": f"{p.cliente.nombre} {p.cliente.apellido}" if p.cliente else "N/A",
                "telefono_cliente": p.cliente.telefono if p.cliente else "",
                "direccion_entrega": p.lugar_entrega.direccion if p.lugar_entrega else "Sin dirección",
                "ciudad_destino": p.lugar_entrega.ciudad if p.lugar_entrega else "",
                "estado": p.estado,
                "instrucciones": p.instrucciones or "",
                "latitud": p.lugar_entrega.latitud if p.lugar_entrega else None,
                "longitud": p.lugar_entrega.longitud if p.lugar_entrega else None,
                "es_cod": p.es_cod or False,
                "valor_a_cobrar": float(p.valor_a_cobrar) if p.valor_a_cobrar else 0.0,
                "peso": float(p.peso) if p.peso else 0.0,
                "tipo_servicio": p.tipo_servicio or "BASICA",
            }
            for p in pedidos
        ]
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- INICIAR RUTA (Flutter → presionar botón Iniciar) ---
@router.post("/ruta/iniciar")
def iniciar_ruta(
    body: IniciarRutaRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    if current_user.rol != "MENSAJERO":
        raise HTTPException(status_code=403, detail="Solo mensajeros pueden iniciar rutas.")

    ruta = db.query(Ruta).filter(
        Ruta.ruta_id == body.ruta_id,
        Ruta.mensajero_id == current_user.id_usuario
    ).first()

    if not ruta:
        raise HTTPException(status_code=404, detail="Ruta no encontrada o no pertenece a este mensajero.")

    if ruta.estado != "Creada":
        raise HTTPException(
            status_code=400,
            detail=f"La ruta ya está en estado '{ruta.estado}' y no puede iniciarse de nuevo."
        )

    ruta.estado = "En curso"
    db.commit()
    db.refresh(ruta)

    return {
        "ok": True,
        "mensaje": "Ruta iniciada correctamente.",
        "ruta_id": ruta.ruta_id,
        "estado": ruta.estado
    }


# --- ACTUALIZAR UBICACIÓN ---
@router.post("/ubicacion")
def actualizar_ubicacion(
    body: UbicacionRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    if current_user.rol != "MENSAJERO":
        raise HTTPException(status_code=403, detail="Solo mensajeros pueden enviar ubicación")
    current_user.latitud          = body.latitud
    current_user.longitud         = body.longitud
    current_user.ultima_ubicacion = datetime.now()
    db.commit()
    return {"ok": True}


# --- UBICACIONES ACTIVAS (para mapa web) — sin autenticación ---
@router.get("/ubicaciones-activas")
def obtener_ubicaciones_activas(db: Session = Depends(get_db)):
    hace_5_min = datetime.now() - timedelta(minutes=5)
    mensajeros = db.query(Usuario).filter(
        Usuario.rol == "MENSAJERO",
        Usuario.activo == True,
        Usuario.latitud.isnot(None),
        Usuario.ultima_ubicacion >= hace_5_min
    ).all()
    return [
        {
            "id_usuario": m.id_usuario,
            "nombre": f"{m.nombre} {m.apellido}",
            "latitud": float(m.latitud),
            "longitud": float(m.longitud),
            "ultima_ubicacion": m.ultima_ubicacion.isoformat() if m.ultima_ubicacion else None,
        }
        for m in mensajeros
    ]


# --- ACTUALIZAR ESTADO SIMPLE ---
@router.put("/pedidos/{envio_id}/estado")
def actualizar_estado_envio(
    envio_id: int,
    body: ActualizarEstadoRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    estados_validos = ["Registrado", "En_Bodega", "En_Ruta", "En_Destino",
                       "Entregado", "Cancelado", "Devolucion", "Retorno", "Rechazado", "Fallido"]
    if body.estado not in estados_validos:
        raise HTTPException(status_code=400, detail="Estado inválido.")

    envio = db.query(Envio).filter(
        Envio.envio_id == envio_id,
        Envio.usuario_mensajero_id == current_user.id_usuario
    ).first()
    if not envio:
        raise HTTPException(status_code=404, detail="Envío no encontrado o sin permiso")

    envio.estado = body.estado
    db.commit()
    db.refresh(envio)

    # ── Auto-finalizar ruta si todos los envíos ya fueron gestionados ──
    ruta_finalizada = _verificar_y_auto_finalizar(envio.ruta_id, db)

    return {
        "mensaje": f"Estado actualizado a '{body.estado}'",
        "estado": envio.estado,
        "ruta_finalizada": ruta_finalizada  # Flutter puede usar esto para mostrar un mensaje
    }


# --- GESTIÓN COMPLETA DE ENTREGA ---
@router.post("/pedidos/{envio_id}/gestionar")
def gestionar_entrega(
    envio_id: int,
    body: GestionEntregaRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    estados_validos = ["Entregado", "Fallido", "Cancelado", "Rechazado"]
    if body.estado not in estados_validos:
        raise HTTPException(status_code=400, detail="Estado de gestión inválido.")

    envio = db.query(Envio).filter(
        Envio.envio_id == envio_id,
        Envio.usuario_mensajero_id == current_user.id_usuario
    ).first()
    if not envio:
        raise HTTPException(status_code=404, detail="Envío no encontrado o sin permiso")

    envio.estado = body.estado
    if body.nombre_receptor:
        nota = f"[ENTREGA] Receptor: {body.nombre_receptor} | Tipo: {body.tipo_receptor}"
        if body.observacion:
            nota += f" | Obs: {body.observacion}"
        envio.instrucciones = nota

    db.commit()
    db.refresh(envio)

    # ── Auto-finalizar ruta si todos los envíos ya fueron gestionados ──
    ruta_finalizada = _verificar_y_auto_finalizar(envio.ruta_id, db)

    return {
        "mensaje": f"Gestión registrada. Estado: '{body.estado}'",
        "estado": envio.estado,
        "ruta_finalizada": ruta_finalizada  # True = la ruta se cerró sola
    }