from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.config.database import get_db # Ajustado a tu config
from app.repositories.inventario_repository import InventarioRepository
from app.models.inventario import InventarioProducto
from app.models.Usuario import Usuario

router = APIRouter(prefix="/inventario", tags=["Inventario"])

# Configuración para renderizar las plantillas HTML de tu carpeta templates
templates = Jinja2Templates(directory="templates")

# ==========================================
#      ENDPOINTS API (DATOS RAW / JSON)
# ==========================================

@router.get("/cliente/{cliente_id}")
def listar_inventario(cliente_id: int, db: Session = Depends(get_db)):
    repo = InventarioRepository(db)
    return repo.obtener_por_cliente(cliente_id)

@router.post("/abastecer/{cliente_id}")
def abastecer_stock(cliente_id: int, data: dict, db: Session = Depends(get_db)):
    repo = InventarioRepository(db)
    producto = repo.buscar_por_sku(cliente_id, data['sku'])
    
    if producto:
        producto.stock_disponible += data['cantidad']
    else:
        producto = InventarioProducto(
            cliente_id=cliente_id,
            sku=data['sku'],
            nombre=data['nombre'],
            stock_disponible=data['cantidad'],
            ubicacion_bodega=data.get('ubicacion')
        )
        repo.guardar_producto(producto)
    
    db.commit()
    return {"message": "Stock actualizado", "nuevo_total": producto.stock_disponible}


# ==========================================
#      VISTA WEB (RENDEREAR JINJA2 / HTML)
# ==========================================

@router.get("/web", response_class=HTMLResponse)
def ver_inventario_web(request: Request, db: Session = Depends(get_db)):
    """
    Esta ruta responde al botón 'Ver Stock' de tu Panel de Cliente.
    Extrae la información de la base de datos en Render y la pinta en el HTML.
    """
    repo = InventarioRepository(db)
    
    # NOTA LOGÍSTICA: Aquí deberías capturar el ID del cliente real desde la sesión o cookies.
    # Por ahora, usamos el ID 1 de prueba para asegurar que traiga datos de PostgreSQL.
    cliente_id_simulado = 1 
    
    # Buscamos los productos asociados en la BD
    productos = repo.obtener_por_cliente(cliente_id_simulado)
    
    # Enviamos los datos ordenados al archivo inventario.html dentro de tus templates
    return templates.TemplateResponse(
        "inventario.html", 
        {
            "request": request, 
            "productos": productos, 
            "cliente_id": cliente_id_simulado
        }
    )
@router.get("/admin", response_class=HTMLResponse)
def inventario_admin(
    request: Request,
    cliente_id: int = None,
    db: Session = Depends(get_db)
):
    clientes = db.query(Usuario).filter(Usuario.rol == "CLIENTE", Usuario.activo == True).all()
    
    cliente_seleccionado = None
    productos = []
    
    if cliente_id:
        cliente_seleccionado = db.query(Usuario).filter(Usuario.id_usuario == cliente_id).first()
        if cliente_seleccionado:
            repo = InventarioRepository(db)
            productos = repo.obtener_por_cliente(cliente_id)
    
    return templates.TemplateResponse("inventario_admin.html", {
        "request": request,
        "clientes": clientes,
        "cliente_seleccionado": cliente_seleccionado,
        "productos": productos
    })