from fastapi import APIRouter, Request, Depends, BackgroundTasks
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime
from decimal import Decimal
from app.config.database import get_db
from app.models.Usuario import Usuario
from app.models.Envio import Envio
from app.models.Transaccion import Transaccion # IMPORTANTE: Para el historial de pagos
from app.config.templates import templates

# Seguridad
from app.security.SecurityConfig import get_current_user

router = APIRouter(tags=["Home"])

# --- RUTAS DE NAVEGACIÓN PRINCIPAL ---

@router.get("/home")
def home(request: Request, db: Session = Depends(get_db)):
    """
    Ruta principal dinámica que redirige según el usuario logueado en la sesión.
    """
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

@router.get("/home_cliente")
def home_cliente(request: Request, db: Session = Depends(get_db)):
    """
    Carga el panel personalizado del cliente (Yohany, Jose, Lau, etc.)
    """
    user_id = request.session.get("user_id")
    
    if not user_id:
        return RedirectResponse(url="/login?error=denied")

    usuario = db.query(Usuario).filter(Usuario.id_usuario == user_id).first()
    
    if not usuario:
        return RedirectResponse(url="/login")

    # Cargamos los envíos SOLO de este usuario logueado
    mis_envios = db.query(Envio).filter(Envio.usuario_cliente_id == usuario.id_usuario).all()

    return templates.TemplateResponse("home_cliente.html", {
        "request": request,
        "usuario": usuario,
        "envios": mis_envios,
        "rol": usuario.rol,
        "saldo": usuario.saldo_plan
    })

# --- RUTAS DE PLANES Y PAGOS ---

@router.get('/planes/detallado/{nombre_plan}')
def detalle_plan(request: Request, nombre_plan: str):
    return templates.TemplateResponse('detalle_plan.html', {
        "request": request, 
        "plan": nombre_plan
    })

@router.get('/planes/pago/{nombre_plan}')
def pasarela_pago(request: Request, nombre_plan: str):
    # Precios unitarios informativos
    precios = {
        "bronce": "11.990",
        "plata": "10.990",
        "oro": "9.990",
        "diamante": "8.990",
        "nacional": "17.990"
    }
    precio_seleccionado = precios.get(nombre_plan.lower(), "0")
    
    return templates.TemplateResponse('pago.html', {
        "request": request,
        "plan": nombre_plan,
        "precio": precio_seleccionado
    })

@router.post('/planes/confirmar')
async def confirmar_pago(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Procesa el pago, actualiza saldo y REGISTRA la transacción en el historial.
    """
    try:
        user_id = request.session.get("user_id")
        if not user_id:
            return RedirectResponse(url="/login")

        form_data = await request.form()
        plan_nombre = form_data.get("plan").lower()
        
        # Configuración de montos según el plan
        config_planes = {
            "bronce": {"total": 119990, "cuota": 11990},
            "plata":  {"total": 359700, "cuota": 10990},
            "oro":     {"total": 599500, "cuota": 9990},
            "diamante":{"total": 1199000, "cuota": 8990}
        }
        
        plan_info = config_planes.get(plan_nombre, {"total": 0, "cuota": 0})

        # --- ACTUALIZACIÓN DINÁMICA DEL USUARIO ---
        usuario = db.query(Usuario).filter(Usuario.id_usuario == user_id).first()
        
        if usuario:
            monto_total = Decimal(plan_info['total'])
            
            # 1. Actualizar datos del usuario
            usuario.saldo_plan = monto_total
            usuario.cuota_fija = plan_info['cuota']
            usuario.rol = plan_nombre.upper() # Cambiamos su rol al del plan adquirido
            
            # 2. REGISTRAR TRANSACCIÓN EN LA BILLETERA
            nueva_trans = Transaccion(
                usuario_id=usuario.id_usuario,
                tipo_movimiento='CARGA',
                monto=monto_total,
                concepto=f"Activación de Plan {plan_nombre.upper()}",
                fecha_creacion=datetime.now()
            )
            db.add(nueva_trans)
            
            # Guardar todo en la BD
            db.commit() 

            print(f"SISTEMA: Plan {plan_nombre.upper()} activado para {usuario.user_name}")

            # Envío de factura simulado
            background_tasks.add_task(enviar_factura_email, usuario.correo, plan_nombre)

            return templates.TemplateResponse("pago_exitoso.html", {
                "request": request,
                "plan": plan_nombre,
                "usuario": usuario.nombre,
                "total": monto_total,
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
    """
    Simulación de envío de correo electrónico.
    """
    print(f"\n--- ENVIEXPRESS MAIL SERVER ---")
    print(f"DESTINO: {email}")
    print(f"ASUNTO: Confirmación de Pago - Plan {plan.upper()}")
    print(f"MENSAJE: Gracias por confiar en Enviexpress. Tu plan ya está activo.")
    print(f"--------------------------------\n")