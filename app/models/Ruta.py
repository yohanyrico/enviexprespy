# app/models/Ruta.py
from sqlalchemy import Column, BigInteger, String, ForeignKey
from sqlalchemy.orm import relationship
from app.config.database import Base

class Ruta(Base):
    __tablename__ = "rutas"

    ruta_id = Column(BigInteger, primary_key=True, autoincrement=True)
    nombre_sector = Column(String(150))
    ciudad = Column(String(100))
    estado = Column(String(50), default="En curso")
    mensajero_id = Column(BigInteger, ForeignKey("usuario.id_usuario"), nullable=True)

    # Relación con el Mensajero asignado a la ruta
    mensajero = relationship("Usuario", foreign_keys=[mensajero_id])
    
    # 🏁 RELACIÓN CORRECTA Y UNIFICADA: 
    # Mapea de forma perfecta todos los envíos asociados a esta ruta logística mediante 'ruta_id'
    envios = relationship("Envio", back_populates="ruta", foreign_keys="[Envio.ruta_id]")