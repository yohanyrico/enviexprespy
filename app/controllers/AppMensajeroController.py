import os
import shutil
from fastapi.responses import JSONResponse
from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from app.config.database import get_db
from app.models.Envio import Envio
from app.models.Ruta import Ruta
from app.models.Usuario import Usuario
from app.models.UbicacionMensajero import UbicacionMensajero
from app.security.SecurityConfig import get_current_user

router = APIRouter(prefix="/api/mensajero", tags=["App Mensajero"])

# --- ESQUEMAS DE PYDANTIC (MODELOS DE ENTRADA) ---

class ActualizarEstadoRequest(BaseModel):
    estado: str

class ActualizacionMasivaRequest(BaseModel):
    guias: List[str]
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
# HELPER — FUNCIONES DE APOYO INTERNAS
# ─────────────────────────────────────────────────────────────

def _verificar_y_auto_finalizar(ruta_id: int, db: Session) -> bool:
    if not ruta_id:
        return False

    ruta = db.query(Ruta).filter(Ruta.ruta_id == ruta_id).first()
    if not ruta or ruta.estado != "En curso":
        return False

    if ruta.tipo_ruta == "RECOLECCION":
        estados_terminales = {"C-Colectado", "Cancelado", "Rechazado"}
    else:
        estados_terminales = {"Entregado", "Rechazado", "Fallido", "Cancelado"}

    pendientes = db.query(Envio).filter(
        Envio.ruta_id == ruta_id,
        Envio.estado.notin_(estados_terminales)
    ).count()

    if pendientes == 0:
        ruta.estado = "Finalizada"
        db.commit()
        print(f"[RUTA] Ruta {ruta_id} ({ruta.tipo_ruta}) finalizada automáticamente.")
        return True

    return False


# ─────────────────────────────────────────────────────────────
# ENDPOINTS DEL CONTROLADOR
# ─────────────────────────────────────────────────────────────

# --- OBTENER PEDIDOS PENDIENTES ---
@router.get("/pedidos-pendientes", response_model=List[Dict[str, Any]])
def obtener_pedidos_app(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    try:
        estados_activos = [
            "Registrado",
            "Pendiente_Recoger",
            "C-Colectado",
            "En_Bodega",
            "Pendiente_Entregar",
            "En_Ruta",
            "En_Destino"
        ]

        # ✅ FIX: busca por mensajero recolector O mensajero entregador
        pedidos = db.query(Envio).filter(
            or_(
                Envio.usuario_mensajero_id == current_user.id_usuario,
                Envio.usuario_mensajero_entrega_id == current_user.id_usuario
            ),
            Envio.estado.in_(estados_activos)
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
                "latitud": float(p.lugar_entrega.latitud) if p.lugar_entrega and p.lugar_entrega.latitud else None,
                "longitud": float(p.lugar_entrega.longitud) if p.lugar_entrega and p.lugar_entrega.longitud else None,
                "es_cod": p.es_cod or False,
                "valor_a_cobrar": float(p.valor_a_cobrar) if p.valor_a_cobrar else 0.0,
                "peso": float(p.peso) if p.peso else 0.0,
                "tipo_servicio": p.tipo_servicio or "BASICA",
            }
            for p in pedidos
        ]
    except Exception as e:
        print(f"Error en pedidos-pendientes: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# --- INICIAR RUTA ---
@router.post("/ruta/iniciar")
def iniciar_ruta(
    body: IniciarRutaRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    if current_user.rol != "MENSAJERO":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo los usuarios con rol MENSAJERO pueden iniciar rutas."
        )

    ruta = db.query(Ruta).filter(
        Ruta.ruta_id == body.ruta_id,
        Ruta.mensajero_id == current_user.id_usuario
    ).first()

    if not ruta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La ruta especificada no fue encontrada o no pertenece a este mensajero."
        )

    if ruta.estado != "Creada":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"La ruta ya se encuentra en estado '{ruta.estado}' y no puede volver a iniciarse."
        )

    ruta.estado = "En curso"
    db.commit()
    db.refresh(ruta)

    return {
        "ok": True,
        "mensaje": "Ruta iniciada correctamente en el sistema.",
        "ruta_id": ruta.ruta_id,
        "estado": ruta.estado,
        "tipo_ruta": ruta.tipo_ruta
    }


# --- ACTUALIZAR UBICACIÓN DESDE FLUTTER ---
@router.post("/ubicacion")
def actualizar_ubicacion(
    body: UbicacionRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    if current_user.rol != "MENSAJERO":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado: Solo los mensajeros pueden reportar coordenadas GPS."
        )

    try:
        ahora = datetime.now()
        current_user.latitud = body.latitud
        current_user.longitud = body.longitud
        current_user.ultima_ubicacion = ahora

        nueva_coordenada = UbicacionMensajero(
            usuario=current_user.id_usuario,
            latitud=body.latitud,
            longitud=body.longitud,
            fecha=ahora
        )
        db.add(nueva_coordenada)
        db.commit()

        print(f"[GPS] Mensajero ID {current_user.id_usuario} ({current_user.nombre}): [{body.latitud}, {body.longitud}]")
        return {"ok": True, "mensaje": "Coordenadas actualizadas de manera exitosa."}

    except Exception as e:
        db.rollback()
        print(f"Error al actualizar ubicación en DB: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al guardar la geolocalización."
        )


# --- UBICACIONES ACTIVAS (Para el Mapa Web) ---
@router.get("/ubicaciones-activas", response_model=List[Dict[str, Any]])
def obtener_ubicaciones_activas(db: Session = Depends(get_db)):
    hace_5_min = datetime.now() - timedelta(minutes=5)

    mensajeros = db.query(Usuario).filter(
        Usuario.rol == "MENSAJERO",
        Usuario.activo == True,
        Usuario.latitud.isnot(None),
        Usuario.longitud.isnot(None),
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


# --- ACTUALIZACIÓN MASIVA DE LOTE ---
@router.put("/pedidos/actualizacion-masiva")
def actualizacion_masiva(
    body: ActualizacionMasivaRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    if current_user.rol != "MENSAJERO":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado."
        )

    estados_validos = [
        "Registrado", "Pendiente_Recoger", "C-Colectado",
        "En_Bodega", "Pendiente_Entregar", "En_Ruta", "En_Destino",
        "Entregado", "Cancelado", "Devolucion", "Retorno",
        "Rechazado", "Fallido"
    ]
    if body.estado not in estados_validos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Estado '{body.estado}' no es válido."
        )

    actualizados = []
    no_encontrados = []
    rutas_afectadas = set()

    for guia in body.guias:
        # ✅ FIX: busca por mensajero recolector O entregador
        envio = db.query(Envio).filter(
            Envio.numero_guia == guia,
            or_(
                Envio.usuario_mensajero_id == current_user.id_usuario,
                Envio.usuario_mensajero_entrega_id == current_user.id_usuario
            )
        ).first()

        if envio:
            envio.estado = body.estado
            if envio.ruta_id:
                rutas_afectadas.add(envio.ruta_id)
            actualizados.append(guia)
        else:
            no_encontrados.append(guia)

    db.commit()

    rutas_finalizadas = []
    for ruta_id in rutas_afectadas:
        if _verificar_y_auto_finalizar(ruta_id, db):
            rutas_finalizadas.append(ruta_id)

    print(f"[LOTE] Mensajero {current_user.id_usuario} actualizó {len(actualizados)} envío(s) a '{body.estado}'")

    return {
        "ok": True,
        "mensaje": f"{len(actualizados)} envío(s) actualizados a '{body.estado}'.",
        "actualizados": actualizados,
        "no_encontrados": no_encontrados,
        "rutas_finalizadas": rutas_finalizadas
    }


# --- ACTUALIZAR ESTADO SIMPLE (un envío individual) ---
@router.put("/pedidos/{envio_id}/estado")
def actualizar_estado_envio(
    envio_id: int,
    body: ActualizarEstadoRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    estados_validos = [
        "Registrado", "Pendiente_Recoger", "C-Colectado",
        "En_Bodega", "Pendiente_Entregar", "En_Ruta", "En_Destino",
        "Entregado", "Cancelado", "Devolucion", "Retorno",
        "Rechazado", "Fallido"
    ]
    if body.estado not in estados_validos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El estado proporcionado es inválido."
        )

    # ✅ FIX: busca por mensajero recolector O entregador
    envio = db.query(Envio).filter(
        Envio.envio_id == envio_id,
        or_(
            Envio.usuario_mensajero_id == current_user.id_usuario,
            Envio.usuario_mensajero_entrega_id == current_user.id_usuario
        )
    ).first()

    if not envio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Envío no encontrado."
        )

    envio.estado = body.estado
    db.commit()
    db.refresh(envio)

    ruta_finalizada = _verificar_y_auto_finalizar(envio.ruta_id, db)

    return {
        "mensaje": f"Estado del envío actualizado a '{body.estado}' exitosamente.",
        "estado": envio.estado,
        "ruta_finalizada": ruta_finalizada
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Estado de gestión no permitido."
        )

    # ✅ FIX: busca por mensajero recolector O entregador
    envio = db.query(Envio).filter(
        Envio.envio_id == envio_id,
        or_(
            Envio.usuario_mensajero_id == current_user.id_usuario,
            Envio.usuario_mensajero_entrega_id == current_user.id_usuario
        )
    ).first()

    if not envio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Envío no encontrado."
        )

    envio.estado = body.estado
    if body.nombre_receptor:
        nota = f"[ENTREGA] Receptor: {body.nombre_receptor} | Tipo: {body.tipo_receptor}"
        if body.observacion:
            nota += f" | Obs: {body.observacion}"
        envio.instrucciones = nota

    db.commit()
    db.refresh(envio)

    ruta_finalizada = _verificar_y_auto_finalizar(envio.ruta_id, db)

    return {
        "mensaje": f"Gestión de entrega registrada bajo el estado: '{body.estado}'",
        "estado": envio.estado,
        "ruta_finalizada": ruta_finalizada
    }


# --- SUBIR EVIDENCIA (foto de recogida o entrega) ---
@router.post("/pedidos/{envio_id}/evidencia")
async def subir_evidencia(
    envio_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    if current_user.rol != "MENSAJERO":
        raise HTTPException(status_code=403, detail="Solo mensajeros pueden subir fotos")

    # ✅ FIX: busca por mensajero recolector O entregador
    envio = db.query(Envio).filter(
        Envio.envio_id == envio_id,
        or_(
            Envio.usuario_mensajero_id == current_user.id_usuario,
            Envio.usuario_mensajero_entrega_id == current_user.id_usuario
        )
    ).first()
    if not envio:
        raise HTTPException(status_code=404, detail="Envío no encontrado")

    carpeta = "app/static/fotos_recogida"
    os.makedirs(carpeta, exist_ok=True)

    extension = file.filename.rsplit(".", 1)[-1].lower() if file.filename else "jpg"
    if extension not in ["jpg", "jpeg", "png", "webp"]:
        extension = "jpg"

    nombre_archivo = f"{envio.numero_guia}_recogida.{extension}"
    ruta_disco = f"{carpeta}/{nombre_archivo}"

    with open(ruta_disco, "wb") as f:
        shutil.copyfileobj(file.file, f)

    envio.foto_recogida = nombre_archivo
    db.commit()

    return JSONResponse({"ok": True, "foto": nombre_archivo})

# --- SUBIR FOTO DE ENTREGA ---
@router.post("/pedidos/{envio_id}/foto-entrega")
async def subir_foto_entrega(
    envio_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    if current_user.rol != "MENSAJERO":
        raise HTTPException(status_code=403, detail="Solo mensajeros pueden subir fotos")

    envio = db.query(Envio).filter(
        Envio.envio_id == envio_id,
        or_(
            Envio.usuario_mensajero_id == current_user.id_usuario,
            Envio.usuario_mensajero_entrega_id == current_user.id_usuario
        )
    ).first()
    if not envio:
        raise HTTPException(status_code=404, detail="Envío no encontrado")

    carpeta = "app/static/fotos_entrega"
    os.makedirs(carpeta, exist_ok=True)

    extension = file.filename.rsplit(".", 1)[-1].lower() if file.filename else "jpg"
    if extension not in ["jpg", "jpeg", "png", "webp"]:
        extension = "jpg"

    nombre_archivo = f"{envio.numero_guia}_entrega.{extension}"
    with open(f"{carpeta}/{nombre_archivo}", "wb") as f:
        shutil.copyfileobj(file.file, f)

    envio.foto_entrega = nombre_archivo
    db.commit()

    return JSONResponse({"ok": True, "foto": nombre_archivo})

# --- MI RUTA ACTIVA ---
@router.get("/mi-ruta")
def obtener_mi_ruta(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    ruta = db.query(Ruta).filter(
        Ruta.mensajero_id == current_user.id_usuario,
        Ruta.estado.in_(["Creada", "En curso"])
    ).order_by(Ruta.ruta_id.desc()).first()

    if not ruta:
        return {"hay_ruta": False}

    pedidos = db.query(Envio).filter(Envio.ruta_id == ruta.ruta_id).all()

    return {
        "hay_ruta": True,
        "ruta_id": ruta.ruta_id,
        "nombre": ruta.nombre_sector or f"Ruta #{ruta.ruta_id}",
        "estado": ruta.estado,
        "tipo_ruta": ruta.tipo_ruta or "ENTREGA",
        "total_pedidos": len(pedidos),
        "pedidos_pendientes": sum(1 for p in pedidos if p.estado not in {
            "Entregado", "C-Colectado", "Cancelado", "Rechazado", "Fallido"
        }),
    }
