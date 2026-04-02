from sqlalchemy import Column, BigInteger, String
from sqlalchemy.orm import relationship
from app.config.database import Base


class Ruta(Base):
    __tablename__ = "rutas"

    ruta_id = Column(BigInteger, primary_key=True, autoincrement=True)
    nombre_sector = Column(String(150))
    ciudad = Column(String(100))

    envios = relationship("Envio", back_populates="ruta")