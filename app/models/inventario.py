from sqlalchemy import Column, Integer, String, ForeignKey, Numeric, DateTime
from sqlalchemy.sql import func
from app.config.database import Base

class InventarioProducto(Base):
    __tablename__ = "inventario_productos"

    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, nullable=False, index=True)
    sku = Column(String(50), nullable=False)
    nombre = Column(String(100), nullable=False)
    stock_disponible = Column(Integer, default=0)
    stock_comprometido = Column(Integer, default=0)
    ubicacion_bodega = Column(String(50), nullable=True)
    peso_kg = Column(Numeric(5, 2), default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class HistorialInventario(Base):
    __tablename__ = "historial_inventario"

    id = Column(Integer, primary_key=True, index=True)
    producto_id = Column(Integer, ForeignKey("inventario_productos.id", ondelete="CASCADE"), nullable=False)
    tipo_movimiento = Column(String(20), nullable=False)
    cantidad = Column(Integer, nullable=False)
    motivo = Column(String(255), nullable=True)
    usuario_id = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())