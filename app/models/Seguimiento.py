# app/models/seguimiento.py

from sqlalchemy import Column, BigInteger, String, DateTime, Enum, ForeignKey
from sqlalchemy.orm import relationship
from app.config.database import Base


class Seguimiento(Base):
    __tablename__ = "seguimientos"

    seguimiento_id = Column(BigInteger, primary_key=True, autoincrement=True)

    envio_id = Column(BigInteger, ForeignKey("envios.envio_id"), nullable=False)
    envio = relationship("Envio", back_populates="seguimientos")

    estado = Column(
    Enum(
        "Registrado",
        "Pendiente_Recoger",
        "Colectado",
        "Pendiente_Verificar",
        "En_Bodega",
        "En_Ruta",
        "En_Destino",
        "Entregado",
        "Fallido",
        "Cancelado",
        "Devolucion",
        "Rechazado",
        name="estadoseguimiento",
        native_enum=False
    ),
    nullable=False,
    default="Registrado"
)
    descripcion = Column(String(255))
    fecha = Column(DateTime, nullable=False)
    foto = Column(String(255), nullable=True)