from sqlalchemy import Column, BigInteger, String, ForeignKey
from sqlalchemy.orm import relationship
from app.config.database import Base

class Ruta(Base):
    __tablename__ = "rutas"

    ruta_id = Column(BigInteger, primary_key=True, autoincrement=True)
    nombre_sector = Column(String(150))
    ciudad = Column(String(100))
    estado = Column(String(50), default="En curso")   # ← nuevo
    mensajero_id = Column(BigInteger, ForeignKey("usuario.id_usuario"), nullable=True)

    mensajero = relationship("Usuario", foreign_keys=[mensajero_id])
    envios = relationship("Envio", back_populates="ruta")