import os
import uvicorn
from dotenv import load_dotenv
load_dotenv() 

print("------------------------------------------")
print(f"VALOR DE WOMPI_KEY: {os.getenv('WOMPI_PUBLIC_KEY')}")
print("------------------------------------------") 

from fastapi import Depends, FastAPI, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import text  
from starlette.middleware.sessions import SessionMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Importar configuración de DB
from app.config.database import engine, Base, SessionLocal, get_db
from app.config.data_initializer import init_database
from app.config.templates import templates 
from app.security.SecurityConfig import hash_password

# Importar modelos
from app.models.Usuario import Usuario 
from app.models.UbicacionMensajero import UbicacionMensajero
# Importar los routers correctamente
from app.controllers.LandingController import router as landing_router
from app.controllers.HomeController import router as home_router
from app.controllers.UsuarioController import router as usuario_router
from app.controllers.EnvioController import router as envio_router
from app.controllers.VehiculoController import router as vehiculo_router
from app.controllers.TarifaController import router as tarifa_router
from app.controllers.SeguimientoController import router as seguimiento_router
from app.controllers.RutaController import router as ruta_router
from app.controllers.AppMensajeroController import router as app_mensajero_router
from app.controllers.FinanzasController import router as finanzas_router
from app.controllers.PlanController import router as plan_router
from app.controllers.BodegaController import router as bodega_router
from app.controllers import inventario_controller

# Importar servicios
from app.services.email_service import enviar_email_recuperacion
from app.utils.security import crear_token_recuperacion, validar_token_recuperacion

app = FastAPI(
    title="EnvíExpress API",
    description="Sistema de gestión de envíos y logística profesional",
    version="1.0.0"
)

# --- Middlewares ---
app.add_middleware(
    SessionMiddleware,
    secret_key="tu_secret_key",
    max_age=3600,
    same_site="lax",
    https_only=False
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Base de Datos ---
Base.metadata.create_all(bind=engine)

# --- Montar Archivos Estáticos ---
if not os.path.exists("app/static"):
    os.makedirs("app/static")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# --- Inclusión de Routers (Corregido: Se eliminó la duplicación de AppMensajero) ---
app.include_router(landing_router)
app.include_router(home_router)
app.include_router(usuario_router)
app.include_router(envio_router)
app.include_router(vehiculo_router)
app.include_router(tarifa_router)
app.include_router(seguimiento_router)
app.include_router(ruta_router)
app.include_router(app_mensajero_router)
app.include_router(finanzas_router)
app.include_router(plan_router)
app.include_router(bodega_router)
app.include_router(inventario_controller.router)

# --- 💻 ENDPOINT GLOBAL PARA EL MAPA DEL ADMINISTRADOR ---
@app.get("/api/admin/ubicaciones-mensajeros")
@app.get("/api/ubicaciones-mensajeros")
def obtener_ubicaciones_actuales(db: Session = Depends(get_db)):
    """
    Busca el último registro de coordenadas reportado por cada usuario en el sistema.
    Ideal para pintar todas las motos activas en el mapa de Bogotá.
    """
    try:
        from app.models.Usuario import Usuario
        
        # Consulta SQL nativa usando DISTINCT ON para traer solo la última coordenada de cada mensajero
        query = """
            SELECT DISTINCT ON (usuario) usuario, latitud, longitud, fecha
            FROM ubicaciones_mensajeros
            ORDER BY usuario, fecha DESC
        """
        resultados = db.execute(text(query)).fetchall()
        
        ubicaciones = []
        for r in resultados:
            # Obtener nombre del mensajero
            mensajero = db.query(Usuario).filter(Usuario.id_usuario == r.usuario).first()
            nombre_mensajero = f"{mensajero.nombre} {mensajero.apellido}" if mensajero else f"Mensajero {r.usuario}"
            
            ubicaciones.append({
                "id": r.usuario,
                "nombre": nombre_mensajero,
                "lat": float(r.latitud),
                "lng": float(r.longitud)
            })
        
        return ubicaciones
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al consultar ubicaciones: {str(e)}")


# --- Eventos de Ciclo de Vida ---
@app.on_event("startup")
def startup_event():
    db = SessionLocal()
    try:
        init_database(db)
    finally:
        db.close()

# --- RUTA DE RECUPERACIÓN ---
@app.post("/recuperar")
async def solicitar_recuperacion(email: str, db: Session = Depends(get_db)):
    usuario = db.query(Usuario).filter(Usuario.correo == email).first()
    if not usuario:
        return {"message": "Si el correo es válido, recibirás un enlace"}
    try:
        token = crear_token_recuperacion(usuario.correo)
        resultado = enviar_email_recuperacion(email, token)
        if resultado:
            return {"message": "Enlace enviado correctamente a su bandeja de entrada"}
        else:
            raise HTTPException(status_code=500, detail="Error al conectar con el servidor de correos")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

@app.get("/reset-password")
async def vista_reset_password(request: Request, token: str):
    return templates.TemplateResponse("reset_password.html", {"request": request, "token": token})

@app.post("/reset-password")
async def reset_password(token: str, nueva_clave: str, db: Session = Depends(get_db)):
    email = validar_token_recuperacion(token)
    if not email:
        raise HTTPException(status_code=400, detail="El enlace ha expirado o es inválido")
    usuario = db.query(Usuario).filter(Usuario.correo == email).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    usuario.password = hash_password(nueva_clave)
    db.commit()
    return {"message": "Contraseña actualizada con éxito. Ya puedes iniciar sesión."}

@app.get("/recuperar")
async def vista_recuperar(request: Request):
    return templates.TemplateResponse("recuperar.html", {"request": request})

# --- Ejecución ---
# --- Ejecución ---
if __name__ == "__main__":
    # Removido reload=True para que Render no choque en producción
    uvicorn.run("main:app", host="0.0.0.0", port=8080)
    
    #uvicorn main:app --reload --port 8080
    #https://matcher-zoom-deploy.ngrok-free.dev/planes/pago/oro
    #ngrok config add-authtoken 3DKTNnRXfbOGJSKoszkQ2Ooko9r_7U6MQpxVy1CNTfTkGBXq1 ngrok http 8080