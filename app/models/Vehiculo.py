# app/models/Vehiculo.py

from sqlalchemy import Column, BigInteger, String, Float, Enum
from sqlalchemy.orm import relationship
from app.config.database import Base


class Vehiculo(Base):
    __tablename__ = "vehiculo"

    vehiculo_id = Column(BigInteger, primary_key=True, autoincrement=True)
    placa = Column(String(10), nullable=False, unique=True)
    
    # Valores exactos como están en la BD (formato Java original)
    tipo = Column(
        Enum("Moto", "Carro", "Camioneta", "Camión", "Van",
            name="tipo", native_enum=False),
        nullable=False
    )
    capacidad_kg = Column(Float, nullable=False)

    # Relación inversa con Envio
    envios = relationship("Envio", back_populates="vehiculo")