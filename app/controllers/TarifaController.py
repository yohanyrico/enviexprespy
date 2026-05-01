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

# --- VISTAS DEL ADMINISTRADOR ---

@router.get("/")
def listar(request: Request, db: Session = Depends(get_db)):
    tarifas = tarifa_repo.find_all(db)
    
    # DEBUG: Verificamos en consola que precio_plan tenga datos
    for t in tarifas:
        print(f"Tarifa: {t.nombre} | Plan: {t.precio_plan} | Envíos: {t.envios_incluidos}")
        
    return templates.TemplateResponse("tarifas.html", {
        "request": request,
        "tarifas": tarifas
    })

@router.get("/nueva")
def nueva(request: Request):
    return templates.TemplateResponse("tarifas-form.html", {
        "request": request,
        "tarifa": None
    })

@router.post("/guardar")
async def guardar(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    id_tarifa = form.get("id")

    # 1. Buscar o crear instancia
    if id_tarifa and id_tarifa.strip():
        tarifa = tarifa_repo.find_by_id(db, int(id_tarifa))
        if not tarifa:
            tarifa = Tarifa()
    else:
        tarifa = Tarifa()

    # 2. Función interna para limpiar puntos de miles y decimales
    def limpiar_monto(valor):
        if not valor: return Decimal("0")
        # Quitamos puntos de miles, espacios y símbolo de peso
        limpio = str(valor).replace(".", "").replace("$", "").replace(",", "").strip()
        return Decimal(limpio) if limpio else Decimal("0")

    # 3. ASIGNACIÓN DE DATOS (IMPORTANTE: nombres coinciden con HTML)
    tarifa.nombre = form.get("nombre")
    
    # Cambiamos "valor_envio" por "precio_plan" para que coincida con el formulario
    tarifa.precio_plan = limpiar_monto(form.get("precio_plan"))
    
    tarifa.envios_incluidos = int(form.get("envios_incluidos", "0"))
    tarifa.descripcion = form.get("descripcion", "")

    # 4. Guardar en DB
    try:
        tarifa_repo.save(db, tarifa) 
    except Exception as e:
        print(f"Error al guardar: {e}")
        raise HTTPException(status_code=500, detail="Error al guardar la tarifa")
    
    return RedirectResponse(url="/tarifas", status_code=302)

@router.get("/editar/{id}")
def editar(id: int, request: Request, db: Session = Depends(get_db)):
    tarifa = tarifa_repo.find_by_id(db, id)
    if not tarifa:
        raise HTTPException(status_code=404, detail=f"Tarifa no encontrada: {id}")
    return templates.TemplateResponse("tarifas-form.html", {
        "request": request,
        "tarifa": tarifa
    })

@router.get("/eliminar/{id}")
def eliminar(id: int, db: Session = Depends(get_db)):
    tarifa = tarifa_repo.find_by_id(db, id)
    if not tarifa:
        raise HTTPException(status_code=404, detail="Tarifa no encontrada")
    tarifa_repo.delete(db, tarifa)
    return RedirectResponse(url="/tarifas", status_code=302)

# --- RUTA PARA EL CLIENTE (CONEXIÓN PANEL DE PAGO) ---

@router.get("/api/detalle/{nombre}")
def obtener_detalle_para_pago(nombre: str, db: Session = Depends(get_db)):
    tarifa = db.query(Tarifa).filter(Tarifa.nombre == nombre).first()
    
    if not tarifa:
        raise HTTPException(status_code=404, detail="Tarifa no encontrada")
        
    return {
        "id": tarifa.id,
        "nombre": tarifa.nombre,
        "precio_unitario": float(tarifa.precio_plan or 0),
        "envios": tarifa.envios_incluidos or 0,
        "total": float((tarifa.precio_plan or 0) * (tarifa.envios_incluidos or 0)),
        "descripcion": tarifa.descripcion
    }