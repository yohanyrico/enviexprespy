# app/models/seguimiento.py

from sqlalchemy import Column, BigInteger, String, DateTime, Enum, ForeignKey
from sqlalchemy.orm import relationship
from app.config.database import Base
from app.models.EstadoEnvio import EstadoEnvio


class Seguimiento(Base):
    __tablename__ = "seguimientos"

    seguimiento_id = Column(BigInteger, primary_key=True, autoincrement=True)

    envio_id = Column(BigInteger, ForeignKey("envios.envio_id"), nullable=False)
    envio = relationship("Envio", back_populates="seguimientos")

    estado = Column(Enum(EstadoEnvio), nullable=False)
    descripcion = Column(String(255))
    fecha = Column(DateTime, nullable=False)