# app/models/usuario.py

from sqlalchemy import Column, BigInteger, String, Boolean, DateTime
from sqlalchemy.orm import relationship
from app.config.database import Base
from datetime import datetime


class Usuario(Base):
    __tablename__ = "usuario"

    id_usuario = Column(BigInteger, primary_key=True, autoincrement=True)
    user_name = Column(String(255), nullable=False, unique=True)
    password = Column(String(255), nullable=False)
    nombre = Column(String(100), nullable=False)
    apellido = Column(String(100), nullable=False)
    correo = Column(String(120), nullable=False, unique=True)
    telefono = Column(String(20))
    rol = Column(String(50), nullable=False)
    activo = Column(Boolean, nullable=False)
    fecha_creacion = Column(DateTime, nullable=False, default=datetime.now)
    envios_como_cliente = relationship("Envio", foreign_keys="[Envio.usuario_cliente_id]", back_populates="cliente")
    envios_como_mensajero = relationship("Envio", foreign_keys="[Envio.usuario_mensajero_id]", back_populates="mensajero")

    # Relaciones inversas con Envio
    envios_como_cliente = relationship(
        "Envio",
        primaryjoin="Usuario.id_usuario == Envio.usuario_cliente_id",
        back_populates="cliente"
    )
    envios_como_mensajero = relationship(
        "Envio",
        primaryjoin="Usuario.id_usuario == Envio.usuario_mensajero_id",
        back_populates="mensajero"
    )