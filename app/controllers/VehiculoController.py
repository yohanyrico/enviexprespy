from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.Vehiculo import Vehiculo
from app.models.Tipo import Tipo
# Mantenemos las importaciones por compatibilidad futura
from app.security.SecurityConfig import get_current_user, require_admin
import app.repositories.VehiculoRepository as vehiculo_repo
from app.config.templates import templates

router = APIRouter(prefix="/vehiculos", tags=["Vehículos"])

@router.get("/")
def listar(request: Request, db: Session = Depends(get_db)):
    # SE QUITÓ: current_user=Depends(get_current_user) y require_admin(current_user)
    return templates.TemplateResponse("vehiculos.html", {
        "request": request,
        "vehiculos": vehiculo_repo.find_all(db)
    })

@router.get("/nuevo")
def nuevo(request: Request):
    # SE QUITÓ: restricción de seguridad
    return templates.TemplateResponse("form-vehiculo.html", {
        "request": request,
        "vehiculo": None,
        "tipos": [t.value for t in Tipo]
    })

@router.post("/guardar")
async def guardar(request: Request, db: Session = Depends(get_db)):
    # SE QUITÓ: restricción de seguridad
    form = await request.form()
    vehiculo_id = form.get("vehiculo_id")

    if vehiculo_id:
        vehiculo = vehiculo_repo.find_by_id(db, int(vehiculo_id))
        if not vehiculo:
            raise HTTPException(status_code=404, detail="Vehículo no encontrado")
    else:
        vehiculo = Vehiculo()

    vehiculo.placa = form.get("placa")
    vehiculo.tipo = form.get("tipo")
    vehiculo.capacidad_kg = float(form.get("capacidad_kg", 0))
    vehiculo_repo.save(db, vehiculo)
    return RedirectResponse(url="/vehiculos", status_code=302)

@router.get("/editar/{id}")
def editar(id: int, request: Request, db: Session = Depends(get_db)):
    # SE QUITÓ: restricción de seguridad
    vehiculo = vehiculo_repo.find_by_id(db, id)
    if not vehiculo:
        raise HTTPException(status_code=404, detail=f"Vehículo no encontrado: {id}")
    return templates.TemplateResponse("form-vehiculo.html", {
        "request": request,
        "vehiculo": vehiculo,
        "tipos": [t.value for t in Tipo]
    })

@router.get("/eliminar/{id}")
def eliminar(id: int, db: Session = Depends(get_db)):
    # SE QUITÓ: restricción de seguridad
    vehiculo = vehiculo_repo.find_by_id(db, id)
    if not vehiculo:
        raise HTTPException(status_code=404, detail="Vehículo no encontrado")
    vehiculo_repo.delete(db, vehiculo)
    return RedirectResponse(url="/vehiculos", status_code=302)