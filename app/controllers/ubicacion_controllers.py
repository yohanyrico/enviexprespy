from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional
from app.config.database import get_db
from app.models.Usuario import Usuario
from app.models.Ruta import Ruta

router = APIRouter(prefix="/api/mensajero", tags=["Ubicaciones"])

class UbicacionRequest(BaseModel):
    latitud: float
    longitud: float

class MensajeroUbicacion(BaseModel):
    id: int
    nombre: str
    lat: float
    lng: float


@router.post("/actualizar-ubicacion/{mensajero_id}")
async def actualizar_ubicacion(
    mensajero_id: int,
    data: UbicacionRequest,
    db: Session = Depends(get_db)
):
    """El mensajero envía su ubicación desde la app Flutter"""
    
    usuario = db.query(Usuario).filter(
        Usuario.id_usuario == mensajero_id,
        Usuario.rol == "MENSAJERO"
    ).first()
    
    if not usuario:
        raise HTTPException(status_code=404, detail="Mensajero no encontrado")
    
    usuario.latitud = data.latitud
    usuario.longitud = data.longitud
    usuario.ultima_ubicacion = datetime.now()
    
    db.commit()
    
    return {"status": "ok", "message": "Ubicación actualizada"}


@router.get("/ubicaciones-activas", response_model=List[MensajeroUbicacion])
async def obtener_mensajeros_activos(db: Session = Depends(get_db)):
    """Devuelve mensajeros con rutas EN CURSO para mostrar en el mapa"""
    
    # Buscar mensajeros con rutas en curso
    rutas_activas = db.query(Ruta).filter(
        Ruta.estado.in_(["En curso", "En_Curso", "En_Ruta"])
    ).all()
    
    mensajeros_ids = list(set([r.mensajero_id for r in rutas_activas if r.mensajero_id]))
    
    if not mensajeros_ids:
        return []
    
    mensajeros = db.query(Usuario).filter(
        Usuario.id_usuario.in_(mensajeros_ids)
    ).all()
    
    resultado = []
    for m in mensajeros:
        # Si tiene ubicación guardada, úsala
        if m.latitud and m.longitud:
            lat = float(m.latitud)
            lng = float(m.longitud)
        else:
            # Coordenadas por defecto (Bogotá)
            lat = 4.65
            lng = -74.10
        
        resultado.append({
            "id": m.id_usuario,
            "nombre": f"{m.nombre} {m.apellido}",
            "lat": lat,
            "lng": lng
        })
    
    return resultado