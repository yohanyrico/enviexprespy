from sqlalchemy import Column, BigInteger, String, Float # Añadimos Float
from sqlalchemy.orm import relationship
from app.config.database import Base

class Lugar(Base):
    __tablename__ = "lugares"

    lugar_id = Column(BigInteger, primary_key=True, autoincrement=True)
    direccion = Column(String(255))
    ciudad = Column(String(100))
    referencia = Column(String(255))
    # --- NUEVOS CAMPOS PARA EL MAPA ---
    latitud = Column(Float, nullable=True)
    longitud = Column(Float, nullable=True)

    envios_recogida = relationship("Envio", foreign_keys="Envio.lugar_recogida_id", back_populates="lugar_recogida")
    envios_entrega = relationship("Envio", foreign_keys="Envio.lugar_entrega_id", back_populates="lugar_entrega")