from fastapi import APIRouter, Request, Depends, BackgroundTasks
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload
from datetime import datetime
from decimal import Decimal
from app.config.database import get_db
from app.models.Usuario import Usuario
from app.models.Envio import Envio
from app.models.Transaccion import Transaccion
from app.models.Tarifa import Tarifa
from app.config.templates import templates

# Seguridad
from app.security.SecurityConfig import get_current_user

router = APIRouter(tags=["Home"])

# --- RUTAS DE NAVEGACIÓN PRINCIPAL ---

@router.get("/home")
def home(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login")

    usuario = db.query(Usuario).filter(Usuario.id_usuario == user_id).first()
    if not usuario:
        return RedirectResponse(url="/login")

    if usuario.rol == "ADMIN":
        return templates.TemplateResponse("home.html", {
            "request": request,
            "rol": "ADMIN",
            "usuario": usuario
        })
    elif usuario.rol == "MENSAJERO":
        return templates.TemplateResponse("home_mensajero.html", {
            "request": request,
            "rol": "MENSAJERO",
            "usuario": usuario
        })

    return RedirectResponse(url="/home_cliente")

# app/controllers/HomeController.py

@router.get("/home_cliente")
def home_cliente(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login")

    # Traemos al usuario con su tarifa
    usuario = db.query(Usuario).options(joinedload(Usuario.tarifa)).filter(Usuario.id_usuario == user_id).first()
    
    # BUSCAMOS TODAS LAS TARIFAS PARA LOS BOTONES FLOTANTES
    tarifas_db = db.query(Tarifa).all()

    return templates.TemplateResponse("home_cliente.html", {
        "request": request,
        "usuario": usuario,
        "tarifas": tarifas_db,  # <--- Esto es lo que hace que sea dinámico
        "s": usuario.saldo_plan
    })
# --- RUTAS DE PLANES Y PAGOS (TOTALMENTE DINÁMICAS) ---

@router.get('/planes/detallado/{nombre_plan}')
def detalle_plan(request: Request, nombre_plan: str):
    return templates.TemplateResponse('detalle_plan.html', {
        "request": request,
        "plan": nombre_plan
    })

@router.get('/planes/pago/{nombre_plan}')
def pasarela_pago(request: Request, nombre_plan: str, db: Session = Depends(get_db)):
    """
    Trae el precio vivo desde la BD. Elimina fallbacks estáticos.
    """
    tarifa = db.query(Tarifa).filter(Tarifa.nombre.ilike(nombre_plan)).first()

    def fmt(n):
        return f"{int(n):,}".replace(",", ".")

    if not tarifa:
        # Si la tarifa no existe en la BD, no podemos cobrar.
        return RedirectResponse(url="/home_cliente?error=tarifa_no_encontrada")

    # Calculamos montos basados en la configuración actual del Admin
    monto_cuota = tarifa.precio_plan
    monto_total = int(tarifa.precio_plan) * tarifa.envios_incluidos

    return templates.TemplateResponse('pago.html', {
        "request": request,
        "plan": nombre_plan,
        "precio": fmt(monto_total),
        "cuota": fmt(monto_cuota)
    })

@router.post('/planes/confirmar')
async def confirmar_pago(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Procesa el pago usando los valores reales de la tabla Tarifa al momento de la transacción.
    """
    try:
        user_id = request.session.get("user_id")
        if not user_id:
            return RedirectResponse(url="/login")

        form_data = await request.form()
        plan_nombre = form_data.get("plan").lower()

        # CONSULTA A LA BD PARA OBTENER PRECIOS ACTUALES
        tarifa = db.query(Tarifa).filter(Tarifa.nombre.ilike(plan_nombre)).first()

        if not tarifa:
            return RedirectResponse(url="/home_cliente?error=plan_invalido")

        # Usamos los valores configurados por el administrador
        monto_cuota = int(tarifa.precio_plan)
        monto_total = monto_cuota * tarifa.envios_incluidos
        monto_total_dec = Decimal(str(monto_total))

        usuario = db.query(Usuario).filter(Usuario.id_usuario == user_id).first()

        if usuario:
            # El saldo se ACUMULA
            usuario.saldo_plan = (usuario.saldo_plan or Decimal('0')) + monto_total_dec
            # Sincronizamos los datos del usuario con el plan adquirido
            usuario.cuota_fija = monto_cuota
            usuario.rol = plan_nombre.upper()
            usuario.tarifa_id = tarifa.id # Vinculación para que el banner sea dinámico

            nueva_trans = Transaccion(
                usuario_id=usuario.id_usuario,
                tipo_movimiento='CARGA',
                monto=monto_total_dec,
                concepto=f"Activación de Plan {plan_nombre.upper()} - ${monto_cuota} por guía",
                fecha_creacion=datetime.now()
            )
            db.add(nueva_trans)
            db.commit()

            print(f"SISTEMA: Plan {plan_nombre.upper()} activado dinámicamente.")
            background_tasks.add_task(enviar_factura_email, usuario.correo, plan_nombre)

            return templates.TemplateResponse("pago_exitoso.html", {
                "request": request,
                "plan": plan_nombre,
                "usuario": usuario.nombre,
                "total": monto_total_dec,
                "saldo_cargado": usuario.saldo_plan,
                "cuota_fija": usuario.cuota_fija
            })

        return RedirectResponse(url="/login")

    except Exception as e:
        db.rollback()
        print(f"ERROR CRÍTICO EN PAGO: {e}")
        return RedirectResponse(url="/home_cliente?error=pago_fallido")

# --- FUNCIONES DE APOYO ---

def enviar_factura_email(email: str, plan: str):
    print(f"\n--- ENVIEXPRESS MAIL SERVER ---")
    print(f"DESTINO: {email}")
    print(f"ASUNTO: Confirmación de Pago - Plan {plan.upper()}")
    print(f"MENSAJE: Gracias por confiar en Enviexpress. Tu plan ya está activo.")
    print(f"--------------------------------\n")