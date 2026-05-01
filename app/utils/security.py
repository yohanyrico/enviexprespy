from datetime import datetime, timedelta
from jose import jwt

SECRET_KEY = "tu_clave_secreta_super_segura" # Usa una variable de entorno
ALGORITHM = "HS256"

def crear_token_recuperacion(email: str):
    expiracion = datetime.utcnow() + timedelta(minutes=15)
    payload = {"sub": email, "exp": expiracion}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def validar_token_recuperacion(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub") # Retorna el email si es válido
    except:
        return None