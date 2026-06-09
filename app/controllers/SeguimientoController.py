# app/controllers/SeguimientoController.py

from fastapi import APIRouter, Query, Request, Depends
from typing import Optional
from sqlalchemy.orm import Session, joinedload
from app.config.database import get_db
from app.models.Envio import Envio
from app.models.Usuario import Usuario
from app.config.templates import templates

router = APIRouter(tags=["Seguimiento"])


@router.get("/seguimiento")
def seguimiento(
    request: Request,
    numero_guia: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Punto de entrada para el rastreo público o privado de guías.
    Si no hay guía, renderiza la vista limpia con el formulario de búsqueda.
    """
    if numero_guia and numero_guia.strip():
        return _buscar(request, numero_guia, db)
        
    return templates.TemplateResponse("seguimiento.html", {
        "request": request,
        "encontrado": None,
        "numero_guia": None,
        "puede_ver_foto": False
    })


def _buscar(request, numero_guia, db):
    """
    Procesa la limpieza del string de la guía, realiza un query optimizado 
    con precarga (joinedload) y gestiona los permisos de visualización de fotos.
    """
    # Limpieza rigurosa de caracteres y espacios para evitar fallos de tipeo del usuario
    guia_limpia = (
        numero_guia.strip().upper()
        .replace("–", "-").replace("—", "-").replace(" ", "")
    )

    # Consulta optimizada trayendo todas las relaciones de una sola vez
    envio = (
        db.query(Envio)
        .options(
            joinedload(Envio.seguimientos),
            joinedload(Envio.mensajero),
            joinedload(Envio.lugar_recogida),
            joinedload(Envio.lugar_entrega),
            joinedload(Envio.ruta),
        )
        .filter(Envio.numero_guia == guia_limpia)
        .first()
    )

    # Si la guía no existe en el sistema
    if not envio:
        return templates.TemplateResponse("seguimiento.html", {
            "request": request,
            "encontrado": False,
            "numero_guia": numero_guia,
            "puede_ver_foto": False,
            "mensaje": f"No se encontró ningún envío con el número de guía: {numero_guia}"
        })

    # ── ¿El cliente autenticado es dueño de este envío para ver la prueba multimedia? ──
    puede_ver_foto = False
    user_id = request.session.get("user_id")
    
    if user_id:
        usuario = db.query(Usuario).filter(Usuario.id_usuario == user_id).first()
        if usuario and usuario.rol == "CLIENTE":
            # Cambia 'usuario_cliente_id' si tu llave foránea en Envio se llama diferente
            puede_ver_foto = (envio.usuario_cliente_id == usuario.id_usuario)
        elif usuario and usuario.rol in ["ADMINISTRADOR", "OPERADOR", "MENSAJERO"]:
            # Opcional: Permitir que el staff de EnviExpress también pueda validar la foto
            puede_ver_foto = True

    # Retorna la información completa para poblar la barra y la línea de tiempo vertical
    return templates.TemplateResponse("seguimiento.html", {
        "request": request,
        "envio": envio,
        "encontrado": True,
        "numero_guia": numero_guia,
        "puede_ver_foto": puede_ver_foto
    })