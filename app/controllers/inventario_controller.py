from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.config.templates import templates
from app.repositories.inventario_repository import InventarioRepository
from app.models.inventario import InventarioProducto, HistorialInventario
from app.models.Usuario import Usuario
from app.security.SecurityConfig import get_current_user

router = APIRouter(prefix="/inventario", tags=["Inventario"])


# ==========================================
#      ENDPOINTS API (DATOS RAW / JSON)
# ==========================================

@router.get("/cliente/{cliente_id}")
def listar_inventario(cliente_id: int, db: Session = Depends(get_db)):
    repo = InventarioRepository(db)
    return repo.obtener_por_cliente(cliente_id)


@router.post("/abastecer/{cliente_id}")
async def abastecer_stock(cliente_id: int, request: Request, db: Session = Depends(get_db)):
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        data      = await request.json()
        sku       = data.get("sku")
        nombre    = data.get("nombre")
        cantidad  = int(data.get("cantidad", 1))
        ubicacion = data.get("ubicacion", "").strip() or None
        stock_minimo = int(data.get("stock_minimo", 5))
    else:
        form      = await request.form()
        sku       = form.get("sku")
        nombre    = form.get("nombre")
        cantidad  = int(form.get("cantidad", 1))
        ubicacion = (form.get("ubicacion") or "").strip() or None
        stock_minimo = int(form.get("stock_minimo", 5))

    repo     = InventarioRepository(db)
    producto = repo.buscar_por_sku(cliente_id, sku)

    if producto:
        producto.stock_disponible += cantidad
    else:
        producto = InventarioProducto(
            cliente_id=cliente_id,
            sku=sku,
            nombre=nombre,
            stock_disponible=cantidad,
            ubicacion_bodega=ubicacion,
            stock_minimo=stock_minimo
        )
        db.add(producto)
        db.flush()

    db.add(HistorialInventario(
        producto_id=producto.id,
        tipo_movimiento="ENTRADA",
        cantidad=cantidad,
        motivo="Abastecimiento manual",
        usuario_id=cliente_id
    ))
    db.commit()

    if "application/json" in content_type:
        return JSONResponse({"ok": True, "stock": producto.stock_disponible})

    return RedirectResponse(url=f"/inventario/admin?cliente_id={cliente_id}", status_code=303)


# ==========================================
#      VISTA WEB CLIENTE
# ==========================================

@router.get("/web", response_class=HTMLResponse)
def ver_inventario_web(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    repo = InventarioRepository(db)
    productos = repo.obtener_por_cliente(current_user.id_usuario)

    return templates.TemplateResponse("inventario.html", {
        "request": request,
        "productos": productos,
        "cliente_id": current_user.id_usuario
    })


# ==========================================
#      VISTA ADMIN (CEO/ADMINISTRATIVO)
# ==========================================

@router.get("/admin", response_class=HTMLResponse)
def inventario_admin(
    request: Request,
    cliente_id: int = None,
    db: Session = Depends(get_db)
):
    # Solo clientes con inventario habilitado
    clientes = db.query(Usuario).filter(
        Usuario.rol == "CLIENTE",
        Usuario.activo == True,
        Usuario.maneja_inventario == True
    ).all()

    cliente_seleccionado = None
    productos = []

    if cliente_id:
        cliente_seleccionado = db.query(Usuario).filter(
            Usuario.id_usuario == cliente_id
        ).first()
        if cliente_seleccionado:
            repo = InventarioRepository(db)
            productos = repo.obtener_por_cliente(cliente_id)

    return templates.TemplateResponse("inventario_admin.html", {
        "request": request,
        "clientes": clientes,
        "cliente_seleccionado": cliente_seleccionado,
        "productos": productos
    })