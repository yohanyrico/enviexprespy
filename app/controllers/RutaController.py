import os
import json
from fastapi import APIRouter, Request, Depends, Body, Query, HTTPException, status
from fastapi.templating import Jinja2Templates
from starlette.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload
from app.config.database import get_db
from app.config.database import SessionLocal
from app.models.Envio import Envio
from app.models.Ruta import Ruta
from app.models.Usuario import Usuario
from sqlalchemy import text
from typing import Optional, List
from pydantic import BaseModel

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "..", "templates"))

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ─────────────────────────────────────────────
# ESQUEMA PYDANTIC PARA RECEPCIÓN DE DATOS EN CAMBIO DE ESTADO
# ─────────────────────────────────────────────
class CambiarEstadoRequest(BaseModel):
    envio_ids: Optional[List[int]] = None
    ruta_id: int
    estado: str

# ─────────────────────────────────────────────
# HELPER: agrupa rutas por estado (BLINDADO CONTRA ENUMS VACÍOS)
# ─────────────────────────────────────────────

def _get_rutas_por_estado(db: Session):
    try:
        rutas = db.query(Ruta).options(
            joinedload(Ruta.mensajero),
            joinedload(Ruta.envios)
        ).all()
        
    except Exception as e:
        db.rollback()
        print(f"🛡️ Bypass activado en _get_rutas_por_estado por registro corrupto: {e}")
        
        query = text("""
            SELECT r.*, 
                   m.nombre as mensajero_nombre, m.apellido as mensajero_apellido
            FROM rutas r
            LEFT JOIN usuario m ON r.mensajero_id = m.id_usuario
            ORDER BY r.ruta_id DESC
        """)
        resultado = db.execute(query).fetchall()
        
        rutas = []
        for row in resultado:
            row_dict = row._asdict() if hasattr(row, '_asdict') else dict(row._mapping)
            
            est_ruta = row_dict.get("estado")
            estado_seguro = est_ruta if (est_ruta and est_ruta.strip()) else "Creada"
            
            class RutaSimulada:
                def __init__(self, d):
                    self.ruta_id = d.get("ruta_id")
                    self.nombre_sector = d.get("nombre_sector")
                    self.ciudad = d.get("ciudad") or "Bogotá"
                    self.mensajero_id = d.get("mensajero_id")
                    self.estado = estado_seguro
                    self.fecha_creacion = d.get("fecha_creacion")
                    self.envios = []
                    
                    if d.get("mensajero_id"):
                        self.mensajero = type('MensajeroSim', (), {
                            'id_usuario': d.get("mensajero_id"),
                            'nombre': d.get("mensajero_nombre") or "Mensajero",
                            'apellido': d.get("mensajero_apellido") or ""
                        })
                    else:
                        self.mensajero = None
            
            rutas.append(RutaSimulada(row_dict))

    return {
        "creadas":     [r for r in rutas if r.estado == "Creada"],
        "en_curso":    [r for r in rutas if r.estado in ["En curso", "En_Curso", "En_Ruta"]],
        "finalizadas": [r for r in rutas if r.estado in ["Finalizada", "Finalizadas"]],
    }


# ─────────────────────────────────────────────
# HELPER: construye la lista de puntos del mapa de forma segura
# Usa json.dumps para evitar que caracteres especiales en direcciones
# (comillas, tildes, #, &, etc.) rompan el bloque <script> en el template.
# ─────────────────────────────────────────────
ESTADOS_EXCLUIR_MAPA = {
    'Entregado', 'Cancelado', 'Rechazado', 'Devolucion', 'Retorno', 'Fallido'
}

def _build_envios_json(envios: list) -> str:
    puntos = []
    for e in envios:
        if e.estado in ESTADOS_EXCLUIR_MAPA:
            continue

        # Punto C — recogida
        rec = e.lugar_recogida
        if rec and rec.latitud and rec.longitud:
            puntos.append({
                "tipo":      "c",
                "lat":       float(rec.latitud),
                "lng":       float(rec.longitud),
                "envioId":   e.envio_id,
                "guia":      e.numero_guia or "",
                "estado":    e.estado or "",
                "fecha":     e.fecha_creacion.strftime('%Y-%m-%d') if e.fecha_creacion else "",
                "direccion": rec.direccion or "",
            })

        # Punto D — entrega
        ent = e.lugar_entrega
        if ent and ent.latitud and ent.longitud:
            puntos.append({
                "tipo":      "d",
                "lat":       float(ent.latitud),
                "lng":       float(ent.longitud),
                "envioId":   e.envio_id,
                "guia":      e.numero_guia or "",
                "estado":    e.estado or "",
                "fecha":     e.fecha_creacion.strftime('%Y-%m-%d') if e.fecha_creacion else "",
                "direccion": ent.direccion or "",
            })

    return json.dumps(puntos, ensure_ascii=False)


# ─────────────────────────────────────────────
# MAPA OPERATIVO - CONTROL INTEGRAL DE RECOGIDA Y ENTREGA
# ─────────────────────────────────────────────
@router.get("/rutas", response_class=HTMLResponse)
@router.get("/rutas/mapa-operaciones", response_class=HTMLResponse)
@router.get("/mapa-operaciones", response_class=HTMLResponse)
@router.api_route("/envios/planificar-ruta", methods=["GET", "POST"], response_class=HTMLResponse)
async def planificar_ruta(
    request: Request, 
    origen_id: Optional[int] = Query(None),
    destino_id: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    try:
        envios_db = db.query(Envio).filter(
            Envio.estado.in_([
                "Registrado",
                "Pendiente_Recoger",
                "C-Colectado",
                "En_Bodega",
                "Pendiente_Entregar",
                "En_Ruta",
                "En_Destino",
                "Entregado",
                "Cancelado",
                "Rechazado",
                "Devolucion",
                "Retorno",
                "Fallido"
            ])
        ).options(
            joinedload(Envio.lugar_recogida),
            joinedload(Envio.lugar_entrega)
        ).all()

        envios = []
        for e in envios_db:
            if e.envio_id == origen_id:
                e.tipo_marcador = "P"
            elif e.envio_id == destino_id:
                e.tipo_marcador = "D"
            else:
                e.tipo_marcador = None
            envios.append(e)
        
    except Exception as e:
        db.rollback()
        print(f"🛡️ Bypass activado en planificar_ruta (Envios) por registro corrupto: {e}")
        
        query_envios = text("""
            SELECT e.*, 
                   lr.direccion as rec_dir, lr.latitud as rec_lat, lr.longitud as rec_lng, lr.ciudad as rec_ciu,
                   le.direccion as ent_dir, le.latitud as ent_lat, le.longitud as ent_lng, le.ciudad as ent_ciu
            FROM envios e
            LEFT JOIN lugares lr ON e.lugar_recogida_id = lr.lugar_id
            LEFT JOIN lugares le ON e.lugar_entrega_id = le.lugar_id
            WHERE e.estado NOT IN ('Entregado', 'Cancelado', 'Rechazado', 'Devolucion', 'Retorno', 'Fallido')
        """)
        resultado_envios = db.execute(query_envios).fetchall()
        
        envios = []
        for row in resultado_envios:
            row_dict = row._asdict() if hasattr(row, '_asdict') else dict(row._mapping)
            
            est_envio = row_dict.get("estado")
            estado_envio_seguro = est_envio if (est_envio and est_envio.strip()) else "Registrado"
            
            class EnvioMapaSimulado:
                def __init__(self, d, es_origen, es_destino):
                    self.envio_id = d.get("envio_id")
                    self.numero_guia = d.get("numero_guia")
                    self.estado = estado_envio_seguro
                    self.ruta_id = d.get("ruta_id")
                    self.usuario_cliente_id = d.get("usuario_cliente_id")
                    self.usuario_mensajero_id = d.get("usuario_mensajero_id")
                    self.usuario_mensajero_entrega_id = d.get("usuario_mensajero_entrega_id")
                    self.estado_recogida = d.get("estado_recogida") or "Pendiente"
                    self.estado_entrega = d.get("estado_entrega") or "Pendiente"
                    self.fecha_creacion = d.get("fecha_creacion")
                    
                    if es_origen:
                        self.tipo_marcador = "P"
                    elif es_destino:
                        self.tipo_marcador = "D"
                    else:
                        self.tipo_marcador = None
                    
                    self.lugar_recogida = type('LugRec', (), {
                        'direccion': d.get("rec_dir") or "",
                        'ciudad':    d.get("rec_ciu") or "Bogotá",
                        'latitud':   d.get("rec_lat"),
                        'longitud':  d.get("rec_lng"),
                    })
                    self.lugar_entrega = type('LugEnt', (), {
                        'direccion': d.get("ent_dir") or "",
                        'ciudad':    d.get("ent_ciu") or "Bogotá",
                        'latitud':   d.get("ent_lat"),
                        'longitud':  d.get("ent_lng"),
                    })
            
            es_origen  = (row_dict.get("envio_id") == origen_id)
            es_destino = (row_dict.get("envio_id") == destino_id)
            envios.append(EnvioMapaSimulado(row_dict, es_origen, es_destino))

    mensajeros  = db.query(Usuario).filter(Usuario.rol == "MENSAJERO").all()
    rutas       = _get_rutas_por_estado(db)
    rol         = request.session.get("rol")

    # ── FIX CRÍTICO: serializar envíos con json.dumps para evitar
    #    que caracteres especiales en direcciones rompan el JS ──
    envios_json = _build_envios_json(envios)
    print(f"DEBUG envios_json tiene {len(json.loads(envios_json))} puntos") 

    return templates.TemplateResponse("mapa-operaciones.html", {
        "request":           request,
        "envios":            envios,       # sigue disponible para el HTML de rutas
        "envios_json":       envios_json,  # ← NUEVO: usado por enviosData en el mapa
        "mensajeros":        mensajeros,
        "rutas_creadas":     rutas["creadas"],
        "rutas_en_curso":    rutas["en_curso"],
        "rutas_finalizadas": rutas["finalizadas"],
        "rol":               rol,
        "origen_id":         origen_id,
        "destino_id":        destino_id,
    })


# ─────────────────────────────────────────────
# CAMBIO DE ESTADO Y AUTOMATIZACIÓN DE RUTAS
# ─────────────────────────────────────────────
@router.post("/cambiar-estado")
@router.post("/rutas/cambiar-estado")
async def cambiar_estado_ruta(payload: CambiarEstadoRequest, db: Session = Depends(get_db)):
    ruta = db.query(Ruta).filter(Ruta.ruta_id == payload.ruta_id).first()
    if not ruta:
        raise HTTPException(status_code=404, detail="Ruta no encontrada en el sistema")

    if payload.estado == "QUITAR_PEDIDOS":
        if payload.envio_ids:
            db.query(Envio).filter(
                Envio.envio_id.in_(payload.envio_ids),
                Envio.ruta_id == payload.ruta_id
            ).update({"estado": "Registrado", "ruta_id": None}, synchronize_session=False)
            db.commit()

        envios_restantes = db.query(Envio).filter(Envio.ruta_id == payload.ruta_id).count()

        if envios_restantes == 0:
            db.delete(ruta)
            db.commit()
            return {
                "status": "success",
                "action": "ruta_eliminada",
                "message": "Se quitaron los pedidos. Como la ruta quedó vacía, fue eliminada del sistema."
            }

        return {"status": "success", "action": "pedidos_quitados", "message": "Pedidos removidos de la ruta con éxito."}

    elif payload.estado in ["Finalizada", "Finalizadas", "En curso", "Creada"]:
        ruta.estado = payload.estado
        db.commit()

        if payload.estado in ["Finalizada", "Finalizadas"]:
            db.query(Envio).filter(Envio.ruta_id == payload.ruta_id).update(
                {"estado": "Entregado"},
                synchronize_session=False
            )
            db.commit()

        return {
            "status": "success",
            "action": "estado_actualizado",
            "message": f"Ruta actualizada a: {payload.estado}"
        }

    raise HTTPException(status_code=400, detail="El estado provisto no es reconocido o válido.")