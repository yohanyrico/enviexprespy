# app/models/Tarifa.py
from sqlalchemy import Column, BigInteger, String, Numeric
from sqlalchemy.orm import relationship
from app.config.database import Base

class Tarifa(Base):
    __tablename__ = "tarifas"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    nombre = Column(String(50), nullable=False) 
    precio_kg = Column(Numeric(10, 2), nullable=False)

    # Relación inversa con Envio (Ya la tenías)
    envios = relationship("Envio", back_populates="tarifa")

    # --- NUEVA RELACIÓN INVERSA CON USUARIO ---
    # Permite saber qué usuarios tienen asignada esta tarifa
    usuarios = relationship("Usuario", back_populates="tarifa")