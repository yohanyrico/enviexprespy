# app/controllers/BodegaController.py
import os
from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from datetime import datetime

from app.config.database import get_db
from app.models.Envio import Envio
from app.models.Ruta import Ruta
from app.models.Usuario import Usuario
from app.security.SecurityConfig import get_current_user

router = APIRouter(prefix="/api/bodega", tags=["Bodega"])


# ── SCHEMAS ──────────────────────────────────────────────────────────────────

class RecibirLoteRequest(BaseModel):
    guias: List[str]

class DespacharLoteRequest(BaseModel):
    guias: List[str]


# ── HELPER ───────────────────────────────────────────────────────────────────

def _es_admin(usuario: Usuario) -> bool:
    return usuario.rol in ("CEO", "ADMINISTRATIVO", "ADMIN")


# ==============================================================================
# 1. OBTENER PEDIDOS CON ESTADO "C-Colectado" (PARA RECIBIR EN BODEGA)
# ==============================================================================
@router.get("/pendientes-recibir", response_model=List[Dict[str, Any]])
def listar_pedidos_para_recibir(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene todos los pedidos con estado C-Colectado listos para recibir en bodega"""
    if not _es_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo administradores pueden ver esta lista."
        )

    pedidos = db.query(Envio).filter(Envio.estado == "C-Colectado").all()

    return [
        {
            "id": p.envio_id,
            "guia": p.numero_guia,
            "cliente": f"{p.cliente.nombre} {p.cliente.apellido}" if p.cliente else "N/A",
            "telefono_cliente": p.cliente.telefono if p.cliente else "",
            "direccion_recogida": p.lugar_recogida.direccion if p.lugar_recogida else "Sin dirección",
            "direccion_entrega": p.lugar_entrega.direccion if p.lugar_entrega else "Sin dirección",
            "estado": p.estado,
            "peso": float(p.peso) if p.peso else 0.0,
            "tipo_servicio": p.tipo_servicio or "BASICA",
            "es_cod": p.es_cod or False,
            "valor_a_cobrar": float(p.valor_a_cobrar) if p.valor_a_cobrar else 0.0,
            "mensajero_recogida": p.usuario_mensajero_recogida.nombre if p.usuario_mensajero_recogida else "No asignado",
        }
        for p in pedidos
    ]


# ==============================================================================
# 2. RECIBIR PEDIDOS EN BODEGA (LOTE - POR GUÍAS)
# ==============================================================================
@router.post("/recibir")
def recibir_en_bodega(
    body: RecibirLoteRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    if not _es_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo administradores pueden recibir pedidos en bodega."
        )

    recibidos = []
    no_encontrados = []
    estado_incorrecto = []

    for guia in body.guias:
        envio = db.query(Envio).filter(Envio.numero_guia == guia).first()

        if not envio:
            no_encontrados.append(guia)
            continue

        if envio.estado != "C-Colectado":
            estado_incorrecto.append({
                "guia": guia,
                "estado_actual": envio.estado,
                "mensaje": f"El pedido está en estado '{envio.estado}', no en C-Colectado"
            })
            continue

        envio.estado = "En_Bodega"
        envio.fecha_en_bodega = datetime.now()
        recibidos.append(guia)

    db.commit()

    return {
        "ok": True,
        "mensaje": f"{len(recibidos)} pedido(s) recibidos en bodega.",
        "recibidos": recibidos,
        "no_encontrados": no_encontrados,
        "estado_incorrecto": estado_incorrecto
    }


# ==============================================================================
# 3. RECIBIR PEDIDO INDIVIDUAL EN BODEGA (POR ID)
# ==============================================================================
@router.put("/recibir-individual/{envio_id}")
def recibir_pedido_individual(
    envio_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    if not _es_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo administradores pueden recibir pedidos."
        )

    envio = db.query(Envio).filter(Envio.envio_id == envio_id).first()
    if not envio:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")

    if envio.estado != "C-Colectado":
        raise HTTPException(
            status_code=400,
            detail=f"El pedido está en estado '{envio.estado}', no se puede recibir. Solo se reciben pedidos en estado 'C-Colectado'."
        )

    envio.estado = "En_Bodega"
    envio.fecha_en_bodega = datetime.now()
    db.commit()

    return {
        "ok": True,
        "mensaje": f"Pedido {envio.numero_guia} recibido en bodega correctamente.",
        "pedido": {
            "id": envio.envio_id,
            "guia": envio.numero_guia,
            "estado": envio.estado
        }
    }


# ==============================================================================
# 4. LISTAR PEDIDOS EN BODEGA (ESTADO "En_Bodega")
# ==============================================================================
@router.get("/pendientes", response_model=List[Dict[str, Any]])
def listar_pedidos_bodega(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    if not _es_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado."
        )

    pedidos = db.query(Envio).filter(Envio.estado == "En_Bodega").all()

    return [
        {
            "id": p.envio_id,
            "guia": p.numero_guia,
            "cliente": f"{p.cliente.nombre} {p.cliente.apellido}" if p.cliente else "N/A",
            "telefono_cliente": p.cliente.telefono if p.cliente else "",
            "direccion_entrega": p.lugar_entrega.direccion if p.lugar_entrega else "Sin dirección",
            "ciudad_destino": p.lugar_entrega.ciudad if p.lugar_entrega else "",
            "estado": p.estado,
            "peso": float(p.peso) if p.peso else 0.0,
            "tipo_servicio": p.tipo_servicio or "BASICA",
            "es_cod": p.es_cod or False,
            "valor_a_cobrar": float(p.valor_a_cobrar) if p.valor_a_cobrar else 0.0,
        }
        for p in pedidos
    ]


# ==============================================================================
# 5. DESPACHAR PEDIDOS DE BODEGA (Mensajero escanea → En_Ruta)
# ==============================================================================
@router.post("/despachar")
def despachar_de_bodega(
    body: DespacharLoteRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    if current_user.rol not in ("MENSAJERO", "CEO", "ADMINISTRATIVO", "ADMIN"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para despachar pedidos."
        )

    despachados = []
    no_encontrados = []
    estado_incorrecto = []

    for guia in body.guias:
        envio = db.query(Envio).filter(Envio.numero_guia == guia).first()

        if not envio:
            no_encontrados.append(guia)
            continue

        if envio.estado not in ("En_Bodega", "Pendiente_Verificar"):
            estado_incorrecto.append({
                "guia": guia,
                "estado_actual": envio.estado,
                "mensaje": f"El pedido está en estado '{envio.estado}', no se puede despachar."
            })
            continue

        envio.estado = "En_Ruta"
        envio.fecha_en_ruta = datetime.now()

        if current_user.rol == "MENSAJERO":
            envio.usuario_mensajero_entrega_id = current_user.id_usuario

        despachados.append(guia)

    db.commit()

    return {
        "ok": True,
        "mensaje": f"{len(despachados)} pedido(s) despachados a En_Ruta.",
        "despachados": despachados,
        "no_encontrados": no_encontrados,
        "estado_incorrecto": estado_incorrecto
    }


# ==============================================================================
# 6. RESUMEN DE BODEGA (Conteos por estado)
# ==============================================================================
@router.get("/resumen")
def resumen_bodega(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    if not _es_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acceso denegado.")

    en_bodega        = db.query(Envio).filter(Envio.estado == "En_Bodega").count()
    c_colectado      = db.query(Envio).filter(Envio.estado == "C-Colectado").count()
    pend_verificar   = db.query(Envio).filter(Envio.estado == "Pendiente_Verificar").count()
    en_ruta          = db.query(Envio).filter(Envio.estado == "En_Ruta").count()

    return {
        "c_colectado": c_colectado,
        "en_bodega": en_bodega,
        "pendiente_verificar": pend_verificar,
        "en_ruta": en_ruta,
    }