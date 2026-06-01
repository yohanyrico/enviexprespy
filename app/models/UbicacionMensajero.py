# app/models/UbicacionMensajero.py

from sqlalchemy import Column, Integer, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.config.database import Base
from datetime import datetime

class UbicacionMensajero(Base):
    __tablename__ = "ubicaciones_mensajeros"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    usuario = Column(Integer, ForeignKey("usuario.id_usuario", ondelete="CASCADE"), nullable=False)
    latitud = Column(Float, nullable=False)
    longitud = Column(Float, nullable=False)
    fecha = Column(DateTime, default=datetime.now, nullable=False)

    # Relación opcional por si necesitas consultar los datos del motorizado después
    mensajero = relationship("Usuario")