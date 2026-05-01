# app/models/Tarifa.py
from sqlalchemy import Column, BigInteger, Integer, String, Numeric, Text
from sqlalchemy.orm import relationship
from app.config.database import Base

class Tarifa(Base):
    __tablename__ = "tarifas"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    nombre = Column(String(50), nullable=False) 
    
    # Comenta o elimina esta línea si ya no quieres usar KG
    # precio_kg = Column(Numeric(10, 2), nullable=False) 

    precio_plan = Column(Numeric(10, 2)) # Este será tu "Valor por envío"
    envios_incluidos = Column(Integer)
    descripcion = Column(Text)
    
    # Relaciones
    envios = relationship("Envio", back_populates="tarifa")
    usuarios = relationship("Usuario", back_populates="tarifa")