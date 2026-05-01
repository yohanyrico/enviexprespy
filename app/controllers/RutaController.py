import os
from fastapi import APIRouter, Request, Depends, Body
from fastapi.templating import Jinja2Templates
from starlette.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload
from app.config.database import SessionLocal
from app.models.Envio import Envio
from app.models.Usuario import Usuario

# Configuración de rutas de templates
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "..", "templates"))

router = APIRouter()

# Dependencia de la Base de Datos
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- RUTA 1: ASIGNACIÓN MASIVA (AJAX) ---
@router.post("/envios/asignar-mensajero-masivo")
async def asignar_mensajero_masivo(
    data: dict = Body(...), 
    db: Session = Depends(get_db)
):
    try:
        envio_ids = data.get("envio_ids")
        id_mensajero = data.get("id_mensajero")

        if not envio_ids or not id_mensajero:
            return {"status": "error", "message": "Faltan datos de envío o mensajero."}

        # Actualización masiva en la tabla envios
        db.query(Envio).filter(Envio.envio_id.in_(envio_ids)).update(
            {"usuario_mensajero_id": id_mensajero, "estado": "En_Ruta"},
            synchronize_session=False
        )
        db.commit()
        return {"status": "success", "message": f"Se han asignado {len(envio_ids)} pedidos correctamente."}
    
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

# --- RUTA 2: QUITAR DE RUTA MASIVO (AJAX) ---
@router.post("/envios/quitar-de-ruta-masivo")
async def quitar_de_ruta_masivo(
    data: dict = Body(...), 
    db: Session = Depends(get_db)
):
    try:
        envio_ids = data.get("envio_ids")
        if not envio_ids:
            return {"status": "error", "message": "No hay envíos seleccionados"}

        db.query(Envio).filter(Envio.envio_id.in_(envio_ids)).update(
            {"usuario_mensajero_id": None, "estado": "Registrado"},
            synchronize_session=False
        )
        db.commit()
        return {"status": "success", "message": "Pedidos liberados de la ruta correctamente."}
    
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

# --- RUTA 3: QUITAR UN SOLO PEDIDO DE LA RUTA (GET) ---
@router.get("/envios/quitar-de-ruta/{envio_id}")
async def quitar_de_ruta(
    envio_id: int, 
    db: Session = Depends(get_db)
):
    try:
        envio = db.query(Envio).filter(Envio.envio_id == envio_id).first()
        
        if not envio:
            return {"status": "error", "message": "Envío no encontrado"}

        envio.usuario_mensajero_id = None
        envio.estado = "Registrado" 
        
        db.commit()
        return RedirectResponse(url="/envios", status_code=303)

    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

# --- RUTA 4: CARGAR EL MAPA OPERATIVO ---
# ✅ FIX BUG 2: Esta es la ÚNICA definición de planificar-ruta.
#    La duplicada en EnvioController.py fue eliminada.
@router.api_route("/envios/planificar-ruta", methods=["GET", "POST"], response_class=HTMLResponse)
async def planificar_ruta(request: Request, db: Session = Depends(get_db)):

    # Solo envíos pendientes van al mapa para asignar
    envios = db.query(Envio).filter(
        Envio.estado == "Registrado"
    ).options(
        joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega)
    ).all()

    # Mensajeros disponibles para el select de asignación
    mensajeros = db.query(Usuario).filter(
        Usuario.rol == "MENSAJERO"
    ).all()

    # ✅ FIX BUG 1 (mapa): Obtener mensajeros con envíos En_Ruta → panel izquierdo
    ids_con_ruta = db.query(Envio.usuario_mensajero_id).filter(
        Envio.estado == "En_Ruta",
        Envio.usuario_mensajero_id != None
    ).distinct().all()

    ids_con_ruta = [row[0] for row in ids_con_ruta]

    rutas_activas = db.query(Usuario).filter(
        Usuario.id_usuario.in_(ids_con_ruta)
    ).all() if ids_con_ruta else []

    rol = request.session.get("rol")

    return templates.TemplateResponse("mapa-operaciones.html", {
        "request": request,
        "envios": envios,
        "mensajeros": mensajeros,
        "rutas_activas": rutas_activas,   # ✅ Ahora sí se pasa al template
        "rol": rol
    })