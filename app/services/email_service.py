import smtplib
import os
from email.message import EmailMessage
import token
from dotenv import load_dotenv

load_dotenv()

def enviar_email_recuperacion(email_destino, token):
    link = f"http://127.0.0.1:8080/reset-password?token={token}"
    msg = EmailMessage()
    msg['Subject'] = "Recuperación de Contraseña - EnvíExpress Bogotá"
    msg['From'] = os.getenv("SMTP_USER")
    msg['To'] = email_destino

    html_content = f"""
    <div style="background-color: #ffffff; padding: 30px; border: 2px solid #000; font-family: sans-serif;">
        <h1 style="color: #000000;">EnvíExpress <span style="color: #ff0000;">Bogotá</span></h1>
        <p>Haz clic para restablecer tu contraseña:</p>
        <a href="{link}" style="background-color: #ff0000; color: white; padding: 12px 25px; text-decoration: none; font-weight: bold; border-radius: 5px; display: inline-block;">
            RESTABLECER CONTRASEÑA
        </a>
        <p style="font-size: 11px; color: #666;">Este enlace expira en 15 minutos.</p>
    </div>
    """
    msg.add_alternative(html_content, subtype='html')

    try:
        server = smtplib.SMTP(os.getenv("SMTP_SERVER"), int(os.getenv("SMTP_PORT")))
        server.starttls()
        server.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD"))
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"--- ERROR GMAIL ---: {str(e)}")
        return False