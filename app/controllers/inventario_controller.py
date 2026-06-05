from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.config.database import get_db # Ajustado a tu config
from app.repositories.inventario_repository import InventarioRepository
from app.models.inventario import InventarioProducto

router = APIRouter(prefix="/inventario", tags=["Inventario"])

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