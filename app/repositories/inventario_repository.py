from sqlalchemy.orm import Session
from app.models.inventario import InventarioProducto, HistorialInventario

class InventarioRepository:
    def __init__(self, db: Session):
        self.db = db

    def obtener_por_cliente(self, cliente_id: int):
        return self.db.query(InventarioProducto).filter(InventarioProducto.cliente_id == cliente_id).all()

    def buscar_por_sku(self, cliente_id: int, sku: str):
        return self.db.query(InventarioProducto).filter(
            InventarioProducto.cliente_id == cliente_id, 
            InventarioProducto.sku == sku
        ).first()

    def guardar_producto(self, producto: InventarioProducto):
        self.db.add(producto)
        self.db.commit()
        self.db.refresh(producto)
        return producto