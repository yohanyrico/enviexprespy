# app/models/Usuario.py
from sqlalchemy import Column, BigInteger, Numeric, String, Boolean, DateTime, ForeignKey
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
    activo = Column(Boolean, nullable=False, default=True)
    fecha_creacion = Column(DateTime, nullable=False, default=datetime.now)
    direccion = Column(String(255), nullable=True)
    ciudad    = Column(String(150), nullable=True)
    localidad = Column(String(100), nullable=True)
    
    # Manejo de Billetera (Asegúrate de que default sea 0.00 para la suma +=)
    saldo_plan = Column(Numeric(12, 2), nullable=False, default=0.00)
    cuota_fija = Column(Numeric(12, 2), nullable=False, default=0.00) 

    # --- CONEXIÓN CON TARIFA ---
    # Verifica que el __tablename__ en Tarifa.py sea exactamente "tarifas"
    tarifa_id = Column(BigInteger, ForeignKey("tarifas.id"), nullable=True)
    
    # Relación para acceder a u.tarifa
    tarifa = relationship("Tarifa", back_populates="usuarios")

    # --- RELACIONES ---

    # Relación con Transacciones (Para el historial que ve Laura)
    transacciones = relationship("Transaccion", back_populates="usuario", cascade="all, delete-orphan")

    # Relaciones con Envio
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