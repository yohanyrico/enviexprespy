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
    guias: List[str]  # Números de guía escaneados

class DespacharLoteRequest(BaseModel):
    guias: List[str]  # Números de guía escaneados antes de salir


# ── HELPER ───────────────────────────────────────────────────────────────────

def _es_admin(usuario: Usuario) -> bool:
    return usuario.rol in ("CEO", "ADMINISTRATIVO", "ADMIN")


# ── ENDPOINTS ────────────────────────────────────────────────────────────────

# --- 1. RECIBIR PEDIDOS EN BODEGA (Admin escanea lo que trajo el mensajero) ---
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

        # Solo se pueden recibir pedidos que vienen de recolección
        if envio.estado != "C-Colectado":
            estado_incorrecto.append({
                "guia": guia,
                "estado_actual": envio.estado,
                "mensaje": f"El pedido está en estado '{envio.estado}', no en C-Colectado"
            })
            continue

        envio.estado = "En_Bodega"
        recibidos.append(guia)

    db.commit()

    print(f"[BODEGA] Admin {current_user.id_usuario} recibió {len(recibidos)} pedido(s) en bodega.")

    return {
        "ok": True,
        "mensaje": f"{len(recibidos)} pedido(s) recibidos en bodega.",
        "recibidos": recibidos,
        "no_encontrados": no_encontrados,
        "estado_incorrecto": estado_incorrecto
    }


# --- 2. LISTAR PEDIDOS EN BODEGA ---
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

    pedidos = db.query(Envio).filter(
        Envio.estado == "En_Bodega"
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
            "peso": float(p.peso) if p.peso else 0.0,
            "tipo_servicio": p.tipo_servicio or "BASICA",
            "es_cod": p.es_cod or False,
            "valor_a_cobrar": float(p.valor_a_cobrar) if p.valor_a_cobrar else 0.0,
        }
        for p in pedidos
    ]


# --- 3. DESPACHAR PEDIDOS DE BODEGA (Mensajero escanea antes de salir → En_Ruta) ---
@router.post("/despachar")
def despachar_de_bodega(
    body: DespacharLoteRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    # Tanto mensajero como admin pueden despachar
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

        # Solo se pueden despachar pedidos en bodega o pendientes de verificar
        if envio.estado not in ("En_Bodega", "Pendiente_Verificar"):
            estado_incorrecto.append({
                "guia": guia,
                "estado_actual": envio.estado,
                "mensaje": f"El pedido está en estado '{envio.estado}', no se puede despachar."
            })
            continue

        envio.estado = "En_Ruta"

        # Si el mensajero que despacha es el entregador asignado, lo registramos
        if current_user.rol == "MENSAJERO":
            envio.usuario_mensajero_entrega_id = current_user.id_usuario

        despachados.append(guia)

    db.commit()

    print(f"[BODEGA] Usuario {current_user.id_usuario} ({current_user.rol}) despachó {len(despachados)} pedido(s).")

    return {
        "ok": True,
        "mensaje": f"{len(despachados)} pedido(s) despachados a En_Ruta.",
        "despachados": despachados,
        "no_encontrados": no_encontrados,
        "estado_incorrecto": estado_incorrecto
    }


# --- 4. RESUMEN DE BODEGA (Conteos por estado) ---
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
        "c_colectado": c_colectado,        # Vienen en camino a bodega
        "en_bodega": en_bodega,            # Ya están en bodega
        "pendiente_verificar": pend_verificar,  # Asignados pero no despachados
        "en_ruta": en_ruta,                # Ya salieron a entregar
    }