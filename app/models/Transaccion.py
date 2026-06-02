from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
from datetime import datetime
from app.config.database import Base

class Transaccion(Base):
    __tablename__ = "transaccion"

    id_transaccion = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuario.id_usuario"))
    envio_id = Column(Integer, ForeignKey("envios.envio_id"), nullable=True)
    
    tipo_movimiento = Column(
        Enum('CARGA', 'DESCUENTO', 'REEMBOLSO', 'AJUSTE',
             name="tipomovimiento", native_enum=False),
        nullable=False
    )
    monto = Column(Numeric(12, 2), nullable=False)
    concepto = Column(String(255), nullable=False)
    fecha_creacion = Column(DateTime, default=datetime.now)

    usuario = relationship("Usuario", back_populates="transacciones")
    envio = relationship("Envio", primaryjoin="Transaccion.envio_id == Envio.envio_id")