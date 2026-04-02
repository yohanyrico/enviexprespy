# app/models/tarifa.py

from sqlalchemy import Column, BigInteger, String, Numeric
from sqlalchemy.orm import relationship
from app.config.database import Base


# app/models/Tarifa.py
class Tarifa(Base):
    __tablename__ = "tarifas"
    id = Column(BigInteger, primary_key=True)
    nombre = Column(String(50)) # <--- Verifica que este nombre sea igual al que usas en el HTML
    precio_kg = Column(Numeric(10, 2))

    # Relación inversa con Envio
    envios = relationship("Envio", back_populates="tarifa")