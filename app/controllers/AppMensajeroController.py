# app/controllers/AppMensajeroController.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.models.Envio import Envio
from app.models.Usuario import Usuario
# ESTA LÍNEA ES LA QUE TE DA EL ERROR SI FALTA:
from app.security.SecurityConfig import get_current_user

router = APIRouter(prefix="/api/mensajero", tags=["App Mensajero"])

@router.get("/pedidos-pendientes")
def obtener_pedidos_app(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    try:
        # Buscamos los envíos asignados al mensajero logueado
        pedidos = db.query(Envio).filter(
            Envio.usuario_mensajero_id == current_user.id_usuario,
            Envio.estado != "Entregado"
        ).all()

        return [
            {
                "id": p.envio_id,
                "guia": p.numero_guia,
                "cliente": f"{p.cliente.nombre} {p.cliente.apellido}" if p.cliente else "N/A",
                "direccion_entrega": p.lugar_entrega.direccion if p.lugar_entrega else "Sin dirección",
                "estado": p.estado,
                "instrucciones": p.instrucciones or "",
                # Latitud y longitud que agregamos
                "latitud": p.lugar_entrega.latitud if p.lugar_entrega else None,
                "longitud": p.lugar_entrega.longitud if p.lugar_entrega else None,
            } for p in pedidos
        ]
    except Exception as e:
        print(f"Error en el controlador: {e}")
        raise HTTPException(status_code=500, detail=str(e))