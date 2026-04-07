from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
from datetime import datetime
from app.config.database import Base

class Transaccion(Base):
    __tablename__ = "transaccion"

    id_transaccion = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuario.id_usuario"))
    
    # CAMBIO AQUÍ: Cambiamos 'envio.envio_id' por 'envios.envio_id' (en plural)
    envio_id = Column(Integer, ForeignKey("envios.envio_id"), nullable=True)
    
    tipo_movimiento = Column(Enum('CARGA', 'DESCUENTO', 'REEMBOLSO', 'AJUSTE'), nullable=False)
    monto = Column(Numeric(12, 2), nullable=False)
    # Cambiamos a String(255) para que coincida con tu SQL
    concepto = Column(String(255), nullable=False)
    fecha_creacion = Column(DateTime, default=datetime.now)

    # Relaciones
    usuario = relationship("Usuario", back_populates="transacciones")
    
    # También ajustamos el primaryjoin para que use el nombre de la clase
    envio = relationship("Envio", primaryjoin="Transaccion.envio_id == Envio.envio_id")