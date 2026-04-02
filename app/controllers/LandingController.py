from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from app.config.templates import templates

router = APIRouter(tags=["Landing"])

@router.get("/")
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})