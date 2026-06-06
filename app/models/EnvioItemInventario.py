# app/models/EnvioItemInventario.py
from sqlalchemy import Column, Integer, BigInteger, ForeignKey
from sqlalchemy.orm import relationship
from app.config.database import Base


class EnvioItemInventario(Base):
    __tablename__ = "envio_items_inventario"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    envio_id    = Column(BigInteger, ForeignKey("envios.envio_id", ondelete="CASCADE"), nullable=False)
    producto_id = Column(Integer, ForeignKey("inventario_productos.id", ondelete="CASCADE"), nullable=False)
    cantidad    = Column(Integer, nullable=False, default=1)

    envio    = relationship("Envio",              back_populates="items_inventario")
    producto = relationship("InventarioProducto", lazy="joined")