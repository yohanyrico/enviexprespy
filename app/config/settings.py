# app/config/data_initializer.py

from sqlalchemy.orm import Session
from app.models.usuario import Usuario
from datetime import datetime
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def init_database(db: Session):
    admin = db.query(Usuario).filter(Usuario.user_name == "admin").first()

    if not admin:
        admin = Usuario(
            user_name="admin",
            password=pwd_context.hash("123"),
            rol="ADMIN",
            nombre="Administrador",
            apellido="Principal",
            correo="admin@correo.com",
            activo=True,
            fecha_creacion=datetime.now(),
            telefono="3244434432"
        )
        db.add(admin)
        db.commit()
        print("✅ Usuario admin creado con éxito")
    else:
        print("ℹ️ Usuario admin ya existe")