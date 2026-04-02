from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from decimal import Decimal

from app.config.database import get_db
from app.models.Tarifa import Tarifa
from app.security.SecurityConfig import get_current_user, require_admin
import app.repositories.TarifaRepository as tarifa_repo
from app.config.templates import templates

router = APIRouter(prefix="/tarifas", tags=["Tarifas"])


@router.get("/")
def listar(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    require_admin(current_user)
    tarifas = tarifa_repo.find_all(db)
    
    # DEBUG: Esto imprimirá en tu consola los nombres reales que vienen de la BD
    for t in tarifas:
        print(f"Tarifa cargada: ID={t.id}, Nombre={t.nombre}")
        
    return templates.TemplateResponse("tarifas.html", {
        "request": request,
        "tarifas": tarifas
    })

@router.get("/nueva")
def nueva(request: Request, current_user=Depends(get_current_user)):
    require_admin(current_user)
    return templates.TemplateResponse("tarifas-form.html", {
        "request": request,
        "tarifa": None
    })

@router.post("/guardar")
async def guardar(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    require_admin(current_user)
    form = await request.form()
    id_tarifa = form.get("id")

    if id_tarifa:
        tarifa = tarifa_repo.find_by_id(db, int(id_tarifa))
        if not tarifa:
            raise HTTPException(status_code=404, detail="Tarifa no encontrada")
    else:
        tarifa = Tarifa()

    # CAMBIO CRÍTICO: Usamos 'nombre' que es como está en tu Modelo y Base de Datos
    # Obtenemos el valor del input 'nombre' o 'tipo' del formulario para mayor seguridad
    nombre_form = form.get("nombre") or form.get("tipo") or "Sin Nombre"
    
    tarifa.nombre = nombre_form
    tarifa.precio_kg = Decimal(form.get("precio_kg", "0"))
    
    tarifa_repo.save(db, tarifa)
    return RedirectResponse(url="/tarifas", status_code=302)

@router.get("/editar/{id}")
def editar(id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    require_admin(current_user)
    tarifa = tarifa_repo.find_by_id(db, id)
    if not tarifa:
        raise HTTPException(status_code=404, detail=f"Tarifa no encontrada: {id}")
    return templates.TemplateResponse("tarifas-form.html", {
        "request": request,
        "tarifa": tarifa
    })

@router.get("/eliminar/{id}")
def eliminar(id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    require_admin(current_user)
    tarifa = tarifa_repo.find_by_id(db, id)
    if not tarifa:
        raise HTTPException(status_code=404, detail="Tarifa no encontrada")
    tarifa_repo.delete(db, tarifa)
    return RedirectResponse(url="/tarifas", status_code=302)