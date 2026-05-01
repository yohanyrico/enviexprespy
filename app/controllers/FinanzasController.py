# app/controllers/FinanzasController.py

from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, extract
from datetime import datetime
from decimal import Decimal

from app.config.database import get_db
from app.models.Usuario import Usuario
from app.models.Transaccion import Transaccion
from app.models.Tarifa import Tarifa
from app.config.templates import templates

router = APIRouter(tags=["Finanzas"])


@router.get("/admin/finanzas")
def panel_finanzas(request: Request, db: Session = Depends(get_db)):
    """
    Panel de Finanzas para el Administrador.
    Muestra resumen global + detalle de todas las transacciones de tipo CARGA (compra de planes).
    """
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login")

    admin = db.query(Usuario).filter(Usuario.id_usuario == user_id).first()
    if not admin or admin.rol != "ADMIN":
        return RedirectResponse(url="/home")

    # --- DETALLE: Todas las transacciones de compra de planes ---
    transacciones = (
        db.query(Transaccion)
        .options(joinedload(Transaccion.usuario))
        .filter(Transaccion.tipo_movimiento == "CARGA")
        .order_by(Transaccion.fecha_creacion.desc())
        .all()
    )

    # --- RESUMEN GLOBAL ---
    total_ingresos = db.query(func.sum(Transaccion.monto)).filter(
        Transaccion.tipo_movimiento == "CARGA"
    ).scalar() or Decimal("0.00")

    total_transacciones = db.query(func.count(Transaccion.id_transaccion)).filter(
        Transaccion.tipo_movimiento == "CARGA"
    ).scalar() or 0

    # Clientes únicos que han comprado al menos un plan
    clientes_activos = db.query(func.count(func.distinct(Transaccion.usuario_id))).filter(
        Transaccion.tipo_movimiento == "CARGA"
    ).scalar() or 0

    # Ingreso promedio por transacción
    promedio_ingreso = (
        (total_ingresos / total_transacciones)
        if total_transacciones > 0
        else Decimal("0.00")
    )

    # Ingresos del mes actual
    now = datetime.now()
    ingresos_mes = db.query(func.sum(Transaccion.monto)).filter(
        Transaccion.tipo_movimiento == "CARGA",
        extract("month", Transaccion.fecha_creacion) == now.month,
        extract("year", Transaccion.fecha_creacion) == now.year,
    ).scalar() or Decimal("0.00")

    # --- DESGLOSE POR PLAN ---
    planes_resumen = {}
    for t in transacciones:
        concepto = t.concepto or ""
        plan = "OTRO"
        for nombre in ["BASICA", "EXPRESS", "NACIONAL"]:
            if nombre in concepto.upper():
                plan = nombre
                break
        if plan not in planes_resumen:
            planes_resumen[plan] = {"cantidad": 0, "total": Decimal("0.00")}
        planes_resumen[plan]["cantidad"] += 1
        planes_resumen[plan]["total"] += t.monto

    def fmt(n):
        return f"${int(n):,}".replace(",", ".")

    return templates.TemplateResponse("finanzas.html", {
        "request": request,
        "usuario": admin,
        "rol": "ADMIN",
        "transacciones": transacciones,
        "total_ingresos": fmt(total_ingresos),
        "total_transacciones": total_transacciones,
        "clientes_activos": clientes_activos,
        "promedio_ingreso": fmt(promedio_ingreso),
        "ingresos_mes": fmt(ingresos_mes),
        "planes_resumen": planes_resumen,
        "fmt": fmt,
        "mes_actual": now.strftime("%B %Y"),
    })