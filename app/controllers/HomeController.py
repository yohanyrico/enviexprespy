from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload
from datetime import datetime
from decimal import Decimal
import os
import uuid
import hashlib

from app.config.database import get_db
from app.models.Usuario import Usuario
from app.models.Transaccion import Transaccion
from app.models.Tarifa import Tarifa
from app.config.templates import templates
from app.security.SecurityConfig import get_current_user

router = APIRouter(tags=["Home"])

# ─────────────────────────────────────────────
# CADA ROL TIENE SU PROPIO TEMPLATE
# ─────────────────────────────────────────────
# CEO            → home.html
# FACTURACION    → home_facturacion.html
# ADMINISTRATIVO → home_administrativo.html
# MENSAJERO      → home_mensajero.html
# CLIENTE        → home_cliente.html
# ─────────────────────────────────────────────

@router.get("/home")
def home(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login")

    usuario = db.query(Usuario).filter(Usuario.id_usuario == user_id).first()
    if not usuario:
        return RedirectResponse(url="/login")

    # ── CEO ──
    if usuario.rol == "CEO":
        return templates.TemplateResponse("home.html", {
            "request": request,
            "rol": usuario.rol,
            "usuario": usuario,
            "puede_ver_finanzas": True,
            "es_ceo": True,
        })

    # ── FACTURACION ──
    if usuario.rol == "FACTURACION":
        return templates.TemplateResponse("home_facturacion.html", {
            "request": request,
            "rol": usuario.rol,
            "usuario": usuario,
        })

    # ── ADMINISTRATIVO ──
    if usuario.rol == "ADMINISTRATIVO":
        return templates.TemplateResponse("home_administrativo.html", {
            "request": request,
            "rol": usuario.rol,
            "usuario": usuario,
        })

    # ── MENSAJERO ──
    if usuario.rol == "MENSAJERO":
        return templates.TemplateResponse("home_mensajero.html", {
            "request": request,
            "rol": usuario.rol,
            "usuario": usuario,
        })

    # ── CLIENTE y cualquier otro ──
    return RedirectResponse(url="/home_cliente")


@router.get("/home_cliente")
def home_cliente(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login")

    usuario = db.query(Usuario).options(joinedload(Usuario.tarifa)).filter(
        Usuario.id_usuario == user_id
    ).first()
    tarifas_db = db.query(Tarifa).all()

    return templates.TemplateResponse("home_cliente.html", {
        "request": request,
        "usuario": usuario,
        "tarifas": tarifas_db,
        "s": usuario.saldo_plan
    })


# ─────────────────────────────────────────────
# PLANES Y PAGOS
# ─────────────────────────────────────────────

@router.get('/planes/detallado/{nombre_plan}')
def detalle_plan(request: Request, nombre_plan: str):
    return templates.TemplateResponse('detalle_plan.html', {
        "request": request,
        "plan": nombre_plan
    })


def generar_firma_integridad(referencia: str, monto_centavos: int, moneda: str) -> str:
    """Genera la firma de integridad SHA-256 exigida por Wompi para el Checkout Web."""
    llave_secreta = os.getenv("WOMPI_INTEGRITY_SECRET")

    print(f"DEBUG: WOMPI_INTEGRITY_SECRET recuperada -> {'(configurada, longitud ' + str(len(llave_secreta)) + ')' if llave_secreta else 'None'}")

    if not llave_secreta:
        print("❌ ERROR CRÍTICO: WOMPI_INTEGRITY_SECRET no está configurada en las variables de entorno de Render.")
        return ""

    cadena = f"{referencia}{monto_centavos}{moneda}{llave_secreta}"
    firma = hashlib.sha256(cadena.encode("utf-8")).hexdigest()

    print(f"DEBUG: Firma generada correctamente para referencia {referencia}")

    return firma


@router.get('/planes/pago/{nombre_plan}')
def pasarela_pago(request: Request, nombre_plan: str, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login")

    tarifa = db.query(Tarifa).filter(Tarifa.nombre.ilike(nombre_plan)).first()
    if not tarifa:
        return RedirectResponse(url="/home_cliente?error=tarifa_no_encontrada")

    def fmt(n):
        return f"{int(n):,}".replace(",", ".")

    monto_cuota = int(tarifa.precio_plan or 0)
    monto_total = monto_cuota * (tarifa.envios_incluidos or 0)
    precio_centavos = monto_total * 100
    referencia  = f"ENVIX-{nombre_plan.upper()}-{uuid.uuid4().hex[:8].upper()}"
    wompi_public_key = os.getenv("WOMPI_PUBLIC_KEY", "")

    print(f">>> WOMPI KEY en pasarela_pago: '{wompi_public_key}'")

    firma_integridad = generar_firma_integridad(
        referencia=referencia,
        monto_centavos=precio_centavos,
        moneda="COP",
    )

    return templates.TemplateResponse('pago.html', {
        "request": request,
        "plan": nombre_plan,
        "precio": fmt(monto_total),
        "cuota": fmt(monto_cuota),
        "precio_centavos": precio_centavos,
        "referencia": referencia,
        "wompi_public_key": wompi_public_key,
        "firma_integridad": firma_integridad,   # 👈 NUEVO: requerido por Wompi
    })


@router.post('/planes/confirmar-wompi')
async def confirmar_wompi(request: Request, db: Session = Depends(get_db)):
    body        = await request.json()
    transaction_id = body.get("transaction_id")
    plan_nombre    = body.get("plan")
    status_tx      = body.get("status")

    if status_tx != "APPROVED":
        return {"ok": False, "mensaje": f"Estado: {status_tx}"}

    user_id = request.session.get("user_id")
    if not user_id:
        return {"ok": False, "mensaje": "Sesión expirada"}

    tarifa  = db.query(Tarifa).filter(Tarifa.nombre.ilike(plan_nombre)).first()
    usuario = db.query(Usuario).filter(Usuario.id_usuario == user_id).first()

    if not tarifa or not usuario:
        return {"ok": False, "mensaje": "Datos no encontrados"}

    monto_cuota = int(tarifa.precio_plan or 0)
    monto_total = Decimal(str(monto_cuota * (tarifa.envios_incluidos or 0)))

    usuario.saldo_plan = (usuario.saldo_plan or Decimal('0')) + monto_total
    usuario.cuota_fija = monto_cuota
    usuario.tarifa_id  = tarifa.id

    nueva_trans = Transaccion(
        usuario_id=usuario.id_usuario,
        tipo_movimiento='CARGA',
        monto=monto_total,
        concepto=f"Plan {plan_nombre.upper()} - TX Wompi {transaction_id}",
        fecha_creacion=datetime.now()
    )
    db.add(nueva_trans)
    db.commit()

    return {"ok": True, "mensaje": "Plan activado correctamente"}


@router.get('/planes/resultado-pago')
def resultado_pago(request: Request, status: str = "UNKNOWN", ref: str = ""):
    return templates.TemplateResponse("resultado_pago.html", {
        "request": request,
        "status": status,
        "referencia": ref,
        "aprobado": status == "APPROVED",
    })


# ─────────────────────────────────────────────
# FUNCIONES DE APOYO
# ─────────────────────────────────────────────

def enviar_factura_email(email: str, plan: str):
    print(f"\n--- ENVIEXPRESS MAIL SERVER ---")
    print(f"DESTINO: {email}")
    print(f"ASUNTO: Confirmación de Pago - Plan {plan.upper()}")
    print(f"MENSAJE: Gracias por confiar en Enviexpress. Tu plan ya está activo.")
    print(f"--------------------------------\n")